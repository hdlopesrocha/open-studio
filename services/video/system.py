"""System status, provider discovery and model inventory for the video component."""

from __future__ import annotations

import os
import platform
import shutil
import socket
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
from mvstudio_shared.comfyui import ComfyUIClient
from mvstudio_shared.config import get_settings
from mvstudio_shared.media import encoder_available
from mvstudio_shared.storage import ProjectStore, disk_usage

from .clients import ServiceClient
from .jobs import JobManager
from .settings_store import AISettingsStore

SERVICE_NAMES = ["audio", "lyrics", "planner", "images", "animation", "renderer"]


def _cpu_info() -> dict[str, Any]:
    model = platform.processor() or "Unknown CPU"
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.lower().startswith("model name"):
                model = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    memory_total = 0
    memory_available = 0
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                memory_total = int(line.split()[1]) * 1024
            elif line.startswith("MemAvailable:"):
                memory_available = int(line.split()[1]) * 1024
    except OSError:
        pass
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu": model,
        "cpu_count": os.cpu_count() or 1,
        "memory_total": memory_total,
        "memory_available": memory_available,
    }


def _gpu_info() -> dict[str, Any]:
    dri_devices = []
    dri_dir = Path("/dev/dri")
    if dri_dir.exists():
        dri_devices = sorted(path.name for path in dri_dir.iterdir())
    nvidia_available = shutil.which("nvidia-smi") is not None
    return {
        "dri_devices": dri_devices,
        "integrated_or_discrete_linux_gpu": bool(dri_devices),
        "nvidia_smi": nvidia_available,
        "cuda_assumed": False,
        "notes": (
            "The core pipeline is CPU-only. Vulkan/VAAPI acceleration is optional; "
            "AI services are optional and use whichever backend their runtime provides."
        ),
    }


def _ollama_status(url: str, model: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "url": url,
        "available": False,
        "model": model,
        "model_installed": False,
        "models": [],
        "detail": "",
    }
    try:
        with httpx.Client(timeout=4.0) as client:
            response = client.get(f"{url.rstrip('/')}/api/tags")
        if response.status_code != 200:
            result["detail"] = f"HTTP {response.status_code}"
            return result
        payload = response.json()
        models = payload.get("models", [])
        result["available"] = True
        result["models"] = [
            {
                "name": item.get("name", ""),
                "size": item.get("size", 0),
                "digest": item.get("digest", ""),
                "modified_at": item.get("modified_at", ""),
                "location": f"ollama:{url}",
                "provider": "ollama",
                "dependencies": "Ollama runtime",
            }
            for item in models
        ]
        names = {item.get("name", "") for item in models}
        short_names = {name.split(":")[0] for name in names}
        result["model_installed"] = model in names or model.split(":")[0] in short_names
        result["detail"] = "available" if result["model_installed"] else (
            f"Model '{model}' is not installed. Install with: ollama pull {model}"
        )
    except Exception as exc:  # noqa: BLE001
        result["detail"] = f"Ollama is not reachable: {exc}"
    return result


def _comfy_status(
    url: str,
    image_workflow: str,
    video_workflow: str,
) -> dict[str, Any]:
    client = ComfyUIClient(url)
    available, detail = client.available()
    checkpoints = client.checkpoints() if available else []
    image_workflow_path = Path(image_workflow).expanduser() if image_workflow else None
    video_workflow_path = Path(video_workflow).expanduser() if video_workflow else None
    return {
        "url": url,
        "available": available,
        "detail": detail,
        "checkpoints": checkpoints,
        "image_workflow": {
            "path": image_workflow,
            "configured": bool(image_workflow),
            "exists": bool(image_workflow_path and image_workflow_path.is_file()),
        },
        "video_workflow": {
            "path": video_workflow,
            "configured": bool(video_workflow),
            "exists": bool(video_workflow_path and video_workflow_path.is_file()),
        },
    }


def _imagegen_status(client: ServiceClient) -> dict[str, Any]:
    status = client.health("images", timeout=4.0)
    result = {
        "url": get_settings().service_url("images"),
        "available": bool(status.get("available")),
        "detail": status.get("detail", ""),
        "providers": status.get("providers", []),
    }
    return result


