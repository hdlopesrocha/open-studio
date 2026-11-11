"""Translation request preparation, execution and persistence."""

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
from .engine import (
    ModelSelection,
    TranslationEngine,
    TranslationOptions,
    build_plain_text,
    pages_from_segments,
)
from .languages import (
    Detection,
    ResolvedLanguage,
    detect_language_detailed,
    normalize_language,
    resolved_language,
)
from .schemas import TranslateRequest
from .segments import segments_from_text

logger = logging.getLogger(__name__)

ENGINE = TranslationEngine(settings)

_SAFE_JOB_ID = re.compile(r"[^A-Za-z0-9_-]+")


@dataclass
class PreparedTranslation:
    request: TranslateRequest
    source: ResolvedLanguage
    target: ResolvedLanguage
    selection: ModelSelection
    segments: list[dict[str, Any]]
    joined: str
    detection: Detection | None
    started: float


def _unsupported(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def prepare_translation(request: TranslateRequest) -> PreparedTranslation:
    started = time.time()
    segments = request.segment_dicts()
    joined = (
        request.text
        if request.text is not None
        else "\n\n".join(segment["text"] for segment in segments)
    )
    if not joined.strip():
        raise HTTPException(status_code=422, detail="There is no text to translate")

    detection: Detection | None = None
    source_raw = (request.source_language or "auto").strip()
    if source_raw.lower() in {"auto", "", "detect", "automatic"}:
        try:
            detection = detect_language_detailed(joined[:20_000])
        except ValueError as exc:
            raise _unsupported(str(exc)) from exc
        source = resolved_language(detection.code)
    else:
        try:
            source = resolved_language(source_raw)
        except ValueError as exc:
            raise _unsupported(str(exc)) from exc

    target_raw = (request.target_language or "en").strip()
    if target_raw.lower() in {"auto", "", "detect", "automatic"}:
        raise _unsupported("A target language must be selected")
    try:
        target_base, target_variant = normalize_language(target_raw)
        if target_base == "auto":
            raise ValueError("A target language must be selected")
        target = resolved_language(target_variant)
    except ValueError as exc:
        raise _unsupported(str(exc)) from exc

    if not segments:
        segments = segments_from_text(joined, max_chars=settings.max_chunk_chars)
    if not segments:
        raise HTTPException(status_code=422, detail="There is no text to translate")

    try:
        selection = ENGINE.resolve_model(request.model, source, target)
    except HTTPException:
        raise
    except ValueError as exc:
        raise _unsupported(str(exc)) from exc

    return PreparedTranslation(
        request=request,
        source=source,
        target=target,
        selection=selection,
        segments=segments,
        joined=joined,
        detection=detection,
        started=started,
    )


def _options(request: TranslateRequest) -> TranslationOptions:
    return TranslationOptions(
        num_beams=request.num_beams,
        max_length=request.max_length,
        temperature=request.temperature,
        length_penalty=request.length_penalty,
        repetition_penalty=request.repetition_penalty,
        no_repeat_ngram_size=request.no_repeat_ngram_size,
        batch_size=request.batch_size,
        preserve_markup=request.preserve_markup,
        glossary=dict(request.glossary or {}),
    )


def translate_prepared(
    prepared: PreparedTranslation,
    progress: Callable[[float, str], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    request = prepared.request
    translated_segments, stats = ENGINE.translate_segments(
        prepared.segments,
        prepared.selection,
        _options(request),
        progress=progress,
        cancel=cancel,
    )
    plain = build_plain_text(translated_segments)
    pages = pages_from_segments(translated_segments)
    warnings: list[str] = []
    if prepared.source.code == prepared.target.code:
        warnings.append(
            "The source and target languages are the same; the text is an identity copy."
        )
    if stats.empty_outputs:
        warnings.append(
            f"{stats.empty_outputs} fragment(s) produced no model output and were kept in the original language."
        )
    if prepared.target.code == "pt" and prepared.target.variant in {"pt-PT", "pt-BR"}:
        warnings.append(
            "Portuguese translations target the requested regional variant; "
            "the OPUS-MT model shares one Portuguese decoder."
        )
    warnings.append(
        "Machine translation can change names, numbers and nuances. "
        "Review important documents before publishing."
    )
    duration = round(time.time() - prepared.started, 3)
    return {
        "source_language": prepared.source.code,
        "source_language_name": prepared.source.name,
        "source_language_variant": prepared.source.variant,
        "target_language": prepared.target.variant,
        "target_language_code": prepared.target.code,
        "target_language_name": prepared.target.name,
        "detected_source_language": prepared.detection is not None,
        "detection": (
            {
                "confidence": prepared.detection.confidence,
                "candidates": prepared.detection.candidates[:5],
            }
            if prepared.detection
            else None
        ),
        "model": prepared.selection.id,
        "model_repo": prepared.selection.repo,
        "model_family": prepared.selection.family,
        "translated_text": plain,
        "segments": translated_segments,
        "pages": pages,
        "stats": {
            "input_characters": len(prepared.joined),
            "input_words": request.source_word_count(),
            "output_characters": len(plain),
            "paragraphs": len(translated_segments),
            "pages": len(pages),
            "chunks": stats.chunks,
            "pieces": stats.pieces,
            "batches": stats.batches,
            "empty_outputs": stats.empty_outputs,
            "glossary_terms": stats.glossary_terms,
            "chunk_chars": settings.max_chunk_chars,
            "device": "cpu",
            "parameters": {
                "num_beams": request.num_beams,
                "max_length": request.max_length,
                "temperature": request.temperature,
                "length_penalty": request.length_penalty,
                "repetition_penalty": request.repetition_penalty,
                "no_repeat_ngram_size": request.no_repeat_ngram_size,
                "batch_size": request.batch_size,
                "preserve_markup": request.preserve_markup,
            },
        },
        "warnings": warnings,
        "duration_seconds": duration,
    }


def perform_translation(
    request: TranslateRequest,
    progress: Callable[[float, str], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    prepared = prepare_translation(request)
    return translate_prepared(prepared, progress=progress, cancel=cancel)


def detect(text: str) -> dict[str, Any]:
    try:
        detection = detect_language_detailed(text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    language = resolved_language(detection.code)
    return {
        "language": detection.code,
        "canonical": detection.code,
        "variant": language.variant,
        "name": language.name,
        "confidence": detection.confidence,
        "candidates": detection.candidates,
        "supported": True,
    }


def artifact_path(job_id: str) -> Path:
    safe = _SAFE_JOB_ID.sub("_", job_id or "job")[:120] or "job"
    return resolve_path("documents", "translation", f"{safe}.txt")


def save_text_artifact(job_id: str, text: str) -> Path:
    path = artifact_path(job_id)
    atomic_write_text(path, text)
    return path


async def run_translate_job(ctx: JobContext) -> dict[str, Any]:
    from .jobutil import run_blocking

    request = TranslateRequest.model_validate(ctx.params or {})
    prepared = await run_in_threadpool(prepare_translation, request)
    await ctx.report(2, stage="translate", message="Translation model ready.")
    response = await run_blocking(
        ctx,
        lambda progress, cancel: translate_prepared(prepared, progress=progress, cancel=cancel),
        stage="translate",
        start_progress=3,
        end_progress=96,
    )
    path = save_text_artifact(ctx.job_id, response["translated_text"])
    await ctx.report(98, stage="translate", message="Saved the translation artifact.")
    info = file_info(path)
    return job_result(
        files=[info],
        data={
            "text_path": info["path"],
            "source_language": response["source_language"],
            "target_language": response["target_language"],
            "detected_source_language": response["detected_source_language"],
            "model": response["model"],
            "stats": response["stats"],
            "warnings": response["warnings"],
            "duration_seconds": response["duration_seconds"],
        },
        message=(
            f"Translated {response['stats']['input_characters']:,} characters "
            f"into {response['target_language']}."
        ),
    )


async def submit_translation_job(request: TranslateRequest) -> dict[str, Any]:
    payload = {
        "component": "translation",
        "action": "translate",
        "title": f"Translate → {request.target_language}",
        "params": request.model_dump(mode="json", exclude_none=True),
    }
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=jobhub_headers()) as client:
            response = await client.post(f"{JOBHUB_URL}/api/jobs", json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="The job hub is unavailable, so the translation job could not be queued.",
        ) from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise HTTPException(status_code=502, detail=f"Could not queue translation job: {detail}")
    return response.json()
