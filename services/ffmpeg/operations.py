"""Shared helpers and dispatch for FFmpeg operations."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openstudio_common import MediaError, sanitize_name, resolve_path

from .catalog import AUDIO_FORMATS, OPERATIONS
from .executor import ExecutionHooks, probe_media, run_ffmpeg

CODEC_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".avif"}
VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".mpeg", ".mpg", ".ts"}
FORMAT_EXT = {
    "mp4": ".mp4",
    "mkv": ".mkv",
    "webm": ".webm",
    "mov": ".mov",
    "avi": ".avi",
    "ts": ".ts",
    "m4a": ".m4a",
    "mp3": ".mp3",
    "wav": ".wav",
    "flac": ".flac",
    "opus": ".opus",
    "ogg": ".ogg",
    "gif": ".gif",
    "apng": ".apng",
    "png": ".png",
    "jpg": ".jpg",
    "jpeg": ".jpg",
    "webp": ".webp",
}
NAMED_COLORS = {
    "black": "0x000000",
    "white": "0xFFFFFF",
    "red": "0xFF0000",
    "green": "0x00FF00",
    "blue": "0x0000FF",
    "yellow": "0xFFFF00",
    "cyan": "0x00FFFF",
    "magenta": "0xFF00FF",
    "gray": "0x808080",
    "grey": "0x808080",
    "orange": "0xFFA500",
}


@dataclass
class OperationResult:
    files: list[Path] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    message: str = "Completed"


def options_of(payload: dict[str, Any]) -> dict[str, Any]:
    options = payload.get("options") or {}
    if not isinstance(options, dict):
        raise ValueError("options must be an object")
    return options


def get(options: dict[str, Any], name: str, default: Any = None) -> Any:
    value = options.get(name)
    return default if value is None or value == "" else value


def get_str(options: dict[str, Any], name: str, default: str = "") -> str:
    value = options.get(name)
    if value is None or value == "":
        return default
    if not isinstance(value, (str, int, float)):
        raise ValueError(f"{name} must be a string")
    return str(value).strip()


def get_bool(options: dict[str, Any], name: str, default: bool = False) -> bool:
    value = options.get(name)
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "y"}:
        return True
    if text in {"0", "false", "no", "off", "n"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def get_int(
    options: dict[str, Any],
    name: str,
    default: int | None = None,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    value = options.get(name)
    if value is None or value == "":
        return default
    try:
        result = int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and result > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return result


def get_float(
    options: dict[str, Any],
    name: str,
    default: float | None = None,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    value = options.get(name)
    if value is None or value == "":
        return default
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and result > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return result


def get_list(options: dict[str, Any], name: str, default: list[Any] | None = None) -> list[Any]:
    value = options.get(name)
    if value is None or value == "":
        return list(default or [])
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return value


def get_dict(options: dict[str, Any], name: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
    value = options.get(name)
    if value is None or value == "":
        return dict(default or {})
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def codec_name(options: dict[str, Any], name: str, default: str) -> str:
    value = get_str(options, name, default) or default
    if not CODEC_RE.match(value):
        raise ValueError(f"{name} contains invalid characters")
    return value


def time_str(value: float) -> str:
    return f"{max(0.0, float(value)):.3f}"


def rate_str(value: float) -> str:
    return f"{float(value):.6f}".rstrip("0").rstrip(".")


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def format_extension(fmt: str, default: str = ".mp4") -> str:
    return FORMAT_EXT.get(str(fmt or "").strip().lower(), default)


def audio_codec_for_target(target: Path, default: str = "aac") -> str:
    """Pick a sensible default audio codec from the output extension."""
    suffix = target.suffix.lower()
    if suffix == ".mp3":
        return "libmp3lame"
    if suffix == ".wav":
        return "pcm_s16le"
    if suffix == ".flac":
        return "flac"
    if suffix == ".opus":
        return "libopus"
    if suffix == ".ogg":
        return "libvorbis"
    if suffix == ".aac":
        return "aac"
    if suffix in {".m4a", ".mp4", ".mov", ".mkv", ".avi", ".ts", ".webm"}:
        return default
    return default


def suffix_for_input(path: Path, default: str = ".mp4") -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES | VIDEO_SUFFIXES:
        return suffix
    return default


def default_name(input_path: Path | None, operation: str, extension: str) -> str:
    stem = sanitize_name(input_path.stem if input_path else operation, "output")
    return f"{stem}_{operation}{extension}"


def resolve_output(
    workdir: Path,
    input_path: Path | None,
    operation: str,
    output_path: Any,
    default_extension: str,
) -> Path:
    """Resolve an explicit output path or fall back to the job folder."""
    name = default_name(input_path, operation, default_extension)
    raw = str(output_path or "").strip()
    if not raw:
        target = workdir / name
    else:
        is_dir_hint = raw.endswith("/") or raw.endswith("\\")
        target = resolve_path(raw)
        if target.exists() and target.is_dir():
            target = target / name
        elif is_dir_hint:
            target.mkdir(parents=True, exist_ok=True)
            target = target / name
        elif not target.suffix:
            target = target.with_name(target.name + default_extension)
    ensure_parent(target)
    if target.exists() and target.is_dir():
        raise ValueError(f"output_path is a folder: {target}")
    if input_path is not None and target.resolve() == input_path.resolve():
        raise ValueError("output_path must differ from input_path")
    return target


def resolve_input(raw: Any, *, required: bool = True) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        if required:
            raise ValueError("input_path is required")
        return None
    path = resolve_path(text)
    if not path.exists():
        raise FileNotFoundError(text)
    if path.is_dir():
        raise ValueError(f"input_path must be a file: {text}")
    return path


def resolve_file(raw: Any, label: str, *, must_exist: bool = True) -> Path:
    text = str(raw or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    path = resolve_path(text)
    if must_exist and not path.exists():
        raise FileNotFoundError(text)
    if path.exists() and path.is_dir():
        raise ValueError(f"{label} must be a file: {text}")
    return path


def video_encode_args(
    options: dict[str, Any],
    *,
    default_codec: str = "libx264",
    crf_name: str = "crf",
    include_preset: bool = True,
) -> list[str]:
    codec = codec_name(options, "video_codec", default_codec)
    args = ["-c:v", codec]
    if codec == "copy":
        return args
    bitrate = get_str(options, "video_bitrate", "")
    if include_preset:
        preset = get_str(options, "preset", "medium")
        if preset:
            args += ["-preset", preset]
    if bitrate:
        args += ["-b:v", bitrate]
    else:
        crf = get_int(options, crf_name, 23, minimum=0, maximum=63)
        if crf is not None and codec not in {"prores_ks", "mpeg4", "libxvid"}:
            args += ["-crf", str(crf)]
    pix_fmt = get_str(options, "pix_fmt", "")
    if pix_fmt:
        args += ["-pix_fmt", pix_fmt]
    profile = get_str(options, "profile", "")
    if profile:
        args += ["-profile:v", profile]
    level = get_str(options, "level", "")
    if level:
        args += ["-level", level]
    tune = get_str(options, "tune", "")
    if tune:
        args += ["-tune", tune]
    return args


def audio_encode_args(options: dict[str, Any], *, default_codec: str = "aac", default_bitrate: str = "192k") -> list[str]:
    codec = codec_name(options, "audio_codec", default_codec)
    args = ["-c:a", codec]
    if codec in {"copy", "none"}:
        return args
    bitrate = get_str(options, "audio_bitrate", "") or get_str(options, "bitrate", "") or default_bitrate
    if bitrate and codec not in {"flac", "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "alac"}:
        args += ["-b:a", bitrate]
    sample_rate = get_int(options, "sample_rate", None, minimum=1000, maximum=384000)
    if sample_rate:
        args += ["-ar", str(sample_rate)]
    channels = get_int(options, "channels", None, minimum=1, maximum=32)
    if channels:
        args += ["-ac", str(channels)]
    return args


def movflags_args(options: dict[str, Any], target: Path) -> list[str]:
    if target.suffix.lower() in {".mp4", ".mov", ".m4a"} and get_bool(options, "movflags_faststart", True):
        return ["-movflags", "+faststart"]
    return []


def format_args(options: dict[str, Any]) -> list[str]:
    fmt = get_str(options, "format", "")
    return ["-f", fmt] if fmt else []


def audio_filter_args(options: dict[str, Any], *, default_bitrate: str = "192k") -> list[str]:
    return audio_encode_args(options, default_bitrate=default_bitrate)


def parse_size(value: str) -> tuple[int | None, int | None] | None:
    text = str(value or "").strip().lower()
    match = re.match(r"^(-?\d+)\s*[x:]\s*(-?\d+)$", text)
    if not match:
        return None
    width, height = int(match.group(1)), int(match.group(2))
    return width, height


def parse_aspect(value: str) -> float | None:
    text = str(value or "").strip()
    match = re.match(r"^(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)$", text)
    if not match:
        return None
    denominator = float(match.group(2))
    if denominator == 0:
        return None
    return float(match.group(1)) / denominator


def color_value(value: str, default: str = "black") -> str:
    text = str(value or "").strip() or default
    lower = text.lower()
    if lower in NAMED_COLORS:
        return NAMED_COLORS[lower]
    if lower.startswith("#") and len(lower) == 7:
        return "0x" + lower[1:]
    return text


def ass_color(value: str, default: str = "white") -> str:
    text = str(value or "").strip() or default
    if text.upper().startswith("&H"):
        return text
    if "@" in text:
        text = text.split("@", 1)[0]
    lower = text.lower()
    if lower in NAMED_COLORS:
        hex_value = NAMED_COLORS[lower][2:]
        return "&H00" + hex_value[4:6] + hex_value[2:4] + hex_value[0:2]
    if text.startswith("#") and len(text) == 7:
        return "&H00" + text[5:7] + text[3:5] + text[1:3]
    if re.match(r"^[0-9A-Fa-f]{6}$", text):
        return "&H00" + text[4:6] + text[2:4] + text[0:2]
    return "&H00FFFFFF"


def escape_filter_path(path: Path | str) -> str:
    text = str(path)
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def escape_drawtext(text: str) -> str:
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
        .replace("%", "\\%")
        .replace("\n", "\\n")
    )


def atempo_chain(factor: float) -> list[str]:
    factor = max(0.01, min(100.0, float(factor)))
    chain: list[str] = []
    while factor > 2.0:
        chain.append("atempo=2.0")
        factor /= 2.0
    while factor < 0.5:
        chain.append("atempo=0.5")
        factor /= 0.5
    chain.append(f"atempo={factor:.6f}")
    return chain


def scale_filter(width: Any, height: Any, *, mode: str = "fit", pad: bool = True, pad_color: str = "black", no_upscale: bool = False) -> str:
    w = str(width) if width not in (None, "") else "-2"
    h = str(height) if height not in (None, "") else "-2"
    if w == "-2" and h == "-2":
        raise ValueError("scale needs at least one of width or height")
    mode = mode if mode in {"fit", "fill", "stretch"} else "fit"
    if mode == "stretch":
        return f"scale={w}:{h}"
    if mode == "fill":
        return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    base = f"scale={w}:{h}:force_original_aspect_ratio=decrease"
    if no_upscale:
        base += ":eval=init"
    if pad and w != "-2" and h != "-2":
        return f"{base},pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={color_value(pad_color)}"
    return base


def overlay_xy(position: str, margin: int, *, text: bool = False, x: int | None = None, y: int | None = None) -> tuple[str, str]:
    position = position if position in {"top-left", "top-right", "bottom-left", "bottom-right", "center", "top", "bottom", "custom"} else "bottom-right"
    if position == "custom":
        return str(x if x is not None else 0), str(y if y is not None else 0)
    width_var = "text_w" if text else "w"
    height_var = "text_h" if text else "h"
    outer_w = "w" if text else "W"
    outer_h = "h" if text else "H"
    if position == "top-left":
        return str(margin), str(margin)
    if position == "top-right":
        return f"{outer_w}-{width_var}-{margin}", str(margin)
    if position == "bottom-left":
        return str(margin), f"{outer_h}-{height_var}-{margin}"
    if position == "bottom-right":
        return f"{outer_w}-{width_var}-{margin}", f"{outer_h}-{height_var}-{margin}"
    if position == "center":
        return f"({outer_w}-{width_var})/2", f"({outer_h}-{height_var})/2"
    if position == "top":
        return f"({outer_w}-{width_var})/2", str(margin)
    return f"({outer_w}-{width_var})/2", f"{outer_h}-{height_var}-{margin}"


def subtitle_force_style(options: dict[str, Any], *, font_default: str = "DejaVu Sans", size_default: int = 24) -> str:
    font = get_str(options, "font", font_default)
    size = get_int(options, "font_size", size_default, minimum=4, maximum=256)
    position = get_str(options, "position", "bottom").lower()
    alignment = {"top": 8, "center": 5, "bottom": 2}.get(position, 2)
    fields = [
        f"FontName={font}",
        f"FontSize={size}",
        f"PrimaryColour={ass_color(get_str(options, 'color', 'white'))}",
        f"OutlineColour={ass_color(get_str(options, 'outline_color', 'black'))}",
        f"BackColour={ass_color(get_str(options, 'back_color', 'black'))}",
        f"BorderStyle={get_int(options, 'border_style', 1, minimum=1, maximum=3)}",
        f"Outline={get_float(options, 'outline', 1, minimum=0, maximum=20):g}",
        f"Shadow={get_float(options, 'shadow', 0, minimum=0, maximum=20):g}",
        f"Alignment={alignment}",
        f"MarginL={get_int(options, 'margin_l', 16, minimum=0, maximum=1000)}",
        f"MarginR={get_int(options, 'margin_r', 16, minimum=0, maximum=1000)}",
        f"MarginV={get_int(options, 'margin_v', 24, minimum=0, maximum=1000)}",
    ]
    for name, field_name in (("bold", "Bold"), ("italic", "Italic"), ("underline", "Underline"), ("strikeout", "StrikeOut")):
        if get_bool(options, name, False):
            fields.append(f"{field_name}=1")
    return ",".join(fields)


async def verify_output(path: Path, operation: str) -> None:
    if not path.exists() or path.is_dir():
        raise MediaError(f"{operation} completed but produced no output at {path.name}")


async def concatenate_files(paths: list[Path], *, job_id: str, hooks: ExecutionHooks, workdir: Path, copy: bool, args_extra: list[str]) -> tuple[list[str], Path]:
    list_file = workdir / f"concat-{job_id[:8] or 'job'}.txt"
    lines = []
    for path in paths:
        escaped = str(path).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ["-f", "concat", "-safe", "0", "-i", str(list_file)], list_file


def output_pattern(
    workdir: Path,
    input_path: Path | None,
    operation: str,
    output_path: Any,
    extension: str,
) -> tuple[Path, Path]:
    """Return (directory, filename pattern with %d) for multi-output operations."""
    stem = sanitize_name(input_path.stem if input_path else operation, "output")
    default_pattern = f"{stem}_{operation}_%03d{extension}"
    raw = str(output_path or "").strip()
    if not raw:
        directory = workdir / f"{operation}_output"
        directory.mkdir(parents=True, exist_ok=True)
        return directory, directory / default_pattern
    is_dir_hint = raw.endswith("/") or raw.endswith("\\")
    target = resolve_path(raw)
    if target.exists() and target.is_dir():
        return target, target / default_pattern
    if is_dir_hint:
        target.mkdir(parents=True, exist_ok=True)
        return target, target / default_pattern
    if "%" in target.name:
        ensure_parent(target)
        return target.parent, target
    if target.suffix.lower() in IMAGE_SUFFIXES | VIDEO_SUFFIXES | {".ts"}:
        ensure_parent(target)
        return target.parent, target.with_name(f"{target.stem}_%03d{target.suffix}")
    target.mkdir(parents=True, exist_ok=True)
    return target, target / default_pattern


def glob_pattern(directory: Path, pattern: Path) -> list[Path]:
    name = pattern.name
    if "%" in name:
        name = re.sub(r"%0?\d*d", "*", name)
    return sorted(path for path in directory.glob(name) if path.is_file() and not path.name.startswith("."))


async def execute_operation(
    operation: str,
    payload: dict[str, Any],
    *,
    workdir: Path,
    hooks: ExecutionHooks,
) -> OperationResult:
    if operation not in OPERATIONS:
        raise ValueError(f"Unknown FFmpeg operation: {operation}")
    options = options_of(payload)
    input_path = resolve_input(payload.get("input_path"), required=operation not in {"raw", "concat"})
    dispatchers = {
        "transcode": _dispatch("ops_basic", "transcode"),
        "extract_audio": _dispatch("ops_basic", "extract_audio"),
        "trim": _dispatch("ops_basic", "trim"),
        "crop_video": _dispatch("ops_basic", "crop_video"),
        "crop_image": _dispatch("ops_basic", "crop_image"),
        "scale": _dispatch("ops_basic", "scale"),
        "rotate": _dispatch("ops_basic", "rotate"),
        "rotate_image": _dispatch("ops_basic", "rotate_image"),
        "concat": _dispatch("ops_compose", "concat"),
        "overlay": _dispatch("ops_compose", "overlay"),
        "subtitles": _dispatch("ops_compose", "subtitles"),
        "gif": _dispatch("ops_extract", "gif"),
        "merge": _dispatch("ops_compose", "merge"),
        "replace_audio": _dispatch("ops_compose", "replace_audio"),
        "speed": _dispatch("ops_basic", "speed"),
        "volume": _dispatch("ops_compose", "volume"),
        "normalize": _dispatch("ops_compose", "normalize"),
        "frames": _dispatch("ops_extract", "frames"),
        "thumbnail": _dispatch("ops_extract", "thumbnail"),
        "split": _dispatch("ops_extract", "split"),
        "segment": _dispatch("ops_extract", "split"),
        "metadata": _dispatch("ops_extract", "metadata"),
        "raw": _dispatch("ops_extract", "raw"),
    }
    handler = dispatchers.get(operation)
    if handler is None:
        raise ValueError(f"Unknown FFmpeg operation: {operation}")
    return await handler(
        input_path=input_path,
        options=options,
        payload=payload,
        workdir=workdir,
        hooks=hooks,
        operation=operation,
    )


def _dispatch(module_name: str, function_name: str):
    import importlib

    async def call(**kwargs: Any) -> OperationResult:
        module = importlib.import_module(f"services.ffmpeg.{module_name}")
        function = getattr(module, function_name)
        return await function(**kwargs)

    return call


async def probe_duration(path: Path) -> float | None:
    data = await probe_media(path)
    return data.get("duration")


def require_duration(data: dict[str, Any], path: Path) -> float:
    duration = data.get("duration")
    if not duration or duration <= 0:
        raise ValueError(f"Could not determine the duration of {path.name}")
    return float(duration)


def positive_int(value: Any, label: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a positive integer") from exc
    if number <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return number


def aspect_crop(width: int, height: int, aspect: float) -> tuple[int, int]:
    current = width / height if height else 0
    if current > aspect:
        crop_h = height
        crop_w = int(round(crop_h * aspect))
    else:
        crop_w = width
        crop_h = int(round(crop_w / aspect))
    return max(1, crop_w), max(1, crop_h)


def even(value: int) -> int:
    return value if value % 2 == 0 else max(2, value - 1)
