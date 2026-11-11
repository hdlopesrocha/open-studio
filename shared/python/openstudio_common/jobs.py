"""Client helpers and cancellation registry for the global job hub."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx

from .config import JOBHUB_URL, SERVICE_NAME, jobhub_headers

log = logging.getLogger("openstudio.jobs")


class JobCancelled(Exception):
    """Raised inside a component worker when the user cancels a job."""


class JobClient:
    """Reports progress to the central job hub and checks cancellations."""

    def __init__(self, job_id: str, timeout: float = 30.0) -> None:
        self.job_id = job_id
        self._timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout, headers=jobhub_headers())

    async def progress(
        self,
        progress: float | None = None,
        stage: str | None = None,
        message: str | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        payload: dict[str, Any] = {}
        if progress is not None:
            payload["progress"] = max(0.0, min(100.0, float(progress)))
        if stage:
            payload["stage"] = stage
        if message:
            payload["message"] = message
        if warnings:
            payload["warnings"] = warnings
        if not payload:
            return
        try:
            await self._client.post(f"{JOBHUB_URL}/internal/jobs/{self.job_id}/progress", json=payload)
        except Exception:  # noqa: BLE001 - progress must never kill a job
            log.warning("Could not report progress for job %s", self.job_id, exc_info=True)

    async def cancelled(self) -> bool:
        try:
            response = await self._client.get(f"{JOBHUB_URL}/internal/jobs/{self.job_id}/cancel-state")
            if response.status_code == 200:
                return bool(response.json().get("cancel_requested"))
        except Exception:  # noqa: BLE001
            log.warning("Could not read cancel state for job %s", self.job_id, exc_info=True)
        return False

    async def artifact(self, artifact: dict[str, Any]) -> None:
        try:
            await self._client.post(f"{JOBHUB_URL}/internal/jobs/{self.job_id}/artifacts", json=artifact)
        except Exception:  # noqa: BLE001
            log.warning("Could not register artifact for job %s", self.job_id, exc_info=True)

    async def close(self) -> None:
        await self._client.aclose()


class CancellationRegistry:
    """Per-process map of job id -> cancel event, filled by the internal API."""

    def __init__(self) -> None:
        self._events: dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()

    async def register(self, job_id: str) -> asyncio.Event:
        async with self._lock:
            event = self._events.setdefault(job_id, asyncio.Event())
            return event

    async def cancel(self, job_id: str) -> bool:
        async with self._lock:
            event = self._events.get(job_id)
            if event is None:
                event = asyncio.Event()
                self._events[job_id] = event
            event.set()
            return True

    async def clear(self, job_id: str) -> None:
        async with self._lock:
            self._events.pop(job_id, None)

    async def raise_if_cancelled(self, job_id: str) -> None:
        async with self._lock:
            event = self._events.get(job_id)
        if event is not None and event.is_set():
            raise JobCancelled("Job cancelled by the user")


@dataclass
class JobContext:
    """Everything a component's internal job handler needs."""

    job_id: str
    action: str
    params: dict[str, Any]
    client: JobClient
    registry: CancellationRegistry
    warnings: list[str] = field(default_factory=list)

    async def report(
        self,
        progress: float | None = None,
        stage: str | None = None,
        message: str | None = None,
    ) -> None:
        await self.client.progress(progress, stage, message)

    async def check(self) -> None:
        await self.registry.raise_if_cancelled(self.job_id)

    async def execute(
        self,
        fn: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Run an awaitable unless the job was cancelled, mapping exceptions."""
        await self.check()
        return await fn(*args, **kwargs)


def submitable_component() -> str:
    return SERVICE_NAME


def job_result(
    *,
    files: list[dict[str, Any]] | None = None,
    data: dict[str, Any] | None = None,
    message: str = "Completed",
) -> dict[str, Any]:
    payload: dict[str, Any] = {"message": message, "files": files or []}
    if data:
        payload.update(data)
    return payload
