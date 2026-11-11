"""Pydantic request models for the translation API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import settings
from .text import word_count


def normalize_glossary(value: Any) -> dict[str, str]:
    """Accept a mapping, a list of pairs, or a list of source/target objects."""
    terms: dict[str, str] = {}
    if value is None:
        return terms
    entries: list[tuple[Any, Any]] = []
    if isinstance(value, dict):
        if "terms" in value and isinstance(value["terms"], list):
            value = value["terms"]
        elif "entries" in value and isinstance(value["entries"], list):
            value = value["entries"]
        else:
            entries = list(value.items())
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                source = item.get("source", item.get("term", item.get("from")))
                target = item.get("target", item.get("translation", item.get("to")))
                entries.append((source, target))
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                entries.append((item[0], item[1]))
            else:
                raise ValueError("Each glossary entry must be a [source, target] pair")
    for source, target in entries:
        source_text = str(source or "").strip()
        target_text = str(target or "").strip()
        if not source_text or not target_text:
            continue
        if len(source_text) > 200 or len(target_text) > 400:
            raise ValueError("Glossary terms are limited to 200/400 characters")
        terms[source_text] = target_text
    if len(terms) > 500:
        raise ValueError("A translation glossary is limited to 500 terms")
    return terms


class SegmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, max_length=200)
    page: int | None = Field(default=None, ge=1, le=100_000)
    text: str = Field(min_length=1)


class TranslateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, max_length=settings.max_input_chars)
    segments: list[SegmentInput] | None = Field(default=None, max_length=settings.max_segments)
    source_language: str = "auto"
    target_language: str = "en"
    model: str = "auto"
    num_beams: int = Field(default=2, ge=1, le=16)
    max_length: int = Field(default=512, ge=8, le=4096)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    length_penalty: float = Field(default=1.0, ge=-5.0, le=5.0)
    repetition_penalty: float = Field(default=1.0, ge=0.1, le=5.0)
    no_repeat_ngram_size: int = Field(default=3, ge=0, le=10)
    batch_size: int = Field(default=8, ge=1, le=64)
    preserve_markup: bool = True
    glossary: dict[str, str] | list[Any] | None = None

    @field_validator("glossary", mode="before")
    @classmethod
    def _glossary(cls, value: Any) -> dict[str, str] | None:
        if value is None:
            return None
        return normalize_glossary(value)

    @field_validator("segments", mode="before")
    @classmethod
    def _segments(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [{"text": item} if isinstance(item, str) else item for item in value]
        return value

    @model_validator(mode="after")
    def require_content(self) -> "TranslateRequest":
        if self.text is not None and self.segments is not None:
            raise ValueError("Provide either text or segments, not both")
        if self.text is None and not self.segments:
            raise ValueError("Provide text or at least one segment")
        total = len(self.text or "")
        total += sum(len(segment.text) for segment in self.segments or [])
        if total > settings.max_input_chars:
            raise ValueError(
                f"The text exceeds the {settings.max_input_chars}-character limit"
            )
        if self.segments and len(self.segments) > settings.max_segments:
            raise ValueError(f"At most {settings.max_segments} segments are allowed")
        if not (self.text or "").strip() and not any(
            segment.text.strip() for segment in self.segments or []
        ):
            raise ValueError("There is no text to translate")
        return self

    def segment_dicts(self) -> list[dict[str, Any]]:
        return [
            {"id": segment.id, "page": segment.page, "text": segment.text}
            for segment in self.segments or []
        ]

    def character_count(self) -> int:
        if self.segments:
            return sum(len(segment.text) for segment in self.segments)
        return len(self.text or "")

    def source_word_count(self) -> int:
        return word_count(self.text or "\n\n".join(segment.text for segment in self.segments or []))


class DetectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=100_000)


class TranslateJobRequest(TranslateRequest):
    """Same schema as the synchronous endpoint; kept as a distinct type."""
