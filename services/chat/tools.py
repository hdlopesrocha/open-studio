"""Agent tools for the Open Studio chat assistant."""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import httpx

from openstudio_common import FILES_ROOT, INTERNAL_TOKEN, JOBHUB_URL, service_url

from .api_reference import API_REFERENCE

log = logging.getLogger("chat.tools")
CURRENT_CHAT_PROMPT: ContextVar[str] = ContextVar("chat_prompt", default="")


def set_chat_prompt(prompt: str) -> None:
    CURRENT_CHAT_PROMPT.set((prompt or "").strip()[:4000])

SERVICE_URLS: dict[str, str] = {
    "admin": service_url("admin"),
    "jobs": JOBHUB_URL,
    "files": service_url("files"),
    "music": service_url("music"),
    "dj": service_url("dj"),
    "video": service_url("video"),
    "voice": service_url("voice"),
    "srt": service_url("srt"),
    "images": service_url("imagegen"),
    "imagegen": service_url("imagegen"),
    "docs": service_url("docs"),
    "documents": service_url("docs"),
    "translation": service_url("translation"),
    "translate": service_url("translation"),
    "summary": service_url("summary"),
    "summarize": service_url("summary"),
    "subtitles": service_url("srt"),
    "pdf": service_url("pdf"),
    "ffmpeg": service_url("ffmpeg"),
    "ytdlp": service_url("ytdlp"),
    "qvac": service_url("qvac"),
    "llm": service_url("llm"),
}

NAVIGATION = {
    "/": "Home",
    "/chat": "Chat",
    "/music": "Audio",
    "/music?tab=dj-library": "Audio · DJ Library",
    "/music?tab=dj-create": "Audio · DJ Create",
    "/music?tab=dj-mix": "Audio · DJ Mix",
    "/music?tab=srt": "Audio · SRT",
    "/video": "Video",
    "/video?tab=qvac": "Video · QVAC",
    "/documents": "Documents",
    "/documents?tab=pdf": "Documents · PDF tools",
    "/documents?tab=summary": "Documents · Summary",
    "/documents?tab=translate": "Documents · Translate",
    "/voice": "Voice",
    "/images": "Images",
    "/files": "Files",
    "/jobs": "Jobs",
    "/settings": "Settings",
}

TOOL_GUIDE = """
You are the execution layer for Open Studio, not just a planner. When the user
asks you to do something, use the tools below to do it. Inspect results and
continue with the next tool until the task is complete or you are blocked.

Tool results include {ok, data} and sometimes an error. Never claim an operation
succeeded unless the tool result says ok. Do not ask for confirmation for normal
non-destructive actions; ask only when a required input cannot be inferred.

Core control:
- navigate {"path": "/video?tab=qvac"} — guide the user to a workspace.
- list_services {} — list service state.
- service_action {"name": "dj", "action": "enable|disable|restart|build"}.
- service_logs {"name": "dj", "lines": 120} — inspect recent container logs.
- list_models {} — list model packs and installed state.
- model_install {"model_id": "translation-nllb"} — queue a model download/verification.
- recheck_model {"model_id": "music-ace-step"} — verify an installed model.
- list_jobs {"status": "failed"} — inspect jobs; omit status for recent jobs.
- job_action {"job_id": "...", "action": "cancel|retry"}.
- get_job {"job_id": "..."}.
- wait_for_job {"job_id": "...", "timeout_seconds": 60} — poll a job briefly.
- start_job {"component": "ffmpeg", "action": "...", "title": "...", "params": {...}}.

Files:
- list_files {"path": ""} — inspect shared files.
- read_file {"path": "..."} — read a text file from shared storage.
- write_file {"path": "...", "content": "..."} — create a text artifact.

Direct media/document tools:
- translate_text {"text": "...", "source_language": "auto", "target_language": "en", "model": "auto"}.
- summarize_text {"text": "...", "length": "short|medium|long", "language": "auto"}.
- synthesize_speech {"text": "...", "engine": "omnivoice|piper", "voice_id": "...", "language": "en"}.
- voice_train {"name": "...", "audio_path": "uploads/reference.wav", "transcript": "...", "language": "en", "consent": true}.
- transcribe_audio {"audio_path": "...", "title": "..."}.
- generate_image {"prompt": "...", "provider": "auto|procedural|diffusers|comfyui|qvac", "width": 1024, "height": 1024, "model": ""}.
- music_generate {"title": "...", "caption": "genre and arrangement description", "lyrics": "optional lyrics", "duration": 120, "genre": "Pop", "mood": "..."}.

REST API access:
- api_catalog {"service": "music"} — list the real endpoints and methods for a service.
  Omit service to list available services.
- api_describe {"service": "music", "path": "/api/music/projects", "method": "POST"} — inspect the request schema before building a complex body.
- api_request {"service": "music", "method": "POST", "path": "/api/music/projects", "body": {...}, "query": {...}} — call an endpoint directly.
  Use api_catalog/api_describe first when you do not know the exact path or body.

Repair and handoff:
- diagnose {} — collect services, models, failed jobs and logs.
- opencode_prompt {"problem": "..."} — produce a copy-ready OpenCode prompt with app context.

Useful workflow:
1. For a generation task, start the job with the relevant tool or api_request.
2. Use get_job or wait_for_job to check it when the task expects a finished result.
3. Report the job id, status, artifacts and the page where the user can inspect it.
Never disable core services or delete files unless the user explicitly asks.
"""
AGENT_TOOL_GUIDE = """
You are Open Studio's execution agent. Use tools, inspect results, and continue
until the task is complete. Return only the JSON decision format requested by the
system. Never invent a tool result.

Tools and arguments:
- navigate(path)
- list_services(); service_action(name, action=enable|disable|restart|build); service_logs(name, lines)
- list_models(); model_install(model_id); recheck_model(model_id)
- list_jobs(status?); get_job(job_id); wait_for_job(job_id, timeout_seconds); job_action(job_id, action=cancel|retry); start_job(component, action, title, params)
- list_files(path?); read_file(path); write_file(path, content)
- api_catalog(service?); api_describe(service, path, method); api_request(service, method, path, body)
- diagnose(); opencode_prompt(problem)
- translate_text(text, source_language?, target_language?, model?)
- summarize_text(text, length?, language?)
- synthesize_speech(text, engine?, voice_id?, language?)
- voice_train(name, audio_path, transcript?, language?, consent=true, description?, tags?, voice_id?)
- transcribe_audio(audio_path)
- generate_image(prompt, provider?, model?, width?, height?)
- music_generate(title, caption, lyrics?, duration?, genre?, mood?)

Use api_catalog before inventing a REST path, then api_describe for the exact
request schema and request_example. api_request accepts optional body and query.
The tool supplies internal authentication; never add internal headers yourself.

API cookbook:
- Create a song: POST /api/music/projects {"title":"..."} -> POST
  /api/music/projects/{project_id}/songs {"title":"...", "genre":"Pop",
  "duration":120} -> POST /api/music/songs/{song_id}/generate
  {"provider":"ace_step", "mode":"full", "caption":"...", "duration":120}.
- Generate an image: POST /api/images/generate {"prompt":"...", "provider":"auto",
  "width":1024, "height":1024}.
- Translate: POST /api/translate/translate {"text":"...", "source_language":"auto",
  "target_language":"pt"}.
- Summarize: POST /api/summary/summarize {"text":"...", "length":"medium",
  "language":"auto"}.
- Speech: POST /api/voice/tts {"text":"...", "engine":"omnivoice"}.
- Train a voice: POST /api/voice/train as multipart/form-data with name, audio,
  transcript, language and consent=true; use voice_train instead of api_request so
  the shared audio file is uploaded correctly. Only clone voices you own or have permission to use.
- Transcribe/align: POST /api/srt/transcribe {"audio_path":"..."} or
  POST /api/srt/align {"audio_path":"...", "lyrics":"..."}.
- Any job: POST /api/jobs {"component":"...", "action":"...", "title":"...",
  "params":{...}}; poll GET /api/jobs/{job_id}.
- Video: POST /api/video/projects then POST /api/video/projects/{id}/run;
  use api_describe for the exact project config.

If a tool fails, inspect the logs/repair result, retry or repair the service, then
use opencode_prompt if code changes are needed. Only use navigate when the user
explicitly asks to open/go to a page. Only write files when requested.
"""

