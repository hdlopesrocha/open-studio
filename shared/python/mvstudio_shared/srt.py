"""SRT parsing, validation, export and ASS subtitle generation.

The parser is intentionally dependency-free and preserves original cue indices
and timestamps. No word-level timings are ever invented.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

from .models import SubtitleLine, SubtitleStyle

_TIMESTAMP_RE = re.compile(
    r"(?m)^[ \t]*(?P<start>\d{1,3}:\d{2}:\d{2}[,.]\d{1,3})"
    r"[ \t]*-->[ \t]*"
    r"(?P<end>\d{1,3}:\d{2}:\d{2}[,.]\d{1,3})"
    r"(?:[ \t]+[^\r\n]*)?[ \t]*$"
)
_TAG_RE = re.compile(r"<[^>]+>")
_ASS_ESCAPE_RE = re.compile(r"\{([^}]*)\}")


class SrtParseError(ValueError):
    """Raised when an SRT file cannot be safely interpreted."""


def parse_srt_timestamp(value: str) -> float:
    """Parse ``HH:MM:SS,mmm`` (also accepts a dot and short milliseconds)."""
    value = value.strip().replace(",", ".")
    match = re.match(r"^(?:(\d{1,3}):)?(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?$", value)
    if not match:
        raise SrtParseError(f"Invalid SRT timestamp: {value!r}")
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    millis = int((match.group(4) or "0").ljust(3, "0")[:3])
    if minutes >= 60 or seconds >= 60:
        raise SrtParseError(f"Invalid SRT timestamp: {value!r}")
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def format_srt_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000.0))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def parse_srt_with_warnings(
    text: str, *, source: str = "<string>"
) -> tuple[list[SubtitleLine], list[str]]:
    """Parse an SRT document and return cues plus non-fatal diagnostics.

    Handles BOMs, CRLF, missing cue numbers, blank lines inside cues and both
    comma and dot millisecond separators. Cue numbers are preserved when
    present; missing ones are assigned sequentially.
    """
    if text is None:
        raise SrtParseError(f"{source}: empty subtitle file")
    text = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise SrtParseError(f"{source}: empty subtitle file")

    matches = list(_TIMESTAMP_RE.finditer(text))
    if not matches:
        raise SrtParseError(
            f"{source}: no valid SRT cues found (expected lines like 00:00:01,000 --> 00:00:04,000)"
        )

    # Work out where each cue starts (including its optional numeric index line).
    block_starts: list[int] = []
    indices: list[int | None] = []
    next_fallback = 1
    for match in matches:
        line_start = match.start()
        previous_line_start = text.rfind("\n", 0, max(0, line_start - 1)) + 1
        previous_line = text[previous_line_start:line_start].strip()
        if previous_line.isdigit():
            block_start = previous_line_start
            index = int(previous_line)
        else:
            block_start = line_start
            index = None
        indices.append(index)
        block_starts.append(block_start)

    cues: list[SubtitleLine] = []
    warnings: list[str] = []
    previous_end = 0.0
    for position, match in enumerate(matches):
        text_start = match.end()
        if text_start < len(text) and text[text_start] == "\n":
            text_start += 1
        text_end = block_starts[position + 1] if position + 1 < len(matches) else len(text)
        raw_text = text[text_start:text_end].strip("\n")
        raw_text = raw_text.strip()
        raw_lines = raw_text.split("\n")
        cue_text = "\n".join(line.rstrip() for line in raw_lines).strip()

        start = parse_srt_timestamp(match.group("start"))
        end = parse_srt_timestamp(match.group("end"))
        if end < start:
            raise SrtParseError(
                f"{source}: cue {indices[position] or position + 1} ends before it starts"
            )
        if end == start:
            raise SrtParseError(
                f"{source}: cue {indices[position] or position + 1} has zero duration"
            )
        if start < previous_end - 0.001:
            warnings.append(f"Overlapping subtitles near {format_srt_timestamp(start)}")
        previous_end = max(previous_end, end)

        index = indices[position] if indices[position] is not None else next_fallback
        next_fallback = max(next_fallback + 1, index + 1)
        if not cue_text:
            warnings.append(f"Empty subtitle cue #{index} ignored")
            continue
        cues.append(SubtitleLine(index=index, start=start, end=end, text=cue_text))

    if not cues:
        raise SrtParseError(f"{source}: no non-empty subtitle cues found")

    from collections import Counter

    duplicates = [index for index, count in Counter(line.index for line in cues).items() if count > 1]
    if duplicates:
        warnings.append(
            "Duplicate subtitle indices found: " + ", ".join(str(value) for value in sorted(duplicates))
        )
    return sorted(cues, key=lambda line: (line.start, line.index)), warnings


def parse_srt(text: str, *, source: str = "<string>") -> list[SubtitleLine]:
    cues, _warnings = parse_srt_with_warnings(text, source=source)
    return cues


def parse_srt_file_with_warnings(
    path: str | Path,
) -> tuple[list[SubtitleLine], list[str]]:
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = file_path.read_text(encoding="latin-1")
    return parse_srt_with_warnings(text, source=str(file_path))


def parse_srt_file(path: str | Path) -> list[SubtitleLine]:
    cues, _warnings = parse_srt_file_with_warnings(path)
    return cues


def write_srt(lines: list[SubtitleLine], *, renumber: bool = False) -> str:
    chunks: list[str] = []
    for position, line in enumerate(sorted(lines, key=lambda item: (item.start, item.index)), start=1):
        index = position if renumber else line.index
        chunks.append(
            f"{index}\n"
            f"{format_srt_timestamp(line.start)} --> {format_srt_timestamp(line.end)}\n"
            f"{line.text.strip()}\n"
        )
    return "\n".join(chunks)


def write_srt_file(lines: list[SubtitleLine], path: str | Path, *, renumber: bool = False) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(write_srt(lines, renumber=renumber), encoding="utf-8")
    return target


def flatten_text(text: str) -> str:
    return " ".join(text.replace("\n", " ").split())


def clean_subtitle_text(text: str) -> str:
    value = _TAG_RE.sub("", text)
    value = html.unescape(value)
    value = value.replace("\u00a0", " ")
    return flatten_text(value)


def subtitle_duration(lines: list[SubtitleLine], fallback: float = 0.0) -> float:
    return max((line.end for line in lines), default=fallback)


def wrap_subtitle_text(text: str, max_chars: int) -> str:
    """Word-wrap for ASS without changing cue timing."""
    max_chars = max(10, int(max_chars))
    output_lines: list[str] = []
    for source_line in clean_subtitle_text(text).split("\n"):
        words = source_line.split()
        if not words:
            continue
        current = words[0]
        for word in words[1:]:
            if len(current) + 1 + len(word) <= max_chars:
                current += " " + word
            else:
                output_lines.append(current)
                current = word
        output_lines.append(current)
    return "\\N".join(output_lines)


@dataclass(frozen=True)
class AssRenderOptions:
    fonts_dir: str | None = None


def _ass_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    centiseconds = int(round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    secs, cs = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _ass_color(hex_color: str, opacity: float = 1.0) -> str:
    value = hex_color.lstrip("#")
    if len(value) != 6:
        value = "FFFFFF"
    red, green, blue = value[0:2], value[2:4], value[4:6]
    alpha = 255 - int(round(max(0.0, min(1.0, opacity)) * 255))
    return f"&H{alpha:02X}{blue}{green}{red}".upper()


def _ass_alignment(position: str, alignment: str) -> int:
    vertical = {"bottom": 0, "center": 3, "top": 6}[position]
    horizontal = {"left": 1, "center": 2, "right": 3}[alignment]
    return vertical + horizontal


def build_ass(
    lines: list[SubtitleLine],
    style: SubtitleStyle,
    *,
    play_res_x: int,
    play_res_y: int,
    title: str = "MVS Video Studio subtitles",
    fonts_dir: str | None = None,
) -> str:
    """Create a styled ASS document.

    Karaoke mode uses whole-line emphasis only. Because SRT contains no
    word-level timings, no word durations are fabricated.
    """
    alignment = _ass_alignment(style.position, style.alignment)
    background_style = 3 if style.background else 1
    back_colour = (
        _ass_color(style.background_color, style.background_opacity)
        if style.background
        else "&H64000000"
    )
    outline = max(style.outline_width, 0.5 if not style.background else 0.0)
    header = f"""[Script Info]
