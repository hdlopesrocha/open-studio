"""Local ChatGPT-style conversations with persistent sessions."""

from __future__ import annotations

import json
import logging
import re
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
from .tools import TOOL_GUIDE, attachment_context, execute_tool

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
    attachments: list[str] = Field(default_factory=list, max_length=12)


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


async def _request_llm(messages: list[dict[str, Any]], model: str, *, temperature: float = 0.7, max_tokens: int = 2048) -> dict[str, Any]:
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
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


async def _call_llm(session: dict[str, Any], messages: list[dict[str, Any]], payload: MessageCreate) -> dict[str, Any]:
    model = (payload.model or session.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    return await _request_llm(messages, model, temperature=payload.temperature, max_tokens=payload.max_tokens)

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
    for item in selected:
        content = str(item.get("content") or "")
        attachments = item.get("metadata", {}).get("attachments") if isinstance(item.get("metadata"), dict) else []
        if attachments:
            content += "\n\n" + attachment_context([str(path) for path in attachments])
        messages.append({"role": str(item.get("role") or "user"), "content": content})
    return messages


DETERMINISTIC_ROUTES = {
    "home": "/", "dashboard": "/", "chat": "/chat", "audio": "/music", "music": "/music",
    "dj": "/music?tab=dj-library", "dj library": "/music?tab=dj-library",
    "dj create": "/music?tab=dj-create", "dj mix": "/music?tab=dj-mix",
    "srt": "/music?tab=srt", "subtitles": "/music?tab=srt", "video": "/video",
    "qvac": "/video?tab=qvac", "documents": "/documents", "docs": "/documents",
    "pdf": "/documents?tab=pdf", "summary": "/documents?tab=summary",
    "translate": "/documents?tab=translate", "translation": "/documents?tab=translate",
    "voice": "/voice", "images": "/images", "picture": "/images", "files": "/files",
    "jobs": "/jobs", "settings": "/settings",
}

SERVICE_ALIASES = {
    "chat": "chat", "music": "music", "ace-step": "music-engine", "music engine": "music-engine",
    "dj": "dj", "video": "video", "voice": "voice", "srt": "srt", "subtitles": "srt",
    "images": "imagegen", "imagegen": "imagegen", "docs": "docs", "documents": "docs",
    "translation": "translation", "translate": "translation", "summary": "summary",
    "pdf": "pdf", "ffmpeg": "ffmpeg", "ytdlp": "ytdlp", "yt-dlp": "ytdlp", "qvac": "qvac",
    "llm": "llm", "ollama": "ollama",
}

MODEL_ALIASES = {
    "llama": "llm-llama3.2-3b", "llm": "llm-llama3.2-3b", "ace-step": "music-ace-step",
    "music": "music-ace-step", "whisper": "whisper-large-v3", "large-v3": "whisper-large-v3",
    "translation": "translation-all", "opus": "translation-opus", "nllb": "translation-nllb",
    "summary": "summary-all", "piper": "piper-voices", "omnivoice": "omnivoice",
    "qvac": "qvac-sd21", "sd turbo": "image-sd-turbo", "sdxl": "image-sdxl",
}

ACTION_WORDS = re.compile(r"\b(create|generate|make|render|translate|summarize|summarise|transcribe|convert|extract|download|mix|run|install|enable|disable|restart|build|open|go to|take me|navigate|diagnose|fix|error|broken|failed|logs?)\b", re.I)


def _deterministic_actions(message: str) -> list[dict[str, Any]]:
    text = message.lower().strip()
    actions: list[dict[str, Any]] = []
    if re.search(r"\b(go to|open|take me to|navigate to|show me)\b", text):
        for label, path in sorted(DETERMINISTIC_ROUTES.items(), key=lambda item: len(item[0]), reverse=True):
            if label in text:
                actions.append({"tool": "navigate", "args": {"path": path}})
                break
    service_action = re.search(r"\b(enable|disable|restart|build|turn on|turn off|start|stop)\s+(?:the\s+)?([a-z0-9 -]+)", text)
    if service_action:
        verb, raw_name = service_action.group(1), service_action.group(2).strip()
        for alias, service in sorted(SERVICE_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
            if raw_name.startswith(alias):
                action = {"turn on": "enable", "turn off": "disable", "start": "enable", "stop": "disable"}.get(verb, verb)
                actions.append({"tool": "service_action", "args": {"name": service, "action": action}})
                break
    if "logs" in text:
        for alias, service in SERVICE_ALIASES.items():
            if alias in text:
                actions.append({"tool": "service_logs", "args": {"name": service, "lines": 160}})
                break
    if re.search(r"\b(install|download|recheck|re-check|verify)\b", text):
        for alias, model_id in MODEL_ALIASES.items():
            if alias in text:
                actions.append({"tool": "recheck_model" if re.search(r"recheck|re-check|verify", text) else "model_install", "args": {"model_id": model_id}})
                break
    if re.search(r"\b(diagnose|diagnostic|fix|error|broken|not working|failed|why.*(working|failing))\b", text):
        actions.append({"tool": "diagnose", "args": {}})
    if re.search(r"\b(opencode|open code|coding agent)\b", text):
        actions.append({"tool": "opencode_prompt", "args": {"problem": message}})
    return actions


async def _llm_plan(session: dict[str, Any], message: str, attachments: list[str], model: str) -> list[dict[str, Any]]:
    if not ACTION_WORDS.search(message):
        return []
    context = attachment_context(attachments)
    prompt = (
        "You are the Open Studio action planner. Decide whether the user is asking you to perform an operation. "
        "Return a JSON object only, with an actions array. If no operation is needed, return {\"actions\":[]}. "
        "Use only the tools below and do not invent API paths.\n\n" + TOOL_GUIDE +
        "\nUseful REST examples: POST /api/images/generate {provider,prompt,width,height}; "
        "POST /api/translate/translate {text,source_language,target_language}; "
        "POST /api/summary/summarize {text,length,language}; POST /api/voice/tts {text,engine,voice}; "
        "POST /api/srt/align {audio_path,lyrics}; POST /api/ffmpeg/run {operation,input_path,options}; "
        "POST /api/jobs {component,action,title,params}. "
        "Never disable core services or delete files.\n\n"
        f"User request:\n{message}\n\n{context}"
    )
    result = await _request_llm(
        [{"role": "system", "content": APP_CONTEXT + "\n\n" + prompt}, {"role": "user", "content": message}],
        model,
        temperature=0.1,
        max_tokens=1000,
    )
    raw = result["content"].strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        payload = json.loads(raw[start:end + 1])
        actions = payload.get("actions") if isinstance(payload, dict) else []
        if not isinstance(actions, list):
            return []
        allowed = {"navigate", "list_services", "service_action", "service_logs", "list_models", "model_install", "recheck_model", "list_jobs", "job_action", "list_files", "read_file", "write_file", "api_request", "diagnose", "opencode_prompt"}
        return [
            {"tool": str(item.get("tool")), "args": item.get("args") if isinstance(item.get("args"), dict) else {}}
            for item in actions[:4]
            if isinstance(item, dict) and str(item.get("tool")) in allowed
        ]
    except (ValueError, TypeError, json.JSONDecodeError):
        return []


async def _run_agent(session: dict[str, Any], message: str, attachments: list[str], model: str) -> tuple[list[dict[str, Any]], str | None]:
    actions = _deterministic_actions(message)
    if not actions:
        actions = await _llm_plan(session, message, attachments, model)
    results: list[dict[str, Any]] = []
    for action in actions[:4]:
        result = await execute_tool(action["tool"], action.get("args") or {})
        results.append({"tool": action["tool"], "args": action.get("args") or {}, **result})
    if not results:
        return [], None
    summary = json.dumps(results, ensure_ascii=False)[:9000]
    try:
        answer = await _request_llm(
            [
                {"role": "system", "content": APP_CONTEXT},
                {"role": "user", "content": f"User request: {message}\n\nAgent tool results:\n{summary}\n\nExplain what was done, what failed, and give the next exact step. Mention links returned by navigate tools."},
            ],
            model,
            temperature=0.2,
            max_tokens=1200,
        )
        text = answer["content"]
    except HTTPException:
        text = "Agent actions completed.\n" + "\n".join(f"- {item['tool']}: {'ok' if item.get('ok') else item.get('error', 'failed')}" for item in results)
    return results, text


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
    attachments = [str(path).strip() for path in payload.attachments if str(path).strip()]
    attachments = [path for path in attachments if not path.startswith("/") and ".." not in Path(path).parts]
    user_message = STORE.append_message(
        session_id,
        "user",
        payload.content.strip(),
        metadata={"attachments": attachments},
    )
    model = (payload.model or session.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    actions, agent_text = await _run_agent(session, payload.content, attachments, model)
    if agent_text is not None:
        assistant_content = agent_text
        usage: dict[str, Any] = {}
        assistant_model = model
    else:
        history = STORE.list_messages(session_id)
        reply = await _call_llm(session, _context(session, history), payload)
        assistant_content = reply["content"]
        usage = reply.get("usage") or {}
        assistant_model = reply["model"]
    assistant_message = STORE.append_message(
        session_id,
        "assistant",
        assistant_content,
        metadata={"model": assistant_model, "usage": usage, "actions": actions},
    )
    return {
        "user_message": user_message,
        "assistant_message": assistant_message,
        "messages": [user_message, assistant_message],
        "session": STORE.get_session(session_id),
        "model": assistant_model,
        "actions": actions,
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
