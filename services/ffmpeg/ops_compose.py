"""Composition and audio-processing FFmpeg operations."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from openstudio_common import resolve_path

from .catalog import AUDIO_FORMATS
from .executor import ExecutionHooks, probe_media, run_ffmpeg
from .operations import (
    OperationResult,
    audio_codec_for_target,
    audio_encode_args,
    color_value,
    concatenate_files,
    escape_drawtext,
    escape_filter_path,
    format_args,
    format_extension,
    get_bool,
    get_float,
    get_int,
    get_list,
    get_str,
    movflags_args,
    overlay_xy,
    rate_str,
    require_duration,
    resolve_file,
    resolve_output,
    subtitle_force_style,
    suffix_for_input,
    time_str,
    verify_output,
    video_encode_args,
)


async def concat(
    *,
    input_path: Path | None,
    options: dict[str, Any],
    payload: dict[str, Any],
    workdir: Path,
    hooks: ExecutionHooks,
    operation: str,
) -> OperationResult:
    raw_files = get_list(options, "files")
    if len(raw_files) < 1:
        raise ValueError("concat requires a non-empty files list")
    files: list[Path] = []
    for item in raw_files:
        if not isinstance(item, str):
            raise ValueError("files must contain strings")
        files.append(resolve_file(item, "concat input"))
    reencode = get_bool(options, "reencode", False)
    copy = get_bool(options, "copy", True) and not reencode
    fmt = get_str(options, "format", "")
    default_ext = format_extension(fmt, suffix_for_input(files[0], ".mp4")) if fmt else suffix_for_input(files[0], ".mp4")
    target = resolve_output(workdir, files[0], operation, payload.get("output_path"), default_ext)
    if target.resolve() in {path.resolve() for path in files}:
        raise ValueError("output_path must not overwrite a concat input")
    transition = get_str(options, "transition", "")
    transition_duration = get_float(options, "transition_duration", 0.5, minimum=0.05, maximum=10) or 0.5

    if transition:
        if len(files) < 2:
            raise ValueError("xfade transitions require at least two files")
        if transition not in {
            "fade", "fadeblack", "fadewhite", "wipeleft", "wiperight", "wipeup", "wipedown",
            "slideleft", "slideright", "slideup", "slidedown", "circlecrop", "rectcrop",
            "distance", "pixelize", "radial", "smoothleft", "smoothright", "smoothup",
            "smoothdown", "circleopen", "circleclose", "dissolve", "horzopen", "horzclose",
            "vertopen", "vertclose",
        }:
            raise ValueError(f"Unsupported xfade transition: {transition}")
        probes = [await probe_media(path) for path in files]
        for path, probe in zip(files, probes):
            if not probe.get("has_video"):
                raise ValueError(f"{path.name} has no video stream")
        durations = [require_duration(probe, path) for path, probe in zip(files, probes)]
        base_video = probes[0].get("video") or {}
        width = get_int(options, "width", None, minimum=2) or int(base_video.get("width") or 1280)
        height = get_int(options, "height", None, minimum=2) or int(base_video.get("height") or 720)
        fps = get_float(options, "fps", None, minimum=0.01, maximum=240) or float(base_video.get("fps") or 30)
        filters: list[str] = []
        for index in range(len(files)):
            filters.append(
                f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={rate_str(fps)},"
                f"setpts=PTS-STARTPTS[v{index}]"
            )
        cumulative = durations[0]
        last_video = "v0"
        for index in range(1, len(files)):
            offset = max(0.0, cumulative - transition_duration)
            label = f"vx{index}"
            filters.append(
                f"[{last_video}][v{index}]xfade=transition={transition}:duration={transition_duration:.3f}:offset={offset:.3f}[{label}]"
            )
            last_video = label
            cumulative = cumulative + durations[index] - transition_duration
        all_audio = all(probe.get("has_audio") for probe in probes)
        audio_label = None
        if all_audio:
            for index, duration in enumerate(durations):
                filters.append(f"[{index}:a]asetpts=PTS-STARTPTS,atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[a{index}]")
            last_audio = "a0"
            for index in range(1, len(files)):
                label = f"ax{index}"
                filters.append(f"[{last_audio}][a{index}]acrossfade=d={transition_duration:.3f}:c1=tri:c2=tri[{label}]")
                last_audio = label
            audio_label = last_audio
        else:
            hooks.warnings.append("Not all clips have audio; the transition output is silent.")
        args = []
        for path in files:
            args += ["-i", str(path)]
        args += ["-filter_complex", ";".join(filters), "-map", f"[{last_video}]"]
        if audio_label:
            args += ["-map", f"[{audio_label}]"]
        else:
            args += ["-an"]
        args += video_encode_args(options)
        if audio_label:
            args += audio_encode_args(options, default_codec="aac")
        args += format_args(options)
        args += movflags_args(options, target)
        args += [str(target)]
        await run_ffmpeg(
            args,
            job_id=hooks.job_id,
            hooks=hooks,
            duration=cumulative,
            progress_start=3,
            progress_end=96,
            stage="Concatenating with transitions",
        )
        await verify_output(target, operation)
        return OperationResult(
            files=[target],
            data={
                "operation": operation,
                "method": "xfade",
                "transition": transition,
                "inputs": [str(path) for path in files],
                "width": width,
                "height": height,
                "fps": fps,
            },
            message=f"Concatenated {len(files)} clips with {transition}",
        )

    list_file: Path | None = None
    try:
        if copy:
            concat_args, list_file = await concatenate_files(
                files, job_id=hooks.job_id, hooks=hooks, workdir=workdir, copy=True, args_extra=[]
            )
            args = [*concat_args, "-map", "0", "-c", "copy"]
            args += format_args(options)
            args += [str(target)]
            await run_ffmpeg(
                args,
                job_id=hooks.job_id,
                hooks=hooks,
                progress_start=3,
                progress_end=96,
                stage="Concatenating",
            )
        else:
            concat_args, list_file = await concatenate_files(
                files, job_id=hooks.job_id, hooks=hooks, workdir=workdir, copy=False, args_extra=[]
            )
            args = [*concat_args, "-map", "0:v:0?", "-map", "0:a:0?", "-sn", "-dn"]
            args += video_encode_args(options)
            args += audio_encode_args(options, default_codec="aac")
            args += format_args(options)
            args += movflags_args(options, target)
            args += [str(target)]
            await run_ffmpeg(
                args,
                job_id=hooks.job_id,
                hooks=hooks,
                progress_start=3,
                progress_end=96,
                stage="Concatenating and re-encoding",
            )
    finally:
        if list_file is not None:
            list_file.unlink(missing_ok=True)
    await verify_output(target, operation)
    return OperationResult(
        files=[target],
        data={"operation": operation, "method": "demuxer", "copy": copy, "inputs": [str(path) for path in files]},
        message=f"Concatenated {len(files)} files",
    )


def _overlay_scale(base_width: int, value: str) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("%"):
        try:
            percent = float(text[:-1])
        except ValueError as exc:
            raise ValueError("scale percentage is invalid") from exc
        pixels = max(1, int(round(base_width * percent / 100.0)))
        return f"scale={pixels}:-2"
    if "x" in text.lower():
        width, _, height = text.lower().partition("x")
        return f"scale={width or -2}:{height or -2}"
    try:
        number = float(text)
    except ValueError as exc:
        raise ValueError("scale must be pixels, WxH or a percentage") from exc
    if 0 < number <= 1:
        return f"scale={max(1, int(round(base_width * number)))}:-2"
    return f"scale={max(1, int(round(number)))}:-2"


async def overlay(
    *,
    input_path: Path,
    options: dict[str, Any],
    payload: dict[str, Any],
    workdir: Path,
    hooks: ExecutionHooks,
    operation: str,
) -> OperationResult:
    base = await probe_media(input_path)
    if not base.get("video"):
        raise ValueError("overlay requires a video or image input")
    is_image = bool(base.get("image"))
    mode = get_str(options, "mode", "image").lower()
    position = get_str(options, "position", "bottom-right").lower()
    margin = get_int(options, "margin", 16, minimum=0, maximum=2000) or 0
    opacity = get_float(options, "opacity", 1.0, minimum=0.0, maximum=1.0)
    if opacity is None:
        opacity = 1.0
    overlay_width = int((base.get("video") or {}).get("width") or 0)
    x_opt = get_int(options, "x", None, minimum=0)
    y_opt = get_int(options, "y", None, minimum=0)
    fmt = get_str(options, "format", "")
    if is_image:
        ext = format_extension(fmt, ".png") if fmt else ".png"
        target = resolve_output(workdir, input_path, operation, payload.get("output_path"), ext)
    else:
        target = resolve_output(workdir, input_path, operation, payload.get("output_path"), suffix_for_input(input_path, ".mp4"))

    if mode in {"image", "watermark"}:
        overlay_path = resolve_file(options.get("overlay_path"), "overlay_path")
        scale_expr = _overlay_scale(overlay_width, get_str(options, "scale", ""))
        x, y = overlay_xy(position, margin, text=False, x=x_opt, y=y_opt)
        chain = ["format=rgba"]
        if scale_expr:
            chain.append(scale_expr)
        chain.append(f"colorchannelmixer=aa={opacity:.4f}")
        filters = f"[1:v]{','.join(chain)}[ov];[0:v][ov]overlay={x}:{y}:format=auto[v]"
        args = ["-i", str(input_path), "-i", str(overlay_path), "-filter_complex", filters, "-map", "[v]"]
        if not is_image:
            args += ["-map", "0:a:0?", "-sn", "-dn"]
        args += video_encode_args(options)
        if not is_image and base.get("has_audio"):
            args += audio_encode_args(options, default_codec="copy")
        if is_image:
            args += ["-frames:v", "1", "-update", "1"]
        args += format_args(options)
        args += [str(target)]
    elif mode == "text":
        text = get_str(options, "text", "")
        if not text:
            raise ValueError("text is required when mode=text")
        font_file = get_str(options, "font_file", "")
        font = get_str(options, "font", "DejaVu Sans")
        font_size = get_int(options, "font_size", 36, minimum=4, maximum=512) or 36
        x, y = overlay_xy(position, margin, text=True, x=x_opt, y=y_opt)
        draw = [
            f"text='{escape_drawtext(text)}'",
            f"fontsize={font_size}",
            f"fontcolor={color_value(get_str(options, 'font_color', 'white'))}",
            f"borderw={get_int(options, 'border_width', 0, minimum=0, maximum=32) or 0}",
            f"bordercolor={color_value(get_str(options, 'border_color', 'black'))}",
            f"shadowx={get_int(options, 'shadow', 0, minimum=0, maximum=32) or 0}",
            f"shadowy={get_int(options, 'shadow', 0, minimum=0, maximum=32) or 0}",
            f"alpha={opacity:.4f}",
            f"x={x}",
            f"y={y}",
        ]
        if font_file:
            draw.append(f"fontfile='{escape_filter_path(resolve_file(font_file, 'font_file'))}'")
        elif font:
            draw.append(f"font='{escape_filter_path(font)}'")
        if get_bool(options, "box", False):
            draw += ["box=1", f"boxcolor={color_value(get_str(options, 'box_color', 'black@0.5'))}"]
        args = ["-i", str(input_path), "-vf", "drawtext=" + ":".join(draw), "-map", "0:v:0"]
        if not is_image:
            args += ["-map", "0:a:0?", "-sn", "-dn"]
        args += video_encode_args(options)
        if not is_image and base.get("has_audio"):
            args += audio_encode_args(options, default_codec="copy")
        if is_image:
            args += ["-frames:v", "1", "-update", "1"]
        args += format_args(options)
        args += [str(target)]
    else:
        raise ValueError("mode must be image, watermark or text")

    await run_ffmpeg(
        args,
        job_id=hooks.job_id,
        hooks=hooks,
        duration=base.get("duration") if not is_image else None,
        progress_start=3,
        progress_end=96,
        stage="Compositing overlay",
    )
    await verify_output(target, operation)
    return OperationResult(
        files=[target],
        data={"operation": operation, "mode": mode, "position": position, "opacity": opacity},
        message=f"Applied {mode} overlay",
    )


async def subtitles(
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
        raise ValueError("subtitles requires a video input")
    subtitle_path = resolve_file(options.get("subtitle_path"), "subtitle_path")
    suffix = subtitle_path.suffix.lower()
    if suffix not in {".srt", ".vtt", ".ass", ".ssa"}:
        raise ValueError("subtitle_path must be .srt, .vtt, .ass or .ssa")
    fontsdir = get_str(options, "fontsdir", "")
    if fontsdir:
        fonts_path = resolve_path(fontsdir)
        if not fonts_path.exists() or not fonts_path.is_dir():
            raise ValueError("fontsdir must point to an existing folder")
        fontsdir_arg = f":fontsdir='{escape_filter_path(fonts_path)}'"
    else:
        fontsdir_arg = ""
    style = subtitle_force_style(options).replace("'", "")
    filter_expr = f"subtitles=filename='{escape_filter_path(subtitle_path)}':force_style='{style}'{fontsdir_arg}"
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
        stage="Burning subtitles",
    )
    await verify_output(target, operation)
    return OperationResult(
        files=[target],
        data={"operation": operation, "subtitle": str(subtitle_path), "burned": True},
        message=f"Burned subtitles into {target.name}",
    )


async def _merge_impl(
    *,
    operation: str,
    input_path: Path,
    options: dict[str, Any],
    payload: dict[str, Any],
    workdir: Path,
    hooks: ExecutionHooks,
    require_audio: bool,
) -> OperationResult:
    video_probe = await probe_media(input_path)
    if not video_probe.get("has_video"):
        raise ValueError(f"{operation} requires a video input")
    audio_raw = get_str(options, "audio_path", "")
    if require_audio and not audio_raw:
        raise ValueError("audio_path is required")
    audio_path = resolve_file(audio_raw, "audio_path") if audio_raw else None
    audio_probe = await probe_media(audio_path) if audio_path else None
    if audio_probe and not audio_probe.get("has_audio"):
        raise ValueError("audio_path has no audio stream")
    replace = get_bool(options, "replace", True) if operation == "merge" else get_bool(options, "mute_original", True)
    shortest = get_bool(options, "shortest", False)
    copy_video = get_bool(options, "copy_video", True)
    original_volume = get_float(options, "original_volume", 1.0, minimum=0.0, maximum=8.0) or 1.0
    new_volume = get_float(options, "new_volume", 1.0, minimum=0.0, maximum=8.0) or 1.0
    target = resolve_output(workdir, input_path, operation, payload.get("output_path"), suffix_for_input(input_path, ".mp4"))

    if audio_path is None:
        if operation != "replace_audio":
            raise ValueError("audio_path is required")
        args = ["-i", str(input_path), "-map", "0:v:0", "-an"]
        if copy_video:
            args += ["-c:v", "copy"]
        else:
            args += video_encode_args(options)
        args += format_args(options)
        args += movflags_args(options, target)
        args += [str(target)]
        await run_ffmpeg(args, job_id=hooks.job_id, hooks=hooks, duration=video_probe.get("duration"), progress_start=3, progress_end=96, stage="Muting audio")
        await verify_output(target, operation)
        return OperationResult(files=[target], data={"operation": operation, "muted": True}, message="Muted original audio")

    if replace:
        args = ["-i", str(input_path), "-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0"]
        if copy_video:
            args += ["-c:v", "copy"]
        else:
            args += video_encode_args(options)
        if new_volume != 1.0:
            args += ["-af", f"volume={new_volume:g}"]
        args += audio_encode_args(options, default_codec="aac")
        if shortest:
            args += ["-shortest"]
        args += format_args(options)
        args += movflags_args(options, target)
        args += [str(target)]
    else:
        if video_probe.get("has_audio"):
            filters = (
                f"[0:a]volume={original_volume:g}[a0];"
                f"[1:a]volume={new_volume:g}[a1];"
                f"[a0][a1]amix=inputs=2:duration=longest:dropout_transition=0[aout]"
            )
            args = ["-i", str(input_path), "-i", str(audio_path), "-filter_complex", filters, "-map", "0:v:0", "-map", "[aout]"]
        else:
            args = ["-i", str(input_path), "-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0"]
            if new_volume != 1.0:
                args += ["-af", f"volume={new_volume:g}"]
            hooks.warnings.append("The video had no original audio; the new track was attached directly.")
        if copy_video:
            args += ["-c:v", "copy"]
        else:
            args += video_encode_args(options)
        args += audio_encode_args(options, default_codec="aac")
        if shortest:
            args += ["-shortest"]
        args += format_args(options)
        args += movflags_args(options, target)
        args += [str(target)]

    await run_ffmpeg(
        args,
        job_id=hooks.job_id,
        hooks=hooks,
        duration=video_probe.get("duration"),
        progress_start=3,
        progress_end=96,
        stage="Merging audio",
    )
    await verify_output(target, operation)
    return OperationResult(
        files=[target],
        data={
            "operation": operation,
            "replace": replace,
            "shortest": shortest,
            "audio": str(audio_path),
            "original_volume": original_volume,
            "new_volume": new_volume,
        },
        message="Replaced audio" if replace else "Merged audio",
    )


async def merge(
    *,
    input_path: Path,
    options: dict[str, Any],
    payload: dict[str, Any],
    workdir: Path,
    hooks: ExecutionHooks,
    operation: str,
) -> OperationResult:
    return await _merge_impl(
        operation=operation,
        input_path=input_path,
        options=options,
        payload=payload,
        workdir=workdir,
        hooks=hooks,
        require_audio=True,
    )


async def replace_audio(
    *,
    input_path: Path,
    options: dict[str, Any],
    payload: dict[str, Any],
    workdir: Path,
    hooks: ExecutionHooks,
    operation: str,
) -> OperationResult:
    return await _merge_impl(
        operation=operation,
        input_path=input_path,
        options=options,
        payload=payload,
        workdir=workdir,
        hooks=hooks,
        require_audio=False,
    )


async def volume(
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
    if get_bool(options, "normalize", False):
        audio_filter = (
            f"loudnorm=I={get_float(options, 'target_lufs', -16):g}"
            f":TP={get_float(options, 'true_peak', -1.5):g}"
            f":LRA={get_float(options, 'lra', 11):g}"
        )
    else:
        gain = get_float(options, "gain", None)
        if gain is not None:
            if gain < 0:
                raise ValueError("gain must be positive; use gain_db for attenuation")
            audio_filter = f"volume={gain:g}"
        else:
            gain_db = get_float(options, "gain_db", 0) or 0.0
            audio_filter = f"volume={gain_db:g}dB"
    target = resolve_output(workdir, input_path, operation, payload.get("output_path"), suffix_for_input(input_path, ".mp4"))
    args: list[str] = ["-i", str(input_path)]
    if probe.get("has_video"):
        args += ["-map", "0:v:0?", "-map", "0:a:0?", "-sn", "-dn", "-af", audio_filter]
        if get_bool(options, "copy_video", True):
            args += ["-c:v", "copy"]
        else:
            args += video_encode_args(options)
    else:
        args += ["-vn", "-map", "0:a:0?", "-af", audio_filter]
    args += audio_encode_args(options, default_codec=audio_codec_for_target(target, "aac"))
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
        stage="Adjusting volume",
    )
    await verify_output(target, operation)
    return OperationResult(files=[target], data={"operation": operation, "filter": audio_filter}, message="Adjusted volume")


def _loudnorm_filter(options: dict[str, Any], measured: dict[str, Any] | None) -> str:
    base = (
        f"loudnorm=I={get_float(options, 'target_lufs', -16):g}"
        f":TP={get_float(options, 'true_peak', -1.5):g}"
        f":LRA={get_float(options, 'lra', 11):g}"
    )
    if get_bool(options, "dual_mono", False):
        base += ":dual_mono=true"
    if measured:
        base += (
            f":measured_I={measured.get('input_i')}"
            f":measured_TP={measured.get('input_tp')}"
            f":measured_LRA={measured.get('input_lra')}"
            f":measured_thresh={measured.get('input_thresh')}"
            f":offset={measured.get('target_offset', '0')}"
            ":linear=true"
        )
    return base


def _parse_loudnorm(stderr: str) -> dict[str, Any] | None:
    matches = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr, re.S)
    if not matches:
        return None
    for candidate in reversed(matches):
        try:
            import json

            data = json.loads(candidate)
            if data.get("input_i") is not None:
                return data
        except Exception:  # noqa: BLE001
            continue
    return None


async def normalize(
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
    keep_video = get_bool(options, "keep_video", False)
    fmt = get_str(options, "format", "")
    if not fmt:
        suffix = Path(str(payload.get("output_path") or "")).suffix.lower().lstrip(".")
        if suffix in AUDIO_FORMATS:
            fmt = suffix
        else:
            fmt = "mp4" if keep_video else "wav"
    if keep_video:
        extension = ".mp4" if fmt in {"mp4", "m4a"} else format_extension(fmt, ".mp4")
    else:
        if fmt not in AUDIO_FORMATS:
            raise ValueError(f"Unsupported audio output format: {fmt}")
        extension = AUDIO_FORMATS[fmt]["extension"]
    target = resolve_output(workdir, input_path, operation, payload.get("output_path"), extension)

    analysis_filter = _loudnorm_filter(options, None) + ":print_format=json"
    analysis_args = ["-i", str(input_path), "-vn", "-map", "0:a:0?", "-af", analysis_filter, "-f", "null", "-"]
    analysis = await run_ffmpeg(
        analysis_args,
        job_id=hooks.job_id,
        hooks=hooks,
        duration=probe.get("duration"),
        progress_start=3,
        progress_end=38,
        stage="Measuring loudness",
    )
    measured = _parse_loudnorm(analysis.stderr)
    if measured is None:
        hooks.warnings.append("Could not parse loudnorm measurements; falling back to a single-pass estimate.")
    final_filter = _loudnorm_filter(options, measured) + ":print_format=summary"
    sample_rate = get_int(options, "sample_rate", None, minimum=1000, maximum=384000)
    args: list[str] = ["-i", str(input_path)]
    if keep_video:
        args += ["-map", "0:v:0?", "-map", "0:a:0?", "-c:v", "copy", "-sn", "-dn", "-af", final_filter]
        codec = get_str(options, "audio_codec", "aac") or "aac"
        args += ["-c:a", codec]
        if codec not in {"flac", "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "alac"}:
            bitrate = get_str(options, "audio_bitrate", "192k")
            if bitrate:
                args += ["-b:a", bitrate]
    else:
        spec = AUDIO_FORMATS[fmt]
        codec = get_str(options, "audio_codec", "") or spec["codec"]
        args += ["-vn", "-sn", "-dn", "-map", "0:a:0?", "-af", final_filter, "-c:a", codec]
        if codec not in {"flac", "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "alac"}:
            bitrate = get_str(options, "audio_bitrate", "192k")
            if bitrate:
                args += ["-b:a", bitrate]
    if sample_rate:
        args += ["-ar", str(sample_rate)]
    args += format_args({"format": fmt} if fmt not in {"wav", "mp3", "flac", "m4a", "opus", "ogg"} else {})
    args += movflags_args(options, target)
    args += [str(target)]
    await run_ffmpeg(
        args,
        job_id=hooks.job_id,
        hooks=hooks,
        duration=probe.get("duration"),
        progress_start=40,
        progress_end=97,
        stage="Applying loudness normalization",
    )
    await verify_output(target, operation)
    return OperationResult(
        files=[target],
        data={
            "operation": operation,
            "measured": measured,
            "target_lufs": get_float(options, "target_lufs", -16),
            "true_peak": get_float(options, "true_peak", -1.5),
            "lra": get_float(options, "lra", 11),
            "two_pass": measured is not None,
            "keep_video": keep_video,
        },
        message="Normalized audio loudness",
    )
