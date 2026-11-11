"""Configuration for the Open Studio translation service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openstudio_common import MODELS_ROOT, env, env_int


def _models_dir() -> Path:
    return Path(env("TRANSLATION_MODELS_DIR", str(MODELS_ROOT / "translation")))


@dataclass(frozen=True)
class Settings:
    models_dir: str = str(_models_dir())
    model_pt_en_repo: str = env("TRANSLATION_MODEL_PT_EN", "Helsinki-NLP/opus-mt-roa-en")
    model_en_pt_repo: str = env("TRANSLATION_MODEL_EN_PT", "Helsinki-NLP/opus-mt-tc-big-en-pt")
    model_nllb_repo: str = env("TRANSLATION_MODEL_NLLB", "facebook/nllb-200-distilled-600M")
    default_source_language: str = env("DEFAULT_SOURCE_LANGUAGE", "auto")
    default_target_language: str = env("DEFAULT_TARGET_LANGUAGE", "en")
    idle_unload_seconds: int = env_int("MODEL_IDLE_UNLOAD_SECONDS", 900)
    cpu_threads: int = env_int("CPU_THREADS", 4)
    max_input_chars: int = env_int("MAX_TRANSLATION_CHARS", 500_000)
    max_segments: int = env_int("MAX_TRANSLATION_SEGMENTS", 20_000)
    max_chunk_chars: int = env_int("TRANSLATION_CHUNK_CHARS", 850)
    max_input_tokens: int = env_int("TRANSLATION_MAX_INPUT_TOKENS", 480)
    num_beams: int = env_int("TRANSLATION_NUM_BEAMS", 2)
    max_length: int = env_int("TRANSLATION_MAX_TOKENS", 512)
    batch_size: int = env_int("TRANSLATION_BATCH_SIZE", 8)
    request_timeout_seconds: float = float(env("TRANSLATION_REQUEST_TIMEOUT", "1800"))
    log_level: str = env("LOG_LEVEL", "INFO")

    @property
    def opus_pt_en_dir(self) -> Path:
        return Path(self.models_dir) / "pt-en"

    @property
    def opus_en_pt_dir(self) -> Path:
        return Path(self.models_dir) / "en-pt"

    @property
    def nllb_dir(self) -> Path:
        return Path(self.models_dir) / "nllb-200-distilled-600M"

    @property
    def models(self) -> dict[str, dict[str, str]]:
        return {
            "opus-mt-pt-en": {
                "family": "opus-mt",
                "repo": self.model_pt_en_repo,
                "path": str(self.opus_pt_en_dir),
                "label": "OPUS-MT Portuguese → English",
            },
            "opus-mt-en-pt": {
                "family": "opus-mt",
                "repo": self.model_en_pt_repo,
                "path": str(self.opus_en_pt_dir),
                "label": "OPUS-MT English → Portuguese",
            },
            "nllb-200-distilled-600M": {
                "family": "nllb",
                "repo": self.model_nllb_repo,
                "path": str(self.nllb_dir),
                "label": "NLLB-200 Distilled 600M (multilingual)",
            },
        }


settings = Settings()