TOOL_NAMES = {
    "navigate", "list_services", "service_action", "service_logs", "list_models",
    "model_install", "recheck_model", "list_jobs", "job_action", "get_job",
    "wait_for_job", "start_job", "list_files", "read_file", "write_file",
    "api_catalog", "api_describe", "api_request", "diagnose", "opencode_prompt",
    "generate_image", "translate_text", "summarize_text", "synthesize_speech",
    "transcribe_audio", "music_generate", "voice_train",
}


API_SPEC_PATH = Path(__file__).with_name("api_spec.json")
_API_SPEC: dict[str, Any] | None = None
API_SERVICE_ALIASES = {
    "images": "imagegen", "imagegen": "imagegen", "translate": "translation",
    "translation": "translation", "summarize": "summary", "summary": "summary",
    "subtitles": "srt", "srt": "srt", "documents": "docs", "docs": "docs",
    "jobs": "jobs", "jobhub": "jobs",
}


def _api_spec() -> dict[str, Any]:
    global _API_SPEC
    if _API_SPEC is None:
        try:
            _API_SPEC = json.loads(API_SPEC_PATH.read_text())
        except (OSError, ValueError, TypeError):
            _API_SPEC = {"services": {}}
    return _API_SPEC


def _spec_service(service: str) -> tuple[str, dict[str, Any] | None]:
    target = API_SERVICE_ALIASES.get(service, service)
    value = (_api_spec().get("services") or {}).get(target)
    return target, value if isinstance(value, dict) else None


def _resolve_ref(schema: Any, components: dict[str, Any], seen: set[str] | None = None) -> Any:
    if not isinstance(schema, dict):
        return schema
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        name = ref.rsplit("/", 1)[-1]
        seen = seen or set()
        if name in seen:
            return {"$ref": ref}
        seen.add(name)
        target = components.get(name)
        return _resolve_ref(target, components, seen) if isinstance(target, dict) else schema
    return schema


def _request_body_schema(operation: dict[str, Any]) -> tuple[Any, str | None]:
    content = (operation.get("requestBody") or {}).get("content") or {}
    for content_type in ("application/json", "multipart/form-data"):
        schema = (content.get(content_type) or {}).get("schema")
        if schema is not None:
            return schema, content_type
    return None, None


def _body_fields(schema: Any, components: dict[str, Any]) -> list[str]:
    schema = _resolve_ref(schema, components)
    if not isinstance(schema, dict):
        return []
    properties = schema.get("properties")
    return sorted(str(key) for key in properties) if isinstance(properties, dict) else []


