"""Configuration for the Open Studio summarization service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openstudio_common import MODELS_ROOT, env, env_int, service_url


def _models_dir() -> Path:
    return Path(env("SUMMARY_MODELS_DIR", str(MODELS_ROOT / "summary")))


@dataclass(frozen=True)
class Settings:
    models_dir: str = str(_models_dir())
    model_en_repo: str = env(
        "SUMMARY_MODEL_EN", "farleyknight/cnn_dailymail-summarization-t5-small-2022-09-08"
    )
    model_pt_repo: str = env("SUMMARY_MODEL_PT", "rhaymison/t5-portuguese-small-summarization")
    model_en_revision: str = env("SUMMARY_MODEL_EN_REVISION", "main")
    model_pt_revision: str = env("SUMMARY_MODEL_PT_REVISION", "main")
    prompt_en: str = env("SUMMARY_PROMPT_EN", "summarize: ")
    prompt_pt: str = env("SUMMARY_PROMPT_PT", "sumarize: ")
    default_language: str = env("DEFAULT_SUMMARY_LANGUAGE", "auto")
    idle_unload_seconds: int = env_int("MODEL_IDLE_UNLOAD_SECONDS", 900)
    cpu_threads: int = env_int("CPU_THREADS", 4)
    max_input_chars: int = env_int("SUMMARY_MAX_INPUT_CHARS", 500_000)
    max_input_tokens: int = env_int("SUMMARY_MAX_INPUT_TOKENS", 480)
    max_chunks: int = env_int("SUMMARY_MAX_CHUNKS", 300)
    num_beams: int = env_int("SUMMARY_NUM_BEAMS", 3)
    short_tokens: int = env_int("SUMMARY_SHORT_TOKENS", 120)
    medium_tokens: int = env_int("SUMMARY_MEDIUM_TOKENS", 240)
    long_tokens: int = env_int("SUMMARY_LONG_TOKENS", 420)
    max_output_tokens: int = env_int("SUMMARY_MAX_OUTPUT_TOKENS", 1024)
    translation_service_url: str = env(
        "TRANSLATION_SERVICE_URL", env("TRANSLATION_URL", service_url("translation"))
    )
    translation_timeout_seconds: int = env_int("SUMMARY_TRANSLATION_TIMEOUT", 900)
    request_timeout_seconds: int = env_int("SUMMARY_REQUEST_TIMEOUT", 1800)
    log_level: str = env("LOG_LEVEL", "INFO")

    @property
    def model_directories(self) -> dict[str, str]:
        return {
            "en": str(Path(self.models_dir) / "en"),
            "pt": str(Path(self.models_dir) / "pt"),
        }

    @property
    def model_repositories(self) -> dict[str, str]:
        return {"en": self.model_en_repo, "pt": self.model_pt_repo}

    @property
    def token_budgets(self) -> dict[str, int]:
        return {
            "short": self.short_tokens,
            "medium": self.medium_tokens,
            "long": self.long_tokens,
        }


settings = Settings()
