"""Piper catalog coverage for the voice service."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from services.voice.voices import VOICES, get_voice, language_matches


def test_required_languages_have_male_and_female_voices():
    by_language: dict[str, set[str]] = defaultdict(set)
    for voice in VOICES:
        by_language[voice.language].add(voice.gender)
    for language in ("en-US", "en-GB", "fr-FR", "de-DE", "es-ES"):
        assert "male" in by_language[language], language
        assert "female" in by_language[language], language


def test_catalog_ids_are_unique_and_resolvable():
    ids = [voice.id for voice in VOICES]
    assert len(ids) == len(set(ids))
    assert get_voice("en-US-ryan").gender == "male"
    assert get_voice("fr-FR-tom").language == "fr-FR"
    assert get_voice("es-ES-sharvard").speaker_id == 1


def test_public_catalog_reports_download_state(tmp_path: Path):
    voice = get_voice("de-DE-thorsten")
    payload = voice.public(tmp_path)
    assert payload["available"] is False
    assert payload["gender"] == "male"
    assert payload["download_hint"]
    assert payload["speaker_id"] is None
    voice.onnx_path(tmp_path).parent.mkdir(parents=True)
    voice.onnx_path(tmp_path).write_bytes(b"onnx")
    voice.config_path(tmp_path).write_text("{}", encoding="utf-8")
    assert voice.public(tmp_path)["available"] is True


def test_language_matching_accepts_regional_and_generic_codes():
    assert language_matches("en", "en-US")
    assert language_matches("en-US", "en-US")
    assert not language_matches("en-GB", "en-US")
    assert language_matches("pt", "pt-BR")
    assert not language_matches("pt-PT", "pt-BR")
