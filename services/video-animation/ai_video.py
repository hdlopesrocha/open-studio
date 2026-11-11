"""Optional ComfyUI image-to-video generation with graceful fallback."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from mvstudio_shared.comfyui import ComfyUIClient, ComfyUIUnavailable
from mvstudio_shared.media import (
    MediaError,
    probe_duration,
    probe_media,
    run_ffmpeg,
    write_bytes_atomic,
)
from mvstudio_shared.models import Scene


class AIVideoConfig:
    def __init__(
        self,
        *,
        url: str,
        workflow_path: str,
        steps: int = 24,
        cfg: float = 5.0,
        checkpoint: str = "",
        timeout_seconds: float = 1800.0,
    ):
        self.url = url
        self.workflow_path = workflow_path
        self.steps = steps
        self.cfg = cfg
        self.checkpoint = checkpoint
        self.timeout_seconds = timeout_seconds


def ai_video_available(config: AIVideoConfig) -> tuple[bool, str]:
    if not config.workflow_path:
        return False, "No ComfyUI video workflow is configured."
    if not Path(config.workflow_path).expanduser().is_file():
        return False, f"ComfyUI video workflow file not found: {config.workflow_path}"
    return ComfyUIClient(config.url).available()


def generate_ai_video(
    *,
    image_path: Path,
    output_path: Path,
    scene: Scene,
    width: int,
    height: int,
    fps: int,
    clip_duration: float,
    config: AIVideoConfig,
) -> dict:
    """Generate and normalise an AI video clip.

    Raises ComfyUIUnavailable/ComfyUIError/MediaError on failure. The caller is
    responsible for an explicit procedural fallback and warning.
    """
    client = ComfyUIClient(config.url)
    available, detail = client.available()
    if not available:
        raise ComfyUIUnavailable(detail)
    frames = max(2, int(round(clip_duration * fps)))
    data, extension, provider_metadata = client.generate(
        workflow_path=config.workflow_path,
        prompt=scene.visual_prompt,
        negative_prompt=scene.negative_prompt,
        width=width,
        height=height,
        seed=scene.seed,
        prefix=f"scene_{scene.scene_id:03d}_{scene.seed}",
        steps=config.steps,
        cfg=config.cfg,
        checkpoint=config.checkpoint,
        reference_image=image_path,
        timeout=config.timeout_seconds,
        extra_replacements={
            "DURATION": f"{clip_duration:.3f}",
            "FPS": fps,
            "FRAMES": frames,
        },
    )
    suffix = extension if extension.startswith(".") else "." + extension
    fd, raw_name = tempfile.mkstemp(prefix="mvs_ai_video_", suffix=suffix, dir=str(output_path.parent))
    os.close(fd)
    raw_path = Path(raw_name)
    try:
        write_bytes_atomic(raw_path, data)
        info = probe_media(raw_path)
        video_streams = [stream for stream in info.get("streams", []) if stream.get("codec_type") == "video"]
        if not video_streams:
            raise MediaError("The configured ComfyUI video workflow did not return a video stream")
        raw_duration = probe_duration(raw_path)
        if raw_duration <= 0.05:
            raise MediaError("The AI-generated video is empty")
        temp_output = output_path.with_name(output_path.stem + ".normalized.mp4")
        run_ffmpeg(
            [
                "-stream_loop",
                "-1",
                "-i",
                str(raw_path),
                "-t",
                f"{clip_duration:.3f}",
                "-vf",
                (
                    f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                    f"crop={width}:{height},fps={fps}"
                ),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(temp_output),
            ],
            timeout=1800,
        )
        os.replace(temp_output, output_path)
    finally:
        try:
            raw_path.unlink()
        except OSError:
            pass
    return {
        "backend": "comfyui_video",
        "provider": "comfyui",
        "workflow": config.workflow_path,
        "generation": provider_metadata,
        "width": width,
        "height": height,
        "fps": fps,
        "duration": round(frames / fps, 3),
        "frames": frames,
    }