def _body_example(schema: Any, components: dict[str, Any], *, depth: int = 0) -> Any:
    if not isinstance(schema, dict) or depth > 4:
        return None
    schema = _resolve_ref(schema, components)
    if not isinstance(schema, dict):
        return None
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]
    for key in ("anyOf", "oneOf", "allOf"):
        options = schema.get(key)
        if isinstance(options, list) and options:
            return _body_example(options[0], components, depth=depth + 1)
    kind = schema.get("type")
    if kind == "object" or isinstance(schema.get("properties"), dict):
        result: dict[str, Any] = {}
        properties = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        for name, prop in properties.items():
            if name in required or len(result) < 8:
                value = _body_example(prop, components, depth=depth + 1)
                if value is not None:
                    result[str(name)] = value
        return result
    if kind == "array":
        item = _body_example(schema.get("items") or {}, components, depth=depth + 1)
        return [item] if item is not None else []
    if kind == "integer":
        return 1
    if kind == "number":
        return 1.0
    if kind == "boolean":
        return True
    if kind == "string":
        fmt = schema.get("format")
        if fmt == "date-time":
            return "2026-01-01T00:00:00Z"
        if fmt == "date":
            return "2026-01-01"
        return "string"
    return None


def _component_subset(schema: Any, components: dict[str, Any]) -> dict[str, Any]:
    names: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            ref = value.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                name = ref.rsplit("/", 1)[-1]
                if name not in names:
                    names.add(name)
                    visit(components.get(name))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
    return {name: components[name] for name in names if name in components}


STATIC_ENDPOINTS: dict[str, list[dict[str, str]]] = {
    "jobs": [
        {"method": "GET", "path": "/api/jobs", "summary": "List jobs, optionally by component/status"},
        {"method": "POST", "path": "/api/jobs", "summary": "Create a job with component, action, title and params"},
        {"method": "GET", "path": "/api/jobs/{job_id}", "summary": "Read job status, progress, error and artifacts"},
        {"method": "POST", "path": "/api/jobs/{job_id}/cancel", "summary": "Cancel a job"},
        {"method": "POST", "path": "/api/jobs/{job_id}/retry", "summary": "Retry a job"},
    ],
    "files": [
        {"method": "GET", "path": "/api/files/list", "summary": "List a shared-storage folder"},
        {"method": "GET", "path": "/api/files/read", "summary": "Read a text file"},
        {"method": "POST", "path": "/api/files/write", "summary": "Write a text file"},
        {"method": "POST", "path": "/api/files/rename", "summary": "Rename a file or folder"},
        {"method": "POST", "path": "/api/files/move", "summary": "Move or copy a file"},
    ],
    "music": [
        {"method": "GET", "path": "/api/music/projects", "summary": "List song projects"},
        {"method": "POST", "path": "/api/music/projects", "summary": "Create a project with title, description and artist"},
        {"method": "POST", "path": "/api/music/projects/{project_id}/songs", "summary": "Create a song in a project"},
        {"method": "POST", "path": "/api/music/songs/{song_id}/generate", "summary": "Queue ACE-Step generation for a song"},
        {"method": "POST", "path": "/api/music/lyrics/draft", "summary": "Queue an LLM lyric draft"},
        {"method": "GET", "path": "/api/music/songs/{song_id}/takes", "summary": "List generated takes"},
        {"method": "GET", "path": "/api/music/catalog", "summary": "Read music models and defaults"},
    ],
    "dj": [
        {"method": "GET", "path": "/api/dj/tracks", "summary": "List analysed DJ tracks"},
        {"method": "POST", "path": "/api/dj/tracks", "summary": "Add a track from shared storage"},
        {"method": "POST", "path": "/api/dj/tracks/{track_id}/analyze", "summary": "Queue DJ analysis"},
        {"method": "POST", "path": "/api/dj/generations", "summary": "Queue a DJ generation"},
        {"method": "POST", "path": "/api/dj/mixes", "summary": "Create a mix draft"},
        {"method": "POST", "path": "/api/dj/mixes/{mix_id}/scene", "summary": "Plan an AI mix scene"},
        {"method": "POST", "path": "/api/dj/mixes/{mix_id}/render", "summary": "Render a mix"},
    ],
    "video": [
        {"method": "GET", "path": "/api/video/projects", "summary": "List video projects"},
        {"method": "POST", "path": "/api/video/projects", "summary": "Create a video project from audio and SRT"},
        {"method": "GET", "path": "/api/video/projects/{project_id}", "summary": "Read a video project"},
        {"method": "POST", "path": "/api/video/projects/{project_id}/run", "summary": "Run the video pipeline"},
        {"method": "GET", "path": "/api/video/projects/{project_id}/assets", "summary": "List project assets"},
        {"method": "GET", "path": "/api/video/projects/{project_id}/scenes", "summary": "List planned scenes"},
    ],
    "images": [
        {"method": "POST", "path": "/api/images/generate", "summary": "Queue image generation"},
        {"method": "POST", "path": "/api/images/upscale", "summary": "Queue image upscaling"},
        {"method": "GET", "path": "/api/images/gallery", "summary": "List generated images"},
        {"method": "GET", "path": "/api/images/models", "summary": "List image models"},
        {"method": "GET", "path": "/api/images/providers", "summary": "List image providers"},
    ],
    "translation": [
        {"method": "POST", "path": "/api/translate/translate", "summary": "Translate text synchronously"},
        {"method": "POST", "path": "/api/translate/translate/job", "summary": "Queue a translation job"},
        {"method": "GET", "path": "/api/translate/models", "summary": "List translation models"},
        {"method": "GET", "path": "/api/translate/languages", "summary": "List supported languages"},
    ],
    "summary": [
        {"method": "POST", "path": "/api/summary/summarize", "summary": "Summarize text synchronously"},
        {"method": "POST", "path": "/api/summary/summarize/job", "summary": "Queue a summary job"},
    ],
    "voice": [
        {"method": "POST", "path": "/api/voice/tts", "summary": "Queue speech synthesis"},
        {"method": "POST", "path": "/api/voice/batch", "summary": "Queue batch speech synthesis"},
        {"method": "GET", "path": "/api/voice/catalog", "summary": "List engines, voices and formats"},
        {"method": "GET", "path": "/api/voice/voices", "summary": "List trained voices"},
    ],
    "srt": [
        {"method": "POST", "path": "/api/srt/transcribe", "summary": "Queue Whisper transcription"},
        {"method": "POST", "path": "/api/srt/align", "summary": "Queue lyric alignment"},
        {"method": "POST", "path": "/api/srt/from-text", "summary": "Create timed subtitles from text"},
        {"method": "POST", "path": "/api/srt/convert", "summary": "Convert SRT/VTT/ASS"},
    ],
    "docs": [
        {"method": "POST", "path": "/api/docs/run", "summary": "Run the document pipeline"},
    ],
    "pdf": [
        {"method": "POST", "path": "/api/pdf/extract", "summary": "Extract text or pages from a PDF"},
    ],
    "ffmpeg": [
        {"method": "POST", "path": "/api/ffmpeg/run", "summary": "Run an FFmpeg operation"},
    ],
    "ytdlp": [
        {"method": "POST", "path": "/api/ytdlp/jobs", "summary": "Queue a yt-dlp download"},
    ],
    "qvac": [
        {"method": "GET", "path": "/api/qvac/status", "summary": "Read QVAC runtime status"},
    ],
}


