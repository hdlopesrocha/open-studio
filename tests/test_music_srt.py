"""Lyric SRT timing and export endpoint tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from openstudio_common import parse_srt
from services.music import main as music_main
from services.music.lyrics import build_lyrics_srt, lyric_section_spans, srt_filename


def test_lyric_section_spans_are_contiguous_and_weighted():
    sections = [
        {"type": "intro", "label": "Intro", "content": "one\n two"},
        {"type": "chorus", "label": "Chorus", "content": "a\nb\nc"},
        {"type": "instrumental", "label": "Solo", "content": ""},
    ]
    spans = lyric_section_spans(sections, 90)
    assert spans[0]["start"] == 0
    assert spans[-1]["end"] == 90
    for previous, current in zip(spans, spans[1:]):
        assert previous["end"] == current["start"]
    assert spans[1]["end"] - spans[1]["start"] > spans[0]["end"] - spans[0]["start"]


def test_build_lyrics_srt_includes_section_labels_and_handles_empty_sections():
    body = build_lyrics_srt(
        [
            {"label": "Verse 1", "type": "verse", "content": "first line\nsecond line"},
            {"label": "Solo", "type": "instrumental", "content": ""},
        ],
        10,
    )
    cues = parse_srt(body)
    assert len(cues) == 3
    assert cues[0].text == "[Verse 1]\nfirst line"
    assert cues[1].text == "second line"
    assert cues[2].text == "[Solo]"
    assert cues[0].start == 0
    assert cues[-1].end == 10
    assert srt_filename("A/B: Song!") == "A-B-Song-lyrics.srt"


def test_music_lyrics_srt_endpoint():
    with TestClient(music_main.app) as client:
        project = client.post("/api/music/projects", json={"title": "SRT Project"}).json()
        song = client.post(
            f"/api/music/projects/{project['id']}/songs",
            json={"title": "SRT Song", "duration": 12},
        ).json()
        lyrics = client.put(
            f"/api/music/songs/{song['id']}/lyrics",
            json={
                "sections": [
                    {"type": "verse", "label": "Verse 1", "content": "line one\nline two"},
                    {"type": "chorus", "label": "Chorus", "content": "sing along"},
                ]
            },
        )
        assert lyrics.status_code == 200
        response = client.get(f"/api/music/songs/{song['id']}/lyrics.srt")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-subrip")
        assert "attachment" in response.headers["content-disposition"]
        cues = parse_srt(response.text)
        assert cues[0].text.startswith("[Verse 1]")
        assert any("[Chorus]" in cue.text for cue in cues)
        assert cues[-1].end == 12

        missing = client.get("/api/music/songs/not-a-song/lyrics.srt")
        assert missing.status_code == 404
