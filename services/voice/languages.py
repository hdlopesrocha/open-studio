"""Language catalog for OmniVoice and the Portuguese variant metadata."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

POPULAR_LANGUAGE_IDS = [
    "en",
    "zh",
    "es",
    "fr",
    "de",
    "pt",
    "pt-PT",
    "pt-BR",
    "it",
    "ja",
    "ko",
    "ru",
    "ar",
    "hi",
]

# OmniVoice exposes a single `pt` model language. These are profile tags: the
# reference clip controls the accent, so a variant needs a matching voice.
PORTUGUESE_VARIANTS = [
    {
        "id": "pt-PT",
        "name": "Portuguese (Portugal)",
        "iso": "por",
        "hours": 0.0,
        "variant_of": "pt",
        "requires_voice": True,
    },
    {
        "id": "pt-BR",
        "name": "Portuguese (Brazil)",
        "iso": "por",
        "hours": 0.0,
        "variant_of": "pt",
        "requires_voice": True,
    },
]
PORTUGUESE_VARIANT_IDS = {variant["id"] for variant in PORTUGUESE_VARIANTS}

_FALLBACK_LANGUAGES = [
    {"id": "en", "name": "English", "iso": "eng", "hours": 206061.0},
    {"id": "zh", "name": "Chinese (Mandarin)", "iso": "zho", "hours": 111343.0},
    {"id": "es", "name": "Spanish", "iso": "spa", "hours": 27559.0},
    {"id": "fr", "name": "French", "iso": "fra", "hours": 23675.0},
    {"id": "de", "name": "German", "iso": "deu", "hours": 21927.0},
    {"id": "pt", "name": "Portuguese (generic)", "iso": "por", "hours": 16855.0},
    {"id": "it", "name": "Italian", "iso": "ita", "hours": 9402.0},
    {"id": "ja", "name": "Japanese", "iso": "jpn", "hours": 36914.0},
    {"id": "ko", "name": "Korean", "iso": "kor", "hours": 8609.0},
    {"id": "ru", "name": "Russian", "iso": "rus", "hours": 20338.0},
    {"id": "ar", "name": "Arabic", "iso": "ara", "hours": 1483.0},
    {"id": "hi", "name": "Hindi", "iso": "hin", "hours": 117.0},
]


def _with_variants(languages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for language in languages:
        if language.get("id") == "pt":
            language["name"] = "Portuguese (generic)"
    existing = {str(language.get("id")) for language in languages}
    for variant in PORTUGUESE_VARIANTS:
        if variant["id"] not in existing:
            languages.append(dict(variant))
    return languages


def load_languages() -> list[dict[str, Any]]:
    """Load the official OmniVoice language map shipped with the service."""
    path = Path(__file__).with_name("data") / "languages.tsv"
    if not path.is_file():
        return _with_variants(list(_FALLBACK_LANGUAGES))

    languages: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for row in reader:
                language_id = (row.get("language_id") or "").strip()
                name = (row.get("language_name") or "").strip()
                if not language_id or not name:
                    continue
                try:
                    hours = float(row.get("train_data_duration") or 0)
                except ValueError:
                    hours = 0.0
                languages.append(
                    {
                        "id": language_id,
                        "name": name,
                        "iso": (row.get("iso_639_3_id") or "").strip() or None,
                        "hours": hours,
                    }
                )
    except Exception:  # noqa: BLE001 - a broken data file must not stop startup
        return _with_variants(list(_FALLBACK_LANGUAGES))

    return _with_variants(languages or list(_FALLBACK_LANGUAGES))


LANGUAGES = load_languages()
LANGUAGE_IDS = {str(language["id"]) for language in LANGUAGES}
LANGUAGE_PAYLOAD = {
    "languages": LANGUAGES,
    "popular": POPULAR_LANGUAGE_IDS,
    "variants": PORTUGUESE_VARIANTS,
    "count": len(LANGUAGES),
}


def normalize_model_language(language: str | None) -> str | None:
    """OmniVoice has one `pt` model language; variants are profile tags."""
    if language in PORTUGUESE_VARIANT_IDS:
        return "pt"
    return language or None
