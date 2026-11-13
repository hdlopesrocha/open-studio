"""Tests for the persistent local chat service."""

from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient


def _load_chat(tmp_path, monkeypatch):
    for name in list(sys.modules):
        if name == "services.chat.main":
            del sys.modules[name]
    monkeypatch.setenv("CHAT_DB_PATH", str(tmp_path / "chat.db"))
    module = importlib.import_module("services.chat.main")
    return module


def _headers(module):
    from openstudio_common import INTERNAL_TOKEN

    return {"X-Internal-Token": INTERNAL_TOKEN}


def test_chat_session_and_message_flow(tmp_path, monkeypatch):
    module = _load_chat(tmp_path, monkeypatch)

    recorded: list[dict] = []

    async def fake_llm(session, messages, payload):
        assert messages[-1]["role"] == "user"
        return {"content": f"reply to: {messages[-1]['content']}", "model": "test-model", "usage": {}}

    async def fake_record(**kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr(module, "_call_llm", fake_llm)
    monkeypatch.setattr(module, "_record_chat_job", fake_record)
    client = TestClient(module.app)
    headers = _headers(module)

    created = client.post(
        "/api/chat/sessions",
        headers=headers,
        json={"title": "Studio notes", "model": "test-model"},
    )
    assert created.status_code in {200, 201}
    session = created.json()
    session_id = session["id"]
    assert session["title"] == "Studio notes"

    listed = client.get("/api/chat/sessions", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    reply = client.post(
        f"/api/chat/sessions/{session_id}/messages",
        headers=headers,
        json={"content": "How do I make a DJ mix?"},
    )
    assert reply.status_code in {200, 201}
    body = reply.json()
    assert body["assistant_message"]["content"].startswith("reply to:")
    assert body["session"]["message_count"] == 2
    assert recorded and recorded[0]["prompt"] == "How do I make a DJ mix?"

    messages = client.get(f"/api/chat/sessions/{session_id}/messages", headers=headers)
    assert messages.status_code == 200
    assert [item["role"] for item in messages.json()["items"]] == ["user", "assistant"]

    reverted = client.post(
        f"/api/chat/sessions/{session_id}/messages/{body['user_message']['id']}/revert",
        headers=headers,
    )
    assert reverted.status_code == 200
    assert reverted.json()["deleted"] == 2
    assert reverted.json()["messages"] == []

    updated = client.patch(
        f"/api/chat/sessions/{session_id}",
        headers=headers,
        json={"title": "Renamed"},
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Renamed"

    deleted = client.delete(f"/api/chat/sessions/{session_id}", headers=headers)
    assert deleted.status_code == 200
    assert client.get("/api/chat/sessions", headers=headers).json()["total"] == 0


def test_chat_llm_failure_and_missing_session(tmp_path, monkeypatch):
    module = _load_chat(tmp_path, monkeypatch)

    async def failed_llm(session, messages, payload):
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="model is offline")

    monkeypatch.setattr(module, "_call_llm", failed_llm)
    client = TestClient(module.app)
    headers = _headers(module)
    session = client.post("/api/chat/sessions", headers=headers, json={}).json()

    response = client.post(
        f"/api/chat/sessions/{session['id']}/messages",
        headers=headers,
        json={"content": "hello"},
    )
    assert response.status_code == 503
    assert "offline" in response.json()["detail"]

    missing = client.get("/api/chat/sessions/nope", headers=headers)
    assert missing.status_code == 404


def test_chat_favorite_model_defaults_new_sessions(tmp_path, monkeypatch):
    module = _load_chat(tmp_path, monkeypatch)
    client = TestClient(module.app)
    headers = _headers(module)

    saved = client.put(
        "/api/chat/preferences",
        headers=headers,
        json={"favorite_model": "qwen3:4b"},
    )
    assert saved.status_code == 200
    assert saved.json()["favorite_model"] == "qwen3:4b"
    assert client.get("/api/chat/preferences", headers=headers).json()["favorite_model"] == "qwen3:4b"

    first = client.post("/api/chat/sessions", headers=headers, json={"title": "First"})
    assert first.status_code == 201
    assert first.json()["model"] == "qwen3:4b"

    explicit = client.post(
        "/api/chat/sessions",
        headers=headers,
        json={"title": "Explicit", "model": "custom-model"},
    )
    assert explicit.status_code == 201
    assert explicit.json()["model"] == "custom-model"

    cleared = client.put(
        "/api/chat/preferences",
        headers=headers,
        json={"favorite_model": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["favorite_model"] == ""

    fallback = client.post("/api/chat/sessions", headers=headers, json={"title": "Fallback"})
    assert fallback.status_code == 201
    assert fallback.json()["model"] == module.DEFAULT_MODEL


def test_chat_job_history_uses_a_durable_outbox(tmp_path, monkeypatch):
    module = _load_chat(tmp_path, monkeypatch)
    payload = {"component": "chat", "action": "prompt", "title": "Chat · test"}
    module.STORE.queue_job_history(payload)
    pending = module.STORE.pending_job_history()
    assert len(pending) == 1
    assert pending[0]["payload"] == payload
    module.STORE.delete_job_history(pending[0]["id"])
    assert module.STORE.pending_job_history() == []


def test_chat_can_generate_and_attach_speech(tmp_path, monkeypatch):
    module = _load_chat(tmp_path, monkeypatch)
    client = TestClient(module.app)
    headers = _headers(module)
    session = client.post("/api/chat/sessions", headers=headers, json={"title": "Voice"}).json()
    assistant = module.STORE.append_message(
        session["id"],
        "assistant",
        "Here is **the** [plan](https://example.test).\n\n```python\nprint('x')\n```",
    )
    seen: dict[str, object] = {}

    async def fake_start_speech(text, payload):
        seen["text"] = text
        seen["engine"] = payload.engine
        seen["format"] = payload.format
        return {"id": "voice-test-job", "status": "queued"}

    monkeypatch.setattr(module, "_start_speech_job", fake_start_speech)
    started = client.post(
        f"/api/chat/sessions/{session['id']}/messages/{assistant['id']}/speech",
        headers=headers,
        json={"engine": "auto", "format": "mp3"},
    )
    assert started.status_code == 202
    assert started.json()["id"] == "voice-test-job"
    assert started.json()["message_id"] == assistant["id"]
    assert "**" not in str(seen["text"])
    assert "Code block omitted." in str(seen["text"])
    assert seen["format"] == "mp3"

    speech = {
        "path": "voice/outputs/test/take.mp3",
        "job_id": "voice-test-job",
        "format": "mp3",
        "duration_seconds": 1.4,
        "voice": "Auto voice",
        "generated_at": "2026-01-01T00:00:00Z",
    }
    attached = client.patch(
        f"/api/chat/sessions/{session['id']}/messages/{assistant['id']}/speech",
        headers=headers,
        json=speech,
    )
    assert attached.status_code == 200
    assert attached.json()["metadata"]["speech"]["path"] == speech["path"]

    messages = client.get(
        f"/api/chat/sessions/{session['id']}/messages",
        headers=headers,
    ).json()["items"]
    assert messages[-1]["metadata"]["speech"]["job_id"] == "voice-test-job"

    unsafe = client.patch(
        f"/api/chat/sessions/{session['id']}/messages/{assistant['id']}/speech",
        headers=headers,
        json={**speech, "path": "chat/uploads/not-audio.mp3"},
    )
    assert unsafe.status_code == 422

    user = module.STORE.append_message(session["id"], "user", "Speak this")
    rejected = client.post(
        f"/api/chat/sessions/{session['id']}/messages/{user['id']}/speech",
        headers=headers,
        json={},
    )
    assert rejected.status_code == 400


def test_chat_speech_falls_back_to_an_installed_piper_voice(tmp_path, monkeypatch):
    module = _load_chat(tmp_path, monkeypatch)

    async def fake_catalog():
        return {
            "engines": [
                {"id": "omnivoice", "available": False},
                {"id": "piper", "available": True},
            ],
            "piper_voices": [
                {"id": "pt-PT-dii", "language": "pt-PT", "available": True},
                {"id": "en-US-lessac", "language": "en-US", "available": True},
            ],
        }

    monkeypatch.setattr(module, "_voice_catalog", fake_catalog)
    import asyncio

    engine, voice = asyncio.run(module._resolve_speech_engine(module.SpeechCreate()))
    assert engine == "piper"
    assert voice == "en-US-lessac"

    engine, voice = asyncio.run(
        module._resolve_speech_engine(module.SpeechCreate(language="pt-BR"))
    )
    assert engine == "piper"
    assert voice == "pt-PT-dii"

    async def ready_catalog():
        return {
            "engines": [
                {
                    "id": "omnivoice",
                    "available": True,
                    "status": "ok",
                    "model_loaded": True,
                    "device": "cuda",
                },
                {"id": "piper", "available": True},
            ],
            "piper_voices": [{"id": "en-US-lessac", "language": "en-US", "available": True}],
        }

    monkeypatch.setattr(module, "_voice_catalog", ready_catalog)
    engine, voice = asyncio.run(module._resolve_speech_engine(module.SpeechCreate()))
    assert engine == "omnivoice"
    assert voice is None

    async def cpu_catalog():
        return {
            "engines": [
                {
                    "id": "omnivoice",
                    "available": True,
                    "status": "ok",
                    "model_loaded": True,
                    "device": "cpu",
                },
                {"id": "piper", "available": True},
            ],
            "piper_voices": [{"id": "en-US-lessac", "language": "en-US", "available": True}],
        }

    monkeypatch.setattr(module, "_voice_catalog", cpu_catalog)
    engine, voice = asyncio.run(module._resolve_speech_engine(module.SpeechCreate()))
    assert engine == "piper"
    assert voice == "en-US-lessac"


def test_chat_pending_jobs_exposes_outbox_entries(tmp_path, monkeypatch):
    module = _load_chat(tmp_path, monkeypatch)
    payload = {
        "id": "chat-test",
        "component": "chat",
        "action": "prompt",
        "title": "Chat · pending",
        "params": {"chat_prompt": "pending prompt"},
        "result": {"message": "pending answer", "session_id": "s1"},
    }
    module.STORE.queue_job_history(payload)
    client = TestClient(module.app)
    response = client.get("/api/chat/pending-jobs", headers=_headers(module))
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == "chat-test"
    assert items[0]["pending"] is True
    assert items[0]["params"]["chat_prompt"] == "pending prompt"


def test_chat_context_describes_open_studio(tmp_path, monkeypatch):
    module = _load_chat(tmp_path, monkeypatch)
    client = TestClient(module.app)
    response = client.get("/api/chat/context", headers=_headers(module))
    assert response.status_code == 200
    payload = response.json()
    assert "Open Studio" in payload["app"]
    assert "Settings" in payload["context"]
    assert "/music" in payload["pages"]
    assert "/api/music/projects" in payload["context"]
    assert "COMPLETE EXTERNAL API REFERENCE" in payload["context"]
