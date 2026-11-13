"""End-to-end processing pipeline driven by gateway jobs."""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

from mvstudio_shared.config import get_settings
from mvstudio_shared.models import (
    AISettings,
    AudioAnalysis,
    CameraMove,
    Job,
    JobKind,
    LyricsAnalysis,
    MusicalEvent,
    MusicalEventCollection,
    OutputConfig,
    PlanResult,
    Project,
    SceneDocument,
    TransitionPlan,
    VisualContext,
    utcnow,
)
from mvstudio_shared.storage import (
    ProjectPaths,
    ProjectStore,
    atomic_write_json,
    ensure_within_roots,
    read_json,
)
from mvstudio_shared.timeline import effective_transition_duration
from pydantic import ValidationError

from .clients import ServiceClient, ServiceError
from .cover import generate_cover
from .jobs import JobContext
from .settings_store import AISettingsStore

logger = logging.getLogger("mvstudio.video.pipeline")


class PipelineError(RuntimeError):
    pass


class StageProgress:
    def __init__(self, context: JobContext, start: float, end: float):
        self.context = context
        self.start = start
        self.end = end

    def percent(self, local: float) -> float:
        local = max(0.0, min(100.0, local))
        return round(self.start + (self.end - self.start) * (local / 100.0), 1)

    def update(
        self,
        local: float,
        stage: str,
        message: str,
        *,
        current_scene: int | None = None,
        scene_total: int | None = None,
    ) -> None:
        self.context.update(
            progress=self.percent(local),
            stage=stage,
            message=message,
            current_scene=current_scene,
            scene_total=scene_total,
        )


def _load_model(path: Path, model: Any) -> Any | None:
    data = read_json(path)
    if data is None:
        return None
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise PipelineError(f"Corrupt project file {path.name}: {exc}") from exc


