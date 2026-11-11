"""Animation microservice: FFmpeg, OpenCV and optional ComfyUI video."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from mvstudio_shared.comfyui import ComfyUIClient
from mvstudio_shared.config import get_settings
from mvstudio_shared.media import MediaError
from mvstudio_shared.models import AudioReactiveConfig, BeatEvent, Scene
from mvstudio_shared.storage import AssetCache, ProjectStore, file_sha256, stable_hash
from openstudio_common import create_service_app
from pydantic import BaseModel, Field

from .ai_video import AIVideoConfig, ai_video_available, generate_ai_video
from .ffmpeg_animator import render_ffmpeg
from .opencv_animator import render_opencv

logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("mvstudio.animation")

router = APIRouter(tags=["animation"])


class ComfyUIVideoConfig(BaseModel):
    url: str = ""
    workflow_path: str = ""
    steps: int = Field(default=24, ge=1, le=200)
    cfg: float = Field(default=5.0, ge=0, le=30)
    checkpoint: str = ""
    timeout_seconds: float = Field(default=1800.0, ge=30.0, le=7200.0)


class AnimateRequest(BaseModel):
    project_id: str
    scene: Scene
    image_path: str
    depth_map_path: str | None = None
    width: int = Field(default=1280, ge=256, le=4096)
    height: int = Field(default=720, ge=256, le=4096)
    fps: Literal[24, 25, 30, 60] = 30
    pre_roll: float = Field(default=0.0, ge=0.0, le=5.0)
    extra_tail: float = Field(default=0.3, ge=0.0, le=2.0)
    backend: Literal["ffmpeg", "opencv", "ai"] = "ffmpeg"
    allow_fallback: bool = True
    audio_reactive: AudioReactiveConfig = Field(default_factory=AudioReactiveConfig)
    beats: list[BeatEvent] = Field(default_factory=list)
    particle_color: str = "#F4A261"
    force: bool = False
    comfyui: ComfyUIVideoConfig = Field(default_factory=ComfyUIVideoConfig)


class GeneratedVideo(BaseModel):
    scene_id: int
    path: str
    backend: str
    provider_requested: str
    cached: bool = False
    width: int
    height: int
    fps: int
    duration: float
    clip_duration: float
    cache_key: str
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VideoProviderStatusRequest(BaseModel):
    comfyui_url: str = ""
    workflow_path: str = ""


def _even(value: int) -> int:
    return value - (value % 2)


def _workflow_hash(path: str) -> str:
    if not path:
        return "none"
    try:
        return hashlib.sha256(Path(path).expanduser().read_bytes()).hexdigest()[:16]
    except OSError:
        return "missing"


@router.post("/provider-status")
def provider_status(request: VideoProviderStatusRequest) -> dict:
    url = request.comfyui_url or get_settings().comfyui_url
    client = ComfyUIClient(url)
    available, detail = client.available()
    workflow = request.workflow_path
    return {
        "service": "animation",
        "comfyui_video": {
            "url": url,
            "available": available,
            "detail": detail,
            "workflow_path": workflow,
            "workflow_configured": bool(workflow),
            "workflow_exists": bool(workflow and Path(workflow).expanduser().is_file()),
        },
    }


@router.post("/animate", response_model=GeneratedVideo)
def animate(request: AnimateRequest) -> GeneratedVideo:
    settings = get_settings()
    store = ProjectStore(settings.projects_root)
    try:
        store.load(request.project_id)
        paths = store.paths(request.project_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Project not found: {request.project_id}") from exc

    width = _even(max(256, request.width))
    height = _even(max(256, request.height))
    scene = request.scene
    try:
        image_path = paths.abs(request.image_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail=f"Scene image not found: {request.image_path}")
    depth_map_path = paths.abs(request.depth_map_path) if request.depth_map_path else None
    if depth_map_path and not depth_map_path.is_file():
        depth_map_path = None
    depth_hash = file_sha256(depth_map_path) if depth_map_path else "none"

    clip_duration = round(scene.duration + request.pre_roll + request.extra_tail, 3)
    if clip_duration <= 0.1:
        raise HTTPException(status_code=422, detail="Animation duration must be positive")
    if clip_duration > 190:
        raise HTTPException(status_code=422, detail="Animation clip is too long for one scene")

    beats = [
        beat
        for beat in sorted(request.beats, key=lambda item: item.time)
        if scene.start - request.pre_roll - 0.1 <= beat.time <= scene.end + 2.0
    ]
    image_hash = file_sha256(image_path)
    reactive = request.audio_reactive
    beat_fingerprint = stable_hash(
        [
            (round(beat.time, 3), round(beat.strength, 3), beat.downbeat)
            for beat in beats
            if reactive.enabled
        ]
    )
    cache_payload = {
        "project_id": request.project_id,
        "scene_id": scene.scene_id,
        "image_sha256": image_hash,
        "depth_sha256": depth_hash,
        "start": scene.start,
        "end": scene.end,
        "camera": scene.camera.model_dump(),
        "effects": sorted(scene.visual_effects),
        "seed": scene.seed,
        "width": width,
        "height": height,
        "fps": request.fps,
        "pre_roll": request.pre_roll,
        "extra_tail": request.extra_tail,
        "backend": request.backend,
        "beat_fingerprint": beat_fingerprint,
        "audio_reactive": reactive.model_dump(),
        "particle_color": request.particle_color,
        "generator": "mvstudio-animation-v1",
        "workflow_hash": _workflow_hash(request.comfyui.workflow_path)
        if request.backend == "ai"
        else "none",
    }
    cache = AssetCache(paths)
    cache_key = cache.key(cache_payload)
    cached = None if request.force else cache.get(cache_key)
    if cached:
        entry_path = paths.dir / cached["path"]
        if entry_path.is_file():
            metadata = cached.get("metadata", {})
            return GeneratedVideo(
                scene_id=scene.scene_id,
                path=cached["path"],
                backend=metadata.get("backend", request.backend),
                provider_requested=request.backend,
                cached=True,
                width=int(metadata.get("width", width)),
                height=int(metadata.get("height", height)),
                fps=int(metadata.get("fps", request.fps)),
                duration=float(metadata.get("duration", clip_duration)),
                clip_duration=float(metadata.get("clip_duration", clip_duration)),
                cache_key=cache_key,
                warnings=metadata.get("warnings", []),
                created_at=metadata.get("created_at") or datetime.now(timezone.utc),
            )

    output_filename = f"scene_{scene.scene_id:03d}_{cache_key[:8]}.mp4"
    output_path = paths.videos_dir / output_filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    backend_used = request.backend
    cacheable = True
    details: dict = {}

    try:
        if request.backend == "ai":
            ai_config = AIVideoConfig(
                url=request.comfyui.url or settings.comfyui_url,
                workflow_path=request.comfyui.workflow_path,
                steps=request.comfyui.steps,
                cfg=request.comfyui.cfg,
                checkpoint=request.comfyui.checkpoint,
                timeout_seconds=request.comfyui.timeout_seconds,
            )
            available, reason = ai_video_available(ai_config)
            if not available:
                message = f"AI video generation unavailable: {reason}"
                if not request.allow_fallback:
                    raise HTTPException(status_code=503, detail=message)
                warnings.append(message + " Falling back to FFmpeg procedural animation.")
                backend_used = "ffmpeg"
                cacheable = False
                details = render_ffmpeg(
                    image_path=image_path,
                    output_path=output_path,
                    width=width,
                    height=height,
                    fps=request.fps,
                    clip_duration=clip_duration,
                    scene=scene,
                    beats=beats,
                    clip_start=scene.start - request.pre_roll,
                    audio_reactive=reactive,
                    particle_color=request.particle_color,
                    cache_dir=paths.cache_dir,
                )
            else:
                try:
                    details = generate_ai_video(
                        image_path=image_path,
                        output_path=output_path,
                        scene=scene,
                        width=width,
                        height=height,
                        fps=request.fps,
                        clip_duration=clip_duration,
                        config=ai_config,
                    )
                    backend_used = "comfyui_video"
                except Exception as exc:
                    message = f"ComfyUI video generation failed: {exc}"
                    if not request.allow_fallback:
                        raise HTTPException(status_code=503, detail=message) from exc
                    warnings.append(message + " Falling back to FFmpeg procedural animation.")
                    backend_used = "ffmpeg"
                    cacheable = False
                    details = render_ffmpeg(
                        image_path=image_path,
                        output_path=output_path,
                        width=width,
                        height=height,
                        fps=request.fps,
                        clip_duration=clip_duration,
                        scene=scene,
                        beats=beats,
                        clip_start=scene.start - request.pre_roll,
                        audio_reactive=reactive,
                        particle_color=request.particle_color,
                        cache_dir=paths.cache_dir,
                    )
        elif request.backend == "opencv":
            backend_used = "opencv"
            details = render_opencv(
                image_path=image_path,
                output_path=output_path,
                width=width,
                height=height,
                fps=request.fps,
                clip_duration=clip_duration,
                scene=scene,
                beats=beats,
                clip_start=scene.start - request.pre_roll,
                audio_reactive=reactive,
                depth_map_path=depth_map_path,
                particle_color=request.particle_color,
            )
        else:
            backend_used = "ffmpeg"
            details = render_ffmpeg(
                image_path=image_path,
                output_path=output_path,
                width=width,
                height=height,
                fps=request.fps,
                clip_duration=clip_duration,
                scene=scene,
                beats=beats,
                clip_start=scene.start - request.pre_roll,
                audio_reactive=reactive,
                particle_color=request.particle_color,
                cache_dir=paths.cache_dir,
            )
    except HTTPException:
        raise
    except (MediaError, ValueError) as exc:
        logger.exception("Animation failed for scene %s", scene.scene_id)
        raise HTTPException(status_code=422, detail=f"Animation failed: {exc}") from exc
    except Exception as exc:
        logger.exception("Animation failed for scene %s", scene.scene_id)
        raise HTTPException(status_code=500, detail=f"Animation failed: {exc}") from exc

    relative_path = paths.rel(output_path)
    metadata = {
        "scene_id": scene.scene_id,
        "path": relative_path,
        "backend": backend_used,
        "width": width,
        "height": height,
        "fps": request.fps,
        "duration": details.get("duration", clip_duration),
        "clip_duration": clip_duration,
        "warnings": warnings,
        "details": {key: value for key, value in details.items() if key != "filter_graph"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if cacheable:
        cache.put(cache_key, relative_path, metadata)
    logger.info(
        "Animated scene %s with %s (%.2fs, cacheable=%s)",
        scene.scene_id,
        backend_used,
        clip_duration,
        cacheable,
    )
    return GeneratedVideo(
        scene_id=scene.scene_id,
        path=relative_path,
        backend=backend_used,
        provider_requested=request.backend,
        cached=False,
        width=width,
        height=height,
        fps=request.fps,
        duration=float(details.get("duration", clip_duration)),
        clip_duration=clip_duration,
        cache_key=cache_key,
        warnings=warnings,
        created_at=datetime.now(timezone.utc),
    )


app = create_service_app(
    "video-animation",
    "Open Studio Video Animation",
    "Cinematic camera movement and optional AI image-to-video generation.",
    extra_routers=[router],
)
