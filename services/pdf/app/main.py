"""Open Studio PDF service API."""

from __future__ import annotations

import importlib.metadata
import logging
import os
from typing import Any

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from openstudio_common import FILES_ROOT, JobRunner, create_service_app, relative_path, resolve_path

from .config import settings
from .extractor import tesseract_info
from .schemas import ExtractRequest, InspectRequest
from .service import (
    inspect_request,
    perform_extract,
    render_preview,
    resolve_pdf_path,
    store_upload,
    submit_extract_job,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("pdf")

router = APIRouter(prefix="/api/pdf", tags=["pdf"])
runner = JobRunner("pdf")

OCR_LABELS = {
    "eng": "English",
    "por": "Portuguese",
    "spa": "Spanish",
    "fra": "French",
    "deu": "German",
    "ita": "Italian",
    "nld": "Dutch",
    "rus": "Russian",
    "ukr": "Ukrainian",
    "pol": "Polish",
    "ron": "Romanian",
    "ell": "Greek",
    "tur": "Turkish",
    "ara": "Arabic",
    "heb": "Hebrew",
    "hin": "Hindi",
    "jpn": "Japanese",
    "kor": "Korean",
    "chi_sim": "Chinese (Simplified)",
    "chi_tra": "Chinese (Traditional)",
    "osd": "Orientation & script detection",
}


def _mupdf_version() -> str:
    try:
        return importlib.metadata.version("PyMuPDF")
    except importlib.metadata.PackageNotFoundError:
        return ""


def _storage_status() -> dict[str, Any]:
    locations = {
        "documents": resolve_path("documents", "pdf"),
        "previews": resolve_path("documents", "pdf", "previews"),
        "uploads": resolve_path("uploads", "pdf"),
    }
    result: dict[str, Any] = {}
    for name, path in locations.items():
        try:
            path.mkdir(parents=True, exist_ok=True)
            result[name] = {
                "path": str(path),
                "relative": relative_path(path),
                "writable": os.access(path, os.W_OK),
            }
        except OSError:
            result[name] = {"path": str(path), "relative": "", "writable": False}
    return result


@router.get("/status")
async def status() -> dict[str, Any]:
    info = await run_in_threadpool(tesseract_info)
    return {
        "status": "ok",
        "service": "pdf",
        "files_root": str(FILES_ROOT),
        "pymupdf_available": bool(_mupdf_version()),
        "pymupdf_version": _mupdf_version(),
        "ocr_available": info["available"],
        "ocr_version": info["version"],
        "ocr_languages": {
            "configured": settings.ocr_languages,
            "installed": info["languages"],
        },
        "storage": _storage_status(),
        "limits": {
            "max_upload_mb": settings.max_upload_mb,
            "max_pages": settings.max_pages,
            "ocr_dpi": settings.ocr_dpi,
            "ocr_timeout_seconds": settings.ocr_timeout_seconds,
            "ocr_min_chars": settings.ocr_min_chars,
        },
        "defaults": {
            "ocr_enabled": settings.ocr_enabled_default,
            "ocr_language": settings.ocr_languages,
            "preview_width": settings.preview_width,
        },
    }


def _ocr_payload() -> dict[str, Any]:
    info = tesseract_info()
    installed = info["languages"]
    return {
        "configured": settings.ocr_languages,
        "installed": installed,
        "languages": installed,
        "items": [
            {"code": code, "label": OCR_LABELS.get(code, code)} for code in installed
        ],
        "total": len(installed),
    }


@router.get("/ocr-languages")
async def ocr_languages() -> dict[str, Any]:
    return await run_in_threadpool(_ocr_payload)


@router.get("/languages")
async def languages() -> dict[str, Any]:
    return await run_in_threadpool(_ocr_payload)


@router.post("/inspect")
async def inspect(payload: InspectRequest) -> dict[str, Any]:
    return await run_in_threadpool(inspect_request, payload.path)


@router.post("/extract")
async def extract(payload: ExtractRequest) -> dict[str, Any]:
    return await run_in_threadpool(perform_extract, payload)


@router.post("/extract/job")
async def extract_job(payload: ExtractRequest) -> dict[str, Any]:
    await run_in_threadpool(resolve_pdf_path, payload.path)
    return await submit_extract_job(payload)


@router.get("/preview")
async def preview(
    path: str = Query(..., min_length=1, max_length=2048),
    page: int = Query(1, ge=1, le=100_000),
    width: int = Query(480, ge=120, le=1600),
    save: bool = False,
) -> Response:
    content, saved = await run_in_threadpool(render_preview, path, page, width, save)
    headers = {
        "Cache-Control": "private, max-age=3600",
        "X-Content-Type-Options": "nosniff",
    }
    if saved:
        headers["X-Preview-Path"] = saved
    return Response(content=content, media_type="image/png", headers=headers)


@router.post("/upload", status_code=201)
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    return await store_upload(file, settings)


@runner.action("extract")
async def extract_action(ctx) -> dict[str, Any]:
    from .service import run_extract_job

    return await run_extract_job(ctx)


app = create_service_app(
    "pdf",
    "Open Studio PDF",
    (
        "PDF inspection, page previews, layout-aware text extraction and optional "
        "Tesseract OCR with Portuguese and English models."
    ),
    runner=runner,
    extra_routers=[router],
)
