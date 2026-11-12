"""Configuration for the Open Studio voice service.

One service, two engines:

* ``omnivoice`` – cloning, voice design and auto mode with Whisper ASR.
* ``piper`` – small, fast ONNX voices with sentence-level timelines.

The OmniVoice stack is heavy (torch + transformers). Its imports are lazy so
the service starts, serves ``/health`` and the Piper engine even when the
package is missing from the image.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openstudio_common import FILES_ROOT, MODELS_ROOT, env, env_bool, env_float, env_int

APP_VERSION = "1.0.0"


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings, read once from the environment."""

    app_version: str
    # ── OmniVoice ──────────────────────────────────────────────────────────
    omnivoice_enabled: bool
    model_id: str
    device: str
    asr_model: str
    asr_device: str | None
    load_asr: bool
    lora_adapter: str | None
    flashinfer: bool
    flashinfer_cuda_graph: bool
    model_wait_seconds: int
    # ── Text / upload limits ───────────────────────────────────────────────
    max_input_chars: int
    max_upload_mb: int
    min_voice_seconds: float
    max_voice_seconds: float
    max_import_mb: int
    max_batch_items: int
    max_sentences: int
    piper_max_text_chars: int
    piper_max_segment_chars: int
    sentence_gap_ms: int
    # ── Piper ──────────────────────────────────────────────────────────────
    default_piper_voice: str
    piper_install_timeout: int
    # ── Defaults / UX ──────────────────────────────────────────────────────
    preview_text: str
    # ── Paths (derived from the shared roots) ──────────────────────────────
    files_root: Path
    models_root: Path

    @property
    def voice_dir(self) -> Path:
        return self.files_root / "voice"

    @property
    def voices_dir(self) -> Path:
        """All trained voice profiles live in the shared ``voices/`` folder."""
        return self.files_root / "voices"

    @property
    def outputs_dir(self) -> Path:
        return self.voice_dir / "outputs"

    @property
    def uploads_dir(self) -> Path:
        return self.voice_dir / "uploads"

    @property
    def piper_dir(self) -> Path:
        """Piper voice models live with the other user-facing voice data."""
        override = env("PIPER_MODELS_DIR", "").strip()
        return Path(override) if override else self.files_root / "voices" / "piper"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_version=env("VOICE_VERSION", APP_VERSION),
            omnivoice_enabled=env_bool("OMNIVOICE_ENABLED", True),
            model_id=env("OMNIVOICE_MODEL", "k2-fsa/OmniVoice").strip(),
            # CPU by default: the CPU image must not probe CUDA and fail late.
            device=env("DEVICE", "cpu").strip() or "cpu",
            asr_model=env("OMNIVOICE_ASR_MODEL", "openai/whisper-large-v3-turbo").strip(),
            asr_device=(env("OMNIVOICE_ASR_DEVICE", "") or "").strip() or None,
            load_asr=env_bool("OMNIVOICE_LOAD_ASR", False),
            lora_adapter=(env("OMNIVOICE_LORA_ADAPTER", "") or "").strip() or None,
            flashinfer=env_bool("OMNIVOICE_FLASHINFER", False),
            flashinfer_cuda_graph=env_bool("OMNIVOICE_FLASHINFER_CUDA_GRAPH", False),
            model_wait_seconds=env_int("OMNIVOICE_WAIT_SECONDS", 1800),
            max_input_chars=env_int("MAX_INPUT_CHARS", 8000),
            max_upload_mb=env_int("VOICE_MAX_UPLOAD_MB", 50),
            min_voice_seconds=env_float("MIN_VOICE_SECONDS", 1.0),
            max_voice_seconds=env_float("MAX_VOICE_SECONDS", 30.0),
            max_import_mb=env_int("MAX_IMPORT_MB", 200),
            max_batch_items=env_int("MAX_BATCH_ITEMS", 50),
            max_sentences=env_int("PIPER_MAX_SENTENCES", 5000),
            piper_max_text_chars=env_int("PIPER_MAX_TEXT_CHARS", 200000),
            piper_max_segment_chars=env_int("PIPER_MAX_SEGMENT_CHARS", 400),
            sentence_gap_ms=env_int("PIPER_SENTENCE_GAP_MS", 120),
            default_piper_voice=env("DEFAULT_PIPER_VOICE", "pt-PT-tugao").strip(),
            piper_install_timeout=env_int("PIPER_INSTALL_TIMEOUT_SECONDS", 1800),
            preview_text=env(
                "VOICE_PREVIEW_TEXT",
                "Hello! This is a preview of my trained voice. "
                "I hope you like how it sounds.",
            ).strip(),
            files_root=FILES_ROOT,
            models_root=MODELS_ROOT,
        )
