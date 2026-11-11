"""Small text helpers for the documents workflow."""

from __future__ import annotations

import re

PAGE_MARKER_LINE = re.compile(r"(?m)^[ \t]*---[ \t]*Page[ \t]+\d+[ \t]*---[ \t]*$")


def clean_text(value: str) -> str:
    text = (value or "").replace("\r\n", "\n").replace("\r", "\n").replace("\x00", " ")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_paragraphs(text: str) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\wÀ-ÿ'-]+\b", text or ""))


def strip_page_markers(text: str) -> str:
    return PAGE_MARKER_LINE.sub(" ", text or "")


def join_texts(parts) -> str:
    return "\n\n".join(part.strip() for part in parts if part and part.strip())
