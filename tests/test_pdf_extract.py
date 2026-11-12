"""PDF inspection/extraction tests using a generated two-page PDF."""

from __future__ import annotations

import pytest

pytest.importorskip("fitz", reason="PyMuPDF is required for PDF extraction tests")

from fastapi import HTTPException

from openstudio_common import FILES_ROOT
from services.pdf.app.config import Settings
from services.pdf.app.extractor import extract_document, inspect_pdf, render_page_preview
from services.pdf.app.schemas import ExtractRequest
from services.pdf.app.service import resolve_pdf_path


def _make_pdf(path):
    import fitz

    document = fitz.open()
    first = document.new_page()
    first.insert_text((72, 96), "Open Studio PDF extraction", fontsize=18)
    first.insert_text((72, 130), "The harbour is quiet before sunrise.", fontsize=12)
    second = document.new_page()
    second.insert_text((72, 96), "Second page content for the extractor.", fontsize=12)
    document.set_metadata({"title": "Harbour Notes", "author": "Ana"})
    document.save(path)
    document.close()


def test_inspect_and_extract_generated_pdf(tmp_path):
    pdf_path = FILES_ROOT / "documents" / "pdf" / "harbour.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    _make_pdf(pdf_path)

    info = inspect_pdf(pdf_path)
    assert info["page_count"] == 2
    assert info["title"] == "Harbour Notes"
    assert info["author"] == "Ana"
    assert info["likely_scanned"] is False
    assert info["size_bytes"] > 0

    result = extract_document(
        pdf_path,
        selected_pages=[1, 2],
        ocr_enabled=False,
        ocr_language="eng",
        settings=Settings(ocr_min_chars=10),
    )
    assert result["page_count"] == 2
    assert result["selected_pages"] == [1, 2]
    assert result["ocr_pages"] == []
    assert result["scanned_pages"] == []
    assert "Open Studio PDF extraction" in result["plain_text"]
    assert "Second page content" in result["plain_text"]
    assert result["stats"]["pages_with_text"] == 2
    assert result["pages"][0]["extraction_method"] == "text"

    preview = render_page_preview(pdf_path, 1, max_width=320)
    assert preview.startswith(b"\x89PNG")
    assert len(preview) > 100


def test_extract_page_selection_resolves_ranges_and_rejects_out_of_range():
    request = ExtractRequest(path="documents/pdf/harbour.pdf", start_page=2, end_page=3)
    assert request.resolved_pages(5) == [2, 3]

    request = ExtractRequest(path="documents/pdf/harbour.pdf", selected_pages=[3, 1, 3])
    assert request.resolved_pages(3) == [1, 3]

    request = ExtractRequest(path="documents/pdf/harbour.pdf")
    assert request.resolved_pages(2) == [1, 2]

    with pytest.raises(ValueError):
        ExtractRequest(path="documents/pdf/harbour.pdf", selected_pages=[4]).resolved_pages(3)


def test_resolve_pdf_path_rejects_missing_and_non_pdf(tmp_path):
    with pytest.raises(HTTPException) as missing:
        resolve_pdf_path("documents/pdf/does-not-exist.pdf")
    assert missing.value.status_code == 404

    text_path = FILES_ROOT / "documents" / "pdf" / "notes.txt"
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text("not a pdf", encoding="utf-8")
    with pytest.raises(HTTPException) as wrong_type:
        resolve_pdf_path("documents/pdf/notes.txt")
    assert wrong_type.value.status_code == 422

    fake_pdf = FILES_ROOT / "documents" / "pdf" / "fake.pdf"
    fake_pdf.write_bytes(b"not really a pdf")
    with pytest.raises(HTTPException) as invalid:
        resolve_pdf_path("documents/pdf/fake.pdf")
    assert invalid.value.status_code == 422

    with pytest.raises(HTTPException):
        resolve_pdf_path("../../etc/passwd")
