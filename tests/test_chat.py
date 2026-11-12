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

    async def fake_llm(session, messages, payload):
        assert messages[-1]["role"] == "user"
        return {"content": f"reply to: {messages[-1]['content']}", "model": "test-model", "usage": {}}

    monkeypatch.setattr(module, "_call_llm", fake_llm)
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

    messages = client.get(f"/api/chat/sessions/{session_id}/messages", headers=headers)
    assert messages.status_code == 200
    assert [item["role"] for item in messages.json()["items"]] == ["user", "assistant"]

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


def test_chat_context_describes_open_studio(tmp_path, monkeypatch):
    module = _load_chat(tmp_path, monkeypatch)
    client = TestClient(module.app)
    response = client.get("/api/chat/context", headers=_headers(module))
    assert response.status_code == 200
    payload = response.json()
    assert "Open Studio" in payload["app"]
    assert "Settings" in payload["context"]
    assert "/music" in payload["pages"]
