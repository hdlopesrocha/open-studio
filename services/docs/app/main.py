"""Open Studio documents workflow API."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from openstudio_common import (
    JOBHUB_URL,
    JobRunner,
    create_service_app,
    jobhub_headers,
    resolve_path,
)

from . import artifacts
from .clients import ServiceClients
from .config import settings
from .schemas import PipelineRequest, TextUpdateRequest
from .text import word_count

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("docs")

router = APIRouter(prefix="/api/docs", tags=["documents"])
runner = JobRunner("docs")

FALLBACK_LENGTHS = [
    {"id": "short", "label": "Short", "max_tokens": 120},
    {"id": "medium", "label": "Medium", "max_tokens": 240},
    {"id": "long", "label": "Long", "max_tokens": 420},
]
FALLBACK_SUMMARY_LANGUAGES = [
    {"id": "en", "label": "English"},
    {"id": "pt-PT", "label": "Portuguese (Portugal)"},
    {"id": "pt-BR", "label": "Portuguese (Brazil)"},
]


def _defaults() -> dict[str, Any]:
    return {
        "title": "",
        "input": {
            "type": "pdf",
            "pdf_path": None,
            "text": None,
            "language": "auto",
            "start_page": None,
            "end_page": None,
            "selected_pages": None,
            "pages": None,
            "ocr_enabled": False,
            "ocr_language": None,
        },
        "translation": {
            "enabled": True,
            "source_language": "auto",
            "target_language": "en",
            "model": "auto",
            "num_beams": 2,
            "max_length": 512,
            "temperature": 0.0,
            "length_penalty": 1.0,
            "repetition_penalty": 1.0,
            "no_repeat_ngram_size": 3,
            "batch_size": 8,
            "preserve_markup": True,
            "glossary": None,
        },
        "summary": {
            "enabled": False,
            "length": "medium",
            "language": None,
            "from_translation": True,
            "source_language": "auto",
            "model": "auto",
            "max_tokens": None,
            "min_tokens": None,
            "num_beams": 3,
            "temperature": 0.0,
            "chunk_tokens": None,
            "hierarchical": True,
        },
        "tts": {
            "enabled": False,
            "engine": "piper",
            "mode": None,
            "voice_id": None,
            "piper_voice": None,
            "language": None,
            "language_variant": None,
            "speed": 1.0,
            "format": "mp3",
            "normalize_audio": False,
            "normalize_text": True,
            "text_source": "content",
            "pitch": 0.0,
            "instruct": None,
            "finalize_with_ffmpeg": True,
            "advanced": {},
        },
        "subtitles": {"enabled": False, "format": "srt"},
        "zip": {"enabled": True},
    }


def _voice_capabilities(catalog: Any) -> dict[str, Any]:
    if not isinstance(catalog, dict) or catalog.get("available") is False:
        return {
            "available": False,
            "engines": [],
            "voices": [],
            "languages": [],
            "formats": ["mp3", "wav"],
            "modes": [],
            "defaults": {},
            "error": (catalog or {}).get("error") if isinstance(catalog, dict) else None,
        }
    voices = catalog.get("voices") or catalog.get("items") or []
    if isinstance(voices, dict):
        voices = list(voices.values())
    engines = catalog.get("engines") or []
    if isinstance(engines, dict):
        engines = list(engines.values())
    languages = catalog.get("languages") or []
    formats = catalog.get("formats") or ["mp3", "wav"]
    if isinstance(formats, dict):
        formats = list(formats)
    return {
        "available": True,
        "engines": engines,
        "voices": voices,
        "languages": languages,
        "modes": catalog.get("modes") or [],
        "formats": formats,
        "defaults": catalog.get("defaults") or {},
        "limits": catalog.get("limits") or {},
        "catalog": catalog,
    }


async def _capabilities() -> dict[str, Any]:
    clients = ServiceClients(settings)
    try:
        payload = await clients.capabilities()
    finally:
        await clients.close()
    pdf_status = payload.get("pdf_status") or {}
    ocr = payload.get("pdf_ocr_languages") or {}
    translation_languages = payload.get("translation_languages") or {}
    translation_models = payload.get("translation_models") or {}
    summary_lengths = payload.get("summary_lengths") or {}
    summary_languages = payload.get("summary_languages") or {}
    summary_models = payload.get("summary_models") or {}
    tts = _voice_capabilities(payload.get("tts_catalog"))
    ffmpeg = payload.get("ffmpeg_catalog") or {}
    translation_items = (
        translation_languages.get("items") or translation_languages.get("languages") or []
    )
    summary_items = summary_lengths.get("items") or summary_lengths.get("lengths") or []
    ocr_items = ocr.get("items") or ocr.get("languages") or []
    return {
        "service": "docs",
        "input_types": ["pdf", "text"],
        "inputs": {
            "types": ["pdf", "text"],
            "pdf": {
                "path_relative_to": "files",
                "page_options": ["start_page", "end_page", "selected_pages"],
                "ocr_enabled": True,
                "ocr_languages": ocr_items,
            },
            "text": {
                "max_characters": settings.max_text_chars,
                "accepts_page_markers": True,
            },
        },
        "pdf": {
            "available": bool(pdf_status.get("status") == "ok"),
            "status": pdf_status,
            "ocr": ocr,
        },
        "translation": {
            "available": bool(translation_items),
            "source_languages": translation_languages.get("source") or ["auto", "pt", "en"],
            "target_languages": translation_languages.get("target") or ["en", "pt-PT", "pt-BR"],
            "languages": translation_items,
            "models": translation_models.get("items") or [],
            "defaults": {
                "enabled": True,
                "source_language": "auto",
                "target_language": "en",
                "model": "auto",
            },
        },
        "summary": {
            "available": bool(summary_items),
            "lengths": summary_items or FALLBACK_LENGTHS,
            "languages": summary_languages.get("items") or FALLBACK_SUMMARY_LANGUAGES,
            "models": summary_models.get("items") or [],
            "defaults": {
                "enabled": False,
                "length": "medium",
                "from_translation": True,
            },
        },
        "tts": tts,
        "ffmpeg": {
            "available": bool(ffmpeg.get("operations") or ffmpeg.get("status")),
            "catalog": ffmpeg,
        },
        "subtitles": {
            "enabled": True,
            "formats": ["srt", "vtt"],
            "timeline_source": "voice /internal/tts",
        },
        "formats": {
            "text": ["txt"],
            "audio": ["mp3", "wav", "flac", "ogg", "opus", "m4a"],
            "subtitles": ["srt", "vtt"],
            "archive": ["zip"],
            "manifest": ["json"],
        },
        "limits": {
            "max_text_characters": settings.max_text_chars,
            "max_tts_characters": settings.max_tts_chars,
            "max_pages": settings.max_pages,
            "max_segments": settings.max_segments,
        },
        "defaults": _defaults(),
    }


def _validate_pdf_input(path_value: str) -> None:
    try:
        path = resolve_path(path_value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"PDF not found: {path_value}")
    if path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=422, detail="Only PDF files can be processed")
    try:
        with path.open("rb") as handle:
            if b"%PDF-" not in handle.read(1024):
                raise HTTPException(status_code=422, detail="The file is not a valid PDF")
    except OSError as exc:
        raise HTTPException(status_code=500, detail="The PDF could not be read") from exc


async def _submit(request: PipelineRequest) -> dict[str, Any]:
    source_name = (
        (request.input.pdf_path or "").rsplit("/", 1)[-1]
        if request.input.type == "pdf"
        else "Pasted text"
    )
    payload = {
        "component": "docs",
        "action": "pipeline",
        "title": request.title or f"Document workflow · {source_name}"[:200],
        "params": request.model_dump(mode="json", exclude_none=True),
    }
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=jobhub_headers()) as client:
            response = await client.post(f"{JOBHUB_URL}/api/jobs", json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="The job hub is unavailable, so the document workflow could not be queued.",
        ) from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise HTTPException(status_code=502, detail=f"Could not queue document workflow: {detail}")
    return response.json()


# -- API -------------------------------------------------------------------


@router.get("/capabilities")
async def capabilities() -> dict[str, Any]:
    return await _capabilities()


@router.post("/run")
async def run(request: PipelineRequest) -> dict[str, Any]:
    if request.input.type == "pdf":
        await run_in_threadpool(_validate_pdf_input, request.input.pdf_path or "")
    return await _submit(request)


def _get_text(job_id: str, kind: str) -> dict[str, Any]:
    if kind not in artifacts.TEXT_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown text kind '{kind}'. Use extracted, translation or summary.",
        )
    try:
        return artifacts.read_text(job_id, kind)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"The {kind} text is not available for this job yet",
        ) from exc


@router.get("/jobs/{job_id}/text/{kind}")
async def get_text(job_id: str, kind: str) -> dict[str, Any]:
    return await run_in_threadpool(_get_text, job_id, kind)


def _patch_text(job_id: str, kind: str, text: str) -> dict[str, Any]:
    if kind not in artifacts.TEXT_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown text kind '{kind}'. Use extracted, translation or summary.",
        )
    try:
        folder = artifacts.job_dir(job_id, create=False)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not folder.is_dir():
        raise HTTPException(status_code=404, detail="The document job was not found")
    try:
        info = artifacts.write_text(job_id, kind, text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    artifacts.update_manifest_text(job_id, kind, info)
    result = artifacts.read_text(job_id, kind)
    result["updated_at"] = info.get("updated_at")
    result["words"] = word_count(text)
    return result


@router.patch("/jobs/{job_id}/text/{kind}")
async def patch_text(job_id: str, kind: str, payload: TextUpdateRequest) -> dict[str, Any]:
    return await run_in_threadpool(_patch_text, job_id, kind, payload.text)


@router.get("/jobs/{job_id}/manifest")
async def get_manifest(job_id: str) -> dict[str, Any]:
    try:
        manifest = await run_in_threadpool(artifacts.read_manifest, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not manifest:
        raise HTTPException(status_code=404, detail="The job manifest is not available yet")
    return manifest


@router.get("/jobs/{job_id}")
async def get_job_summary(job_id: str) -> dict[str, Any]:
    try:
        manifest = await run_in_threadpool(artifacts.read_manifest, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not manifest:
        raise HTTPException(status_code=404, detail="The document job was not found")
    return {
        "job_id": job_id,
        "title": manifest.get("title"),
        "status": manifest.get("status"),
        "source": manifest.get("source"),
        "languages": manifest.get("languages"),
        "stats": manifest.get("stats"),
        "artifacts": manifest.get("artifacts"),
        "warnings": manifest.get("warnings"),
        "created_at": manifest.get("created_at"),
        "updated_at": manifest.get("updated_at"),
    }


@runner.action("pipeline")
async def pipeline_action(ctx) -> dict[str, Any]:
    from .pipeline import run_pipeline_job

    return await run_pipeline_job(ctx)


app = create_service_app(
    "docs",
    "Open Studio Documents",
    (
        "PDF/text → translation → summary → speech → synchronized SRT/VTT → "
        "manifest and ZIP, orchestrated through the central job hub."
    ),
    runner=runner,
    extra_routers=[router],
)
