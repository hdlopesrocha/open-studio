"""Piper synthesis wrapper with lazy imports and a single cached voice."""

from __future__ import annotations

import importlib.util
import logging
import threading
import wave
from pathlib import Path
from typing import Any

from .config import Settings
from .errors import PiperUnavailableError, PiperVoiceMissingError
from .voices import PiperVoice

logger = logging.getLogger(__name__)


class PiperEngine:
    """Reuse one Piper voice at a time to keep memory bounded."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        self._voice: Any = None
        self._voice_id: str | None = None

    @staticmethod
    def module_available() -> bool:
        try:
            return (
                importlib.util.find_spec("piper") is not None
                and importlib.util.find_spec("onnxruntime") is not None
            )
        except (ImportError, ValueError):
            return False

    @staticmethod
    def version() -> str | None:
        try:
            from importlib.metadata import version

            return version("piper-tts")
        except Exception:  # noqa: BLE001
            return None

    def status(self, voices_installed: int = 0, voices_total: int = 0) -> dict[str, Any]:
        available = self.module_available()
        return {
            "status": "ok" if available else "unavailable",
            "available": available,
            "version": self.version(),
            "models_dir": str(self.settings.piper_dir),
            "voices_total": voices_total,
            "voices_installed": voices_installed,
            "pitch_supported": False,
        }

    def _load(self, voice: PiperVoice) -> Any:
        if not voice.available(self.settings.piper_dir):
            raise PiperVoiceMissingError(
                f"The Piper voice {voice.id} is not installed.",
                details={
                    "voice_id": voice.id,
                    "install": f'POST /api/voice/piper/install {{"voice_id":"{voice.id}"}}',
                },
            )
        if self._voice is not None and self._voice_id == voice.id:
            return self._voice

        try:
            from piper import PiperVoice as PiperVoiceModel
        except ImportError as exc:
            raise PiperUnavailableError(
                "piper-tts is not installed in this image; Piper voices are unavailable.",
                details={"voice_id": voice.id},
            ) from exc

        try:
            loaded = PiperVoiceModel.load(
                str(voice.onnx_path(self.settings.piper_dir)),
                config_path=str(voice.config_path(self.settings.piper_dir)),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to load Piper voice %s", voice.id)
            raise PiperUnavailableError(
                f"The Piper voice {voice.id} could not be initialized: {exc}",
                details={"voice_id": voice.id},
            ) from exc

        self._voice = loaded
        self._voice_id = voice.id
        logger.info("Loaded Piper voice %s", voice.id)
        return loaded

    def synthesize_sentence(
        self,
        voice: PiperVoice,
        text: str,
        speed: float,
        destination: Path,
    ) -> None:
        """Synthesize one sentence to a mono 16-bit WAV file."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            loaded = self._load(voice)
            try:
                from piper import SynthesisConfig
            except ImportError as exc:
                raise PiperUnavailableError(
                    "Piper SynthesisConfig is not available in this piper-tts version.",
                    details={"voice_id": voice.id},
                ) from exc

            config = SynthesisConfig(
                length_scale=1.0 / max(0.25, float(speed or 1.0)),
                noise_scale=0.667,
                noise_w_scale=0.8,
                normalize_audio=True,
                volume=1.0,
            )
            try:
                with wave.open(str(destination), "wb") as wav_file:
                    loaded.synthesize_wav(text, wav_file, syn_config=config)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Piper synthesis failed for %s", voice.id)
                raise PiperUnavailableError(
                    f"Piper synthesis failed: {exc}",
                    details={"voice_id": voice.id},
                ) from exc

        if not destination.is_file() or destination.stat().st_size <= 44:
            raise PiperUnavailableError(
                "The Piper engine did not produce audio for this sentence.",
                details={"voice_id": voice.id},
            )

    def unload(self) -> None:
        with self._lock:
            self._voice = None
            self._voice_id = None
