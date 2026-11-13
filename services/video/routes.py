"""REST API for the Open Studio video orchestrator.

Public routes are mounted at ``/api/video`` by the shared gateway. Project
metadata stays project-relative on disk; every public payload converts asset
paths to the shared files-relative form used by ``/api/files/raw/<path>``.
"""

from __future__ import annotations

import io
import logging
import mimetypes
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from mvstudio_shared.config import get_settings
from mvstudio_shared.media import MediaError, validate_audio, write_bytes_atomic
from mvstudio_shared.models import (
    AISettings,
    Job,
    JobKind,
    OutputConfig,
    Project,
    ProjectConfig,
    ProjectSummary,
    ReorderRequest,
    Scene,
    SceneDocument,
    ScenePatch,
    SceneRegenerateRequest,
    VisualContext,
)
from mvstudio_shared.srt import parse_srt_file_with_warnings, write_srt_file
from mvstudio_shared.storage import (
    ProjectPaths,
    ProjectStore,
    atomic_write_json,
    make_project_id,
    read_json,
    sanitize_filename,
)
from mvstudio_shared.styles import style_catalogue
from PIL import Image, ImageOps
from pydantic import BaseModel, Field, ValidationError

from .catalog import build_catalog
from .cover import generate_cover
from .jobs import JobConflict, JobNotFound
from .runner import CentralJobError, _find_active_job, submit_central_job
from .system import collect_status, model_inventory

logger = logging.getLogger("mvstudio.video.routes")

router = APIRouter(prefix="/api/video", tags=["video"])

AUDIO_SUFFIXES = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".aiff", ".aif"}


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    title: str | None = Field(default=None, max_length=200)
    artist: str | None = Field(default=None, max_length=200)
    config: ProjectConfig | None = None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    title: str = Field(default="", max_length=200)
    artist: str = Field(default="", max_length=200)
    audio_path: str = Field(min_length=1)
    srt_path: str = Field(min_length=1)
    config: ProjectConfig | None = None


class JobOptions(BaseModel):
    scene_ids: list[int] | None = None
    force: bool = False
    skip_images: bool = False
    skip_animation: bool = False
    output: OutputConfig | None = None
    animation: bool = True
    image: bool = True
    variant: int = Field(default=0, ge=0, le=32)
    variants: int = Field(default=1, ge=1, le=4)
    prompt: str | None = None
    negative_prompt: str | None = None


class JobCreateRequest(BaseModel):
    kind: JobKind
    options: JobOptions = Field(default_factory=JobOptions)


class RunRequest(BaseModel):
    action: str = Field(min_length=1, max_length=40)
    options: dict[str, Any] = Field(default_factory=dict)


class SceneImageSelect(BaseModel):
    path: str


def _state(request: Request) -> tuple[ProjectStore, Any, Any, Any]:
    app = request.app
    return app.state.store, app.state.ai_store, app.state.client, app.state.jobs


def _get_project(store: ProjectStore, project_id: str) -> Project:
    try:
        return store.load(project_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}") from exc


def _get_plan(store: ProjectStore, project_id: str) -> tuple[SceneDocument, VisualContext]:
    paths = store.paths(project_id)
    data = read_json(paths.scenes_file)
    context_data = read_json(paths.visual_context_file)
    if not data or not context_data:
        raise HTTPException(status_code=404, detail="No scene plan found for this project")
    try:
        return SceneDocument.model_validate(data), VisualContext.model_validate(context_data)
    except ValidationError as exc:
        raise HTTPException(status_code=500, detail=f"Corrupt scene plan: {exc}") from exc


def _save_plan(store: ProjectStore, project_id: str, document: SceneDocument) -> None:
    paths = store.paths(project_id)
    document.updated_at = datetime.now(timezone.utc)
    atomic_write_json(paths.scenes_file, document.model_dump(mode="json"))


def _invalidate_video(scene: Scene) -> None:
    scene.video_path = None
    scene.status = "image_ready" if scene.image_path else "planned"


def _to_files(paths: ProjectPaths, value: str | None) -> str | None:
    if not value:
        return None
    try:
        candidate = Path(str(value))
        resolved = candidate if candidate.is_absolute() else paths.abs(candidate)
        return paths.files_rel(resolved)
    except Exception:  # noqa: BLE001
        return str(value)


def _public_project(project: Project, store: ProjectStore) -> dict[str, Any]:
    paths = store.paths(project.id)
    data = project.model_dump(mode="json")
    for key in ("audio_path", "srt_path", "final_video", "final_thumbnail", "cover_image"):
        data[key] = _to_files(paths, data.get(key))
    if project.final_video_external:
        external = Path(project.final_video_external)
        try:
            data["final_video_external"] = paths.files_rel(external)
        except Exception:  # noqa: BLE001
            data["final_video_external"] = project.final_video_external
    return data


