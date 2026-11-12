"""Music HTTP API tests with the engine and job hub mocked out."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from services.music import main as music_main


def _run(coro):
    return asyncio.run(coro)


def test_project_song_and_lyrics_crud():
    with TestClient(music_main.app) as client:
        created = client.post(
            "/api/music/projects",
            json={"title": "Harbour Sessions", "artist": "Ana", "description": "demos"},
        )
        assert created.status_code == 201
        project = created.json()
        project_id = project["id"]
        assert project["title"] == "Harbour Sessions"
        assert project["song_count"] == 0

        listed = client.get("/api/music/projects", params={"q": "Harbour"})
        assert listed.status_code == 200
        assert any(item["id"] == project_id for item in listed.json()["items"])

        patched = client.patch(f"/api/music/projects/{project_id}", json={"title": "Harbour Tapes"})
        assert patched.status_code == 200
        assert patched.json()["title"] == "Harbour Tapes"

        song_response = client.post(
            f"/api/music/projects/{project_id}/songs",
            json={"title": "Night Ferry", "language": "pt-PT", "bpm": 104, "energy": 61},
        )
        assert song_response.status_code == 201
        song = song_response.json()
        song_id = song["id"]
        assert song["project_id"] == project_id
        assert song["bpm"] == 104
        assert song["project"]["title"] == "Harbour Tapes"
        assert [section["label"] for section in song["lyrics"]["sections"]] == ["Verse 1", "Chorus"]

        detail = client.get(f"/api/music/projects/{project_id}")
        assert detail.status_code == 200
        assert detail.json()["song_count"] == 1
        assert detail.json()["songs"][0]["id"] == song_id

        updated = client.patch(
            f"/api/music/songs/{song_id}",
            json={"title": "Night Ferry (edit)", "mood": "Hopeful", "bpm": 108},
        )
        assert updated.status_code == 200
        assert updated.json()["title"] == "Night Ferry (edit)"
        assert updated.json()["mood"] == "Hopeful"

        lyrics = client.put(
            f"/api/music/songs/{song_id}/lyrics",
            json={
                "sections": [
                    {"type": "", "label": "Intro", "content": "One breath"},
                    {"type": "chorus", "label": "Refrão", "content": "Hold the line"},
                    {"type": "guitar solo", "label": "Solo", "content": ""},
                ]
            },
        )
        assert lyrics.status_code == 200
        sections = lyrics.json()["sections"]
        assert [section["type"] for section in sections] == ["intro", "chorus", "verse"]
        assert sections[1]["content"] == "Hold the line"

        fetched_lyrics = client.get(f"/api/music/songs/{song_id}/lyrics")
        assert fetched_lyrics.json()["sections"] == sections

        duplicate = client.post(f"/api/music/songs/{song_id}/duplicate")
        assert duplicate.status_code == 201
        copy = duplicate.json()
        assert copy["title"] == "Night Ferry (edit) (copy)"
        assert [section["content"] for section in copy["lyrics"]["sections"]] == [
            "One breath",
            "Hold the line",
            "",
        ]

        assert client.delete(f"/api/music/songs/{copy['id']}").status_code == 204
        assert client.get(f"/api/music/songs/{copy['id']}").status_code == 404
        assert client.delete(f"/api/music/projects/{project_id}").status_code == 204
        assert client.get(f"/api/music/projects/{project_id}").status_code == 404


def test_generation_submits_job_and_updates_song(monkeypatch):
    submitted: list[tuple[str, str, dict]] = []

    async def fake_prepare(params):
        return {"song": {"id": params.song_id}, "base_payload": {}}

    async def fake_submit(action, title, params):
        submitted.append((action, title, params))
        return {"id": "job_test", "component": "music", "action": action}

    monkeypatch.setattr(music_main, "prepare_generation", fake_prepare)
    monkeypatch.setattr(music_main, "submit_job", fake_submit)

    with TestClient(music_main.app) as client:
        project = client.post("/api/music/projects", json={"title": "Engine Test"}).json()
        song = client.post(
            f"/api/music/projects/{project['id']}/songs",
            json={"title": "Mocked Render", "duration": 30},
        ).json()

        response = client.post(
            f"/api/music/songs/{song['id']}/generate",
            json={"mode": "full", "variations": 2, "seed": 7, "audio_format": "wav24"},
        )
        assert response.status_code == 202
        assert response.json()["id"] == "job_test"
        assert submitted[0][0] == "generate"
        assert submitted[0][1].startswith("Mocked Render")
        assert submitted[0][2]["song_id"] == song["id"]
        assert submitted[0][2]["seed"] == 7

        refreshed = client.get(f"/api/music/songs/{song['id']}").json()
        assert refreshed["provider"] == "ace_step"
        assert refreshed["model_id"] == "acestep-v15-turbo"

        invalid = client.post(
            f"/api/music/songs/{song['id']}/generate",
            json={"mode": "cover"},
        )
        assert invalid.status_code == 422
        assert "source_path" in str(invalid.json()["detail"])


def test_lyrics_draft_submits_job_with_song_context(monkeypatch):
    submitted: list[tuple[str, str, dict]] = []

    async def fake_available():
        return None

    async def fake_submit(action, title, params):
        submitted.append((action, title, params))
        return {"id": "job_lyrics", "component": "music", "action": action}

    monkeypatch.setattr(music_main.lyrics, "ensure_available", fake_available)
    monkeypatch.setattr(music_main, "submit_job", fake_submit)

    with TestClient(music_main.app) as client:
        project = client.post("/api/music/projects", json={"title": "Lyrics Test"}).json()
        song = client.post(
            f"/api/music/projects/{project['id']}/songs",
            json={
                "title": "Draft Me",
                "genre": "Fado",
                "style": "sparse guitar",
                "instructions": "a harbour at night",
            },
        ).json()

        response = client.post(
            "/api/music/lyrics/draft",
            json={"song_id": song["id"], "structure": ["Verse 1", "Chorus"]},
        )
        assert response.status_code == 202
        assert response.json()["id"] == "job_lyrics"
        action, title, params = submitted[0]
        assert action == "lyrics_draft"
        assert "Draft Me" in title
        assert params["song_id"] == song["id"]
        assert params["theme"] == "a harbour at night"
        assert params["genre"] == "Fado"
        assert params["structure"][0]["type"] == "verse"


def test_export_validation_without_ffmpeg(monkeypatch):
    monkeypatch.setattr(music_main.shutil, "which", lambda _name: None)
    with TestClient(music_main.app) as client:
        missing = client.post("/api/music/export", json={})
        assert missing.status_code == 422

        project = client.post("/api/music/projects", json={"title": "Export Test"}).json()
        song = client.post(f"/api/music/projects/{project['id']}/songs", json={}).json()
        response = client.post(
            "/api/music/export",
            json={"song_id": song["id"], "format": "mp3"},
        )
        assert response.status_code == 503
        assert "ffmpeg" in response.json()["detail"].lower()
