"""FFmpeg / FFprobe helpers and media validation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .config import get_settings


class MediaError(RuntimeError):
    pass


def _binary(name: str) -> str:
    configured = get_settings().ffmpeg if name == "ffmpeg" else get_settings().ffprobe
    if shutil.which(configured) or Path(configured).exists():
        return configured
    raise MediaError(f"{name} is not installed or not on PATH")


def run_command(
    args: list[str],
    *,
    timeout: float | None = 1800,
    cwd: str | Path | None = None,
    input_data: bytes | None = None,
) -> subprocess.CompletedProcess:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
            input=input_data,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"Command timed out after {timeout}s: {' '.join(args[:4])}") from exc
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace")[-4000:]
        raise MediaError(f"Command failed ({completed.returncode}): {' '.join(args[:6])}\n{stderr}")
    return completed


def probe_media(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.is_file():
        raise MediaError(f"Media file does not exist: {target}")
    completed = run_command(
        [
            _binary("ffprobe"),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(target),
        ],
        timeout=60,
    )
    try:
        data = json.loads(completed.stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise MediaError(f"Could not read media metadata for {target.name}") from exc
    if not data.get("format") or not data.get("streams"):
        raise MediaError(f"Unrecognised or empty media file: {target.name}")
    return data


def probe_duration(path: str | Path) -> float:
    data = probe_media(path)
    try:
        duration = float(data["format"].get("duration", 0.0))
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        for stream in data.get("streams", []):
            try:
                duration = max(duration, float(stream.get("duration", 0.0)))
            except (TypeError, ValueError):
                continue
    if duration <= 0:
        raise MediaError(f"Could not determine duration of {Path(path).name}")
    return round(duration, 3)


def validate_audio(path: str | Path) -> dict[str, Any]:
    data = probe_media(path)
    audio_streams = [stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"]
    if not audio_streams:
        raise MediaError("The selected file has no audio stream")
    duration = probe_duration(path)
    if duration < 1.0:
        raise MediaError("The audio file is shorter than one second")
    stream = audio_streams[0]
    return {
        "duration": duration,
        "codec": stream.get("codec_name"),
        "sample_rate": int(stream.get("sample_rate", 0) or 0),
        "channels": int(stream.get("channels", 0) or 0),
        "format": data.get("format", {}).get("format_name", ""),
    }


def validate_image(path: str | Path) -> tuple[int, int, str]:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise MediaError("Pillow is required to validate images") from exc
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            image_format = image.format or "unknown"
    except Exception as exc:
        raise MediaError(f"Unreadable image file: {Path(path).name}") from exc
    if width < 32 or height < 32:
        raise MediaError("Image is too small; use at least 32x32 pixels")
    return width, height, image_format


def run_ffmpeg(args: list[str], *, timeout: float | None = 3600) -> subprocess.CompletedProcess:
    return run_command([_binary("ffmpeg"), "-hide_banner", "-y", *args], timeout=timeout)


def encoder_available(encoder: str) -> bool:
    try:
        completed = run_command([_binary("ffmpeg"), "-hide_banner", "-encoders"], timeout=30)
    except MediaError:
        return False
    return encoder in completed.stdout.decode("utf-8", errors="replace")


def escape_filter_path(path: str | Path) -> str:
    """Escape a path for an FFmpeg filter option value."""
    value = str(Path(path).resolve()).replace("\\", "/")
    value = value.replace(":", "\\:").replace("'", "\\'")
    value = value.replace("[", "\\[").replace("]", "\\]")
    return value


def extract_thumbnail(
    video_path: str | Path,
    output_path: str | Path,
    *,
    time: float = 1.0,
    width: int = 480,
) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-ss",
            f"{max(0.0, time):.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={width}:-2",
            "-q:v",
            "3",
            str(target),
        ],
        timeout=120,
    )
    return target


def atomic_replace(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, target)


def write_bytes_atomic(path: str | Path, data: bytes) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise
    return target
