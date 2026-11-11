"""Owns the single OmniVoice model instance and serializes inference.

The model is loaded lazily in a daemon thread at service startup. Missing
optional packages are a supported state: the engine reports ``unavailable``
with a clear message and the rest of the service (Piper, history, uploads)
keeps working.
"""

from __future__ import annotations

import importlib.util
import logging
import threading
import time
from pathlib import Path
from typing import Any

from .config import Settings

logger = logging.getLogger(__name__)

OMNIVOICE_MISSING_MESSAGE = (
    "OmniVoice is not installed in this image. Cloning, voice design and "
    "Whisper transcription are disabled. Piper voices remain fully available."
)


class ModelNotReadyError(RuntimeError):
    def __init__(self, message: str, status: str = "loading") -> None:
        super().__init__(message)
        self.status = status


class ModelManager:
    """Owns the OmniVoice model and a small cache of loaded voice prompts."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model: Any = None
        self.package_available = importlib.util.find_spec("omnivoice") is not None
        if not settings.omnivoice_enabled:
            self.status = "unavailable"
            self.status_message = "OmniVoice disabled by OMNIVOICE_ENABLED=false"
        elif not self.package_available:
            self.status = "unavailable"
            self.status_message = OMNIVOICE_MISSING_MESSAGE
        else:
            self.status = "loading"
            self.status_message = "Starting OmniVoice"
        self.error = (
            None
            if settings.omnivoice_enabled and self.package_available
            else self.status_message
        )
        self.device = settings.device
        self.sample_rate = 24_000
        self.started_at = time.time()
        self.load_started_at: float | None = None
        self.loaded_at: float | None = None
        self.lora_adapter = settings.lora_adapter
        self.flashinfer_enabled = False

        self._torch: Any = None
        self._thread: threading.Thread | None = None
        self._model_lock = threading.RLock()
        self._cache_lock = threading.Lock()
        self._prompt_cache: dict[str, tuple[float, Any]] = {}

    @property
    def model_loaded(self) -> bool:
        return self.model is not None

    @property
    def asr_loaded(self) -> bool:
        return bool(self.model is not None and getattr(self.model, "_asr_pipe", None))

    @property
    def uptime_seconds(self) -> float:
        return round(time.time() - self.started_at, 1)

    @property
    def load_seconds(self) -> float | None:
        if self.load_started_at is None:
            return None
        end = self.loaded_at or time.time()
        return round(end - self.load_started_at, 1)

    @property
    def ready(self) -> bool:
        return self.status == "ok" and self.model is not None

    def start_loading(self) -> None:
        if not self.settings.omnivoice_enabled:
            self.status = "unavailable"
            self.status_message = "OmniVoice disabled by OMNIVOICE_ENABLED=false"
            self.error = self.status_message
            return
        self.package_available = importlib.util.find_spec("omnivoice") is not None
        if not self.package_available:
            self.status = "unavailable"
            self.status_message = OMNIVOICE_MISSING_MESSAGE
            self.error = OMNIVOICE_MISSING_MESSAGE
            logger.warning(OMNIVOICE_MISSING_MESSAGE)
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._load, name="omnivoice-loader", daemon=True)
        self._thread.start()

    def reload(self) -> None:
        if self.status == "loading":
            return
        with self._model_lock:
            self.model = None
            self._prompt_cache.clear()
            if self._torch is not None:
                try:
                    if self._torch.cuda.is_available():
                        self._torch.cuda.empty_cache()
                except Exception:  # noqa: BLE001
                    pass
            self.status = "loading"
            self.status_message = "Reloading OmniVoice model"
            self.error = None
            self.loaded_at = None
            self.flashinfer_enabled = False
            self.lora_adapter = self.settings.lora_adapter
        self.start_loading()

    def ensure_ready(self) -> None:
        if self.status == "unavailable":
            raise ModelNotReadyError(self.status_message, status="unavailable")
        if self.status == "error":
            raise ModelNotReadyError(self.error or "The model failed to load", status="error")
        if self.model is None:
            raise ModelNotReadyError(
                "The OmniVoice model is still loading. Please wait for warm-up to finish.",
                status="loading",
            )

    def _resolve_device(self, torch: Any) -> str:
        requested = (self.settings.device or "cpu").strip()
        if requested and requested.lower() != "auto":
            return requested
        if torch.cuda.is_available():
            return "cuda:0"
        try:
            if torch.backends.mps.is_available():
                return "mps"
        except Exception:  # noqa: BLE001
            pass
        try:
            if hasattr(torch, "xpu") and torch.xpu.is_available():
                return "xpu"
        except Exception:  # noqa: BLE001
            pass
        return "cpu"

    def _load(self) -> None:
        self.status = "loading"
        self.status_message = "Loading OmniVoice model weights. The first run downloads several GB."
        self.error = None
        self.load_started_at = time.time()
        self.loaded_at = None

        if importlib.util.find_spec("omnivoice") is None:
            self.package_available = False
            self.status = "unavailable"
            self.status_message = OMNIVOICE_MISSING_MESSAGE
            self.error = OMNIVOICE_MISSING_MESSAGE
            logger.warning(OMNIVOICE_MISSING_MESSAGE)
            return

        try:
            import torch
            from omnivoice import OmniVoice

            self._torch = torch
            self.package_available = True
            device = self._resolve_device(torch)
            dtype = (
                torch.float16
                if str(device).startswith(("cuda", "xpu"))
                else torch.float32
            )

            logger.info(
                "Loading OmniVoice model %s on %s (%s)",
                self.settings.model_id,
                device,
                dtype,
            )
            model = OmniVoice.from_pretrained(
                self.settings.model_id,
                device_map=device,
                dtype=dtype,
                asr_model_name=self.settings.asr_model,
                asr_device=self.settings.asr_device,
                load_asr=self.settings.load_asr,
            )

            if self.settings.lora_adapter:
                adapter_path = Path(self.settings.lora_adapter).expanduser()
                if not adapter_path.exists():
                    raise FileNotFoundError(f"LoRA adapter directory not found: {adapter_path}")
                from omnivoice.utils.lora import load_lora_adapter

                logger.info("Applying LoRA adapter from %s", adapter_path)
                model = load_lora_adapter(model, str(adapter_path))
                self.lora_adapter = str(adapter_path)

            if self.settings.flashinfer:
                try:
                    from omnivoice.models.omnivoice_flashinfer import apply_flashinfer

                    logger.info(
                        "Enabling FlashInfer (cuda_graph=%s)",
                        self.settings.flashinfer_cuda_graph,
                    )
                    apply_flashinfer(
                        model,
                        enable_cuda_graph=self.settings.flashinfer_cuda_graph,
                    )
                    self.flashinfer_enabled = True
                except Exception:  # noqa: BLE001
                    logger.exception("FlashInfer could not be enabled; continuing without it")
                    self.flashinfer_enabled = False

            with self._model_lock:
                self.model = model
                self.device = str(getattr(model, "device", device))
                self.sample_rate = int(getattr(model, "sampling_rate", 24_000) or 24_000)
                self.status = "ok"
                self.status_message = "Model ready"
                self.loaded_at = time.time()

            logger.info("OmniVoice ready on %s in %.1fs", self.device, self.load_seconds or 0.0)
        except ImportError as exc:
            # A missing transitive dependency is still "unavailable", not a
            # corrupt model. The message names the missing module.
            self.package_available = importlib.util.find_spec("omnivoice") is not None
            self.status = "unavailable"
            self.status_message = f"OmniVoice could not be imported: {exc}. Piper voices remain available."
            self.error = str(exc)
            logger.warning(self.status_message)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to load OmniVoice")
            with self._model_lock:
                self.model = None
                self.status = "error"
                self.status_message = "OmniVoice model failed to load"
                self.error = str(exc)
                self.loaded_at = None

    def create_prompt(
        self,
        ref_audio: str,
        ref_text: str | None,
        preprocess_prompt: bool = True,
    ) -> Any:
        with self._model_lock:
            self.ensure_ready()
            return self.model.create_voice_clone_prompt(
                ref_audio=ref_audio,
                ref_text=ref_text or None,
                preprocess_prompt=preprocess_prompt,
            )

    def load_prompt(self, voice_id: str, path: Path) -> Any:
        try:
            from omnivoice import VoiceClonePrompt
        except ImportError as exc:
            raise ModelNotReadyError(
                f"OmniVoice is not installed, cannot load voice prompts: {exc}",
                status="unavailable",
            ) from exc

        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError as exc:
            raise FileNotFoundError("Voice prompt file is missing") from exc

        with self._cache_lock:
            cached = self._prompt_cache.get(voice_id)
            if cached is not None and cached[0] == mtime:
                return cached[1]

        prompt = VoiceClonePrompt.load(str(path))
        with self._cache_lock:
            self._prompt_cache[voice_id] = (mtime, prompt)
        return prompt

    def invalidate_voice(self, voice_id: str) -> None:
        with self._cache_lock:
            self._prompt_cache.pop(voice_id, None)

    def generate(
        self,
        *,
        text: str,
        language: str | None = None,
        voice_clone_prompt: Any = None,
        instruct: str | None = None,
        speed: float | None = 1.0,
        duration: float | None = None,
        num_step: int = 32,
        guidance_scale: float = 2.0,
        denoise: bool = True,
        t_shift: float = 0.1,
        position_temperature: float = 5.0,
        class_temperature: float = 0.0,
        layer_penalty_factor: float = 5.0,
        postprocess_output: bool = True,
        pad_duration: float = 0.1,
        fade_duration: float = 0.1,
        audio_chunk_duration: float = 15.0,
        audio_chunk_threshold: float = 30.0,
        normalize_text: bool = False,
        seed: int | None = None,
    ) -> tuple[Any, int, float]:
        with self._model_lock:
            self.ensure_ready()
            if seed is not None:
                import random

                import numpy as np

                random.seed(seed)
                np.random.seed(seed)
                self._torch.manual_seed(seed)
                try:
                    if self._torch.cuda.is_available():
                        self._torch.cuda.manual_seed_all(seed)
                except Exception:  # noqa: BLE001
                    pass
            started = time.time()
            audios = self.model.generate(
                text=text,
                language=language or None,
                voice_clone_prompt=voice_clone_prompt,
                instruct=instruct or None,
                speed=speed,
                duration=duration,
                num_step=num_step,
                guidance_scale=guidance_scale,
                denoise=denoise,
                t_shift=t_shift,
                position_temperature=position_temperature,
                class_temperature=class_temperature,
                layer_penalty_factor=layer_penalty_factor,
                postprocess_output=postprocess_output,
                pad_duration=pad_duration,
                fade_duration=fade_duration,
                audio_chunk_duration=audio_chunk_duration,
                audio_chunk_threshold=audio_chunk_threshold,
                normalize_text=normalize_text,
            )
            elapsed = time.time() - started
            return audios[0], self.sample_rate, elapsed

    def transcribe(self, audio_path: str) -> str:
        with self._model_lock:
            self.ensure_ready()
            if getattr(self.model, "_asr_pipe", None) is None:
                self.model.load_asr_model()
            return self.model.transcribe(audio_path)

    def health(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.status_message,
            "error": self.error,
            "available": self.package_available,
            "model_loaded": self.model_loaded,
            "model_id": self.settings.model_id,
            "device": self.device,
            "sample_rate": self.sample_rate,
            "asr_model": self.settings.asr_model,
            "asr_loaded": self.asr_loaded,
            "load_seconds": self.load_seconds,
            "lora_adapter": self.lora_adapter,
            "flashinfer": self.flashinfer_enabled,
        }
