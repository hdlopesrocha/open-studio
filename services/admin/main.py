"""Service manager for Open Studio.

The gateway and the always-on core are intentionally small. Every component is
disabled by default and lives behind a Compose profile. This service is the only
container with access to the Docker socket; it builds and starts services on
demand and removes their containers when they are disabled.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import shutil
import signal
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException

from openstudio_common import (
    FILES_ROOT,
    INTERNAL_TOKEN,
    JOBHUB_URL,
    JobCancelled,
    JobContext,
    JobRunner,
    create_service_app,
    jobhub_headers,
    utc_now,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("admin")

VERSION = "1.0.0"
PROJECT_DIR = Path(os.getenv("OPENSTUDIO_PROJECT_DIR", "/project"))
COMPOSE_FILE = PROJECT_DIR / "docker-compose.yml"
CORE = {"files", "jobhub", "admin", "gateway", "frontend"}

META: dict[str, dict[str, Any]] = {
    "admin": {"label": "Service Manager", "description": "Builds, starts and stops optional services on demand.", "group": "Core", "requires": []},
    "gateway": {"label": "Gateway", "description": "Password, sessions, API keys and the authenticated reverse proxy.", "group": "Core", "requires": []},
    "files": {"label": "Files", "description": "Shared storage and file explorer API.", "group": "Core", "requires": []},
    "jobhub": {"label": "Job Hub", "description": "Persistent per-component queues and SSE progress.", "group": "Core", "requires": []},
    "frontend": {"label": "Frontend", "description": "Unified Vue application served by nginx.", "group": "Core", "requires": []},
    "music": {
        "label": "Music Studio",
        "description": "ACE-Step 1.5 projects, songs, lyrics, takes and exports.",
        "group": "Create",
        "requires": ["music-engine"],
    },
    "music-engine": {
        "label": "ACE-Step Engine",
        "description": "GGUF/C++ music inference engine. First start downloads several GB.",
        "group": "Engines",
        "requires": [],
    },
    "video": {
        "label": "Video Studio",
        "description": "Video orchestration: analysis, planning, images, animation and render.",
        "group": "Create",
        "requires": ["video-audio", "video-lyrics", "video-planner", "video-animation", "video-renderer", "imagegen"],
    },
    "video-audio": {"label": "Video Audio Analysis", "description": "Librosa beat, section and spectral analysis.", "group": "Video helpers", "requires": []},
    "video-lyrics": {"label": "Video Lyrics Analysis", "description": "SRT parsing, repetition and section mapping.", "group": "Video helpers", "requires": []},
    "video-planner": {"label": "Video Planner", "description": "Deterministic scene planner with optional Ollama enrichment.", "group": "Video helpers", "requires": []},
    "video-animation": {"label": "Video Animation", "description": "FFmpeg and OpenCV camera animation renderer.", "group": "Video helpers", "requires": []},
    "video-renderer": {"label": "Video Renderer", "description": "Final assembly, subtitles and audio muxing.", "group": "Video helpers", "requires": []},
    "voice": {
        "label": "Voice / TTS",
        "description": "OmniVoice cloning/design and fast Piper voices. All TTS runs here.",
        "group": "Create",
        "requires": [],
    },
    "srt": {"label": "AI Subtitles", "description": "Whisper transcription and lyric alignment to SRT/VTT/ASS.", "group": "Create", "requires": []},
    "imagegen": {"label": "Picture Studio", "description": "Procedural, Diffusers, ComfyUI and QVAC image generation.", "group": "Create", "requires": []},
    "docs": {
        "label": "Documents",
        "description": "PDF/text → translate → summarize → narrate → SRT → ZIP.",
        "group": "Text",
        "requires": ["pdf", "translation", "summary", "voice", "ffmpeg"],
    },
    "translation": {"label": "Translation", "description": "Shared OPUS-MT/NLLB translation service.", "group": "Text", "requires": []},
    "summary": {"label": "Summaries", "description": "Hierarchical T5 summaries in English and Portuguese.", "group": "Text", "requires": []},
    "pdf": {"label": "PDF / OCR", "description": "PyMuPDF extraction and Tesseract OCR.", "group": "Text", "requires": []},
    "ffmpeg": {"label": "FFmpeg", "description": "Shared media workbench: trim, crop, transcode, concat and more.", "group": "Tools", "requires": []},
    "ytdlp": {"label": "yt-dlp", "description": "Media analysis and downloads with ffmpeg post-processing.", "group": "Tools", "requires": []},
    "qvac": {"label": "QVAC", "description": "Tether QVAC video/image diffusion and upscaling.", "group": "Create", "requires": []},
    "llm": {"label": "LLM Bridge", "description": "OpenAI-compatible bridge used by lyrics and video planning.", "group": "Core AI", "requires": ["ollama"]},
    "ollama": {"label": "Ollama", "description": "Local LLM runtime. Pull a model with `make models-llm`.", "group": "Core AI", "requires": []},
}

runner = JobRunner("admin")
router = APIRouter(prefix="/api/admin", tags=["services"])
SERVICE_NAME = "admin"
CONTROL_LOCK = asyncio.Lock()


def compose_command() -> list[str]:
    command = ["docker", "compose", "--project-directory", str(PROJECT_DIR), "-f", str(COMPOSE_FILE)]
    overrides = os.getenv("COMPOSE_OVERRIDES", "").strip()
    if overrides:
        for token in shlex.split(overrides):
            if token == "-f":
                continue
            candidate = Path(token)
            command += ["-f", str(candidate if candidate.is_absolute() else PROJECT_DIR / candidate)]
    return command


def env() -> dict[str, str]:
    result = os.environ.copy()
    result["COMPOSE_PROJECT_NAME"] = "openstudio"
    result["OPENSTUDIO_DATA_DIR"] = os.getenv("OPENSTUDIO_DATA_DIR", str(PROJECT_DIR / "data"))
    return result


async def run_command(
    args: list[str],
    *,
    ctx: JobContext | None = None,
    timeout: float = 6 * 3600,
) -> tuple[int, list[str]]:
    log.info("admin command: %s", " ".join(shlex.quote(part) for part in args))
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(PROJECT_DIR),
        env=env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    lines: list[str] = []
    started = asyncio.get_running_loop().time()
    try:
        assert process.stdout is not None
        while True:
            try:
                raw = await asyncio.wait_for(process.stdout.readline(), timeout=1.0)
            except asyncio.TimeoutError:
                if ctx is not None:
                    await ctx.check()
                if asyncio.get_running_loop().time() - started > timeout:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    raise TimeoutError(f"Command exceeded {timeout:.0f}s")
                continue
            if not raw:
                break
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                lines.append(line)
                if ctx is not None and len(lines) > 500:
                    del lines[:100]
                if ctx is not None:
                    stage = "Building" if "build" in " ".join(args[:8]) else "Applying"
                    progress = min(94.0, 5.0 + len(lines) * 0.6)
                    await ctx.report(progress, stage, line[:180])
        code = await process.wait()
        return code, lines
    finally:
        if process.returncode is None:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            await process.wait()


async def compose_json(args: list[str]) -> Any:
    code, lines = await run_command([*compose_command(), *args], timeout=60)
    if code != 0:
        raise HTTPException(status_code=502, detail="\n".join(lines[-20:]) or "docker compose failed")
    text = "\n".join(lines).strip()
    if not text:
        return []
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        items = []
        for line in text.splitlines():
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return items


async def compose_services() -> list[str]:
    code, lines = await run_command(
        [*compose_command(), "--profile", "services", "config", "--services"], timeout=60
    )
    if code != 0:
        raise HTTPException(status_code=502, detail="\n".join(lines[-20:]))
    return [line.strip() for line in lines if line.strip() and not line.startswith("WARN")]


async def compose_config() -> dict[str, Any]:
    data = await compose_json(["--profile", "services", "config", "--format", "json"])
    return data if isinstance(data, dict) else {}


async def image_exists(image: str) -> bool:
    if not image:
        return False
    process = await asyncio.create_subprocess_exec(
        "docker", "image", "inspect", image,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    return await process.wait() == 0


def container_maps(containers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for container in containers:
        service = container.get("Service") or container.get("service")
        if service:
            mapping[service] = container
    return mapping


async def services_payload() -> list[dict[str, Any]]:
    config = await compose_config()
    configured = config.get("services", {}) if isinstance(config.get("services"), dict) else {}
    containers = await compose_json(["ps", "-a", "--format", "json"])
    if isinstance(containers, dict):
        containers = [containers]
    by_service = container_maps([item for item in containers if isinstance(item, dict)])
    names = list(configured.keys())
    for name in META:
        if name not in names:
            names.append(name)
    result: list[dict[str, Any]] = []
    for name in sorted(names):
        cfg = configured.get(name, {}) if isinstance(configured.get(name), dict) else {}
        container = by_service.get(name, {})
        state = str(container.get("State") or container.get("state") or "").lower()
        health = str(container.get("Health") or container.get("health") or "").lower()
        image = str(cfg.get("image") or container.get("Image") or "")
        meta = META.get(name, {})
        is_core = name in CORE
        running = state == "running"
        enabled = running or is_core
        if state == "running":
            health_label = health or "running"
        elif state in {"exited", "created", "dead"}:
            health_label = state
        elif is_core:
            health_label = "core"
        else:
            health_label = "disabled"
        result.append(
            {
                "name": name,
                "label": meta.get("label") or name.replace("-", " ").title(),
                "description": meta.get("description") or cfg.get("description") or "",
                "group": meta.get("group") or ("Core" if is_core else "Services"),
                "core": is_core,
                "enabled": enabled,
                "running": running,
                "state": state or "absent",
                "health": health_label,
                "image": image,
                "image_built": await image_exists(image),
                "requires": meta.get("requires") or [],
                "container": container.get("Name") or container.get("name") or "",
                "status": str(container.get("Status") or container.get("status") or ""),
            }
        )
    return result


@router.get("/services")
async def list_services() -> dict[str, Any]:
    items = await services_payload()
    return {
        "items": items,
        "core": [item for item in items if item["core"]],
        "optional": [item for item in items if not item["core"]],
        "enabled": sum(1 for item in items if item["enabled"]),
        "running": sum(1 for item in items if item["running"]),
        "total": len(items),
        "generated_at": utc_now(),
    }


@router.get("/services/{name}/logs")
async def service_logs(name: str, lines: int = 200, x_internal_token: str = Header(default="")) -> dict[str, Any]:
    if x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid internal token")
    lines = max(10, min(1000, lines))
    code, output = await run_command([*compose_command(), "logs", "--no-color", "--tail", str(lines), name], timeout=60)
    return {"service": name, "lines": output, "code": code}


async def submit(action: str, name: str) -> dict[str, Any]:
    if name not in META and name not in CORE:
        raise HTTPException(status_code=404, detail="Unknown service")
    if name in CORE and action != "restart":
        raise HTTPException(status_code=409, detail="Core services are always enabled")
    body = {
        "component": "admin",
        "action": action,
        "title": f"{action.title()} service · {name}",
        "params": {"service": name},
    }
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=jobhub_headers()) as client:
            response = await client.post(f"{JOBHUB_URL}/api/jobs", json=body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Job hub unreachable: {exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=response.text[:1000])
    return response.json()


@router.post("/services/{name}/enable")
async def enable(name: str) -> dict[str, Any]:
    return await submit("enable", name)


@router.post("/services/{name}/disable")
async def disable(name: str) -> dict[str, Any]:
    return await submit("disable", name)


@router.post("/services/{name}/build")
async def build(name: str) -> dict[str, Any]:
    return await submit("build", name)


@router.post("/services/{name}/restart")
async def restart(name: str) -> dict[str, Any]:
    return await submit("restart", name)


@router.post("/files/delete-all")
async def delete_all_files(payload: dict[str, Any]) -> dict[str, Any]:
    if str(payload.get("confirm") or "") != "DELETE":
        raise HTTPException(status_code=422, detail='Send {"confirm":"DELETE"} to confirm')
    root = FILES_ROOT.resolve()
    removed = 0
    freed = 0
    for child in list(root.iterdir()):
        try:
            if child.is_dir():
                freed += sum(f.stat().st_size for f in child.rglob("*") if f.is_file())
                shutil.rmtree(child)
            else:
                freed += child.stat().st_size
                child.unlink()
            removed += 1
        except OSError:
            log.warning("Could not remove %s", child, exc_info=True)
    for name in ("music", "video", "voice", "voices", "documents", "images", "subtitles", "ffmpeg", "ytdlp", "qvac", "uploads", "tmp"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return {"removed": removed, "bytes_freed": freed, "root": str(root), "deleted_at": utc_now()}


async def _control_locked(ctx: JobContext) -> dict[str, Any]:
    name = str(ctx.params.get("service") or "")
    action = ctx.action
    if not name:
        raise ValueError("service is required")
    if name in CORE and action != "restart":
        raise ValueError("core services are always enabled")
    if action == "enable":
        await ctx.report(2.0, "Starting", f"Preparing {name}")
        configured = await compose_config()
        service_cfg = (configured.get("services") or {}).get(name) or {}
        image = str(service_cfg.get("image") or "")
        built = await image_exists(image) if image else False
        command = [*compose_command(), "--profile", "services", "up", "-d"]
        if not built:
            command.append("--build")
            await ctx.report(4.0, "Building", f"Image for {name} is missing; building it now")
        command += ["--remove-orphans", name]
        code, lines = await run_command(command, ctx=ctx)
        if code != 0:
            raise RuntimeError("\n".join(lines[-30:]) or "docker compose up failed")
        await ctx.report(100.0, "Complete", f"{name} enabled")
        return {
            "message": f"{name} enabled",
            "data": {"service": name, "built": not built, "image": image, "output": lines[-20:]},
        }
    if action == "disable":
        await ctx.report(10.0, "Stopping", f"Stopping {name}")
        code, lines = await run_command([*compose_command(), "stop", name], ctx=ctx, timeout=600)
        await run_command([*compose_command(), "rm", "-f", name], ctx=ctx, timeout=600)
        await ctx.report(100.0, "Complete", f"{name} disabled and removed")
        return {"message": f"{name} disabled", "data": {"service": name, "output": lines[-20:]}}
    if action == "build":
        await ctx.report(2.0, "Building", f"Building {name}")
        code, lines = await run_command([*compose_command(), "build", name], ctx=ctx)
        if code != 0:
            raise RuntimeError("\n".join(lines[-30:]) or "docker compose build failed")
        return {"message": f"{name} image built", "data": {"service": name, "output": lines[-20:]}}
    if action == "restart":
        code, lines = await run_command([*compose_command(), "restart", name], ctx=ctx, timeout=600)
        if code != 0:
            raise RuntimeError("\n".join(lines[-30:]) or "restart failed")
        return {"message": f"{name} restarted", "data": {"service": name, "output": lines[-20:]}}
    raise ValueError(f"Unknown action {action}")


async def _control(ctx: JobContext) -> dict[str, Any]:
    # Serialize Docker CLI operations inside the admin process. The job hub
    # already has one admin worker, but this also protects against stale tasks
    # from a previous hub process during a restart.
    async with CONTROL_LOCK:
        return await _control_locked(ctx)


for _action in ("enable", "disable", "build", "restart"):
    runner.register(_action, _control)


app = create_service_app(
    "admin",
    "Open Studio Service Manager",
    "Builds, starts, stops and reports the health of every optional service on demand.",
    runner=runner,
    extra_routers=[router],
)
