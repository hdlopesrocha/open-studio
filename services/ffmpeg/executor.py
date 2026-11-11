"""Process execution, progress parsing and ffprobe helpers for the FFmpeg service."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from openstudio_common import (
    FFMPEG,
    FFPROBE,
    JobCancelled,
    MediaError,
    file_info,
    kind_of,
    relative_path,
    resolve_path,
)

log = logging.getLogger("ffmpeg.executor")

ProgressReporter = Callable[[float | None, str | None, str | None], Awaitable[None]]
CancelCheck = Callable[[], Awaitable[None]]


class ProcessTimeout(MediaError):
    """Raised when a bounded ffmpeg run exceeds its deadline."""


@dataclass
class ExecutionHooks:
    """Bridge between the executor and a job context or a sync request."""

    job_id: str
    report: ProgressReporter | None = None
    check: CancelCheck | None = None
    warnings: list[str] = field(default_factory=list)

    async def notify(self, progress: float | None = None, stage: str | None = None, message: str | None = None) -> None:
        if self.report is None:
            return
        try:
            await self.report(progress, stage, message)
        except Exception:  # noqa: BLE001 - progress must never fail a job
            log.debug("Progress callback failed", exc_info=True)

    async def ensure_active(self) -> None:
        if self.check is not None:
            await self.check()


@dataclass
class FFmpegRun:
    args: list[str]
    code: int
    stderr: str
    stderr_tail: str
    last_seconds: float | None
    elapsed: float


class ProcessManager:
    """Track live ffmpeg processes so cancellation can terminate them immediately."""

    def __init__(self) -> None:
        self._active: dict[str, asyncio.subprocess.Process] = {}

    def register(self, key: str, process: asyncio.subprocess.Process) -> None:
        self._active[key] = process

    def unregister(self, key: str, process: asyncio.subprocess.Process | None = None) -> None:
        current = self._active.get(key)
        if process is None or current is process:
            self._active.pop(key, None)

    def get(self, key: str) -> asyncio.subprocess.Process | None:
        return self._active.get(key)

    def active(self) -> dict[str, int]:
        return {key: proc.pid for key, proc in self._active.items() if proc.returncode is None}

    async def cancel(self, key: str) -> bool:
        process = self._active.get(key)
        if process is None or process.returncode is not None:
            return False
        await terminate_process(process)
        return True

    async def cancel_all(self) -> None:
        for process in list(self._active.values()):
            await terminate_process(process)


PROCESSES = ProcessManager()


async def terminate_process(process: asyncio.subprocess.Process) -> None:
    """Terminate ffmpeg and any child processes in its session."""
    if process.returncode is not None:
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.terminate()
        except ProcessLookupError:
            return
    try:
        await asyncio.wait_for(process.wait(), timeout=3.0)
        return
    except asyncio.TimeoutError:
        pass
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except ProcessLookupError:
            pass


def _parse_time(value: str) -> float | None:
    value = (value or "").strip()
    if not value:
        return None
    match = re.match(r"^(-?\d+):(\d{2}):(\d{2}(?:\.\d+)?)$", value)
    if not match:
        try:
            return float(value)
        except ValueError:
            return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


async def run_ffmpeg(
    args: list[str],
    *,
    job_id: str,
    hooks: ExecutionHooks | None = None,
    duration: float | None = None,
    progress_start: float = 0.0,
    progress_end: float = 100.0,
    stage: str = "Processing",
    timeout: float | None = None,
) -> FFmpegRun:
    """Run ffmpeg with -progress pipe:1, reporting percent and killing on cancel."""
    hooks = hooks or ExecutionHooks(job_id=job_id)
    full_args = list(args)
    if "-progress" not in full_args:
        full_args = ["-nostats", "-progress", "pipe:1", *full_args]
    command = [FFMPEG, "-hide_banner", "-y", *full_args]
    started = time.monotonic()
    deadline = started + timeout if timeout else None

    await hooks.ensure_active()
    await hooks.notify(max(0.0, progress_start), stage, "Starting FFmpeg")
    log.info("ffmpeg job=%s start: %s", job_id, " ".join(command))

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    PROCESSES.register(job_id, process)
    stderr_lines: list[str] = []
    last_seconds: float | None = None
    last_report = 0.0
    last_percent = -1.0

    def stderr_tail(limit: int = 24) -> str:
        return "\n".join(line for line in stderr_lines[-limit:] if line)

    async def pump_stdout() -> None:
        nonlocal last_seconds, last_report, last_percent
        assert process.stdout is not None
        while True:
            raw = await process.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", "replace").strip()
            if not line or "=" not in line:
                continue
            key, value = line.split("=", 1)
            seconds: float | None = None
            if key in {"out_time_us", "out_time_ms"}:
                try:
                    seconds = int(value) / 1_000_000.0
                except ValueError:
                    seconds = None
            elif key == "out_time":
                seconds = _parse_time(value)
            if seconds is not None:
                last_seconds = max(last_seconds or 0.0, seconds)
                if duration and duration > 0:
                    ratio = max(0.0, min(1.0, last_seconds / duration))
                    percent = progress_start + (progress_end - progress_start) * ratio
                    now = time.monotonic()
                    if now - last_report >= 0.75 and (percent - last_percent >= 0.5 or percent >= progress_end):
                        last_report = now
                        last_percent = percent
                        message = f"{last_seconds:.1f}s / {duration:.1f}s"
                        await hooks.notify(round(percent, 2), stage, message)
            elif key == "progress" and value == "end":
                await hooks.notify(progress_end, stage, "Finalizing")

    async def pump_stderr() -> None:
        assert process.stderr is not None
        while True:
            raw = await process.stderr.readline()
            if not raw:
                break
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                stderr_lines.append(line)
                if len(stderr_lines) > 4000:
                    del stderr_lines[:1000]

    stdout_task = asyncio.create_task(pump_stdout())
    stderr_task = asyncio.create_task(pump_stderr())
    killed_for_cancel = False
    timed_out = False
    try:
        while True:
            try:
                await asyncio.wait_for(process.wait(), timeout=0.35)
                break
            except asyncio.TimeoutError:
                pass
            try:
                await hooks.ensure_active()
            except JobCancelled:
                killed_for_cancel = True
                await hooks.notify(progress_start if not last_percent else last_percent, "Cancelling", "Stopping FFmpeg")
                await terminate_process(process)
                raise
            if deadline is not None and time.monotonic() > deadline:
                timed_out = True
                await terminate_process(process)
                raise ProcessTimeout(f"FFmpeg exceeded the {timeout:.0f}s timeout")
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        await process.wait()
    finally:
        if process.returncode is None:
            await terminate_process(process)
        PROCESSES.unregister(job_id, process)
        for task in (stdout_task, stderr_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

    elapsed = time.monotonic() - started
    stderr = "\n".join(stderr_lines)
    if process.returncode != 0:
        if killed_for_cancel:
            raise JobCancelled("Cancelled by the user")
        if timed_out:
            raise ProcessTimeout(f"FFmpeg exceeded the {timeout:.0f}s timeout")
        tail = stderr_tail() or "FFmpeg failed"
        raise MediaError(tail)
    await hooks.notify(progress_end, stage, "Completed")
    return FFmpegRun(
        args=command,
        code=int(process.returncode or 0),
        stderr=stderr,
        stderr_tail=stderr_tail(),
        last_seconds=last_seconds,
        elapsed=round(elapsed, 2),
    )


def _num(value: Any, digits: int = 3) -> float | None:
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _fps(value: Any) -> float | None:
    text = str(value or "")
    if "/" in text:
        try:
            numerator, denominator = text.split("/", 1)
            if float(denominator) == 0:
                return None
            return round(float(numerator) / float(denominator), 3)
        except (TypeError, ValueError):
            return None
    return _num(value)


def _rotation(stream: dict[str, Any]) -> int | None:
    tags = stream.get("tags") or {}
    if tags.get("rotate") is not None:
        try:
            return int(float(tags["rotate"])) % 360
        except (TypeError, ValueError):
            pass
    for side in stream.get("side_data_list") or []:
        if side.get("rotation") is not None:
            try:
                return int(float(side["rotation"])) % 360
            except (TypeError, ValueError):
                pass
    return None


async def ffprobe_json(path: Path, timeout: float = 120.0) -> dict[str, Any]:
    command = [
        FFPROBE,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-show_chapters",
        str(path),
    ]
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        await terminate_process(process)
        raise MediaError("ffprobe timed out") from exc
    if process.returncode != 0:
        detail = stderr.decode("utf-8", "replace").strip()
        raise MediaError(detail or f"ffprobe failed for {path.name}")
    try:
        return json.loads(stdout.decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError as exc:
        raise MediaError("ffprobe returned invalid JSON") from exc


def _stream_details(stream: dict[str, Any]) -> dict[str, Any]:
    tags = stream.get("tags") or {}
    disposition = stream.get("disposition") or {}
    return {
        "index": stream.get("index"),
        "type": stream.get("codec_type"),
        "codec": stream.get("codec_name"),
        "codec_long": stream.get("codec_long_name"),
        "profile": stream.get("profile"),
        "level": stream.get("level"),
        "width": stream.get("width"),
        "height": stream.get("height"),
        "coded_width": stream.get("coded_width"),
        "coded_height": stream.get("coded_height"),
        "fps": _fps(stream.get("avg_frame_rate") or stream.get("r_frame_rate")),
        "r_frame_rate": stream.get("r_frame_rate"),
        "avg_frame_rate": stream.get("avg_frame_rate"),
        "pix_fmt": stream.get("pix_fmt"),
        "sample_aspect_ratio": stream.get("sample_aspect_ratio"),
        "display_aspect_ratio": stream.get("display_aspect_ratio"),
        "bit_rate": _int(stream.get("bit_rate")),
        "nb_frames": _int(stream.get("nb_frames")),
        "duration": _num(stream.get("duration")),
        "sample_rate": _int(stream.get("sample_rate")),
        "channels": _int(stream.get("channels")),
        "channel_layout": stream.get("channel_layout"),
        "sample_fmt": stream.get("sample_fmt"),
        "bits_per_sample": _int(stream.get("bits_per_sample") or stream.get("bits_per_raw_sample")),
        "language": tags.get("language"),
        "title": tags.get("title"),
        "rotation": _rotation(stream),
        "disposition": {key: value for key, value in disposition.items() if value},
        "tags": tags,
        "color_range": stream.get("color_range"),
        "color_space": stream.get("color_space"),
        "color_transfer": stream.get("color_transfer"),
        "color_primaries": stream.get("color_primaries"),
    }


async def probe_media(path: Path) -> dict[str, Any]:
    """Return detailed, JSON-safe ffprobe metadata for a media file."""
    raw = await ffprobe_json(path)
    fmt = raw.get("format") or {}
    streams = [_stream_details(stream) for stream in raw.get("streams") or []]
    video_streams = [stream for stream in streams if stream["type"] == "video" and not stream["disposition"].get("attached_pic")]
    audio_streams = [stream for stream in streams if stream["type"] == "audio"]
    subtitle_streams = [stream for stream in streams if stream["type"] == "subtitle"]
    format_name = fmt.get("format_name") or ""
    image_like = bool(video_streams) and (
        "image2" in format_name
        or (
            len(video_streams) == 1
            and video_streams[0].get("duration") in (None, 0)
            and (video_streams[0].get("nb_frames") or 0) <= 1
            and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".avif"}
        )
    )
    video = video_streams[0] if video_streams else None
    audio = audio_streams[0] if audio_streams else None
    duration = _num(fmt.get("duration")) or (video or {}).get("duration") or (audio or {}).get("duration")
    size = _int(fmt.get("size")) or (path.stat().st_size if path.exists() else 0)
    result: dict[str, Any] = {
        "path": relative_path(path),
        "filename": path.name,
        "format_name": fmt.get("format_name"),
        "format_long_name": fmt.get("format_long_name"),
        "duration": duration,
        "size": size,
        "bit_rate": _int(fmt.get("bit_rate")),
        "tags": fmt.get("tags") or {},
        "nb_streams": fmt.get("nb_streams"),
        "streams": streams,
        "video": video,
        "audio": audio,
        "subtitle": subtitle_streams[0] if subtitle_streams else None,
        "has_video": bool(video_streams) and not image_like,
        "has_audio": bool(audio_streams),
        "has_subtitles": bool(subtitle_streams),
        "is_image": image_like,
        "kind": "image" if image_like else ("video" if video_streams else ("audio" if audio_streams else kind_of(path))),
        "chapters": raw.get("chapters") or [],
        "format": {
            "filename": path.name,
            "nb_streams": fmt.get("nb_streams"),
            "format_name": fmt.get("format_name"),
            "format_long_name": fmt.get("format_long_name"),
            "duration": _num(fmt.get("duration")),
            "size": _int(fmt.get("size")),
            "bit_rate": _int(fmt.get("bit_rate")),
            "tags": fmt.get("tags") or {},
        },
        "primary_video": video,
        "primary_audio": audio,
    }
    if image_like and video:
        result["image"] = {
            "width": video.get("width"),
            "height": video.get("height"),
            "pix_fmt": video.get("pix_fmt"),
            "codec": video.get("codec"),
            "size": size,
        }
    else:
        result["image"] = None
    return result


def input_file(rel_path: str) -> Path:
    if not rel_path or not str(rel_path).strip():
        raise ValueError("input_path is required")
    path = resolve_path(str(rel_path))
    if not path.exists():
        raise FileNotFoundError(str(rel_path))
    if path.is_dir():
        raise ValueError(f"Expected a file, got a folder: {rel_path}")
    return path


def file_descriptor(path: Path, *, kind: str | None = None) -> dict[str, Any]:
    info = file_info(path)
    return {
        "path": info["path"],
        "name": info["name"],
        "kind": kind or info["kind"],
        "mime": info["mime"],
        "size": info["size"],
        "modified": info["modified"],
    }


def describe_files(paths: list[Path], *, kind: str | None = None) -> list[dict[str, Any]]:
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists() or path.is_dir():
            continue
        try:
            item = file_descriptor(path, kind=kind)
        except ValueError:
            continue
        if item["path"] in seen:
            continue
        seen.add(item["path"])
        items.append(item)
    return items


def glob_outputs(directory: Path, pattern: str = "*") -> list[Path]:
    if not directory.exists():
        return []
    return sorted(path for path in directory.glob(pattern) if path.is_file() and not path.name.startswith("."))
