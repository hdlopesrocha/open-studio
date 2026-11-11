"""Request schemas for the AI subtitles service."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OUTPUT_FORMATS = ("srt", "vtt", "ass")
_HEX = re.compile(r"^#?(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$")


class APIModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class WhisperOptions(APIModel):
    model: str = "small"
    language: str | None = None
    task: Literal["transcribe", "translate"] = "transcribe"
    beam_size: int = Field(default=5, ge=1, le=20)
    best_of: int = Field(default=5, ge=1, le=20)
    patience: float = Field(default=1.0, ge=0.1, le=5.0)
    temperature: float | list[float] | None = 0.0
    compression_ratio_threshold: float | None = Field(default=2.4, ge=0.1, le=100.0)
    log_prob_threshold: float | None = Field(default=-1.0, ge=-100.0, le=0.0)
    no_speech_threshold: float | None = Field(default=0.6, ge=0.0, le=1.0)
    condition_on_previous_text: bool = False
    initial_prompt: str | None = Field(default=None, max_length=4000)
    vad_filter: bool = False
    vad_parameters: dict[str, Any] | None = None
    word_timestamps: bool = False
    prepend_punctuations: str = "\"'“¿([{-"
    append_punctuations: str = "\"'.。,，!！?？:：”)]}、"
    device: Literal["auto", "cpu", "cuda"] = "auto"
    compute_type: str | None = None
    output_format: Literal["srt", "vtt", "ass"] = "srt"
    translate_to: str | None = None
    translation_model: str | None = None
    max_line_chars: int = Field(default=42, ge=0, le=200)
    max_lines: int = Field(default=2, ge=1, le=6)
    segment_gap: float = Field(default=0.06, ge=0.0, le=2.0)

    @field_validator("language", "translate_to")
    @classmethod
    def _language_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value or value.lower() == "auto":
            return None
        if not re.match(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})?$", value):
            raise ValueError(f"Invalid language code: {value!r}")
        return value

    @field_validator("temperature")
    @classmethod
    def _temperature(cls, value: float | list[float] | None) -> float | list[float]:
        if value is None:
            return 0.0
        if isinstance(value, list):
            if not value:
                return 0.0
            if len(value) > 12:
                raise ValueError("At most 12 fallback temperatures are allowed")
            if any(item < 0 or item > 2 for item in value):
                raise ValueError("Temperatures must be between 0 and 2")
            return value
        if value < 0 or value > 2:
            raise ValueError("Temperature must be between 0 and 2")
        return value

    @field_validator("initial_prompt")
    @classmethod
    def _prompt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class TranscribeRequest(WhisperOptions):
    audio_path: str = Field(min_length=1)
    title: str | None = Field(default=None, max_length=160)


class AlignRequest(WhisperOptions):
    audio_path: str = Field(min_length=1)
    lyrics: str | None = None
    lyrics_path: str | None = None
    use_lyrics_bias: bool = True
    instrumental_gap: float = Field(default=8.0, ge=2.0, le=120.0)
    title: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def _lyrics_present(self) -> "AlignRequest":
        if not (self.lyrics and self.lyrics.strip()) and not self.lyrics_path:
            raise ValueError("Provide lyrics or lyrics_path for alignment")
        return self


class FromTextRequest(APIModel):
    text: str | None = None
    text_path: str | None = None
    audio_path: str | None = None
    duration: float | None = Field(default=None, gt=0)
    start: float = Field(default=0.0, ge=0)
    end: float | None = Field(default=None, gt=0)
    output_format: Literal["srt", "vtt", "ass"] = "srt"
    translate_to: str | None = None
    translation_model: str | None = None
    max_line_chars: int = Field(default=42, ge=0, le=200)
    max_lines: int = Field(default=2, ge=1, le=6)
    segment_gap: float = Field(default=0.08, ge=0.0, le=2.0)
    words_per_minute: float = Field(default=160.0, ge=40.0, le=400.0)
    title: str | None = Field(default=None, max_length=160)

    @field_validator("translate_to")
    @classmethod
    def _language(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value or value.lower() == "auto":
            return None
        if not re.match(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})?$", value):
            raise ValueError(f"Invalid language code: {value!r}")
        return value

    @model_validator(mode="after")
    def _text_present(self) -> "FromTextRequest":
        if not (self.text and self.text.strip()) and not self.text_path:
            raise ValueError("Provide text or text_path")
        if self.end is not None and self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class ConvertRequest(APIModel):
    content: str | None = None
    path: str | None = None
    cues: list[dict[str, Any]] | None = None
    source_format: Literal["auto", "srt", "vtt", "ass"] = "auto"
    output_format: Literal["srt", "vtt", "ass"] | None = None
    to_format: Literal["srt", "vtt", "ass"] | None = Field(default=None, alias="format")
    title: str = Field(default="Open Studio Subtitles", max_length=200)
    style: dict[str, Any] | None = None
    font_name: str | None = None
    font_size: int | None = Field(default=None, ge=6, le=300)
    primary_color: str | None = None
    secondary_color: str | None = None
    outline_color: str | None = None
    back_color: str | None = None
    bold: bool | None = None
    italic: bool | None = None
    border_style: int | None = Field(default=None, ge=1, le=4)
    outline: float | None = Field(default=None, ge=0, le=20)
    shadow: float | None = Field(default=None, ge=0, le=20)
    alignment: int | None = Field(default=None, ge=1, le=9)
    margin_l: int | None = Field(default=None, ge=0, le=1000)
    margin_r: int | None = Field(default=None, ge=0, le=1000)
    margin_v: int | None = Field(default=None, ge=0, le=1000)
    play_res_x: int | None = Field(default=None, ge=320, le=7680)
    play_res_y: int | None = Field(default=None, ge=180, le=4320)
    save: bool = False
    output_path: str | None = None

    @field_validator("primary_color", "secondary_color", "outline_color", "back_color")
    @classmethod
    def _colour(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not _HEX.match(value):
            raise ValueError("Colors must be #RGB, #RRGGBB or #RRGGBBAA hex values")
        return value if value.startswith("#") else f"#{value}"

    @model_validator(mode="after")
    def _input_present(self) -> "ConvertRequest":
        if not self.content and not self.path and not self.cues:
            raise ValueError("Provide content, path or cues")
        return self

    @property
    def target_format(self) -> str:
        return self.output_format or self.to_format or "srt"


class EstimateRequest(APIModel):
    audio_path: str | None = None
    duration: float | None = Field(default=None, gt=0)
    model: str = "small"
    task: Literal["transcribe", "translate"] = "transcribe"
    language: str | None = None
    word_timestamps: bool = False
    device: Literal["auto", "cpu", "cuda"] = "auto"
    text: str | None = None
    title: str | None = None