def _reference_catalog(service: str) -> list[dict[str, str]]:
    aliases = {"images": "imagegen", "imagegen": "imagegen", "translate": "translation", "summarize": "summary", "subtitles": "srt", "documents": "docs"}
    target = aliases.get(service, service)
    current = ""
    items: list[dict[str, str]] = []
    for line in API_REFERENCE.splitlines():
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            continue
        if current != target or not line.strip():
            continue
        method, _, path = line.partition(" ")
        if method in {"GET", "POST", "PUT", "PATCH", "DELETE"} and path.startswith("/api/"):
            items.append({"method": method, "path": path, "summary": "API reference"})
    return items


def _static_catalog(service: str) -> list[dict[str, str]]:
    aliases = {"imagegen": "images", "translate": "translation", "summarize": "summary", "subtitles": "srt", "documents": "docs"}
    return _reference_catalog(service) or STATIC_ENDPOINTS.get(aliases.get(service, service), [])


def _headers() -> dict[str, str]:
    return {"Content-Type": "application/json", "X-Internal-Token": INTERNAL_TOKEN, "X-Service": "chat"}


async def _request(service: str, method: str, path: str, body: Any = None, *, params: dict[str, Any] | None = None, timeout: float = 120.0) -> dict[str, Any]:
    base = SERVICE_URLS.get(service)
    if not base:
        return {"ok": False, "error": f"Unknown service '{service}'. Available: {', '.join(SERVICE_URLS)}"}
    if not path.startswith("/api/"):
        return {"ok": False, "error": "Agent API paths must start with /api/."}
    if "/internal/" in path:
        return {"ok": False, "error": "Internal control paths are not available to the agent."}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=timeout, write=60.0, pool=30.0), headers=_headers()) as client:
            response = await client.request(method.upper(), f"{base.rstrip('/')}{path}", json=body, params=params)
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"{service} is unreachable: {exc}"}
    try:
        payload = response.json()
    except (ValueError, TypeError):
        payload = response.text[:4000]
    return {"ok": response.status_code < 400, "status": response.status_code, "data": payload}


async def _request_upload(
    service: str,
    path: str,
    field: str,
    file_path: str,
    data: dict[str, Any],
    *,
    timeout: float = 180.0,
) -> dict[str, Any]:
    base = SERVICE_URLS.get(service)
    if not base:
        return {"ok": False, "error": f"Unknown service '{service}'."}
    relative = file_path.strip().lstrip("/")
    if relative.startswith("data/files/"):
        relative = relative[len("data/files/"):]
    candidate = (FILES_ROOT / relative).resolve()
    root = FILES_ROOT.resolve()
    if candidate != root and root not in candidate.parents:
        return {"ok": False, "error": "The audio file must be inside shared storage."}
    if not candidate.is_file():
        return {"ok": False, "error": f"Audio file not found: {relative}"}
    mime = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    try:
        with candidate.open("rb") as handle:
            files = {field: (candidate.name, handle, mime)}
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=timeout, write=120.0, pool=30.0), headers=_headers()) as client:
                response = await client.post(f"{base.rstrip('/')}{path}", data={key: str(value) for key, value in data.items() if value is not None}, files=files)
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"{service} upload failed: {exc}"}
    try:
        payload = response.json()
    except (ValueError, TypeError):
        payload = response.text[:4000]
    return {"ok": response.status_code < 400, "status": response.status_code, "data": payload}


async def _openapi(service: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    target, spec = _spec_service(service)
    if spec:
        return {"openapi": spec.get("openapi") or "3.1.0", "info": spec.get("info") or {}, "paths": spec.get("paths") or {}, "components": spec.get("components") or {}}, None
    base = SERVICE_URLS.get(service)
    if not base:
        return None, {"ok": False, "error": f"Unknown service '{service}'. Available: {', '.join(SERVICE_URLS)}"}
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=_headers()) as client:
            response = await client.get(f"{base.rstrip('/')}/openapi.json")
    except httpx.HTTPError as exc:
        return None, {"ok": False, "error": f"Could not read the OpenAPI schema for {service}: {exc}"}
    if response.status_code >= 400:
        return None, {"ok": False, "error": f"OpenAPI schema unavailable for {service} ({response.status_code})."}
    try:
        return response.json(), None
    except (ValueError, TypeError):
        return None, {"ok": False, "error": f"OpenAPI schema for {service} was not valid JSON."}


