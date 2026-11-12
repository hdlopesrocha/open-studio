"""Agent tools for the Open Studio chat assistant."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from openstudio_common import FILES_ROOT, INTERNAL_TOKEN, JOBHUB_URL, service_url

log = logging.getLogger("chat.tools")

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
    "docs": service_url("docs"),
    "translation": service_url("translation"),
    "summary": service_url("summary"),
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
Available agent tools (return JSON only when you decide to use them):
- navigate {"path": "/music?tab=dj-mix"} — guide the user to a workspace.
- list_services {} — list service state.
- service_action {"name": "dj", "action": "enable|disable|restart|build"} — repair/start a service.
- service_logs {"name": "dj", "lines": 120} — inspect recent container logs.
- list_models {} — list model packs and installed state.
- model_install {"model_id": "translation-nllb"} — queue a model download/verification.
- recheck_model {"model_id": "music-ace-step"} — verify an installed model.
- list_jobs {"status": "failed"} — inspect jobs; omit status for recent jobs.
- job_action {"job_id": "...", "action": "cancel|retry"}.
- list_files {"path": ""} — inspect shared files.
- read_file {"path": "..."} — read a text file from shared storage.
- write_file {"path": "...", "content": "..."} — create a text artifact.
- api_request {"service": "imagegen", "method": "POST", "path": "/api/images/generate", "body": {...}} — call a whitelisted Open Studio REST API. Use the application context and endpoint names; do not invent paths.
- diagnose {} — collect service, model, failed job and log information for a problem.
- opencode_prompt {"problem": "..."} — produce a copy-ready prompt for OpenCode with app context.

Use at most 4 tools per turn. Do not run destructive file deletion or disable core services.
"""


def _headers() -> dict[str, str]:
    return {"Content-Type": "application/json", "X-Internal-Token": INTERNAL_TOKEN, "X-Service": "chat"}


async def _request(service: str, method: str, path: str, body: Any = None, *, timeout: float = 120.0) -> dict[str, Any]:
    base = SERVICE_URLS.get(service)
    if not base:
        return {"ok": False, "error": f"Unknown service '{service}'. Available: {', '.join(SERVICE_URLS)}"}
    if not path.startswith("/api/"):
        return {"ok": False, "error": "Agent API paths must start with /api/."}
    if "/internal/" in path:
        return {"ok": False, "error": "Internal control paths are not available to the agent."}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=timeout, write=60.0, pool=30.0), headers=_headers()) as client:
            response = await client.request(method.upper(), f"{base.rstrip('/')}{path}", json=body)
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"{service} is unreachable: {exc}"}
    try:
        payload = response.json()
    except (ValueError, TypeError):
        payload = response.text[:4000]
    return {"ok": response.status_code < 400, "status": response.status_code, "data": payload}


async def _diagnose() -> dict[str, Any]:
    services = await _request("admin", "GET", "/api/admin/services")
    models = await _request("admin", "GET", "/api/admin/models")
    jobs = await _request("jobs", "GET", "/api/jobs?status=failed&limit=12")
    offline: list[str] = []
    if services.get("ok"):
        for item in services.get("data", {}).get("items", []):
            if item.get("enabled") and not item.get("online"):
                offline.append(str(item.get("name")))
    logs: dict[str, Any] = {}
    for name in offline[:3]:
        result = await _request("admin", "GET", f"/api/admin/services/{name}/logs?lines=80")
        if result.get("ok"):
            lines = str(result.get("data", {}).get("lines") or "").splitlines()
            logs[name] = lines[-80:]
    source = {"services": services.get("data"), "models": models.get("data"), "failed_jobs": jobs.get("data"), "logs": logs}
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
            return await _request("admin", "GET", "/api/admin/services")
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
            return await _request("admin", "GET", "/api/admin/models")
        if name in {"model_install", "recheck_model"}:
            model_id = str(args.get("model_id") or "").strip()
            if not model_id:
                return {"ok": False, "error": "model_id is required"}
            return await _request("admin", "POST", f"/api/admin/models/{model_id}/install?force=true")
        if name == "list_jobs":
            status = str(args.get("status") or "").strip()
            suffix = f"&status={status}" if status else ""
            return await _request("jobs", "GET", f"/api/jobs?limit=30{suffix}")
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
            path = str(args.get("path") or "")
            content = str(args.get("content") or "")
            return await _request("files", "POST", "/api/files/write", {"path": path, "content": content})
        if name == "api_request":
            service = str(args.get("service") or "").strip()
            method = str(args.get("method") or "GET").upper()
            path = str(args.get("path") or "").strip()
            body = args.get("body")
            if method not in {"GET", "POST", "PATCH", "PUT", "DELETE"}:
                return {"ok": False, "error": "Unsupported HTTP method"}
            return await _request(service, method, path, body)
        if name == "diagnose":
            return await _diagnose()
        if name == "opencode_prompt":
            problem = str(args.get("problem") or "Open Studio issue")
            details = str(args.get("details") or "")
            return {"ok": True, "data": {"prompt": build_opencode_prompt(problem, details=details)}}
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
