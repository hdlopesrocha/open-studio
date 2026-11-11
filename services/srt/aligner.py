"""Lyric-to-transcript alignment.

Whisper word timestamps are matched against the user's lyric lines with a
SequenceMatcher pass plus fuzzy replacement matching. The result is one cue per
lyric line (long lines are split on punctuation/word boundaries), with
proportional timing for lines the recogniser missed and explicit handling of
instrumental gaps.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Iterable

from .formats import (
    cue_weight,
    distribute_window,
    enforce_gap,
    estimated_reading_seconds,
    split_text_for_cues,
)

_LRC_ALL = re.compile(r"\[(\d{1,2}):(\d{2}(?:[.:]\d{1,3})?)\]")
_SECTION = re.compile(r"^\[(?:verse|chorus|bridge|intro|outro|hook|pre-chorus|refrain|solo|instrumental|break|drop)[^\]]*\]$", re.I)
_METADATA = re.compile(r"^\[(?:ar|ti|al|by|offset|re|ve|length):[^\]]*\]$", re.I)
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")
_TOKEN = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)


@dataclass
class LyricLine:
    text: str
    explicit_start: float | None = None
    section: str | None = None


@dataclass
class TimedWord:
    text: str
    start: float
    end: float
    probability: float | None = None
    approximated: bool = False


@dataclass
class AsrToken:
    text: str
    start: float
    end: float
    probability: float | None = None
    word_index: int = 0


@dataclass
class AlignStats:
    total_tokens: int = 0
    matched_tokens: int = 0
    lines: int = 0
    anchored_lines: int = 0
    fallback_lines: int = 0
    weak_lines: list[int] = field(default_factory=list)
    matched_ratio: float = 0.0
    instrumental_gaps: list[dict[str, float]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_tokens": self.total_tokens,
            "matched_tokens": self.matched_tokens,
            "matched_ratio": round(self.matched_ratio, 4),
            "lines": self.lines,
            "anchored_lines": self.anchored_lines,
            "fallback_lines": self.fallback_lines,
            "weak_lines": self.weak_lines,
            "instrumental_gaps": self.instrumental_gaps,
            "warnings": self.warnings,
        }


def normalize_token(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.replace("’", "'")
    value = re.sub(r"[^\w']+", "", value)
    return value.strip("'")


def tokenize(value: str) -> list[str]:
    """Language-aware tokenizer; CJK text falls back to character tokens."""
    value = unicodedata.normalize("NFKC", value or "")
    if _CJK.search(value) and " " not in value.strip():
        tokens: list[str] = []
        for part in re.findall(r"[A-Za-z0-9]+|[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]", value):
            normalized = normalize_token(part)
            if normalized:
                tokens.append(normalized)
        return tokens
    return [normalized for normalized in (normalize_token(match.group(0)) for match in _TOKEN.finditer(value)) if normalized]


def parse_lyric_lines(text: str) -> list[LyricLine]:
    """Parse plain or LRC lyrics, dropping section tags and comments."""
    lines: list[LyricLine] = []
    for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        value = raw.strip()
        if not value or value.startswith("#") or value.startswith("//"):
            continue
        if _SECTION.match(value) or _METADATA.match(value):
            continue
        stamps = _LRC_ALL.findall(value)
        body = value
        explicit_start: float | None = None
        if stamps:
            body = _LRC_ALL.sub("", value).strip()
            match = _LRC_ALL.search(value)
            if match:
                try:
                    minutes = float(match.group(1))
                    seconds = float(match.group(2).replace(":", "."))
                    explicit_start = minutes * 60 + seconds
                except ValueError:
                    explicit_start = None
        if not body:
            continue
        section_match = re.match(r"^\[([^\]]+)\]\s*(.*)$", body)
        section = None
        if section_match and not section_match.group(2):
            continue
        if section_match:
            section = section_match.group(1).strip().lower()
            body = section_match.group(2).strip()
            if not body:
                continue
        lines.append(LyricLine(text=body, explicit_start=explicit_start, section=section))
    return lines


def extract_words(segments: Iterable[dict[str, Any]]) -> tuple[list[TimedWord], bool]:
    """Flatten faster-whisper segments into timed words.

    Returns ``(words, approximated)``. If a segment has no word timestamps the
    words are distributed across the segment proportionally to their length.
    """
    words: list[TimedWord] = []
    approximated = False
    for segment in segments:
        start = float(segment.get("start") or 0.0)
        end = float(segment.get("end") or start)
        raw_words = segment.get("words") or []
        if raw_words:
            for item in raw_words:
                text = str(item.get("word") or item.get("text") or "").strip()
                if not text:
                    continue
                word_start = item.get("start")
                word_end = item.get("end")
                if word_start is None:
                    word_start = start
                if word_end is None:
                    word_end = word_start
                probability = item.get("probability")
                words.append(
                    TimedWord(
                        text=text,
                        start=max(0.0, float(word_start)),
                        end=max(float(word_start), float(word_end)),
                        probability=float(probability) if probability is not None else None,
                    )
                )
            continue
        approximated = True
        text = str(segment.get("text") or "").strip()
        tokens = text.split()
        if not tokens:
            continue
        total_chars = sum(max(1, len(token)) for token in tokens)
        cursor = start
        span = max(0.05, end - start)
        for token in tokens:
            share = span * (max(1, len(token)) / total_chars)
            words.append(TimedWord(text=token, start=cursor, end=min(end, cursor + share)))
            cursor += share
    # A missing segment word list is not the same as a missing model output.
    return words, approximated


def _asr_tokens(words: list[TimedWord]) -> tuple[list[AsrToken], list[list[int]]]:
    tokens: list[AsrToken] = []
    word_to_tokens: list[list[int]] = []
    for word_index, word in enumerate(words):
        indices: list[int] = []
        pieces = tokenize(word.text)
        if not pieces:
            word_to_tokens.append(indices)
            continue
        for piece in pieces:
            indices.append(len(tokens))
            tokens.append(
                AsrToken(
                    text=piece,
                    start=word.start,
                    end=word.end,
                    probability=word.probability,
                    word_index=word_index,
                )
            )
        word_to_tokens.append(indices)
    return tokens, word_to_tokens


def _fuzzy_replace(
    lyric_tokens: list[str],
    asr_tokens: list[AsrToken],
    i1: int,
    i2: int,
    j1: int,
    j2: int,
    mapping: dict[int, int],
) -> None:
    """Pair tokens inside a ``replace`` opcode using pairwise similarity."""
    count = min(i2 - i1, j2 - j1)
    for offset in range(count):
        left = lyric_tokens[i1 + offset]
        right = asr_tokens[j1 + offset].text
        if not left or not right:
            continue
        if left == right or SequenceMatcher(None, left, right, autojunk=False).ratio() >= 0.72:
            mapping[i1 + offset] = j1 + offset


def match_tokens(lyric_tokens: list[str], asr_tokens: list[AsrToken]) -> dict[int, int]:
    """Map lyric-token index -> ASR-token index."""
    if not lyric_tokens or not asr_tokens:
        return {}
    matcher = SequenceMatcher(None, lyric_tokens, [token.text for token in asr_tokens], autojunk=False)
    mapping: dict[int, int] = {}
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for lyric_index, asr_index in zip(range(i1, i2), range(j1, j2)):
                mapping[lyric_index] = asr_index
        elif tag == "replace":
            _fuzzy_replace(lyric_tokens, asr_tokens, i1, i2, j1, j2, mapping)
    return mapping


def _line_weight(text: str) -> float:
    return max(0.75, estimated_reading_seconds(text, words_per_minute=150.0))


def _distribute_missing(
    line_indices: list[int],
    lines: list[LyricLine],
    line_times: dict[int, tuple[float, float]],
    anchored: set[int],
    first_anchor_start: float | None,
    last_anchor_end: float | None,
    duration: float,
    *,
    gap: float,
    stats: AlignStats,
) -> None:
    """Time lines whose tokens were not found, respecting instrumental gaps."""
    for index in line_indices:
        if index in anchored or index in line_times:
            continue
        previous = next((candidate for candidate in range(index - 1, -1, -1) if candidate in line_times), None)
        following = next((candidate for candidate in range(index + 1, len(lines)) if candidate in line_times), None)
        previous_end = line_times[previous][1] if previous is not None else 0.0
        following_start = line_times[following][0] if following is not None else duration

        # A run of consecutive missing lines is distributed as one window.
        run = [index]
        cursor = index + 1
        while cursor < len(lines) and cursor not in line_times and cursor not in anchored:
            if lines[cursor].explicit_start is not None:
                break
            run.append(cursor)
            cursor += 1
        if cursor == index:
            continue
        weights = [_line_weight(lines[item].text) for item in run]
        target_total = sum(weights)
        left = previous_end
        right = following_start
        if right - left > target_total * 2.5 + 2.0:
            # Do not stretch a line through an instrumental break. Sit the run
            # next to the following vocal or the previous one.
            if following is not None:
                left = max(left, right - target_total - gap)
            else:
                right = min(right, left + max(target_total, 3.0))
        if right < left:
            right = left + target_total
        times = distribute_window(left, right, weights, gap=gap, min_duration=0.35)
        for item, (start, end) in zip(run, times):
            line_times[item] = (start, end)
            stats.fallback_lines += 1
        index = run[-1] + 1


def align_lyrics(
    lyrics_text: str,
    segments: list[dict[str, Any]],
    duration: float,
    *,
    max_line_chars: int = 42,
    max_lines: int = 2,
    segment_gap: float = 0.06,
    instrumental_gap: float = 8.0,
) -> tuple[list[dict[str, Any]], AlignStats]:
    lines = parse_lyric_lines(lyrics_text)
    stats = AlignStats(lines=len(lines))
    if not lines:
        stats.warnings.append("No lyric lines were found in the supplied text.")
        return [], stats

    words, approximated = extract_words(segments)
    if approximated:
        stats.warnings.append(
            "Whisper did not return word-level timestamps for part of the audio; "
            "lyric times are estimated inside those segments."
        )
    if not words:
        stats.warnings.append("No speech was recognised; lyric lines were distributed across the audio.")

    asr_tokens, _word_to_tokens = _asr_tokens(words)
    line_token_ranges: list[tuple[int, int]] = []
    lyric_tokens: list[str] = []
    for line in lines:
        start_index = len(lyric_tokens)
        lyric_tokens.extend(tokenize(line.text))
        line_token_ranges.append((start_index, len(lyric_tokens)))
    stats.total_tokens = len(lyric_tokens)
    mapping = match_tokens(lyric_tokens, asr_tokens)
    stats.matched_tokens = len(mapping)
    stats.matched_ratio = (len(mapping) / len(lyric_tokens)) if lyric_tokens else 0.0

    line_times: dict[int, tuple[float, float]] = {}
    line_confidence: dict[int, float] = {}
    weak: set[int] = set()
    for line_index, (token_start, token_end) in enumerate(line_token_ranges):
        token_count = token_end - token_start
        if token_count == 0:
            continue
        matched = [mapping[index] for index in range(token_start, token_end) if index in mapping]
        if not matched:
            continue
        start = min(asr_tokens[index].start for index in matched)
        end = max(asr_tokens[index].end for index in matched)
        confidence = len(matched) / token_count
        line_times[line_index] = (start, max(start + 0.05, end))
        line_confidence[line_index] = confidence
        if confidence < 0.34 and token_count >= 3:
            weak.add(line_index)
        if lines[line_index].explicit_start is not None:
            hinted = float(lines[line_index].explicit_start)
            length = max(0.6, line_times[line_index][1] - line_times[line_index][0])
            line_times[line_index] = (hinted, hinted + length)

    anchored = set(line_times)
    stats.anchored_lines = len(anchored)
    first_anchor_start = min((value[0] for value in line_times.values()), default=None)
    last_anchor_end = max((value[1] for value in line_times.values()), default=None)

    if not anchored:
        span_start = min((word.start for word in words), default=0.0)
        span_end = max((word.end for word in words), default=duration)
        if span_end - span_start < 1.0:
            span_start, span_end = 0.0, max(1.0, duration)
        weights = [_line_weight(line.text) for line in lines]
        times = distribute_window(span_start, span_end, weights, gap=segment_gap, min_duration=0.35)
        for index, (start, end) in enumerate(times):
            line_times[index] = (start, end)
            line_confidence[index] = 0.0
            stats.fallback_lines += 1
        if words:
            stats.warnings.append(
                "The lyrics could not be matched to the transcript; all cues were timed proportionally."
            )
    else:
        # Missing lines before the first anchor.
        before = [index for index in range(len(lines)) if index not in line_times and (first_anchor_start or 0) > 0]
        if before:
            _distribute_missing(
                before,
                lines,
                line_times,
                anchored,
                first_anchor_start,
                last_anchor_end,
                duration,
                gap=segment_gap,
                stats=stats,
            )
        # Missing lines after the last anchor.
        after = [index for index in range(len(lines)) if index not in line_times]
        if after:
            previous = max((index for index in line_times), default=None)
            if previous is not None:
                _distribute_missing(
                    [index for index in range(previous + 1, len(lines)) if index not in line_times],
                    lines,
                    line_times,
                    anchored,
                    first_anchor_start,
                    last_anchor_end,
                    duration,
                    gap=segment_gap,
                    stats=stats,
                )
        # Any remaining missing lines (singletons between anchors).
        remaining = [index for index in range(len(lines)) if index not in line_times]
        if remaining:
            _distribute_missing(
                remaining,
                lines,
                line_times,
                anchored,
                first_anchor_start,
                last_anchor_end,
                duration,
                gap=segment_gap,
                stats=stats,
            )

    # Explicit LRC timestamps are authoritative even when ASR missed the line.
    for index, line in enumerate(lines):
        if line.explicit_start is None or index not in line_times:
            continue
        start = max(0.0, float(line.explicit_start))
        current_end = line_times[index][1]
        length = max(0.6, current_end - line_times[index][0])
        line_times[index] = (start, start + length)

    # Enforce readable minimums without crossing the next line.
    ordered = sorted(line_times.items())
    for position, (index, (start, end)) in enumerate(ordered):
        next_start = ordered[position + 1][1][0] if position + 1 < len(ordered) else duration
        start = max(0.0, start)
        if end < start + 0.35:
            end = start + 0.35
        if next_start is not None and end > next_start - min(0.02, segment_gap):
            end = max(start + 0.15, next_start - min(0.02, segment_gap))
        if duration and end > duration:
            end = max(start + 0.05, duration)
        line_times[index] = (start, end)

    stats.weak_lines = sorted(index + 1 for index in weak)
    if stats.weak_lines:
        stats.warnings.append(
            "Weak lyric matches on line(s) "
            + ", ".join(str(index) for index in stats.weak_lines[:12])
            + ("..." if len(stats.weak_lines) > 12 else "")
            + "; review those cue times after alignment."
        )
    if stats.fallback_lines and stats.anchored_lines:
        stats.warnings.append(
            f"{stats.fallback_lines} lyric line(s) had no recognisable words and were timed proportionally."
        )
    if stats.matched_tokens and stats.total_tokens and stats.matched_ratio < 0.45:
        stats.warnings.append(
            f"Only {stats.matched_ratio * 100:.0f}% of lyric tokens matched the transcript. "
            "Check the language/model or edit the cues after alignment."
        )

    # Build one or more cues per line, splitting long lines on punctuation.
    cues: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        start, end = line_times.get(index, (0.0, min(duration, 1.0)))
        chunks = split_text_for_cues(line.text, max_line_chars=max_line_chars, max_lines=max_lines)
        if not chunks:
            continue
        confidence = round(line_confidence.get(index, 0.0), 3)
        if len(chunks) == 1:
            cues.append(
                {
                    "start": start,
                    "end": end,
                    "text": chunks[0],
                    "confidence": confidence,
                    "source_line": index + 1,
                }
            )
            continue
        weights = [cue_weight(chunk) for chunk in chunks]
        times = distribute_window(start, end, weights, gap=min(0.08, segment_gap), min_duration=0.3)
        for chunk, (chunk_start, chunk_end) in zip(chunks, times):
            cues.append(
                {
                    "start": chunk_start,
                    "end": chunk_end,
                    "text": chunk,
                    "confidence": confidence,
                    "source_line": index + 1,
                }
            )

    cues = enforce_gap(cues, gap=segment_gap, duration=duration, min_duration=0.25)

    # Report meaningful instrumental intervals between cues for the UI.
    for left, right in zip(cues, cues[1:]):
        gap_size = float(right["start"]) - float(left["end"])
        if gap_size >= instrumental_gap:
            stats.instrumental_gaps.append(
                {
                    "start": round(float(left["end"]), 3),
                    "end": round(float(right["start"]), 3),
                    "duration": round(gap_size, 3),
                }
            )
    if stats.instrumental_gaps:
        longest = max(item["duration"] for item in stats.instrumental_gaps)
        stats.warnings.append(
            f"Detected {len(stats.instrumental_gaps)} instrumental gap(s); longest {longest:.1f}s. "
            "Those intervals intentionally have no lyric cues."
        )
    if not cues:
        stats.warnings.append("Alignment produced no cues.")
    return cues, stats


def proportional_cues_from_lines(
    text: str,
    duration: float,
    *,
    start: float = 0.0,
    end: float | None = None,
    max_line_chars: int = 42,
    max_lines: int = 2,
    gap: float = 0.08,
    words_per_minute: float = 160.0,
) -> list[dict[str, Any]]:
    """Estimate cue timings from plain text without any model."""
    lines = parse_lyric_lines(text)
    if not lines:
        return []
    window_start = max(0.0, float(start))
    window_end = float(end) if end is not None else max(window_start + 1.0, float(duration))
    if window_end <= window_start:
        window_end = window_start + 1.0
    prepared: list[tuple[str, list[str], float]] = []
    for line in lines:
        chunks = split_text_for_cues(line.text, max_line_chars=max_line_chars, max_lines=max_lines)
        if not chunks:
            continue
        # Singing is slower than reading; keep the estimate expressive.
        paused = estimated_reading_seconds(line.text, words_per_minute=max(60.0, words_per_minute)) * 1.18
        prepared.append((line.text, chunks, max(0.7, paused)))
    if not prepared:
        return []
    weights = [weight for _line, _chunks, weight in prepared]
    available = max(0.1, window_end - window_start)
    natural_total = sum(max(0.7, weight) for weight in weights)
    line_windows: list[tuple[float, float]] = []
    if natural_total <= available:
        # Keep cue durations natural but spread their starts across the audio,
        # so sparse lyrics do not become one giant cue and full lyrics still
        # follow the whole song. The final line lands on the window end.
        total_weight = sum(max(1e-6, weight) for weight in weights)
        cumulative = 0.0
        starts: list[float] = []
        for weight in weights:
            starts.append(window_start + available * (cumulative / total_weight))
            cumulative += max(1e-6, weight)
        if len(starts) > 1:
            starts[-1] = max(starts[-2] + 0.2, window_end - max(0.7, weights[-1]))
        for index, start in enumerate(starts):
            length = max(0.7, weights[index])
            end = min(window_end, start + length)
            if index + 1 < len(starts):
                end = min(end, max(start + 0.2, starts[index + 1] - gap))
            line_windows.append((start, max(start + 0.2, end)))
    else:
        line_windows = distribute_window(window_start, window_end, weights, gap=gap, min_duration=0.35)
    cues: list[dict[str, Any]] = []
    for line_index, (_line, chunks, _weight) in enumerate(prepared, start=1):
        line_start, line_end = line_windows[line_index - 1]
        chunk_weights = [cue_weight(chunk) for chunk in chunks]
        chunk_times = distribute_window(
            line_start,
            max(line_start + 0.2, line_end),
            chunk_weights,
            gap=min(gap, 0.05),
            min_duration=0.2,
        )
        for chunk, (chunk_start, chunk_end) in zip(chunks, chunk_times):
            cues.append(
                {
                    "start": chunk_start,
                    "end": chunk_end,
                    "text": chunk,
                    "confidence": 0.5,
                    "source_line": line_index,
                }
            )
    return enforce_gap(cues, gap=gap, duration=window_end, min_duration=0.2)


def suggested_total_duration(text: str, *, words_per_minute: float = 150.0) -> float:
    lines = parse_lyric_lines(text)
    if not lines:
        return 0.0
    weight = sum(_line_weight(line.text) for line in lines)
    pauses = max(0, len(lines) - 1) * 0.35
    spoken = sum(max(1, len(line.text.split())) for line in lines) / max(30.0, words_per_minute) * 60.0
    return round(min(weight, max(spoken, weight * 0.85)) + pauses, 2)


def window_from_times(
    *,
    duration: float | None = None,
    start: float = 0.0,
    end: float | None = None,
) -> tuple[float, float]:
    if end is not None:
        return max(0.0, float(start)), max(float(start) + 0.1, float(end))
    if duration is not None:
        return max(0.0, float(start)), max(float(start) + 0.1, float(duration))
    raise ValueError("A duration, end time or audio file is required to estimate cue timings")


def round_stats(stats: AlignStats) -> dict[str, Any]:
    payload = stats.as_dict()
    payload["matched_ratio"] = round(float(payload["matched_ratio"]), 4)
    return payload


__all__ = [
    "AlignStats",
    "LyricLine",
    "TimedWord",
    "align_lyrics",
    "parse_lyric_lines",
    "proportional_cues_from_lines",
    "suggested_total_duration",
    "tokenize",
    "window_from_times",
]
