"""Frame extraction, GIF, segmentation, metadata and raw FFmpeg operations."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from openstudio_common import MediaError, resolve_path

from .executor import ExecutionHooks, probe_media, run_ffmpeg
from .operations import (
    OperationResult,
    audio_encode_args,
    format_args,
    format_extension,
    get_bool,
    get_float,
    get_int,
    get_list,
    get_str,
    glob_pattern,
    output_pattern,
    rate_str,
    resolve_output,
    suffix_for_input,
    time_str,
    verify_output,
    video_encode_args,
)


def _pattern_with_index(pattern: Path, index: int) -> Path:
    def replace(match: re.Match[str]) -> str:
        width = int(match.group(1) or 1)
        return f"{index:0{width}d}"

    name = re.sub(r"%0?(\d*)d", replace, pattern.name)
    return pattern.with_name(name)


async def frames(
    *,
    input_path: Path,
    options: dict[str, Any],
    payload: dict[str, Any],
    workdir: Path,
    hooks: ExecutionHooks,
    operation: str,
) -> OperationResult:
    probe = await probe_media(input_path)
    if not probe.get("video"):
        raise ValueError("frames requires a video or image input")
    mode = get_str(options, "mode", "fps").lower()
    if mode not in {"fps", "timestamps"}:
        raise ValueError("mode must be fps or timestamps")
    fmt = get_str(options, "format", "")
    if not fmt:
        suffix = Path(str(payload.get("output_path") or "")).suffix.lower().lstrip(".")
        fmt = suffix if suffix in {"jpg", "jpeg", "png", "webp"} else "jpg"
    extension = ".jpg" if fmt in {"jpg", "jpeg"} else f".{fmt}"
    directory, pattern = output_pattern(workdir, input_path, operation, payload.get("output_path"), extension)
    max_frames = get_int(options, "max_frames", 1000, minimum=1, maximum=5000) or 1000
    width = get_int(options, "width", None, minimum=-1)
    height = get_int(options, "height", None, minimum=-1)
    scale_expr = ""
    if (width is not None and width != 0) or (height is not None and height != 0):
        if width in (None, 0):
            width = -1
        if height in (None, 0):
            height = -1
        if width == -1 and height == -1:
            raise ValueError("width and height cannot both be -1")
        scale_expr = f",scale={width}:{height}"
    quality = get_int(options, "quality", 2, minimum=2, maximum=31) or 2
    quality_args = ["-q:v", str(quality)] if fmt in {"jpg", "jpeg", "webp"} else []
    files: list[Path] = []

    if mode == "fps":
        fps = get_float(options, "fps", 1.0, minimum=0.01, maximum=240) or 1.0
        start = get_float(options, "start", 0.0, minimum=0.0) or 0.0
        duration = get_float(options, "duration", None, minimum=0.01)
        filter_expr = f"fps={rate_str(fps)}{scale_expr}"
        args = []
        if start:
            args += ["-ss", time_str(start)]
        args += ["-i", str(input_path), "-vf", filter_expr, "-frames:v", str(max_frames), "-start_number", "1"]
        if duration:
            args += ["-t", time_str(duration)]
        args += quality_args
        args += [str(pattern)]
        await run_ffmpeg(
            args,
            job_id=hooks.job_id,
            hooks=hooks,
            duration=duration or probe.get("duration"),
            progress_start=3,
            progress_end=96,
            stage="Extracting frames",
        )
        files = glob_pattern(directory, pattern)
    else:
        timestamps = get_list(options, "timestamps")
        if not timestamps:
            raise ValueError("timestamps must contain at least one time in seconds")
        if len(timestamps) > max_frames:
            raise ValueError(f"timestamps exceeds the {max_frames} frame limit")
        parsed: list[float] = []
        for value in timestamps:
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("timestamps must contain numbers") from exc
            if number < 0:
                raise ValueError("timestamps cannot be negative")
            parsed.append(number)
        total_duration = probe.get("duration") or 0
        for index, timestamp in enumerate(parsed, start=1):
            if total_duration and timestamp > total_duration:
                hooks.warnings.append(f"Skipped timestamp {timestamp}s beyond the media duration.")
                continue
            target = _pattern_with_index(pattern, index)
            args = [
                "-ss",
                time_str(timestamp),
                "-i",
                str(input_path),
                "-frames:v",
                "1",
                "-update",
                "1",
            ]
            if scale_expr:
                args += ["-vf", scale_expr.lstrip(",")]
            args += quality_args
            args += [str(target)]
            progress = 4 + (index - 1) / len(parsed) * 90
            try:
                await run_ffmpeg(
                    args,
                    job_id=hooks.job_id,
                    hooks=hooks,
                    progress_start=progress,
                    progress_end=progress + 90 / len(parsed),
                    stage=f"Extracting frame {index}/{len(parsed)}",
                )
                await verify_output(target, operation)
                files.append(target)
            except MediaError as exc:
                hooks.warnings.append(f"Frame at {timestamp}s failed: {exc}")
        files = [path for path in files if path.exists()]
    if not files:
        raise MediaError("No frames were extracted")
    files = files[:max_frames]
    return OperationResult(
        files=files,
        data={
            "operation": operation,
            "mode": mode,
            "count": len(files),
            "format": fmt,
            "directory": str(directory),
            "pattern": str(pattern),
        },
        message=f"Extracted {len(files)} frame(s)",
    )


async def gif(
    *,
    input_path: Path,
    options: dict[str, Any],
    payload: dict[str, Any],
    workdir: Path,
    hooks: ExecutionHooks,
    operation: str,
) -> OperationResult:
    probe = await probe_media(input_path)
    if not probe.get("has_video"):
        raise ValueError("gif requires a video input")
    start = get_float(options, "start", 0.0, minimum=0.0) or 0.0
    duration = get_float(options, "duration", 3.0, minimum=0.1, maximum=120) or 3.0
    fps = get_float(options, "fps", 12.0, minimum=1.0, maximum=50.0) or 12.0
    width = get_int(options, "width", 480, minimum=16, maximum=1920) or 480
    max_colors = get_int(options, "max_colors", 256, minimum=2, maximum=256) or 256
    dither = get_str(options, "dither", "bayer").lower()
    if dither not in {"bayer", "sierra2_4a", "none"}:
        raise ValueError("dither must be bayer, sierra2_4a or none")
    loop = get_int(options, "loop", 0, minimum=-1, maximum=1000) or 0
    palette = get_bool(options, "palette", True)
    target = resolve_output(workdir, input_path, operation, payload.get("output_path"), ".gif")

    base = f"fps={rate_str(fps)},scale={width}:-1:flags=lanczos"
    if palette:
        if dither == "none":
            use = "paletteuse=dither=none"
        elif dither == "sierra2_4a":
            use = "paletteuse=dither=sierra2_4a"
        else:
            use = "paletteuse=dither=bayer:bayer_scale=5"
        filter_expr = f"{base},split[s0][s1];[s0]palettegen=max_colors={max_colors}:stats_mode=diff[p];[s1][p]{use}"
    else:
        filter_expr = base
    args = ["-ss", time_str(start), "-t", time_str(duration), "-i", str(input_path), "-vf", filter_expr, "-loop", str(loop), str(target)]
    await run_ffmpeg(
        args,
        job_id=hooks.job_id,
        hooks=hooks,
        duration=duration,
        progress_start=3,
        progress_end=96,
        stage="Creating GIF",
    )
    await verify_output(target, operation)
    return OperationResult(
        files=[target],
        data={"operation": operation, "start": start, "duration": duration, "fps": fps, "width": width, "palette": palette},
        message=f"Created {target.name}",
    )


async def thumbnail(
    *,
    input_path: Path,
    options: dict[str, Any],
    payload: dict[str, Any],
    workdir: Path,
    hooks: ExecutionHooks,
    operation: str,
) -> OperationResult:
    probe = await probe_media(input_path)
    if not probe.get("video"):
        raise ValueError("thumbnail requires a video or image input")
    timestamp = get_float(options, "time", 0.0, minimum=0.0) or 0.0
    duration = probe.get("duration")
    if duration and timestamp >= float(duration):
        timestamp = max(0.0, float(duration) - 0.1)
        hooks.warnings.append(f"Requested timestamp is beyond the media; using {timestamp:.2f}s.")
    width = get_int(options, "width", 320, minimum=16, maximum=4096) or 320
    height = get_int(options, "height", None, minimum=2)
    fmt = get_str(options, "format", "")
    if not fmt:
        suffix = Path(str(payload.get("output_path") or "")).suffix.lower().lstrip(".")
        fmt = suffix if suffix in {"jpg", "jpeg", "png", "webp"} else "jpg"
    extension = ".jpg" if fmt in {"jpg", "jpeg"} else f".{fmt}"
    target = resolve_output(workdir, input_path, operation, payload.get("output_path"), extension)
    scale_expr = f"scale={width}:{height if height else -2}"
    args = ["-ss", time_str(timestamp), "-i", str(input_path), "-vf", scale_expr, "-frames:v", "1", "-update", "1", "-an", "-sn"]
    quality = get_int(options, "quality", 2, minimum=2, maximum=31) or 2
    if fmt in {"jpg", "jpeg", "webp"}:
        args += ["-q:v", str(quality)]
    args += [str(target)]
    await run_ffmpeg(args, job_id=hooks.job_id, hooks=hooks, progress_start=5, progress_end=95, stage="Creating thumbnail")
    await verify_output(target, operation)
    return OperationResult(
        files=[target],
        data={"operation": operation, "time": timestamp, "width": width, "height": height},
        message=f"Created thumbnail at {timestamp:.2f}s",
    )


SEGMENT_FORMAT = {
    ".mp4": "mp4",
    ".m4v": "mp4",
    ".mov": "mov",
    ".mkv": "matroska",
    ".webm": "webm",
    ".ts": "mpegts",
    ".avi": "avi",
}


async def split(
    *,
    input_path: Path,
    options: dict[str, Any],
    payload: dict[str, Any],
    workdir: Path,
    hooks: ExecutionHooks,
    operation: str,
) -> OperationResult:
    probe = await probe_media(input_path)
    duration = get_float(options, "duration", 60.0, minimum=1.0, maximum=86400.0) or 60.0
    fmt = get_str(options, "format", "")
    extension = format_extension(fmt, suffix_for_input(input_path, ".mp4")) if fmt else suffix_for_input(input_path, ".mp4")
    directory, pattern = output_pattern(workdir, input_path, operation, payload.get("output_path"), extension)
    copy = get_bool(options, "copy", True)
    segment_format = SEGMENT_FORMAT.get(extension, "")
    args = ["-i", str(input_path), "-map", "0", "-f", "segment", "-segment_time", time_str(duration)]
    if get_bool(options, "reset_timestamps", True):
        args += ["-reset_timestamps", "1"]
    if segment_format:
        args += ["-segment_format", segment_format]
    if copy:
        args += ["-c", "copy"]
    else:
        args += video_encode_args(options)
        args += audio_encode_args(options, default_codec="aac")
        args += ["-force_key_frames", f"expr:gte(t,n_forced*{duration:.3f})"]
    args += [str(pattern)]
    await run_ffmpeg(
        args,
        job_id=hooks.job_id,
        hooks=hooks,
        duration=probe.get("duration"),
        progress_start=3,
        progress_end=96,
        stage="Splitting",
    )
    files = glob_pattern(directory, pattern)
    if not files:
        raise MediaError("Segmentation produced no files")
    return OperationResult(
        files=files,
        data={"operation": operation, "segment_seconds": duration, "count": len(files), "pattern": str(pattern), "copy": copy},
        message=f"Split into {len(files)} segment(s)",
    )


async def metadata(
    *,
    input_path: Path,
    options: dict[str, Any],
    payload: dict[str, Any],
    workdir: Path,
    hooks: ExecutionHooks,
    operation: str,
) -> OperationResult:
    probe = await probe_media(input_path)
    fmt = get_str(options, "format", "")
    extension = format_extension(fmt, suffix_for_input(input_path, ".mkv")) if fmt else suffix_for_input(input_path, ".mkv")
    target = resolve_output(workdir, input_path, operation, payload.get("output_path"), extension)
    args = ["-i", str(input_path), "-map", "0", "-c", "copy"]
    if get_bool(options, "strip", False):
        args += ["-map_metadata", "-1"]
    if not get_bool(options, "chapters", True):
        args += ["-map_chapters", "-1"]
    metadata_values = options.get("metadata") or {}
    if not isinstance(metadata_values, dict):
        raise ValueError("metadata must be an object")
    for key, value in metadata_values.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("metadata keys must be non-empty strings")
        text = str(value)
        if "\x00" in key or "\x00" in text:
            raise ValueError("metadata cannot contain null bytes")
        args += ["-metadata", f"{key}={text}"]
    remove_keys = get_list(options, "remove")
    for key in remove_keys:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("remove must contain metadata key strings")
        args += ["-metadata", f"{key}="]
    args += format_args(options)
    args += [str(target)]
    await run_ffmpeg(args, job_id=hooks.job_id, hooks=hooks, progress_start=5, progress_end=95, stage="Updating metadata")
    await verify_output(target, operation)
    return OperationResult(
        files=[target],
        data={
            "operation": operation,
            "strip": get_bool(options, "strip", False),
            "metadata": {str(key): str(value) for key, value in metadata_values.items()},
            "remove": remove_keys,
            "input_format": probe.get("format_name"),
        },
        message="Updated metadata",
    )


def _normalize_raw_argv(raw: Any) -> list[str]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("argv must be a non-empty list of strings")
    argv: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError("argv must contain only strings")
        if "\x00" in item:
            raise ValueError("argv cannot contain null bytes")
        argv.append(item)
    first = argv[0]
    executable = Path(first).name.lower()
    if executable in {"ffmpeg", "ffmpeg.exe"}:
        argv = argv[1:]
    elif not first.startswith("-"):
        raise ValueError("raw only supports the ffmpeg executable; pass ffmpeg arguments without a shell")
    if not argv:
        raise ValueError("argv contains no ffmpeg arguments")
    return argv


async def raw(
    *,
    input_path: Path | None,
    options: dict[str, Any],
    payload: dict[str, Any],
    workdir: Path,
    hooks: ExecutionHooks,
    operation: str,
) -> OperationResult:
    argv = _normalize_raw_argv(options.get("argv"))
    if input_path is not None and "-i" not in argv:
        argv = ["-i", str(input_path), *argv]
    target: Path | None = None
    output_raw = str(payload.get("output_path") or "").strip()
    if output_raw:
        target = resolve_path(output_raw)
        ensure_dir = target.parent
        ensure_dir.mkdir(parents=True, exist_ok=True)
        if str(target) not in argv:
            argv.append(str(target))
    timeout = get_float(options, "timeout", 3600.0, minimum=1.0, maximum=86400.0)
    duration = None
    if input_path is not None:
        try:
            duration = (await probe_media(input_path)).get("duration")
        except Exception:  # noqa: BLE001 - raw inputs may be unusual or synthetic
            duration = None
    run = await run_ffmpeg(
        argv,
        job_id=hooks.job_id,
        hooks=hooks,
        duration=duration,
        progress_start=3,
        progress_end=96,
        stage="Running raw FFmpeg",
        timeout=timeout,
    )
    files: list[Path] = []
    if target is not None and target.exists() and target.is_file():
        files.append(target)
    else:
        hooks.warnings.append("No output_path was provided or produced; raw FFmpeg output cannot be reported automatically.")
    return OperationResult(
        files=files,
        data={
            "operation": operation,
            "argv": run.args[1:],
            "stderr_tail": run.stderr_tail,
            "elapsed": run.elapsed,
        },
        message="Raw FFmpeg command completed",
    )
