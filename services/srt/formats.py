"""Subtitle parsing, wrapping and rendering for SRT, WebVTT and ASS.

The shared library covers SRT/VTT; this module adds ASS and the cue-splitting
helpers used by alignment and text-driven timing.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from openstudio_common import parse_srt

FORMATS = ("srt", "vtt", "ass")

_ASS_OVERRIDE = re.compile(r"\{[^}]*\}")
_ASS_TS = re.compile(r"(?P<h>\d+):(?P<m>\d{1,2}):(?P<s>\d{1,2})[.](?P<cs>\d{1,2})")
_ASS_SPLIT = re.compile(r"[，。；：、！？,;:!?]")


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def clean_line(value: str) -> str:
    value = value.replace("\u00a0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    return value.strip()


def wrap_text(text: str, max_line_chars: int = 42, max_lines: int = 2) -> list[str]:
    """Wrap one cue's text into at most ``max_lines`` display lines."""
    text = clean_line(text)
    if not text or max_line_chars <= 0:
        return [text] if text else []
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_line_chars:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if max_lines > 0 and len(lines) > max_lines:
        # Merge overflow back into the final permitted line. Alignment usually
        # splits the source text first, so this only catches pathological words.
        head = lines[: max_lines - 1]
        tail = " ".join(lines[max_lines - 1 :])
        lines = [*head, tail]
    return lines


