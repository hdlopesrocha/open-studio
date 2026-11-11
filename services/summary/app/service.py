"""Summary request preparation, execution and persistence."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

from openstudio_common import (
    JOBHUB_URL,
    JobContext,
    atomic_write_text,
    file_info,
    job_result,
    jobhub_headers,
    resolve_path,
)

from .config import settings
from .engine import SummarizationEngine, SummaryOptions
from .languages import SummaryLanguages, resolve_languages
from .schemas import SummaryRequest

logger = logging.getLogger(__name__)

ENGINE = SummarizationEngine(settings)
_SAFE_JOB_ID = re.compile(r"[^A-Za-z0-9_-]+")


@dataclass
class PreparedSummary:
    request: SummaryRequest
    languages: SummaryLanguages
    options: SummaryOptions
    started: float


def prepare_summary(request: SummaryRequest) -> PreparedSummary:
    started = time.time()
    try:
        languages = resolve_languages(
            request.source_language,
            request.language,
            request.text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    ENGINE.resolve_model(request.model, languages.source)
    options = SummaryOptions(**request.options())
    return PreparedSummary(
        request=request,
        languages=languages,
        options=options,
        started=started,
    )


def perform_summary(
    request: SummaryRequest,
    progress: Callable[[float, str], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    prepared = prepare_summary(request)
    result = ENGINE.summarize(
        request.text,
        prepared.languages,
        prepared.options,
        model_requested=request.model,
        progress=progress,
        cancel=cancel,
    )
    result["duration_seconds"] = round(time.time() - prepared.started, 2)
    return result


def artifact_path(job_id: str) -> Path:
    safe = _SAFE_JOB_ID.sub("_", job_id or "job")[:120] or "job"
    return resolve_path("documents", "summary", f"{safe}.txt")


def save_text_artifact(job_id: str, text: str) -> Path:
    path = artifact_path(job_id)
    atomic_write_text(path, text)
    return path


async def run_summarize_job(ctx: JobContext) -> dict[str, Any]:
    from .jobutil import run_blocking

    request = SummaryRequest.model_validate(ctx.params or {})
    prepared = await run_in_threadpool(prepare_summary, request)
    await ctx.report(2, stage="summarize", message="Summary model ready.")
    result = await run_blocking(
        ctx,
        lambda progress, cancel: perform_summary(
            request, progress=progress, cancel=cancel
        ),
        stage="summarize",
        start_progress=3,
        end_progress=96,
    )
    path = save_text_artifact(ctx.job_id, result["summary"])
    await ctx.report(98, stage="summarize", message="Saved the summary artifact.")
    info = file_info(path)
    return job_result(
        files=[info],
        data={
            "text_path": info["path"],
            "summary": result["summary"],
            "source_language": result["source_language"],
            "language": result["language"],
            "length": result["length"],
            "translated": result["translated"],
            "model": result["model"],
            "stats": {
                "input_words": result["input_words"],
                "output_words": result["output_words"],
                "chunk_count": result["chunk_count"],
                "hierarchy_levels": result["hierarchy_levels"],
                "parameters": result["parameters"],
            },
            "warnings": result["warnings"],
            "duration_seconds": result["duration_seconds"],
        },
        message=(
            f"Summary ready ({result['output_words']:,} words, "
            f"{result['chunk_count']} chunk(s))."
        ),
    )


async def submit_summary_job(request: SummaryRequest) -> dict[str, Any]:
    payload = {
        "component": "summary",
        "action": "summarize",
        "title": f"Summarize ({request.length})",
        "params": request.model_dump(mode="json", exclude_none=True),
    }
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=jobhub_headers()) as client:
            response = await client.post(f"{JOBHUB_URL}/api/jobs", json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="The job hub is unavailable, so the summary job could not be queued.",
        ) from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise HTTPException(status_code=502, detail=f"Could not queue summary job: {detail}")
    return response.json()
