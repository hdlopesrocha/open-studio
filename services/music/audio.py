"""Audio helpers for generated takes and exports."""

from __future__ import annotations

import asyncio
import json
import wave
from pathlib import Path
from typing import Any

from openstudio_common import (
    MediaError,
    ffmpeg,
    ffprobe,
    guess_mime,
    kind_of,
    relative_path,
    sanitize_name,
)

ENGINE_OUTPUT_FORMATS = {
    "wav": "wav16",
    "wav16": "wav16",
    "wav24": "wav24",
    "wav32": "wav32",
    "mp3": "mp3",
    "flac": "wav16",
}

MIME_BY_FORMAT = {
    "wav": "audio/wav",
    "wav16": "audio/wav",
    "wav24": "audio/wav",
    "wav32": "audio/wav",
    "mp3": "audio/mpeg",
    "flac": "audio/flac",
}

EXTENSION_BY_FORMAT = {
    "wav": ".wav",
    "wav16": ".wav",
    "wav24": ".wav",
    "wav32": ".wav",
    "mp3": ".mp3",
    "flac": ".flac",
}


def engine_output_format(audio_format: str) -> str:
    return ENGINE_OUTPUT_FORMATS.get((audio_format or "wav").lower(), "wav16")


def extension_for_format(audio_format: str) -> str:
    return EXTENSION_BY_FORMAT.get((audio_format or "wav").lower(), ".wav")


def extension_for_mime(mime: str) -> str:
    mime = (mime or "").split(";")[0].strip().lower()
    if "mpeg" in mime or "mp3" in mime:
        return ".mp3"
    if "flac" in mime:
        return ".flac"
    if "ogg" in mime or "opus" in mime:
        return ".ogg"
    return ".wav"


def _wave_duration(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate()
            if not rate:
                return None
            return round(handle.getnframes() / rate, 3)
    except (wave.Error, OSError, EOFError):
        return None


async def probe_duration(path: Path, fallback: float | None = None) -> float:
    """Return an audio duration using ffprobe, with a WAV-header fallback."""
    try:
        data = await ffprobe(path)
        duration = data.get("duration")
        if duration:
            return round(float(duration), 3)
    except (MediaError, OSError, ValueError, json.JSONDecodeError):
        pass
    duration = await asyncio.to_thread(_wave_duration, path)
    if duration is not None:
        return duration
    return round(float(fallback or 0), 3)


async def convert_audio(source: Path, destination: Path, output_format: str) -> Path:
    """Convert audio with ffmpeg. Raises MediaError on failure."""
    if not source.exists():
        raise MediaError("The source audio file no longer exists.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fmt = (output_format or "wav").lower()
    if fmt in {"wav", "wav16", "wav24", "wav32"}:
        codec = ["-c:a", "pcm_s16le" if fmt in {"wav", "wav16"} else "pcm_s24le" if fmt == "wav24" else "pcm_s32le"]
    elif fmt == "mp3":
        codec = ["-c:a", "libmp3lame", "-b:a", "256k"]
    elif fmt == "flac":
        codec = ["-c:a", "flac"]
    else:
        raise MediaError(f"Unsupported audio format: {output_format}")
    try:
        await ffmpeg(["-v", "error", "-i", str(source), "-vn", *codec, str(destination)], timeout=900)
    except FileNotFoundError as exc:
        if destination.exists():
            destination.unlink(missing_ok=True)
        raise MediaError("ffmpeg is not installed in the music container.") from exc
    except MediaError:
        if destination.exists():
            destination.unlink(missing_ok=True)
        raise
    return destination


def safe_filename(title: str, fallback: str = "song") -> str:
    name = sanitize_name(title or fallback, fallback=fallback)
    if not name or name in {".", ".."}:
        name = fallback
    return name[:120]


def file_record(path: Path, kind: str | None = None) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": relative_path(path),
        "kind": kind or kind_of(path),
        "mime": guess_mime(path),
        "name": path.name,
        "size": stat.st_size,
    }
