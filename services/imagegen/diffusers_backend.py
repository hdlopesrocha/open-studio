"""Optional Hugging Face diffusers backend.

torch/diffusers are imported lazily so the image service can start, serve the
catalog and generate procedural artwork in a minimal image.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import logging
import os
import secrets
import threading
from importlib import metadata
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter

from openstudio_common import FILES_ROOT, MODELS_ROOT, env, env_bool, resolve_path

log = logging.getLogger("imagegen.diffusers")

MODELS_DIR = Path(env("IMAGEGEN_MODELS_DIR", str(MODELS_ROOT / "images")))
MAX_DIMENSION = int(env("IMAGEGEN_MAX_DIMENSION", "4096"))
_PIPELINES: dict[tuple[str, bool], Any] = {}
_PIPELINE_LOCKS: dict[tuple[str, bool], threading.RLock] = {}
_LORA_STATE: dict[int, str] = {}
_CACHE_LOCK = threading.RLock()
_RUNTIME: dict[str, Any] | None = None

REMOTE_MODELS = [
    {
        "id": "stabilityai/sd-turbo",
        "name": "SD Turbo",
        "description": "1–4 step 512px model for fast previews.",
        "kind": "diffusers",
        "size": "small",
        "recommended_steps": 4,
        "guidance": 0.0,
    },
    {
        "id": "runwayml/stable-diffusion-v1-5",
        "name": "Stable Diffusion 1.5",
        "description": "Classic 512px base model with a very large LoRA ecosystem.",
        "kind": "diffusers",
        "size": "medium",
        "recommended_steps": 28,
        "guidance": 7.0,
    },
    {
        "id": "stabilityai/stable-diffusion-xl-base-1.0",
        "name": "SDXL Base 1.0",
        "description": "1024px photorealistic/illustration model.",
        "kind": "diffusers",
        "size": "large",
        "recommended_steps": 30,
        "guidance": 6.5,
    },
    {
        "id": "stabilityai/sdxl-turbo",
        "name": "SDXL Turbo",
        "description": "Very fast 1024px previews in 1–4 steps.",
        "kind": "diffusers",
        "size": "large",
        "recommended_steps": 4,
        "guidance": 0.0,
    },
    {
        "id": "black-forest-labs/FLUX.1-schnell",
        "name": "FLUX.1 Schnell",
        "description": "High quality 4-step FLUX model (large download, needs bfloat16).",
        "kind": "diffusers",
        "size": "very large",
        "recommended_steps": 4,
        "guidance": 0.0,
    },
]


def deps_installed() -> bool:
    return importlib.util.find_spec("torch") is not None and importlib.util.find_spec("diffusers") is not None


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def runtime_info(force: bool = False) -> dict[str, Any]:
    """Import torch once to report device capabilities."""
    global _RUNTIME
    if _RUNTIME is not None and not force:
        return _RUNTIME
    info: dict[str, Any] = {
        "torch_version": _package_version("torch"),
        "diffusers_version": _package_version("diffusers"),
        "transformers_version": _package_version("transformers"),
        "cuda_available": False,
        "mps_available": False,
        "device": "unavailable",
        "device_name": None,
        "vram_total_mb": None,
    }
    if not deps_installed():
        _RUNTIME = info
        return info
    try:
        import torch

        info["cuda_available"] = bool(torch.cuda.is_available())
        try:
            info["mps_available"] = bool(torch.backends.mps.is_available())
        except Exception:  # noqa: BLE001
            info["mps_available"] = False
        if info["cuda_available"]:
            info["device"] = "cuda"
            try:
                info["device_name"] = torch.cuda.get_device_name(0)
                props = torch.cuda.get_device_properties(0)
                info["vram_total_mb"] = int(props.total_memory / (1024 * 1024))
            except Exception:  # noqa: BLE001
                pass
        elif info["mps_available"]:
            info["device"] = "mps"
            info["device_name"] = "Apple Metal"
        else:
            info["device"] = "cpu"
            info["device_name"] = os.uname().machine if hasattr(os, "uname") else "CPU"
    except Exception as exc:  # noqa: BLE001
        info["error"] = str(exc)
    _RUNTIME = info
    return info


def local_models() -> list[dict[str, Any]]:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for entry in sorted(MODELS_DIR.iterdir(), key=lambda item: item.name.lower()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir() and (entry / "model_index.json").is_file():
            class_name = None
            try:
                class_name = json.loads((entry / "model_index.json").read_text("utf-8")).get("_class_name")
            except Exception:  # noqa: BLE001
                pass
            items.append(
                {
                    "id": entry.name,
                    "name": entry.name.replace("_", " ").replace("-", " ").title(),
                    "kind": "diffusers",
                    "path": str(entry),
                    "class_name": class_name,
                    "source": "local",
                }
            )
        elif entry.is_file() and entry.suffix.lower() in {".safetensors", ".ckpt"}:
            items.append(
                {
                    "id": entry.name,
                    "name": entry.stem,
                    "kind": "checkpoint",
                    "path": str(entry),
                    "class_name": None,
                    "source": "local",
                }
            )
    return items


def model_catalogue() -> dict[str, Any]:
    local = local_models()
    remote = []
    for item in REMOTE_MODELS:
        remote.append({**item, "source": "huggingface", "downloaded": False})
    return {
        "available": deps_installed(),
        "models_dir": str(MODELS_DIR),
        "local": local,
        "remote": remote,
        "runtime": runtime_info(),
        "defaults": {
            "model": local[0]["id"] if local else (REMOTE_MODELS[0]["id"] if deps_installed() else ""),
            "width": 1024,
            "height": 1024,
            "steps": 28,
            "guidance": 7.0,
            "sampler": "euler",
            "scheduler": None,
            "batch_count": 1,
            "strength": 0.6,
            "output_format": "png",
        },
    }


class DiffusersUnavailable(RuntimeError):
    pass


def resolve_model(value: str | None) -> str:
    value = (value or "").strip()
    if not value:
        local = local_models()
        if not local:
            raise DiffusersUnavailable(
                "No diffusers model is installed. Put a model under /data/models/images "
                "or pass a Hugging Face model id."
            )
        return str(local[0]["path"])
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        if not candidate.exists():
            raise DiffusersUnavailable(f"Model path does not exist: {value}")
        return str(candidate)
    # A local model name (relative to the images model root) is preferred over
    # a Hugging Face repo id.
    local_candidate = MODELS_DIR / value
    if local_candidate.exists():
        return str(local_candidate)
    if value.count("/") == 1 and not value.startswith((".", "/")):
        return value
    raise DiffusersUnavailable(f"Unknown model '{value}'. Use a files-relative path, local model name or HF id.")


SCHEDULERS = {
    "euler": "EulerDiscreteScheduler",
    "euler_a": "EulerAncestralDiscreteScheduler",
    "euler_ancestral": "EulerAncestralDiscreteScheduler",
    "euler_karras": "EulerDiscreteScheduler",
    "heun": "HeunDiscreteScheduler",
    "heun_karras": "HeunDiscreteScheduler",
    "lms": "LMSDiscreteScheduler",
    "lms_karras": "LMSDiscreteScheduler",
    "ddim": "DDIMScheduler",
    "pndm": "PNDMScheduler",
    "unipc": "UniPCMultistepScheduler",
    "dpmpp_2m": "DPMSolverMultistepScheduler",
    "dpmpp_2m_karras": "DPMSolverMultistepScheduler",
    "dpmpp_2": "DPMSolverMultistepScheduler",
    "dpmpp_sde": "DPMSolverSDEScheduler",
    "dpmpp_singlestep": "DPMSolverSinglestepScheduler",
    "lcm": "LCMScheduler",
    "deis": "DEISMultistepScheduler",
    "kdpm2": "KDPM2DiscreteScheduler",
    "kdpm2_a": "KDPM2AncestralDiscreteScheduler",
}


def _set_scheduler(pipe: Any, sampler: str | None, scheduler: str | None, warnings: list[str]) -> None:
    value = (scheduler or sampler or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not value or value in {"default", "auto", "native"}:
        return
    karras = "karras" in value
    try:
        from diffusers import schedulers

        if value.startswith("dpmpp_2m") and "sde" in value:
            class_name = "DPMSolverSDEScheduler"
        else:
            class_name = SCHEDULERS.get(value)
        if class_name is None:
            # Accept an explicit diffusers class name.
            class_name = next((name for name in dir(schedulers) if name.lower() == value.replace("_", "")), None)
        scheduler_class = getattr(schedulers, class_name, None) if class_name else None
        if scheduler_class is None:
            warnings.append(f"Unknown scheduler/sampler '{value}'; keeping the model default.")
            return
        config = dict(getattr(pipe.scheduler, "config", {}) or {})
        new_scheduler = scheduler_class.from_config(config)
        if karras and hasattr(new_scheduler, "use_karras_sigmas"):
            new_scheduler.use_karras_sigmas = True
        pipe.scheduler = new_scheduler
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Could not apply scheduler '{value}': {exc}")


def _dtype(torch: Any, device: str, model: str) -> Any:
    if device != "cuda":
        return torch.float32
    if "flux" in model.lower():
        return torch.bfloat16
    return torch.float16


def _pipeline_kwargs(torch: Any, dtype: Any) -> dict[str, Any]:
    return {
        "torch_dtype": dtype,
        "safety_checker": None,
        "requires_safety_checker": False,
    }


def _load_pipeline(model: str, device: str, img2img: bool, warnings: list[str]) -> Any:
    try:
        import torch
        from diffusers import (
            AutoPipelineForImage2Image,
            AutoPipelineForText2Image,
            StableDiffusionImg2ImgPipeline,
            StableDiffusionPipeline,
            StableDiffusionXLImg2ImgPipeline,
            StableDiffusionXLPipeline,
        )
    except Exception as exc:  # noqa: BLE001
        raise DiffusersUnavailable(
            "diffusers/torch are not installed. Rebuild imagegen with INSTALL_DIFFUSERS=1."
        ) from exc
    dtype = _dtype(torch, device, model)
    kwargs = _pipeline_kwargs(torch, dtype)
    path = Path(model)
    lower = model.lower()
    try:
        if path.is_file():
            if "xl" in lower:
                cls = StableDiffusionXLImg2ImgPipeline if img2img else StableDiffusionXLPipeline
            else:
                cls = StableDiffusionImg2ImgPipeline if img2img else StableDiffusionPipeline
            pipe = cls.from_single_file(str(path), **kwargs)
        elif img2img:
            pipe = AutoPipelineForImage2Image.from_pretrained(model, **kwargs)
        else:
            pipe = AutoPipelineForText2Image.from_pretrained(model, **kwargs)
    except Exception as exc:  # noqa: BLE001
        raise DiffusersUnavailable(f"Could not load diffusers model '{model}': {exc}") from exc
    if hasattr(pipe, "enable_vae_slicing"):
        try:
            pipe.enable_vae_slicing()
        except Exception:  # noqa: BLE001
            pass
    if env_bool("DIFFUSERS_ATTENTION_SLICING", False) and hasattr(pipe, "enable_attention_slicing"):
        try:
            pipe.enable_attention_slicing()
        except Exception:  # noqa: BLE001
            pass
    try:
        if device == "cuda":
            try:
                pipe.to("cuda")
            except Exception as exc:  # noqa: BLE001
                if env_bool("DIFFUSERS_CPU_OFFLOAD", True) and hasattr(pipe, "enable_model_cpu_offload"):
                    warnings.append(f"CUDA placement failed ({exc}); enabling model CPU offload.")
                    pipe.enable_model_cpu_offload()
                else:
                    raise
        elif device == "mps":
            pipe.to("mps")
        else:
            pipe.to("cpu")
            warnings.append("Diffusers is running on CPU; generation can be slow.")
    except Exception as exc:  # noqa: BLE001
        raise DiffusersUnavailable(f"Could not move the diffusers pipeline to {device}: {exc}") from exc
    return pipe


def _get_pipeline(model: str, device: str, img2img: bool, warnings: list[str]) -> Any:
    key = (model, img2img)
    with _CACHE_LOCK:
        lock = _PIPELINE_LOCKS.setdefault(key, threading.RLock())
    with lock:
        pipe = _PIPELINES.get(key)
        if pipe is not None:
            return pipe
        log.info("Loading diffusers pipeline %s (img2img=%s, device=%s)", model, img2img, device)
        pipe = _load_pipeline(model, device, img2img, warnings)
        _PIPELINES[key] = pipe
        return pipe


def _lora_values(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(part).strip() for part in value if str(part).strip()]
    return [str(value).strip()]


def _resolve_asset(value: str) -> str:
    candidate = Path(value).expanduser()
    roots = (FILES_ROOT.resolve(), MODELS_DIR.resolve())
    if candidate.is_absolute():
        resolved = candidate.resolve()
        if any(resolved == root or root in resolved.parents for root in roots):
            return str(resolved)
        return value
    for root in roots:
        resolved = (root / value).resolve()
        if (resolved == root or root in resolved.parents) and resolved.exists():
            return str(resolved)
    return value


def _apply_lora(pipe: Any, lora: Any, scale: float | None, warnings: list[str]) -> None:
    values = _lora_values(lora)
    state_key = id(pipe)
    signature = "|".join(values)
    if not values:
        if _LORA_STATE.get(state_key):
            try:
                pipe.unload_lora_weights()
            except Exception:  # noqa: BLE001
                pass
            _LORA_STATE.pop(state_key, None)
        return
    if _LORA_STATE.get(state_key) == signature:
        return
    try:
        try:
            pipe.unload_lora_weights()
        except Exception:  # noqa: BLE001
            pass
        adapters: list[str] = []
        for index, value in enumerate(values):
            adapter_name = f"lora_{index}"
            resolved = _resolve_asset(value)
            pipe.load_lora_weights(resolved, adapter_name=adapter_name)
            adapters.append(adapter_name)
        if adapters and hasattr(pipe, "set_adapters"):
            if scale is not None:
                pipe.set_adapters(adapters, adapter_weights=[float(scale)] * len(adapters))
            else:
                pipe.set_adapters(adapters)
        _LORA_STATE[state_key] = signature
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"LoRA could not be loaded ({exc}); continuing without it.")
        _LORA_STATE.pop(state_key, None)


def _accepted_kwargs(pipe: Any) -> set[str] | None:
    try:
        signature = inspect.signature(pipe.__call__)
    except (TypeError, ValueError):
        return None
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()):
        return None
    return set(signature.parameters)


def _parse_upscale(value: Any) -> float:
    if value in (None, False, 0, "0", "none", ""):
        return 1.0
    if value is True:
        return 2.0
    text = str(value).strip().lower().replace("x", "")
    try:
        factor = float(text)
    except ValueError:
        return 1.0
    return max(1.0, min(4.0, factor))


def _upscale_image(image: Image.Image, factor: float) -> Image.Image:
    if factor <= 1.0:
        return image
    target = (max(1, int(image.width * factor)), max(1, int(image.height * factor)))
    if max(target) > MAX_DIMENSION:
        scale = MAX_DIMENSION / max(target)
        target = (max(1, int(target[0] * scale)), max(1, int(target[1] * scale)))
    result = image.resize(target, Image.Resampling.LANCZOS)
    return result.filter(ImageFilter.UnsharpMask(radius=1.2, percent=55, threshold=3))


def generate(params: dict[str, Any]) -> dict[str, Any]:
    """Run a diffusers generation and return PIL images plus metadata."""
    if not deps_installed():
        raise DiffusersUnavailable(
            "diffusers/torch are not installed in this image. Rebuild with INSTALL_DIFFUSERS=1 "
            "or use provider=procedural."
        )
    import torch

    warnings: list[str] = []
    prompt = str(params.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required for diffusers generation")
    negative_prompt = str(params.get("negative_prompt") or "").strip()
    width = int(params.get("width") or 1024)
    height = int(params.get("height") or 1024)
    adjusted_w = max(64, min(MAX_DIMENSION, (width // 8) * 8))
    adjusted_h = max(64, min(MAX_DIMENSION, (height // 8) * 8))
    if (adjusted_w, adjusted_h) != (width, height):
        warnings.append(f"Dimensions adjusted to multiples of 8: {adjusted_w}x{adjusted_h}.")
    width, height = adjusted_w, adjusted_h
    steps = max(1, min(200, int(params.get("steps") or 28)))
    guidance_raw = params.get("cfg_scale")
    guidance = float(guidance_raw) if guidance_raw is not None else float(params.get("guidance") or 7.0)
    batch_count = max(1, min(8, int(params.get("batch_count") or 1)))
    seed = params.get("seed")
    if seed is None or int(seed) < 0:
        seed = secrets.randbelow(2**31 - 1)
    seed = int(seed) % (2**31 - 1)
    strength = max(0.0, min(1.0, float(params.get("strength") or 0.6)))
    model = resolve_model(params.get("model"))
    init_value = params.get("init_image")
    init_image = None
    if init_value:
        try:
            if Path(str(init_value)).is_absolute():
                init_path = Path(str(init_value)).resolve()
                roots = (FILES_ROOT.resolve(), MODELS_DIR.resolve())
                if not any(init_path == root or root in init_path.parents for root in roots):
                    raise ValueError("init_image must live under the shared files or models root")
            else:
                init_path = resolve_path(str(init_value))
            init_image = Image.open(init_path).convert("RGB")
            init_image.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
            # img2img dimensions come from the init image unless explicitly set.
            if params.get("width") is None and params.get("height") is None:
                width, height = init_image.width - (init_image.width % 8), init_image.height - (init_image.height % 8)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Could not open init_image: {exc}") from exc
    info = runtime_info()
    device = str(info.get("device") or "cpu")
    if device not in {"cuda", "mps", "cpu"}:
        device = "cpu"
    pipe = _get_pipeline(model, device, init_image is not None, warnings)
    _set_scheduler(pipe, params.get("sampler"), params.get("scheduler"), warnings)
    _apply_lora(pipe, params.get("lora"), params.get("lora_scale"), warnings)
    if device == "cuda":
        torch.cuda.empty_cache()
    generator = torch.Generator(device="cpu").manual_seed(seed)
    call_kwargs: dict[str, Any] = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "num_inference_steps": steps,
        "guidance_scale": guidance,
        "generator": generator,
        "num_images_per_prompt": batch_count,
    }
    if init_image is None:
        call_kwargs["width"] = width
        call_kwargs["height"] = height
    else:
        call_kwargs["image"] = init_image
        call_kwargs["strength"] = strength
    accepted = _accepted_kwargs(pipe)
    if accepted is not None:
        if "negative_prompt" not in accepted:
            call_kwargs.pop("negative_prompt", None)
        if "guidance_scale" not in accepted:
            call_kwargs.pop("guidance_scale", None)
        if "num_images_per_prompt" not in accepted:
            call_kwargs.pop("num_images_per_prompt", None)
    log.info(
        "Diffusers generating %s images with %s on %s (steps=%s, guidance=%s, seed=%s)",
        batch_count,
        model,
        device,
        steps,
        guidance,
        seed,
    )
    try:
        result = pipe(**call_kwargs)
    except TypeError as exc:
        # Older pipelines may not accept one of the optional arguments.
        warnings.append(f"Pipeline argument fallback: {exc}")
        for key in ("num_images_per_prompt", "negative_prompt", "guidance_scale"):
            call_kwargs.pop(key, None)
            try:
                result = pipe(**call_kwargs)
                break
            except TypeError:
                continue
        else:
            raise
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Diffusers generation failed: {exc}") from exc
    images = list(getattr(result, "images", []) or [])
    if not images:
        raise RuntimeError("Diffusers returned no images")
    upscale = _parse_upscale(params.get("upscale"))
    if upscale > 1.0:
        images = [_upscale_image(image.convert("RGB"), upscale) for image in images]
        warnings.append(f"Images upscaled {upscale:g}× with Lanczos.")
    metadata = [
        {
            "model": model,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": images[index].width,
            "height": images[index].height,
            "requested_width": width,
            "requested_height": height,
            "steps": steps,
            "guidance": guidance,
            "seed": seed,
            "variant": index,
            "sampler": params.get("sampler"),
            "scheduler": params.get("scheduler"),
            "init_image": str(init_value) if init_value else None,
            "strength": strength if init_image is not None else None,
            "lora": params.get("lora"),
            "upscale": upscale,
            "device": device,
            "dtype": str(_dtype(torch, device, model)).replace("torch.", ""),
        }
        for index in range(len(images))
    ]
    return {"images": images, "metadata": metadata, "warnings": warnings}


def unload_models() -> int:
    with _CACHE_LOCK:
        count = len(_PIPELINES)
        _PIPELINES.clear()
        _LORA_STATE.clear()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass
    return count


__all__ = [
    "DiffusersUnavailable",
    "deps_installed",
    "generate",
    "local_models",
    "model_catalogue",
    "runtime_info",
    "unload_models",
]
