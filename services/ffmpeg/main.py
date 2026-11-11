"""Open Studio FFmpeg service.

Exposes a complete operation catalog, synchronous probing and both queued and
synchronous media processing. Every long operation runs through the shared
JobRunner and reports progress parsed from ffmpeg's ``-progress pipe:1`` output.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException, Query

from openstudio_common import (
    INTERNAL_TOKEN,
    JOBHUB_URL,
    JobRunner,
    MediaError,
    create_service_app,
    env_float,
    env_int,
    jobhub_headers,
    resolve_path,
    utc_now,
)

from .catalog import OPERATIONS, build_catalog, operation_list
from .executor import PROCESSES, ExecutionHooks, describe_files, probe_media
from .operations import OperationResult, execute_operation

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ffmpeg")

VERSION = "1.0.0"
SYNC_TIMEOUT = env_float("FFMPEG_SYNC_TIMEOUT", 300.0)
JOB_TIMEOUT = env_int("FFMPEG_JOB_TIMEOUT", 86_400)
JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")

runner = JobRunner("ffmpeg")
router = APIRouter(prefix="/api/ffmpeg", tags=["ffmpeg"])
internal = APIRouter(prefix="/internal/ffmpeg", tags=["internal"])


def _validate_job_id(value: Any) -> str:
    job_id = str(value or "").strip()
    if not job_id:
        job_id = uuid.uuid4().hex[:16]
    if not JOB_ID_RE.match(job_id):
        raise ValueError("job_id may only contain letters, numbers, underscore and dash")
    return job_id


def _workdir(job_id: str) -> Path:
    directory = resolve_path("ffmpeg", job_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _operation_payload(body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    operation = str(body.get("operation") or "").strip()
    if operation not in OPERATIONS:
        raise HTTPException(status_code=422, detail=f"Unknown FFmpeg operation '{operation}'")
    options = body.get("options")
    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise HTTPException(status_code=422, detail="options must be an object")
    input_path = body.get("input_path")
    output_path = body.get("output_path")
    if input_path is not None and not isinstance(input_path, str):
        raise HTTPException(status_code=422, detail="input_path must be a string")
    if output_path is not None and not isinstance(output_path, str):
        raise HTTPException(status_code=422, detail="output_path must be a string")
    payload = {
        "operation": operation,
        "input_path": input_path or "",
        "output_path": output_path or "",
        "options": options,
    }
    return operation, payload


async def _output_summary(path: Path) -> dict[str, Any] | None:
    try:
        probe = await probe_media(path)
    except Exception:  # noqa: BLE001 - a raw operation may create a non-media file
        return None
    video = probe.get("video") or {}
    audio = probe.get("audio") or {}
    return {
        "path": probe.get("path"),
        "kind": probe.get("kind"),
        "duration": probe.get("duration"),
        "size": probe.get("size"),
        "format": probe.get("format_name"),
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": video.get("fps"),
        "video_codec": video.get("codec"),
        "audio_codec": audio.get("codec"),
        "sample_rate": audio.get("sample_rate"),
        "channels": audio.get("channels"),
    }


async def _build_result(
    operation: str,
    result: OperationResult,
    *,
    warnings: list[str] | None = None,
    elapsed: float | None = None,
) -> dict[str, Any]:
    data = dict(result.data or {})
    data["operation"] = operation
    if warnings:
        merged = list(data.get("warnings") or [])
        merged.extend(warnings)
        data["warnings"] = merged
    if elapsed is not None:
        data["elapsed_seconds"] = round(elapsed, 2)
    descriptors = describe_files(result.files)
    data["file_count"] = len(descriptors)
    if len(descriptors) == 1:
        summary = await _output_summary(result.files[0])
        if summary:
            data["output"] = summary
    return {"message": result.message or "Completed", "files": descriptors, "data": data}


async def _execute(
    operation: str,
    payload: dict[str, Any],
    *,
    job_id: str,
    report=None,
    check=None,
) -> dict[str, Any]:
    hooks = ExecutionHooks(job_id=job_id, report=report, check=check)
    started = asyncio.get_running_loop().time()
    result = await execute_operation(operation, payload, workdir=_workdir(job_id), hooks=hooks)
    elapsed = asyncio.get_running_loop().time() - started
    return await _build_result(operation, result, warnings=hooks.warnings, elapsed=elapsed)


def _job_handler(operation: str):
    async def handler(ctx) -> dict[str, Any]:
        payload = {
            "operation": operation,
            "input_path": ctx.params.get("input_path") or "",
            "output_path": ctx.params.get("output_path") or "",
            "options": ctx.params.get("options") or {},
        }
        if not isinstance(payload["options"], dict):
            raise ValueError("options must be an object")
        hooks = ExecutionHooks(job_id=ctx.job_id, report=ctx.report, check=ctx.check)
        started = asyncio.get_running_loop().time()
        log.info("job %s action=%s input=%s", ctx.job_id, operation, payload["input_path"])
        result = await execute_operation(operation, payload, workdir=_workdir(ctx.job_id), hooks=hooks)
        elapsed = asyncio.get_running_loop().time() - started
        if hooks.warnings:
            await ctx.client.progress(warnings=hooks.warnings)
        return await _build_result(operation, result, warnings=hooks.warnings, elapsed=elapsed)

    handler.__name__ = f"job_{operation}"
    return handler


for _operation in OPERATIONS:
    runner.register(_operation, _job_handler(_operation))


async def _submit_job(operation: str, payload: dict[str, Any], title: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "component": "ffmpeg",
        "action": operation,
        "title": title or f"FFmpeg · {operation.replace('_', ' ')}",
        "params": payload,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=jobhub_headers()) as client:
            response = await client.post(f"{JOBHUB_URL}/api/jobs", json=body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Job hub unreachable: {exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Job hub rejected the job: {response.text[:1000]}")
    return response.json()


async def _sync_timeout(body: dict[str, Any]) -> float:
    raw = body.get("timeout")
    if raw is None:
        return max(1.0, min(SYNC_TIMEOUT, float(JOB_TIMEOUT)))
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="timeout must be a number of seconds") from exc
    if value <= 0 or value > 86_400:
        raise HTTPException(status_code=422, detail="timeout must be between 1 and 86400 seconds")
    return value


async def _run_sync(body: dict[str, Any]) -> dict[str, Any]:
    operation, payload = _operation_payload(body)
    job_id = _validate_job_id(body.get("job_id") or f"sync-{uuid.uuid4().hex[:12]}")
    timeout = await _sync_timeout(body)
    try:
        result = await asyncio.wait_for(_execute(operation, payload, job_id=job_id), timeout=timeout)
    except asyncio.TimeoutError as exc:
        await PROCESSES.cancel(job_id)
        raise HTTPException(status_code=504, detail=f"FFmpeg operation timed out after {timeout:g}s") from exc
    except MediaError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    result["job_id"] = job_id
    return result


@router.get("/catalog")
async def catalog(refresh: bool = Query(False)) -> dict[str, Any]:
    data = await build_catalog(refresh=refresh)
    return {**data, "service": "ffmpeg", "version": VERSION, "generated_at": utc_now(), "active_processes": PROCESSES.active()}


@router.get("/operations")
async def operations() -> dict[str, Any]:
    items = operation_list()
    return {"items": items, "total": len(items)}


@router.post("/probe")
async def probe(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("path") or payload.get("input_path") or payload.get("file")
    if not raw or not isinstance(raw, str):
        raise HTTPException(status_code=422, detail="path is required")
    path = resolve_path(raw)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {raw}")
    if path.is_dir():
        raise HTTPException(status_code=422, detail="path must point to a file")
    try:
        return await probe_media(path)
    except MediaError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/run")
async def run(payload: dict[str, Any]) -> dict[str, Any]:
    operation, normalized = _operation_payload(payload)
    job = await _submit_job(operation, normalized, payload.get("title"))
    return job


@router.post("/run-sync")
async def run_sync(payload: dict[str, Any]) -> dict[str, Any]:
    return await _run_sync(payload)


@router.get("/active")
async def active() -> dict[str, Any]:
    return {"processes": PROCESSES.active(), "total": len(PROCESSES.active())}


@internal.post("/run")
async def internal_run(payload: dict[str, Any], x_internal_token: str = Header(default="")) -> dict[str, Any]:
    if x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid internal token")
    operation, normalized = _operation_payload(payload)
    if payload.get("sync", True):
        return await _run_sync(payload)
    job = await _submit_job(operation, normalized, payload.get("title"))
    return {"job": job, "job_id": job.get("id"), "sync": False}


@internal.get("/processes")
async def internal_processes(x_internal_token: str = Header(default="")) -> dict[str, Any]:
    if x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid internal token")
    return {"processes": PROCESSES.active(), "total": len(PROCESSES.active())}


@internal.post("/finalize")
async def internal_finalize(payload: dict[str, Any], x_internal_token: str = Header(default="")) -> dict[str, Any]:
    """Docs-service compatibility: finalize/normalize synthesized speech.

    Accepts ``{source_path, output_path, format, normalize_audio, title}`` and
    returns a normal ffmpeg result whose ``path`` is files-relative.
    """
    if x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid internal token")
    source = payload.get("source_path") or payload.get("input_path")
    if not source:
        raise HTTPException(status_code=422, detail="source_path is required")
    fmt = str(payload.get("format") or "mp3").lower().lstrip(".")
    if fmt not in {"mp3", "wav", "flac", "aac", "opus", "ogg", "m4a"}:
        fmt = "mp3"
    body = {
        "operation": "extract_audio",
        "input_path": source,
        "output_path": payload.get("output_path") or "",
        "options": {
            "format": fmt,
            "normalize": bool(payload.get("normalize_audio")),
            "target_lufs": payload.get("target_lufs", -16),
        },
        "timeout": payload.get("timeout", 600),
        "job_id": payload.get("job_id") or f"finalize-{uuid.uuid4().hex[:12]}",
    }
    result = await _run_sync(body)
    files = result.get("files") or []
    if files:
        result["path"] = files[0].get("path")
        result["relative_path"] = files[0].get("path")
    result["message"] = payload.get("title") and f"Finalized {payload['title']}" or "Audio finalized"
    return result


async def _shutdown() -> None:
    await PROCESSES.cancel_all()


app = create_service_app(
    "ffmpeg",
    "Open Studio FFmpeg",
    "FFmpeg and ffprobe media operations for video, audio, image and subtitle tooling.",
    version=VERSION,
    runner=runner,
    extra_routers=[router, internal],
    on_shutdown=_shutdown,
)


@app.exception_handler(MediaError)
async def media_error_handler(_request, exc: MediaError):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=500, content={"detail": str(exc)})
