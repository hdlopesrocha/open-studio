"""Pydantic request models for the voice service."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .text import split_batch_text

AudioFormat = Literal["wav", "mp3", "flac"]
TTSMode = Literal["auto", "voice", "design"]
EngineName = Literal["omnivoice", "piper", "auto"]
SplitMode = Literal["blank-line", "line"]


class GenerationParams(BaseModel):
    """Every generation control exposed by the UI and the API."""

    model_config = ConfigDict(extra="ignore")

    engine: EngineName = "omnivoice"
    mode: TTSMode = "auto"
    voice_id: str | None = Field(None, max_length=32)
    piper_voice: str | None = Field(None, max_length=80)
    instruct: str | None = Field(None, max_length=600)
    style_instruct: str | None = Field(None, max_length=600)
    language: str | None = Field(None, max_length=64)
    language_variant: str | None = Field(None, max_length=16)

    speed: float | None = Field(1.0, ge=0.25, le=4.0)
    num_step: int = Field(32, ge=1, le=128)
    guidance_scale: float = Field(2.0, ge=0.0, le=20.0)
    t_shift: float = Field(0.1, ge=0.0, le=10.0)
    denoise: bool = True
    preprocess_prompt: bool = True
    postprocess_output: bool = True
    seed: int | None = Field(None, ge=0, le=4_294_967_295)
    format: AudioFormat = "wav"
    normalize_text: bool = False
    pitch: float = Field(0.0, ge=-24.0, le=24.0)
    normalize_audio: bool = False

    # Original OmniVoice advanced controls kept for API/UI parity.
    duration: float | None = Field(None, ge=0.5, le=600.0)
    position_temperature: float = Field(5.0, ge=0.0, le=100.0)
    class_temperature: float = Field(0.0, ge=0.0, le=10.0)
    layer_penalty_factor: float = Field(5.0, ge=0.0, le=100.0)
    pad_duration: float = Field(0.1, ge=0.0, le=5.0)
    fade_duration: float = Field(0.1, ge=0.0, le=5.0)
    audio_chunk_duration: float = Field(15.0, gt=0.0, le=120.0)
    audio_chunk_threshold: float = Field(30.0, ge=0.0, le=600.0)

    @field_validator(
        "voice_id",
        "piper_voice",
        "instruct",
        "style_instruct",
        "language",
        "language_variant",
    )
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("speed")
    @classmethod
    def _speed_default(cls, value: float | None) -> float:
        return 1.0 if value is None else value


class TTSRequest(GenerationParams):
    text: str = Field(..., min_length=1, max_length=200_000)

    @field_validator("text")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Text cannot be empty")
        return value


class BatchTTSRequest(GenerationParams):
    items: list[str] | None = None
    texts: list[str] | None = None
    text: str | None = Field(None, max_length=200_000)
    split_mode: SplitMode = "blank-line"

    @model_validator(mode="after")
    def _resolve_items(self) -> "BatchTTSRequest":
        values: list[str] | None = self.items if self.items is not None else self.texts
        if values is None and self.text:
            values = split_batch_text(self.text, self.split_mode)
        if values is None:
            raise ValueError("Provide items, texts, or text with split_mode")
        cleaned: list[str] = []
        for value in values:
            value = (value or "").strip()
            if not value:
                continue
            if len(value) > 200_000:
                raise ValueError("Batch items must be 200,000 characters or less")
            cleaned.append(value)
        if not cleaned:
            raise ValueError("At least one batch item is required")
        if len(cleaned) > 50:
            raise ValueError("Batch supports at most 50 items")
        self.items = cleaned
        return self

    def to_tts_request(self, text: str) -> TTSRequest:
        payload = self.model_dump(exclude={"items", "texts", "text", "split_mode"})
        return TTSRequest(text=text, **payload)


class VoiceUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(None, max_length=60)
    language: str | None = Field(None, max_length=64)
    transcript: str | None = Field(None, max_length=8000)
    description: str | None = Field(None, max_length=1000)
    tags: list[str] | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Voice name cannot be empty")
        return value

    @field_validator("language", "transcript", "description")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    voice_id: str = Field(..., min_length=1, max_length=32)
    text: str | None = Field(None, max_length=300)


class PiperInstallRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    voice_id: str | None = Field(None, max_length=80)
    voice_ids: list[str] | None = None
    force: bool = False

    @model_validator(mode="after")
    def _has_selection(self) -> "PiperInstallRequest":
        if not self.voice_id and not self.voice_ids:
            raise ValueError("Provide voice_id or voice_ids")
        return self


class OpenAISpeechRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str = "omnivoice"
    input: str = Field(..., min_length=1, max_length=200_000)
    voice: str = Field("auto", max_length=300)
    # OpenAI defaults to mp3. The native /tts endpoint keeps wav as its default.
    response_format: AudioFormat = "mp3"
    speed: float | None = Field(1.0, ge=0.25, le=4.0)
    language: str | None = Field(None, max_length=64)
    language_variant: str | None = Field(None, max_length=16)
    instruct: str | None = Field(None, max_length=600)
    style_instruct: str | None = Field(None, max_length=600)
    normalize_text: bool = False
    seed: int | None = Field(None, ge=0, le=4_294_967_295)
    pitch: float = Field(0.0, ge=-24.0, le=24.0)
    normalize_audio: bool = False
    engine: EngineName | None = None

    @field_validator("input")
    @classmethod
    def _strip_input(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Input cannot be empty")
        return value

    @field_validator(
        "language",
        "language_variant",
        "instruct",
        "style_instruct",
        "voice",
    )
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


def public_generation_params(req: GenerationParams) -> dict[str, Any]:
    """Compact, JSON-safe parameter snapshot stored with an output."""
    return req.model_dump(exclude={"text"})
