"""Pydantic request models for the music service.

The public contract is intentionally permissive about extra fields so a newer
Vue client cannot break an older service. Unknown fields are ignored and every
ACE-Step control the contract lists has an explicit field.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .catalog import DEFAULT_MODEL
from .db import section_type

GenerationMode = Literal["full", "repaint", "cover", "extend"]
InferMethod = Literal["ode", "sde"]
AudioFormat = Literal["wav", "wav16", "wav24", "wav32", "mp3", "flac"]
ExportFormat = Literal["wav", "mp3", "flac", "zip"]
VocalType = Literal["instrumental", "male", "female", "duet", "group", "choir"]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    artist: str = Field(default="", max_length=160)
    color: str = Field(default="lime", max_length=24)


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    artist: str | None = Field(default=None, max_length=160)
    color: str | None = Field(default=None, max_length=24)


class SongCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_id: str | None = None
    title: str = Field(default="Untitled song", min_length=1, max_length=200)
    artist: str = Field(default="", max_length=160)
    language: str = Field(default="pt-PT", max_length=40)
    language_label: str = Field(default="Portuguese (Portugal)", max_length=120)
    genre: str = Field(default="Pop", max_length=80)
    subgenre: str = Field(default="", max_length=100)
    style: str = Field(default="", max_length=500)
    mood: str = Field(default="Introspective", max_length=80)
    energy: int = Field(default=48, ge=0, le=100)
    bpm: int = Field(default=96, ge=30, le=300)
    duration: float = Field(default=150, ge=5, le=600)
    vocal_type: VocalType = "female"
    vocal_intensity: int = Field(default=55, ge=0, le=100)
    singing_style: str = Field(default="Melodic", max_length=100)
    vocal_emotion: str = Field(default="Intimate", max_length=100)
    vocal_range: str = Field(default="Alto", max_length=60)
    vocal_prompt: str = Field(default="", max_length=2000)
    pronunciation: str = Field(default="", max_length=2000)
    instructions: str = Field(default="", max_length=4000)
    provider: str = Field(default="ace_step", max_length=60)
    model_id: str = Field(default=DEFAULT_MODEL, max_length=120)


class SongUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    artist: str | None = Field(default=None, max_length=160)
    language: str | None = Field(default=None, max_length=40)
    language_label: str | None = Field(default=None, max_length=120)
    genre: str | None = Field(default=None, max_length=80)
    subgenre: str | None = Field(default=None, max_length=100)
    style: str | None = Field(default=None, max_length=500)
    mood: str | None = Field(default=None, max_length=80)
    energy: int | None = Field(default=None, ge=0, le=100)
    bpm: int | None = Field(default=None, ge=30, le=300)
    duration: float | None = Field(default=None, ge=5, le=600)
    vocal_type: VocalType | None = None
    vocal_intensity: int | None = Field(default=None, ge=0, le=100)
    singing_style: str | None = Field(default=None, max_length=100)
    vocal_emotion: str | None = Field(default=None, max_length=100)
    vocal_range: str | None = Field(default=None, max_length=60)
    vocal_prompt: str | None = Field(default=None, max_length=2000)
    pronunciation: str | None = Field(default=None, max_length=2000)
    instructions: str | None = Field(default=None, max_length=4000)
    provider: str | None = Field(default=None, max_length=60)
    model_id: str | None = Field(default=None, max_length=120)


class LyricsSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    type: str = "verse"
    label: str = Field(default="Verse 1", max_length=120)
    content: str = Field(default="", max_length=20000)
    instructions: str = Field(default="", max_length=2000)

    @field_validator("type", mode="before")
    @classmethod
    def normalise_type(cls, value: Any) -> str:
        return str(value or "").strip().lower()[:40]

    @field_validator("label", mode="before")
    @classmethod
    def normalise_label(cls, value: Any) -> str:
        text = str(value or "").strip()
        return text[:120] or "Section"

    @model_validator(mode="after")
    def type_from_label(self) -> "LyricsSection":
        self.type = section_type(self.type, self.label)
        return self


class LyricsUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sections: list[LyricsSection] = Field(default_factory=list, max_length=60)


class LyricsPlanItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str = "verse"
    label: str = Field(default="Section", max_length=120)
    line_count: int = Field(default=4, ge=1, le=16)

    @field_validator("type", mode="before")
    @classmethod
    def normalise_type(cls, value: Any) -> str:
        return str(value or "").strip().lower()[:40]

    @field_validator("label", mode="before")
    @classmethod
    def normalise_label(cls, value: Any) -> str:
        text = str(value or "").strip()
        return text[:120] or "Section"

    @model_validator(mode="after")
    def label_from_type(self) -> "LyricsPlanItem":
        self.type = section_type(self.type, self.label)
        if not self.label or self.label == "Section":
            self.label = {
                "intro": "Intro",
                "verse": "Verse",
                "pre-chorus": "Pre-Chorus",
                "chorus": "Chorus",
                "bridge": "Bridge",
                "outro": "Outro",
            }.get(self.type, "Section")
        return self


class LyricsDraftRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    song_id: str | None = None
    title: str = Field(default="", max_length=200)
    theme: str = Field(default="", max_length=4000)
    direction: str = Field(default="", max_length=3000)
    genre: str = Field(default="Pop", max_length=80)
    subgenre: str = Field(default="", max_length=100)
    style: str = Field(default="", max_length=500)
    mood: str = Field(default="", max_length=80)
    energy: int = Field(default=50, ge=0, le=100)
    language: str = Field(default="pt-PT", max_length=40)
    language_label: str = Field(default="", max_length=120)
    vocal_type: VocalType = "female"
    structure: list[LyricsPlanItem] = Field(default_factory=list, max_length=30)
    save: bool = False

    @field_validator("structure", mode="before")
    @classmethod
    def parse_structure(cls, value: Any) -> list[Any]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("structure must be a list")
        result: list[Any] = []
        for item in value:
            if isinstance(item, str):
                text = item.strip()
                if not text:
                    continue
                result.append({"label": text, "type": section_type("", text), "line_count": 4})
            elif isinstance(item, dict):
                result.append(item)
        return result[:30]

    @model_validator(mode="after")
    def has_brief(self) -> "LyricsDraftRequest":
        if not self.song_id and not any(text.strip() for text in (self.theme, self.title, self.direction)):
            raise ValueError("Provide a theme, a title or creative direction for the lyricist.")
        return self


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: str = Field(default="ace_step", max_length=60)
    model_id: str = Field(default=DEFAULT_MODEL, max_length=120)
    mode: GenerationMode = "full"
    variations: int = Field(default=2, ge=1, le=4)
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)
    inference_steps: int | None = Field(default=None, ge=1, le=200)
    guidance_scale: float | None = Field(default=None, ge=0, le=30)
    thinking: bool = False
    use_format: bool = False
    enhance_prompt: bool = False
    instruction: str = Field(default="", max_length=3000)
    caption: str | None = Field(default=None, max_length=8000)
    lyrics: str | None = Field(default=None, max_length=20000)
    vocal_language: str | None = Field(default=None, max_length=20)
    duration: float | None = Field(default=None, ge=5, le=600)
    bpm: int | None = Field(default=None, ge=30, le=300)
    source_path: str | None = None
    reference_path: str | None = None
    style_id: str | None = Field(default=None, max_length=64)
    track: str | None = Field(default=None, max_length=120)
    start_seconds: float | None = Field(default=None, ge=0, le=600)
    end_seconds: float | None = Field(default=None, gt=0, le=600)
    cover_strength: float = Field(default=0.75, ge=0, le=1)
    infer_method: InferMethod = "ode"
    audio_format: AudioFormat = "wav"
    lm_batch_size: int | None = Field(default=None, ge=1, le=4)
    synth_batch_size: int | None = Field(default=None, ge=1, le=9)

    @field_validator("audio_format", mode="before")
    @classmethod
    def normalise_audio_format(cls, value: Any) -> str:
        text = str(value or "wav").strip().lower()
        if text in {"", "wav16", "wave"}:
            return "wav"
        return text

    @model_validator(mode="after")
    def validate_mode(self) -> "GenerateRequest":
        if self.mode in {"repaint", "cover", "extend"} and not (self.source_path or "").strip():
            raise ValueError(f"{self.mode} requires source_path audio.")
        if self.mode == "repaint":
            if self.end_seconds is None:
                raise ValueError("repaint requires end_seconds.")
            start = self.start_seconds or 0.0
            if self.end_seconds <= start:
                raise ValueError("repaint end_seconds must be after start_seconds.")
        return self


class GenerationJobParams(GenerateRequest):
    song_id: str


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    song_id: str | None = None
    project_id: str | None = None
    take_id: str | None = None
    format: ExportFormat = "wav"
    audio_format: str | None = None
    kind: str | None = None
    mode: str | None = None
    package: bool | None = None
    zip: bool | None = None
    include_all_takes: bool = True

    @field_validator("format", mode="before")
    @classmethod
    def normalise_format(cls, value: Any) -> str:
        return str(value or "wav").strip().lower()

    @field_validator("audio_format", mode="before")
    @classmethod
    def normalise_audio_format(cls, value: Any) -> Any:
        return str(value).strip().lower() if value is not None else None

    def resolved(self) -> tuple[str, str]:
        raw_format = str(self.audio_format or self.format or "wav").strip().lower()
        kind = str(self.kind or self.mode or "").strip().lower()
        if raw_format in {"wav16", "wave"}:
            raw_format = "wav"
        if raw_format in {"zip", "session", "package", "archive"}:
            kind = "zip"
            raw_format = "wav"
        if self.package or self.zip:
            kind = "zip"
        if kind in {"session", "package", "archive"}:
            kind = "zip"
        if kind in {"project"}:
            kind = "project"
        if kind not in {"audio", "zip", "project"}:
            kind = "audio"
        if self.project_id and not self.song_id and kind == "audio":
            kind = "project"
        fmt = raw_format if raw_format in {"wav", "mp3", "flac"} else "wav"
        return fmt, kind


class TakeUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    is_favorite: bool | None = None
    notes: str | None = Field(default=None, max_length=4000)
