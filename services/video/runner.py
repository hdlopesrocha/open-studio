"""Bridge between the central Open Studio job hub and the video pipeline.

Public ``POST /api/video/projects/{id}/run`` calls create a job in the central
job hub (component ``video``). The hub dispatches ``/internal/jobs/run`` here;
this module starts the copied, project-persistent ``JobManager`` job and mirrors
its progress into the central ``JobContext``. The local manager remains an
implementation detail so pause/cancel, per-scene checkpoints and resumability are
preserved without duplicating public jobs.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import mimetypes
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException
from mvstudio_shared.config import get_settings
from mvstudio_shared.models import JobKind, Project, ProjectConfig, utcnow
from mvstudio_shared.storage import ProjectPaths, ProjectStore, read_json
from openstudio_common import JobCancelled, JobContext, JOBHUB_URL, jobhub_headers
from pydantic import ValidationError

from .jobs import JobConflict, JobManager, JobNotFound
from .pipeline import Pipeline, PipelineError

logger = logging.getLogger("mvstudio.video.runner")

ACTION_KINDS: dict[str, JobKind] = {
    "analyze": JobKind.analyze,
    "plan": JobKind.plan,
    "images": JobKind.images,
    "animate": JobKind.animate,
    "render": JobKind.render,
    "full": JobKind.full,
    "regenerate": JobKind.regenerate,
    # Legacy aliases accepted through the internal job endpoint.
    "analyze_audio": JobKind.analyze_audio,
    "analyze_lyrics": JobKind.analyze_lyrics,
    "generate_images": JobKind.generate_images,
    "full_pipeline": JobKind.full_pipeline,
    "regenerate_scene": JobKind.regenerate_scene,
}

ACTION_LABELS = {
    "analyze": "Analyse audio & lyrics",
    "plan": "Plan scenes",
    "images": "Generate scene images",
    "animate": "Animate scenes",
    "render": "Render final video",
    "full": "Full pipeline",
    "regenerate": "Regenerate scenes",
}

ACTION_MESSAGES = {
    "analyze": "Audio and lyric analysis complete",
    "plan": "Scene plan complete",
    "images": "Scene images ready",
    "animate": "Scene animation ready",
    "render": "Final video rendered",
    "full": "Full video pipeline complete",
    "regenerate": "Scenes regenerated",
}


class CentralJobError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


_SUBMIT_LOCK = asyncio.Lock()


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


_OUTPUT_KEYS = {
    "resolution",
    "aspect_ratio",
    "fps",
    "codec",
    "quality",
    "crf",
    "preset",
    "audio_bitrate",
    "burn_subtitles",
    "export_srt",
    "output_filename",
    "output_dir",
}
_SCENE_KEYS = {
    "min_duration",
    "max_duration",
    "target_duration",
    "max_lyric_lines_per_scene",
    "style_id",
    "visual_style_prompt",
    "seed",
    "image_provider",
    "image_width",
    "image_height",
    "animation_backend",
    "variants",
    "generate_depth_maps",
}
_AUDIO_REACTIVE_KEYS = {"enabled", "beat_pulse", "bass_pulse", "beat_cuts", "particles", "intensity"}
_AI_KEYS = {"llm_mode", "marker", "allow_fallback"}


def apply_runtime_config(store: ProjectStore, project: Project, options: dict[str, Any]) -> Project:
    """Apply project-config overrides supplied with a ``/run`` request.

    The UI normally PATCHes the project first. Accepting overrides here makes the
    job API self-contained and keeps every control usable from one request.
    """
    patch: dict[str, Any] = {}
    if isinstance(options.get("config"), dict):
        patch = _deep_merge(patch, options["config"])
    for key in ("output", "scenes", "subtitles", "subtitle_style", "audio_reactive", "ai"):
        value = options.get(key)
        if isinstance(value, dict):
            target = "subtitles" if key == "subtitle_style" else key
            patch = _deep_merge(patch, {target: value})
    direct_output = {key: options[key] for key in _OUTPUT_KEYS if key in options}
    if direct_output:
        patch = _deep_merge(patch, {"output": direct_output})
    direct_scenes = {key: options[key] for key in _SCENE_KEYS if key in options}
    if direct_scenes:
        patch = _deep_merge(patch, {"scenes": direct_scenes})
    direct_reactive = {key: options[key] for key in _AUDIO_REACTIVE_KEYS if key in options}
    if direct_reactive:
        patch = _deep_merge(patch, {"audio_reactive": direct_reactive})
    direct_ai = {key: options[key] for key in _AI_KEYS if key in options}
    if direct_ai:
        patch = _deep_merge(patch, {"ai": direct_ai})
    if not patch:
        return project
    merged = _deep_merge(project.config.model_dump(mode="json"), patch)
    try:
        project.config = ProjectConfig.model_validate(merged)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid project configuration: {exc}") from exc
    return store.save(project)


def _normalise_params(params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    raw = dict(params or {})
    project_id = str(raw.pop("project_id", "") or raw.pop("projectId", "") or "").strip()
    nested = raw.pop("options", None)
    if isinstance(nested, dict):
        options = dict(nested)
        # Keep flat extras too, without letting nested options shadow them.
        for key, value in raw.items():
            options.setdefault(key, value)
    else:
        options = raw
    if not project_id:
        project_id = str(options.pop("project_id", "") or options.pop("projectId", "") or "").strip()
    return project_id, options


def _mime_for(path: Path) -> str:
    suffix = path.suffix.lower()
    explicit = {
        ".mp4": "video/mp4",
        ".mkv": "video/x-matroska",
        ".webm": "video/webm",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".flac": "audio/flac",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".srt": "application/x-subrip",
        ".ass": "text/x-ssa",
        ".json": "application/json",
    }
    return explicit.get(suffix) or mimetypes.guess_type(str(path))[0] or "application/octet-stream"


def _kind_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".mp4", ".mkv", ".webm", ".mov"}:
        return "video"
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return "image"
    if suffix in {".srt", ".ass", ".vtt"}:
        return "subtitle"
    if suffix in {".mp3", ".wav", ".m4a", ".flac"}:
        return "audio"
    if suffix == ".json":
        return "data"
    return "file"


def _file_entry(paths: ProjectPaths, path: Path) -> dict[str, Any] | None:
    try:
        if not path.is_file():
            return None
        relative = paths.files_rel(path)
        if not relative:
            return None
        return {
            "path": relative,
            "kind": _kind_for(path),
            "mime": _mime_for(path),
            "name": path.name,
            "size": path.stat().st_size,
        }
    except OSError:
        return None


def _collect_files(project: Project, paths: ProjectPaths, action: str) -> list[dict[str, Any]]:
    candidates: list[Path] = []
    # Project-level deliverables come first so a scene-heavy project can never
    # truncate the final video/thumbnail from the result file list.
    if project.final_video:
        candidates.append(paths.abs(project.final_video))
    candidates.extend(
        [
            paths.output_dir / "subtitles.srt",
            paths.output_dir / "subtitles.ass",
        ]
    )
    if project.final_thumbnail:
        candidates.append(paths.abs(project.final_thumbnail))
    if project.cover_image:
        candidates.append(paths.abs(project.cover_image))
    document = read_json(paths.scenes_file, default=None) or {}
    scenes = document.get("scenes", []) if isinstance(document, dict) else []
    if action in {"images", "animate", "full", "regenerate"}:
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            if action in {"images", "full", "regenerate"}:
                image = scene.get("image_path")
                if image:
                    candidates.append(paths.abs(image))
                for variant in scene.get("image_variants") or []:
                    if variant:
                        candidates.append(paths.abs(variant))
                thumbnail = scene.get("thumbnail_path")
                if thumbnail:
                    candidates.append(paths.abs(thumbnail))
            if action in {"animate", "full", "regenerate"}:
                video = scene.get("video_path")
                if video:
                    candidates.append(paths.abs(video))
    candidates.extend(
        [
            paths.audio_analysis,
            paths.lyrics_analysis,
            paths.scenes_file,
            paths.visual_context_file,
        ]
    )
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in candidates:
        entry = _file_entry(paths, path)
        if entry and entry["path"] not in seen:
            seen.add(entry["path"])
            files.append(entry)
        if len(files) >= 400:
            break
    # Keep the most user-relevant media first.
    order = {"video": 0, "subtitle": 1, "image": 2, "audio": 3, "data": 4, "file": 5}
    files.sort(key=lambda item: (order.get(item["kind"], 9), item["path"]))
    return files


def _result_payload(project: Project, paths: ProjectPaths, action: str, local_result: dict[str, Any] | None) -> dict[str, Any]:
    local_result = local_result or {}
    video_path = paths.files_rel(paths.abs(project.final_video)) if project.final_video else None
    thumbnail_path = paths.files_rel(paths.abs(project.final_thumbnail)) if project.final_thumbnail else None
    cover_path = paths.files_rel(paths.abs(project.cover_image)) if project.cover_image else None
    subtitles_path = paths.files_rel(paths.output_dir / "subtitles.srt") if (paths.output_dir / "subtitles.srt").is_file() else None
    data = {
        "project_id": project.id,
        "action": action,
        "stage": project.stage,
        "scene_count": project.scene_count,
        "video_path": video_path,
        "final_video": video_path,
        "thumbnail_path": thumbnail_path,
        "cover_path": cover_path,
        "subtitles_path": subtitles_path,
        "duration": project.duration,
        "width": project.width,
        "height": project.height,
        "fps": project.config.output.fps,
        "codec": project.config.output.codec,
        "warnings": project.warnings[-20:],
        "local_result": {
            key: value
            for key, value in local_result.items()
            if key in {"stage", "scene_count", "duration", "width", "height"}
        },
    }
    return data


async def _wait_for_terminal(manager: JobManager, job_id: str, timeout: float = 60.0) -> Any:
    deadline = asyncio.get_running_loop().time() + timeout
    job = manager.get(job_id)
    while not job.is_terminal and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.5)
        try:
            job = manager.get(job_id)
        except JobNotFound:
            break
    return job


def register_handlers(runner: Any, manager: JobManager, pipeline: Pipeline | None, store: ProjectStore) -> None:
    """Register the seven public video actions on an ``openstudio_common.JobRunner``."""

    async def handle(context: JobContext) -> dict[str, Any]:
        action = context.action
        kind = ACTION_KINDS.get(action)
        if kind is None:
            raise HTTPException(status_code=422, detail=f"Unknown video action: {action}")
        project_id, options = _normalise_params(context.params)
        if not project_id:
            raise HTTPException(status_code=422, detail="project_id is required")
        try:
            project = store.load(project_id)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=404, detail=f"Project not found: {project_id}") from exc

        project = apply_runtime_config(store, project, options)
        if manager.active_jobs(project_id):
            raise HTTPException(status_code=409, detail="Another job is already running for this project")

        try:
            local_job = manager.create_job(project_id, kind, options)
        except JobConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Could not start video job: {exc}") from exc

        logger.info("Central job %s started local job %s (%s)", context.job_id, local_job.id, action)
        await context.report(0, action, f"Starting {ACTION_LABELS.get(action, action).lower()}")
        cancel_sent = False
        last_cancel_check = 0.0
        reported_warnings: set[str] = set()
        try:
            while True:
                try:
                    await context.check()
                except JobCancelled:
                    if not cancel_sent:
                        manager.cancel(local_job.id)
                        cancel_sent = True
                    await _wait_for_terminal(manager, local_job.id)
                    raise
                now = asyncio.get_running_loop().time()
                if not cancel_sent and now - last_cancel_check >= 2.5:
                    last_cancel_check = now
                    try:
                        if await context.client.cancelled():
                            manager.cancel(local_job.id)
                            cancel_sent = True
                    except Exception:  # noqa: BLE001 - progress polling must not fail a job
                        pass
                try:
                    current = manager.get(local_job.id)
                except JobNotFound:
                    break
                if cancel_sent:
                    if current.is_terminal:
                        raise JobCancelled("Job cancelled by the user")
                    await asyncio.sleep(0.5)
                    continue
                new_warnings = [item for item in current.warnings if item not in reported_warnings]
                if new_warnings:
                    reported_warnings.update(new_warnings)
                    try:
                        await context.client.progress(warnings=new_warnings)
                    except Exception:  # noqa: BLE001
                        pass
                await context.report(
                    current.progress,
                    current.stage,
                    current.message,
                )
                if current.is_terminal:
                    break
                await asyncio.sleep(1.0)
        except JobCancelled:
            if not cancel_sent:
                manager.cancel(local_job.id)
                await _wait_for_terminal(manager, local_job.id)
            raise
        except asyncio.CancelledError:
            manager.cancel(local_job.id)
            raise

        final_job = manager.get(local_job.id)
        if final_job.status.value == "canceled":
            raise JobCancelled("Job cancelled by the user")
        if final_job.status.value in {"failed", "interrupted"}:
            raise RuntimeError(final_job.error or final_job.message or "Video job failed")

        project = store.load(project_id)
        paths = store.paths(project_id)
        files = _collect_files(project, paths, action)
        data = _result_payload(project, paths, action, final_job.result)
        message = ACTION_MESSAGES.get(action, "Video job complete")
        # Honour a cancellation that arrived while the local job was finishing.
        await context.check()
        await context.report(100, "complete", message)
        logger.info("Local job %s completed; returning %d file(s)", local_job.id, len(files))
        return {"message": message, "files": files, "data": data}

    for action in ("analyze", "plan", "images", "animate", "render", "full", "regenerate"):
        runner.register(action, handle)
    for action in (
        "analyze_audio",
        "analyze_lyrics",
        "generate_images",
        "full_pipeline",
        "regenerate_scene",
    ):
        runner.register(action, handle)


async def _find_active_job(project_id: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0), headers=jobhub_headers()) as client:
        response = await client.get(
            f"{JOBHUB_URL}/api/jobs",
            params={
                "component": "video",
                "status": "queued,running,canceling",
                "limit": 200,
            },
        )
    if response.status_code >= 400:
        return None
    payload = response.json()
    for job in payload.get("items", []):
        params = job.get("params") or {}
        pid = params.get("project_id") or params.get("projectId")
        if str(pid or "") == project_id:
            return job
    return None


async def submit_central_job(
    project: Project,
    action: str,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create exactly one central job-hub job for a project action."""
    if action not in ACTION_KINDS or action not in ACTION_LABELS:
        raise CentralJobError(f"Unknown video action: {action}", status_code=422)
    params = {"project_id": project.id, "options": options or {}}
    title = f"{project.title or project.name} · {ACTION_LABELS.get(action, action)}"
    payload = {"component": "video", "action": action, "title": title, "params": params}
    # Serialise check+create inside this process so a double click cannot race
    # between the active-jobs query and the POST.
    async with _SUBMIT_LOCK:
        try:
            active = await _find_active_job(project.id)
        except Exception as exc:  # noqa: BLE001
            raise CentralJobError(f"Job hub is unavailable: {exc}", status_code=503) from exc
        if active:
            raise CentralJobError(
                f"Another video job is already active for this project (job {active.get('id')})",
                status_code=409,
            )
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                headers=jobhub_headers(),
            ) as client:
                response = await client.post(f"{JOBHUB_URL}/api/jobs", json=payload)
        except Exception as exc:  # noqa: BLE001
            raise CentralJobError(f"Could not submit the job: {exc}", status_code=503) from exc
    if response.status_code >= 400:
        detail = response.text[:1000]
        try:
            detail = response.json().get("detail", detail)
        except Exception:  # noqa: BLE001
            pass
        raise CentralJobError(str(detail), status_code=response.status_code if response.status_code < 500 else 502)
    return response.json()
