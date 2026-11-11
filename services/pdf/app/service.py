"""PDF request handling, artifacts and uploads."""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable

import httpx
from fastapi import HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from openstudio_common import (
    JOBHUB_URL,
    JobContext,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
    file_info,
    job_result,
    jobhub_headers,
    relative_path,
    resolve_path,
    sanitize_name,
    unique_path,
    utc_now,
)

from .config import Settings, settings
from .extractor import (
    extract_document,
    inspect_pdf,
    render_page_preview,
    resolve_ocr_language,
)
from .schemas import ExtractRequest

logger = logging.getLogger(__name__)

_SAFE_JOB_ID = re.compile(r"[^A-Za-z0-9_-]+")


def resolve_pdf_path(rel: str) -> Path:
    try:
        path = resolve_path(rel)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"PDF not found: {rel}")
    if path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=422, detail="Only PDF files can be processed")
    try:
        with path.open("rb") as handle:
            header = handle.read(1024)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="The PDF could not be read") from exc
    if b"%PDF-" not in header:
        raise HTTPException(status_code=422, detail="The file is not a valid PDF")
    return path


def inspect_request(rel: str) -> dict[str, Any]:
    path = resolve_pdf_path(rel)
    result = inspect_pdf(path, settings.ocr_min_chars)
    result["file"] = relative_path(path)
    result["filename"] = path.name
    return result


def _ocr_language_for_request(request: ExtractRequest) -> str:
    if request.ocr_enabled:
        return resolve_ocr_language(request.ocr_language, settings)
    raw = request.ocr_language or settings.ocr_languages or "eng"
    parts = [part for part in re.split(r"[+,\s]+", raw.strip().lower()) if part]
    return "+".join(dict.fromkeys(parts)) or "eng"


