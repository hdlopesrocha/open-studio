"""Basic per-file FFmpeg operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .catalog import AUDIO_FORMATS
from .executor import ExecutionHooks, probe_media, run_ffmpeg
from .operations import (
    OperationResult,
    audio_codec_for_target,
    audio_encode_args,
    atempo_chain,
    aspect_crop,
    codec_name,
    color_value,
    format_args,
    format_extension,
    get_bool,
    get_float,
    get_int,
    get_str,
    movflags_args,
    parse_aspect,
    parse_size,
    rate_str,
    resolve_output,
    scale_filter,
    suffix_for_input,
    time_str,
    verify_output,
    video_encode_args,
)


async def transcode(
    *,
    input_path: Path,
    options: dict[str, Any],
    payload: dict[str, Any],
    workdir: Path,
    hooks: ExecutionHooks,
    operation: str,
) -> OperationResult:
    probe = await probe_media(input_path)
    media = get_str(options, "media", "auto").lower()
    if media not in {"auto", "video", "audio"}:
        raise ValueError("media must be auto, video or audio")
    if media == "auto":
        media = "video" if probe.get("has_video") or probe.get("is_image") else "audio"
    if media == "video" and not probe.get("video"):
        raise ValueError("Input has no video stream")
    if media == "audio" and not probe.get("audio"):
        raise ValueError("Input has no audio stream")

    fmt = get_str(options, "format", "")
    if media == "audio":
        if not fmt:
            suffix = Path(str(payload.get("output_path") or "")).suffix.lower()
            fmt = suffix.lstrip(".") if suffix.lstrip(".") in AUDIO_FORMATS else ""
        default_ext = format_extension(fmt, ".m4a") if fmt else ".m4a"
    else:
        default_ext = format_extension(fmt, ".mp4") if fmt else ".mp4"
    target = resolve_output(workdir, input_path, operation, payload.get("output_path"), default_ext)
    fmt = fmt or target.suffix.lstrip(".").lower()

    args: list[str] = []
    hwaccel = get_str(options, "hwaccel", "none").lower()
    if hwaccel and hwaccel not in {"none", "auto"}:
        args += ["-hwaccel", hwaccel]
        device = get_str(options, "hwaccel_device", "")
        if device:
            args += ["-hwaccel_device", device]
    args += ["-i", str(input_path)]

    filters: list[str] = []
    if media == "video":
        width: int | None = get_int(options, "width", None, minimum=-2)
        height: int | None = get_int(options, "height", None, minimum=-2)
        resolution = parse_size(get_str(options, "resolution", ""))
        if resolution:
            width, height = resolution
        if width is not None or height is not None:
            if width in (None, 0):
                width = -2
            if height in (None, 0):
                height = -2
            filters.append(scale_filter(width, height, mode="fit", pad=True, pad_color="black"))
        fps = get_float(options, "fps", None, minimum=0.01, maximum=240)
        if fps:
            filters.append(f"fps={rate_str(fps)}")
        args += ["-map", "0:v:0?", "-map", "0:a:0?", "-sn", "-dn"]
        if filters:
            if codec_name(options, "video_codec", "libx264") == "copy":
                raise ValueError("video_codec=copy cannot be combined with scaling or fps filters")
            args += ["-vf", ",".join(filters)]
        args += video_encode_args(options)
        if probe.get("has_audio"):
            args += audio_encode_args(options, default_codec="aac")
        else:
            audio_codec = get_str(options, "audio_codec", "")
            if audio_codec and audio_codec != "copy":
                args += ["-an"]
    else:
        args += ["-vn", "-sn", "-dn", "-map", "0:a:0?"]
        codec = get_str(options, "audio_codec", "")
        if codec:
            options = {**options, "audio_codec": codec}
        args += audio_encode_args(options, default_codec=audio_codec_for_target(target, "aac"))
        fmt = fmt if fmt in AUDIO_FORMATS else "m4a"
    if get_bool(options, "shortest", False):
        args += ["-shortest"]
    if media == "audio" and fmt:
        args += ["-f", fmt]
    elif get_str(options, "format", ""):
        args += ["-f", get_str(options, "format", "")]
    args += movflags_args(options, target)
    args += [str(target)]

    duration = probe.get("duration")
    await run_ffmpeg(
        args,
        job_id=hooks.job_id,
        hooks=hooks,
        duration=duration,
        progress_start=3,
        progress_end=96,
        stage="Transcoding",
    )
    await verify_output(target, operation)
    return OperationResult(
        files=[target],
        data={
            "operation": operation,
            "media": media,
            "format": fmt,
            "input": {"duration": probe.get("duration"), "format": probe.get("format_name"), "kind": probe.get("kind")},
        },
        message=f"Transcoded {input_path.name}",
    )


async def extract_audio(
    *,
    input_path: Path,
    options: dict[str, Any],
    payload: dict[str, Any],
    workdir: Path,
    hooks: ExecutionHooks,
    operation: str,
) -> OperationResult:
    probe = await probe_media(input_path)
    if not probe.get("has_audio"):
        raise ValueError("Input has no audio stream")
    fmt = get_str(options, "format", "").lower()
    if not fmt:
        suffix = Path(str(payload.get("output_path") or "")).suffix.lower().lstrip(".")
        fmt = suffix if suffix in AUDIO_FORMATS else "mp3"
    if fmt not in AUDIO_FORMATS:
        raise ValueError(f"Unsupported audio format: {fmt}")
    spec = AUDIO_FORMATS[fmt]
    target = resolve_output(workdir, input_path, operation, payload.get("output_path"), spec["extension"])
    codec = get_str(options, "audio_codec", "") or spec["codec"]

    args = ["-i", str(input_path), "-vn", "-sn", "-dn", "-map", "0:a:0?"]
    args += ["-c:a", codec]
    bitrate = get_str(options, "audio_bitrate", "") or get_str(options, "bitrate", "")
    if bitrate and codec not in {"flac", "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "alac"}:
        args += ["-b:a", bitrate]
    sample_rate = get_int(options, "sample_rate", None, minimum=1000, maximum=384000)
    if sample_rate:
        args += ["-ar", str(sample_rate)]
    channels = get_int(options, "channels", None, minimum=1, maximum=32)
    if channels:
        args += ["-ac", str(channels)]
    if get_bool(options, "normalize", False):
        args += [
            "-af",
            (
                f"loudnorm=I={get_float(options, 'target_lufs', -16):g}"
                f":TP={get_float(options, 'true_peak', -1.5):g}"
                f":LRA={get_float(options, 'lra', 11):g}"
            ),
        ]
    args += movflags_args(options, target)
    args += [str(target)]
    await run_ffmpeg(
        args,
        job_id=hooks.job_id,
        hooks=hooks,
        duration=probe.get("duration"),
        progress_start=3,
        progress_end=96,
        stage="Extracting audio",
    )
    await verify_output(target, operation)
    return OperationResult(
        files=[target],
        data={
            "operation": operation,
            "format": fmt,
            "codec": codec,
            "sample_rate": sample_rate or (probe.get("audio") or {}).get("sample_rate"),
            "channels": channels or (probe.get("audio") or {}).get("channels"),
        },
        message=f"Extracted audio to {target.name}",
    )


async def trim(
    *,
    input_path: Path,
    options: dict[str, Any],
    payload: dict[str, Any],
    workdir: Path,
    hooks: ExecutionHooks,
    operation: str,
) -> OperationResult:
    probe = await probe_media(input_path)
    total = probe.get("duration")
    start = get_float(options, "start", 0.0, minimum=0) or 0.0
    duration = get_float(options, "duration", None, minimum=0.01)
    end = get_float(options, "end", None, minimum=0)
    if duration is None and end is not None:
        duration = end - start
    if duration is None:
        if total:
            duration = max(0.01, float(total) - start)
        else:
            raise ValueError("trim requires duration or end")
    if duration <= 0:
        raise ValueError("end must be greater than start")
    if end is None:
        end = start + duration
    if total and start >= total:
        raise ValueError("start is beyond the end of the input")

    copy = get_bool(options, "copy", False)
    accurate = get_bool(options, "accurate", True)
    target = resolve_output(workdir, input_path, operation, payload.get("output_path"), suffix_for_input(input_path, ".mp4"))
    args: list[str] = []
    if copy:
        args += ["-ss", time_str(start), "-i", str(input_path), "-t", time_str(duration)]
        args += ["-map", "0", "-c", "copy", "-avoid_negative_ts", "make_zero"]
        if not accurate:
            hooks.warnings.append("Stream copy cuts on keyframes; accurate=false does not change copy behaviour.")
    else:
        if accurate:
            args += ["-i", str(input_path), "-ss", time_str(start)]
        else:
            args += ["-ss", time_str(start), "-i", str(input_path)]
        args += ["-t", time_str(duration), "-map", "0:v:0?", "-map", "0:a:0?", "-sn", "-dn"]
        args += video_encode_args(options, default_codec="libx264")
        if probe.get("has_audio"):
            args += audio_encode_args(options, default_codec="aac")
    args += format_args(options)
    args += movflags_args(options, target)
    args += [str(target)]
    await run_ffmpeg(
        args,
        job_id=hooks.job_id,
        hooks=hooks,
        duration=duration,
        progress_start=3,
        progress_end=96,
        stage="Trimming",
    )
    await verify_output(target, operation)
    return OperationResult(
        files=[target],
        data={"operation": operation, "start": start, "end": end, "duration": duration, "copy": copy, "accurate": accurate},
        message=f"Trimmed {duration:.2f}s from {input_path.name}",
    )


def _crop_geometry(probe: dict[str, Any], options: dict[str, Any], *, image: bool) -> tuple[int, int, int, int]:
    video = probe.get("video") or {}
    source_w = int(video.get("width") or 0)
    source_h = int(video.get("height") or 0)
    if not source_w or not source_h:
        raise ValueError("Could not determine input dimensions")
    width = get_int(options, "width", None, minimum=1)
    height = get_int(options, "height", None, minimum=1)
    aspect = parse_aspect(get_str(options, "aspect", ""))
    if aspect:
        if width and not height:
            height = int(round(width / aspect))
        elif height and not width:
            width = int(round(height * aspect))
        elif not width and not height:
            width, height = aspect_crop(source_w, source_h, aspect)
    if not width:
        width = source_w
    if not height:
        height = source_h
    if width > source_w or height > source_h:
        raise ValueError(f"Crop {width}x{height} is larger than the source {source_w}x{source_h}")
    x = get_int(options, "x", 0, minimum=0) or 0
    y = get_int(options, "y", 0, minimum=0) or 0
    if get_bool(options, "center", False):
        x = max(0, (source_w - width) // 2)
        y = max(0, (source_h - height) // 2)
    if x + width > source_w or y + height > source_h:
        raise ValueError("Crop rectangle extends beyond the source image")
    return width, height, x, y


async def crop_video(
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
        raise ValueError("Input has no video stream")
    width, height, x, y = _crop_geometry(probe, options, image=False)
    target = resolve_output(workdir, input_path, operation, payload.get("output_path"), suffix_for_input(input_path, ".mp4"))
    args = ["-i", str(input_path), "-vf", f"crop={width}:{height}:{x}:{y}", "-map", "0:v:0?", "-map", "0:a:0?", "-sn", "-dn"]
    args += video_encode_args(options)
    if probe.get("has_audio"):
        args += audio_encode_args(options, default_codec="copy")
    args += format_args(options)
    args += movflags_args(options, target)
    args += [str(target)]
    await run_ffmpeg(
        args,
        job_id=hooks.job_id,
        hooks=hooks,
        duration=probe.get("duration"),
        progress_start=3,
        progress_end=96,
        stage="Cropping video",
    )
    await verify_output(target, operation)
    warnings = [] if width % 2 == 0 and height % 2 == 0 else ["Odd crop dimensions may fail with yuv420p encoders; use even width/height."]
    return OperationResult(
        files=[target],
        data={"operation": operation, "crop": {"width": width, "height": height, "x": x, "y": y}, "warnings": warnings},
        message=f"Cropped video to {width}x{height}",
    )


async def crop_image(
    *,
    input_path: Path,
    options: dict[str, Any],
    payload: dict[str, Any],
    workdir: Path,
    hooks: ExecutionHooks,
    operation: str,
) -> OperationResult:
    probe = await probe_media(input_path)
    if not probe.get("image"):
        raise ValueError("crop_image requires a still image")
    width, height, x, y = _crop_geometry(probe, options, image=True)
    fmt = get_str(options, "format", "")
    if not fmt:
        suffix = Path(str(payload.get("output_path") or "")).suffix.lower().lstrip(".")
        fmt = suffix if suffix in {"png", "jpg", "jpeg", "webp"} else "png"
    if fmt not in {"png", "jpg", "jpeg", "webp"}:
        raise ValueError("format must be png, jpg or webp")
    ext = ".jpg" if fmt in {"jpg", "jpeg"} else f".{fmt}"
    target = resolve_output(workdir, input_path, operation, payload.get("output_path"), ext)
    args = [
        "-i",
        str(input_path),
        "-vf",
        f"crop={width}:{height}:{x}:{y}",
        "-frames:v",
        "1",
        "-update",
        "1",
        "-an",
        "-sn",
    ]
    quality = get_int(options, "quality", 2, minimum=2, maximum=31)
    if fmt in {"jpg", "jpeg", "webp"} and quality is not None:
        args += ["-q:v", str(quality)]
    args += [str(target)]
    await run_ffmpeg(args, job_id=hooks.job_id, hooks=hooks, progress_start=5, progress_end=95, stage="Cropping image")
    await verify_output(target, operation)
    return OperationResult(
        files=[target],
        data={"operation": operation, "crop": {"width": width, "height": height, "x": x, "y": y}, "format": fmt},
        message=f"Cropped image to {width}x{height}",
    )


async def scale(
    *,
    input_path: Path,
    options: dict[str, Any],
    payload: dict[str, Any],
    workdir: Path,
    hooks: ExecutionHooks,
    operation: str,
) -> OperationResult:
    probe = await probe_media(input_path)
    is_image = bool(probe.get("image"))
    width = get_int(options, "width", None, minimum=-2)
    height = get_int(options, "height", None, minimum=-2)
    mode = get_str(options, "mode", "fit").lower()
    pad = get_bool(options, "pad", True)
    no_upscale = get_bool(options, "no_upscale", False)
    video = probe.get("video") or {}
    source_w = int(video.get("width") or 0)
    source_h = int(video.get("height") or 0)
    if no_upscale and source_w and source_h:
        if width and width > 0:
            width = min(width, source_w)
        if height and height > 0:
            height = min(height, source_h)
    if width in (None, 0):
        width = -2
    if height in (None, 0):
        height = -2
    if width == -2 and height == -2:
        raise ValueError("scale requires width or height")
    filter_expr = scale_filter(width, height, mode=mode, pad=pad, pad_color=get_str(options, "pad_color", "black"), no_upscale=no_upscale)

    if is_image:
        fmt = get_str(options, "format", "")
        if not fmt:
            suffix = Path(str(payload.get("output_path") or "")).suffix.lower().lstrip(".")
            fmt = suffix if suffix in {"png", "jpg", "jpeg", "webp"} else "png"
        ext = ".jpg" if fmt in {"jpg", "jpeg"} else f".{fmt}"
        target = resolve_output(workdir, input_path, operation, payload.get("output_path"), ext)
        args = ["-i", str(input_path), "-vf", filter_expr, "-frames:v", "1", "-update", "1", "-an", "-sn"]
        quality = get_int(options, "quality", 2, minimum=2, maximum=31)
        if fmt in {"jpg", "jpeg", "webp"} and quality is not None:
            args += ["-q:v", str(quality)]
        args += [str(target)]
        await run_ffmpeg(args, job_id=hooks.job_id, hooks=hooks, progress_start=5, progress_end=95, stage="Scaling image")
    else:
        target = resolve_output(workdir, input_path, operation, payload.get("output_path"), suffix_for_input(input_path, ".mp4"))
        args = ["-i", str(input_path), "-vf", filter_expr, "-map", "0:v:0?", "-map", "0:a:0?", "-sn", "-dn"]
        args += video_encode_args(options)
        if probe.get("has_audio"):
            args += audio_encode_args(options, default_codec="copy")
        args += format_args(options)
        args += movflags_args(options, target)
        args += [str(target)]
        await run_ffmpeg(
            args,
            job_id=hooks.job_id,
            hooks=hooks,
            duration=probe.get("duration"),
            progress_start=3,
            progress_end=96,
            stage="Scaling video",
        )
    await verify_output(target, operation)
    return OperationResult(
        files=[target],
        data={"operation": operation, "width": width, "height": height, "mode": mode, "filter": filter_expr},
        message=f"Scaled {input_path.name} to {width}x{height}",
    )


def _rotate_filter(options: dict[str, Any]) -> str:
    angle = get_float(options, "angle", 90.0) or 0.0
    normalized = angle % 360
    filters: list[str] = []
    if abs(normalized - 90) < 0.001 or abs(normalized - 270) < 0.001:
        filters.append("transpose=1" if abs(normalized - 90) < 0.001 else "transpose=2")
    elif abs(normalized - 180) < 0.001:
        filters += ["hflip", "vflip"]
    elif abs(normalized) > 0.001:
        expression = f"{angle}*PI/180"
        filters.append(
            f"rotate={expression}:ow=rotw({expression}):oh=roth({expression}):fillcolor={color_value(get_str(options, 'fill_color', 'black'))}"
        )
    if get_bool(options, "flip_h", False):
        filters.append("hflip")
    if get_bool(options, "flip_v", False):
        filters.append("vflip")
    if not filters:
        filters.append("null")
    return ",".join(filters)


async def rotate(
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
        raise ValueError("Input has no video stream")
    target = resolve_output(workdir, input_path, operation, payload.get("output_path"), suffix_for_input(input_path, ".mp4"))
    filter_expr = _rotate_filter(options)
    args = ["-i", str(input_path), "-vf", filter_expr, "-map", "0:v:0?", "-map", "0:a:0?", "-sn", "-dn"]
    args += video_encode_args(options)
    if probe.get("has_audio"):
        args += audio_encode_args(options, default_codec="copy")
    args += format_args(options)
    args += movflags_args(options, target)
    args += [str(target)]
    await run_ffmpeg(
        args,
        job_id=hooks.job_id,
        hooks=hooks,
        duration=probe.get("duration"),
        progress_start=3,
        progress_end=96,
        stage="Rotating video",
    )
    await verify_output(target, operation)
    return OperationResult(files=[target], data={"operation": operation, "filter": filter_expr}, message="Rotated video")


async def rotate_image(
    *,
    input_path: Path,
    options: dict[str, Any],
    payload: dict[str, Any],
    workdir: Path,
    hooks: ExecutionHooks,
    operation: str,
) -> OperationResult:
    probe = await probe_media(input_path)
    if not probe.get("image"):
        raise ValueError("rotate_image requires a still image")
    fmt = get_str(options, "format", "")
    if not fmt:
        suffix = Path(str(payload.get("output_path") or "")).suffix.lower().lstrip(".")
        fmt = suffix if suffix in {"png", "jpg", "jpeg", "webp"} else "png"
    ext = ".jpg" if fmt in {"jpg", "jpeg"} else f".{fmt}"
    target = resolve_output(workdir, input_path, operation, payload.get("output_path"), ext)
    filter_expr = _rotate_filter(options)
    args = ["-i", str(input_path), "-vf", filter_expr, "-frames:v", "1", "-update", "1", "-an", "-sn"]
    quality = get_int(options, "quality", 2, minimum=2, maximum=31)
    if fmt in {"jpg", "jpeg", "webp"} and quality is not None:
        args += ["-q:v", str(quality)]
    args += [str(target)]
    await run_ffmpeg(args, job_id=hooks.job_id, hooks=hooks, progress_start=5, progress_end=95, stage="Rotating image")
    await verify_output(target, operation)
    return OperationResult(files=[target], data={"operation": operation, "filter": filter_expr}, message="Rotated image")


async def speed(
    *,
    input_path: Path,
    options: dict[str, Any],
    payload: dict[str, Any],
    workdir: Path,
    hooks: ExecutionHooks,
    operation: str,
) -> OperationResult:
    probe = await probe_media(input_path)
    factor = get_float(options, "factor", 1.0, minimum=0.1, maximum=100) or 1.0
    video_factor = get_float(options, "video_factor", factor, minimum=0.1, maximum=100) or factor
    audio_factor = get_float(options, "audio_factor", factor, minimum=0.1, maximum=100) or factor
    target = resolve_output(workdir, input_path, operation, payload.get("output_path"), suffix_for_input(input_path, ".mp4"))
    args: list[str] = []
    if probe.get("has_video"):
        args += ["-i", str(input_path), "-vf", f"setpts=PTS/{video_factor:.6f}"]
    else:
        args += ["-i", str(input_path)]
    if probe.get("has_audio"):
        if get_bool(options, "pitch_correction", True):
            audio_filter = ",".join(atempo_chain(audio_factor))
        else:
            sample_rate = int((probe.get("audio") or {}).get("sample_rate") or 48000)
            audio_filter = f"asetrate={sample_rate}*{audio_factor:.6f},aresample={sample_rate}"
        args += ["-af", audio_filter]
    args += ["-map", "0:v:0?", "-map", "0:a:0?", "-sn", "-dn"]
    if probe.get("has_video"):
        args += video_encode_args(options)
    if probe.get("has_audio"):
        args += audio_encode_args(options, default_codec=audio_codec_for_target(target, "aac"))
    args += ["-shortest"]
    args += format_args(options)
    args += movflags_args(options, target)
    args += [str(target)]
    duration = probe.get("duration")
    await run_ffmpeg(
        args,
        job_id=hooks.job_id,
        hooks=hooks,
        duration=float(duration) / video_factor if duration else None,
        progress_start=3,
        progress_end=96,
        stage="Changing speed",
    )
    await verify_output(target, operation)
    if not probe.get("has_audio"):
        hooks.warnings.append("Input has no audio; only the video stream was retimed.")
    return OperationResult(
        files=[target],
        data={"operation": operation, "video_factor": video_factor, "audio_factor": audio_factor, "pitch_correction": get_bool(options, "pitch_correction", True)},
        message=f"Applied {factor}x speed change",
    )
