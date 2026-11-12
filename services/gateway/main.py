"""Open Studio public gateway.

The only published API surface. It owns first-run password setup, sessions,
API keys, service health aggregation and a transparent authenticated reverse
proxy to every internal micro-service.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx
import psutil
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from openstudio_common import (
    FILES_ROOT,
    INTERNAL_TOKEN,
    env,
    env_bool,
    env_int,
    human_size,
    service_url,
)

from .auth import AuthStore

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("gateway")

VERSION = env("OPENSTUDIO_VERSION", "1.0.0")
COOKIE_NAME = env("SESSION_COOKIE", "os_session")
COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", False)
AUTH = AuthStore()
STARTED = time.time()
LOGIN_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
MAX_LOGIN_ATTEMPTS = env_int("LOGIN_ATTEMPTS_PER_MINUTE", 8)

# name -> (base URL, prefix, label, category)
SERVICES: dict[str, tuple[str, str, str, str]] = {
    "files": (service_url("files"), "/api/files", "Files", "core"),
    "admin": (service_url("admin"), "/api/admin", "Services", "core"),
    "jobs": (service_url("jobhub"), "/api/jobs", "Jobs", "core"),
    "chat": (service_url("chat"), "/api/chat", "Chat", "core"),
    "music": (service_url("music"), "/api/music", "Music", "create"),
    "dj": (service_url("dj"), "/api/dj", "DJ Studio", "create"),
    "video": (service_url("video"), "/api/video", "Video", "create"),
    "voice": (service_url("voice"), "/api/voice", "Voice", "create"),
    "srt": (service_url("srt"), "/api/srt", "Subtitles", "create"),
    "imagegen": (service_url("imagegen"), "/api/images", "Images", "create"),
    "docs": (service_url("docs"), "/api/docs", "Documents", "text"),
    "translation": (service_url("translation"), "/api/translate", "Translate", "text"),
    "summary": (service_url("summary"), "/api/summary", "Summary", "text"),
    "pdf": (service_url("pdf"), "/api/pdf", "PDF", "text"),
    "ffmpeg": (service_url("ffmpeg"), "/api/ffmpeg", "FFmpeg", "tools"),
    "ytdlp": (service_url("ytdlp"), "/api/ytdlp", "yt-dlp", "tools"),
    "qvac": (service_url("qvac"), "/api/qvac", "QVAC", "create"),
    "llm": (service_url("llm"), "/api/llm", "LLM", "core"),
}

PUBLIC_PATHS = {
    "/api/health",
    "/api/version",
    "/api/auth/status",
    "/api/auth/setup",
    "/api/auth/login",
    "/health",
    "/",
}

# Public route aliases used by the unified frontend. Internally the services
# keep explicit names (imagegen, translation) so each has one canonical queue.
PROXY_ALIASES = {
    "images": "imagegen",
    "translate": "translation",
}
HOP_HEADERS = {
    "host",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "cookie",
    "authorization",
}
RESPONSE_SKIP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "content-encoding",
}

app = FastAPI(
    title="Open Studio API",
    version=VERSION,
    docs_url="/api/docs" if env_bool("ENABLE_DOCS", False) else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if env_bool("ENABLE_DOCS", False) else None,
    lifespan=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in env("CORS_ORIGINS", "http://localhost:8090,http://127.0.0.1:8090").split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Disposition", "X-Request-ID"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(self), geolocation=()")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:80]
    return (request.client.host if request.client else "unknown")[:80]


def token_from_request(request: Request) -> tuple[str | None, str]:
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie:
        return cookie, "cookie"
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip(), "bearer"
    key = request.headers.get("x-api-key")
    if key:
        return key.strip(), "api_key"
    return None, "none"


def identity(request: Request) -> dict[str, Any] | None:
    token, source = token_from_request(request)
    if not token:
        return None
    session = AUTH.session_for(token)
    if session:
        return {**session, "source": source}
    api_key = AUTH.api_key_for(token)
    if api_key:
        return {**api_key, "source": "api_key"}
    return None


def require_auth(request: Request) -> dict[str, Any]:
    if not AUTH.has_password:
        raise HTTPException(status_code=428, detail="First-run password setup is required")
    user = identity(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=30 * 86400,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",
    )


def check_login_rate(ip: str) -> None:
    now = time.time()
    attempts = [t for t in LOGIN_ATTEMPTS[ip] if now - t < 60]
    if len(attempts) >= MAX_LOGIN_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again in a minute.")
    attempts.append(now)
    LOGIN_ATTEMPTS[ip] = attempts


# Public endpoints ---------------------------------------------------------

@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "name": "Open Studio",
        "version": VERSION,
        "status": "ok",
        "setup_required": not AUTH.has_password,
        "docs": "/api/docs" if env_bool("ENABLE_DOCS", False) else None,
    }


@app.get("/health")
@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "open-studio-gateway",
        "version": VERSION,
        "setup_required": not AUTH.has_password,
        "uptime_seconds": round(time.time() - STARTED, 1),
    }


@app.get("/api/version")
async def version() -> dict[str, Any]:
    return {"name": "Open Studio", "version": VERSION}


@app.get("/api/auth/status")
async def auth_status(request: Request) -> dict[str, Any]:
    user = identity(request)
    return {
        "setup_required": not AUTH.has_password,
        "authenticated": bool(user),
        "password_set_at": AUTH.setup_at,
        "identity": {"type": user.get("type"), "id": user.get("id")} if user else None,
        "version": VERSION,
    }


@app.post("/api/auth/setup")
async def setup(payload: dict[str, Any], request: Request, response: Response) -> dict[str, Any]:
    if AUTH.has_password:
        raise HTTPException(status_code=409, detail="Password is already configured")
    password = str(payload.get("password") or "")
    confirm = str(payload.get("confirm") or password)
    if password != confirm:
        raise HTTPException(status_code=422, detail="Passwords do not match")
    try:
        AUTH.set_password(password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    token, session = AUTH.create_session(user_agent=request.headers.get("user-agent", ""), ip=client_ip(request))
    set_session_cookie(response, token)
    return {"ok": True, "setup_complete": True, "session": session}


@app.post("/api/auth/login")
async def login(payload: dict[str, Any], request: Request, response: Response) -> dict[str, Any]:
    if not AUTH.has_password:
        raise HTTPException(status_code=428, detail="First-run password setup is required")
    ip = client_ip(request)
    check_login_rate(ip)
    password = str(payload.get("password") or "")
    if not AUTH.check_password(password):
        raise HTTPException(status_code=401, detail="Incorrect password")
    token, session = AUTH.create_session(
        user_agent=request.headers.get("user-agent", ""),
        ip=ip,
    )
    set_session_cookie(response, token)
    return {"ok": True, "session": session}


@app.post("/api/auth/logout")
async def logout(request: Request, response: Response) -> dict[str, Any]:
    token, _ = token_from_request(request)
    session = AUTH.session_for(token, touch=False) if token else None
    if session:
        AUTH.revoke_session(session["id"])
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
async def me(request: Request) -> dict[str, Any]:
    user = require_auth(request)
    return {"authenticated": True, "identity": user, "setup_at": AUTH.setup_at, "version": VERSION}


@app.post("/api/auth/change-password")
async def change_password(payload: dict[str, Any], request: Request, response: Response) -> dict[str, Any]:
    require_auth(request)
    try:
        AUTH.change_password(str(payload.get("current_password") or ""), str(payload.get("new_password") or ""))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    token, session = AUTH.create_session(user_agent=request.headers.get("user-agent", ""), ip=client_ip(request))
    set_session_cookie(response, token)
    return {"ok": True, "session": session}


@app.get("/api/auth/sessions")
async def sessions(request: Request) -> dict[str, Any]:
    require_auth(request)
    current, _ = token_from_request(request)
    current_session = AUTH.session_for(current, touch=False) if current else None
    return {
        "items": [{**item, "current": bool(current_session and item["id"] == current_session["id"])} for item in AUTH.list_sessions()]
    }


@app.delete("/api/auth/sessions/{session_id}")
async def revoke_session(session_id: str, request: Request) -> dict[str, Any]:
    require_auth(request)
    if not AUTH.revoke_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


@app.get("/api/auth/api-keys")
async def api_keys(request: Request) -> dict[str, Any]:
    require_auth(request)
    return {"items": AUTH.list_api_keys()}


@app.post("/api/auth/api-keys")
async def create_api_key(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    require_auth(request)
    return AUTH.create_api_key(str(payload.get("name") or "API key"))


@app.delete("/api/auth/api-keys/{key_id}")
async def revoke_api_key(key_id: str, request: Request) -> dict[str, Any]:
    require_auth(request)
    if not AUTH.revoke_api_key(key_id):
        raise HTTPException(status_code=404, detail="API key not found")
    return {"ok": True}


# Aggregated system state --------------------------------------------------

@app.get("/api/status")
async def system_status(request: Request) -> dict[str, Any]:
    require_auth(request)
    async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=1.5)) as client:
        async def probe(name: str) -> dict[str, Any]:
            base, prefix, label, category = SERVICES[name]
            started = time.time()
            try:
                response = await client.get(f"{base}/health")
                ok = response.status_code < 500
                body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                return {
                    "name": name,
                    "label": label,
                    "category": category,
                    "online": ok,
                    "status": body.get("status", "ok" if ok else "error"),
                    "version": body.get("version"),
                    "latency_ms": round((time.time() - started) * 1000),
                    "detail": body.get("service") or body.get("detail"),
                }
            except Exception as exc:  # noqa: BLE001
                return {
                    "name": name,
                    "label": label,
                    "category": category,
                    "online": False,
                    "status": "offline",
                    "latency_ms": None,
                    "detail": str(exc)[:200],
                }

        services = await asyncio.gather(*(probe(name) for name in SERVICES))

    queues: dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{SERVICES['jobs'][0]}/api/jobs/queues")
            if response.status_code == 200:
                queues = response.json()
    except Exception:  # noqa: BLE001
        pass

    disk = shutil.disk_usage(FILES_ROOT)
    memory = psutil.virtual_memory()
    gpu = None
    try:
        output = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,driver_version", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if output.returncode == 0 and output.stdout.strip():
            rows = []
            for line in output.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 4:
                    rows.append({"name": parts[0], "memory_total_mb": int(parts[1]), "memory_used_mb": int(parts[2]), "driver": parts[3]})
            gpu = rows
    except Exception:  # noqa: BLE001
        gpu = None

    return {
        "app": {"name": "Open Studio", "version": VERSION, "uptime_seconds": round(time.time() - STARTED, 1)},
        "setup_required": not AUTH.has_password,
        "services": services,
        "online": sum(1 for s in services if s["online"]),
        "total": len(services),
        "queues": queues,
        "storage": {
            "root": str(FILES_ROOT),
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "free_label": human_size(disk.free),
        },
        "system": {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "cpu_count": psutil.cpu_count(),
            "memory_total": memory.total,
            "memory_used": memory.used,
            "memory_percent": memory.percent,
            "gpu": gpu,
        },
    }


@app.get("/api/system/info")
async def system_info(request: Request) -> dict[str, Any]:
    require_auth(request)
    return {
        "version": VERSION,
        "services": [
            {"name": name, "label": label, "category": category, "prefix": f"/api/{name}"}
            for name, (_, _, label, category) in SERVICES.items()
        ],
        "setup_required": not AUTH.has_password,
        "files_root": str(FILES_ROOT),
        "features": {
            "auth": True,
            "jobs": True,
            "shared_files": True,
            "gpu": env_bool("OPENSTUDIO_GPU", False),
        },
    }


# Transparent authenticated proxy -----------------------------------------

@app.api_route("/api/{service}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy_root(service: str, request: Request):
    """Proxy an empty service path without the trailing-slash redirect.

    Browsers follow 307s, but scripts and API clients should not have to. The
    explicit /api/status, /api/auth/* and /api/health routes are registered
    earlier and therefore still win.
    """
    return await proxy(service, "", request)


@app.api_route("/api/{service}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy(service: str, path: str, request: Request):
    require_auth(request)
    service = PROXY_ALIASES.get(service, service)
    if service not in SERVICES:
        raise HTTPException(status_code=404, detail=f"Unknown service '{service}'")
    base, prefix, _, _ = SERVICES[service]
    target = f"{base}{prefix}" + (f"/{path}" if path else "")
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS}
    headers["X-Internal-Token"] = INTERNAL_TOKEN
    headers["X-OpenStudio-User"] = "authenticated"
    timeout = httpx.Timeout(connect=20.0, read=None, write=None, pool=30.0)
    client = httpx.AsyncClient(timeout=timeout, follow_redirects=False)
    try:
        upstream_request = client.build_request(
            request.method,
            target,
            params=list(request.query_params.multi_items()),
            headers=headers,
            content=request.stream(),
        )
        upstream = await client.send(upstream_request, stream=True)
    except httpx.ConnectError as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"{service} service is offline: {exc}") from exc
    except httpx.TimeoutException as exc:
        await client.aclose()
        raise HTTPException(status_code=504, detail=f"{service} service timed out") from exc
    except Exception as exc:  # noqa: BLE001
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"{service} proxy error: {exc}") from exc

    response_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in RESPONSE_SKIP}
    media_type = upstream.headers.get("content-type")

    async def stream_body():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        stream_body(),
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=media_type,
        background=None,
    )
