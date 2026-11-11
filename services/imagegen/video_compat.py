"""VideoStudio-compatible image generation on top of the unified providers.

The video orchestrator calls this service at ``/internal/video`` with the same
GenerateImageRequest/GeneratedImage payloads used by the standalone MVS image
service, so video projects get a zero-model procedural fallback automatically.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from PIL import Image

from openstudio_common import FILES_ROOT, env

from . import video_art
from .comfyui import ComfyUIClient, ComfyUIError, ComfyUIUnavailable
from .providers import ProviderError, generate_images
from .storage import (
    AssetCache,
    project_directory,
    project_relative,
    save_pil,
    save_thumbnail_jpeg,
    stable_hash,
    write_sidecar,
)
from .video_models import GeneratedImage, GenerateImageRequest

log = logging.getLogger("imagegen.video")


def _even(value: int) -> int:
    return max(256, int(value) - (int(value) % 2))


def _workflow_hash(path: str) -> str:
    if not path:
        return "none"
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        shared = FILES_ROOT / path
        if shared.is_file():
            candidate = shared
    try:
        return hashlib.sha256(candidate.read_bytes()).hexdigest()[:16]
    except OSError:
        return "missing"


def _reference_hash(value: str | None) -> str:
    if not value:
        return "none"
    try:
        return hashlib.sha256(Path(value).expanduser().read_bytes()).hexdigest()[:16]
    except OSError:
        return "missing"


def _unique(warnings: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in warnings if item))


def _prompt(scene: Any) -> str:
    return (
        scene.visual_prompt
        or scene.description
        or scene.lyrics
        or "Cinematic atmospheric artwork for a music video scene"
    )


def _negative(scene: Any, context: Any) -> str:
    return scene.negative_prompt or context.negative_prompt or ""


def _comfy_client(url: str = "") -> ComfyUIClient:
    return ComfyUIClient(url or env("COMFYUI_URL", "http://comfyui:8188"))


def _write_comfy_image(data: bytes, destination: Path) -> Image.Image:
    with Image.open(io.BytesIO(data)) as incoming:
        incoming.load()
        if incoming.width < 32 or incoming.height < 32:
            raise ComfyUIError("ComfyUI returned an image that is too small")
        image = incoming.convert("RGB")
    save_pil(image, destination, "png")
    return image


async def _diffusers_or_qvac(request: GenerateImageRequest, scene: Any, context: Any) -> tuple[Image.Image, str, list[str]]:
    provider = request.provider
    params = {
        "provider": provider,
        "model": env("MVS_DIFFUSERS_MODEL", "") if provider == "diffusers" else "",
        "prompt": _prompt(scene),
        "negative_prompt": _negative(scene, context),
        "width": request.width,
        "height": request.height,
        "steps": 28,
        "guidance": 7.0,
        "seed": scene.seed + request.variant * 104729,
        "batch_count": 1,
    }
    result = await generate_images(params)
    image = result["images"][0]["image"]
    return image, provider, list(result.get("warnings") or [])


async def generate_video_image(request: GenerateImageRequest) -> GeneratedImage:
    try:
        project_dir = project_directory(request.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"Project not found: {request.project_id}") from exc

    width = _even(request.width)
    height = _even(request.height)
    scene = request.scene
    context = request.visual_context
    warnings: list[str] = []
    comfy_config = request.comfyui
    url = comfy_config.url or env("COMFYUI_URL", "http://comfyui:8188")
    workflow_path = comfy_config.workflow_path.strip()
    workflow = comfy_config.workflow
    provider_used = "procedural"
    cacheable = True

    if request.provider in {"auto", "comfyui"}:
        if workflow or workflow_path:
            client = _comfy_client(url)
            available, detail = await asyncio.to_thread(client.available)
            if available:
                provider_used = "comfyui"
            else:
                message = f"ComfyUI unavailable ({detail}); procedural artwork was generated instead."
                if request.provider == "comfyui" and not request.allow_fallback:
                    raise HTTPException(status_code=503, detail=message)
                warnings.append(message)
        elif request.provider == "comfyui":
            message = (
                "No ComfyUI image workflow is configured; procedural artwork was generated instead."
            )
            if not request.allow_fallback:
                raise HTTPException(status_code=503, detail=message)
            warnings.append(message)
        else:
            warnings.append(
                "No ComfyUI image workflow is configured; procedural artwork was generated. "
                "This is not AI-generated imagery."
            )
    elif request.provider in {"procedural"}:
        provider_used = "procedural"
    else:
        provider_used = request.provider

    cache = AssetCache(project_dir)
    cache_payload = {
        "project_id": request.project_id,
        "scene_id": scene.scene_id,
        "variant": request.variant,
        "seed": scene.seed,
        "width": width,
        "height": height,
        "provider_requested": request.provider,
        "provider_used": provider_used,
        "prompt": _prompt(scene),
        "negative_prompt": _negative(scene, context),
        "style": context.style_id,
        "context_seed": context.seed,
        "workflow_hash": _workflow_hash(workflow_path) if provider_used == "comfyui" else "procedural-v3",
        "checkpoint": comfy_config.checkpoint if provider_used == "comfyui" else "",
        "reference_image_hash": _reference_hash(comfy_config.reference_image_path),
        "generator": "openstudio-imagegen-v1",
    }
    cache_key = cache.key(cache_payload)
    if not request.force:
        cached = cache.get(cache_key)
        if cached:
            entry_path = project_dir / cached.get("path", "")
            if entry_path.is_file():
                metadata = cached.get("metadata", {})
                return GeneratedImage(
                    scene_id=scene.scene_id,
                    path=cached.get("path", ""),
                    thumbnail_path=metadata.get("thumbnail_path"),
                    source=metadata.get("source", provider_used),
                    provider_requested=request.provider,
                    cached=True,
                    width=int(metadata.get("width", width)),
                    height=int(metadata.get("height", height)),
                    seed=int(metadata.get("seed", scene.seed)),
                    variant=request.variant,
                    cache_key=cache_key,
                    warnings=metadata.get("warnings", warnings),
                    created_at=metadata.get("created_at") or datetime.now(timezone.utc),
                )

    stem = f"scene_{scene.scene_id:03d}_v{request.variant}_{cache_key[:8]}"
    image_relative = f"assets/images/{stem}.png"
    thumb_relative = f"assets/thumbnails/{stem}.jpg"
    image_path = project_dir / image_relative
    thumb_path = project_dir / thumb_relative

    try:
        if provider_used == "comfyui":
            client = _comfy_client(url)
            try:
                binary, extension, provider_metadata = await asyncio.to_thread(
                    client.generate,
                    prompt=_prompt(scene),
                    negative_prompt=_negative(scene, context),
                    width=width,
                    height=height,
                    seed=scene.seed + request.variant * 104729,
                    prefix=stem,
                    steps=comfy_config.steps,
                    cfg=comfy_config.cfg,
                    checkpoint=comfy_config.checkpoint,
                    workflow_path=workflow_path or None,
                    workflow=workflow,
                    reference_image=comfy_config.reference_image_path,
                    timeout=comfy_config.timeout_seconds,
                )
                image = _write_comfy_image(binary, image_path)
                if image.width != width or image.height != height:
                    warnings.append(
                        f"ComfyUI returned {image.width}x{image.height}, "
                        f"which differs from the requested {width}x{height}."
                    )
                log.info("ComfyUI generated scene %s (%s)", scene.scene_id, provider_metadata)
            except (ComfyUIUnavailable, ComfyUIError, OSError) as exc:
                message = f"ComfyUI image generation failed: {exc}"
                if not request.allow_fallback:
                    raise HTTPException(status_code=503, detail=message) from exc
                warnings.append(message + " Procedural artwork was generated instead.")
                provider_used = "procedural"
                cacheable = False
                image = await asyncio.to_thread(
                    video_art.generate_procedural_art,
                    scene,
                    context,
                    width,
                    height,
                    variant=request.variant,
                )
                save_pil(image, image_path, "png")
        elif provider_used in {"diffusers", "qvac"}:
            try:
                image, used, extra_warnings = await _diffusers_or_qvac(request, scene, context)
                warnings.extend(extra_warnings)
                if image.width != width or image.height != height:
                    image = image.resize((width, height), Image.Resampling.LANCZOS)
                save_pil(image, image_path, "png")
                provider_used = used
            except Exception as exc:  # noqa: BLE001
                message = f"The {provider_used} image provider failed: {exc}"
                if not request.allow_fallback:
                    raise HTTPException(status_code=503, detail=message) from exc
                warnings.append(message + " Procedural artwork was generated instead.")
                provider_used = "procedural"
                cacheable = False
                image = await asyncio.to_thread(
                    video_art.generate_procedural_art,
                    scene,
                    context,
                    width,
                    height,
                    variant=request.variant,
                )
                save_pil(image, image_path, "png")
        else:
            image = await asyncio.to_thread(
                video_art.generate_procedural_art,
                scene,
                context,
                width,
                height,
                variant=request.variant,
            )
            save_pil(image, image_path, "png")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("MVS image generation failed for scene %s", scene.scene_id)
        raise HTTPException(status_code=500, detail=f"Image generation failed: {exc}") from exc

    # Thumbnail.
    thumbnail_path: str | None = None
    try:
        with Image.open(image_path) as source_image:
            save_thumbnail_jpeg(source_image, thumb_path, max_edge=480, quality=86)
        thumbnail_path = thumb_relative
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Thumbnail generation failed: {exc}")

    unique_warnings = _unique(warnings)
    created_at = datetime.now(timezone.utc)
    metadata = {
        "kind": "imagegen.metadata",
        "path": image_relative,
        "thumbnail_path": thumbnail_path,
        "source": provider_used,
        "provider": provider_used,
        "provider_requested": request.provider,
        "project_id": request.project_id,
        "scene_id": scene.scene_id,
        "width": width,
        "height": height,
        "seed": scene.seed,
        "variant": request.variant,
        "cache_key": cache_key,
        "warnings": unique_warnings,
        "created_at": created_at.isoformat(),
        "prompt": _prompt(scene),
        "negative_prompt": _negative(scene, context),
        "model": comfy_config.checkpoint if provider_used == "comfyui" else provider_used,
        "request": request.model_dump(mode="json"),
    }
    write_sidecar(image_path, metadata)
    entry_metadata = {
        "scene_id": scene.scene_id,
        "path": image_relative,
        "thumbnail_path": thumbnail_path,
        "source": provider_used,
        "provider_requested": request.provider,
        "width": width,
        "height": height,
        "seed": scene.seed,
        "variant": request.variant,
        "cache_key": cache_key,
        "warnings": unique_warnings,
        "created_at": created_at.isoformat(),
        "prompt": _prompt(scene),
        "negative_prompt": _negative(scene, context),
        "metadata_path": project_relative(project_dir, image_path.with_suffix(".json")),
    }
    if cacheable:
        cache.put(cache_key, image_relative, entry_metadata)
    return GeneratedImage(
        scene_id=scene.scene_id,
        path=image_relative,
        thumbnail_path=thumbnail_path,
        source=provider_used,
        provider_requested=request.provider,
        cached=False,
        width=width,
        height=height,
        seed=scene.seed,
        variant=request.variant,
        cache_key=cache_key,
        warnings=unique_warnings,
        created_at=created_at,
    )


async def provider_status(comfyui_url: str = "", workflow_path: str = "") -> dict[str, Any]:
    url = comfyui_url or env("COMFYUI_URL", "http://comfyui:8188")
    client = _comfy_client(url)
    available, detail = await asyncio.to_thread(client.available)
    checkpoints = await asyncio.to_thread(client.checkpoints) if available else []
    resolved_workflow = workflow_path
    workflow_exists = False
    if workflow_path:
        candidate = Path(workflow_path).expanduser()
        if not candidate.is_absolute():
            candidate = FILES_ROOT / workflow_path
        workflow_exists = candidate.is_file()
        if workflow_exists:
            resolved_workflow = str(candidate)
    return {
        "service": "images",
        "comfyui": {
            "url": url,
            "available": available,
            "detail": detail,
            "workflow_path": resolved_workflow,
            "workflow_configured": bool(workflow_path),
            "workflow_exists": workflow_exists,
            "checkpoints": checkpoints,
        },
    }


__all__ = ["generate_video_image", "provider_status"]
