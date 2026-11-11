"""FFmpeg operation catalog and runtime capability introspection."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from openstudio_common import FFMPEG, FFPROBE

log = logging.getLogger("ffmpeg.catalog")

VIDEO_CODECS = [
    "libx264",
    "libx265",
    "libvpx-vp9",
    "libaom-av1",
    "libsvtav1",
    "h264_nvenc",
    "hevc_nvenc",
    "av1_nvenc",
    "h264_vaapi",
    "hevc_vaapi",
    "av1_vaapi",
    "h264_qsv",
    "hevc_qsv",
    "h264_videotoolbox",
    "hevc_videotoolbox",
    "prores_ks",
    "mpeg4",
    "libxvid",
    "copy",
]
AUDIO_CODECS = [
    "aac",
    "libmp3lame",
    "libopus",
    "libvorbis",
    "flac",
    "pcm_s16le",
    "pcm_s24le",
    "pcm_s32le",
    "pcm_f32le",
    "ac3",
    "eac3",
    "alac",
    "copy",
]
SUBTITLE_CODECS = ["mov_text", "srt", "ass", "webvtt", "copy"]
CONTAINERS = ["mp4", "mkv", "webm", "mov", "avi", "ts", "m4a", "mp3", "wav", "flac", "opus", "ogg", "gif", "apng"]
VIDEO_PRESETS = [
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
    "placebo",
]
NVENC_PRESETS = ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]
PIXEL_FORMATS = ["yuv420p", "yuv422p", "yuv444p", "yuv420p10le", "yuv422p10le", "yuv444p10le", "nv12", "p010le", "rgb24", "rgba", "gray", "pal8"]
SAMPLE_RATES = [8000, 11025, 16000, 22050, 32000, 44100, 48000, 88200, 96000, 176400, 192000]
CHANNELS = [1, 2, 3, 4, 5, 6, 8]
HWACCELS = ["none", "auto", "cuda", "vaapi", "qsv", "videotoolbox", "d3d11va", "dxva2", "amf", "opencl", "vulkan"]
FIT_MODES = ["fit", "fill", "stretch"]
POSITIONS = ["top-left", "top-right", "bottom-left", "bottom-right", "center", "top", "bottom", "custom"]
TRANSITIONS = [
    "fade",
    "fadeblack",
    "fadewhite",
    "wipeleft",
    "wiperight",
    "wipeup",
    "wipedown",
    "slideleft",
    "slideright",
    "slideup",
    "slidedown",
    "circlecrop",
    "rectcrop",
    "distance",
    "pixelize",
    "radial",
    "smoothleft",
    "smoothright",
    "smoothup",
    "smoothdown",
    "circleopen",
    "circleclose",
    "dissolve",
    "horzopen",
    "horzclose",
    "vertopen",
    "vertclose",
]
AUDIO_FORMATS = {
    "mp3": {"codec": "libmp3lame", "extension": ".mp3", "mime": "audio/mpeg"},
    "wav": {"codec": "pcm_s16le", "extension": ".wav", "mime": "audio/wav"},
    "flac": {"codec": "flac", "extension": ".flac", "mime": "audio/flac"},
    "aac": {"codec": "aac", "extension": ".m4a", "mime": "audio/mp4"},
    "m4a": {"codec": "aac", "extension": ".m4a", "mime": "audio/mp4"},
    "opus": {"codec": "libopus", "extension": ".opus", "mime": "audio/opus"},
    "ogg": {"codec": "libvorbis", "extension": ".ogg", "mime": "audio/ogg"},
}


def param(
    name: str,
    type_: str,
    default: Any,
    description: str,
    *,
    required: bool = False,
    enum: list[Any] | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
    unit: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": name,
        "type": type_,
        "default": default,
        "description": description,
    }
    if required:
        data["required"] = True
    if enum is not None:
        data["enum"] = enum
    if minimum is not None:
        data["minimum"] = minimum
    if maximum is not None:
        data["maximum"] = maximum
    if unit:
        data["unit"] = unit
    return data


INPUT = param("input_path", "string", "", "Input file path relative to the shared files root.", required=True)
OUTPUT = param("output_path", "string", "", "Output file or folder path relative to the shared files root. Defaults to ffmpeg/<job_id>/.")
AUDIO_OUTPUT = param("output_path", "string", "", "Output file or folder path relative to the shared files root. Defaults to ffmpeg/<job_id>/.")

CODEC_PARAMS = [
    param("video_codec", "string", "libx264", "Video encoder.", enum=VIDEO_CODECS),
    param("preset", "string", "medium", "Encoder preset.", enum=VIDEO_PRESETS + NVENC_PRESETS),
    param("crf", "number", 23, "Constant rate factor for x264/x265/VP9 (lower is better).", minimum=0, maximum=63),
    param("video_bitrate", "string", "", "Target video bitrate (for example 6M). Overrides CRF when set."),
    param("audio_codec", "string", "aac", "Audio encoder.", enum=AUDIO_CODECS),
    param("audio_bitrate", "string", "192k", "Target audio bitrate (for example 192k)."),
]

COMMON_ENCODE = CODEC_PARAMS + [
    param("profile", "string", "", "Codec profile, for example high or main."),
    param("level", "string", "", "Codec level, for example 4.1."),
    param("tune", "string", "", "Encoder tune, for example film or animation."),
    param("pix_fmt", "string", "", "Output pixel format.", enum=PIXEL_FORMATS),
    param("sample_rate", "integer", None, "Audio sample rate.", enum=SAMPLE_RATES),
    param("channels", "integer", None, "Audio channel count.", enum=CHANNELS),
    param("movflags_faststart", "boolean", True, "Add +faststart for MP4/MOV output."),
    param("shortest", "boolean", False, "Stop at the shortest input stream."),
    param("format", "string", "", "Force a container/muxer.", enum=CONTAINERS),
]


def _envelope(description: str, extra: list[dict[str, Any]], *, input_param: dict[str, Any] | None = INPUT) -> dict[str, Any]:
    params = ([input_param] if input_param is not None else []) + [OUTPUT] + extra
    return {"description": description, "params": params}


OPERATIONS: dict[str, dict[str, Any]] = {
    "transcode": {
        "title": "Transcode",
        "category": "video",
        "sync": True,
        "description": "Re-encode video and/or audio with full codec, quality, resolution and frame-rate control.",
        "params": [INPUT, OUTPUT]
        + CODEC_PARAMS
        + [
            param("media", "string", "auto", "Process both streams, or force video/audio only.", enum=["auto", "video", "audio"]),
            param("hwaccel", "string", "none", "Hardware decoding acceleration.", enum=HWACCELS),
            param("hwaccel_device", "string", "", "Hardware device index or DRM render node."),
            param("resolution", "string", "", "Output size as WIDTHxHEIGHT. Use -2 for automatic even dimension."),
            param("width", "integer", None, "Output width in pixels.", minimum=2),
            param("height", "integer", None, "Output height in pixels.", minimum=2),
            param("fps", "number", None, "Output frame rate.", minimum=0.01, maximum=240),
            param("pix_fmt", "string", "", "Output pixel format.", enum=PIXEL_FORMATS),
            param("profile", "string", "", "Codec profile, for example high or main."),
            param("level", "string", "", "Codec level, for example 4.1."),
            param("tune", "string", "", "Encoder tune, for example film or animation."),
            param("sample_rate", "integer", None, "Audio sample rate.", enum=SAMPLE_RATES),
            param("channels", "integer", None, "Audio channel count.", enum=CHANNELS),
            param("movflags_faststart", "boolean", True, "Add +faststart for MP4/MOV output."),
            param("format", "string", "", "Force a container/muxer.", enum=CONTAINERS),
            param("shortest", "boolean", False, "Stop at the shortest input stream."),
        ],
    },
    "extract_audio": {
        "title": "Extract audio",
        "category": "audio",
        "sync": True,
        "description": "Extract, convert and optionally normalize the audio track.",
        "params": [INPUT, OUTPUT]
        + [
            param("format", "string", "mp3", "Audio output format.", enum=list(AUDIO_FORMATS)),
            param("bitrate", "string", "192k", "Target bitrate for lossy formats."),
            param("sample_rate", "integer", None, "Resample the output.", enum=SAMPLE_RATES),
            param("channels", "integer", None, "Channel count.", enum=CHANNELS),
            param("normalize", "boolean", False, "Single-pass EBU R128 loudness normalization."),
            param("target_lufs", "number", -16, "Integrated loudness target.", minimum=-70, maximum=-5),
            param("true_peak", "number", -1.5, "True peak ceiling in dBTP.", minimum=-9, maximum=0),
            param("lra", "number", 11, "Loudness range target.", minimum=1, maximum=50),
            param("audio_codec", "string", "", "Override the encoder chosen by format.", enum=AUDIO_CODECS),
            param("audio_bitrate", "string", "", "Alias for bitrate."),
        ],
    },
    "trim": {
        "title": "Trim",
        "category": "video",
        "sync": True,
        "description": "Cut a section with stream copy or a frame-accurate re-encode.",
        "params": [INPUT, OUTPUT]
        + [
            param("start", "number", 0, "Start time in seconds.", minimum=0),
            param("end", "number", None, "End time in seconds.", minimum=0),
            param("duration", "number", None, "Clip duration in seconds. Overrides end when both are set.", minimum=0.01),
            param("copy", "boolean", False, "Stream copy instead of re-encoding (keyframe accurate)."),
            param("accurate", "boolean", True, "Seek after decoding for frame-accurate cuts (re-encode only)."),
            param("video_codec", "string", "libx264", "Video encoder when re-encoding.", enum=VIDEO_CODECS),
            param("audio_codec", "string", "aac", "Audio encoder when re-encoding.", enum=AUDIO_CODECS),
            param("crf", "number", 23, "CRF for re-encoding.", minimum=0, maximum=63),
            param("preset", "string", "medium", "Encoder preset.", enum=VIDEO_PRESETS),
            param("format", "string", "", "Force a container/muxer.", enum=CONTAINERS),
        ],
    },
    "crop_video": {
        "title": "Crop video",
        "category": "video",
        "sync": True,
        "description": "Crop a video to an exact rectangle or aspect ratio.",
        "params": [INPUT, OUTPUT]
        + [
            param("width", "integer", None, "Crop width in pixels.", minimum=2),
            param("height", "integer", None, "Crop height in pixels.", minimum=2),
            param("x", "integer", 0, "Crop X offset.", minimum=0),
            param("y", "integer", 0, "Crop Y offset.", minimum=0),
            param("aspect", "string", "", "Target aspect ratio, for example 16:9 or 1:1."),
            param("center", "boolean", False, "Center the crop rectangle."),
            param("video_codec", "string", "libx264", "Video encoder.", enum=VIDEO_CODECS),
            param("crf", "number", 23, "CRF for the output.", minimum=0, maximum=63),
            param("preset", "string", "medium", "Encoder preset.", enum=VIDEO_PRESETS),
            param("audio_codec", "string", "copy", "Audio handling.", enum=AUDIO_CODECS),
            param("audio_bitrate", "string", "192k", "Audio bitrate when re-encoding."),
            param("format", "string", "", "Force a container/muxer.", enum=CONTAINERS),
        ],
    },
    "crop_image": {
        "title": "Crop image",
        "category": "image",
        "sync": True,
        "description": "Crop a still image and save it as PNG, JPEG or WebP.",
        "params": [INPUT, OUTPUT]
        + [
            param("width", "integer", None, "Crop width in pixels.", minimum=1),
            param("height", "integer", None, "Crop height in pixels.", minimum=1),
            param("x", "integer", 0, "Crop X offset.", minimum=0),
            param("y", "integer", 0, "Crop Y offset.", minimum=0),
            param("aspect", "string", "", "Target aspect ratio, for example 16:9."),
            param("center", "boolean", False, "Center the crop rectangle."),
            param("format", "string", "png", "Output image format.", enum=["png", "jpg", "jpeg", "webp"]),
            param("quality", "integer", 2, "JPEG/WebP quality (2 is best, 31 is worst for JPEG).", minimum=2, maximum=31),
        ],
    },
    "scale": {
        "title": "Scale",
        "category": "video",
        "sync": True,
        "description": "Resize video or image using fit, fill or stretch semantics.",
        "params": [INPUT, OUTPUT]
        + [
            param("width", "integer", None, "Target width. Use -2 to preserve aspect ratio.", minimum=-2),
            param("height", "integer", None, "Target height. Use -2 to preserve aspect ratio.", minimum=-2),
            param("mode", "string", "fit", "fit letterboxes, fill crops, stretch distorts.", enum=FIT_MODES),
            param("pad", "boolean", True, "Pad fit output to the exact target size."),
            param("pad_color", "string", "black", "Padding color (name or 0xRRGGBB)."),
            param("no_upscale", "boolean", False, "Never enlarge the source."),
            param("video_codec", "string", "libx264", "Video encoder.", enum=VIDEO_CODECS),
            param("crf", "number", 23, "CRF for the output.", minimum=0, maximum=63),
            param("preset", "string", "medium", "Encoder preset.", enum=VIDEO_PRESETS),
            param("audio_codec", "string", "copy", "Audio handling.", enum=AUDIO_CODECS),
            param("audio_bitrate", "string", "192k", "Audio bitrate when re-encoding."),
            param("format", "string", "", "Output image/container format.", enum=CONTAINERS + ["png", "jpg", "jpeg", "webp"]),
        ],
    },
    "rotate": {
        "title": "Rotate / flip video",
        "category": "video",
        "sync": True,
        "description": "Rotate by 90/180/270 or an arbitrary angle and optionally flip.",
        "params": [INPUT, OUTPUT]
        + [
            param("angle", "number", 90, "Rotation angle in degrees (clockwise)."),
            param("flip_h", "boolean", False, "Mirror horizontally."),
            param("flip_v", "boolean", False, "Mirror vertically."),
            param("fill_color", "string", "black", "Background color for arbitrary rotation."),
            param("video_codec", "string", "libx264", "Video encoder.", enum=VIDEO_CODECS),
            param("crf", "number", 23, "CRF for the output.", minimum=0, maximum=63),
            param("preset", "string", "medium", "Encoder preset.", enum=VIDEO_PRESETS),
            param("audio_codec", "string", "copy", "Audio handling.", enum=AUDIO_CODECS),
            param("format", "string", "", "Force a container/muxer.", enum=CONTAINERS),
        ],
    },
    "rotate_image": {
        "title": "Rotate / flip image",
        "category": "image",
        "sync": True,
        "description": "Rotate and flip a still image.",
        "params": [INPUT, OUTPUT]
        + [
            param("angle", "number", 90, "Rotation angle in degrees (clockwise)."),
            param("flip_h", "boolean", False, "Mirror horizontally."),
            param("flip_v", "boolean", False, "Mirror vertically."),
            param("fill_color", "string", "black", "Background color for arbitrary rotation."),
            param("format", "string", "png", "Output image format.", enum=["png", "jpg", "jpeg", "webp"]),
            param("quality", "integer", 2, "JPEG/WebP quality.", minimum=2, maximum=31),
        ],
    },
    "concat": {
        "title": "Concatenate",
        "category": "video",
        "sync": True,
        "description": "Join clips in order with optional xfade transitions. Re-encodes or copies.",
        "params": [OUTPUT]
        + [
            param("files", "array", [], "Ordered list of input paths relative to the files root.", required=True),
            param("copy", "boolean", True, "Stream copy when possible."),
            param("reencode", "boolean", False, "Force a re-encode."),
            param("transition", "string", "", "Optional xfade transition name.", enum=TRANSITIONS),
            param("transition_duration", "number", 0.5, "Transition duration in seconds.", minimum=0.05, maximum=10),
            param("video_codec", "string", "libx264", "Encoder for re-encoding.", enum=VIDEO_CODECS),
            param("crf", "number", 23, "CRF for re-encoding.", minimum=0, maximum=63),
            param("preset", "string", "medium", "Encoder preset.", enum=VIDEO_PRESETS),
            param("audio_codec", "string", "aac", "Audio encoder for re-encoding.", enum=AUDIO_CODECS),
            param("format", "string", "", "Force a container/muxer.", enum=CONTAINERS),
        ],
    },
    "overlay": {
        "title": "Overlay image or text",
        "category": "video",
        "sync": True,
        "description": "Composite an image, watermark or styled text onto a video or image.",
        "params": [INPUT, OUTPUT]
        + [
            param("mode", "string", "image", "Overlay kind.", enum=["image", "watermark", "text"]),
            param("overlay_path", "string", "", "Image/watermark path relative to the files root."),
            param("text", "string", "", "Text to draw when mode=text."),
            param("position", "string", "bottom-right", "Anchor position.", enum=POSITIONS),
            param("x", "integer", None, "Custom X coordinate.", minimum=0),
            param("y", "integer", None, "Custom Y coordinate.", minimum=0),
            param("margin", "integer", 16, "Margin from the edges.", minimum=0),
            param("opacity", "number", 1, "Overlay opacity from 0 to 1.", minimum=0, maximum=1),
            param("scale", "string", "", "Overlay width in pixels, a percentage (25%), or fraction."),
            param("font", "string", "DejaVu Sans", "Font family for text overlays."),
            param("font_file", "string", "", "Explicit font file inside the files root."),
            param("font_size", "integer", 36, "Text size.", minimum=4, maximum=512),
            param("font_color", "string", "white", "Text color."),
            param("border_width", "integer", 0, "Text outline width.", minimum=0, maximum=32),
            param("border_color", "string", "black", "Text outline color."),
            param("shadow", "integer", 0, "Text shadow offset.", minimum=0, maximum=32),
            param("box", "boolean", False, "Draw a background box behind text."),
            param("box_color", "string", "black@0.5", "Text box color."),
            param("video_codec", "string", "libx264", "Video encoder.", enum=VIDEO_CODECS),
            param("crf", "number", 23, "CRF for the output.", minimum=0, maximum=63),
            param("preset", "string", "medium", "Encoder preset.", enum=VIDEO_PRESETS),
            param("audio_codec", "string", "copy", "Audio handling.", enum=AUDIO_CODECS),
            param("format", "string", "", "Force a container/muxer.", enum=CONTAINERS),
        ],
    },
    "subtitles": {
        "title": "Burn subtitles",
        "category": "video",
        "sync": True,
        "description": "Burn SRT, VTT or ASS subtitles into the video with full style control.",
        "params": [INPUT, OUTPUT]
        + [
            param("subtitle_path", "string", "", "Subtitle file path relative to the files root.", required=True),
            param("font", "string", "DejaVu Sans", "Font family name."),
            param("font_size", "integer", 24, "Subtitle font size.", minimum=4, maximum=256),
            param("color", "string", "white", "Primary text color (name or #RRGGBB)."),
            param("outline_color", "string", "black", "Outline color."),
            param("outline", "number", 1, "Outline width.", minimum=0, maximum=12),
            param("shadow", "number", 0, "Shadow depth.", minimum=0, maximum=12),
            param("position", "string", "bottom", "Vertical alignment.", enum=["top", "center", "bottom"]),
            param("margin_v", "integer", 24, "Vertical margin.", minimum=0, maximum=500),
            param("margin_l", "integer", 16, "Left margin.", minimum=0, maximum=500),
            param("margin_r", "integer", 16, "Right margin.", minimum=0, maximum=500),
            param("bold", "boolean", False, "Bold text."),
            param("italic", "boolean", False, "Italic text."),
            param("underline", "boolean", False, "Underlined text."),
            param("strikeout", "boolean", False, "Strikethrough text."),
            param("fontsdir", "string", "", "Folder with custom fonts, relative to the files root."),
            param("video_codec", "string", "libx264", "Video encoder.", enum=VIDEO_CODECS),
            param("crf", "number", 23, "CRF for the output.", minimum=0, maximum=63),
            param("preset", "string", "medium", "Encoder preset.", enum=VIDEO_PRESETS),
            param("audio_codec", "string", "copy", "Audio handling.", enum=AUDIO_CODECS),
            param("format", "string", "", "Force a container/muxer.", enum=CONTAINERS),
        ],
    },
    "frames": {
        "title": "Extract frames",
        "category": "image",
        "sync": True,
        "description": "Extract frames at a fixed rate or at explicit timestamps.",
        "params": [INPUT, OUTPUT]
        + [
            param("mode", "string", "fps", "Extraction mode.", enum=["fps", "timestamps"]),
            param("fps", "number", 1, "Frames per second when mode=fps.", minimum=0.01, maximum=240),
            param("timestamps", "array", [], "Explicit timestamps in seconds when mode=timestamps."),
            param("start", "number", 0, "Start time in seconds.", minimum=0),
            param("duration", "number", None, "Optional duration limit.", minimum=0.01),
            param("format", "string", "jpg", "Frame image format.", enum=["jpg", "jpeg", "png", "webp"]),
            param("width", "integer", None, "Resize frames to this width; -1 preserves ratio.", minimum=-1),
            param("height", "integer", None, "Resize frames to this height; -1 preserves ratio.", minimum=-1),
            param("quality", "integer", 2, "JPEG/WebP quality.", minimum=2, maximum=31),
            param("max_frames", "integer", 1000, "Safety limit for extracted frames.", minimum=1, maximum=5000),
        ],
    },
    "gif": {
        "title": "Create GIF",
        "category": "image",
        "sync": True,
        "description": "Convert a clip section into an optimized palette GIF.",
        "params": [INPUT, OUTPUT]
        + [
            param("start", "number", 0, "Start time in seconds.", minimum=0),
            param("duration", "number", 3, "GIF duration in seconds.", minimum=0.1, maximum=120),
            param("fps", "number", 12, "GIF frame rate.", minimum=1, maximum=50),
            param("width", "integer", 480, "GIF width; height preserves aspect.", minimum=16, maximum=1920),
            param("max_colors", "integer", 256, "Palette size.", minimum=2, maximum=256),
            param("dither", "string", "bayer", "Dithering mode.", enum=["bayer", "sierra2_4a", "none"]),
            param("loop", "integer", 0, "Loop count; 0 is infinite.", minimum=-1, maximum=1000),
            param("palette", "boolean", True, "Generate an optimized palette."),
        ],
    },
    "merge": {
        "title": "Merge audio and video",
        "category": "video",
        "sync": True,
        "description": "Attach an audio file to a video, optionally mixing with the original.",
        "params": [
            INPUT,
            param("audio_path", "string", "", "Audio file path relative to the files root.", required=True),
            OUTPUT,
            param("replace", "boolean", True, "Replace the original audio instead of mixing."),
            param("original_volume", "number", 1, "Original audio gain when mixing.", minimum=0, maximum=4),
            param("new_volume", "number", 1, "New audio gain.", minimum=0, maximum=4),
            param("shortest", "boolean", False, "Stop at the shortest input."),
            param("copy_video", "boolean", True, "Copy the video stream."),
            param("video_codec", "string", "libx264", "Encoder when copy_video is false.", enum=VIDEO_CODECS),
            param("audio_codec", "string", "aac", "Audio encoder.", enum=AUDIO_CODECS),
            param("audio_bitrate", "string", "192k", "Audio bitrate."),
            param("format", "string", "", "Force a container/muxer.", enum=CONTAINERS),
        ],
    },
    "replace_audio": {
        "title": "Replace audio",
        "category": "audio",
        "sync": True,
        "description": "Replace or mute the original audio of a video with a new track.",
        "params": [
            INPUT,
            param("audio_path", "string", "", "Replacement audio path relative to the files root."),
            OUTPUT,
            param("mute_original", "boolean", True, "Discard the original audio. Set false to mix it back."),
            param("original_volume", "number", 1, "Original audio gain when mixing.", minimum=0, maximum=4),
            param("new_volume", "number", 1, "New audio gain.", minimum=0, maximum=4),
            param("shortest", "boolean", False, "Stop at the shortest input."),
            param("copy_video", "boolean", True, "Copy the video stream."),
            param("audio_codec", "string", "aac", "Audio encoder.", enum=AUDIO_CODECS),
            param("audio_bitrate", "string", "192k", "Audio bitrate."),
            param("format", "string", "", "Force a container/muxer.", enum=CONTAINERS),
        ],
    },
    "speed": {
        "title": "Change speed",
        "category": "video",
        "sync": True,
        "description": "Speed up or slow down video and audio, optionally preserving pitch.",
        "params": [INPUT, OUTPUT]
        + [
            param("factor", "number", 1.25, "Speed multiplier applied to both streams.", minimum=0.1, maximum=100),
            param("video_factor", "number", None, "Separate video speed multiplier.", minimum=0.1, maximum=100),
            param("audio_factor", "number", None, "Separate audio speed multiplier.", minimum=0.1, maximum=100),
            param("pitch_correction", "boolean", True, "Preserve audio pitch (atempo) instead of shifting it."),
            param("video_codec", "string", "libx264", "Video encoder.", enum=VIDEO_CODECS),
            param("crf", "number", 23, "CRF for the output.", minimum=0, maximum=63),
            param("preset", "string", "medium", "Encoder preset.", enum=VIDEO_PRESETS),
            param("audio_codec", "string", "aac", "Audio encoder.", enum=AUDIO_CODECS),
            param("audio_bitrate", "string", "192k", "Audio bitrate."),
            param("format", "string", "", "Force a container/muxer.", enum=CONTAINERS),
        ],
    },
    "volume": {
        "title": "Adjust volume",
        "category": "audio",
        "sync": True,
        "description": "Apply gain or one-pass EBU R128 loudness normalization to the audio.",
        "params": [INPUT, OUTPUT]
        + [
            param("gain_db", "number", 0, "Gain in decibels."),
            param("gain", "number", None, "Linear gain multiplier; overrides gain_db."),
            param("normalize", "boolean", False, "Use loudnorm instead of a volume filter."),
            param("target_lufs", "number", -16, "Integrated loudness target.", minimum=-70, maximum=-5),
            param("true_peak", "number", -1.5, "True peak ceiling.", minimum=-9, maximum=0),
            param("lra", "number", 11, "Loudness range.", minimum=1, maximum=50),
            param("audio_codec", "string", "aac", "Audio encoder.", enum=AUDIO_CODECS),
            param("audio_bitrate", "string", "192k", "Audio bitrate."),
            param("copy_video", "boolean", True, "Copy video when present."),
            param("format", "string", "", "Force a container/muxer.", enum=CONTAINERS),
        ],
    },
    "normalize": {
        "title": "Normalize audio (two-pass)",
        "category": "audio",
        "sync": True,
        "description": "Measure and apply EBU R128 loudnorm in two passes for accurate loudness.",
        "params": [INPUT, OUTPUT]
        + [
            param("target_lufs", "number", -16, "Integrated loudness target.", minimum=-70, maximum=-5),
            param("true_peak", "number", -1.5, "True peak ceiling in dBTP.", minimum=-9, maximum=0),
            param("lra", "number", 11, "Loudness range target.", minimum=1, maximum=50),
            param("sample_rate", "integer", 48000, "Output sample rate.", enum=SAMPLE_RATES),
            param("dual_mono", "boolean", False, "Treat mono as dual mono."),
            param("keep_video", "boolean", False, "Keep the video stream and normalize only audio."),
            param("format", "string", "wav", "Audio output format when not keeping video.", enum=["wav", "mp3", "flac", "m4a", "opus", "ogg", "mp4", "mkv"]),
            param("audio_codec", "string", "", "Override the encoder implied by format.", enum=AUDIO_CODECS),
            param("audio_bitrate", "string", "192k", "Bitrate for lossy formats."),
        ],
    },
    "thumbnail": {
        "title": "Thumbnail",
        "category": "image",
        "sync": True,
        "description": "Extract a single frame at a timestamp and resize it.",
        "params": [INPUT, OUTPUT]
        + [
            param("time", "number", 0, "Timestamp in seconds.", minimum=0),
            param("width", "integer", 320, "Thumbnail width; height preserves aspect.", minimum=16, maximum=4096),
            param("height", "integer", None, "Optional explicit height; otherwise -2 preserves aspect.", minimum=2),
            param("format", "string", "jpg", "Image format.", enum=["jpg", "jpeg", "png", "webp"]),
            param("quality", "integer", 2, "JPEG/WebP quality.", minimum=2, maximum=31),
        ],
    },
    "split": {
        "title": "Split / segment",
        "category": "video",
        "sync": True,
        "description": "Split a file into fixed-duration segments.",
        "params": [INPUT, OUTPUT]
        + [
            param("duration", "number", 60, "Segment duration in seconds.", minimum=1, maximum=86400),
            param("copy", "boolean", True, "Stream copy instead of re-encoding at segment boundaries."),
            param("video_codec", "string", "libx264", "Video encoder when copy is false.", enum=VIDEO_CODECS),
            param("audio_codec", "string", "aac", "Audio encoder when copy is false.", enum=AUDIO_CODECS),
            param("crf", "number", 23, "CRF when re-encoding.", minimum=0, maximum=63),
            param("preset", "string", "medium", "Encoder preset.", enum=VIDEO_PRESETS),
            param("reset_timestamps", "boolean", True, "Reset timestamps on every segment."),
            param("format", "string", "", "Segment container.", enum=CONTAINERS),
        ],
    },
    "segment": {
        "title": "Split / segment (alias)",
        "category": "video",
        "sync": True,
        "description": "Alias for split.",
        "params": [INPUT, OUTPUT]
        + [
            param("duration", "number", 60, "Segment duration in seconds.", minimum=1, maximum=86400),
            param("copy", "boolean", True, "Stream copy instead of re-encoding."),
            param("video_codec", "string", "libx264", "Video encoder when copy is false.", enum=VIDEO_CODECS),
            param("audio_codec", "string", "aac", "Audio encoder when copy is false.", enum=AUDIO_CODECS),
            param("crf", "number", 23, "CRF when re-encoding.", minimum=0, maximum=63),
            param("preset", "string", "medium", "Encoder preset.", enum=VIDEO_PRESETS),
            param("reset_timestamps", "boolean", True, "Reset timestamps on every segment."),
            param("format", "string", "", "Segment container.", enum=CONTAINERS),
        ],
    },
    "metadata": {
        "title": "Metadata",
        "category": "video",
        "sync": True,
        "description": "Strip or set container metadata without re-encoding.",
        "params": [INPUT, OUTPUT]
        + [
            param("strip", "boolean", False, "Remove all existing metadata."),
            param("metadata", "object", {}, "Key/value metadata to set."),
            param("remove", "array", [], "Metadata keys to remove."),
            param("chapters", "boolean", True, "Copy chapters when the container supports them."),
            param("format", "string", "", "Force a container/muxer.", enum=CONTAINERS),
        ],
    },
    "raw": {
        "title": "Raw FFmpeg",
        "category": "advanced",
        "sync": False,
        "description": "Run an explicit ffmpeg argv list. Only the ffmpeg executable is allowed; no shell is used.",
        "params": [
            param("input_path", "string", "", "Optional input file added with -i when argv has no -i."),
            OUTPUT,
            param("argv", "array", [], "Full ffmpeg argument list as strings, without the executable.", required=True),
            param("timeout", "number", 3600, "Execution timeout in seconds.", minimum=1, maximum=86400),
        ],
    },
}


def operation_list() -> list[dict[str, Any]]:
    return [{"name": name, **spec} for name, spec in OPERATIONS.items()]


FILTER_OPTIONS = [
    {
        "name": "scale",
        "description": "Resize with fit/fill/stretch handling.",
        "params": ["width", "height", "force_original_aspect_ratio", "flags"],
    },
    {
        "name": "crop",
        "description": "Crop by width/height/x/y.",
        "params": ["width", "height", "x", "y", "keep_aspect"],
    },
    {
        "name": "transpose / rotate",
        "description": "Rotate by 90/180/270 or an arbitrary angle.",
        "params": ["angle", "fill_color", "ow", "oh"],
    },
    {
        "name": "overlay",
        "description": "Composite an image or watermark with opacity.",
        "params": ["x", "y", "format", "opacity"],
    },
    {
        "name": "drawtext",
        "description": "Styled text overlays.",
        "params": ["text", "font", "fontfile", "fontsize", "fontcolor", "borderw", "bordercolor", "box", "boxcolor", "alpha"],
    },
    {
        "name": "subtitles / ass",
        "description": "Burn SRT/VTT/ASS subtitles with force_style.",
        "params": ["filename", "force_style", "fontsdir", "alpha"],
    },
    {
        "name": "xfade",
        "description": "Transition between concatenated clips.",
        "params": ["transition", "duration", "offset"],
    },
    {
        "name": "acrossfade",
        "description": "Crossfade audio between concatenated clips.",
        "params": ["duration", "curve1", "curve2"],
    },
    {
        "name": "loudnorm",
        "description": "EBU R128 loudness normalization, single or two-pass.",
        "params": ["I", "TP", "LRA", "measured_I", "measured_TP", "measured_LRA", "measured_thresh", "offset", "linear", "dual_mono"],
    },
    {
        "name": "atempo",
        "description": "Pitch-preserving audio speed change.",
        "params": ["tempo"],
    },
    {
        "name": "palettegen / paletteuse",
        "description": "Optimized GIF palette generation.",
        "params": ["max_colors", "stats_mode", "dither", "bayer_scale"],
    },
    {
        "name": "fps",
        "description": "Frame rate conversion.",
        "params": ["fps", "start_time", "round"],
    },
    {
        "name": "volume",
        "description": "Linear or decibel gain.",
        "params": ["volume", "precision"],
    },
    {
        "name": "amix",
        "description": "Mix multiple audio inputs.",
        "params": ["inputs", "duration", "dropout_transition", "weights"],
    },
]

STYLE_FIELDS = [
    "FontName",
    "FontSize",
    "PrimaryColour",
    "SecondaryColour",
    "OutlineColour",
    "BackColour",
    "Bold",
    "Italic",
    "Underline",
    "StrikeOut",
    "BorderStyle",
    "Outline",
    "Shadow",
    "Alignment",
    "MarginL",
    "MarginR",
    "MarginV",
]


def _version_info(binary: str) -> dict[str, Any]:
    import subprocess

    try:
        output = subprocess.run(
            [binary, "-version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        ).stdout
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": str(exc)}
    lines = [line for line in output.splitlines() if line.strip()]
    info: dict[str, Any] = {
        "available": bool(lines),
        "version_line": lines[0] if lines else "",
        "libraries": [line for line in lines if line.startswith("lib")],
        "configuration": next((line for line in lines if line.startswith("configuration:")), ""),
    }
    match = re.search(r"version\s+(\S+)", info["version_line"])
    info["version"] = match.group(1) if match else ""
    return info


def _list_encoders() -> list[dict[str, str]]:
    import subprocess

    try:
        output = subprocess.run([FFMPEG, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=15, check=False).stdout
    except Exception:  # noqa: BLE001
        return []
    encoders: list[dict[str, str]] = []
    for line in output.splitlines():
        match = re.match(r"^\s*([VAS])([A-Z.]{5})\s+(\S+)\s+(.*)$", line)
        if match and match.group(3) != "=":
            encoders.append(
                {
                    "type": {"V": "video", "A": "audio", "S": "subtitle"}[match.group(1)],
                    "name": match.group(3),
                    "description": match.group(4).strip(),
                }
            )
    return encoders


def _list_formats() -> dict[str, list[dict[str, str]]]:
    import subprocess

    try:
        output = subprocess.run([FFMPEG, "-hide_banner", "-formats"], capture_output=True, text=True, timeout=15, check=False).stdout
    except Exception:  # noqa: BLE001
        return {"demuxers": [], "muxers": []}
    demuxers: list[dict[str, str]] = []
    muxers: list[dict[str, str]] = []
    for line in output.splitlines():
        match = re.match(r"^\s*([D ])([E ])\s+(\S+)\s+(.*)$", line)
        if not match:
            continue
        if match.group(3) == "=":
            continue
        entry = {"name": match.group(3), "description": match.group(4).strip()}
        if match.group(1) == "D":
            demuxers.append(entry)
        if match.group(2) == "E":
            muxers.append(entry)
    return {"demuxers": demuxers, "muxers": muxers}


def _list_filters() -> list[str]:
    import subprocess

    try:
        output = subprocess.run([FFMPEG, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=15, check=False).stdout
    except Exception:  # noqa: BLE001
        return []
    names: list[str] = []
    for line in output.splitlines():
        match = re.match(r"^\s*[TSC.]{3}\s+(\S+)\s+", line)
        if match and match.group(1) != "=":
            names.append(match.group(1))
    return sorted(set(names))


def _list_hwaccels() -> list[str]:
    import subprocess

    try:
        output = subprocess.run([FFMPEG, "-hide_banner", "-hwaccels"], capture_output=True, text=True, timeout=15, check=False).stdout
    except Exception:  # noqa: BLE001
        return []
    return [line.strip() for line in output.splitlines() if line.strip() and not line.startswith("Hardware")]


def _list_pixel_formats() -> list[str]:
    import subprocess

    try:
        output = subprocess.run([FFMPEG, "-hide_banner", "-pix_fmts"], capture_output=True, text=True, timeout=15, check=False).stdout
    except Exception:  # noqa: BLE001
        return PIXEL_FORMATS
    names: list[str] = []
    for line in output.splitlines():
        match = re.match(r"^\s*[IO.]{2}[A-Z.]{3}\s+(\S+)\s+\d+\s+\d+", line)
        if match:
            names.append(match.group(1))
    return sorted(set(names)) or PIXEL_FORMATS


def _build_catalog() -> dict[str, Any]:
    formats = _list_formats()
    encoders = _list_encoders()
    return {
        "operations": operation_list(),
        "common": {
            "input": INPUT,
            "output": OUTPUT,
            "note": "All paths are relative to the shared files root. Outputs default to ffmpeg/<job_id>/.",
        },
        "codecs": {
            "video": VIDEO_CODECS,
            "audio": AUDIO_CODECS,
            "subtitle": SUBTITLE_CODECS,
            "encoders": encoders,
        },
        "formats": CONTAINERS,
        "muxers": formats["muxers"],
        "demuxers": formats["demuxers"],
        "presets": {"x264_x265": VIDEO_PRESETS, "nvenc": NVENC_PRESETS},
        "filters": FILTER_OPTIONS,
        "filter_names": _list_filters(),
        "pixel_formats": _list_pixel_formats(),
        "sample_rates": SAMPLE_RATES,
        "channels": CHANNELS,
        "hwaccels": _list_hwaccels() or HWACCELS,
        "audio_formats": AUDIO_FORMATS,
        "fit_modes": FIT_MODES,
        "positions": POSITIONS,
        "transitions": TRANSITIONS,
        "subtitle_style_fields": STYLE_FIELDS,
        "fonts": ["DejaVu Sans", "Noto Sans", "Noto Serif", "Liberation Sans", "DejaVu Serif"],
        "limits": {
            "max_frames": 5000,
            "sync_timeout_seconds": 3600,
            "default_job_timeout_seconds": 86400,
        },
        "ffmpeg": _version_info(FFMPEG),
        "ffprobe": _version_info(FFPROBE),
    }


_catalog_cache: dict[str, Any] | None = None
_catalog_lock = asyncio.Lock()


async def build_catalog(refresh: bool = False) -> dict[str, Any]:
    global _catalog_cache
    async with _catalog_lock:
        if _catalog_cache is not None and not refresh:
            return _catalog_cache
        _catalog_cache = await asyncio.to_thread(_build_catalog)
        return _catalog_cache
