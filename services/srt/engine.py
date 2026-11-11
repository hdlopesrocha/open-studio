"""Lazy faster-whisper engine with model caching and health probing."""

from __future__ import annotations

import importlib.util
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from openstudio_common import MODELS_ROOT, env, env_bool, env_int

log = logging.getLogger("srt.engine")

WHISPER_CACHE = Path(env("WHISPER_CACHE_DIR", str(MODELS_ROOT / "whisper")))

MODEL_SPECS: list[dict[str, Any]] = [
    {
        "id": "tiny",
        "name": "Whisper Tiny",
        "repo": "Systran/faster-whisper-tiny",
        "parameters": "39M",
        "disk_mb": 75,
        "multilingual": True,
        "speed": "fastest",
        "description": "Very fast drafts, short clips and low-power CPUs. Accuracy is limited.",
    },
    {
        "id": "base",
        "name": "Whisper Base",
        "repo": "Systran/faster-whisper-base",
        "parameters": "74M",
        "disk_mb": 145,
        "multilingual": True,
        "speed": "very fast",
        "description": "Quick previews and clean speech. Good CPU baseline.",
    },
    {
        "id": "small",
        "name": "Whisper Small",
        "repo": "Systran/faster-whisper-small",
        "parameters": "244M",
        "disk_mb": 480,
        "multilingual": True,
        "speed": "fast",
        "description": "Balanced quality and speed for podcasts, interviews and lyrics.",
    },
    {
        "id": "medium",
        "name": "Whisper Medium",
        "repo": "Systran/faster-whisper-medium",
        "parameters": "769M",
        "disk_mb": 1500,
        "multilingual": True,
        "speed": "moderate",
        "description": "High accuracy. Best with a GPU or a fast multi-core CPU.",
    },
    {
        "id": "large-v3",
        "name": "Whisper Large v3",
        "repo": "Systran/faster-whisper-large-v3",
        "parameters": "1550M",
        "disk_mb": 3100,
        "multilingual": True,
        "speed": "slow",
        "description": "Best multilingual accuracy; recommended for lyric alignment.",
    },
    {
        "id": "distil-large-v3",
        "name": "Distil Whisper Large v3",
        "repo": "Systran/faster-distil-whisper-large-v3",
        "parameters": "756M",
        "disk_mb": 1500,
        "multilingual": False,
        "speed": "fast",
        "description": "English-only distilled large model. Near large-v3 quality at ~2x speed.",
    },
]

MODEL_ALIASES = {
    "tiny.en": "tiny.en",
    "base.en": "base.en",
    "small.en": "small.en",
    "medium.en": "medium.en",
    "large-v1": "large-v1",
    "large-v2": "large-v2",
    "large": "large-v3",
    "distil-large-v2": "distil-large-v2",
    "distil-medium.en": "distil-medium.en",
    "distil-small.en": "distil-small.en",
}

DEFAULT_MODEL = env("WHISPER_DEFAULT_MODEL", "small")


def canonical_model(value: str | None) -> str:
    value = (value or DEFAULT_MODEL).strip()
    if not value:
        value = DEFAULT_MODEL
    return MODEL_ALIASES.get(value, value)


def imported() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def ctranslate2_version() -> str | None:
    try:
        import ctranslate2

        return getattr(ctranslate2, "__version__", None)
    except Exception:  # noqa: BLE001
        return None


_gpu_cache: tuple[float, dict[str, Any]] | None = None


def gpu_info(force: bool = False) -> dict[str, Any]:
    """Best-effort GPU status without importing torch."""
    global _gpu_cache
    now = time.time()
    if not force and _gpu_cache and now - _gpu_cache[0] < 30:
        return _gpu_cache[1]
    info: dict[str, Any] = {
        "available": False,
        "device_count": 0,
        "name": None,
        "memory_total_mb": None,
        "memory_free_mb": None,
        "compute_types": [],
        "detail": "No CUDA device detected.",
    }
    try:
        import ctranslate2

        count = int(ctranslate2.get_cuda_device_count())
        info["device_count"] = count
        info["available"] = count > 0
        if count:
            info["detail"] = f"{count} CUDA device(s) visible to CTranslate2."
            try:
                info["compute_types"] = sorted(ctranslate2.get_supported_compute_types("cuda"))
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        info["detail"] = f"CUDA probe failed: {exc}"
    if shutil.which("nvidia-smi"):
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.total,memory.free",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            first = next((line for line in result.stdout.splitlines() if line.strip()), "")
            if first:
                parts = [part.strip() for part in first.split(",")]
                info["name"] = parts[0] if parts else None
                try:
                    info["memory_total_mb"] = int(float(parts[1]))
                except (IndexError, ValueError):
                    pass
                try:
                    info["memory_free_mb"] = int(float(parts[2]))
                except (IndexError, ValueError):
                    pass
                info["available"] = True
                if not info["device_count"]:
                    info["device_count"] = 1
                info["detail"] = f"{info['name']} ({info['memory_total_mb'] or '?'} MB VRAM)."
        except Exception:  # noqa: BLE001
            pass
    _gpu_cache = (now, info)
    return info


