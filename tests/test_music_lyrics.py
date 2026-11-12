"""Deterministic music-domain tests: lyrics parsing, sections and request contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.music import prompts
from services.music.db import section_type
from services.music.lyrics import DEFAULT_STRUCTURE, build_prompt, parse_sectioned_lyrics
from services.music.schemas import (
    ExportRequest,
    GenerateRequest,
    LyricsDraftRequest,
    LyricsPlanItem,
    LyricsSection,
)


def test_parse_sectioned_lyrics_maps_labels_and_preserves_body():
    draft = """```text
[Intro]
A city wakes up

[Verse 1]
The streetlights blink twice
I count the quiet cars

[Refrão]
Hold on, hold on
```
"""
    sections = parse_sectioned_lyrics(draft)

    assert [section["type"] for section in sections] == ["intro", "verse", "chorus"]
    assert [section["label"] for section in sections] == ["Intro", "Verse 1", "Refrão"]
    assert sections[0]["content"] == "A city wakes up"
    assert "streetlights blink twice" in sections[1]["content"]
    assert sections[2]["content"] == "Hold on, hold on"
    assert all(section["id"] for section in sections)
    assert all(section["instructions"] == "" for section in sections)


def test_parse_sectioned_lyrics_falls_back_to_single_verse():
    sections = parse_sectioned_lyrics("Just one line\nand another line")

    assert len(sections) == 1
    assert sections[0]["type"] == "verse"
    assert sections[0]["label"] == "Verse 1"
    assert sections[0]["content"] == "Just one line\nand another line"
    assert "without section markers" in sections[0]["instructions"]


def test_parse_sectioned_lyrics_keeps_bracketed_production_notes_in_body():
    draft = "[Verse 1]\nFirst line\n[whispered]\nSecond line\n\n[Chorus]\nLoud line"
    sections = parse_sectioned_lyrics(draft)

    assert len(sections) == 2
    assert "[whispered]" in sections[0]["content"]
    assert sections[0]["content"].endswith("Second line")
    assert sections[1]["type"] == "chorus"


def test_parse_sectioned_lyrics_keeps_unknown_leading_bracket_as_body():
    sections = parse_sectioned_lyrics("[guitar riff]\nla la")
    assert len(sections) == 1
    assert sections[0]["type"] == "verse"
    assert sections[0]["content"] == "[guitar riff]\nla la"


def test_section_type_prefers_explicit_type_then_label_tokens():
    assert section_type("chorus", "Whatever") == "chorus"
    assert section_type("", "Pre-Chorus") == "pre-chorus"
    assert section_type("", "Refrão final") == "verse"  # Portuguese labels are mapped by the LLM parser
    assert section_type("", "Guitar solo") == "verse"
    assert section_type("unknown", "Bridge") == "bridge"


def test_lyrics_section_and_plan_models_normalise_input():
    section = LyricsSection(type=" CHORUS ", label="  ", content="line")
    assert section.type == "chorus"
    assert section.label == "Section"

    plan = LyricsPlanItem(type="chorus", label="", line_count=8)
    assert plan.type == "chorus"
    assert plan.label == "Chorus"

    with pytest.raises(ValidationError):
        LyricsPlanItem(line_count=0)


def test_lyrics_draft_request_requires_a_brief_and_parses_structure_strings():
    with pytest.raises(ValidationError):
        LyricsDraftRequest()

    request = LyricsDraftRequest(theme="Lisbon at dawn", structure=["Intro", "Verse 1"])
    assert [item.type for item in request.structure] == ["intro", "verse"]
    assert [item.label for item in request.structure] == ["Intro", "Verse 1"]


def test_build_prompt_includes_structure_and_instrumental_note():
    request = LyricsDraftRequest(
        theme="A quiet harbour",
        genre="Fado",
        mood="Melancholic",
        vocal_type="instrumental",
        language="pt-PT",
    )
    system_prompt, user_prompt = build_prompt(request)

    assert "instrumental track" in user_prompt.lower()
    assert "Fado" in user_prompt
    assert "A quiet harbour" in user_prompt
    for label, _lines in DEFAULT_STRUCTURE:
        assert f"[{label}]" in user_prompt


def test_format_lyrics_skips_empty_sections_and_handles_instrumentals():
    song = {"vocal_type": "instrumental"}
    assert prompts.format_lyrics(song, [{"label": "Verse", "content": "ignored"}]) == "[Instrumental]"

    song = {"vocal_type": "female"}
    sections = [
        {"label": "Verse 1", "content": "one\ntwo", "instructions": ""},
        {"label": "Empty", "content": "", "instructions": ""},
        {"label": "", "type": "chorus", "content": "three"},
    ]
    formatted = prompts.format_lyrics(song, sections)
    assert formatted == "[Verse 1]\none\ntwo\n\n[Chorus]\nthree"
    assert "Empty" not in formatted


def test_generation_request_requires_source_for_audio_editing_modes():
    with pytest.raises(ValidationError):
        GenerateRequest(mode="cover")
    with pytest.raises(ValidationError):
        GenerateRequest(mode="repaint", source_path="music/source.wav")

    cover = GenerateRequest(mode="cover", source_path="music/source.wav", cover_strength=0.4)
    assert cover.cover_strength == 0.4

    repaint = GenerateRequest(
        mode="repaint",
        source_path="music/source.wav",
        start_seconds=2,
        end_seconds=8,
    )
    assert repaint.start_seconds == 2

    with pytest.raises(ValidationError):
        GenerateRequest(mode="repaint", source_path="music/source.wav", start_seconds=8, end_seconds=2)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"song_id": "s", "format": "mp3"}, ("mp3", "audio")),
        ({"song_id": "s", "audio_format": "WAV16"}, ("wav", "audio")),
        ({"song_id": "s", "format": "zip"}, ("wav", "zip")),
        ({"song_id": "s", "format": "wav", "package": True}, ("wav", "zip")),
        ({"song_id": "s", "format": "wav", "mode": "project"}, ("wav", "project")),
        ({"project_id": "p", "format": "wav"}, ("wav", "project")),
    ],
)
def test_export_request_resolves_format_and_kind(payload, expected):
    assert ExportRequest(**payload).resolved() == expected


def test_export_request_rejects_unknown_format():
    with pytest.raises(ValidationError):
        ExportRequest(song_id="s", format="nonsense")
