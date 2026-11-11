"""Local text helpers for the translation service.

These helpers intentionally live in the service instead of the shared package so
the component stays self-contained and can be deployed independently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

PAGE_MARKER = re.compile(r"(?m)^[ \t]*---[ \t]*Page[ \t]+(\d+)[ \t]*---[ \t]*$")
_PAGE_MARKER_LINE = re.compile(r"(?m)^[ \t]*---[ \t]*Page[ \t]+\d+[ \t]*---[ \t]*$")

_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "fig", "no",
    "vol", "approx", "dept", "inc", "ltd", "co", "u.s", "u.k", "jan", "feb",
    "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "sra", "dra", "profa", "eng", "ex", "exmo", "exma", "ilmo", "ilma", "pág",
    "pag", "cap", "art", "al", "av", "tv", "a.c", "d.c", "nº", "tab", "ref",
    "ed", "org", "coord", "p.ex", "v.g", "fev", "abr", "mai", "ago", "set",
    "out", "dez",
}


def clean_text(value: str) -> str:
    """Normalise line endings and whitespace without touching paragraph breaks."""
    text = (value or "").replace("\r\n", "\n").replace("\r", "\n").replace("\x00", " ")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_page_blocks(text: str) -> list[tuple[int | None, str]]:
    """Split text on ``--- Page N ---`` markers, keeping the marker values."""
    matches = list(PAGE_MARKER.finditer(text))
    if not matches:
        return [(None, text)]
    blocks: list[tuple[int | None, str]] = []
    prefix = text[: matches[0].start()]
    if prefix.strip():
        blocks.append((None, prefix))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append((int(match.group(1)), text[match.end() : end]))
    return blocks


def split_paragraphs(text: str) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    # A page marker on its own line separates pages, not paragraphs.
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    return paragraphs


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\wÀ-ÿ'-]+\b", text or ""))


def _protect_periods(text: str) -> str:
    text = re.sub(r"(?<=\d)\.(?=\d)", "\uE000", text)

    def protect(match: re.Match[str]) -> str:
        return match.group(0)[:-1] + "\uE000"

    text = re.sub(
        r"(?i)\b(?:mr|mrs|ms|dr|dra|prof|profa|sr|sra|jr|st|vs|etc|e\.g|i\.e|fig|no|vol|"
        r"approx|dept|inc|ltd|co|u\.s|u\.k|pág|pag|cap|art|al|av|tv|a\.c|d\.c|nº|tab|"
        r"ref|ed|org|coord|p\.ex|v\.g|jan|fev|feb|mar|abr|apr|mai|may|jun|jul|ago|aug|"
        r"set|sep|sept|out|oct|nov|dez|dec)\.",
        protect,
        text,
    )
    text = re.sub(r"(?<=\b[A-ZÁÉÍÓÚÂÊÔÃÕÇ])\.(?=\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ]\.)", "\uE000", text)
    text = re.sub(
        r"(?<=\b[A-ZÁÉÍÓÚÂÊÔÃÕÇ])\.(?=\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç])",
        "\uE000",
        text,
    )
    return text


def sentence_split(text: str) -> list[str]:
    """Conservative sentence splitter that protects abbreviations and decimals."""
    text = clean_text(text)
    if not text:
        return []
    protected = _protect_periods(text)
    sentences: list[str] = []
    start = 0
    closers = "\"'”’»)]}"
    i = 0
    length = len(protected)
    while i < length:
        char = protected[i]
        if char in ".!?…":
            j = i + 1
            while j < length and protected[j] == "…":
                j += 1
            while j < length and protected[j] in closers:
                j += 1
            k = j
            while k < length and protected[k] in " \t":
                k += 1
            next_char = "\n" if k < length and protected[k] == "\n" else (protected[k] if k < length else "")
            should_split = k >= length or next_char == "\n" or next_char.isupper() or next_char.isdigit() or next_char in "\"'“«("
            if should_split:
                piece = protected[start:j].strip()
                if piece:
                    sentences.append(piece.replace("\uE000", ".").replace("\n", " "))
                start = j
                i = j
                continue
        i += 1
    tail = protected[start:].strip().replace("\uE000", ".").replace("\n", " ")
    if tail:
        sentences.append(tail)
    return [sentence.strip() for sentence in sentences if sentence.strip()]


def split_long_piece(piece: str, max_chars: int) -> list[str]:
    """Split an overly long sentence at clauses, then words, without data loss."""
    piece = piece.strip()
    if len(piece) <= max_chars:
        return [piece]
    parts: list[str] = []
    remainder = piece
    while len(remainder) > max_chars:
        window = remainder[: max_chars + 1]
        cut = max(
            window.rfind("; "),
            window.rfind(": "),
            window.rfind(", "),
            window.rfind(" — "),
            window.rfind(" – "),
        )
        if cut < max_chars // 2:
            cut = window.rfind(" ")
        if cut < max_chars // 3:
            cut = max_chars
        candidate = remainder[:cut].strip()
        if candidate:
            parts.append(candidate)
        remainder = remainder[cut:].strip()
    if remainder:
        parts.append(remainder)
    return parts


def chunk_paragraph(paragraph: str, max_chars: int = 850) -> list[str]:
    """Pack whole sentences into chunks, preserving sentence boundaries."""
    if max_chars < 80:
        raise ValueError("max_chars must be at least 80")
    sentences = sentence_split(paragraph)
    if not sentences:
        return []
    pieces: list[str] = []
    for sentence in sentences:
        pieces.extend(split_long_piece(sentence, max_chars))
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if not current:
            current = piece
        elif len(current) + 1 + len(piece) <= max_chars:
            current = f"{current} {piece}"
        else:
            chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
    return chunks


def strip_page_markers(text: str) -> str:
    return _PAGE_MARKER_LINE.sub(" ", text or "")


def join_paragraphs(paragraphs: Iterable[str]) -> str:
    return "\n\n".join(paragraph.strip() for paragraph in paragraphs if paragraph and paragraph.strip())


@dataclass
class Span:
    """A literal (markup/glossary) or translatable span."""

    text: str
    literal: bool = False