; Generated by MVS Video Studio
Title: {title}
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.font_family},{style.font_size},{_ass_color(style.primary_color)},{_ass_color(style.highlight_color)},{_ass_color(style.outline_color)},{back_colour},0,0,0,0,100,100,0,0,{background_style},{outline:.1f},{style.shadow:.1f},{alignment},60,60,{style.margin_v},1
Style: Active,{style.font_family},{style.font_size},{_ass_color(style.highlight_color)},{_ass_color(style.primary_color)},{_ass_color(style.outline_color)},{back_colour},0,0,0,0,100,100,0,0,{background_style},{outline:.1f},{style.shadow:.1f},{alignment},60,60,{style.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    for line in sorted(lines, key=lambda item: (item.start, item.index)):
        content = wrap_subtitle_text(line.text, style.max_line_width)
        content = content.replace("{", "｛").replace("}", "｝").replace("\n", "\\N")
        event_style = "Active" if style.karaoke else "Default"
        fade = "{\\fad(120,120)}" if style.karaoke else ""
        events.append(
            f"Dialogue: 0,{_ass_time(line.start)},{_ass_time(line.end)},"
            f"{event_style},,0,0,0,,{fade}{content}"
        )
    return header + "\n".join(events) + "\n"


def write_ass(
    lines: list[SubtitleLine],
    path: str | Path,
    style: SubtitleStyle,
    *,
    play_res_x: int,
    play_res_y: int,
    title: str = "MVS Video Studio subtitles",
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        build_ass(lines, style, play_res_x=play_res_x, play_res_y=play_res_y, title=title),
        encoding="utf-8",
    )
    return target
