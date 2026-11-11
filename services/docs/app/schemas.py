"""Request models for the documents workflow."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import settings


def normalize_glossary(value: Any) -> dict[str, str]:
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
        raise ValueError("A glossary is limited to 500 terms")
    return terms


class InputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["pdf", "text"] = "text"
    pdf_path: str | None = Field(default=None, max_length=2048)
    text: str | None = Field(default=None, max_length=settings.max_text_chars)
    language: str = "auto"
    start_page: int | None = Field(default=None, ge=1)
    end_page: int | None = Field(default=None, ge=1)
    selected_pages: list[int] | None = Field(default=None, max_length=2000)
    pages: list[int] | None = Field(default=None, max_length=2000)
    ocr_enabled: bool = False
    ocr_language: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_input(self) -> "InputConfig":
        if self.pages is not None:
            if not self.pages:
                raise ValueError("pages cannot be empty")
            if any(page < 1 for page in self.pages):
                raise ValueError("Page numbers must be 1-based")
            if self.selected_pages is None:
                self.selected_pages = list(self.pages)
        if self.type == "pdf":
            if not self.pdf_path:
                raise ValueError("pdf_path is required for PDF input")
            if self.text and self.text.strip():
                raise ValueError("Pasted text cannot be combined with PDF input")
        else:
            if not self.text or not self.text.strip():
                raise ValueError("Text input requires non-empty text")
            if len(self.text) > settings.max_text_chars:
                raise ValueError(
                    f"Text exceeds the {settings.max_text_chars}-character limit"
                )
            if self.pdf_path or self.start_page or self.end_page or self.selected_pages:
                raise ValueError("PDF page options are only valid for PDF input")
        if self.selected_pages is not None:
            if not self.selected_pages:
                raise ValueError("selected_pages cannot be empty")
            if any(page < 1 for page in self.selected_pages):
                raise ValueError("Page numbers must be 1-based")
            if len(set(self.selected_pages)) > 2000:
                raise ValueError("At most 2000 pages can be selected")
        if (
            self.start_page is not None
            and self.end_page is not None
            and self.end_page < self.start_page
        ):
            raise ValueError("end_page must be greater than or equal to start_page")
        if (
            self.start_page is not None
            and self.end_page is not None
            and self.end_page - self.start_page > 2000
        ):
            raise ValueError("The page range is too large")
        return self

    def resolved_pages(self, page_count: int) -> list[int]:
        if self.selected_pages:
            pages = sorted(set(self.selected_pages))
        elif self.start_page is not None and self.end_page is not None:
            pages = list(range(self.start_page, self.end_page + 1))
        elif self.start_page is not None:
            pages = [self.start_page]
        elif self.end_page is not None:
            pages = list(range(1, self.end_page + 1))
        else:
            pages = list(range(1, page_count + 1))
        if any(page > page_count for page in pages):
            raise ValueError(f"Page numbers must be between 1 and {page_count}")
        return pages


class TranslationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
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

    def params(self) -> dict[str, Any]:
        return {
            "source_language": self.source_language,
            "target_language": self.target_language,
            "model": self.model,
            "num_beams": self.num_beams,
            "max_length": self.max_length,
            "temperature": self.temperature,
            "length_penalty": self.length_penalty,
            "repetition_penalty": self.repetition_penalty,
            "no_repeat_ngram_size": self.no_repeat_ngram_size,
            "batch_size": self.batch_size,
            "preserve_markup": self.preserve_markup,
            "glossary": self.glossary or {},
        }


class SummaryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    length: Literal["short", "medium", "long"] = "medium"
    language: str | None = None
    from_translation: bool = True
    source_language: str = "auto"
    model: str = "auto"
    max_tokens: int | None = Field(default=None, ge=16, le=4096)
    min_tokens: int | None = Field(default=None, ge=0, le=4096)
    num_beams: int = Field(default=3, ge=1, le=16)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    chunk_tokens: int | None = Field(default=None, ge=64, le=2048)
    hierarchical: bool = True

    @model_validator(mode="after")
    def validate_budget(self) -> "SummaryConfig":
        if (
            self.max_tokens is not None
            and self.min_tokens is not None
            and self.min_tokens >= self.max_tokens
        ):
            raise ValueError("min_tokens must be smaller than max_tokens")
        return self

    def params(self) -> dict[str, Any]:
        return {
            "length": self.length,
            "language": self.language,
            "source_language": self.source_language,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "min_tokens": self.min_tokens,
            "num_beams": self.num_beams,
            "temperature": self.temperature,
            "chunk_tokens": self.chunk_tokens,
            "hierarchical": self.hierarchical,
        }


class TTSConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    engine: str = "piper"
    mode: str | None = None
    voice_id: str | None = Field(default=None, max_length=200)
    piper_voice: str | None = Field(default=None, max_length=200)
    language: str | None = Field(default=None, max_length=40)
    language_variant: str | None = Field(default=None, max_length=40)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    format: Literal["mp3", "wav", "flac", "ogg", "opus", "m4a"] = "mp3"
    normalize_audio: bool = False
    normalize_text: bool = True
    text_source: Literal["content", "summary"] = "content"
    pitch: float = Field(default=0.0, ge=-24.0, le=24.0)
    instruct: str | None = Field(default=None, max_length=4000)
    finalize_with_ffmpeg: bool = True
    advanced: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_voice(self) -> "TTSConfig":
        if self.engine == "piper" and not (self.piper_voice or self.voice_id):
            # The voice service can pick a default, but an explicit choice is
            # safer for reproducible document narration. Leave validation to
            # runtime so the catalogue can supply defaults.
            pass
        return self

    def params(self, text: str, language: str | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "text": text,
            "engine": self.engine,
            "mode": self.mode,
            "voice_id": self.voice_id,
            "piper_voice": self.piper_voice,
            "language": language,
            "language_variant": self.language_variant,
            "speed": self.speed,
            "format": self.format,
            "normalize_audio": self.normalize_audio,
            "normalize_text": self.normalize_text,
            "pitch": self.pitch,
            "instruct": self.instruct,
        }
        for key, value in (self.advanced or {}).items():
            payload.setdefault(key, value)
        return {key: value for key, value in payload.items() if value is not None}


class SubtitlesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    format: Literal["srt", "vtt"] = "srt"


class ZipConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True


class PipelineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=200)
    input: InputConfig
    translation: TranslationConfig = Field(default_factory=TranslationConfig)
    summary: SummaryConfig = Field(default_factory=SummaryConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    subtitles: SubtitlesConfig = Field(default_factory=SubtitlesConfig)
    zip: ZipConfig = Field(default_factory=ZipConfig)

    @model_validator(mode="after")
    def validate_pipeline(self) -> "PipelineRequest":
        if self.tts.enabled and self.tts.text_source == "summary" and not self.summary.enabled:
            raise ValueError("TTS cannot narrate a summary when summarization is disabled")
        if self.summary.enabled and not self.translation.enabled:
            # from_translation is simply ignored and the extracted text is used.
            pass
        return self

    def public_config(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class TextUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=1_000_000)

    @field_validator("text")
    @classmethod
    def require_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("The edited text cannot be empty")
        return value