def _public_summary(summary: ProjectSummary, store: ProjectStore) -> dict[str, Any]:
    data = summary.model_dump(mode="json")
    if summary.cover_image:
        data["cover_image"] = _to_files(store.paths(summary.id), summary.cover_image)
    if summary.final_video:
        data["final_video"] = _to_files(store.paths(summary.id), summary.final_video)
    return data


def _public_scene(scene: Scene, paths: ProjectPaths) -> dict[str, Any]:
    data = scene.model_dump(mode="json")
    for key in ("image_path", "thumbnail_path", "depth_map_path", "video_path"):
        data[key] = _to_files(paths, data.get(key))
    data["image_variants"] = [
        converted
        for converted in (_to_files(paths, value) for value in scene.image_variants)
        if converted
    ]
    return data


def _public_document(document: SceneDocument, paths: ProjectPaths) -> dict[str, Any]:
    data = document.model_dump(mode="json")
    data["scenes"] = [_public_scene(scene, paths) for scene in document.scenes]
    return data


def _plan_response(
    document: SceneDocument,
    context: VisualContext,
    paths: ProjectPaths,
) -> dict[str, Any]:
    return {
        "scene_document": _public_document(document, paths),
        "visual_context": context.model_dump(mode="json"),
    }


async def _save_upload(upload: UploadFile, target: Path, max_bytes: int) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        with target.open("wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Upload exceeds the {max_bytes // (1024 * 1024)} MB limit",
                    )
                handle.write(chunk)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    if size == 0:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="The uploaded file is empty")
    return size


def _form_text(form: Any, key: str, default: str = "") -> str:
    value = form.get(key)
    if value is None or hasattr(value, "read"):
        return default
    return str(value)


def _resolve_input_file(value: str, allowed_suffixes: set[str], label: str) -> Path:
    settings = get_settings()
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = settings.files_root / value
    candidate = candidate.resolve()
    try:
        candidate.relative_to(settings.files_root.resolve())
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"{label} path must be inside the shared files root",
        ) from exc
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"{label} file not found: {value}")
    if candidate.suffix.lower() not in allowed_suffixes:
        raise HTTPException(status_code=422, detail=f"Unsupported {label} format: {candidate.suffix}")
    return candidate


def _validate_sources(audio_target: Path, srt_target: Path) -> tuple[dict[str, Any], list[str]]:
    try:
        audio_info = validate_audio(audio_target)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"The audio file is not readable: {exc}") from exc
    try:
        cues, srt_warnings = parse_srt_file_with_warnings(srt_target)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"The SRT file is not readable: {exc}") from exc
    if not cues:
        raise HTTPException(status_code=422, detail="The SRT file contains no usable subtitle cues")
    if max(cue.end for cue in cues) > audio_info["duration"] + 2.0:
        srt_warnings.append(
            "Subtitle timings extend beyond the end of the audio. Original timestamps were preserved."
        )
    return audio_info, srt_warnings


def _finish_create(
    store: ProjectStore,
    project_id: str,
    paths: ProjectPaths,
    name: str,
    title: str,
    artist: str,
    audio_target: Path,
    srt_target: Path,
    audio_filename: str,
    srt_filename: str,
    project_config: ProjectConfig,
    audio_info: dict[str, Any],
    srt_warnings: list[str],
) -> dict[str, Any]:
    project = Project(
        id=project_id,
        name=name.strip(),
        title=title.strip() or name.strip(),
        artist=artist.strip(),
        duration=audio_info["duration"],
        audio_path=paths.rel(audio_target),
        srt_path=paths.rel(srt_target),
        audio_filename=sanitize_filename(audio_filename or audio_target.name),
        srt_filename=sanitize_filename(srt_filename or srt_target.name),
        config=project_config,
        stage="created",
        status="idle",
        warnings=list(dict.fromkeys(srt_warnings)),
    )
    store.create(project)
    cover_path = paths.thumbnails_dir / "cover.jpg"
    try:
        generate_cover(project, cover_path)
        project.cover_image = paths.rel(cover_path)
        store.save(project)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cover generation failed: %s", exc)
    return _public_project(project, store)


def _config_from_text(value: str | None) -> ProjectConfig:
    if not value or not value.strip():
        return ProjectConfig()
    try:
        return ProjectConfig.model_validate_json(value)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid project configuration: {exc}") from exc


# ---------------------------------------------------------------------------
# Health, catalogue and system
# ---------------------------------------------------------------------------


