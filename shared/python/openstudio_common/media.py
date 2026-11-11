"""FFmpeg / FFprobe helpers shared by media-aware services."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"


class MediaError(RuntimeError):
    pass


async def run_process(cmd: list[str], timeout: float = 3600.0) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise MediaError(f"Process timed out after {timeout:.0f}s") from exc
    return process.returncode, stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace")


async def ffprobe(path: Path) -> dict[str, Any]:
    code, out, err = await run_process(
        [
            FFPROBE,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        timeout=120,
    )
    if code != 0:
        raise MediaError(err.strip() or f"ffprobe failed for {path.name}")
    data = json.loads(out or "{}")
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    return {
        "path": str(path),
        "duration": _float(fmt.get("duration")),
        "size": _int(fmt.get("size")),
        "bit_rate": _int(fmt.get("bit_rate")),
        "format_name": fmt.get("format_name"),
        "format_long_name": fmt.get("format_long_name"),
        "tags": fmt.get("tags", {}),
        "streams": [
            {
                "index": s.get("index"),
                "type": s.get("codec_type"),
                "codec": s.get("codec_name"),
                "codec_long": s.get("codec_long_name"),
                "width": s.get("width"),
                "height": s.get("height"),
                "fps": _fps(s.get("avg_frame_rate") or s.get("r_frame_rate")),
                "sample_rate": _int(s.get("sample_rate")),
                "channels": _int(s.get("channels")),
                "channel_layout": s.get("channel_layout"),
                "bit_rate": _int(s.get("bit_rate")),
                "pix_fmt": s.get("pix_fmt"),
                "duration": _float(s.get("duration")),
                "language": (s.get("tags") or {}).get("language"),
            }
            for s in streams
        ],
    }


async def ffmpeg(args: list[str], timeout: float = 3600.0) -> str:
    code, _, err = await run_process([FFMPEG, "-hide_banner", "-y", *args], timeout=timeout)
    if code != 0:
        tail = "\n".join(err.strip().splitlines()[-20:])
        raise MediaError(tail or "ffmpeg failed")
    return err


def _float(value: Any) -> float | None:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _fps(value: Any) -> float | None:
    try:
        num, den = str(value).split("/")
        return round(float(num) / float(den), 3) if float(den) else None
    except (ValueError, ZeroDivisionError):
        return None