async def _api_catalog(service: str = "") -> dict[str, Any]:
    if not service:
        return {"ok": True, "data": {"services": sorted(SERVICE_URLS)}}
    target, _ = _spec_service(service)
    doc, error = await _openapi(service)
    if error:
        items = _static_catalog(service)
        return {"ok": True, "data": {"service": service, "endpoints": items, "total": len(items), "source": "built-in catalog (OpenAPI docs disabled)"}}
    paths = doc.get("paths") or {}
    items: list[dict[str, Any]] = []
    for path, operations in paths.items():
        if not path.startswith("/api/") or "/internal/" in path:
            continue
        if not isinstance(operations, dict):
            continue
        for method, operation in operations.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"} or not isinstance(operation, dict):
                continue
            body_schema, _ = _request_body_schema(operation)
            components = doc.get("components", {}).get("schemas", {})
            items.append({
                "method": method.upper(),
                "path": path,
                "summary": str(operation.get("summary") or operation.get("operationId") or "")[:160],
                "query": [str(param.get("name")) for param in operation.get("parameters") or [] if isinstance(param, dict) and param.get("in") == "query"],
                "body_fields": _body_fields(body_schema, components),
            })
    return {"ok": True, "data": {"service": target, "endpoints": items[:400], "total": len(items), "source": "built-in OpenAPI spec"}}


async def _api_describe(service: str, path: str, method: str) -> dict[str, Any]:
    target, _ = _spec_service(service)
    doc, error = await _openapi(service)
    if error:
        for item in _static_catalog(service):
            if item["path"] == path and item["method"] == method.upper():
                return {"ok": True, "data": {"service": service, "method": method.upper(), "path": path, "summary": item["summary"], "request_body": None, "note": "OpenAPI docs are disabled; use the tool guide fields or api_request with the documented payload."}}
        return error
    operations = (doc.get("paths") or {}).get(path)
    if not isinstance(operations, dict):
        return {"ok": False, "error": f"{path} is not present in the {service} OpenAPI schema."}
    operation = operations.get(method.lower())
    if not isinstance(operation, dict):
        return {"ok": False, "error": f"{method.upper()} {path} is not available in {service}."}
    body_schema, content_type = _request_body_schema(operation)
    components = doc.get("components", {}).get("schemas", {})
    return {
        "ok": True,
        "data": {
            "service": target,
            "method": method.upper(),
            "path": path,
            "summary": operation.get("summary") or operation.get("operationId") or "",
            "parameters": operation.get("parameters") or [],
            "request_body": body_schema,
            "request_content_type": content_type,
            "request_example": _body_example(body_schema, components),
            "body_fields": _body_fields(body_schema, components),
            "components": _component_subset(body_schema, components),
        },
    }


async def _wait_for_job(job_id: str, timeout_seconds: float) -> dict[str, Any]:
    if not job_id:
        return {"ok": False, "error": "job_id is required"}
    timeout_seconds = max(0.0, min(120.0, float(timeout_seconds or 0)))
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    latest: dict[str, Any] = {}
    while True:
        latest = await _request("jobs", "GET", f"/api/jobs/{job_id}")
        if not latest.get("ok"):
            return latest
        job = latest.get("data") or {}
        if str(job.get("status") or "") in {"completed", "failed", "canceled"}:
            return latest
        if asyncio.get_running_loop().time() >= deadline:
            return latest
        await asyncio.sleep(2.0)


