"""Unit tests for the shared storage and subtitle helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from openstudio_common import storage
from openstudio_common.srt import (
    build_srt,
    build_vtt,
    normalize_cues,
    parse_srt,
    parse_timestamp,
)


def test_path_traversal_is_rejected(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(storage, "FILES_ROOT", tmp_path)
    assert storage.resolve_path("music", "song.wav") == (tmp_path / "music" / "song.wav").resolve()
    with pytest.raises(ValueError):
        storage.resolve_path("../../etc/passwd")
    with pytest.raises(ValueError):
        storage.resolve_path("/etc/passwd")


def test_file_info_and_listing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(storage, "FILES_ROOT", tmp_path)
    (tmp_path / "music").mkdir()
    sample = tmp_path / "music" / "take.wav"
    sample.write_bytes(b"RIFF....WAVE")
    info = storage.file_info(sample)
    assert info["path"] == "music/take.wav"
    assert info["kind"] == "audio"
    assert info["size"] == 12
    items = storage.list_directory("music")
    assert items[0]["name"] == "take.wav"


def test_srt_roundtrip():
    text = "1\n00:00:00,000 --> 00:00:02,500\nA cidade fecha os olhos\n\n2\n00:00:02,500 --> 00:00:05,500\nEu conto os passos\n"
    cues = parse_srt(text)
    assert len(cues) == 2
    assert cues[0].start == 0
    assert cues[1].end == 5.5
    rebuilt = build_srt(cues)
    assert "00:00:02,500 --> 00:00:05,500" in rebuilt
    vtt = build_vtt(cues)
    assert vtt.startswith("WEBVTT")
    assert "00:00:02.500 --> 00:00:05.500" in vtt


def test_timestamp_and_normalization():
    assert parse_timestamp("01:02:03,004") == 3723.004
    cues = normalize_cues(
        [
            {"start": 0, "end": 4, "text": "one"},
            {"start": 1, "end": 5, "text": "two"},
        ]
    )
    assert cues[0]["end"] <= cues[1]["start"]


def test_file_naming():
    assert storage.sanitize_name("../../evil name?.wav") == "evil name_.wav"
    assert storage.kind_of("x.mp3") == "audio"
    assert storage.kind_of("x.srt") == "subtitle"
