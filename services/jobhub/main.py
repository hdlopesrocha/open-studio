"""Open Studio central job hub.

One persistent queue per component, with independently configurable concurrency.
Every service talks to the same API, so the Vue app has one global job drawer
while music, video, voice, documents, subtitles, ffmpeg, yt-dlp and QVAC can
process in parallel.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx
from fastapi import Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from openstudio_common import (
    INTERNAL_TOKEN,
    STATE_ROOT,
    create_service_app,
    env_int,
    jobhub_headers,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("jobhub")

DB_PATH = STATE_ROOT / "jobs.db"
JOB_TIMEOUT = env_int("JOB_TIMEOUT_SECONDS", 86_400)

DEFAULT_COMPONENTS = {
    "admin": (8000, 1),
    "music": (8000, 1),
    "dj": (8000, 1),
    "video": (8000, 2),
    "voice": (8000, 1),
    "srt": (8000, 1),
    "imagegen": (8000, 1),
    "translation": (8000, 2),
    "summary": (8000, 1),
    "pdf": (8000, 2),
    "docs": (8000, 2),
    "ffmpeg": (8000, 2),
    "ytdlp": (8000, 2),
    "qvac": (8000, 1),
    "models": (8000, 1),
    "llm": (8000, 2),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Store:
    def __init__(self, path=DB_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init()

    def _init(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    component TEXT NOT NULL,
                    action TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT,
                    message TEXT,
                    progress REAL NOT NULL DEFAULT 0,
                    params TEXT NOT NULL DEFAULT '{}',
                    result TEXT,
                    error TEXT,
                    warnings TEXT NOT NULL DEFAULT '[]',
                    artifacts TEXT NOT NULL DEFAULT '[]',
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    parent_id TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_component_status ON jobs(component, status);
                CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
                """
            )
            self._conn.commit()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        for key, default in (("params", "{}"), ("result", "null"), ("warnings", "[]"), ("artifacts", "[]")):
            try:
                data[key] = json.loads(data.get(key) or default)
            except json.JSONDecodeError:
                data[key] = json.loads(default)
        data["cancel_requested"] = bool(data.get("cancel_requested"))
        return data

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        job_id = payload.get("id") or uuid.uuid4().hex[:16]
        now = utc_now()
        component = str(payload.get("component") or "").strip()
        action = str(payload.get("action") or "").strip()
        if not component or component not in COMPONENTS:
            raise ValueError(f"Unknown or missing component '{component}'")
        if not action:
            raise ValueError("action is required")
        title = str(payload.get("title") or "").strip() or f"{component} · {action.replace('_', ' ')}"
        with self._lock:
            self._conn.execute(
                """INSERT INTO jobs
                (id, component, action, title, status, stage, message, progress, params, warnings,
                 artifacts, parent_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'queued', 'Queued', 'Waiting for a worker.', 0, ?, '[]', '[]', ?, ?, ?)""",
                (
                    job_id,
                    component,
                    action,
                    title[:200],
                    json.dumps(payload.get("params") or {}, ensure_ascii=False),
                    payload.get("parent_id"),
                    now,
                    now,
                ),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._row(row)  # type: ignore[return-value]

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._row(row)

    def list(
        self,
        component: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
        parent_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        where = ["1=1"]
        args: list[Any] = []
        if component:
            where.append("component=?")
            args.append(component)
        if status:
            statuses = [part.strip() for part in status.split(",") if part.strip()]
            where.append("status IN (" + ",".join("?" for _ in statuses) + ")")
            args.extend(statuses)
        if parent_id:
            where.append("parent_id=?")
            args.append(parent_id)
        clause = " AND ".join(where)
        with self._lock:
            total = self._conn.execute(f"SELECT COUNT(*) FROM jobs WHERE {clause}", args).fetchone()[0]
            rows = self._conn.execute(
                f"SELECT * FROM jobs WHERE {clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
        return [self._row(r) for r in rows], total  # type: ignore[misc]

    def update(self, job_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {
            "status",
            "stage",
            "message",
            "progress",
            "result",
            "error",
            "warnings",
            "artifacts",
            "cancel_requested",
            "attempts",
            "started_at",
            "finished_at",
        }
        updates = []
        args: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key in {"result", "warnings", "artifacts"}:
                value = json.dumps(value, ensure_ascii=False)
            if key == "cancel_requested":
                value = 1 if value else 0
            updates.append(f"{key}=?")
            args.append(value)
        if not updates:
            return self.get(job_id)
        updates.append("updated_at=?")
        args.append(utc_now())
        with self._lock:
            self._conn.execute(f"UPDATE jobs SET {', '.join(updates)} WHERE id=?", [*args, job_id])
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._row(row)

    def append_warning(self, job_id: str, warning: str) -> None:
        job = self.get(job_id)
        if not job:
            return
        warnings = list(job.get("warnings") or [])
        if warning not in warnings:
            warnings.append(warning)
            self.update(job_id, warnings=warnings[-100:])

    def append_artifacts(self, job_id: str, artifacts: list[dict[str, Any]]) -> None:
        job = self.get(job_id)
        if not job:
            return
        existing = list(job.get("artifacts") or [])
        existing.extend(artifacts)
        self.update(job_id, artifacts=existing[-500:])

    def delete(self, job_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
            self._conn.commit()
            return cursor.rowcount > 0

    def counts(self) -> dict[str, dict[str, int]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT component, status, COUNT(*) AS n FROM jobs GROUP BY component, status"
            ).fetchall()
        result: dict[str, dict[str, int]] = {}
        for row in rows:
            result.setdefault(row["component"], {})[row["status"]] = row["n"]
        return result

    def pending(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE status IN ('queued','running','canceling') ORDER BY created_at ASC"
            ).fetchall()
        return [self._row(r) for r in rows]  # type: ignore[misc]


def component_config() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name, (port, default_concurrency) in DEFAULT_COMPONENTS.items():
        upper = name.upper().replace("-", "_")
        url = os.getenv(f"{upper}_URL", f"http://{name}:{port}").rstrip("/")
        concurrency = env_int(f"{upper}_CONCURRENCY", default_concurrency)
        result[name] = {"url": url, "concurrency": max(1, concurrency)}
    return result


COMPONENTS = component_config()
STORE = Store()
QUEUES: dict[str, asyncio.Queue[str]] = {}
WORKERS: list[asyncio.Task[Any]] = []
SUBSCRIBERS: set[asyncio.Queue[dict[str, Any]]] = set()
STOP = asyncio.Event()


def event(event_type: str, job: dict[str, Any]) -> dict[str, Any]:
    return {"type": event_type, "job": job, "at": utc_now()}


async def broadcast(event_type: str, job: dict[str, Any] | None) -> None:
    if job is None:
        return
    payload = event(event_type, job)
    for queue in list(SUBSCRIBERS):
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            SUBSCRIBERS.discard(queue)


async def sse_stream(request: Request, queue: asyncio.Queue[dict[str, Any]]) -> AsyncIterator[bytes]:
    SUBSCRIBERS.add(queue)
    try:
        yield b": connected\n\n"
        while True:
            if await request.is_disconnected():
                break
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=15)
                yield f"event: {payload['type']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()
            except asyncio.TimeoutError:
                yield b": ping\n\n"
    finally:
        SUBSCRIBERS.discard(queue)


async def execute(job: dict[str, Any]) -> None:
    job_id = job["id"]
    component = job["component"]
    config = COMPONENTS[component]
    current = STORE.get(job_id)
    if not current or current["cancel_requested"] or current["status"] == "canceled":
        return
    STORE.update(job_id, status="running", stage="Starting", message="Dispatching to worker.", started_at=utc_now(), attempts=int(current.get("attempts") or 0) + 1)
    await broadcast("job.updated", STORE.get(job_id))
    headers = {"X-Internal-Token": INTERNAL_TOKEN, "Content-Type": "application/json"}
    payload = {"job_id": job_id, "action": job["action"], "params": job.get("params") or {}}
    try:
        timeout = httpx.Timeout(connect=20.0, read=None, write=60.0, pool=20.0)
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            response = await client.post(f"{config['url']}/internal/jobs/run", json=payload)
        latest = STORE.get(job_id) or {}
        if response.status_code >= 400:
            detail = response.text
            try:
                detail = response.json().get("detail", detail)
            except Exception:  # noqa: BLE001
                pass
            STORE.update(
                job_id,
                status="canceled" if latest.get("cancel_requested") else "failed",
                stage="Cancelled" if latest.get("cancel_requested") else "Failed",
                message=str(detail)[:2000],
                error=str(detail)[:4000],
                finished_at=utc_now(),
                progress=latest.get("progress", 0),
            )
        else:
            body = response.json()
            if body.get("cancelled") or latest.get("cancel_requested"):
                STORE.update(
                    job_id,
                    status="canceled",
                    stage="Cancelled",
                    message="Cancelled by the user.",
                    finished_at=utc_now(),
                )
            else:
                STORE.update(
                    job_id,
                    status="completed",
                    stage="Complete",
                    message=(body.get("result") or {}).get("message", "Completed"),
                    progress=100,
                    result=body.get("result") or {},
                    finished_at=utc_now(),
                )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("Job %s failed", job_id)
        STORE.update(
            job_id,
            status="failed",
            stage="Failed",
            message=f"Worker error: {exc}",
            error=str(exc)[:4000],
            finished_at=utc_now(),
        )
    await broadcast("job.updated", STORE.get(job_id))


async def worker(component: str) -> None:
    queue = QUEUES[component]
    while not STOP.is_set():
        try:
            job_id = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        job = STORE.get(job_id)
        if not job or job["status"] not in {"queued", "canceling"}:
            queue.task_done()
            continue
        if job.get("cancel_requested"):
            STORE.update(job_id, status="canceled", stage="Cancelled", message="Cancelled before starting.", finished_at=utc_now())
            await broadcast("job.updated", STORE.get(job_id))
            queue.task_done()
            continue
        try:
            await asyncio.wait_for(execute(job), timeout=JOB_TIMEOUT)
        except asyncio.TimeoutError:
            STORE.update(job_id, status="failed", stage="Timed out", message=f"Job exceeded {JOB_TIMEOUT}s", finished_at=utc_now())
            await broadcast("job.updated", STORE.get(job_id))
            await cancel_remote(job_id, component)
        finally:
            queue.task_done()


async def cancel_remote(job_id: str, component: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=15.0, headers={"X-Internal-Token": INTERNAL_TOKEN}) as client:
            await client.post(f"{COMPONENTS[component]['url']}/internal/jobs/{job_id}/cancel")
    except Exception:  # noqa: BLE001
        log.warning("Could not deliver cancellation for %s", job_id, exc_info=True)


async def _startup_hub() -> None:
    for name in COMPONENTS:
        if name in QUEUES:
            continue
        QUEUES[name] = asyncio.Queue()
        for _ in range(COMPONENTS[name]["concurrency"]):
            WORKERS.append(asyncio.create_task(worker(name), name=f"worker-{name}"))
    for job in STORE.pending():
        if job["status"] in {"running", "canceling"}:
            # Do not replay a long-running job after a hub or host restart. A
            # Docker build could otherwise block the component queue forever.
            STORE.update(
                job["id"],
                status="failed",
                stage="Interrupted",
                message="The job hub restarted while this job was running. Retry it from the UI.",
                error="Interrupted by a job hub or host restart.",
                finished_at=utc_now(),
                cancel_requested=False,
            )
            await broadcast("job.updated", STORE.get(job["id"]))
            continue
        if job["component"] in QUEUES:
            QUEUES[job["component"]].put_nowait(job["id"])
    log.info("Job hub ready with %s components", len(COMPONENTS))


async def _shutdown_hub() -> None:
    STOP.set()
    for task in WORKERS:
        task.cancel()
    await asyncio.gather(*WORKERS, return_exceptions=True)


app = create_service_app(
    "jobhub",
    "Open Studio Job Hub",
    "One persistent queue per component with parallel execution across components.",
    on_startup=_startup_hub,
    on_shutdown=_shutdown_hub,
)


def check_internal(token: str) -> None:
    if token != INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid internal token")


@app.get("/api/jobs")
async def list_jobs(
    component: str | None = None,
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    parent_id: str | None = None,
) -> dict[str, Any]:
    items, total = STORE.list(component, status, limit, offset, parent_id)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.post("/api/jobs")
async def create_job(payload: dict[str, Any]) -> dict[str, Any]:
    job = STORE.create(payload)
    QUEUES[job["component"]].put_nowait(job["id"])
    await broadcast("job.created", job)
    return job


@app.get("/api/jobs/queues")
async def queues() -> dict[str, Any]:
    counts = STORE.counts()
    return {
        "components": [
            {
                "component": name,
                "concurrency": cfg["concurrency"],
                "queued": counts.get(name, {}).get("queued", 0),
                "running": counts.get(name, {}).get("running", 0)
                + counts.get(name, {}).get("canceling", 0),
                "completed": counts.get(name, {}).get("completed", 0),
                "failed": counts.get(name, {}).get("failed", 0),
            }
            for name, cfg in COMPONENTS.items()
        ]
    }


@app.get("/api/jobs/events")
async def events(request: Request) -> StreamingResponse:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)
    return StreamingResponse(sse_stream(request, queue), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    job = STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request) -> StreamingResponse:
    if not STORE.get(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
    SUBSCRIBERS.add(queue)

    async def stream() -> AsyncIterator[bytes]:
        try:
            yield b": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                    if payload["job"]["id"] != job_id:
                        continue
                    yield f"event: {payload['type']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()
                    if payload["job"]["status"] in {"completed", "failed", "canceled"}:
                        break
                except asyncio.TimeoutError:
                    yield b": ping\n\n"
        finally:
            SUBSCRIBERS.discard(queue)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict[str, Any]:
    job = STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] in {"completed", "failed", "canceled"}:
        return job
    if job["status"] == "queued":
        STORE.update(job_id, status="canceled", stage="Cancelled", message="Cancelled before starting.", cancel_requested=True, finished_at=utc_now())
    else:
        STORE.update(job_id, status="canceling", stage="Cancelling", message="Cancellation requested.", cancel_requested=True)
        await cancel_remote(job_id, job["component"])
    await broadcast("job.updated", STORE.get(job_id))
    return STORE.get(job_id)  # type: ignore[return-value]


@app.post("/api/jobs/{job_id}/retry")
async def retry_job(job_id: str) -> dict[str, Any]:
    job = STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    clone = STORE.create(
        {
            "component": job["component"],
            "action": job["action"],
            "title": job["title"],
            "params": job["params"],
            "parent_id": job_id,
        }
    )
    QUEUES[clone["component"]].put_nowait(clone["id"])
    await broadcast("job.created", clone)
    return clone


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str) -> dict[str, Any]:
    job = STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] not in {"completed", "failed", "canceled"}:
        raise HTTPException(status_code=409, detail="Cannot delete an active job")
    STORE.delete(job_id)
    return {"ok": True}


# Internal callbacks -------------------------------------------------------

@app.post("/internal/jobs/{job_id}/progress")
async def progress(job_id: str, payload: dict[str, Any], x_internal_token: str = Header(default="")) -> dict[str, Any]:
    check_internal(x_internal_token)
    job = STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    updates: dict[str, Any] = {}
    if "progress" in payload:
        updates["progress"] = max(float(job.get("progress") or 0), min(100.0, float(payload["progress"])))
    if payload.get("stage"):
        updates["stage"] = str(payload["stage"])[:200]
    if payload.get("message"):
        updates["message"] = str(payload["message"])[:2000]
    if payload.get("warnings"):
        for warning in payload["warnings"]:
            STORE.append_warning(job_id, str(warning)[:1000])
        job = STORE.get(job_id) or job
        updates["warnings"] = job.get("warnings") or []
    updated = STORE.update(job_id, **updates) if updates else job
    await broadcast("job.updated", updated)
    return {"ok": True}


@app.get("/internal/jobs/{job_id}/cancel-state")
async def cancel_state(job_id: str, x_internal_token: str = Header(default="")) -> dict[str, Any]:
    check_internal(x_internal_token)
    job = STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, "cancel_requested": job.get("cancel_requested", False)}


@app.post("/internal/jobs/{job_id}/artifacts")
async def artifacts(job_id: str, artifact: dict[str, Any], x_internal_token: str = Header(default="")) -> dict[str, Any]:
    check_internal(x_internal_token)
    STORE.append_artifacts(job_id, [artifact])
    await broadcast("job.updated", STORE.get(job_id))
    return {"ok": True}


@app.get("/internal/jobs/{job_id}")
async def internal_get(job_id: str, x_internal_token: str = Header(default="")) -> dict[str, Any]:
    check_internal(x_internal_token)
    job = STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/internal/components")
async def internal_components(x_internal_token: str = Header(default="")) -> dict[str, Any]:
    check_internal(x_internal_token)
    return {"components": COMPONENTS}


@app.get("/internal/events")
async def internal_events(request: Request, x_internal_token: str = Header(default="")) -> StreamingResponse:
    check_internal(x_internal_token)
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)
    return StreamingResponse(sse_stream(request, queue), media_type="text/event-stream")
