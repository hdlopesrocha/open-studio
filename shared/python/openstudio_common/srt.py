"""Subtitle parsing/building helpers (SRT + WebVTT)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

_TS = re.compile(
    r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{1,3})"
)


@dataclass
class Cue:
    index: int
    start: float
    end: float
    text: str

    def to_dict(self) -> dict:
        return {"index": self.index, "start": self.start, "end": self.end, "text": self.text}


def parse_timestamp(value: str) -> float:
    match = _TS.search(value.strip())
    if not match:
        raise ValueError(f"Invalid timestamp: {value}")
    return (
        int(match.group("h")) * 3600
        + int(match.group("m")) * 60
        + int(match.group("s"))
        + int(match.group("ms").ljust(3, "0")) / 1000
    )


def format_timestamp(seconds: float, *, vtt: bool = False) -> str:
    seconds = max(0.0, float(seconds))
    millis = int(round(seconds * 1000))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    sep = "." if vtt else ","
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{sep}{ms:03d}"


def parse_srt(text: str) -> list[Cue]:
    normal = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normal:
        return []
    cues: list[Cue] = []
    blocks = re.split(r"\n{2,}", normal)
    for block in blocks:
        lines = [line for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        index = len(cues) + 1
        if lines[0].strip().isdigit():
            index = int(lines[0].strip())
            lines = lines[1:]
        if not lines or "-->" not in lines[0]:
            continue
        start_s, end_s = [part.strip() for part in lines[0].split("-->", 1)]
        payload = "\n".join(lines[1:]).strip()
        cues.append(Cue(index=index, start=parse_timestamp(start_s), end=parse_timestamp(end_s), text=payload))
    return cues


def parse_vtt(text: str) -> list[Cue]:
    body = re.sub(r"^WEBVTT.*?\n\n", "", text.replace("\r\n", "\n"), flags=re.S)
    return parse_srt(body)


def parse_any(text: str) -> list[Cue]:
    if text.lstrip().startswith("WEBVTT"):
        return parse_vtt(text)
    return parse_srt(text)


def build_srt(cues: Iterable[Cue | dict], *, renumber: bool = True) -> str:
    blocks: list[str] = []
    for position, cue in enumerate(cues, start=1):
        if isinstance(cue, dict):
            start = float(cue.get("start", 0))
            end = float(cue.get("end", start + 1))
            text = str(cue.get("text", "")).strip()
            index = int(cue.get("index", position)) if not renumber else position
        else:
            start, end, text, index = cue.start, cue.end, cue.text, cue.index
            if renumber:
                index = position
        if end <= start:
            end = start + 0.5
        blocks.append(f"{index}\n{format_timestamp(start)} --> {format_timestamp(end)}\n{text.strip()}\n")
    return "\n".join(blocks)


def build_vtt(cues: Iterable[Cue | dict]) -> str:
    blocks = ["WEBVTT\n"]
    for cue in cues:
        if isinstance(cue, dict):
            start = float(cue.get("start", 0))
            end = float(cue.get("end", start + 1))
            text = str(cue.get("text", "")).strip()
        else:
            start, end, text = cue.start, cue.end, cue.text
        blocks.append(f"{format_timestamp(start, vtt=True)} --> {format_timestamp(end, vtt=True)}\n{text}\n")
    return "\n".join(blocks)


def normalize_cues(cues: list[dict], *, min_duration: float = 0.4) -> list[dict]:
    normalized: list[dict] = []
    for idx, cue in enumerate(cues):
        start = max(0.0, float(cue.get("start", 0)))
        end = max(start + min_duration, float(cue.get("end", start + min_duration)))
        if idx + 1 < len(cues):
            next_start = float(cues[idx + 1].get("start", end))
            if end > next_start:
                end = max(start + 0.05, next_start)
        normalized.append(
            {
                "index": idx + 1,
                "start": round(start, 3),
                "end": round(end, 3),
                "text": str(cue.get("text", "")).strip(),
            }
        )
    return normalized


def split_lyric_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if re.fullmatch(r"\[.*?\]", line):
            continue
        lines.append(line)
    return lines