@router.get("/catalog")
def catalog(request: Request, live: bool = False) -> dict[str, Any]:
    _store, ai_store, _client, _jobs = _state(request)
    payload = build_catalog(ai_store)
    if live:
        # Optional slow path: probes Ollama and ComfyUI for installed models.
        payload["live_models"] = model_inventory(ai_store)
    return payload


@router.get("/styles")
def styles() -> list[dict[str, Any]]:
    return style_catalogue()


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    store, ai_store, client, jobs = _state(request)
    return collect_status(
        store=store,
        client=client,
        manager=jobs,
        ai_store=ai_store,
        started_at=request.app.state.started_at,
        uptime_seconds=time.time() - request.app.state.started_at,
    )


@router.get("/system")
def system_status(request: Request) -> dict[str, Any]:
    return status(request)


@router.get("/settings/ai", response_model=AISettings)
def get_ai_settings(request: Request) -> AISettings:
    _store, ai_store, _client, _jobs = _state(request)
    return ai_store.load()


@router.put("/settings/ai", response_model=AISettings)
def update_ai_settings(payload: AISettings, request: Request) -> AISettings:
    _store, ai_store, _client, _jobs = _state(request)
    return ai_store.save(payload)


@router.get("/ai/models")
def ai_models(request: Request) -> dict[str, Any]:
    _store, ai_store, _client, _jobs = _state(request)
    return model_inventory(ai_store)


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@router.get("/projects")
def list_projects(request: Request) -> list[dict[str, Any]]:
    store, _ai, _client, _jobs = _state(request)
    return [_public_summary(summary, store) for summary in store.list()]


