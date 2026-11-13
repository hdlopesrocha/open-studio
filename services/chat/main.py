"""Local ChatGPT-style conversations with persistent sessions."""

from __future__ import annotations

import asyncio
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

from .context import APP_CONTEXT, APP_CORE
from .tools import AGENT_TOOL_GUIDE, TOOL_GUIDE, TOOL_NAMES, attachment_context, execute_tool, repair_tool_failure

log = logging.getLogger("chat")

VERSION = "1.0.0"
LLM_URL = env("LLM_URL", service_url("llm")).rstrip("/")
DEFAULT_MODEL = env("CHAT_MODEL", env("LLM_MODEL", "llama3.2:3b"))
AGENT_MODEL = env("CHAT_AGENT_MODEL", "qwen3:4b")
DEFAULT_SYSTEM_PROMPT = env(
    "CHAT_SYSTEM_PROMPT",
    "You are Open Studio's local AI assistant. Be clear, practical and concise. "
    "Use the application context below to help the user navigate and operate this studio.",
).strip() + "\n\n" + APP_CORE
CONTEXT_MESSAGES = int(env("CHAT_CONTEXT_MESSAGES", "40"))
CONTEXT_CHARS = int(env("CHAT_CONTEXT_CHARS", "24000"))
AGENT_STEPS = int(env("CHAT_AGENT_STEPS", "4"))
AGENT_TOOL_CALLS = int(env("CHAT_AGENT_TOOL_CALLS", "8"))
AGENT_TIMEOUT_SECONDS = float(env("CHAT_AGENT_TIMEOUT_SECONDS", "240"))
AGENT_LLM_TIMEOUT_SECONDS = float(env("CHAT_AGENT_LLM_TIMEOUT_SECONDS", "120"))
AGENT_TOOL_TIMEOUT_SECONDS = float(env("CHAT_AGENT_TOOL_TIMEOUT_SECONDS", "90"))
AGENT_CORE = (
    "Open Studio is a local creative suite. You execute user tasks through tools. "
    "Use api_catalog for exact API paths and api_describe for request schemas. "
    "Never claim success without a successful tool result. /no_think"
)
DB_PATH = Path(env("CHAT_DB_PATH", str(STATE_ROOT / "chat.db")))

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _headers() -> dict[str, str]:
    return {"Content-Type": "application/json", "X-Internal-Token": INTERNAL_TOKEN, "X-Service": "chat"}


def _now() -> str:
    return utc_now()


class SessionCreate(BaseModel):
    title: str = Field(default="New chat", max_length=160)
    system_prompt: str = Field(default=DEFAULT_SYSTEM_PROMPT, max_length=40000)
    model: str = Field(default=DEFAULT_MODEL, max_length=200)


class SessionUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    system_prompt: str | None = Field(default=None, max_length=40000)
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

    def revert_from(self, session_id: str, message_id: str) -> int | None:
        """Delete a message and every message after it, preserving DB order."""
        with self._lock:
            row = self._conn.execute(
                "SELECT rowid FROM messages WHERE id=? AND session_id=?", (message_id, session_id)
            ).fetchone()
            if row is None:
                return None
            cursor = self._conn.execute(
                "DELETE FROM messages WHERE session_id=? AND rowid>=?", (session_id, row["rowid"])
            )
            self._conn.commit()
            return cursor.rowcount


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


async def _request_llm(messages: list[dict[str, Any]], model: str, *, temperature: float = 0.7, max_tokens: int = 2048, json_mode: bool = False, think: bool = False) -> dict[str, Any]:
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
        "think": think,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=30.0), headers=_headers()) as client:
            response = await client.post(f"{LLM_URL}/api/llm/chat", json=body)
            if json_mode and response.status_code == 400:
                body.pop("response_format", None)
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


async def _agent_llm(messages: list[dict[str, Any]], fallback_model: str, *, temperature: float = 0.1, max_tokens: int = 900, json_mode: bool = False) -> dict[str, Any]:
    try:
        return await _request_llm(messages, AGENT_MODEL, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode)
    except HTTPException as exc:
        if exc.status_code == 503 and ("not installed" in str(exc.detail).lower() or "not found" in str(exc.detail).lower()):
            return await _request_llm(messages, fallback_model, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode)
        raise


