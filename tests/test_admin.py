"""Service manager compose-command helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("openstudio_admin_main", ROOT / "services" / "admin" / "main.py")
assert SPEC and SPEC.loader
admin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(admin)

CONFIGURED = {
    "jobhub": {"depends_on": None},
    "imagegen": {"depends_on": {"jobhub": {"condition": "service_healthy"}}},
    "video-audio": {},
    "video": {"depends_on": {"jobhub": {}, "video-audio": {}, "imagegen": {}}},
    "translation": {},
    "srt": {"depends_on": {"jobhub": {}, "translation": {}}},
    "pdf": {},
    "summary": {},
    "voice": {},
    "ffmpeg": {},
    "docs": {
        "depends_on": {
            "jobhub": {},
            "pdf": {},
            "translation": {},
            "summary": {},
            "voice": {},
            "ffmpeg": {},
        }
    },
}


def test_core_dependencies_are_never_selected():
    assert admin.required_services("imagegen", CONFIGURED) == []
    assert "jobhub" not in admin.required_services("video", CONFIGURED)


def test_compose_dependencies_are_included():
    assert admin.required_services("srt", CONFIGURED) == ["translation"]
    assert admin.required_services("video", CONFIGURED) == ["imagegen", "video-audio"]


def test_meta_dependencies_are_included():
    expected = ["ffmpeg", "pdf", "summary", "translation", "voice"]
    assert admin.required_services("docs", CONFIGURED) == expected


def test_unknown_service_has_no_dependencies():
    assert admin.required_services("nope", CONFIGURED) == []


def test_model_catalog_covers_every_model_family():
    items = admin.MODEL_ITEMS
    ids = [item["id"] for item in items]
    assert len(ids) == len(set(ids))
    kinds = {item["kind"] for item in items}
    assert {"ollama", "music", "whisper", "translation", "summary", "piper", "omnivoice", "diffusers", "qvac"} <= kinds
    groups = admin._model_groups(items)
    assert {group["group"] for group in groups} >= {"Language", "Music", "Voice", "Subtitles", "Text", "Images", "QVAC"}
    assert sum(len(group["items"]) for group in groups) == len(items)
    assert {"translation-opus", "translation-nllb", "summary-en", "summary-pt", "whisper-base", "whisper-medium"} <= set(ids)
