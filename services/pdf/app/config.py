"""Configuration for the Open Studio PDF service."""

from __future__ import annotations

from dataclasses import dataclass

from openstudio_common import env, env_bool, env_int


@dataclass(frozen=True)
class Settings:
    max_upload_mb: int = env_int("MAX_UPLOAD_MB", 200)
    max_pages: int = env_int("MAX_PDF_PAGES", 2000)
    ocr_enabled_default: bool = env_bool("OCR_ENABLED_DEFAULT", False)
    ocr_languages: str = env("OCR_LANGUAGES", "por+eng")
    ocr_dpi: int = env_int("OCR_DPI", 200)
    ocr_timeout_seconds: int = env_int("OCR_TIMEOUT_SECONDS", 180)
    ocr_min_chars: int = env_int("OCR_MIN_CHARS", 40)
    preview_width: int = env_int("PDF_PREVIEW_WIDTH", 480)
    preview_max_pages_saved: int = env_int("PDF_PREVIEW_MAX_PAGES", 200)
    log_level: str = env("LOG_LEVEL", "INFO")


settings = Settings()
