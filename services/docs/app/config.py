"""Configuration for the documents workflow service."""

from __future__ import annotations

from dataclasses import dataclass

from openstudio_common import env, env_int, service_url


@dataclass(frozen=True)
class Settings:
    max_text_chars: int = env_int("DOCS_MAX_TEXT_CHARS", 200_000)
    max_tts_chars: int = env_int("DOCS_MAX_TTS_CHARS", 500_000)
    max_pages: int = env_int("DOCS_MAX_PAGES", 2000)
    max_segments: int = env_int("DOCS_MAX_SEGMENTS", 5000)
    capabilities_timeout: int = env_int("DOCS_CAPABILITIES_TIMEOUT", 6)
    pdf_timeout: int = env_int("DOCS_PDF_TIMEOUT", 1800)
    translation_timeout: int = env_int("DOCS_TRANSLATION_TIMEOUT", 3600)
    summary_timeout: int = env_int("DOCS_SUMMARY_TIMEOUT", 3600)
    tts_timeout: int = env_int("DOCS_TTS_TIMEOUT", 7200)
    ffmpeg_timeout: int = env_int("DOCS_FFMPEG_TIMEOUT", 1800)
    pdf_url: str = env("PDF_URL", service_url("pdf"))
    translation_url: str = env("TRANSLATION_URL", service_url("translation"))
    summary_url: str = env("SUMMARY_URL", service_url("summary"))
    voice_url: str = env("VOICE_URL", service_url("voice"))
    ffmpeg_url: str = env("FFMPEG_URL", service_url("ffmpeg"))
    tts_internal_path: str = env("DOCS_TTS_INTERNAL_PATH", "/internal/tts")
    ffmpeg_finalize_path: str = env("DOCS_FFMPEG_FINALIZE_PATH", "/internal/finalize")
    log_level: str = env("LOG_LEVEL", "INFO")


settings = Settings()