class Pipeline:
    def __init__(
        self,
        store: ProjectStore,
        client: ServiceClient,
        ai_store: AISettingsStore,
    ):
        self.store = store
        self.client = client
        self.ai_store = ai_store
        self.settings = get_settings()

    # ------------------------------------------------------------------
    # Artefacts
    # ------------------------------------------------------------------
    def _load_audio(self, paths: ProjectPaths) -> AudioAnalysis | None:
        return _load_model(paths.audio_analysis, AudioAnalysis)

    def _load_lyrics(self, paths: ProjectPaths) -> LyricsAnalysis | None:
        return _load_model(paths.lyrics_analysis, LyricsAnalysis)

    def _load_plan(self, paths: ProjectPaths, project_id: str) -> tuple[SceneDocument | None, VisualContext | None]:
        scenes = _load_model(paths.scenes_file, SceneDocument)
        context = _load_model(paths.visual_context_file, VisualContext)
        if scenes and scenes.project_id != project_id:
            raise PipelineError("The scene plan belongs to a different project")
        return scenes, context

    @staticmethod
    def _musical_events(audio: AudioAnalysis) -> MusicalEventCollection:
        events: list[MusicalEvent] = []
        for beat in audio.beats:
            events.append(
                MusicalEvent(
                    time=beat.time,
                    type="downbeat" if beat.downbeat else "beat",
                    label="Downbeat" if beat.downbeat else "Beat",
                    energy=min(1.0, float(beat.strength)),
                )
            )
        for section in audio.sections:
            events.append(
                MusicalEvent(
                    time=section.start,
                    end=section.end,
                    type="section",
                    label=f"{section.label} ({section.kind})",
                    energy=min(1.0, float(section.energy)),
                )
            )
        # A manageable number of onsets for the UI and future effect work.
        for onset in audio.onsets[:1500]:
            events.append(
                MusicalEvent(
                    time=onset.time,
                    type="onset",
                    label="Onset",
                    energy=min(1.0, float(onset.strength)),
                )
            )
        events.sort(key=lambda item: item.time)
        return MusicalEventCollection(
            duration=audio.duration,
            tempo=audio.tempo,
            events=events,
        )

    def _save_plan(self, paths: ProjectPaths, project_id: str, result: PlanResult) -> SceneDocument:
        document = SceneDocument(
            project_id=project_id,
            scenes=result.scenes,
            warnings=list(dict.fromkeys(result.warnings)),
            planner=result.planner,
            updated_at=utcnow(),
        )
        atomic_write_json(paths.scenes_file, document.model_dump(mode="json"))
        atomic_write_json(paths.visual_context_file, result.visual_context.model_dump(mode="json"))
        return document

    # ------------------------------------------------------------------
    # AI / service configuration
    # ------------------------------------------------------------------
    def _ai_payload(self, ai: AISettings) -> dict[str, Any]:
        return ai.model_dump(mode="json")

    def _image_provider(self, project: Project) -> str:
        return project.config.scenes.image_provider

    # ------------------------------------------------------------------
    # Returned-asset normalisation
    # ------------------------------------------------------------------
    def _resolve_returned_path(self, paths: ProjectPaths, value: str | None) -> Path | None:
        """Resolve a path returned by a downstream service.

        Accepts absolute paths, project-relative paths and files-relative paths.
        """
        if not value:
            return None
        raw = str(value).strip()
        if not raw:
            return None
        candidate = Path(raw)
        if candidate.is_absolute():
            return candidate.resolve() if candidate.is_file() else None
        for base in (paths.dir, self.settings.files_root):
            possible = (base / raw).resolve()
            if possible.is_file():
                return possible
        return None

    def _ensure_project_asset(
        self,
        paths: ProjectPaths,
        value: str | None,
        target_dir: Path,
        stem: str,
        default_suffix: str,
    ) -> str | None:
        """Copy an external asset into the project and return a project-relative path."""
        source = self._resolve_returned_path(paths, value)
        if source is None:
            return None
        try:
            source.relative_to(paths.dir.resolve())
            return paths.rel(source)
        except ValueError:
            pass
        suffix = source.suffix.lower() or default_suffix
        target = target_dir / f"{stem}{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return paths.rel(target)

    def _make_thumbnail(self, paths: ProjectPaths, project_relative: str, stem: str) -> str | None:
        source = paths.abs(project_relative)
        if not source.is_file():
            return None
        try:
            from PIL import Image

            target = paths.thumbnails_dir / f"{stem}.jpg"
            target.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(source) as incoming:
                thumb = incoming.convert("RGB")
                thumb.thumbnail((480, 480))
                thumb.save(target, format="JPEG", quality=86, optimize=True)
            return paths.rel(target)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not create thumbnail for %s: %s", project_relative, exc)
            return None

    def _ingest_generated_image(
        self,
        paths: ProjectPaths,
        result: dict[str, Any],
        scene_id: int,
        variant: int,
    ) -> tuple[str, str | None, str, list[str]]:
        """Copy/normalise an image returned by the shared imagegen service."""
        stem = f"scene_{scene_id:03d}_v{variant}_{uuid.uuid4().hex[:8]}"
        image_relative = self._ensure_project_asset(
            paths,
            result.get("path"),
            paths.images_dir,
            stem,
            ".png",
        )
        if not image_relative:
            raise PipelineError(
                f"Image generation for scene {scene_id} returned no readable image "
                f"(path={result.get('path')!r})"
            )
        thumbnail_relative = self._ensure_project_asset(
            paths,
            result.get("thumbnail_path"),
            paths.thumbnails_dir,
            stem,
            ".jpg",
        )
        thumbnail_relative = thumbnail_relative or self._make_thumbnail(paths, image_relative, stem)
        source = str(result.get("source") or "procedural").lower()
        if source not in {"procedural", "comfyui", "qvac", "diffusers", "user"}:
            source = "procedural"
        warnings = [str(item) for item in result.get("warnings", []) if item]
        return image_relative, thumbnail_relative, source, warnings

    def _ingest_animated_clip(
        self,
        paths: ProjectPaths,
        result: dict[str, Any],
        scene_id: int,
    ) -> tuple[str, list[str]]:
        stem = f"scene_{scene_id:03d}_{uuid.uuid4().hex[:8]}"
        video_relative = self._ensure_project_asset(
            paths,
            result.get("path"),
            paths.videos_dir,
            stem,
            ".mp4",
        )
        if not video_relative:
            raise PipelineError(
                f"Animation for scene {scene_id} returned no readable clip "
                f"(path={result.get('path')!r})"
            )
        warnings = [str(item) for item in result.get("warnings", []) if item]
        return video_relative, warnings

    def _apply_regenerate_overrides(
        self,
        paths: ProjectPaths,
        scene_ids: list[int],
        options: dict[str, Any],
    ) -> None:
        document, _context = self._load_plan(paths, paths.project_id)
        if document is None:
            raise PipelineError("No scene plan found. Generate the story plan first.")
        selected = set(scene_ids)
        changed = False
        for scene in document.scenes:
            if selected and scene.scene_id not in selected:
                continue
            prompt = options.get("prompt") or options.get("visual_prompt")
            if isinstance(prompt, str) and prompt.strip():
                scene.visual_prompt = prompt.strip()
                changed = True
            negative = options.get("negative_prompt")
            if isinstance(negative, str):
                scene.negative_prompt = negative.strip()
                changed = True
            if isinstance(options.get("camera"), dict):
                scene.camera = CameraMove.model_validate(options["camera"])
                changed = True
            if isinstance(options.get("transition"), dict):
                scene.transition = TransitionPlan.model_validate(options["transition"])
                changed = True
            if isinstance(options.get("visual_effects"), list):
                scene.visual_effects = [str(item) for item in options["visual_effects"]]
                changed = True
            if options.get("seed") is not None:
                scene.seed = int(options["seed"])
                changed = True
        if changed:
            document.updated_at = utcnow()
            atomic_write_json(paths.scenes_file, document.model_dump(mode="json"))

    # ------------------------------------------------------------------
    # Job dispatch
    # ------------------------------------------------------------------
    def run(self, context: JobContext, job: Job) -> dict[str, Any]:
        project = self.store.load(job.project_id)
        options = job.options or {}
        if job.kind == JobKind.analyze:
            self.analyze_audio(context, project, options, (2, 50))
            project = self.store.load(project.id)
            self.analyze_lyrics(context, project, options, (50, 98))
        elif job.kind == JobKind.analyze_audio:
            self.analyze_audio(context, project, options, (2, 98))
        elif job.kind == JobKind.analyze_lyrics:
            self.analyze_lyrics(context, project, options, (2, 98))
        elif job.kind == JobKind.plan:
            self.plan(context, project, options, (2, 98))
        elif job.kind in {JobKind.images, JobKind.generate_images}:
            self.generate_images(context, project, options, (2, 98))
        elif job.kind == JobKind.animate:
            self.animate(context, project, options, (2, 98))
        elif job.kind == JobKind.render:
            self.render(context, project, options, (2, 99))
        elif job.kind in {JobKind.regenerate, JobKind.regenerate_scene}:
            paths = self.store.paths(project.id)
            document, _context = self._load_plan(paths, project.id)
            if document is None:
                raise PipelineError("No scene plan found. Generate the story plan first.")
            scene_ids = [int(item) for item in (options.get("scene_ids") or [])]
            if not scene_ids:
                scene_ids = [scene.scene_id for scene in document.scenes]
            if not scene_ids:
                raise PipelineError("Regenerate requires at least one scene")
            self._apply_regenerate_overrides(paths, scene_ids, options)
            if options.get("image", True):
                image_options = {**options, "scene_ids": scene_ids, "force": True}
                self.generate_images(context, project, image_options, (2, 50))
                project = self.store.load(project.id)
            if options.get("animation", True):
                animation_options = {**options, "scene_ids": scene_ids, "force": True}
                self.animate(context, project, animation_options, (50, 98))
        elif job.kind in {JobKind.full, JobKind.full_pipeline}:
            project = self.store.load(project.id)
            project.warnings = []
            self.store.save(project)
            self.analyze_audio(context, project, options, (2, 14))
            project = self.store.load(project.id)
            self.analyze_lyrics(context, project, options, (14, 22))
            project = self.store.load(project.id)
            self.plan(context, project, options, (22, 34))
            project = self.store.load(project.id)
            if not options.get("skip_images"):
                self.generate_images(context, project, options, (34, 62))
            project = self.store.load(project.id)
            if not options.get("skip_animation"):
                self.animate(context, project, options, (62, 90))
            project = self.store.load(project.id)
            self.render(context, project, options, (90, 99))
        else:
            raise PipelineError(f"Unsupported job kind: {job.kind}")
        final_project = self.store.load(project.id)
        return {
            "project_id": final_project.id,
            "stage": final_project.stage,
            "scene_count": final_project.scene_count,
            "final_video": final_project.final_video,
            "final_video_external": final_project.final_video_external,
            "final_thumbnail": final_project.final_thumbnail,
            "cover_image": final_project.cover_image,
            "duration": final_project.duration,
            "width": final_project.width,
            "height": final_project.height,
            "warnings": final_project.warnings[-20:],
        }

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------
    def analyze_audio(
        self, context: JobContext, project: Project, options: dict[str, Any], progress_range: tuple[float, float]
    ) -> AudioAnalysis:
        progress = StageProgress(context, *progress_range)
        paths = self.store.paths(project.id)
        audio_path = paths.abs(project.audio_path)
        if not audio_path.is_file():
            raise PipelineError("Project audio file is missing")
        progress.update(1, "audio", "Sending audio to the analysis service")
        context.checkpoint()
        try:
            result = self.client.post(
                "audio",
                "/analyze",
                {"audio_path": str(audio_path), "sample_rate": 22050},
                timeout=1800,
            )
        except ServiceError as exc:
            raise PipelineError(f"Audio analysis failed: {exc.message}") from exc
        context.checkpoint()
        analysis = AudioAnalysis.model_validate(result)
        atomic_write_json(paths.audio_analysis, analysis.model_dump(mode="json"))
        atomic_write_json(
            paths.musical_events,
            self._musical_events(analysis).model_dump(mode="json"),
        )
        warnings = list(dict.fromkeys(analysis.warnings))
        for warning in warnings:
            context.warn(warning)
        project.duration = analysis.duration
        if project.stage in {"created", "analyzed"}:
            project.stage = "analyzed" if paths.lyrics_analysis.is_file() else "created"
        project.status = "processing"
        project.warnings = list(dict.fromkeys(project.warnings + warnings))[-40:]
        self.store.save(project)
        progress.update(
            100,
            "audio",
            f"Audio analysed: {analysis.duration:.1f}s, {analysis.tempo:.0f} BPM, {len(analysis.beats)} beats",
        )
        return analysis

    # ------------------------------------------------------------------
    # Lyrics
    # ------------------------------------------------------------------
    def analyze_lyrics(
        self, context: JobContext, project: Project, options: dict[str, Any], progress_range: tuple[float, float]
    ) -> LyricsAnalysis:
        progress = StageProgress(context, *progress_range)
        paths = self.store.paths(project.id)
        srt_path = paths.abs(project.srt_path)
        if not srt_path.is_file():
            raise PipelineError("Project subtitle file is missing")
        audio = self._load_audio(paths)
        progress.update(1, "lyrics", "Parsing subtitles and detecting lyric structure")
        context.checkpoint()
        payload: dict[str, Any] = {
            "srt_path": str(srt_path),
            "gap_threshold": 6.0,
        }
        if audio:
            payload["audio_analysis"] = audio.model_dump(mode="json")
        try:
            result = self.client.post("lyrics", "/analyze", payload, timeout=300)
        except ServiceError as exc:
            raise PipelineError(f"Lyrics analysis failed: {exc.message}") from exc
        context.checkpoint()
        analysis = LyricsAnalysis.model_validate(result)
        atomic_write_json(paths.lyrics_analysis, analysis.model_dump(mode="json"))
        for warning in list(dict.fromkeys(analysis.warnings)):
            context.warn(warning)
        if project.stage in {"created", "analyzed"}:
            project.stage = "analyzed" if paths.audio_analysis.is_file() else "created"
        project.status = "processing"
        project.warnings = list(dict.fromkeys(project.warnings + analysis.warnings))[-40:]
        self.store.save(project)
        progress.update(
            100,
            "lyrics",
            f"Lyrics analysed: {len(analysis.lines)} cues, {len(analysis.sections)} sections, language {analysis.language}",
        )
        return analysis

    # ------------------------------------------------------------------
    # Story planning
    # ------------------------------------------------------------------
    def plan(
        self, context: JobContext, project: Project, options: dict[str, Any], progress_range: tuple[float, float]
    ) -> PlanResult:
        progress = StageProgress(context, *progress_range)
        paths = self.store.paths(project.id)
        audio = self._load_audio(paths)
        lyrics = self._load_lyrics(paths)
        if lyrics is None:
            raise PipelineError("Lyrics analysis is required before story planning (run Analyze lyrics)")
        progress.update(4, "planning", "Building a structure-aware scene plan")
        context.checkpoint()
        ai = self.ai_store.load()
        payload = {
            "project_id": project.id,
            "project_name": project.name,
            "title": project.title,
            "artist": project.artist,
            "audio_analysis": audio.model_dump(mode="json") if audio else None,
            "lyrics_analysis": lyrics.model_dump(mode="json"),
            "config": project.config.model_dump(mode="json"),
            "ai_settings": self._ai_payload(ai),
        }
        try:
            result = self.client.post("planner", "/plan", payload, timeout=900)
        except ServiceError as exc:
            raise PipelineError(f"Story planning failed: {exc.message}") from exc
        context.checkpoint()
        plan = PlanResult.model_validate(result)
        document = self._save_plan(paths, project.id, plan)
        project.scene_count = len(plan.scenes)
        project.planner = plan.planner
        project.stage = "planned"
        project.status = "processing"
        stale_markers = (
            "scene planning was used",
            "scene descriptions enhanced with local ollama",
            "ollama returned too few usable scene updates",
            "ollama scene enhancement is capped",
            "ollama request failed:",
            "ollama is not reachable",
            "ollama is running but model",
        )
        project.warnings = [
            warning
            for warning in project.warnings
            if not any(marker in warning.lower() for marker in stale_markers)
        ]
        project.warnings = list(dict.fromkeys(project.warnings + plan.warnings))[-40:]
        cover_path = paths.thumbnails_dir / "cover.jpg"
        try:
            generate_cover(project, cover_path, plan.visual_context)
            project.cover_image = paths.rel(cover_path)
        except Exception as exc:
            logger.warning("Could not generate project cover: %s", exc)
        self.store.save(project)
        for warning in list(dict.fromkeys(plan.warnings)):
            context.warn(warning)
        progress.update(
            100,
            "planning",
            f"Planned {len(document.scenes)} scenes with {plan.planner} planning",
        )
        return plan

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------
    def generate_images(
        self, context: JobContext, project: Project, options: dict[str, Any], progress_range: tuple[float, float]
    ) -> SceneDocument:
        progress = StageProgress(context, *progress_range)
        paths = self.store.paths(project.id)
        document, visual_context = self._load_plan(paths, project.id)
        if document is None or visual_context is None:
            raise PipelineError("No scene plan found. Generate the story plan first.")
        selected = {int(item) for item in (options.get("scene_ids") or [])}
        force = bool(options.get("force"))
        variant_start = max(0, int(options.get("variant") or 0))
        variant_count = max(1, min(4, int(options.get("variants") or 1)))
        ai = self.ai_store.load()
        width = project.config.scenes.image_width or project.config.output.width
        height = project.config.scenes.image_height or project.config.output.height
        scenes = sorted(document.scenes, key=lambda scene: scene.start)
        targets = [scene for scene in scenes if not selected or scene.scene_id in selected]
        if not targets:
            raise PipelineError("No matching scenes to generate")
        completed = 0
        for scene in scenes:
            if selected and scene.scene_id not in selected:
                continue
            context.checkpoint()
            if not force and scene.image_path:
                image_file = paths.abs(scene.image_path)
                if image_file.is_file() and scene.image_source in {
                    "user",
                    "procedural",
                    "comfyui",
                    "qvac",
                    "diffusers",
                }:
                    completed += 1
                    progress.update(
                        2 + 96 * completed / max(1, len(targets)),
                        "images",
                        f"Scene {scene.scene_id}: using cached image",
                        current_scene=scene.scene_id,
                        scene_total=len(targets),
                    )
                    continue
            reference_image = None
            for other in scenes:
                if other.scene_id == scene.scene_id or not other.image_path:
                    continue
                other_path = paths.abs(other.image_path)
                if other_path.is_file() and other.image_source in {
                    "procedural",
                    "comfyui",
                    "qvac",
                    "diffusers",
                    "user",
                }:
                    reference_image = str(other_path)
                    break
            generated_any = False
            for variant_offset in range(variant_count):
                context.checkpoint()
                variant = variant_start + variant_offset
                progress.update(
                    2 + 94 * (completed + variant_offset / variant_count) / max(1, len(targets)),
                    "images",
                    f"Generating image for scene {scene.scene_id} (variant {variant + 1})",
                    current_scene=scene.scene_id,
                    scene_total=len(targets),
                )
                payload = {
                    "project_id": project.id,
                    "scene": scene.model_dump(mode="json"),
                    "visual_context": visual_context.model_dump(mode="json"),
                    "width": width,
                    "height": height,
                    "provider": project.config.scenes.image_provider,
                    "variant": variant,
                    "force": force,
                    "allow_fallback": project.config.ai.allow_fallback,
                    "comfyui": {
                        "url": ai.comfyui_url,
                        "workflow_path": ai.image_workflow_path,
                        "steps": ai.image_steps,
                        "cfg": ai.image_cfg,
                        "checkpoint": ai.image_checkpoint,
                        "reference_image_path": reference_image,
                    },
                }
                try:
                    result = self.client.post("images", "/generate", payload, timeout=1200)
                except ServiceError as exc:
                    raise PipelineError(
                        f"Image generation failed for scene {scene.scene_id}: {exc.message}"
                    ) from exc
                context.checkpoint()
                image_relative, thumbnail_relative, source, warnings = self._ingest_generated_image(
                    paths, result, scene.scene_id, variant
                )
                if not generated_any or not scene.image_path:
                    scene.image_path = image_relative
                scene.image_source = source  # type: ignore[assignment]
                scene.thumbnail_path = thumbnail_relative
                if image_relative not in scene.image_variants:
                    scene.image_variants.append(image_relative)
                scene.status = "image_ready"
                # A new image invalidates the previous animated clip.
                scene.video_path = None
                generated_any = True
                for warning in warnings:
                    context.warn(warning)
                document.updated_at = utcnow()
                atomic_write_json(paths.scenes_file, document.model_dump(mode="json"))
            completed += 1
            progress.update(
                2 + 94 * completed / max(1, len(targets)),
                "images",
                f"Scene {scene.scene_id}: {scene.image_source} image ready",
                current_scene=scene.scene_id,
                scene_total=len(targets),
            )
        fresh = self.store.load(project.id)
        fresh.stage = "assets_ready"
        fresh.status = "processing"
        fresh.warnings = list(dict.fromkeys(fresh.warnings + project.warnings))[-40:]
        self.store.save(fresh)
        progress.update(100, "images", f"Image assets ready for {completed} scene(s)")
        return document

    # ------------------------------------------------------------------
    # Animation
    # ------------------------------------------------------------------
    def animate(
        self, context: JobContext, project: Project, options: dict[str, Any], progress_range: tuple[float, float]
    ) -> SceneDocument:
        progress = StageProgress(context, *progress_range)
        paths = self.store.paths(project.id)
        document, visual_context = self._load_plan(paths, project.id)
        if document is None or visual_context is None:
            raise PipelineError("No scene plan found. Generate the story plan first.")
        audio = self._load_audio(paths)
        beats = audio.beats if audio else []
        selected = set(options.get("scene_ids") or [])
        force = bool(options.get("force"))
        ai = self.ai_store.load()
        ordered = sorted(document.scenes, key=lambda scene: scene.start)
        targets = [scene for scene in ordered if not selected or scene.scene_id in selected]
        if not targets:
            raise PipelineError("No matching scenes to animate")
        particle_color = visual_context.palette[-2] if len(visual_context.palette) > 1 else "#F4A261"
        completed = 0
        for index, scene in enumerate(ordered):
            if selected and scene.scene_id not in selected:
                continue
            context.checkpoint()
            if not scene.image_path:
                raise PipelineError(f"Scene {scene.scene_id} has no image to animate")
            image_path = paths.abs(scene.image_path)
            if not image_path.is_file():
                raise PipelineError(f"Scene {scene.scene_id} image is missing")
            if not force and scene.video_path and paths.abs(scene.video_path).is_file():
                completed += 1
                progress.update(
                    2 + 94 * completed / max(1, len(targets)),
                    "animation",
                    f"Scene {scene.scene_id}: using cached clip",
                    current_scene=scene.scene_id,
                    scene_total=len(targets),
                )
                continue
            order_index = index
            pre_roll = 0.0
            if order_index > 0:
                pre_roll = effective_transition_duration(ordered[order_index - 1], scene)
            progress.update(
                2 + 92 * completed / max(1, len(targets)),
                "animation",
                f"Animating scene {scene.scene_id} ({project.config.scenes.animation_backend})",
                current_scene=scene.scene_id,
                scene_total=len(targets),
            )
            payload = {
                "project_id": project.id,
                "scene": scene.model_dump(mode="json"),
                "image_path": scene.image_path,
                "depth_map_path": scene.depth_map_path,
                "width": project.config.output.width,
                "height": project.config.output.height,
                "fps": project.config.output.fps,
                "pre_roll": pre_roll,
                "extra_tail": 0.35,
                "backend": project.config.scenes.animation_backend,
                "allow_fallback": project.config.ai.allow_fallback,
                "audio_reactive": project.config.audio_reactive.model_dump(mode="json"),
                "beats": [beat.model_dump(mode="json") for beat in beats],
                "particle_color": particle_color,
                "force": force,
                "comfyui": {
                    "url": ai.comfyui_url,
                    "workflow_path": ai.video_workflow_path,
                    "steps": ai.video_steps,
                    "cfg": ai.video_cfg,
                    "checkpoint": ai.video_checkpoint,
                },
            }
            try:
                result = self.client.post("animation", "/animate", payload, timeout=7200)
            except ServiceError as exc:
                raise PipelineError(
                    f"Animation failed for scene {scene.scene_id}: {exc.message}"
                ) from exc
            context.checkpoint()
            video_relative, animation_warnings = self._ingest_animated_clip(
                paths, result, scene.scene_id
            )
            scene.video_path = video_relative
            scene.status = "animated"
            for warning in animation_warnings:
                context.warn(str(warning))
            document.updated_at = utcnow()
            atomic_write_json(paths.scenes_file, document.model_dump(mode="json"))
            completed += 1
            progress.update(
                2 + 94 * completed / max(1, len(targets)),
                "animation",
                f"Scene {scene.scene_id}: clip ready ({result.get('backend')})",
                current_scene=scene.scene_id,
                scene_total=len(targets),
            )
        fresh = self.store.load(project.id)
        fresh.stage = "animated"
        fresh.status = "processing"
        fresh.warnings = list(dict.fromkeys(fresh.warnings + project.warnings))[-40:]
        self.store.save(fresh)
        progress.update(100, "animation", f"Animated {completed} scene(s)")
        return document

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------
    def render(
        self, context: JobContext, project: Project, options: dict[str, Any], progress_range: tuple[float, float]
    ) -> dict[str, Any]:
        progress = StageProgress(context, *progress_range)
        paths = self.store.paths(project.id)
        document, visual_context = self._load_plan(paths, project.id)
        if document is None:
            raise PipelineError("No scene plan found. Generate the story plan first.")
        if not document.scenes:
            raise PipelineError("The scene plan is empty")
        output = project.config.output
        if options.get("output"):
            try:
                output = OutputConfig.model_validate(options["output"])
            except ValidationError as exc:
                raise PipelineError(f"Invalid output settings: {exc}") from exc
            project.config.output = output
            self.store.save(project)
        missing = [
            scene.scene_id
            for scene in document.scenes
            if not scene.video_path or not paths.abs(scene.video_path).is_file()
        ]
        if missing:
            raise PipelineError(
                "Some scenes have no animated clip: "
                + ", ".join(str(scene_id) for scene_id in missing[:10])
                + ". Run the animation step first."
            )
        progress.update(4, "render", "Assembling scenes, music, transitions and subtitles")
        context.checkpoint()
        payload = {
            "project_id": project.id,
            "scenes": [scene.model_dump(mode="json") for scene in document.scenes],
            "audio_path": project.audio_path,
            "subtitle_path": project.srt_path,
            "output": output.model_dump(mode="json"),
            "subtitle_style": project.config.subtitles.model_dump(mode="json"),
            "title": project.title or project.name,
        }
        try:
            result = self.client.post("renderer", "/render", payload, timeout=7200)
        except ServiceError as exc:
            raise PipelineError(f"Video rendering failed: {exc.message}") from exc
        context.checkpoint()
        video_relative = self._ensure_project_asset(
            paths,
            result.get("video_path"),
            paths.output_dir,
            f"final_{uuid.uuid4().hex[:8]}",
            ".mp4",
        )
        if not video_relative:
            raise PipelineError("Rendering completed but returned no readable video file")
        result["video_path"] = video_relative
        srt_relative = self._ensure_project_asset(
            paths,
            result.get("srt_path"),
            paths.output_dir,
            "subtitles",
            ".srt",
        )
        if srt_relative:
            result["srt_path"] = srt_relative
        thumbnail_relative = self._ensure_project_asset(
            paths,
            result.get("thumbnail_path"),
            paths.thumbnails_dir,
            f"final_{uuid.uuid4().hex[:8]}",
            ".jpg",
        )
        if thumbnail_relative:
            result["thumbnail_path"] = thumbnail_relative
        project.final_video = video_relative
        project.final_thumbnail = thumbnail_relative
        project.stage = "rendered"
        project.status = "processing"
        for warning in result.get("warnings", []):
            context.warn(str(warning))
        external = self._export_to_external_dir(project, paths, output, result, context)
        fresh = self.store.load(project.id)
        fresh.final_video = project.final_video
        fresh.final_thumbnail = project.final_thumbnail
        fresh.final_video_external = external
        fresh.stage = "rendered"
        fresh.status = "processing"
        fresh.warnings = list(dict.fromkeys(fresh.warnings + project.warnings))[-40:]
        self.store.save(fresh)
        progress.update(
            100,
            "render",
            f"Rendered {result.get('duration', 0):.1f}s {output.width}x{output.height} video",
        )
        return result

    def _export_to_external_dir(
        self,
        project: Project,
        paths: ProjectPaths,
        output: OutputConfig,
        result: dict[str, Any],
        context: JobContext,
    ) -> str | None:
        requested = (output.output_dir or "").strip()
        if not requested:
            return None
        try:
            settings = get_settings()
            if Path(requested).is_absolute():
                destination_dir = Path(requested).expanduser().resolve()
            elif requested.replace("\\", "/").startswith("video/"):
                destination_dir = (settings.files_root / requested).resolve()
            else:
                # Relative export folders are created inside the component's
                # dedicated exports tree, never inside the project directory.
                relative = requested.replace("\\", "/")
                if relative.startswith("exports/"):
                    relative = relative[len("exports/") :]
                destination_dir = (settings.exports_root / relative).resolve()
            if not settings.allow_external_output:
                ensure_within_roots(destination_dir, settings.allowed_output_roots)
            destination_dir.mkdir(parents=True, exist_ok=True)
            if not destination_dir.is_dir():
                raise OSError("Output path is not a directory")
            source_video = paths.abs(result["video_path"])
            destination_video = destination_dir / source_video.name
            shutil.copy2(source_video, destination_video)
            if output.export_srt and result.get("srt_path"):
                source_srt = paths.abs(result["srt_path"])
                shutil.copy2(source_srt, destination_dir / source_srt.name)
            return str(destination_video)
        except Exception as exc:
            context.warn(f"Could not export to the chosen output directory: {exc}")
            return None


def build_runner(store: ProjectStore, client: ServiceClient, ai_store: AISettingsStore):
    pipeline = Pipeline(store, client, ai_store)

    def runner(context: JobContext, job: Job) -> dict[str, Any]:
        return pipeline.run(context, job)

    return runner
