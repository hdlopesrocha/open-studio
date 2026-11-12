"""Local ChatGPT-style conversations with persistent sessions."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from openstudio_common import INTERNAL_TOKEN, STATE_ROOT, create_service_app, env, service_url, utc_now

from .context import APP_CONTEXT

log = logging.getLogger("chat")

VERSION = "1.0.0"
LLM_URL = env("LLM_URL", service_url("llm")).rstrip("/")
DEFAULT_MODEL = env("CHAT_MODEL", env("LLM_MODEL", "llama3.2:3b"))
DEFAULT_SYSTEM_PROMPT = env(
    "CHAT_SYSTEM_PROMPT",
    "You are Open Studio's local AI assistant. Be clear, practical and concise. "
    "Use the application context below to help the user navigate and operate this studio.",
).strip() + "\n\n" + APP_CONTEXT
CONTEXT_MESSAGES = int(env("CHAT_CONTEXT_MESSAGES", "40"))
CONTEXT_CHARS = int(env("CHAT_CONTEXT_CHARS", "24000"))
DB_PATH = Path(env("CHAT_DB_PATH", str(STATE_ROOT / "chat.db")))

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _headers() -> dict[str, str]:
    return {"Content-Type": "application/json", "X-Internal-Token": INTERNAL_TOKEN, "X-Service": "chat"}


def _now() -> str:
    return utc_now()


class SessionCreate(BaseModel):
    title: str = Field(default="New chat", max_length=160)
    system_prompt: str = Field(default=DEFAULT_SYSTEM_PROMPT, max_length=16000)
    model: str = Field(default=DEFAULT_MODEL, max_length=200)


class SessionUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    system_prompt: str | None = Field(default=None, max_length=16000)
    model: str | None = Field(default=None, max_length=200)


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=200_000)
    model: str | None = Field(default=None, max_length=200)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=1, le=8192)


class ChatStore:
    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                system_prompt TEXT NOT NULL,
                model TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chat_messages_session
                ON messages(session_id, created_at);
            """
        )
        self._conn.commit()

    @staticmethod
    def _session(row: sqlite3.Row, *, message_count: int = 0, last_message: str = "") -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "system_prompt": row["system_prompt"],
            "model": row["model"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "message_count": message_count,
            "last_message": last_message,
        }

    @staticmethod
    def _message(row: sqlite3.Row) -> dict[str, Any]:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (TypeError, ValueError):
            metadata = {}
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "role": row["role"],
            "content": row["content"],
            "metadata": metadata,
            "created_at": row["created_at"],
        }

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC").fetchall()
            result = []
            for row in rows:
                count = self._conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE session_id=?", (row["id"],)
                ).fetchone()[0]
                last = self._conn.execute(
                    "SELECT content FROM messages WHERE session_id=? ORDER BY created_at DESC LIMIT 1",
                    (row["id"],),
                ).fetchone()
                result.append(self._session(row, message_count=count, last_message=(last["content"] if last else "")[:180]))
            return result

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            if row is None:
                return None
            count = self._conn.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id=?", (session_id,)
            ).fetchone()[0]
            last = self._conn.execute(
                "SELECT content FROM messages WHERE session_id=? ORDER BY created_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            return self._session(row, message_count=count, last_message=(last["content"] if last else "")[:180])

    def create_session(self, payload: SessionCreate) -> dict[str, Any]:
        session_id = uuid.uuid4().hex
        now = _now()
        title = (payload.title or "New chat").strip() or "New chat"
        system_prompt = (payload.system_prompt or DEFAULT_SYSTEM_PROMPT).strip()
        model = (payload.model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions(id,title,system_prompt,model,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (session_id, title, system_prompt, model, now, now),
            )
            self._conn.commit()
        return self.get_session(session_id) or {}

    def update_session(self, session_id: str, payload: SessionUpdate) -> dict[str, Any] | None:
        current = self.get_session(session_id)
        if current is None:
            return None
        values = payload.model_dump(exclude_none=True)
        if not values:
            return current
        title = str(values.get("title") or current["title"]).strip() or current["title"]
        system_prompt = str(values.get("system_prompt") or current["system_prompt"]).strip() or current["system_prompt"]
        model = str(values.get("model") or current["model"]).strip() or current["model"]
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET title=?, system_prompt=?, model=?, updated_at=? WHERE id=?",
                (title, system_prompt, model, _now(), session_id),
            )
            self._conn.commit()
        return self.get_session(session_id)

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
            cursor = self._conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            self._conn.commit()
            return cursor.rowcount > 0

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY created_at, rowid", (session_id,)
            ).fetchall()
            return [self._message(row) for row in rows]

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message_id = uuid.uuid4().hex
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO messages(id,session_id,role,content,metadata_json,created_at) VALUES(?,?,?,?,?,?)",
                (message_id, session_id, role, content, json.dumps(metadata or {}), now),
            )
            self._conn.execute(
                "UPDATE sessions SET updated_at=?, title=CASE WHEN title='New chat' AND ?='user' THEN ? ELSE title END WHERE id=?",
                (now, role, content.strip().replace("\n", " ")[:80], session_id),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        return self._message(row)

    def delete_message(self, session_id: str, message_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM messages WHERE id=? AND session_id=?", (message_id, session_id)
            )
            self._conn.commit()
            return cursor.rowcount > 0


STORE = ChatStore()


async def _llm_models() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=8.0, headers=_headers()) as client:
            response = await client.get(f"{LLM_URL}/api/llm/models")
        if response.status_code < 400:
            data = response.json()
            items = data.get("items") or data.get("models") or []
            return {"items": items, "default": data.get("default") or DEFAULT_MODEL, "reachable": True}
        return {"items": [], "default": DEFAULT_MODEL, "reachable": False, "error": response.text[:500]}
    except Exception as exc:  # noqa: BLE001
        return {"items": [], "default": DEFAULT_MODEL, "reachable": False, "error": str(exc)}