def ffmpeg_info() -> dict[str, Any]:
    binary = shutil.which("ffmpeg")
    probe = shutil.which("ffprobe")
    version = None
    if binary:
        try:
            result = subprocess.run(
                [binary, "-version"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            version = (result.stdout.splitlines() or [""])[0]
        except Exception:  # noqa: BLE001
            version = None
    return {"available": bool(binary), "path": binary, "version": version, "ffprobe": probe}


def model_cached(model_id: str) -> bool:
    candidate = WHISPER_CACHE / model_id
    if candidate.exists():
        return True
    patterns = [
        f"models--Systran--faster-whisper-{model_id}",
        f"models--Systran--faster-distil-whisper-{model_id.replace('distil-', '')}",
        f"models--*--*{model_id}*",
    ]
    for pattern in patterns:
        try:
            if any(WHISPER_CACHE.glob(pattern)):
                return True
        except OSError:
            continue
    return False


def resolve_device(preferred: str | None = None) -> str:
    preferred = (preferred or env("WHISPER_DEVICE", "auto")).strip().lower()
    if preferred in {"cpu", "cuda"}:
        return preferred
    return "cuda" if gpu_info().get("available") else "cpu"


def resolve_compute_type(device: str, preferred: str | None = None) -> str:
    preferred = (preferred or env("WHISPER_COMPUTE_TYPE", "auto")).strip().lower()
    if preferred not in {"", "auto"}:
        return preferred
    return "float16" if device == "cuda" else "int8"


class WhisperEngine:
    """Thread-safe model cache.

    Loading is intentionally lazy: importing this service, serving /catalog and
    converting subtitle files never download or load a model.
    """

    def __init__(self) -> None:
        self.cache_dir = WHISPER_CACHE
        self._models: dict[tuple[str, str, str], tuple[Any, dict[str, Any]]] = {}
        self._lock = threading.RLock()
        self._load_seconds: dict[str, float] = {}

    def loaded_models(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(info) for _model, info in self._models.values()]

    def unload(self, model_id: str | None = None) -> int:
        removed = 0
        with self._lock:
            for key in list(self._models):
                if model_id is None or key[0] == canonical_model(model_id):
                    self._models.pop(key, None)
                    removed += 1
        return removed

    def load(
        self,
        model_id: str | None,
        *,
        device: str | None = None,
        compute_type: str | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        name = canonical_model(model_id)
        device = resolve_device(device)
        compute = resolve_compute_type(device, compute_type)
        key = (name, device, compute)
        with self._lock:
            cached = self._models.get(key)
            if cached:
                return cached
            if not imported():
                raise RuntimeError(
                    "faster-whisper is not installed in this image. Rebuild the srt service "
                    "with its requirements, or use /convert and /from-text without a model."
                )
            import faster_whisper

            self.cache_dir.mkdir(parents=True, exist_ok=True)
            started = time.time()
            warnings: list[str] = []
            try:
                model = faster_whisper.WhisperModel(
                    name,
                    device=device,
                    compute_type=compute,
                    download_root=str(self.cache_dir),
                    cpu_threads=max(1, env_int("WHISPER_CPU_THREADS", min(8, os.cpu_count() or 4))),
                    num_workers=1,
                    local_files_only=env_bool("WHISPER_LOCAL_FILES_ONLY", False),
                )
            except Exception as exc:  # noqa: BLE001
                if device == "cuda":
                    warnings.append(f"CUDA load failed ({exc}); falling back to CPU int8.")
                    device = "cpu"
                    compute = resolve_compute_type("cpu", "int8")
                    key = (name, device, compute)
                    model = faster_whisper.WhisperModel(
                        name,
                        device=device,
                        compute_type=compute,
                        download_root=str(self.cache_dir),
                        cpu_threads=max(1, env_int("WHISPER_CPU_THREADS", 4)),
                        num_workers=1,
                        local_files_only=env_bool("WHISPER_LOCAL_FILES_ONLY", False),
                    )
                else:
                    raise
            elapsed = round(time.time() - started, 2)
            info = {
                "model": name,
                "device": device,
                "compute_type": compute,
                "load_seconds": elapsed,
                "warnings": warnings,
            }
            self._models[key] = (model, info)
            self._load_seconds[name] = elapsed
            log.info("Loaded Whisper model %s on %s (%s) in %.2fs", name, device, compute, elapsed)
            return model, info

    def status(self) -> dict[str, Any]:
        models = []
        for spec in MODEL_SPECS:
            models.append(
                {
                    "id": spec["id"],
                    "downloaded": model_cached(spec["id"]),
                    "multilingual": spec["multilingual"],
                }
            )
        return {
            "available": imported(),
            "ctranslate2_version": ctranslate2_version(),
            "cache_dir": str(self.cache_dir),
            "cache_exists": self.cache_dir.exists(),
            "downloads_enabled": not env_bool("WHISPER_LOCAL_FILES_ONLY", False),
            "device": resolve_device(),
            "compute_type": resolve_compute_type(resolve_device()),
            "loaded": self.loaded_models(),
            "models": models,
            "gpu": gpu_info(),
            "ffmpeg": ffmpeg_info(),
        }


ENGINE = WhisperEngine()
