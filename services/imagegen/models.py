"""Request schemas for the unified image generation service."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class APIModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class ComfyOptions(APIModel):
    url: str = ""
    workflow_path: str = ""
    workflow: dict[str, Any] | None = None
    steps: int | None = Field(default=None, ge=1, le=200)
    cfg: float | None = Field(default=None, ge=0.0, le=30.0)
    checkpoint: str = ""
    timeout_seconds: float | None = Field(default=None, ge=10.0, le=3600.0)
    reference_image_path: str | None = None


class GenerateRequest(APIModel):
    provider: Literal["auto", "procedural", "diffusers", "comfyui", "qvac"] = "auto"
    model: str = ""
    prompt: str = ""
    negative_prompt: str = ""
    width: int = Field(default=1024, ge=64, le=4096)
    height: int = Field(default=1024, ge=64, le=4096)
    steps: int = Field(default=28, ge=1, le=200)
    guidance: float = Field(default=7.0, ge=0.0, le=30.0)
    cfg_scale: float | None = Field(default=None, ge=0.0, le=30.0)
    seed: int | None = Field(default=None, ge=-1, le=2_147_483_647)
    batch_count: int = Field(default=1, ge=1, le=8)
    sampler: str = "euler"
    scheduler: str | None = None
    init_image: str | None = None
    init_images: list[str] | None = None
    strength: float = Field(default=0.6, ge=0.0, le=1.0)
    lora: str | list[str] | None = None
    lora_scale: float | None = Field(default=None, ge=0.0, le=4.0)
    output_format: Literal["png", "jpeg", "webp"] = "png"
    upscale: bool | int | float | str | None = None
    style: str | None = None
    title: str | None = Field(default=None, max_length=160)
    allow_fallback: bool = True
    quality: int = Field(default=92, ge=40, le=100)
    comfyui: ComfyOptions | None = None
    workflow_path: str | None = None
    workflow: dict[str, Any] | None = None
    comfyui_url: str | None = None
    checkpoint: str | None = None
    timeout_seconds: float | None = Field(default=None, ge=10.0, le=3600.0)
    reference_image: str | None = None


class UpscaleRequest(APIModel):
    path: str | None = None
    image_path: str | None = None
    scale: float = Field(default=2.0, ge=1.0, le=8.0)
    width: int | None = Field(default=None, ge=64, le=8192)
    height: int | None = Field(default=None, ge=64, le=8192)
    output_format: Literal["png", "jpeg", "webp"] = "png"
    quality: int = Field(default=94, ge=40, le=100)
    sharpen: bool = True
    title: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def _path_present(self) -> "UpscaleRequest":
        if not (self.path or self.image_path):
            raise ValueError("Provide path or image_path")
        return self

    @property
    def source_path(self) -> str:
        return (self.path or self.image_path or "").strip()
