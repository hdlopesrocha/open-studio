"""Pydantic request models for the summary API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import settings


class SummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=settings.max_input_chars)
    length: Literal["short", "medium", "long"] = "medium"
    language: str | None = "auto"
    source_language: str = "auto"
    model: str = "auto"
    max_tokens: int | None = Field(default=None, ge=16, le=4096)
    min_tokens: int | None = Field(default=None, ge=0, le=4096)
    num_beams: int = Field(default=3, ge=1, le=16)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    chunk_tokens: int | None = Field(default=None, ge=64, le=2048)
    hierarchical: bool = True

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("There is no text to summarize")
        return value

    @model_validator(mode="after")
    def _budgets(self) -> "SummaryRequest":
        if (
            self.max_tokens is not None
            and self.min_tokens is not None
            and self.min_tokens >= self.max_tokens
        ):
            raise ValueError("min_tokens must be smaller than max_tokens")
        return self

    def character_count(self) -> int:
        return len(self.text)

    def options(self) -> dict:
        return {
            "length": self.length,
            "max_tokens": self.max_tokens,
            "min_tokens": self.min_tokens,
            "num_beams": self.num_beams,
            "temperature": self.temperature,
            "chunk_tokens": self.chunk_tokens,
            "hierarchical": self.hierarchical,
        }