@router.post("/projects", status_code=201)
async def create_project(request: Request) -> dict[str, Any]:
    store, _ai_store, _client, _jobs = _state(request)
    settings = get_settings()
    content_type = (request.headers.get("content-type") or "").lower()

    if "application/json" in content_type:
        try:
            payload = ProjectCreate.model_validate(await request.json())
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid project payload: {exc}") from exc
        audio_source = _resolve_input_file(payload.audio_path, AUDIO_SUFFIXES, "audio")
        srt_source = _resolve_input_file(payload.srt_path, {".srt"}, "subtitle")
        project_config = payload.config or ProjectConfig()
        project_id = make_project_id(payload.name)
        paths = store.paths(project_id)
        try:
            paths.ensure()
            audio_suffix = audio_source.suffix.lower()
            audio_target = paths.input_dir / f"music{audio_suffix}"
            srt_target = paths.input_dir / "lyrics.srt"
            max_bytes = settings.max_upload_mb * 1024 * 1024
            if audio_source.stat().st_size > max_bytes or srt_source.stat().st_size > max_bytes:
                raise HTTPException(status_code=413, detail="Input file exceeds the upload limit")
            shutil.copy2(audio_source, audio_target)
            shutil.copy2(srt_source, srt_target)
            audio_info, srt_warnings = _validate_sources(audio_target, srt_target)
            return _finish_create(
                store,
                project_id,
                paths,
                payload.name,
                payload.title,
                payload.artist,
                audio_target,
                srt_target,
                audio_source.name,
                srt_source.name,
                project_config,
                audio_info,
                srt_warnings,
            )
        except HTTPException:
            shutil.rmtree(paths.dir, ignore_errors=True)
            raise
        except Exception as exc:  # noqa: BLE001
            shutil.rmtree(paths.dir, ignore_errors=True)
            raise HTTPException(status_code=500, detail=f"Could not create project: {exc}") from exc

    if "multipart/form-data" not in content_type and "application/x-www-form-urlencoded" not in content_type:
        raise HTTPException(
            status_code=415,
            detail="Use application/json with audio_path/srt_path or multipart with audio and srt files",
        )

    try:
        form = await request.form()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Invalid multipart payload: {exc}") from exc
    name = _form_text(form, "name").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Project name is required")
    title = _form_text(form, "title")
    artist = _form_text(form, "artist")
    project_config = _config_from_text(_form_text(form, "config") or None)
    audio = form.get("audio")
    srt = form.get("srt")
    if audio is None or not hasattr(audio, "read") or srt is None or not hasattr(srt, "read"):
        raise HTTPException(status_code=422, detail="Both audio and srt files are required")

    audio_suffix = Path(getattr(audio, "filename", "") or "").suffix.lower()
    if audio_suffix not in AUDIO_SUFFIXES:
        raise HTTPException(
            status_code=422,
            detail="Unsupported audio format. Use MP3, WAV, FLAC, M4A, AAC, OGG, Opus or AIFF.",
        )
    srt_suffix = Path(getattr(srt, "filename", "") or "").suffix.lower()
    if srt_suffix != ".srt":
        raise HTTPException(status_code=422, detail="Lyrics must be an .srt subtitle file")

    project_id = make_project_id(name)
    paths = store.paths(project_id)
    try:
        paths.ensure()
        audio_target = paths.input_dir / f"music{audio_suffix}"
        srt_target = paths.input_dir / "lyrics.srt"
        max_bytes = settings.max_upload_mb * 1024 * 1024
        await _save_upload(audio, audio_target, max_bytes)
        await _save_upload(srt, srt_target, max_bytes)
        audio_info, srt_warnings = _validate_sources(audio_target, srt_target)
        return _finish_create(
            store,
            project_id,
            paths,
            name,
            title,
            artist,
            audio_target,
            srt_target,
            getattr(audio, "filename", "") or audio_target.name,
            getattr(srt, "filename", "") or srt_target.name,
            project_config,
            audio_info,
            srt_warnings,
        )
    except HTTPException:
        shutil.rmtree(paths.dir, ignore_errors=True)
        raise
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(paths.dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Could not create project: {exc}") from exc


@router.get("/projects/{project_id}")
def get_project(project_id: str, request: Request) -> dict[str, Any]:
    store, _ai, _client, _jobs = _state(request)
    project = _get_project(store, project_id)
    return _public_project(project, store)


@router.patch("/projects/{project_id}")
def update_project(project_id: str, payload: ProjectUpdate, request: Request) -> dict[str, Any]:
    store, _ai, _client, jobs = _state(request)
    project = _get_project(store, project_id)
    if jobs.active_jobs(project_id):
        raise HTTPException(status_code=409, detail="Wait for the active job to finish or cancel it first")
    if payload.name is not None:
        project.name = payload.name.strip()
    if payload.title is not None:
        project.title = payload.title.strip()
    if payload.artist is not None:
        project.artist = payload.artist.strip()
    old_output = project.config.output
    if payload.config is not None:
        new_output = payload.config.output
        dims_changed = (
            old_output.width != new_output.width
            or old_output.height != new_output.height
            or old_output.fps != new_output.fps
            or old_output.aspect_ratio != new_output.aspect_ratio
            or old_output.resolution != new_output.resolution
        )
        project.config = payload.config
        if dims_changed:
            project.warnings = (
                project.warnings
                + ["Output settings changed; re-render the video to apply the new resolution or frame rate."]
            )[-40:]
    if any(value is not None for value in (payload.title, payload.artist, payload.name, payload.config)):
        paths = store.paths(project_id)
        try:
            try:
                _document, context = _get_plan(store, project_id)
            except HTTPException:
                context = None
            generate_cover(project, paths.thumbnails_dir / "cover.jpg", context)
            project.cover_image = paths.rel(paths.thumbnails_dir / "cover.jpg")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cover regeneration failed: %s", exc)
    store.save(project)
    return _public_project(project, store)


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(project_id: str, request: Request) -> None:
    store, _ai, _client, jobs = _state(request)
    _get_project(store, project_id)
    if jobs.active_jobs(project_id):
        raise HTTPException(status_code=409, detail="Cancel the active job before deleting the project")
    try:
        central_active = await _find_active_job(project_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Could not verify active video jobs: {exc}") from exc
    if central_active:
        raise HTTPException(
            status_code=409,
            detail="A central video job is active for this project. Cancel it before deleting.",
        )
    try:
        store.delete(project_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not delete project: {exc}") from exc


# ---------------------------------------------------------------------------
# Analysis and plan reads
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/analysis/audio")
def get_audio_analysis(project_id: str, request: Request) -> Any:
    store, _ai, _client, _jobs = _state(request)
    _get_project(store, project_id)
    return read_json(store.paths(project_id).audio_analysis)


@router.get("/projects/{project_id}/analysis/lyrics")
def get_lyrics_analysis(project_id: str, request: Request) -> Any:
    store, _ai, _client, _jobs = _state(request)
    _get_project(store, project_id)
    return read_json(store.paths(project_id).lyrics_analysis)


@router.get("/projects/{project_id}/analysis/events")
def get_musical_events(project_id: str, request: Request) -> Any:
    store, _ai, _client, _jobs = _state(request)
    _get_project(store, project_id)
    return read_json(store.paths(project_id).musical_events)


@router.get("/projects/{project_id}/plan")
def get_plan(project_id: str, request: Request) -> dict[str, Any]:
    store, _ai, _client, _jobs = _state(request)
    _get_project(store, project_id)
    document, context = _get_plan(store, project_id)
    return _plan_response(document, context, store.paths(project_id))


@router.get("/projects/{project_id}/scenes")
def get_scenes(project_id: str, request: Request) -> dict[str, Any]:
    store, _ai, _client, _jobs = _state(request)
    _get_project(store, project_id)
    document, _context = _get_plan(store, project_id)
    return _public_document(document, store.paths(project_id))


@router.put("/projects/{project_id}/scenes/{scene_id}")
def update_scene(project_id: str, scene_id: int, patch: ScenePatch, request: Request) -> dict[str, Any]:
    store, _ai, _client, jobs = _state(request)
    project = _get_project(store, project_id)
    if jobs.active_jobs(project_id):
        raise HTTPException(status_code=409, detail="Wait for the active job to finish before editing scenes")
    document, context = _get_plan(store, project_id)
    ordered = sorted(document.scenes, key=lambda scene: scene.start)
    target = next((scene for scene in ordered if scene.scene_id == scene_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Scene {scene_id} not found")
    index = ordered.index(target)
    paths = store.paths(project_id)
    fields_set = patch.model_fields_set
    affected_videos: set[int] = set()
    timeline_changed = False

    if "start" in fields_set and patch.start is not None:
        expected_start = 0.0 if index == 0 else ordered[index - 1].end
        if abs(patch.start - expected_start) > 0.02:
            raise HTTPException(
                status_code=422,
                detail=(
                    "A scene start is fixed by the previous scene. Change this scene's end "
                    "or the previous scene's duration instead."
                ),
            )
    if "end" in fields_set and patch.end is not None:
        new_end = round(patch.end, 3)
        if new_end <= target.start + 0.4:
            raise HTTPException(status_code=422, detail="Scene duration must be at least 0.4 seconds")
        if index < len(ordered) - 1:
            following = ordered[index + 1]
            if new_end >= following.end - 0.4:
                raise HTTPException(status_code=422, detail="Scene end leaves the following scene too short")
            if abs(new_end - target.end) > 0.001:
                target.end = new_end
                following.start = new_end
                timeline_changed = True
                affected_videos.update({target.scene_id, following.scene_id})
                if index > 0:
                    affected_videos.add(ordered[index - 1].scene_id)
        else:
            if new_end > project.duration + 0.05:
                raise HTTPException(
                    status_code=422,
                    detail="The final scene cannot extend beyond the audio duration",
                )
            if abs(new_end - target.end) > 0.001:
                target.end = new_end
                timeline_changed = True
                affected_videos.add(target.scene_id)
                if index > 0:
                    affected_videos.add(ordered[index - 1].scene_id)

    simple_fields = {
        "description": "description",
        "visual_prompt": "visual_prompt",
        "negative_prompt": "negative_prompt",
        "camera": "camera",
        "transition": "transition",
        "visual_effects": "visual_effects",
        "lyrics": "lyrics",
        "seed": "seed",
    }
    for field, attribute in simple_fields.items():
        if field in fields_set and getattr(patch, field) is not None:
            setattr(target, attribute, getattr(patch, field))
            if field in {"camera", "visual_effects", "transition", "seed"}:
                affected_videos.add(target.scene_id)
                if field == "transition" and index < len(ordered) - 1:
                    affected_videos.add(ordered[index + 1].scene_id)
    if "depth_map_path" in fields_set:
        raw = patch.depth_map_path
        if raw is None or not str(raw).strip():
            target.depth_map_path = None
        else:
            relative = paths.to_project_rel(raw)
            if not relative or not paths.abs(relative).is_file():
                raise HTTPException(status_code=404, detail="The depth map file does not exist")
            target.depth_map_path = relative
        affected_videos.add(target.scene_id)
    for affected_id in affected_videos:
        scene = next((item for item in document.scenes if item.scene_id == affected_id), None)
        if scene:
            _invalidate_video(scene)
    if target.end <= target.start:
        raise HTTPException(status_code=422, detail="Scene must end after it starts")
    if timeline_changed:
        project.warnings = (
            project.warnings
            + ["Scene timing changed. Re-animate the affected scenes before rendering."]
        )[-40:]
        project.stage = "assets_ready"
    if affected_videos:
        project.stage = "assets_ready"
    project.status = "idle"
    _save_plan(store, project_id, document)
    store.save(project)
    return _plan_response(document, context, paths)


@router.post("/projects/{project_id}/scenes/reorder")
def reorder_scenes(project_id: str, payload: ReorderRequest, request: Request) -> dict[str, Any]:
    store, _ai, _client, jobs = _state(request)
    project = _get_project(store, project_id)
    if jobs.active_jobs(project_id):
        raise HTTPException(status_code=409, detail="Wait for the active job to finish before editing scenes")
    document, context = _get_plan(store, project_id)
    paths = store.paths(project_id)
    ordered = sorted(document.scenes, key=lambda scene: scene.start)
    ids = [scene.scene_id for scene in ordered]
    if sorted(payload.scene_ids) != sorted(ids):
        raise HTTPException(status_code=422, detail="Reorder request must include every scene exactly once")
    source_by_id = {scene.scene_id: scene for scene in ordered}
    content_fields = [
        "lyrics",
        "description",
        "visual_prompt",
        "negative_prompt",
        "camera",
        "visual_effects",
        "section_id",
        "section_kind",
        "section_label",
        "subtitle_indices",
        "energy",
        "seed",
        "image_path",
        "image_source",
        "image_variants",
        "depth_map_path",
        "thumbnail_path",
    ]
    import copy

    sources = [source_by_id[scene_id] for scene_id in payload.scene_ids]
    for slot, source in zip(ordered, sources):
        for field in content_fields:
            setattr(slot, field, copy.deepcopy(getattr(source, field)))
        slot.video_path = None
        slot.status = "image_ready" if slot.image_path else "planned"
    project.stage = "assets_ready"
    project.status = "idle"
    project.warnings = (
        project.warnings
        + ["Scenes reordered. Timings were preserved; re-animate and re-render the video."]
    )[-40:]
    _save_plan(store, project_id, document)
    store.save(project)
    return _plan_response(document, context, paths)


@router.post("/projects/{project_id}/scenes/{scene_id}/image")
async def upload_scene_image(
    project_id: str,
    scene_id: int,
    request: Request,
    image: UploadFile = File(...),
) -> dict[str, Any]:
    store, _ai, _client, jobs = _state(request)
    project = _get_project(store, project_id)
    if jobs.active_jobs(project_id):
        raise HTTPException(status_code=409, detail="Wait for the active job to finish before uploading assets")
    document, context = _get_plan(store, project_id)
    paths = store.paths(project_id)
    scene = next((item for item in document.scenes if item.scene_id == scene_id), None)
    if scene is None:
        raise HTTPException(status_code=404, detail=f"Scene {scene_id} not found")
    max_bytes = 80 * 1024 * 1024
    data = await image.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail="Image exceeds the 80 MB limit")
    if not data:
        raise HTTPException(status_code=422, detail="The uploaded image is empty")
    try:
        with Image.open(io.BytesIO(data)) as incoming:
            incoming.load()
            if incoming.width * incoming.height > 80_000_000:
                raise HTTPException(status_code=422, detail="Image dimensions are too large")
            rendered = ImageOps.exif_transpose(incoming).convert("RGB")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Unreadable image: {exc}") from exc
    stem = f"user_scene_{scene_id:03d}_{uuid.uuid4().hex[:8]}"
    image_path = paths.images_dir / f"{stem}.png"
    thumb_path = paths.thumbnails_dir / f"{stem}.jpg"
    buffer = io.BytesIO()
    rendered.save(buffer, format="PNG", optimize=True)
    write_bytes_atomic(image_path, buffer.getvalue())
    thumb = rendered.copy()
    thumb.thumbnail((640, 640))
    thumb_buffer = io.BytesIO()
    thumb.save(thumb_buffer, format="JPEG", quality=86, optimize=True)
    write_bytes_atomic(thumb_path, thumb_buffer.getvalue())
    scene.image_path = paths.rel(image_path)
    scene.thumbnail_path = paths.rel(thumb_path)
    scene.image_source = "user"
    scene.image_variants = list(dict.fromkeys(scene.image_variants + [scene.image_path]))
    _invalidate_video(scene)
    document.updated_at = datetime.now(timezone.utc)
    _save_plan(store, project_id, document)
    project.stage = "assets_ready"
    project.status = "idle"
    store.save(project)
    return _plan_response(document, context, paths)


@router.post("/projects/{project_id}/scenes/{scene_id}/depth-map")
async def upload_scene_depth_map(
    project_id: str,
    scene_id: int,
    request: Request,
    image: UploadFile = File(...),
) -> dict[str, Any]:
    store, _ai, _client, jobs = _state(request)
    project = _get_project(store, project_id)
    if jobs.active_jobs(project_id):
        raise HTTPException(status_code=409, detail="Wait for the active job to finish before uploading assets")
    document, context = _get_plan(store, project_id)
    paths = store.paths(project_id)
    scene = next((item for item in document.scenes if item.scene_id == scene_id), None)
    if scene is None:
        raise HTTPException(status_code=404, detail=f"Scene {scene_id} not found")
    data = await image.read(80 * 1024 * 1024 + 1)
    if len(data) > 80 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Depth map exceeds the 80 MB limit")
    if not data:
        raise HTTPException(status_code=422, detail="The uploaded depth map is empty")
    try:
        with Image.open(io.BytesIO(data)) as incoming:
            incoming.load()
            if incoming.width * incoming.height > 80_000_000:
                raise HTTPException(status_code=422, detail="Depth map dimensions are too large")
            depth = incoming.convert("L")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Unreadable depth map: {exc}") from exc
    target = paths.depth_dir / f"scene_{scene_id:03d}_depth_{uuid.uuid4().hex[:8]}.png"
    buffer = io.BytesIO()
    depth.save(buffer, format="PNG", optimize=True)
    write_bytes_atomic(target, buffer.getvalue())
    scene.depth_map_path = paths.rel(target)
    _invalidate_video(scene)
    document.updated_at = datetime.now(timezone.utc)
    _save_plan(store, project_id, document)
    project.stage = "assets_ready"
    project.status = "idle"
    store.save(project)
    return _plan_response(document, context, paths)


@router.post("/projects/{project_id}/scenes/{scene_id}/select-image")
def select_scene_image(
    project_id: str,
    scene_id: int,
    payload: SceneImageSelect,
    request: Request,
) -> dict[str, Any]:
    store, _ai, _client, jobs = _state(request)
    project = _get_project(store, project_id)
    if jobs.active_jobs(project_id):
        raise HTTPException(status_code=409, detail="Wait for the active job to finish before editing scenes")
    document, context = _get_plan(store, project_id)
    paths = store.paths(project_id)
    scene = next((item for item in document.scenes if item.scene_id == scene_id), None)
    if scene is None:
        raise HTTPException(status_code=404, detail=f"Scene {scene_id} not found")
    selected: str | None = None
    for variant in scene.image_variants:
        if payload.path in {variant, paths.files_rel(paths.abs(variant))}:
            selected = variant
            break
    if selected is None:
        raise HTTPException(status_code=422, detail="The selected image is not a variant of this scene")
    image_path = paths.abs(selected)
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="The selected image file no longer exists")
    scene.image_path = selected
    scene.thumbnail_path = None
    _invalidate_video(scene)
    _save_plan(store, project_id, document)
    project.stage = "assets_ready"
    project.status = "idle"
    store.save(project)
    return _plan_response(document, context, paths)


@router.get("/projects/{project_id}/scenes/{scene_id}/images")
def list_scene_images(project_id: str, scene_id: int, request: Request) -> dict[str, Any]:
    store, _ai, _client, _jobs = _state(request)
    _get_project(store, project_id)
    document, _context = _get_plan(store, project_id)
    paths = store.paths(project_id)
    scene = next((item for item in document.scenes if item.scene_id == scene_id), None)
    if scene is None:
        raise HTTPException(status_code=404, detail=f"Scene {scene_id} not found")
    items = []
    for relative in scene.image_variants:
        path = paths.abs(relative)
        if path.is_file():
            public = paths.files_rel(path)
            items.append(
                {
                    "path": public,
                    "url": f"/api/files/raw/{public}",
                    "selected": relative == scene.image_path,
                }
            )
    return {"scene_id": scene_id, "images": items, "items": items, "total": len(items)}


@router.post("/projects/{project_id}/scenes/{scene_id}/regenerate")
def regenerate_scene(
    project_id: str,
    scene_id: int,
    payload: SceneRegenerateRequest,
    request: Request,
) -> dict[str, Any]:
    store, _ai, _client, jobs = _state(request)
    project = _get_project(store, project_id)
    document, _context = _get_plan(store, project_id)
    scene = next((item for item in document.scenes if item.scene_id == scene_id), None)
    if scene is None:
        raise HTTPException(status_code=404, detail=f"Scene {scene_id} not found")
    if payload.prompt is not None:
        scene.visual_prompt = payload.prompt.strip()
        _save_plan(store, project_id, document)
        store.save(project)
    options = {
        "scene_ids": [scene_id],
        "force": True,
        "image": payload.image,
        "animation": payload.animation,
        "variants": payload.variants,
        "variant": 0,
    }
    try:
        job = jobs.create_job(project_id, JobKind.regenerate, options)
    except JobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return job.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Public job submission (central job hub) + local compatibility jobs
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/run")
async def run_project(project_id: str, payload: RunRequest, request: Request) -> dict[str, Any]:
    store, _ai, _client, jobs = _state(request)
    project = _get_project(store, project_id)
    if jobs.active_jobs(project_id):
        raise HTTPException(status_code=409, detail="Another local video job is already running for this project")
    try:
        return await submit_central_job(project, payload.action, payload.options)
    except CentralJobError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/projects/{project_id}/jobs")
def create_job(project_id: str, payload: JobCreateRequest, request: Request) -> dict[str, Any]:
    store, _ai, _client, jobs = _state(request)
    _get_project(store, project_id)
    options = payload.options.model_dump(exclude_none=True)
    try:
        job = jobs.create_job(project_id, payload.kind, options)
    except JobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return job.model_dump(mode="json")


@router.post("/projects/{project_id}/jobs/{kind}")
def create_job_by_kind(
    project_id: str,
    kind: str,
    request: Request,
    payload: JobOptions | None = None,
) -> dict[str, Any]:
    store, _ai, _client, jobs = _state(request)
    _get_project(store, project_id)
    try:
        job_kind = JobKind(kind)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Unknown job kind: {kind}") from exc
    options = (payload or JobOptions()).model_dump(exclude_none=True)
    try:
        job = jobs.create_job(project_id, job_kind, options)
    except JobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return job.model_dump(mode="json")


@router.get("/projects/{project_id}/jobs")
def list_jobs(project_id: str, request: Request, limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    store, _ai, _client, jobs = _state(request)
    _get_project(store, project_id)
    return [job.model_dump(mode="json") for job in jobs.project_jobs(project_id, limit=limit)]


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> dict[str, Any]:
    _store, _ai, _client, jobs = _state(request)
    try:
        return jobs.get(job_id).model_dump(mode="json")
    except JobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request) -> dict[str, Any]:
    _store, _ai, _client, jobs = _state(request)
    try:
        return jobs.cancel(job_id).model_dump(mode="json")
    except JobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/pause")
def pause_job(job_id: str, request: Request) -> dict[str, Any]:
    _store, _ai, _client, jobs = _state(request)
    try:
        return jobs.pause(job_id).model_dump(mode="json")
    except JobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except JobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/resume")
def resume_job(job_id: str, request: Request) -> dict[str, Any]:
    _store, _ai, _client, jobs = _state(request)
    try:
        return jobs.resume(job_id).model_dump(mode="json")
    except JobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except JobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, request: Request) -> dict[str, Any]:
    _store, _ai, _client, jobs = _state(request)
    try:
        return jobs.retry(job_id).model_dump(mode="json")
    except JobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except JobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Files and assets
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/audio")
def get_audio(project_id: str, request: Request, download: bool = False) -> FileResponse:
    store, _ai, _client, _jobs = _state(request)
    project = _get_project(store, project_id)
    audio_path = store.paths(project_id).abs(project.audio_path)
    if not audio_path.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found")
    media_type = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
    return FileResponse(audio_path, media_type=media_type, filename=audio_path.name if download else None)


@router.get("/projects/{project_id}/video")
def get_video(project_id: str, request: Request, download: bool = False) -> FileResponse:
    store, _ai, _client, _jobs = _state(request)
    project = _get_project(store, project_id)
    if not project.final_video:
        raise HTTPException(status_code=404, detail="No rendered video yet")
    video_path = store.paths(project_id).abs(project.final_video)
    if not video_path.is_file():
        raise HTTPException(status_code=404, detail="The rendered video file is missing")
    media = "video/x-matroska" if video_path.suffix.lower() == ".mkv" else "video/mp4"
    return FileResponse(video_path, media_type=media, filename=video_path.name if download else None)


@router.get("/projects/{project_id}/subtitles")
def get_subtitles(project_id: str, request: Request, download: bool = True) -> FileResponse:
    store, _ai, _client, _jobs = _state(request)
    project = _get_project(store, project_id)
    paths = store.paths(project_id)
    srt_target = paths.output_dir / "subtitles.srt"
    source = paths.abs(project.srt_path)
    if not source.is_file():
        raise HTTPException(status_code=404, detail="Source subtitle file not found")
    lines, _warnings = parse_srt_file_with_warnings(source)
    write_srt_file(lines, srt_target)
    return FileResponse(
        srt_target,
        media_type="application/x-subrip",
        filename="subtitles.srt" if download else None,
    )


@router.get("/projects/{project_id}/assets")
def list_assets(project_id: str, request: Request) -> dict[str, Any]:
    store, _ai, _client, _jobs = _state(request)
    _get_project(store, project_id)
    paths = store.paths(project_id)
    groups: dict[str, list[dict[str, Any]]] = {}
    flat: list[dict[str, Any]] = []
    directories = {
        "input": paths.input_dir,
        "images": paths.images_dir,
        "videos": paths.videos_dir,
        "thumbnails": paths.thumbnails_dir,
        "depth": paths.depth_dir,
        "output": paths.output_dir,
    }
    for group, directory in directories.items():
        items: list[dict[str, Any]] = []
        if directory.is_dir():
            for path in sorted(directory.iterdir()):
                if not path.is_file():
                    continue
                public = paths.files_rel(path)
                item = {
                    "path": public,
                    "name": path.name,
                    "kind": group,
                    "size": path.stat().st_size,
                    "modified_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
                    "url": f"/api/files/raw/{public}",
                }
                items.append(item)
                flat.append(item)
        groups[group] = items
    flat.sort(key=lambda item: item["path"])
    return {
        "project_id": project_id,
        "assets": groups,
        "items": flat,
        "total": len(flat),
    }