def _preferred_break(words: list[str], limit: int) -> int:
    """Return a split index near the end of ``words`` if punctuation allows."""
    best = len(words)
    running = 0
    for index, word in enumerate(words):
        running += len(word) + 1
        if running > limit:
            break
        if _ASS_SPLIT.search(word[-1:]):
            best = index + 1
    if best == len(words):
        return len(words)
    if best < max(1, len(words) // 3):
        return len(words)
    return best


def split_text_for_cues(text: str, max_line_chars: int = 42, max_lines: int = 2) -> list[str]:
    """Split a long subtitle/lyric line into readable cue payloads.

    Punctuation is preferred as a break point; otherwise the split is made on a
    word boundary. Each returned item is already wrapped for display (``\\n``).
    """
    text = clean_line(text)
    if not text:
        return []
    if max_line_chars <= 0:
        return [text]
    max_total = max(1, max_line_chars) * max(1, max_lines)
    if len(text) <= max_line_chars:
        return [text]
    words = text.split(" ")
    chunks: list[list[str]] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if current and len(candidate) > max_total:
            cut = _preferred_break(current, max_total)
            chunks.append(current[:cut])
            current = current[cut:]
        current.append(word)
    if current:
        chunks.append(current)
    payloads: list[str] = []
    for chunk in chunks:
        lines = wrap_text(" ".join(chunk), max_line_chars, max_lines)
        if lines:
            payloads.append("\n".join(lines))
    return payloads or [text]


def estimated_reading_seconds(text: str, words_per_minute: float = 165.0) -> float:
    words = max(1, len(text.split()))
    base = words / max(30.0, words_per_minute) * 60.0
    punctuation = len(re.findall(r"[,.!?;:…]", text))
    return base + punctuation * 0.16


# ---------------------------------------------------------------------------
# ASS
# ---------------------------------------------------------------------------


def ass_timestamp(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    centis = int(round(seconds * 100))
    hours, rem = divmod(centis, 360_000)
    minutes, rem = divmod(rem, 6_000)
    secs, cs = divmod(rem, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{cs:02d}"


def parse_ass_timestamp(value: str) -> float:
    match = _ASS_TS.search(value.strip())
    if not match:
        raise ValueError(f"Invalid ASS timestamp: {value!r}")
    return (
        int(match.group("h")) * 3600
        + int(match.group("m")) * 60
        + int(match.group("s"))
        + int(match.group("cs").ljust(2, "0")) / 100
    )


def hex_to_ass_color(value: str, alpha: int = 0) -> str:
    """Convert ``#RRGGBB`` to ASS ``&HAABBGGRR`` (alpha 0 = opaque)."""
    value = (value or "#FFFFFF").lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    if len(value) != 6:
        value = "FFFFFF"
    try:
        red, green, blue = (int(value[index : index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        red = green = blue = 255
    alpha = max(0, min(255, int(alpha)))
    return f"&H{alpha:02X}{blue:02X}{green:02X}{red:02X}"


def ass_text(value: str) -> str:
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("{", "(").replace("}", ")")
    text = text.replace("\n", r"\N")
    return text.strip()


def unass_text(value: str) -> str:
    text = _ASS_OVERRIDE.sub("", value)
    text = text.replace(r"\N", "\n").replace(r"\n", "\n").replace(r"\h", " ")
    return "\n".join(part.strip() for part in text.split("\n")).strip()


def parse_ass(text: str) -> list[dict[str, Any]]:
    cues: list[dict[str, Any]] = []
    in_events = False
    format_fields: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.lower() == "[events]":
            in_events = True
            continue
        if line.startswith("[") and line.endswith("]"):
            in_events = False
            continue
        if not in_events:
            continue
        if line.lower().startswith("format:"):
            format_fields = [part.strip().lower() for part in line.split(":", 1)[1].split(",")]
            continue
        if not line.lower().startswith("dialogue:"):
            continue
        payload = line.split(":", 1)[1].lstrip()
        if format_fields:
            parts = payload.split(",", len(format_fields) - 1)
            row = dict(zip(format_fields, parts))
            start_s = row.get("start", "")
            end_s = row.get("end", "")
            body = row.get("text", "")
        else:
            parts = payload.split(",", 9)
            if len(parts) < 10:
                continue
            start_s, end_s, body = parts[1], parts[2], parts[9]
        try:
            start = parse_ass_timestamp(start_s)
            end = parse_ass_timestamp(end_s)
        except ValueError:
            continue
        body = unass_text(body)
        if not body:
            continue
        cues.append({"index": len(cues) + 1, "start": start, "end": end, "text": body})
    cues.sort(key=lambda cue: cue["start"])
    for index, cue in enumerate(cues, start=1):
        cue["index"] = index
    return cues


def parse_flexible_timestamp(value: str) -> float:
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    try:
        numbers = [float(part) for part in parts]
    except ValueError as exc:
        raise ValueError(f"Invalid timestamp: {value!r}") from exc
    if len(numbers) == 3:
        return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    if len(numbers) == 1:
        return numbers[0]
    raise ValueError(f"Invalid timestamp: {value!r}")


def parse_vtt(text: str) -> list[dict[str, Any]]:
    """Parse WebVTT, including MM:SS timestamps, cue ids and cue settings."""
    normal = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    if normal.startswith("WEBVTT"):
        normal = normal.split("\n", 1)[1] if "\n" in normal else ""
    cues: list[dict[str, Any]] = []
    for block in re.split(r"\n{2,}", normal.strip()):
        lines = [line for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        if lines[0].strip().upper().startswith(("NOTE", "STYLE", "REGION")):
            continue
        timestamp_index = next((index for index, line in enumerate(lines) if "-->" in line), None)
        if timestamp_index is None:
            continue
        payload = lines[timestamp_index].split("-->", 1)
        start_value = payload[0].strip()
        end_value = payload[1].strip().split(" ", 1)[0]
        try:
            start = parse_flexible_timestamp(start_value)
            end = parse_flexible_timestamp(end_value)
        except ValueError:
            continue
        body = "\n".join(lines[timestamp_index + 1 :]).strip()
        if not body:
            continue
        cues.append({"index": len(cues) + 1, "start": start, "end": end, "text": body})
    cues.sort(key=lambda cue: cue["start"])
    for index, cue in enumerate(cues, start=1):
        cue["index"] = index
    return cues


def detect_format(text: str) -> str:
    sample = text.lstrip("\ufeff \r\n\t")[:2000]
    if sample.startswith("WEBVTT"):
        return "vtt"
    if "[Script Info]" in sample or "[Events]" in sample or "Dialogue:" in sample:
        return "ass"
    return "srt"


def parse_subtitles(text: str, source_format: str = "auto") -> list[dict[str, Any]]:
    fmt = detect_format(text) if source_format in {"", "auto", None} else source_format
    if fmt == "ass":
        return parse_ass(text)
    if fmt == "vtt":
        return parse_vtt(text)
    return [
        {"index": index, "start": cue.start, "end": cue.end, "text": cue.text}
        for index, cue in enumerate(parse_srt(text), start=1)
    ]


def build_ass(
    cues: Iterable[dict[str, Any] | Any],
    *,
    title: str = "Open Studio Subtitles",
    style: dict[str, Any] | None = None,
) -> str:
    style = style or {}
    font_name = str(style.get("font_name") or "DejaVu Sans").replace(",", " ")
    font_size = max(8, int(style.get("font_size") or 54))
    primary = hex_to_ass_color(str(style.get("primary_color") or "#FFFFFF"))
    secondary = hex_to_ass_color(str(style.get("secondary_color") or "#FFD166"))
    outline_color = hex_to_ass_color(str(style.get("outline_color") or "#000000"))
    back_color = hex_to_ass_color(str(style.get("back_color") or "#000000"), 96)
    bold = -1 if style.get("bold") else 0
    italic = -1 if style.get("italic") else 0
    border_style = int(style.get("border_style") or 1)
    outline = float(style.get("outline") if style.get("outline") is not None else 2.0)
    shadow = float(style.get("shadow") if style.get("shadow") is not None else 1.0)
    alignment = int(style.get("alignment") or 2)
    margin_l = int(style.get("margin_l") or 40)
    margin_r = int(style.get("margin_r") or 40)
    margin_v = int(style.get("margin_v") or 60)
    play_res_x = int(style.get("play_res_x") or 1920)
    play_res_y = int(style.get("play_res_y") or 1080)
    spacing = float(style.get("spacing") or 0.0)
    header = f"""[Script Info]
; Generated by Open Studio AI Subtitles
Title: {title.replace(chr(10), ' ')}
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: {play_res_x}
PlayResY: {play_res_y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{primary},{secondary},{outline_color},{back_color},{bold},{italic},0,0,100,100,{spacing:g},0,{border_style},{outline:g},{shadow:g},{alignment},{margin_l},{margin_r},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for cue in cues:
        if isinstance(cue, dict):
            start = float(cue.get("start", 0.0))
            end = float(cue.get("end", start + 0.5))
            text = str(cue.get("text", ""))
        else:
            start, end, text = float(cue.start), float(cue.end), str(cue.text)
        if end <= start:
            end = start + 0.5
        lines.append(
            "Dialogue: 0,"
            f"{ass_timestamp(start)},{ass_timestamp(end)},Default,,0,0,0,,{ass_text(text)}\n"
        )
    return "".join(lines)


def build_subtitles(
    cues: Iterable[dict[str, Any] | Any],
    output_format: str,
    *,
    title: str = "Open Studio Subtitles",
    style: dict[str, Any] | None = None,
) -> str:
    output_format = output_format.lower().strip()
    if output_format == "ass":
        return build_ass(cues, title=title, style=style)
    from openstudio_common import build_srt, build_vtt

    if output_format == "vtt":
        return build_vtt(cues)
    if output_format == "srt":
        return build_srt(cues)
    raise ValueError(f"Unsupported subtitle format: {output_format}")


# ---------------------------------------------------------------------------
# Cue timing helpers
# ---------------------------------------------------------------------------


def enforce_gap(
    cues: list[dict[str, Any]],
    *,
    gap: float = 0.05,
    duration: float | None = None,
    min_duration: float = 0.25,
) -> list[dict[str, Any]]:
    """Sort cues, clamp overlaps and enforce a small inter-cue gap."""
    result = sorted(
        (
            {
                "index": 0,
                "start": max(0.0, float(cue.get("start", 0.0))),
                "end": max(0.0, float(cue.get("end", 0.0))),
                "text": str(cue.get("text", "")).strip(),
                **{key: value for key, value in cue.items() if key not in {"index", "start", "end", "text"}},
            }
            for cue in cues
            if str(cue.get("text", "")).strip()
        ),
        key=lambda cue: (cue["start"], cue["end"]),
    )
    for position, cue in enumerate(result):
        if cue["end"] <= cue["start"]:
            cue["end"] = cue["start"] + min_duration
        if position + 1 < len(result):
            next_start = result[position + 1]["start"]
            limit = next_start - max(0.0, gap)
            if cue["end"] > limit and limit > cue["start"]:
                cue["end"] = limit
            elif limit <= cue["start"]:
                cue["end"] = cue["start"] + 0.05
        if duration is not None and position == len(result) - 1 and cue["end"] > duration:
            cue["end"] = max(cue["start"] + 0.05, duration)
    for index, cue in enumerate(result, start=1):
        cue["index"] = index
        cue["start"] = round(cue["start"], 3)
        cue["end"] = round(cue["end"], 3)
    return result


def distribute_window(
    start: float,
    end: float,
    weights: list[float],
    *,
    gap: float = 0.05,
    min_duration: float = 0.4,
) -> list[tuple[float, float]]:
    """Split a time window proportionally to ``weights``."""
    count = len(weights)
    if count == 0:
        return []
    span = max(0.0, float(end) - float(start))
    safe_gap = max(0.0, gap)
    usable = max(0.0, span - safe_gap * (count - 1))
    total_weight = sum(max(1e-6, weight) for weight in weights)
    cursor = float(start)
    times: list[tuple[float, float]] = []
    for position, weight in enumerate(weights):
        share = usable * (max(1e-6, weight) / total_weight)
        cue_start = cursor
        cue_end = cue_start + share
        if position == count - 1:
            cue_end = float(end)
        if cue_end < cue_start + min_duration and position < count - 1:
            cue_end = cue_start + min_duration
        times.append((cue_start, cue_end))
        cursor = cue_end + safe_gap
    return times


def cue_weight(text: str) -> float:
    words = max(1, len(text.split()))
    punctuation = len(re.findall(r"[,.!?;:…]", text))
    return words + punctuation * 0.5


def format_cues_for_result(cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trim cue dictionaries for the UI preview (stable, JSON-safe)."""
    payload: list[dict[str, Any]] = []
    for index, cue in enumerate(cues, start=1):
        item = {
            "index": index,
            "start": round(float(cue.get("start", 0.0)), 3),
            "end": round(float(cue.get("end", 0.0)), 3),
            "text": str(cue.get("text", "")),
        }
        for key in ("confidence", "source_line", "language", "translated_text", "original_text"):
            if cue.get(key) is not None:
                item[key] = cue[key]
        payload.append(item)
    return payload
