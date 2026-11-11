"""Text segmentation for translation requests."""

from __future__ import annotations

import re
from typing import Any

from .text import PAGE_MARKER, split_paragraphs


def segments_from_text(text: str, max_chars: int = 850) -> list[dict[str, Any]]:
    """Create paragraph segments while keeping explicit PDF page boundaries.

    Page markers are consumed as structure and re-emitted by the response
    builder, so they are never sent to the model.
    """
    del max_chars  # chunking is performed by the engine with token limits
    matches = list(PAGE_MARKER.finditer(text or ""))
    blocks: list[tuple[int | None, str]] = []
    if not matches:
        blocks.append((None, text or ""))
    else:
        prefix = text[: matches[0].start()]
        if prefix.strip():
            blocks.append((None, prefix))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            blocks.append((int(match.group(1)), text[match.end() : end]))
    segments: list[dict[str, Any]] = []
    for page, block in blocks:
        for paragraph in split_paragraphs(block):
            segments.append(
                {
                    "id": f"p{len(segments) + 1}",
                    "page": page,
                    "text": re.sub(r"[ \t]+", " ", paragraph).strip(),
                }
            )
    return segments