def perform_extract(
    request: ExtractRequest,
    progress: Callable[[float, str], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    path = resolve_pdf_path(request.path)
    info = inspect_pdf(path, settings.ocr_min_chars)
    page_count = int(info["page_count"])
    try:
        pages = request.resolved_pages(page_count)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    ocr_language = _ocr_language_for_request(request)
    result = extract_document(
        path,
        selected_pages=pages,
        ocr_enabled=request.ocr_enabled,
        ocr_language=ocr_language,
        settings=settings,
        progress=progress,
        cancel=cancel,
    )
    return {
        "path": relative_path(path),
        "filename": path.name,
        "title": info.get("title", ""),
        **result,
    }


def _job_dir(job_id: str) -> Path:
    safe = _SAFE_JOB_ID.sub("_", job_id or "job")[:120] or "job"
    return resolve_path("documents", "pdf", safe)


def save_extraction_artifacts(job_id: str, result: dict[str, Any]) -> dict[str, Path]:
    folder = _job_dir(job_id)
    folder.mkdir(parents=True, exist_ok=True)
    text_path = folder / "extracted.txt"
    pages_path = folder / "pages.json"
    atomic_write_text(text_path, str(result.get("plain_text") or ""))
    atomic_write_json(
        pages_path,
        {
            "source": result.get("path"),
            "filename": result.get("filename"),
            "page_count": result.get("page_count"),
            "selected_pages": result.get("selected_pages"),
            "ocr_enabled": result.get("ocr_enabled"),
            "ocr_language": result.get("ocr_language"),
            "stats": result.get("stats"),
            "warnings": result.get("warnings"),
            "pages": result.get("pages"),
        },
    )
    return {"text": text_path, "pages": pages_path}


async def run_extract_job(ctx: JobContext) -> dict[str, Any]:
    from .jobutil import run_blocking

    request = ExtractRequest.model_validate(ctx.params or {})
    await ctx.report(2, stage="extract", message="Opening the PDF.")
    result = await run_blocking(
        ctx,
        lambda progress, cancel: perform_extract(request, progress=progress, cancel=cancel),
        stage="extract",
        start_progress=3,
        end_progress=94,
    )
    paths = save_extraction_artifacts(ctx.job_id, result)
    await ctx.report(97, stage="extract", message="Saved the extracted text.")
    files = [file_info(paths["text"]), file_info(paths["pages"])]
    return job_result(
        files=files,
        data={
            "text_path": relative_path(paths["text"]),
            "pages_path": relative_path(paths["pages"]),
            "source_path": result.get("path"),
            "page_count": result.get("page_count"),
            "selected_pages": result.get("selected_pages"),
            "ocr_enabled": result.get("ocr_enabled"),
            "ocr_language": result.get("ocr_language"),
            "ocr_pages": result.get("ocr_pages"),
            "scanned_pages": result.get("scanned_pages"),
            "empty_pages": result.get("empty_pages"),
            "stats": result.get("stats"),
            "warnings": result.get("warnings"),
        },
        message=(
            f"Extracted {result.get('stats', {}).get('characters', 0):,} characters "
            f"from {len(result.get('selected_pages') or [])} page(s)."
        ),
    )


async def submit_extract_job(request: ExtractRequest) -> dict[str, Any]:
    payload = {
        "component": "pdf",
        "action": "extract",
        "title": f"Extract PDF · {Path(request.path).name}"[:200],
        "params": request.model_dump(mode="json", exclude_none=True),
    }
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=jobhub_headers()) as client:
            response = await client.post(f"{JOBHUB_URL}/api/jobs", json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="The job hub is unavailable, so the PDF extraction job could not be queued.",
        ) from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise HTTPException(status_code=502, detail=f"Could not queue PDF job: {detail}")
    return response.json()


async def store_upload(file: UploadFile, app_settings: Settings | None = None) -> dict[str, Any]:
    app_settings = app_settings or settings
    if not file.filename:
        raise HTTPException(status_code=422, detail="A PDF file is required")
    original = sanitize_name(file.filename, fallback="document.pdf")
    if not original.lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="Only PDF files are accepted")
    upload_dir = resolve_path("uploads", "pdf")
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(upload_dir, original)
    limit = app_settings.max_upload_mb * 1024 * 1024
    fd, temp_name = tempfile.mkstemp(prefix=".upload-", suffix=".part", dir=str(upload_dir))
    total = 0
    header = b""
    try:
        with os.fdopen(fd, "wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"The PDF exceeds the {app_settings.max_upload_mb} MB upload limit."
                        ),
                    )
                if len(header) < 1024:
                    header += chunk[: 1024 - len(header)]
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if total == 0:
            raise HTTPException(status_code=422, detail="The uploaded file is empty")
        if b"%PDF-" not in header:
            raise HTTPException(status_code=422, detail="The uploaded file is not a PDF")
        os.replace(temp_name, target)
        info = await run_in_threadpool(inspect_pdf, target, app_settings.ocr_min_chars)
        if info["page_count"] > app_settings.max_pages:
            target.unlink(missing_ok=True)
            raise HTTPException(
                status_code=422,
                detail=f"The PDF has more than the {app_settings.max_pages}-page limit",
            )
        return {
            **info,
            "path": relative_path(target),
            "filename": original,
            "size_bytes": total,
            "uploaded_at": utc_now(),
        }
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        Path(temp_name).unlink(missing_ok=True)
        await file.close()


def render_preview(rel: str, page: int, width: int, save: bool = False) -> tuple[bytes, str | None]:
    path = resolve_pdf_path(rel)
    content = render_page_preview(path, page, width)
    saved: str | None = None
    if save:
        directory = resolve_path("documents", "pdf", "previews")
        directory.mkdir(parents=True, exist_ok=True)
        stem = sanitize_name(path.stem, fallback="document")[:80]
        target = directory / f"{stem}-page-{page:04d}.png"
        atomic_write_bytes(target, content)
        saved = relative_path(target)
    return content, saved