def collect_status(
    *,
    store: ProjectStore,
    client: ServiceClient,
    manager: JobManager,
    ai_store: AISettingsStore,
    started_at: float,
    uptime_seconds: float,
) -> dict[str, Any]:
    settings = get_settings()
    ai = ai_store.load()
    services: dict[str, Any] = {}

    def check(name: str) -> dict[str, Any]:
        return client.health(name)

    with ThreadPoolExecutor(max_workers=7) as executor:
        futures = {name: executor.submit(check, name) for name in SERVICE_NAMES}
        for name, future in futures.items():
            try:
                services[name] = future.result(timeout=10)
            except Exception as exc:  # noqa: BLE001
                services[name] = {"available": False, "detail": str(exc)}
    projects = store.list()
    active_jobs = manager.active_jobs()
    ollama = _ollama_status(ai.ollama_url, ai.ollama_model)
    comfy = _comfy_status(ai.comfyui_url, ai.image_workflow_path, ai.video_workflow_path)
    usage = disk_usage(settings.projects_root)
    try:
        ffmpeg_ok = shutil.which(settings.ffmpeg) is not None
    except Exception:  # noqa: BLE001
        ffmpeg_ok = False
    encoders = {
        "libx264": encoder_available("libx264"),
        "libx265": encoder_available("libx265"),
    }
    return {
        "gateway": {
            "service": "video",
            "status": "ok",
            "version": "1.0.0",
            "uptime_seconds": round(uptime_seconds, 1),
            "hostname": socket.gethostname(),
        },
        "services": services,
        "projects": {
            "count": len(projects),
            "active_jobs": len(active_jobs),
        },
        "storage": {
            "projects_root": str(settings.projects_root),
            "exports_root": str(settings.exports_root),
            "cache_root": str(settings.cache_root),
            "config_root": str(settings.config_root),
            "models_root": str(settings.models_root),
            "disk": usage,
            "max_upload_mb": settings.max_upload_mb,
            "allow_external_output": settings.allow_external_output,
        },
        "providers": {
            "ollama": ollama,
            "comfyui": comfy,
            "imagegen": _imagegen_status(client),
        },
        "ai_settings": ai.model_dump(mode="json"),
        "hardware": {
            "cpu": _cpu_info(),
            "gpu": _gpu_info(),
            "ffmpeg": {"available": ffmpeg_ok, "path": settings.ffmpeg, "encoders": encoders},
        },
        "runtime": {
            "started_at": started_at,
        },
    }


def model_inventory(ai_store: AISettingsStore) -> dict[str, Any]:
    settings = get_settings()
    ai = ai_store.load()
    ollama = _ollama_status(ai.ollama_url, ai.ollama_model)
    comfy = _comfy_status(ai.comfyui_url, ai.image_workflow_path, ai.video_workflow_path)
    models: list[dict[str, Any]] = []
    for model in ollama.get("models", []):
        models.append(
            {
                **model,
                "type": "llm",
                "compatible": True,
                "compatibility_note": (
                    "Runs through Ollama. CPU execution is supported; larger models need more RAM."
                ),
            }
        )
    for checkpoint in comfy.get("checkpoints", []):
        models.append(
            {
                "name": checkpoint,
                "size": 0,
                "digest": "",
                "modified_at": "",
                "location": f"comfyui:{ai.comfyui_url}",
                "provider": "comfyui",
                "dependencies": "ComfyUI + a compatible image or video workflow",
                "type": "image-model",
                "compatible": comfy.get("available", False),
                "compatibility_note": (
                    "Requires ComfyUI and a user-provided API workflow. No model is downloaded automatically."
                ),
            }
        )
    return {
        "models": models,
        "ollama": ollama,
        "comfyui": comfy,
        "image_providers": [
            {
                "id": "auto",
                "name": "Auto",
                "description": "Use the best configured image provider, falling back to procedural art.",
            },
            {
                "id": "procedural",
                "name": "Procedural",
                "description": "Deterministic Pillow artwork; no model needed.",
            },
            {
                "id": "comfyui",
                "name": "ComfyUI",
                "description": "User-managed ComfyUI workflow with checkpoint and sampler controls.",
            },
            {
                "id": "qvac",
                "name": "QVAC",
                "description": "Local QVAC diffusion through the shared imagegen service.",
            },
            {
                "id": "diffusers",
                "name": "Diffusers",
                "description": "Local Hugging Face diffusers pipeline through imagegen.",
            },
        ],
        "models_root": str(settings.models_root),
        "notes": [
            "No models are downloaded automatically on startup.",
            "Procedural artwork and FFmpeg animation work without any installed AI model.",
        ],
    }