async def _call_llm(session: dict[str, Any], messages: list[dict[str, Any]], payload: MessageCreate) -> dict[str, Any]:
    model = (payload.model or session.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    body = {
        "model": model,
        "messages": messages,
        "temperature": payload.temperature,
        "max_tokens": payload.max_tokens,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=30.0), headers=_headers()) as client:
            response = await client.post(f"{LLM_URL}/api/llm/chat", json=body)
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="The local model timed out. Try a shorter prompt or a smaller model.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"The local LLM bridge is unreachable: {exc}") from exc
    if response.status_code >= 400:
        detail = response.text[:2000]
        try:
            value = response.json().get("detail")
            if isinstance(value, str):
                detail = value
        except (ValueError, TypeError):
            pass
        raise HTTPException(status_code=response.status_code, detail=detail)
    data = response.json()
    choices = data.get("choices") or []
    content = ""
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
        content = str(message.get("content") or "")
    if not content:
        raise HTTPException(status_code=502, detail="The local model returned an empty response.")
    return {"content": content, "model": data.get("model") or model, "usage": data.get("usage") or {}}


def _context(session: dict[str, Any], history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    system_prompt = str(session.get("system_prompt") or "").strip()
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    selected = history[-CONTEXT_MESSAGES:]
    total = sum(len(str(item.get("content") or "")) for item in selected)
    while selected and total > CONTEXT_CHARS:
        removed = selected.pop(0)
        total -= len(str(removed.get("content") or ""))
    messages.extend({"role": item["role"], "content": item["content"]} for item in selected)
    return messages


@router.get("/context")
async def chat_context() -> dict[str, Any]:
    return {
        "app": "Open Studio",
        "context": APP_CONTEXT,
        "pages": ["/chat", "/music", "/video", "/voice", "/images", "/documents", "/ffmpeg", "/ytdlp", "/files", "/jobs", "/settings"],
    }


@router.get("/health")
async def chat_health() -> dict[str, Any]:
    models = await _llm_models()
    return {
        "status": "ok" if models.get("reachable") else "degraded",
        "service": "chat",
        "model": DEFAULT_MODEL,
        "model_installed": bool(models.get("items")),
        "llm_reachable": bool(models.get("reachable")),
        "detail": None if models.get("reachable") else models.get("error") or "LLM bridge is offline.",
    }


@router.get("/models")
async def chat_models() -> dict[str, Any]:
    data = await _llm_models()
    return {**data, "default": data.get("default") or DEFAULT_MODEL}


@router.get("/sessions")
async def list_sessions() -> dict[str, Any]:
    items = STORE.list_sessions()
    return {"items": items, "total": len(items)}


@router.post("/sessions", status_code=201)
async def create_session(payload: SessionCreate) -> dict[str, Any]:
    return STORE.create_session(payload)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    session = STORE.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return {**session, "messages": STORE.list_messages(session_id)}


@router.patch("/sessions/{session_id}")
async def update_session(session_id: str, payload: SessionUpdate) -> dict[str, Any]:
    session = STORE.update_session(session_id, payload)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return session


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, Any]:
    if not STORE.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Chat session not found")
    return {"ok": True, "id": session_id}


@router.get("/sessions/{session_id}/messages")
async def list_messages(session_id: str) -> dict[str, Any]:
    if STORE.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    items = STORE.list_messages(session_id)
    return {"items": items, "total": len(items)}


@router.post("/sessions/{session_id}/messages", status_code=201)
async def send_message(session_id: str, payload: MessageCreate) -> dict[str, Any]:
    session = STORE.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    user_message = STORE.append_message(session_id, "user", payload.content.strip())
    history = STORE.list_messages(session_id)
    reply = await _call_llm(session, _context(session, history), payload)
    assistant_message = STORE.append_message(
        session_id,
        "assistant",
        reply["content"],
        metadata={"model": reply["model"], "usage": reply.get("usage") or {}},
    )
    return {
        "user_message": user_message,
        "assistant_message": assistant_message,
        "messages": [user_message, assistant_message],
        "session": STORE.get_session(session_id),
        "model": reply["model"],
    }


@router.delete("/sessions/{session_id}/messages/{message_id}")
async def delete_message(session_id: str, message_id: str) -> dict[str, Any]:
    if not STORE.delete_message(session_id, message_id):
        raise HTTPException(status_code=404, detail="Message not found")
    return {"ok": True, "id": message_id}


app = create_service_app(
    "chat",
    "Open Studio Chat",
    "Persistent local ChatGPT-style sessions backed by the LLM bridge.",
    version=VERSION,
    extra_routers=[router],
)
