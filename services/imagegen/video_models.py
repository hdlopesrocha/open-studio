"""Compatibility models mirroring the video-studio image service contract."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MVSModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Character(MVSModel):
    name: str = ""
    role: str = "protagonist"
    description: str = ""
    appearance: str = ""
    accent_color: str = "#F4A261"


class Location(MVSModel):
    name: str = ""
    description: str = ""
    motif: str = ""


class CameraMove(MVSModel):
    movement: str = "slow_forward"
    zoom: float = 1.08
    pan_x: float = 0.0
    pan_y: float = 0.0
    rotation: float = 0.0


class TransitionPlan(MVSModel):
    type: str = "crossfade"
    duration: float = 0.6


class VisualContext(MVSModel):
    style_id: str = "cinematic"
    style_name: str = "Cinematic"
    style_prompt: str = ""
    negative_prompt: str = ""
    palette: list[str] = Field(default_factory=list)
    lighting: str = ""
    art_direction: str = ""
    environment: str = ""
    characters: list[Character] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    motifs: list[str] = Field(default_factory=list)
    seed: int = 1987
    planner: str = "deterministic"


class Scene(MVSModel):
    scene_id: int = 1
    start: float = 0.0
    end: float = 1.0
    lyrics: str = ""
    description: str = ""
    visual_prompt: str = ""
    negative_prompt: str = ""
    camera: CameraMove = Field(default_factory=CameraMove)
    transition: TransitionPlan = Field(default_factory=TransitionPlan)
    visual_effects: list[str] = Field(default_factory=list)
    section_id: int | None = None
    section_kind: str = "unknown"
    section_label: str = ""
    subtitle_indices: list[int] = Field(default_factory=list)
    energy: float = 0.5
    seed: int = 1
    image_path: str | None = None
    image_source: str = "none"
    image_variants: list[str] = Field(default_factory=list)
    depth_map_path: str | None = None
    video_path: str | None = None
    thumbnail_path: str | None = None
    status: str = "planned"
    warnings: list[str] = Field(default_factory=list)


class ComfyUIConfig(MVSModel):
    url: str = ""
    workflow_path: str = ""
    workflow: dict[str, Any] | None = None
    steps: int = Field(default=28, ge=1, le=200)
    cfg: float = Field(default=6.0, ge=0.0, le=30.0)
    checkpoint: str = ""
    timeout_seconds: float = Field(default=600.0, ge=10.0, le=3600.0)
    reference_image_path: str | None = None


class GenerateImageRequest(MVSModel):
    project_id: str
    scene: Scene
    visual_context: VisualContext
    width: int = Field(default=1280, ge=256, le=4096)
    height: int = Field(default=720, ge=256, le=4096)
    provider: Literal["auto", "procedural", "comfyui", "diffusers", "qvac"] = "auto"
    variant: int = Field(default=0, ge=0, le=32)
    force: bool = False
    allow_fallback: bool = True
    comfyui: ComfyUIConfig = Field(default_factory=ComfyUIConfig)


class GeneratedImage(MVSModel):
    scene_id: int
    path: str
    thumbnail_path: str | None = None
    source: Literal["procedural", "comfyui", "diffusers", "qvac"]
    provider_requested: str
    cached: bool = False
    width: int
    height: int
    seed: int
    variant: int
    cache_key: str
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class ProviderStatusRequest(MVSModel):
    comfyui_url: str = ""
    workflow_path: str = ""


__all__ = [
    "Character",
    "ComfyUIConfig",
    "GenerateImageRequest",
    "GeneratedImage",
    "Location",
    "ProviderStatusRequest",
    "Scene",
    "VisualContext",
    "utcnow",
]
