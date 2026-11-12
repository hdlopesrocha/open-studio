"""Open Studio unified image generation service."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query

from openstudio_common import (
    INTERNAL_TOKEN,
    JOBHUB_URL,
    JobContext,
    JobRunner,
    create_service_app,
    env,
    env_bool,
    jobhub_headers,
    relative_path,
)

from . import diffusers_backend, qvac
from .comfyui import ComfyUIClient
from .models import GenerateRequest, UpscaleRequest
from .procedural import style_catalogue
from .providers import ProviderError, generate_images
from .storage import (
    artifact,
    descriptive_stem,
    ensure_dirs,
    extension_for,
    gallery_items,
    job_directory,
    normalize_format,
    resolve_input_image,
    save_pil,
    save_thumbnail_jpeg,
    utc_iso,
    write_job_manifest,
    write_sidecar,
)
from .video_compat import generate_video_image, provider_status
from .video_models import GeneratedImage, GenerateImageRequest, ProviderStatusRequest

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("imagegen")

VERSION = "1.0.0"
router = APIRouter(prefix="/api/images", tags=["images"])
internal_router = APIRouter(prefix="/internal/video", tags=["video-compat"])
runner = JobRunner("imagegen")


async def _internal_guard(x_internal_token: str = Header(default="")) -> None:
    """Accept MVS-style token-less calls from the video orchestrator.

    The endpoint is private (the public gateway never proxies /internal/video).
    Set MVS_REQUIRE_INTERNAL_TOKEN=true to enforce the shared token as well.
    """
    if x_internal_token and x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid internal token")
    if not x_internal_token and env_bool("MVS_REQUIRE_INTERNAL_TOKEN", False):
        raise HTTPException(status_code=403, detail="Internal token required")


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in items if item and item.strip()))


def _prompt_excerpt(prompt: str, limit: int = 60) -> str:
    collapsed = " ".join((prompt or "").split())
    return collapsed[: limit - 1] + "…" if len(collapsed) > limit else collapsed


async def submit_job(action: str, title: str, params: dict[str, Any]) -> dict[str, Any]:
    payload = {"component": "imagegen", "action": action, "title": title[:200], "params": params}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
            response = await client.post(f"{JOBHUB_URL}/api/jobs", json=payload, headers=jobhub_headers())
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Job hub is unavailable: {exc}") from exc
    if response.status_code >= 400:
        detail = response.text[:1000]
        try:
            detail = response.json().get("detail", detail)
        except Exception:  # noqa: BLE001
            pass
        raise HTTPException(status_code=502, detail=f"Could not create job: {detail}")
    return response.json()


PARAMETERS = {
    "common": {
        "provider": {
            "type": "string",
            "default": "auto",
            "values": ["auto", "procedural", "diffusers", "comfyui", "qvac"],
        },
        "model": {"type": "string", "default": ""},
        "prompt": {"type": "string", "default": ""},
        "negative_prompt": {"type": "string", "default": ""},
        "width": {"type": "integer", "default": 1024, "min": 64, "max": 4096},
        "height": {"type": "integer", "default": 1024, "min": 64, "max": 4096},
        "steps": {"type": "integer", "default": 28, "min": 1, "max": 200},
        "guidance": {"type": "number", "default": 7.0, "min": 0, "max": 30},
        "cfg_scale": {"type": "number", "default": None, "min": 0, "max": 30},
        "seed": {"type": "integer", "default": None, "description": "-1 or null picks a random seed"},
        "batch_count": {"type": "integer", "default": 1, "min": 1, "max": 8},
        "sampler": {"type": "string", "default": "euler"},
        "scheduler": {"type": "string", "default": None},
        "init_image": {"type": "string", "default": None},
        "strength": {"type": "number", "default": 0.6, "min": 0, "max": 1},
        "lora": {"type": "string|array", "default": None},
        "lora_scale": {"type": "number", "default": None},
        "upscale": {"type": "integer|string|boolean", "default": None},
        "output_format": {"type": "string", "default": "png", "values": ["png", "jpeg", "webp"]},
        "style": {"type": "string", "default": "cinematic", "values": [item["id"] for item in style_catalogue()]},
        "comfyui": {
            "type": "object",
            "fields": [
                "url",
                "workflow_path",
                "workflow",
                "steps",
                "cfg",
                "checkpoint",
                "timeout_seconds",
                "reference_image_path",
            ],
        },
    },
    "capabilities": {
        "text_to_image": True,
        "image_to_image": True,
        "inpainting": False,
        "lora": True,
        "upscale": True,
        "batch": True,
        "negative_prompt": True,
        "seeds": True,
        "deterministic_procedural": True,
    },
}


# ---------------------------------------------------------------------------
# Catalog and discovery
# ---------------------------------------------------------------------------


@router.get("/providers")
async def providers() -> dict[str, Any]:
    comfy_client = ComfyUIClient("")
    comfy_task = asyncio.to_thread(comfy_client.available)
    qvac_task = qvac.status()
    diffusers_task = asyncio.to_thread(diffusers_backend.model_catalogue)
    (comfy_available, comfy_detail), qvac_status, diffusers_catalogue = await asyncio.gather(
        comfy_task, qvac_task, diffusers_task
    )
    styles = style_catalogue()
    items = [
        {
            "id": "procedural",
            "name": "Procedural",
            "available": True,
            "detail": "Always available. Deterministic Pillow artwork, no model required.",
            "models": styles,
            "requires_model": False,
            "capabilities": ["text_to_image", "batch", "seed", "style", "typography"],
        },
        {
            "id": "diffusers",
            "name": "Diffusers",
            "available": diffusers_catalogue.get("available", False),
            "detail": (
                f"{len(diffusers_catalogue.get('local') or [])} local model(s); "
                f"device={diffusers_catalogue.get('runtime', {}).get('device', 'unavailable')}."
                if diffusers_catalogue.get("available")
                else "torch/diffusers are not installed in this image."
            ),
            "models": [*diffusers_catalogue.get("local", []), *diffusers_catalogue.get("remote", [])],
            "requires_model": True,
            "runtime": diffusers_catalogue.get("runtime", {}),
        },
        {
            "id": "comfyui",
            "name": "ComfyUI",
            "available": bool(comfy_available),
            "detail": comfy_detail,
            "url": comfy_client.base_url,
            "workflow_path": env("COMFYUI_WORKFLOW_PATH", ""),
            "requires_model": False,
            "capabilities": ["workflow", "reference_image", "loras", "checkpoints"],
        },
        {
            "id": "qvac",
            "name": "QVAC",
            "available": bool(qvac_status.get("available")),
            "detail": qvac_status.get("detail"),
            "url": qvac_status.get("url") or qvac.QVAC_URL,
            "requires_model": False,
        },
    ]
    return {
        "items": items,
        "total": len(items),
        "providers": {item["id"]: item for item in items},
        "defaults": {
            "provider": env("IMAGEGEN_DEFAULT_PROVIDER", "auto"),
            "width": 1024,
            "height": 1024,
            "steps": 28,
            "guidance": 7.0,
            "batch_count": 1,
            "output_format": "png",
            "style": "cinematic",
        },
        "styles": styles,
        "parameters": PARAMETERS,
    }


@router.get("/models")
async def models() -> dict[str, Any]:
    diffusers_catalogue = await asyncio.to_thread(diffusers_backend.model_catalogue)
    comfy_client = ComfyUIClient("")
    available, detail = await asyncio.to_thread(comfy_client.available)
    checkpoints = await asyncio.to_thread(comfy_client.checkpoints) if available else []
    items: list[dict[str, Any]] = []
    for style in style_catalogue():
        items.append(
            {
                "id": f"procedural:{style['id']}",
                "name": f"Procedural · {style['name']}",
                "provider": "procedural",
                "model": "procedural",
                "style": style["id"],
                "description": style["description"],
                "palette": style["palette"],
                "available": True,
                "downloaded": True,
                "requires_download": False,
                "defaults": {"width": 1024, "height": 1024, "seed": 1987},
            }
        )
    for entry in diffusers_catalogue.get("local", []):
        items.append(
            {
                "id": entry.get("id"),
                "name": entry.get("name") or entry.get("id"),
                "provider": "diffusers",
                "model": entry.get("id"),
                "path": entry.get("path"),
                "kind": entry.get("kind"),
                "class_name": entry.get("class_name"),
                "source": "local",
                "available": diffusers_catalogue.get("available", False),
                "downloaded": True,
                "requires_download": False,
                "defaults": {
                    "width": 1024,
                    "height": 1024,
                    "steps": 28,
                    "guidance": 7.0,
                    "sampler": "euler",
                },
            }
        )
    for entry in diffusers_catalogue.get("remote", []):
        items.append(
            {
                "id": entry.get("id"),
                "name": entry.get("name") or entry.get("id"),
                "provider": "diffusers",
                "model": entry.get("id"),
                "source": "huggingface",
                "description": entry.get("description"),
                "size": entry.get("size"),
                "available": diffusers_catalogue.get("available", False),
                "downloaded": False,
                "requires_download": True,
                "defaults": {
                    "width": 1024 if "xl" in str(entry.get("id", "")).lower() or "flux" in str(entry.get("id", "")).lower() else 512,
                    "height": 1024 if "xl" in str(entry.get("id", "")).lower() or "flux" in str(entry.get("id", "")).lower() else 512,
                    "steps": entry.get("recommended_steps", 28),
                    "guidance": entry.get("guidance", 7.0),
                    "sampler": "euler",
                },
            }
        )
    for checkpoint in checkpoints:
        items.append(
            {
                "id": f"comfyui:{checkpoint}",
                "name": checkpoint,
                "provider": "comfyui",
                "model": checkpoint,
                "checkpoint": checkpoint,
                "source": "comfyui",
                "available": available,
                "downloaded": True,
                "requires_download": False,
                "defaults": {"width": 1024, "height": 1024, "steps": 28, "guidance": 6.0},
            }
        )
    qvac_status = await qvac.status()
    if qvac_status.get("available"):
        items.append(
            {
                "id": "qvac:default",
                "name": "QVAC image model",
                "provider": "qvac",
                "model": "",
                "source": "qvac",
                "available": True,
                "downloaded": True,
                "requires_download": False,
                "detail": "CPU-friendly defaults: 512×512, 4 steps, batch 1. Increase only if you can wait.",
                "defaults": {"width": 512, "height": 512, "steps": 4, "guidance": 1.0, "cfg_scale": 1.0, "batch_count": 1},
            }
        )
    return {
        "items": items,
        "total": len(items),
        "providers": {
            "procedural": {"available": True},
            "diffusers": {
                "available": diffusers_catalogue.get("available", False),
                "local_count": len(diffusers_catalogue.get("local") or []),
                "models_dir": diffusers_catalogue.get("models_dir"),
                "runtime": diffusers_catalogue.get("runtime", {}),
            },
            "comfyui": {"available": available, "detail": detail, "checkpoints": checkpoints},
            "qvac": qvac_status,
        },
        "parameters": PARAMETERS,
        "styles": style_catalogue(),
    }


@router.get("/gallery")
async def gallery(
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
    provider: str = Query("", max_length=40),
    q: str = Query("", max_length=200, description="Search prompt, title or model"),
    query: str = Query("", max_length=200, description="Alias for q"),
) -> dict[str, Any]:
    return await asyncio.to_thread(
        gallery_items,
        limit=limit,
        offset=offset,
        provider=provider,
        query=q or query,
    )


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


def _result_image_payload(
    *,
    image: Any,
    meta: dict[str, Any],
    request: GenerateRequest,
    ctx: JobContext,
    directory: Path,
    index: int,
    provider: str,
    provider_requested: str,
    warnings: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    output_format = normalize_format(request.output_format)
    extension = extension_for(output_format)
    prompt = str(meta.get("prompt") or request.prompt or "")
    seed_value = meta.get("seed")
    seed = int(seed_value) if seed_value is not None else int(request.seed or 0)
    stem = descriptive_stem(prompt, provider, seed, index)
    image_path = directory / f"{stem}.{extension}"
    thumb_path = directory / f"{stem}.thumb.jpg"
    save_pil(image, image_path, output_format, quality=request.quality)
    save_thumbnail_jpeg(image, thumb_path, max_edge=480, quality=86)
    provider_metadata = {
        key: value
        for key, value in meta.items()
        if key
        not in {
            "image",
            "prompt",
            "negative_prompt",
            "width",
            "height",
            "seed",
            "variant",
        }
    }
    provider_metadata = json.loads(json.dumps(provider_metadata, default=str))
    sidecar_payload = {
        "kind": "imagegen.metadata",
        "version": 1,
        "type": "image",
        "job_id": ctx.job_id,
        "title": request.title,
        "path": relative_path(image_path),
        "thumbnail_path": relative_path(thumb_path),
        "provider": provider,
        "provider_requested": provider_requested,
        "model": meta.get("model") or request.model,
        "prompt": prompt,
        "negative_prompt": request.negative_prompt or str(meta.get("negative_prompt") or ""),
        "width": image.width,
        "height": image.height,
        "seed": seed,
        "variant": index,
        "batch_count": request.batch_count,
        "steps": meta.get("steps", request.steps),
        "guidance": meta.get("guidance", request.cfg_scale if request.cfg_scale is not None else request.guidance),
        "sampler": request.sampler,
        "scheduler": request.scheduler,
        "style": meta.get("style") or request.style,
        "init_image": request.init_image,
        "strength": request.strength if request.init_image else None,
        "lora": request.lora,
        "lora_scale": request.lora_scale,
        "upscale": request.upscale,
        "output_format": output_format,
        "width_requested": request.width,
        "height_requested": request.height,
        "warnings": _unique(warnings),
        "created_at": utc_iso(),
        "provider_metadata": provider_metadata,
        "request": request.model_dump(mode="json"),
    }
    sidecar_path = write_sidecar(image_path, sidecar_payload)
    artifacts = [
        artifact(image_path, role="image", provider=provider, format=output_format),
        artifact(thumb_path, role="thumbnail", provider=provider),
        artifact(sidecar_path, role="metadata", format="json"),
    ]
    item = {
        "index": index,
        "path": relative_path(image_path),
        "thumbnail_path": relative_path(thumb_path),
        "sidecar_path": relative_path(sidecar_path),
        "provider": provider,
        "model": sidecar_payload["model"],
        "width": image.width,
        "height": image.height,
        "seed": seed,
        "variant": index,
        "prompt": prompt,
        "created_at": sidecar_payload["created_at"],
        "url": f"/api/files/raw/{relative_path(image_path)}",
        "thumbnail_url": f"/api/files/raw/{relative_path(thumb_path)}",
    }
    return item, artifacts


@runner.action("generate")
async def job_generate(ctx: JobContext) -> dict[str, Any]:
    request = GenerateRequest.model_validate(ctx.params)
    await ctx.check()
    if request.init_image:
        try:
            resolve_input_image(request.init_image, label="init image")
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if request.init_images:
        for value in request.init_images:
            try:
                resolve_input_image(value, label="init image")
            except (ValueError, FileNotFoundError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
    prompt = request.prompt.strip()
    if not prompt and request.provider not in {"procedural", "auto"}:
        raise HTTPException(status_code=422, detail="prompt is required for this provider")
    if not prompt:
        prompt = "An atmospheric original artwork"
    await ctx.report(3.0, "Preparing", f"Preparing {request.provider} generation…")
    params = request.model_dump(mode="json", exclude_none=True)
    params["prompt"] = prompt
    warnings: list[str] = []

    async def on_poll(status: str, elapsed: float) -> None:
        progress = min(58.0, 12.0 + min(45.0, elapsed / 6.0))
        await ctx.report(progress, "Waiting for QVAC", f"QVAC status: {status} ({elapsed:.0f}s)…")

    await ctx.report(10.0, "Generating", "The image provider is working…")
    try:
        result = await generate_images(params, on_poll=on_poll)
    except Exception as exc:  # noqa: BLE001
        provider_failed = str(exc) or exc.__class__.__name__
        # Explicit QVAC requests must surface the real failure. Procedural art
        # is not a substitute when the user selected QVAC.
        if not request.allow_fallback or request.provider == "qvac":
            raise HTTPException(status_code=503, detail=f"Image generation failed: {provider_failed}") from exc
        warnings.append(f"{request.provider} generation failed ({provider_failed}); procedural fallback was used.")
        log.info("Falling back to procedural image generation: %s", provider_failed)
        fallback_params = {
            **params,
            "provider": "procedural",
            "model": "",
            "style": request.style,
        }
        await ctx.report(25.0, "Procedural fallback", "Generating local procedural artwork…")
        try:
            result = await generate_images(fallback_params)
        except Exception as fallback_exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Image generation failed: {fallback_exc}") from fallback_exc
        warnings.extend(result.get("warnings") or [])
    await ctx.check()
    provider_used = str(result.get("provider") or request.provider)
    warnings.extend(result.get("warnings") or [])
    warnings = _unique(warnings)
    directory = job_directory(ctx.job_id)
    await ctx.report(62.0, "Saving images", f"Saving {len(result['images'])} image(s)…")
    image_items: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    total = max(1, len(result["images"]))
    for index, entry in enumerate(result["images"]):
        await ctx.check()
        image_items_entry, image_artifacts = _result_image_payload(
            image=entry["image"],
            meta=entry.get("metadata") or {},
            request=request,
            ctx=ctx,
            directory=directory,
            index=index,
            provider=provider_used,
            provider_requested=request.provider,
            warnings=warnings,
        )
        image_items.append(image_items_entry)
        artifacts.extend(image_artifacts)
        for artifact_entry in image_artifacts:
            await ctx.client.artifact(artifact_entry)
        await ctx.report(
            62.0 + (30.0 * (index + 1) / total),
            "Saving images",
            f"Saved image {index + 1}/{total}",
        )
    manifest_payload = {
        "kind": "imagegen.job",
        "version": 1,
        "job_id": ctx.job_id,
        "provider": provider_used,
        "provider_requested": request.provider,
        "prompt": prompt,
        "negative_prompt": request.negative_prompt,
        "model": request.model,
        "width": request.width,
        "height": request.height,
        "batch_count": request.batch_count,
        "output_format": normalize_format(request.output_format),
        "warnings": warnings,
        "images": image_items,
        "created_at": utc_iso(),
        "request": request.model_dump(mode="json"),
    }
    manifest_path = write_job_manifest(directory, manifest_payload)
    manifest_artifact = artifact(manifest_path, role="manifest", format="json")
    artifacts.append(manifest_artifact)
    await ctx.client.artifact(manifest_artifact)
    await ctx.report(97.0, "Complete", "Image generation finished.")
    message = f"Generated {len(image_items)} {provider_used} image(s) with {request.model or provider_used}."
    if provider_used != request.provider and request.provider != "auto":
        message += f" (Requested {request.provider}; fallback used.)"
    return {
        "message": message,
        "files": artifacts,
        "data": {
            "provider": provider_used,
            "provider_requested": request.provider,
            "model": request.model,
            "prompt": prompt,
            "negative_prompt": request.negative_prompt,
            "title": request.title,
            "seed": request.seed,
            "batch_count": request.batch_count,
            "images": image_items,
            "warnings": warnings,
            "files": {
                "images": [item["path"] for item in image_items],
                "thumbnails": [item["thumbnail_path"] for item in image_items],
                "metadata": [item["sidecar_path"] for item in image_items],
                "manifest": relative_path(manifest_path),
            },
            "gallery_url": "/api/images/gallery",
            "created_at": utc_iso(),
            "job_id": ctx.job_id,
        },
    }


@runner.action("upscale")
async def job_upscale(ctx: JobContext) -> dict[str, Any]:
    request = UpscaleRequest.model_validate(ctx.params)
    await ctx.check()
    try:
        source = resolve_input_image(request.source_path)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await ctx.report(10.0, "Loading", f"Loading {source.name}…")
    try:
        from PIL import Image, ImageFilter

        with Image.open(source) as opened:
            opened.load()
            image = opened.convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Could not read the image: {exc}") from exc
    width, height = image.size
    if request.width and request.height:
        target_w, target_h = request.width, request.height
    elif request.width:
        target_w, target_h = request.width, max(1, round(height * request.width / width))
    elif request.height:
        target_w, target_h = max(1, round(width * request.height / height)), request.height
    else:
        target_w, target_h = max(1, round(width * request.scale)), max(1, round(height * request.scale))
    target_w, target_h = min(8192, target_w), min(8192, target_h)
    await ctx.report(30.0, "Upscaling", f"Resizing {width}x{height} → {target_w}x{target_h}…")
    from PIL import Image, ImageFilter

    upscaled = image.resize((target_w, target_h), Image.Resampling.LANCZOS)
    if request.sharpen:
        upscaled = upscaled.filter(ImageFilter.UnsharpMask(radius=1.4, percent=70, threshold=3))
    await ctx.check()
    directory = job_directory(ctx.job_id)
    output_format = normalize_format(request.output_format)
    extension = extension_for(output_format)
    stem = descriptive_stem(source.stem, "upscaled", int(ctx.job_id[:6], 16) if all(c in "0123456789abcdef" for c in ctx.job_id[:6]) else 0, 0)
    image_path = directory / f"{stem}.{extension}"
    thumb_path = directory / f"{stem}.thumb.jpg"
    save_pil(upscaled, image_path, output_format, quality=request.quality)
    save_thumbnail_jpeg(upscaled, thumb_path, max_edge=480, quality=86)
    source_metadata = {}
    source_sidecar = source.with_suffix(".json")
    try:
        if source_sidecar.is_file():
            source_metadata = json.loads(source_sidecar.read_text("utf-8"))
    except Exception:  # noqa: BLE001
        source_metadata = {}
    sidecar_payload = {
        "kind": "imagegen.metadata",
        "version": 1,
        "type": "upscale",
        "job_id": ctx.job_id,
        "title": request.title,
        "path": relative_path(image_path),
        "thumbnail_path": relative_path(thumb_path),
        "provider": "upscale",
        "provider_requested": "upscale",
        "model": "pillow-lanczos",
        "prompt": source_metadata.get("prompt") or "",
        "negative_prompt": source_metadata.get("negative_prompt") or "",
        "source_path": relative_path(source),
        "source_width": width,
        "source_height": height,
        "width": upscaled.width,
        "height": upscaled.height,
        "scale": request.scale,
        "sharpen": request.sharpen,
        "output_format": output_format,
        "created_at": utc_iso(),
        "warnings": [],
        "request": request.model_dump(mode="json"),
    }
    sidecar_path = write_sidecar(image_path, sidecar_payload)
    artifacts = [
        artifact(image_path, role="image", provider="upscale", format=output_format),
        artifact(thumb_path, role="thumbnail", provider="upscale"),
        artifact(sidecar_path, role="metadata", format="json"),
    ]
    for artifact_entry in artifacts:
        await ctx.client.artifact(artifact_entry)
    await ctx.report(96.0, "Complete", "Upscale finished.")
    item = {
        "path": relative_path(image_path),
        "thumbnail_path": relative_path(thumb_path),
        "sidecar_path": relative_path(sidecar_path),
        "source_path": relative_path(source),
        "width": upscaled.width,
        "height": upscaled.height,
        "source_width": width,
        "source_height": height,
        "format": output_format,
        "url": f"/api/files/raw/{relative_path(image_path)}",
    }
    return {
        "message": f"Upscaled {source.name} from {width}x{height} to {upscaled.width}x{upscaled.height}.",
        "files": artifacts,
        "data": {
            "image": item,
            "images": [item],
            "provider": "upscale",
            "warnings": [],
            "created_at": utc_iso(),
            "job_id": ctx.job_id,
        },
    }


# ---------------------------------------------------------------------------
# Public job submission
# ---------------------------------------------------------------------------


@router.post("/generate")
async def submit_generate(request: GenerateRequest) -> dict[str, Any]:
    if request.init_image:
        resolve_input_image(request.init_image, label="init image")
    if request.init_images:
        for value in request.init_images:
            resolve_input_image(value, label="init image")
    title = request.title or f"Generate image · {_prompt_excerpt(request.prompt) or request.provider}"
    return await submit_job("generate", title, request.model_dump(mode="json", exclude_none=True))


@router.post("/upscale")
async def submit_upscale(request: UpscaleRequest) -> dict[str, Any]:
    resolve_input_image(request.source_path)
    title = request.title or f"Upscale {Path(request.source_path).name}"
    return await submit_job("upscale", title, request.model_dump(mode="json", exclude_none=True))


# ---------------------------------------------------------------------------
# Video studio (MVS) compatibility
# ---------------------------------------------------------------------------


@internal_router.post("/provider-status", dependencies=[Depends(_internal_guard)])
async def video_provider_status(request: ProviderStatusRequest) -> dict[str, Any]:
    payload = await provider_status(request.comfyui_url, request.workflow_path)
    diffusers_info = await asyncio.to_thread(diffusers_backend.model_catalogue)
    payload["diffusers"] = {
        "available": diffusers_info.get("available", False),
        "local_models": [entry.get("id") for entry in diffusers_info.get("local", [])],
        "runtime": diffusers_info.get("runtime", {}),
    }
    payload["qvac"] = await qvac.status()
    return payload


@internal_router.post("/generate", response_model=GeneratedImage, dependencies=[Depends(_internal_guard)])
async def video_generate(request: GenerateImageRequest) -> GeneratedImage:
    return await generate_video_image(request)


async def _startup() -> None:
    ensure_dirs()
    log.info(
        "Image service ready (procedural=%s, diffusers=%s, comfyui=%s, qvac=%s)",
        True,
        diffusers_backend.deps_installed(),
        env("COMFYUI_URL", "http://comfyui:8188"),
        qvac.QVAC_URL,
    )


app = create_service_app(
    "imagegen",
    "Open Studio Images",
    "Unified procedural, diffusers, ComfyUI and QVAC image generation with video compatibility.",
    runner=runner,
    version=VERSION,
    extra_routers=[router, internal_router],
    on_startup=_startup,
)
