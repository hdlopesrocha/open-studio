"""Unified image provider dispatch (procedural, diffusers, ComfyUI, QVAC)."""

from __future__ import annotations

import asyncio
import io
import logging
import secrets
from typing import Any

from PIL import Image

from openstudio_common import env

from . import diffusers_backend, qvac
from .comfyui import ComfyUIClient, ComfyUIError, ComfyUIUnavailable
from .procedural import generate_procedural, resolve_style

log = logging.getLogger("imagegen.providers")

PROVIDERS = ("procedural", "diffusers", "comfyui", "qvac")


class ProviderError(RuntimeError):
    pass


def _seed(params: dict[str, Any], offset: int = 0) -> int:
    value = params.get("seed")
    if value is None or int(value) < 0:
        return secrets.randbelow(2**31 - 1) + offset
    return (int(value) + offset) % (2**31 - 1)


def resolve_auto(params: dict[str, Any]) -> str:
    configured = (env("IMAGEGEN_DEFAULT_PROVIDER", "") or "").strip().lower()
    if configured in PROVIDERS:
        return configured
    model = str(params.get("model") or "").lower()
    for provider in PROVIDERS:
        if model.startswith(provider + ":"):
            return provider
    comfy = params.get("comfyui") or {}
    workflow = comfy.get("workflow") if isinstance(comfy, dict) else None
    workflow_path = (comfy.get("workflow_path") if isinstance(comfy, dict) else "") or params.get(
        "workflow_path"
    ) or env("COMFYUI_WORKFLOW_PATH", "")
    if workflow or workflow_path:
        # Let the ComfyUI provider report its own availability and fall back
        # with an explicit warning if the server is down.
        return "comfyui"
    return "procedural"


def _apply_upscale(image: Image.Image, value: Any) -> Image.Image:
    if value is True:
        factor = 2.0
    elif value in (None, False, 0, "0", ""):
        factor = 1.0
    else:
        try:
            factor = float(str(value).lower().replace("x", ""))
        except ValueError:
            factor = 1.0
    factor = max(1.0, min(4.0, factor))
    if factor <= 1.0:
        return image
    target = (max(1, int(image.width * factor)), max(1, int(image.height * factor)))
    if max(target) > 8192:
        scale = 8192 / max(target)
        target = (max(1, int(target[0] * scale)), max(1, int(target[1] * scale)))
    return image.resize(target, Image.Resampling.LANCZOS)


