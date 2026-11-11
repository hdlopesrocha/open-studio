"""Open Studio summarization service API."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.concurrency import run_in_threadpool

from openstudio_common import INTERNAL_TOKEN, JobRunner, create_service_app

from .config import settings
from .engine import build_languages_payload, build_lengths
from .schemas import SummaryRequest
from .service import (
    ENGINE,
    perform_summary,
    prepare_summary,
    submit_summary_job,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("summary")

router = APIRouter(prefix="/api/summary", tags=["summary"])
internal = APIRouter(prefix="/internal", tags=["internal"])
runner = JobRunner("summary")
_idle_task: asyncio.Task[Any] | None = None


def verify_internal(token: str) -> None:
    if token != INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid internal token")


@router.get("/status")
async def status() -> dict[str, Any]:
    return {"status": "ok", "service": "summary", **ENGINE.status()}


@router.get("/lengths")
async def lengths() -> dict[str, Any]:
    items = build_lengths(settings)
    return {
        "items": items,
        "lengths": items,
        "total": len(items),
        "languages": build_languages_payload(),
        "default": "medium",
    }


@router.get("/languages")
async def languages() -> dict[str, Any]:
    items = build_languages_payload()
    return {
        "items": items,
        "languages": items,
        "total": len(items),
        "source": ["auto", "en", "pt", "pt-PT", "pt-BR"],
    }


@router.get("/models")
async def models() -> dict[str, Any]:
    return ENGINE.models_payload()


@router.post("/summarize")
async def summarize(request: SummaryRequest) -> dict[str, Any]:
    return await run_in_threadpool(perform_summary, request)


@router.post("/summarize/job")
async def summarize_job(request: SummaryRequest) -> dict[str, Any]:
    await run_in_threadpool(prepare_summary, request)
    return await submit_summary_job(request)


@internal.post("/summarize")
async def internal_summarize(
    request: SummaryRequest,
    x_internal_token: str = Header(default=""),
) -> dict[str, Any]:
    verify_internal(x_internal_token)
    return await run_in_threadpool(perform_summary, request)


@internal.get("/summary/catalogue")
async def internal_catalogue(x_internal_token: str = Header(default="")) -> dict[str, Any]:
    verify_internal(x_internal_token)
    return {
        "lengths": build_lengths(settings),
        "languages": build_languages_payload(),
        "models": ENGINE.models_payload(),
        "status": ENGINE.status(),
    }


@runner.action("summarize")
async def summarize_action(ctx) -> dict[str, Any]:
    from .service import run_summarize_job

    return await run_summarize_job(ctx)


async def _idle_unload_loop() -> None:
    while True:
        try:
            await asyncio.sleep(60)
            await run_in_threadpool(ENGINE.maybe_unload_idle)
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            logger.exception("Idle model unload failed")


async def _startup() -> None:
    global _idle_task
    if settings.idle_unload_seconds:
        _idle_task = asyncio.create_task(_idle_unload_loop())
    logger.info(
        "Summary service ready: model dir=%s, threads=%s",
        settings.models_dir,
        settings.cpu_threads,
    )


async def _shutdown() -> None:
    global _idle_task
    if _idle_task:
        _idle_task.cancel()
        try:
            await _idle_task
        except (asyncio.CancelledError, Exception):
            pass
        _idle_task = None
    await run_in_threadpool(ENGINE.unload)


app = create_service_app(
    "summary",
    "Open Studio Summary",
    (
        "Local T5 summarization with length budgets, token-aware chunking, "
        "hierarchical map-reduce and optional cross-language translation."
    ),
    runner=runner,
    extra_routers=[router, internal],
    on_startup=_startup,
    on_shutdown=_shutdown,
)