async def _call_llm(session: dict[str, Any], messages: list[dict[str, Any]], payload: MessageCreate) -> dict[str, Any]:
    model = (payload.model or session.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    return await _request_llm(messages, model, temperature=payload.temperature, max_tokens=payload.max_tokens)

def _context(session: dict[str, Any], history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    system_prompt = str(session.get("system_prompt") or "").strip()
    if "COMPLETE EXTERNAL API REFERENCE" in system_prompt:
        system_prompt = system_prompt.split("COMPLETE EXTERNAL API REFERENCE", 1)[0].strip()
    if "OPEN STUDIO OVERVIEW" not in system_prompt:
        system_prompt = (system_prompt + "\n\n" + APP_CORE).strip()
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

ACTION_WORDS = re.compile(r"\b(create|generate|make|render|translate|summarize|summarise|transcribe|convert|extract|download|upload|mix|run|start|stop|install|enable|disable|restart|build|open|go to|take me|navigate|diagnose|fix|repair|error|broken|failed|logs?|check|list|find|search|inspect|review|read|show|status|progress|delete|rename|move|copy|save|write|edit|update)\b", re.I)
STATUS_TERMS = re.compile(r"\b(status|progress|queue|jobs?|services?|models?|files?|installed|available|logs?|latest|last|offline|online|failed)\b", re.I)


def _deterministic_actions(message: str) -> list[dict[str, Any]]:
    text = message.lower().strip()
    actions: list[dict[str, Any]] = []
    nav = re.search(r"\b(?:go to|open|take me to|navigate to|show me(?:\s+the)?)\s+(.+)$", text)
    if nav:
        target = re.sub(r"^the\s+", "", nav.group(1).strip())
        for label, path in sorted(DETERMINISTIC_ROUTES.items(), key=lambda item: len(item[0]), reverse=True):
            if target.startswith(label) or label in target:
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


QUERY_INTENT = re.compile(r"\b(check|list|inspect|report|show|status|which|what|use tools|inspect|review|tell me)\b", re.I)


def _query_actions(message: str) -> list[dict[str, Any]]:
    text = message.lower()
    if not QUERY_INTENT.search(text):
        return []
    actions: list[dict[str, Any]] = []
    if re.search(r"\bservices?\b|\bonline\b|\boffline\b|\brunning\b", text):
        actions.append({"tool": "list_services", "args": {}})
    if re.search(r"\bjobs?\b|\bqueue\b|\bfailed\b", text):
        actions.append({"tool": "list_jobs", "args": {"status": "failed" if "failed" in text else ""}})
    if re.search(r"\bmodels?\b|\binstalled\b", text):
        actions.append({"tool": "list_models", "args": {}})
    if re.search(r"\bfiles?\b|\bstorage\b", text):
        actions.append({"tool": "list_files", "args": {"path": ""}})
    return actions


def _explicit_tool_actions(message: str) -> list[dict[str, Any]]:
    text = message.lower()
    actions: list[dict[str, Any]] = []
    if re.search(r"\bapi[\s_-]?catalog\b|\b(endpoints?|rest api|openapi)\b", text):
        service = ""
        for alias, name in sorted(SERVICE_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
            if alias in text:
                service = name
                break
        actions.append({"tool": "api_catalog", "args": {"service": service}})
    return actions


INFORMATIONAL = re.compile(
    r"^\s*(how|what|why|where|when|which|who|explain|describe|tell me|walk me through|guide me|show me how|can you explain|do i|does|is there|are there)\b",
    re.I,
)
AGENT_OVERRIDE = re.compile(r"\b(use (the )?(tools?|api)|using the api|for me|do it|actually|perform|execute|now)\b|^\s*/(agent|tools)\b", re.I)
FAILURE_TERMS = re.compile(r"\b(wrong|not working|offline|failing|failed|broken|error|diagnose|fix|repair)\b", re.I)
PLAIN_FINAL = re.compile(r"^\s*(?:final|answer)\s*:\s*", re.I)


def _should_use_agent(message: str, attachments: list[str]) -> bool:
    text = message.strip()
    if text.startswith(("/agent", "/tools")):
        return True
    if _explicit_tool_actions(text):
        return True
    if not ACTION_WORDS.search(text) and not STATUS_TERMS.search(text):
        return False
    if FAILURE_TERMS.search(text) or STATUS_TERMS.search(text) or AGENT_OVERRIDE.search(text):
        return True
    if attachments:
        return True
    if INFORMATIONAL.match(text):
        return False
    return True


def _navigation_requested(message: str) -> bool:
    match = re.search(r"\b(?:go to|open|take me to|navigate to|show me(?:\s+the)?)\s+(.+)$", message, re.I)
    if not match:
        return False
    target = re.sub(r"^the\s+", "", match.group(1).strip().lower())
    return any(target.startswith(label) or label in target for label in DETERMINISTIC_ROUTES)


def _parse_agent_decision(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    payload: Any = None
    first = text.find("{")
    if first >= 0:
        candidates = [text[first:]]
        last = text.rfind("}")
        if last > first:
            candidates.append(text[first:last + 1])
        decoder = json.JSONDecoder()
        for candidate in candidates:
            try:
                payload = json.loads(candidate)
                break
            except (ValueError, TypeError, json.JSONDecodeError):
                try:
                    payload, _ = decoder.raw_decode(candidate)
                    break
                except (ValueError, TypeError, json.JSONDecodeError):
                    continue
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError, json.JSONDecodeError):
            payload = None
    if not isinstance(payload, dict):
        if PLAIN_FINAL.match(text):
            return {"actions": [], "final": PLAIN_FINAL.sub("", text, count=1).strip()}
        return None
    raw_actions = payload.get("actions")
    if raw_actions is None:
        raw_actions = payload.get("tool_calls")
    if raw_actions is None and payload.get("tool"):
        raw_actions = [payload]
    if not isinstance(raw_actions, list):
        raw_actions = []
    actions: list[dict[str, Any]] = []
    for item in raw_actions[:4]:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or item.get("name") or "").strip()
        if tool not in TOOL_NAMES:
            continue
        args = item.get("args") or item.get("arguments") or {}
        actions.append({"tool": tool, "args": args if isinstance(args, dict) else {}})
    final = payload.get("final") or payload.get("answer") or payload.get("response")
    if isinstance(final, str) and final.strip().lower() not in {"", "null", "none"}:
        final = final.strip()
    else:
        final = None
    thought = payload.get("thought") or payload.get("reasoning") or ""
    return {"thought": str(thought)[:800], "actions": actions, "final": final}


LANGUAGE_CODES = {
    "portuguese": "pt", "português": "pt", "english": "en", "inglês": "en",
    "spanish": "es", "espanhol": "es", "french": "fr", "francês": "fr",
    "german": "de", "alemão": "de", "italian": "it", "italiano": "it",
    "dutch": "nl", "japanese": "ja", "japonês": "ja", "chinese": "zh",
    "korean": "ko", "russian": "ru", "arabic": "ar", "hindi": "hi",
}


def _task_text(message: str) -> str:
    if ":" in message:
        candidate = message.split(":", 1)[1].strip()
        if candidate:
            return candidate
    quoted = re.search(r"[\"'“”](.+?)[\"'“”]", message, re.S)
    if quoted:
        return quoted.group(1).strip()
    return message.strip()


def _image_prompt(message: str) -> str:
    prompt = _task_text(message)
    if prompt != message.strip():
        return prompt
    cleaned = re.sub(
        r"^\s*(?:please\s+)?(?:generate|create|make)\s+(?:me\s+)?(?:an?\s+)?(?:image|picture|art(?:work)?)\s*(?:of|showing|with)?\s*",
        "",
        message,
        flags=re.I,
    )
    return cleaned.strip() or message.strip()


def _prepare_action(action: dict[str, Any], message: str) -> dict[str, Any]:
    prepared = {"tool": action.get("tool"), "args": dict(action.get("args") or {})}
    tool = prepared["tool"]
    args = prepared["args"]
    if tool in {"translate_text", "summarize_text"} and not str(args.get("text") or args.get("source_text") or args.get("content") or "").strip():
        args["text"] = _task_text(message)
    if tool == "translate_text":
        target = str(args.get("target_language") or "").strip()
        match = re.search(r"\b(?:to|into)\s+([a-zA-ZÀ-ÿ-]+)", message, re.I)
        if (not target or target.lower() == "auto") and match:
            word = match.group(1).lower()
            args["target_language"] = LANGUAGE_CODES.get(word, match.group(1))
    return prepared


def _action_allowed(action: dict[str, Any], message: str, attachments: list[str]) -> bool:
    tool = str(action.get("tool") or "")
    if tool == "navigate" and not _navigation_requested(message):
        return False
    if tool in {"read_file", "write_file", "list_files"} and not attachments:
        if not re.search(r"\b(files?|path|save|write|read|storage|document)\b", message, re.I):
            return False
    return True


def _compact_results(results: list[dict[str, Any]], limit: int = 9000) -> str:
    text = json.dumps(results, ensure_ascii=False)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... tool output truncated; rely on the visible fields and call another tool if needed."


def _job_from_result(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        if isinstance(data.get("job"), dict):
            return data["job"]
        if data.get("id") and (data.get("status") or data.get("component")):
            return data
    return {}


def _tool_summary(results: list[dict[str, Any]]) -> str:
    successful = {str(item.get("tool")) for item in results if item.get("ok")}
    visible = [item for item in results if item.get("ok") or str(item.get("tool")) not in successful]
    lines: list[str] = []
    for item in visible:
        tool = str(item.get("tool") or "tool")
        if not item.get("ok"):
            lines.append(f"{tool}: failed — {item.get('error') or 'unknown error'}")
            continue
        data = item.get("data")
        args = item.get("args") if isinstance(item.get("args"), dict) else {}
        repair = item.get("repair") if isinstance(item.get("repair"), dict) else {}
        if repair:
            lines.append(f"Auto-repair: {repair.get('service')} {repair.get('action')}; retry {'succeeded' if item.get('ok') else 'failed'}.")
            repair_logs = repair.get("logs") or []
            if repair_logs:
                lines.append("Recent log: " + str(repair_logs[-1])[:500])
            if repair.get("opencode_prompt"):
                lines.append("OpenCode prompt:\n" + str(repair["opencode_prompt"])[:3000])
        if tool == "list_services" and isinstance(data, dict):
            items = data.get("items") or []
            online = [str(entry.get("name")) for entry in items if entry.get("running") or entry.get("online")]
            offline = [str(entry.get("name")) for entry in items if entry.get("enabled") and not (entry.get("running") or entry.get("online"))]
            disabled = [str(entry.get("name")) for entry in items if not entry.get("enabled")]
            lines.append(f"Services checked: {data.get('total', len(items))} total, {len(online)} online, {len(offline)} offline.")
            lines.append("Offline: " + (", ".join(offline) if offline else "none") + ".")
            if disabled:
                lines.append("Disabled: " + ", ".join(disabled) + ".")
        elif tool == "list_models" and isinstance(data, dict):
            items = data.get("items") or []
            installed = sum(1 for entry in items if entry.get("installed"))
            missing = [str(entry.get("id")) for entry in items if not entry.get("installed")]
            lines.append(f"Models checked: {installed} installed of {data.get('total', len(items))}.")
            if missing:
                lines.append("Missing: " + ", ".join(missing) + ".")
        elif tool in {"list_jobs", "job_action", "get_job", "wait_for_job"}:
            job = _job_from_result(data)
            if job:
                message = str(job.get("message") or "").strip()
                lines.append(f"Job {job.get('id')}: {job.get('status')} · {job.get('progress') or 0}%{(' · ' + message) if message else ''}.")
                if job.get("error"):
                    lines.append(f"Error: {job['error']}")
            else:
                jobs = data.get("items") if isinstance(data, dict) else []
                if jobs:
                    lines.append("Jobs: " + ", ".join(f"{job.get('id')} {job.get('status')}" for job in jobs[:12]) + ".")
                else:
                    lines.append(f"{tool}: completed.")
        elif tool in {"generate_image", "transcribe_audio", "synthesize_speech", "music_generate", "start_job", "model_install", "recheck_model"}:
            job = _job_from_result(data)
            if job:
                lines.append(f"{tool}: job {job.get('id')} is {job.get('status')}.")
            elif isinstance(data, dict) and isinstance(data.get("job"), dict):
                job = data["job"]
                lines.append(f"{tool}: job {job.get('id')} is {job.get('status')}.")
            else:
                lines.append(f"{tool}: submitted.")
        elif tool == "translate_text" and isinstance(data, dict):
            lines.append("Translation: " + str(data.get("translated_text") or "")[:1200])
        elif tool == "summarize_text" and isinstance(data, dict):
            lines.append("Summary: " + str(data.get("summary") or data.get("text") or "")[:1200])
        elif tool == "diagnose" and isinstance(data, dict):
            offline = data.get("offline_services") or []
            lines.append("Diagnostics: offline services: " + (", ".join(map(str, offline)) if offline else "none") + ".")
            failed = data.get("failed_jobs") or {}
            job_items = failed.get("items") if isinstance(failed, dict) else []
            if job_items:
                lines.append(f"Failed jobs: {len(job_items)} (latest: {job_items[0].get('id')} {job_items[0].get('title')}).")
        elif tool == "service_action" and isinstance(data, dict):
            lines.append(f"Service action {args.get('name') or ''} {args.get('action') or ''}: completed.".strip())
        elif tool == "service_logs" and isinstance(data, dict):
            raw_lines = str(data.get("lines") or "").splitlines()
            lines.append(f"Logs: {len(raw_lines)} lines" + (f"; last line: {raw_lines[-1][:240]}" if raw_lines else "."))
        elif tool in {"read_file", "write_file"} and isinstance(data, dict):
            content = data.get("content")
            if content:
                lines.append(f"File {data.get('path') or ''}: {str(content)[:1200]}")
            else:
                lines.append(f"File {data.get('path') or data.get('name') or ''}: {tool.split('_')[0]} completed.")
        elif tool == "navigate" and isinstance(data, dict):
            lines.append(f"Navigation: {data.get('label') or data.get('path')}.")
        elif tool == "opencode_prompt" and isinstance(data, dict):
            prompt = str(data.get("prompt") or "")
            lines.append("OpenCode prompt prepared." + (f"\n{prompt[:2000]}" if prompt else ""))
        elif tool == "api_catalog" and isinstance(data, dict):
            endpoints = data.get("endpoints") or []
            lines.append(f"API catalog: {data.get('total', len(endpoints))} endpoints for {data.get('service') or 'services'}.")
            for endpoint in endpoints[:24]:
                lines.append(f"- {endpoint.get('method')} {endpoint.get('path')} — {endpoint.get('summary') or ''}".rstrip(" —"))
        elif tool == "list_files" and isinstance(data, dict):
            entries = data.get("items") or data.get("entries") or []
            lines.append("Files: " + (", ".join(str(entry.get("path") or entry.get("name")) for entry in entries[:20]) if entries else "none") + ".")
        elif tool == "api_request" and isinstance(data, dict):
            lines.append(f"API request completed: {json.dumps(data, ensure_ascii=False)[:1600]}")
        elif tool == "opencode_prompt":
            lines.append("OpenCode prompt prepared.")
        elif isinstance(data, dict) and data.get("translated_text"):
            lines.append("Translation: " + str(data["translated_text"])[:1200])
        elif isinstance(data, dict) and data.get("summary"):
            lines.append("Summary: " + str(data["summary"])[:1200])
        else:
            lines.append(f"{tool}: completed.")
    return "\n".join(dict.fromkeys(line for line in lines if line))


def _grounding_tokens(results: list[dict[str, Any]]) -> set[str]:
    tokens: set[str] = set()
    for item in results:
        data = item.get("data")
        tool = item.get("tool")
        args = item.get("args") if isinstance(item.get("args"), dict) else {}
        if tool == "list_services" and isinstance(data, dict):
            tokens.update(str(entry.get("name")) for entry in data.get("items") or [])
            tokens.update({"service", "services", "online", "offline", "disabled"})
        elif tool == "list_models" and isinstance(data, dict):
            tokens.update(str(entry.get("id")) for entry in data.get("items") or [])
            tokens.update({"model", "models", "installed", "missing"})
        elif tool == "service_action":
            tokens.update({str(args.get("name") or ""), str(args.get("action") or ""), "service"})
        elif isinstance(data, dict):
            job = _job_from_result(data)
            if job:
                tokens.update({str(job.get("id") or ""), str(job.get("status") or ""), "job"})
            if data.get("translated_text"):
                tokens.add("translation")
            if data.get("summary"):
                tokens.add("summary")
    tokens.update({"id", "status", "queued", "running", "completed", "failed", "started"})
    return {token.lower() for token in tokens if token}


READ_ONLY_TOOLS = {"list_services", "list_models", "list_jobs", "get_job", "wait_for_job", "service_logs", "diagnose", "api_catalog", "read_file", "list_files", "navigate"}
DIRECT_RESULT_TOOLS = READ_ONLY_TOOLS | {"translate_text", "summarize_text", "generate_image", "transcribe_audio", "synthesize_speech", "music_generate", "start_job", "service_action", "model_install", "recheck_model"}
FAST_RESULT_TOOLS = {"navigate", "list_services", "list_models", "list_jobs", "list_files", "read_file", "translate_text", "summarize_text", "generate_image", "music_generate", "service_action", "model_install", "recheck_model", "api_catalog", "get_job", "wait_for_job", "service_logs", "opencode_prompt"}


def _grounded_answer(text: str | None, results: list[dict[str, Any]]) -> str:
    summary = _tool_summary(results)
    if results and all(str(item.get("tool") or "") in DIRECT_RESULT_TOOLS for item in results):
        return summary
    if any(not item.get("ok") for item in results):
        return summary
    if not text:
        return summary
    cleaned = text.strip()
    if cleaned.startswith("{") and cleaned.endswith("}"):
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict) and isinstance(parsed.get("final"), str):
                cleaned = parsed["final"].strip()
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
    if not cleaned or cleaned.startswith("{"):
        return summary
    tokens = _grounding_tokens(results)
    lowered = cleaned.lower()
    if tokens and not any(token in lowered for token in tokens):
        return summary
    if summary and summary not in cleaned:
        return cleaned + "\n\nVerified results: " + summary
    return cleaned


async def _execute_agent_tool(action: dict[str, Any]) -> dict[str, Any]:
    try:
        result = await asyncio.wait_for(execute_tool(action["tool"], action.get("args") or {}), timeout=AGENT_TOOL_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        result = {"ok": False, "error": f"{action['tool']} timed out after {int(AGENT_TOOL_TIMEOUT_SECONDS)}s"}
    if not result.get("ok"):
        try:
            result = await repair_tool_failure(action, result)
        except Exception as exc:  # noqa: BLE001
            log.warning("Automatic repair for %s failed: %s", action.get("tool"), exc)
    return result


async def _final_answer(messages: list[dict[str, Any]], model: str, results: list[dict[str, Any]], message: str = "") -> str:
    if not results:
        return ""
    summary = _tool_summary(results)
    try:
        raw = (await asyncio.wait_for(_agent_llm(
            [
                {
                    "role": "system",
                    "content": "You are Open Studio's execution assistant. Answer only from the verified tool results. Do not call tools, invent statuses or mention unrelated tasks. Be concise and factual. /no_think",
                },
                {
                    "role": "user",
                    "content": f"User request: {message or 'Complete the requested task.'}\n\nVerified tool results:\n{summary}\n\nWrite the final answer. Include relevant ids, paths, status and the next step if anything remains.",
                },
            ],
            model,
            temperature=0.1,
            max_tokens=500,
        ), timeout=AGENT_LLM_TIMEOUT_SECONDS))["content"]
        parsed = _parse_agent_decision(raw)
        if parsed and parsed.get("final"):
            raw = str(parsed["final"])
        return _grounded_answer(raw, results)
    except (HTTPException, asyncio.TimeoutError):
        return summary


async def _run_agent(session: dict[str, Any], message: str, attachments: list[str], model: str) -> tuple[list[dict[str, Any]], str | None]:
    initial_actions = _deterministic_actions(message)
    if _should_use_agent(message, attachments):
        if (
            not attachments
            and re.search(r"\btranslate\b", message, re.I)
            and not re.match(r"^\s*(how|what|why|explain|tell me)", message, re.I)
            and (":" in message or re.search(r"[\"'“”]", message))
        ):
            initial_actions.append({"tool": "translate_text", "args": {"text": _task_text(message)}})
        if not attachments and re.search(r"\b(generate|create|make)\b.*\b(image|picture|artwork|art)\b", message, re.I) and not re.match(r"^\s*(how|what|why|explain|tell me)", message, re.I):
            initial_actions.append({"tool": "generate_image", "args": {"prompt": _image_prompt(message), "provider": "auto"}})
        if not attachments and re.search(r"\bsummar(?:y|ize|ise)\b", message, re.I) and (":" in message or re.search(r"[\"'“”]", message)) and not re.match(r"^\s*(how|what|why|explain|tell me)", message, re.I):
            initial_actions.append({"tool": "summarize_text", "args": {"text": _task_text(message)}})
        if not attachments and re.search(r"\b(create|make|generate|compose)\b.*\b(song|track|music)\b", message, re.I) and not re.match(r"^\s*(how|what|why|explain|tell me)", message, re.I):
            title_match = re.search(r"(?:called|named|titled)\s+[\"'“”]?(.+?)[\"'“”]?(?:[.,]|$)", message, re.I)
            initial_actions.append({"tool": "music_generate", "args": {"title": title_match.group(1).strip() if title_match else "Open Studio song", "caption": _task_text(message)}})
        seen = {(item.get("tool"), json.dumps(item.get("args") or {}, sort_keys=True)) for item in initial_actions}
        for action in [*_query_actions(message), *_explicit_tool_actions(message)]:
            signature = (action.get("tool"), json.dumps(action.get("args") or {}, sort_keys=True))
            if signature not in seen:
                initial_actions.append(action)
                seen.add(signature)
    if not initial_actions and not _should_use_agent(message, attachments):
        return [], None
    results: list[dict[str, Any]] = []
    tool_calls = 0
    initial_actions = [_prepare_action(action, message) for action in initial_actions if _action_allowed(action, message, attachments)]
    for action in initial_actions[:8]:
        if tool_calls >= AGENT_TOOL_CALLS:
            break
        result = await _execute_agent_tool(action)
        results.append({"tool": action["tool"], "args": action.get("args") or {}, **result})
        tool_calls += 1
    if initial_actions and results and all(str(action.get("tool") or "") in FAST_RESULT_TOOLS for action in initial_actions):
        return results, _tool_summary(results)
    protocol = (
        "You are an execution agent. Work step by step. On each turn return ONLY a JSON object. "
        "To use tools: {\"thought\":\"brief reasoning\",\"actions\":[{\"tool\":\"tool_name\",\"args\":{}}],\"final\":null}. "
        "When the task is complete, or after you have enough information: "
        "{\"thought\":\"brief reasoning\",\"actions\":[],\"final\":\"answer for the user\"}. "
        "Use the results of each tool call to decide what to do next. Do not return a final answer while more tool calls are needed. "
        "Do not make up tool results. If a tool fails, read the provided logs/service repair result, retry or repair the affected service, and use opencode_prompt if the failure needs code changes. "
        "For a read-only status/check task, call the relevant tool and then answer from its data; do not move to an unrelated workspace. "
        "Only use navigate when the user explicitly asks to open or go to a page. Only use write_file when the user explicitly asks to save or write a file."
    )
    history = STORE.list_messages(str(session.get("id") or ""))
    prior = history[:-1] if history and history[-1].get("role") == "user" else history
    messages = _context(session, prior)
    agent_system = AGENT_CORE + "\n\n" + AGENT_TOOL_GUIDE + "\n\n" + protocol
    if messages and messages[0].get("role") == "system":
        messages[0]["content"] = agent_system
    else:
        messages.insert(0, {"role": "system", "content": agent_system})
    messages.append({"role": "user", "content": message + ("\n\n" + attachment_context(attachments) if attachments else "")})
    if initial_actions and results:
        messages.append({"role": "assistant", "content": json.dumps({"thought": "Initial deterministic actions", "actions": initial_actions, "final": None})})
        messages.append({"role": "user", "content": "TOOL RESULTS (initial):\n" + _compact_results(results)})
    final_text: str | None = None
    deadline = time.monotonic() + AGENT_TIMEOUT_SECONDS
    for _ in range(max(1, AGENT_STEPS)):
        if tool_calls >= AGENT_TOOL_CALLS or time.monotonic() >= deadline:
            break
        remaining = max(5.0, min(AGENT_LLM_TIMEOUT_SECONDS, deadline - time.monotonic()))
        try:
            raw = (await asyncio.wait_for(_agent_llm(messages, model, temperature=0.1, max_tokens=900, json_mode=True), timeout=remaining))["content"]
        except (HTTPException, asyncio.TimeoutError):
            if results:
                return results, _tool_summary(results)
            return [], None
        decision = _parse_agent_decision(raw)
        log.info("Agent step decision: actions=%s final=%s", [item.get("tool") for item in (decision or {}).get("actions", [])], bool((decision or {}).get("final")))
        if decision is None:
            log.warning("Agent decision was not valid JSON: %s", raw[:1600])
            if results:
                return results, await _final_answer(messages, model, results, message)
            return [], None
        actions = [action for action in (decision.get("actions") or []) if _action_allowed(action, message, attachments)]
        actions = [_prepare_action(action, message) for action in actions]
        if not actions:
            final_text = decision.get("final")
            if final_text:
                return results, _grounded_answer(final_text, results)
            if results:
                break
            return [], None
        messages.append({"role": "assistant", "content": json.dumps(decision, ensure_ascii=False)})
        step_results: list[dict[str, Any]] = []
        for action in actions:
            if tool_calls >= AGENT_TOOL_CALLS:
                break
            result = await _execute_agent_tool(action)
            step_results.append({"tool": action["tool"], "args": action.get("args") or {}, **result})
            tool_calls += 1
        if step_results:
            results.extend(step_results)
            if all(str(item.get("tool") or "") in FAST_RESULT_TOOLS for item in step_results) and not re.search(r"\b(and|then|also|both|after that)\b", message, re.I):
                return results, _tool_summary(results)
            messages.append({"role": "user", "content": "TOOL RESULTS:\n" + _compact_results(step_results)})
        if not step_results:
            if results:
                break
            return [], None
    if not results:
        return [], None
    if final_text:
        return results, _grounded_answer(final_text, results)
    return results, await _final_answer(messages, model, results, message)


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
        "agent_model": AGENT_MODEL,
        "model_installed": bool(models.get("items")),
        "agent_model_installed": any(str(item.get("id")) == AGENT_MODEL for item in models.get("items", []) if isinstance(item, dict)),
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
        assistant_model = AGENT_MODEL if AGENT_MODEL else model
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


@router.post("/sessions/{session_id}/messages/{message_id}/revert")
async def revert_from_message(session_id: str, message_id: str) -> dict[str, Any]:
    if STORE.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    deleted = STORE.revert_from(session_id, message_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return {
        "ok": True,
        "deleted": deleted,
        "messages": STORE.list_messages(session_id),
        "session": STORE.get_session(session_id),
    }


app = create_service_app(
    "chat",
    "Open Studio Chat",
    "Persistent local ChatGPT-style sessions backed by the LLM bridge.",
    version=VERSION,
    extra_routers=[router],
)
