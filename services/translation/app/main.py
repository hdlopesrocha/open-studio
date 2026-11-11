"""Open Studio translation service API."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.concurrency import run_in_threadpool

from openstudio_common import INTERNAL_TOKEN, JobRunner, create_service_app

from .config import settings
from .languages import language_catalogue
from .schemas import DetectRequest, TranslateRequest
from .service import (
    ENGINE,
    detect,
    perform_translation,
    prepare_translation,
    submit_translation_job,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("translation")

router = APIRouter(prefix="/api/translate", tags=["translation"])
internal = APIRouter(prefix="/internal", tags=["internal"])
runner = JobRunner("translation")

_idle_task: asyncio.Task[Any] | None = None


def verify_internal(token: str) -> None:
    if token != INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid internal token")


# -- catalogue -------------------------------------------------------------


@router.get("/status")
async def status() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "translation",
        **ENGINE.status(),
        "languages": {
            "opus": ["pt", "en"],
            "nllb": [entry["code"] for entry in language_catalogue()],
        },
    }


@router.get("/languages")
async def languages() -> dict[str, Any]:
    items = language_catalogue()
    codes = [entry["code"] for entry in items]
    variants = ["pt-PT", "pt-BR"]
    target_codes = ["en", "pt", *variants] + [
        code for code in codes if code not in {"en", "pt"}
    ]
    return {
        "items": items,
        "total": len(items),
        "languages": items,
        "source": ["auto", *target_codes],
        "target": target_codes,
        "pairs": [
            {"source": "pt", "target": "en"},
            {"source": "en", "target": "pt"},
        ],
        "variants": {
            "pt": ["pt", "pt-PT", "pt-BR"],
            "zh-Hant": ["zh-Hant", "zh-TW"],
        },
        "opus_pairs": [
            {"source": "pt", "target": "en", "model": "opus-mt-pt-en"},
            {"source": "en", "target": "pt", "model": "opus-mt-en-pt"},
        ],
        "notes": [
            "OPUS-MT covers Portuguese ↔ English and is always preferred for that pair.",
            "Install NLLB-200 to translate the other languages.",
        ],
    }


@router.get("/models")
async def models() -> dict[str, Any]:
    return ENGINE.models_payload()


# -- translation -----------------------------------------------------------


@router.post("/translate")
async def translate(request: TranslateRequest) -> dict[str, Any]:
    return await run_in_threadpool(perform_translation, request)


@router.post("/translate/job")
async def translate_job(request: TranslateRequest) -> dict[str, Any]:
    # Validate before queueing so obvious bad requests fail immediately.
    await run_in_threadpool(prepare_translation, request)
    return await submit_translation_job(request)


@router.post("/detect")
async def detect_language(payload: DetectRequest) -> dict[str, Any]:
    return await run_in_threadpool(detect, payload.text)


# -- internal synchronous endpoints for the documents pipeline --------------


@internal.post("/translate")
async def internal_translate(
    request: TranslateRequest,
    x_internal_token: str = Header(default=""),
) -> dict[str, Any]:
    verify_internal(x_internal_token)
    return await run_in_threadpool(perform_translation, request)


@internal.post("/detect")
async def internal_detect(
    payload: DetectRequest,
    x_internal_token: str = Header(default=""),
) -> dict[str, Any]:
    verify_internal(x_internal_token)
    return await run_in_threadpool(detect, payload.text)


@internal.get("/translation/models")
async def internal_models(x_internal_token: str = Header(default="")) -> dict[str, Any]:
    verify_internal(x_internal_token)
    return ENGINE.models_payload()


# -- jobs ------------------------------------------------------------------


@runner.action("translate")
async def translate_action(ctx) -> dict[str, Any]:
    from .service import run_translate_job

    return await run_translate_job(ctx)


# -- lifecycle -------------------------------------------------------------


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
        "Translation service ready: model dir=%s, threads=%s, idle unload=%ss",
        settings.models_dir,
        settings.cpu_threads,
        settings.idle_unload_seconds,
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
    "translation",
    "Open Studio Translation",
    (
        "Local Portuguese↔English OPUS-MT translation with optional multilingual "
        "NLLB-200, page-marker preservation, glossaries and batch job support."
    ),
    runner=runner,
    extra_routers=[router, internal],
    on_startup=_startup,
    on_shutdown=_shutdown,
)
