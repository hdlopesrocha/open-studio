"""Text splitting helpers for TTS and batch generation.

Piper is synthesized sentence by sentence so the resulting timeline uses real
sentence durations. OmniVoice also splits long text at sentence boundaries so a
cancelled job can stop between model calls.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable

_WHITESPACE = re.compile(r"[ \t\u00a0]+")
_SENTENCE_END = re.compile(r"(?<=[.!?…。！？])\s+|\n+")
_LONG_SPLIT = re.compile(r"(?<=[,;:，；：、])\s+")


def clean_text(text: str) -> str:
    """Normalize user text without destroying paragraph separators."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned_lines: list[str] = []
    for raw_line in text.split("\n"):
        line = "".join(
            char
            for char in raw_line
            if char == "\t" or unicodedata.category(char) not in {"Cc", "Cf"}
        )
        line = _WHITESPACE.sub(" ", line).strip()
        cleaned_lines.append(line)
    # Collapse runs of blank lines but keep paragraph boundaries.
    result: list[str] = []
    blank = False
    for line in cleaned_lines:
        if not line:
            if result and not blank:
                result.append("")
            blank = True
            continue
        result.append(line)
        blank = False
    return "\n".join(result).strip()


def split_paragraphs(text: str) -> list[str]:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", normalized)]
    return [part for part in paragraphs if part]


def sentence_split(text: str, language: str | None = None) -> list[str]:
    """Split a paragraph into sentence-like pieces.

    The splitter is deliberately conservative: it splits after strong terminal
    punctuation followed by whitespace, plus on hard newlines. Abbreviations
    and decimals therefore usually stay intact, while subtitles still get short
    per-sentence audio chunks.
    """
    del language  # reserved for future language-specific abbreviation rules
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    pieces: list[str] = []
    for line in normalized.split("\n"):
        line = line.strip()
        if not line:
            continue
        for piece in _SENTENCE_END.split(line):
            piece = piece.strip()
            if piece:
                pieces.append(piece)
    return pieces


def split_long_piece(text: str, max_chars: int) -> list[str]:
    """Split an over-long sentence at commas, then at word boundaries."""
    if max_chars <= 0 or len(text) <= max_chars:
        return [text]

    parts: list[str] = []
    buffer = ""
    for piece in _LONG_SPLIT.split(text):
        piece = piece.strip()
        if not piece:
            continue
        if not buffer:
            buffer = piece
        elif len(buffer) + 1 + len(piece) <= max_chars:
            buffer = f"{buffer} {piece}"
        else:
            parts.append(buffer)
            buffer = piece
    if buffer:
        parts.append(buffer)

    result: list[str] = []
    for part in parts:
        if len(part) <= max_chars:
            result.append(part)
            continue
        words = part.split()
        line = ""
        for word in words:
            if not line:
                line = word
            elif len(line) + 1 + len(word) <= max_chars:
                line = f"{line} {word}"
            else:
                result.append(line)
                line = word
        if line:
            result.append(line)
    return result or [text]


def split_speech_segments(text: str, language: str | None, max_chars: int) -> list[str]:
    """Return clean, speakable segments in reading order."""
    segments: list[str] = []
    for paragraph in split_paragraphs(clean_text(text)):
        for sentence in sentence_split(paragraph, language):
            for piece in split_long_piece(sentence, max_chars):
                cleaned = clean_text(piece).replace("\n", " ").strip()
                if cleaned and any(char.isalnum() for char in cleaned):
                    segments.append(cleaned)
    return segments


def split_text_for_jobs(text: str, max_chars: int = 420) -> list[str]:
    """Split long text for cancellable OmniVoice generation."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    for paragraph in split_paragraphs(text):
        for piece in sentence_split(paragraph):
            if len(piece) > max_chars:
                chunks.extend(split_long_piece(piece, max_chars))
            else:
                chunks.append(piece)

    # Recombine short pieces up to max_chars so we do not make one model call
    # per tiny sentence.
    merged: list[str] = []
    current = ""
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if not current:
            current = chunk
        elif len(current) + 1 + len(chunk) <= max_chars:
            current = f"{current} {chunk}"
        else:
            merged.append(current)
            current = chunk
    if current:
        merged.append(current)
    return merged or [text]


def split_batch_text(text: str, mode: str) -> list[str]:
    """Split raw batch input into items (blank-line or line mode)."""
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    if mode == "line":
        parts: Iterable[str] = normalized.split("\n")
    else:
        parts = re.split(r"\n\s*\n+", normalized)
    items = [clean_text(part).replace("\n", " ").strip() for part in parts]
    return [item for item in items if item]