def _procedural(params: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    prompt = str(params.get("prompt") or "An atmospheric original artwork").strip()
    width = int(params.get("width") or 1024)
    height = int(params.get("height") or 1024)
    batch = max(1, min(8, int(params.get("batch_count") or 1)))
    base_seed = _seed(params)
    style_value = params.get("style")
    model_value = str(params.get("model") or "")
    if not style_value and model_value.startswith("procedural:"):
        style_value = model_value.split(":", 1)[1]
    style = resolve_style(style_value)
    images = []
    for index in range(batch):
        image = generate_procedural(
            prompt,
            negative_prompt=str(params.get("negative_prompt") or ""),
            width=width,
            height=height,
            seed=base_seed,
            style=style,
            batch_index=index,
        )
        image = _apply_upscale(image, params.get("upscale"))
        images.append(
            {
                "image": image,
                "metadata": {
                    "provider": "procedural",
                    "model": f"procedural:{style}",
                    "style": style,
                    "prompt": prompt,
                    "negative_prompt": str(params.get("negative_prompt") or ""),
                    "width": image.width,
                    "height": image.height,
                    "seed": (base_seed + index * 7919) % (2**31 - 1),
                    "variant": index,
                    "upscale": params.get("upscale"),
                },
            }
        )
    warnings.append("Generated with the built-in procedural renderer (no AI model involved).")
    return {"images": images, "warnings": warnings}


def _diffusers(params: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    model = str(params.get("model") or "")
    if model.startswith("diffusers:"):
        params = {**params, "model": model.split(":", 1)[1]}
    result = diffusers_backend.generate(params)
    images = [
        {"image": image, "metadata": metadata}
        for image, metadata in zip(result.get("images") or [], result.get("metadata") or [])
    ]
    warnings.extend(result.get("warnings") or [])
    return {"images": images, "warnings": warnings}


def _comfy(params: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    config = params.get("comfyui") if isinstance(params.get("comfyui"), dict) else {}
    url = str(config.get("url") or params.get("comfyui_url") or env("COMFYUI_URL", "http://comfyui:8188"))
    workflow_path = config.get("workflow_path") or params.get("workflow_path") or env("COMFYUI_WORKFLOW_PATH", "")
    workflow = config.get("workflow") or params.get("workflow")
    if not workflow and not workflow_path:
        raise ProviderError(
            "No ComfyUI workflow is configured. Provide a workflow JSON/path or use procedural artwork."
        )
    steps = int(config.get("steps") or params.get("steps") or 28)
    cfg_raw = params.get("cfg_scale")
    cfg_value = config.get("cfg")
    if cfg_value is None:
        cfg_value = cfg_raw if cfg_raw is not None else params.get("guidance")
    cfg = float(6.0 if cfg_value is None else cfg_value)
    model_value = str(params.get("model") or "")
    if model_value.lower().startswith(("comfyui:", "procedural:", "diffusers:", "qvac:")):
        model_value = model_value.split(":", 1)[1]
    checkpoint = str(config.get("checkpoint") or params.get("checkpoint") or model_value)
    timeout = float(config.get("timeout_seconds") or params.get("timeout_seconds") or 600.0)
    reference = config.get("reference_image_path") or params.get("reference_image") or params.get("init_image")
    prompt = str(params.get("prompt") or "").strip()
    if not prompt:
        raise ProviderError("prompt is required for ComfyUI generation")
    negative = str(params.get("negative_prompt") or "")
    width = int(params.get("width") or 1024)
    height = int(params.get("height") or 1024)
    batch = max(1, min(8, int(params.get("batch_count") or 1)))
    base_seed = _seed(params)
    client = ComfyUIClient(url)
    available, detail = client.available()
    if not available:
        raise ComfyUIUnavailable(detail)
    images = []
    for index in range(batch):
        seed = (base_seed + index * 104729) % (2**31 - 1)
        binary, extension, metadata = client.generate(
            prompt=prompt,
            negative_prompt=negative,
            width=width,
            height=height,
            seed=seed,
            prefix=f"os_{base_seed}_{index}",
            steps=steps,
            cfg=cfg,
            checkpoint=checkpoint,
            workflow_path=str(workflow_path) if workflow_path else None,
            workflow=workflow if isinstance(workflow, dict) else None,
            reference_image=str(reference) if reference else None,
            timeout=timeout,
        )
        try:
            image = Image.open(io.BytesIO(binary))
            image.load()
            image = image.convert("RGB")
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"ComfyUI returned an unreadable image: {exc}") from exc
        image = _apply_upscale(image, params.get("upscale"))
        images.append(
            {
                "image": image,
                "metadata": {
                    "provider": "comfyui",
                    "model": checkpoint or "comfyui",
                    "prompt": prompt,
                    "negative_prompt": negative,
                    "width": image.width,
                    "height": image.height,
                    "steps": steps,
                    "cfg": cfg,
                    "seed": seed,
                    "variant": index,
                    "comfyui": metadata,
                    "extension": extension,
                },
            }
        )
    return {"images": images, "warnings": warnings}


async def _qvac(params: dict[str, Any], warnings: list[str], on_poll: Any = None) -> dict[str, Any]:
    model = str(params.get("model") or "")
    if model.startswith("qvac:"):
        params = {**params, "model": model.split(":", 1)[1] if model.split(":", 1)[1] != "default" else ""}
    result = await qvac.generate(params, on_poll=on_poll)
    images = []
    for index, entry in enumerate(result.get("images") or []):
        try:
            image = Image.open(io.BytesIO(entry["data"]))
            image.load()
            image = image.convert("RGB")
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"QVAC returned an unreadable image: {exc}") from exc
        metadata = {
            "provider": "qvac",
            "model": params.get("model") or "qvac",
            "prompt": str(params.get("prompt") or ""),
            "negative_prompt": str(params.get("negative_prompt") or ""),
            "width": image.width,
            "height": image.height,
            "seed": params.get("seed"),
            "variant": index,
            "qvac": entry.get("metadata") or {},
        }
        images.append({"image": image, "metadata": metadata})
    warnings.extend(result.get("warnings") or [])
    payload = result.get("metadata") or {}
    return {"images": images, "warnings": warnings, "provider_metadata": payload}


async def generate_images(params: dict[str, Any], *, on_poll: Any = None) -> dict[str, Any]:
    requested = str(params.get("provider") or "auto").strip().lower()
    if requested not in PROVIDERS and requested != "auto":
        raise ProviderError(f"Unknown image provider '{requested}'")
    provider = resolve_auto(params) if requested == "auto" else requested
    warnings: list[str] = []
    if provider == "procedural":
        result = await asyncio.to_thread(_procedural, params, warnings)
    elif provider == "diffusers":
        result = await asyncio.to_thread(_diffusers, params, warnings)
    elif provider == "comfyui":
        result = await asyncio.to_thread(_comfy, params, warnings)
    elif provider == "qvac":
        result = await _qvac(params, warnings, on_poll=on_poll)
    else:  # pragma: no cover - guarded above
        raise ProviderError(f"Unknown image provider '{provider}'")
    if not result.get("images"):
        raise ProviderError(f"The {provider} provider produced no images")
    result["provider"] = provider
    result["provider_requested"] = requested
    result["warnings"] = list(dict.fromkeys(result.get("warnings") or []))
    return result


def available_providers() -> dict[str, bool]:
    return {
        "procedural": True,
        "diffusers": diffusers_backend.deps_installed(),
        "comfyui": bool(env("COMFYUI_URL", "")),
        "qvac": bool(qvac.QVAC_URL),
    }


__all__ = [
    "PROVIDERS",
    "ProviderError",
    "available_providers",
    "generate_images",
    "resolve_auto",
]