async def _music_generate(args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title") or "Open Studio song").strip() or "Open Studio song"
    project = await _request("music", "POST", "/api/music/projects", {
        "title": title,
        "description": str(args.get("description") or ""),
        "artist": str(args.get("artist") or ""),
    })
    if not project.get("ok"):
        return project
    project_data = project.get("data") or {}
    project_id = str(project_data.get("id") or "")
    if not project_id:
        return {"ok": False, "error": "Music project creation did not return an id.", "data": project}
    song_body: dict[str, Any] = {
        "title": title,
        "artist": str(args.get("artist") or ""),
        "genre": str(args.get("genre") or "Pop"),
        "mood": str(args.get("mood") or "Introspective"),
        "style": str(args.get("style") or ""),
        "language": str(args.get("language") or "en"),
        "duration": float(args.get("duration") or 150),
        "bpm": int(args.get("bpm") or 96),
    }
    song = await _request("music", "POST", f"/api/music/projects/{project_id}/songs", song_body)
    if not song.get("ok"):
        return song
    song_data = song.get("data") or {}
    song_id = str(song_data.get("id") or "")
    if not song_id:
        return {"ok": False, "error": "Song creation did not return an id.", "data": song}
    generate_body: dict[str, Any] = {
        "provider": str(args.get("provider") or "ace_step"),
        "mode": "full",
        "caption": str(args.get("caption") or args.get("prompt") or title),
        "duration": float(args.get("duration") or 150),
        "bpm": int(args.get("bpm") or 96),
        "variations": int(args.get("variations") or 1),
    }
    if args.get("lyrics"):
        generate_body["lyrics"] = str(args.get("lyrics"))
    job = await _request("music", "POST", f"/api/music/songs/{song_id}/generate", generate_body)
    return {"ok": bool(job.get("ok")), "data": {"project": project_data, "song": song_data, "job": job.get("data")}, "status": job.get("status")}

TOOL_SERVICE_MAP = {
    "translate_text": "translation",
    "summarize_text": "summary",
    "generate_image": "imagegen",
    "transcribe_audio": "srt",
    "synthesize_speech": "voice",
    "music_generate": "music",
    "voice_train": "voice",
}
SERVICE_ALIAS_MAP = {
    "images": "imagegen", "imagegen": "imagegen", "translate": "translation",
    "translation": "translation", "summarize": "summary", "summary": "summary",
    "subtitles": "srt", "srt": "srt", "documents": "docs", "docs": "docs",
    "voice": "voice", "music": "music", "music-engine": "music-engine",
    "video": "video", "qvac": "qvac", "llm": "llm", "ollama": "ollama",
    "pdf": "pdf", "ffmpeg": "ffmpeg", "ytdlp": "ytdlp", "files": "files",
    "jobs": "jobhub", "jobhub": "jobhub", "admin": "admin",
}


def _compact_services(payload: Any) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    items = []
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        items.append({
            "name": item.get("name"),
            "label": item.get("label"),
            "core": bool(item.get("core")),
            "enabled": bool(item.get("enabled")),
            "running": bool(item.get("running")),
            "state": item.get("state"),
            "health": item.get("health"),
            "status": item.get("status"),
        })
    return {
        "items": items,
        "core": data.get("core"),
        "optional": data.get("optional"),
        "enabled": data.get("enabled"),
        "running": data.get("running"),
        "total": data.get("total", len(items)),
    }


def _compact_models(payload: Any) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    items = []
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        items.append({
            "id": item.get("id"),
            "label": item.get("label"),
            "group": item.get("group"),
            "installed": bool(item.get("installed")),
            "size": item.get("size"),
            "detail": item.get("detail"),
        })
    return {"items": items, "total": data.get("total", len(items)), "installed": data.get("installed")}


def _compact_jobs(payload: Any) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    items = []
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        items.append({
            "id": item.get("id"),
            "component": item.get("component"),
            "action": item.get("action"),
            "title": item.get("title"),
            "status": item.get("status"),
            "stage": item.get("stage"),
            "progress": item.get("progress"),
            "error": item.get("error"),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
            "artifacts": item.get("artifacts") or [],
        })
    return {"items": items, "total": data.get("total", len(items)), "limit": data.get("limit"), "offset": data.get("offset")}


def _service_for_action(action: dict[str, Any]) -> str | None:
    tool = str(action.get("tool") or "")
    args = action.get("args") if isinstance(action.get("args"), dict) else {}
    raw = str(args.get("service") or "") if tool == "api_request" else TOOL_SERVICE_MAP.get(tool, "")
    return SERVICE_ALIAS_MAP.get(raw.strip().lower(), raw.strip().lower() or None)


def _looks_repairable(result: dict[str, Any]) -> bool:
    if result.get("ok"):
        return False
    status = result.get("status")
    if status in {500, 502, 503, 504}:
        return True
    text = f"{result.get('error') or ''} {result.get('data') or ''}".lower()
    return any(token in text for token in ("unreachable", "connection refused", "timed out", "timeout", "offline", "not available", "service unavailable", "bad gateway", "no healthy upstream"))


async def _service_item(service: str) -> dict[str, Any] | None:
    result = await _request("admin", "GET", "/api/admin/services")
    if not result.get("ok"):
        return None
    for item in (result.get("data") or {}).get("items") or []:
        if str(item.get("name") or "") == service:
            return item
    return None


async def repair_tool_failure(action: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    if not _looks_repairable(result):
        return result
    service = _service_for_action(action)
    if not service or service in {"admin", "jobhub", "files", "llm", "ollama"}:
        return result
    before = await _service_item(service)
    if not before:
        return result
    logs_result = await _request("admin", "GET", f"/api/admin/services/{service}/logs?lines=80")
    logs = str((logs_result.get("data") or {}).get("lines") or "").splitlines()[-60:] if logs_result.get("ok") else []
    action_name = "enable" if not before.get("enabled") else "restart"
    repaired = await _request("admin", "POST", f"/api/admin/services/{service}/{action_name}")
    await asyncio.sleep(2.0)
    after = await _service_item(service)
    retry = await execute_tool(str(action.get("tool")), action.get("args") if isinstance(action.get("args"), dict) else {})
    repair_info = {
        "service": service,
        "action": action_name,
        "service_action_ok": bool(repaired.get("ok")),
        "before": {key: before.get(key) for key in ("enabled", "running", "health", "state")},
        "after": {key: (after or {}).get(key) for key in ("enabled", "running", "health", "state")},
        "logs": logs[-30:],
        "retried": True,
    }
    if not retry.get("ok"):
        repair_info["opencode_prompt"] = build_opencode_prompt(
            f"{service} failed while executing {action.get('tool')}",
            details=json.dumps({"service": repair_info, "error": retry, "logs": logs[-40:]}, ensure_ascii=False)[:12000],
        )
    retry["repair"] = repair_info
    return retry


def _service_online(item: dict[str, Any]) -> bool:
    if "online" in item:
        return bool(item.get("online"))
    if "running" in item:
        return bool(item.get("running"))
    return str(item.get("state") or "").lower() in {"running", "healthy"} or str(item.get("health") or "").lower() == "healthy"


async def _diagnose() -> dict[str, Any]:
    services = await _request("admin", "GET", "/api/admin/services")
    models = await _request("admin", "GET", "/api/admin/models")
    jobs = await _request("jobs", "GET", "/api/jobs?status=failed&limit=12")
    offline: list[str] = []
    if services.get("ok"):
        for item in services.get("data", {}).get("items", []):
            if item.get("enabled") and not _service_online(item):
                offline.append(str(item.get("name")))
    logs: dict[str, Any] = {}
    for name in offline[:3]:
        result = await _request("admin", "GET", f"/api/admin/services/{name}/logs?lines=80")
        if result.get("ok"):
            lines = str(result.get("data", {}).get("lines") or "").splitlines()
            logs[name] = lines[-80:]
    source = {
        "services": _compact_services(services.get("data")),
        "models": _compact_models(models.get("data")),
        "failed_jobs": _compact_jobs(jobs.get("data")),
        "logs": logs,
    }
    prompt = build_opencode_prompt(
        "Open Studio agent diagnosis",
        details=json.dumps(source, ensure_ascii=False)[:12000],
    )
    return {"ok": True, "data": {**source, "offline_services": offline, "opencode_prompt": prompt}}


def build_opencode_prompt(problem: str, *, details: str = "") -> str:
    return f"""You are working in the Open Studio repository (/home/hdlrocha/open-studio).

Problem:
{problem}

Useful application context:
- Vue 3 frontend under frontend/src; FastAPI services under services/*.
- Gateway/auth in services/gateway; shared service plumbing in shared/python/openstudio_common.
- Jobs run through services/jobhub; service manager is services/admin.
- Standard verification: PYTHONPATH=/tmp/opencode/pylibs:shared/python:. python3 -m pytest -q
- Frontend checks: cd frontend && npx vue-tsc --noEmit && npm run build
- Runtime diagnostics: docker compose ps, docker compose logs <service>, /api/status, /api/admin/services, /api/admin/models, /api/jobs?status=failed.
- Keep changes consistent with the existing UI/service patterns and add or update tests.

Diagnostic data:
{details or "(not provided)"}

Please identify the root cause, implement the smallest complete fix, run the relevant tests and builds, and report the changed files and verification results. Do not commit unless asked."""


def _chat_prompt() -> str:
    return CURRENT_CHAT_PROMPT.get().strip()


async def execute_tool(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    try:
        if name == "navigate":
            path = str(args.get("path") or "/")
            if path not in NAVIGATION:
                matches = [item for item in NAVIGATION if item.lower().startswith(path.lower())]
                path = matches[0] if matches else "/"
            return {"ok": True, "data": {"path": path, "label": NAVIGATION.get(path, path)}}
        if name == "list_services":
            result = await _request("admin", "GET", "/api/admin/services")
            if result.get("ok") and isinstance(result.get("data"), dict):
                result["data"] = _compact_services(result["data"])
            return result
        if name == "service_action":
            service = str(args.get("name") or "").strip()
            action = str(args.get("action") or "").strip().lower()
            if action not in {"enable", "disable", "restart", "build"} or not service:
                return {"ok": False, "error": "service_action needs name and action enable/disable/restart/build"}
            return await _request("admin", "POST", f"/api/admin/services/{service}/{action}")
        if name == "service_logs":
            service = str(args.get("name") or "").strip()
            lines = max(10, min(500, int(args.get("lines") or 120)))
            return await _request("admin", "GET", f"/api/admin/services/{service}/logs?lines={lines}")
        if name == "list_models":
            result = await _request("admin", "GET", "/api/admin/models")
            if result.get("ok") and isinstance(result.get("data"), dict):
                result["data"] = _compact_models(result["data"])
            return result
        if name in {"model_install", "recheck_model"}:
            model_id = str(args.get("model_id") or "").strip()
            if not model_id:
                return {"ok": False, "error": "model_id is required"}
            return await _request("admin", "POST", f"/api/admin/models/{model_id}/install?force=true")
        if name == "list_jobs":
            status = str(args.get("status") or "").strip()
            suffix = f"&status={status}" if status else ""
            result = await _request("jobs", "GET", f"/api/jobs?limit=30{suffix}")
            if result.get("ok") and isinstance(result.get("data"), dict):
                result["data"] = _compact_jobs(result["data"])
            return result
        if name == "job_action":
            job_id = str(args.get("job_id") or "").strip()
            action = str(args.get("action") or "").strip().lower()
            if not job_id or action not in {"cancel", "retry"}:
                return {"ok": False, "error": "job_action needs job_id and action cancel/retry"}
            return await _request("jobs", "POST", f"/api/jobs/{job_id}/{action}")
        if name == "list_files":
            path = str(args.get("path") or "")
            return await _request("files", "GET", f"/api/files/list?path={path}")
        if name == "read_file":
            path = str(args.get("path") or "")
            return await _request("files", "GET", f"/api/files/read?path={path}")
        if name == "write_file":
            path = str(args.get("path") or "").strip()
            content = str(args.get("content") or "")
            if not path:
                return {"ok": False, "error": "path is required"}
            if not content.strip():
                return {"ok": False, "error": "content is required; refusing to write an empty file"}
            return await _request("files", "POST", "/api/files/write", {"path": path, "content": content})
        if name == "api_request":
            service = str(args.get("service") or "").strip()
            method = str(args.get("method") or "GET").upper()
            path = str(args.get("path") or "").strip()
            body = args.get("body")
            query = args.get("query") if isinstance(args.get("query"), dict) else (args.get("params") if isinstance(args.get("params"), dict) else None)
            if method not in {"GET", "POST", "PATCH", "PUT", "DELETE"}:
                return {"ok": False, "error": "Unsupported HTTP method"}
            if service in {"jobs", "jobhub"} and method == "POST" and isinstance(body, dict) and _chat_prompt():
                body = dict(body)
                job_params = dict(body.get("params") or {}) if isinstance(body.get("params"), dict) else {}
                job_params.setdefault("chat_prompt", _chat_prompt())
                body["params"] = job_params
            return await _request(service, method, path, body, params=query)
        if name == "diagnose":
            return await _diagnose()
        if name == "opencode_prompt":
            problem = str(args.get("problem") or "Open Studio issue")
            details = str(args.get("details") or "")
            return {"ok": True, "data": {"prompt": build_opencode_prompt(problem, details=details)}}
        if name == "api_catalog":
            return await _api_catalog(str(args.get("service") or "").strip())
        if name == "api_describe":
            return await _api_describe(str(args.get("service") or "").strip(), str(args.get("path") or "").strip(), str(args.get("method") or "GET").strip())
        if name == "get_job":
            job_id = str(args.get("job_id") or "").strip()
            if not job_id:
                return {"ok": False, "error": "job_id is required"}
            return await _request("jobs", "GET", f"/api/jobs/{job_id}")
        if name == "wait_for_job":
            return await _wait_for_job(str(args.get("job_id") or "").strip(), float(args.get("timeout_seconds") or 0))
        if name == "start_job":
            component = str(args.get("component") or "").strip()
            action = str(args.get("action") or "").strip()
            if not component or not action:
                return {"ok": False, "error": "start_job needs component and action"}
            params = dict(args.get("params") or {}) if isinstance(args.get("params"), dict) else {}
            if _chat_prompt():
                params.setdefault("chat_prompt", _chat_prompt())
            payload = {"component": component, "action": action, "title": str(args.get("title") or ""), "params": params}
            return await _request("jobs", "POST", "/api/jobs", payload)
        if name == "generate_image":
            prompt = str(args.get("prompt") or "").strip()
            if not prompt:
                return {"ok": False, "error": "prompt is required"}
            body = {key: args[key] for key in ("provider", "model", "width", "height", "negative_prompt", "steps", "guidance", "seed", "batch_count", "output_format", "title") if key in args}
            body["prompt"] = prompt
            return await _request("images", "POST", "/api/images/generate", body)
        if name == "translate_text":
            text = str(args.get("text") or args.get("source_text") or args.get("content") or "").strip()
            if not text:
                return {"ok": False, "error": "text is required"}
            body = {key: args[key] for key in ("source_language", "target_language", "model", "num_beams", "max_length", "temperature") if key in args}
            body["text"] = text
            return await _request("translation", "POST", "/api/translate/translate", body, timeout=300.0)
        if name == "summarize_text":
            text = str(args.get("text") or args.get("content") or "").strip()
            if not text:
                return {"ok": False, "error": "text is required"}
            body = {key: args[key] for key in ("length", "language", "source_language", "model", "max_tokens", "min_tokens") if key in args}
            body["text"] = text
            return await _request("summary", "POST", "/api/summary/summarize", body, timeout=300.0)
        if name == "synthesize_speech":
            text = str(args.get("text") or "").strip()
            if not text:
                return {"ok": False, "error": "text is required"}
            body = {key: value for key, value in args.items() if key != "text"}
            body["text"] = text
            return await _request("voice", "POST", "/api/voice/tts", body)
        if name == "transcribe_audio":
            audio_path = str(args.get("audio_path") or "").strip()
            if not audio_path:
                return {"ok": False, "error": "audio_path is required"}
            body = {key: value for key, value in args.items() if key != "audio_path"}
            body["audio_path"] = audio_path
            return await _request("srt", "POST", "/api/srt/transcribe", body)
        if name == "voice_train":
            voice_name = str(args.get("name") or "").strip()
            audio_path = str(args.get("audio_path") or "").strip()
            if not voice_name:
                return {"ok": False, "error": "Voice name is required."}
            if not audio_path:
                return {"ok": False, "error": "audio_path is required; use a shared reference audio file."}
            if not bool(args.get("consent", False)):
                return {"ok": False, "error": "Explicit consent is required: only clone voices you own or have permission to use. Pass consent=true after confirming."}
            data = {
                "name": voice_name,
                "consent": "true",
                "preprocess_prompt": "true" if args.get("preprocess_prompt", True) else "false",
                "transcript": args.get("transcript"),
                "language": args.get("language"),
                "description": args.get("description"),
                "tags": ", ".join(args.get("tags") or []) if isinstance(args.get("tags"), list) else args.get("tags"),
            }
            voice_id = str(args.get("voice_id") or "").strip()
            path = f"/api/voice/voices/{voice_id}/retrain" if voice_id else "/api/voice/train"
            return await _request_upload("voice", path, "audio", audio_path, data)
        if name == "music_generate":
            return await _music_generate(args)
        return {"ok": False, "error": f"Unknown agent tool '{name}'"}
    except Exception as exc:  # noqa: BLE001
        log.exception("Agent tool %s failed", name)
        return {"ok": False, "error": str(exc)}


def attachment_context(attachments: list[str]) -> str:
    if not attachments:
        return ""
    lines = ["Attached files are already in shared storage and may be used by API tools:"]
    for path in attachments[:8]:
        candidate = (FILES_ROOT / path).resolve()
        try:
            inside = candidate == FILES_ROOT.resolve() or FILES_ROOT.resolve() in candidate.parents
            exists = inside and candidate.is_file()
        except OSError:
            exists = False
        lines.append(f"- {path}{'' if exists else ' (missing)'}")
    return "\n".join(lines)
