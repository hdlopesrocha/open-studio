"""PDF parsing, layout-aware extraction and optional Tesseract OCR."""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from openstudio_common import JobCancelled

from .config import Settings
from .text import clean_text

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]
CancelCallback = Callable[[], bool]


@dataclass
class Block:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    font_size: float = 0.0

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2.0


def _fitz() -> Any:
    try:
        import fitz  # type: ignore

        return fitz
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail="PyMuPDF is not installed in the PDF service image.",
        ) from exc


def tesseract_info() -> dict[str, Any]:
    try:
        import pytesseract  # type: ignore

        version = str(pytesseract.get_tesseract_version())
        languages: list[str] = []
        try:
            languages = sorted(pytesseract.get_languages(config=""))
        except Exception:  # noqa: BLE001
            pass
        return {"available": True, "version": version, "languages": languages}
    except Exception:  # noqa: BLE001
        return {"available": False, "version": "", "languages": []}


def ocr_available() -> bool:
    return bool(tesseract_info()["available"])


def resolve_ocr_language(value: str | None, settings: Settings) -> str:
    raw = (value or settings.ocr_languages or "eng").strip().lower()
    parts = [part for part in re.split(r"[+,\s]+", raw) if part]
    if not parts:
        parts = ["eng"]
    if any(not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", part) for part in parts):
        raise HTTPException(status_code=422, detail="Invalid OCR language code.")
    canonical = "+".join(dict.fromkeys(parts))
    info = tesseract_info()
    if info["available"] and info["languages"]:
        installed = set(info["languages"])
        missing = [part for part in parts if part not in installed]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=(
                    "OCR language(s) not installed: "
                    + ", ".join(missing)
                    + ". Installed: "
                    + ", ".join(sorted(installed))
                ),
            )
    return canonical


def inspect_pdf(path: Path, scanned_threshold: int = 40) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    fitz = _fitz()
    try:
        document = fitz.open(path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=422,
            detail="The file is not a valid or readable PDF.",
        ) from exc
    try:
        if document.needs_pass:
            raise HTTPException(
                status_code=422,
                detail="Password-protected PDFs are not supported. Remove the password first.",
            )
        page_count = document.page_count
        if page_count < 1:
            raise HTTPException(status_code=422, detail="The PDF contains no pages.")
        metadata = document.metadata or {}
        sample_count = min(5, page_count)
        text_pages = 0
        for page_number in range(sample_count):
            try:
                if len(document.load_page(page_number).get_text("text").strip()) >= scanned_threshold:
                    text_pages += 1
            except Exception:  # noqa: BLE001
                continue
        return {
            "source_name": path.name,
            "page_count": page_count,
            "title": (metadata.get("title") or "").strip()[:500],
            "author": (metadata.get("author") or "").strip()[:500],
            "subject": (metadata.get("subject") or "").strip()[:500],
            "creator": (metadata.get("creator") or "").strip()[:200],
            "producer": (metadata.get("producer") or "").strip()[:200],
            "encrypted": False,
            "likely_scanned": sample_count > 0 and text_pages == 0,
            "sampled_pages": sample_count,
            "size_bytes": path.stat().st_size,
            "metadata": {
                key: (value or "")
                for key, value in metadata.items()
                if key in {"title", "author", "subject", "keywords", "creator", "producer", "creationDate", "modDate"}
            },
        }
    finally:
        document.close()


def render_page_preview(path: Path, page_number: int, max_width: int = 480) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    fitz = _fitz()
    try:
        document = fitz.open(path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="The PDF could not be opened.") from exc
    try:
        if page_number < 1 or page_number > document.page_count:
            raise HTTPException(
                status_code=404,
                detail=f"Page {page_number} does not exist (document has {document.page_count} pages).",
            )
        page = document.load_page(page_number - 1)
        width = max(1.0, float(page.rect.width))
        zoom = max(0.15, min(2.5, max_width / width))
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return pixmap.tobytes("png")
    finally:
        document.close()


def _line_text(block: dict[str, Any]) -> str:
    lines: list[str] = []
    for line in block.get("lines", []):
        text = "".join(str(span.get("text", "")) for span in line.get("spans", [])).strip()
        if text:
            lines.append(text)
    raw = "\n".join(lines)
    raw = re.sub(r"(?<=[A-Za-zÀ-ÿ])-\n(?=[a-zà-ÿ])", "", raw)
    raw = re.sub(r"\s*\n\s*", " ", raw)
    return clean_text(raw)


def _block_font_size(raw_block: dict[str, Any]) -> float:
    sizes = [
        float(span.get("size") or 0.0)
        for line in raw_block.get("lines", [])
        for span in line.get("spans", [])
        if str(span.get("text") or "").strip()
    ]
    return max(sizes) if sizes else 0.0


def _blocks_from_page(page: Any) -> list[Block]:
    try:
        data = page.get_text("dict", sort=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=422, detail="Text could not be extracted from a page."
        ) from exc
    blocks: list[Block] = []
    page_width = float(page.rect.width) or 1.0
    for raw_block in data.get("blocks", []):
        if raw_block.get("type") != 0:
            continue
        text = _line_text(raw_block)
        if not text:
            continue
        x0, y0, x1, y1 = [float(value) for value in raw_block.get("bbox", (0, 0, 0, 0))]
        if text.isdigit() and len(text) <= 4 and (y1 < 50 or y0 > page.rect.height - 50):
            continue
        if (x1 - x0) > page_width * 2.5:
            continue
        blocks.append(Block(x0, y0, x1, y1, text, _block_font_size(raw_block)))
    return blocks


def _join_wrapped_text(left: str, right: str) -> str:
    left = left.rstrip()
    right = right.lstrip()
    if not left:
        return right
    if not right:
        return left
    if left.endswith("-") and right[:1].islower():
        return left[:-1] + right
    return f"{left} {right}"


def _blocks_are_wrapped(previous: Block, current: Block) -> bool:
    if previous.font_size and current.font_size:
        if abs(previous.font_size - current.font_size) > max(1.0, previous.font_size * 0.12):
            return False
    gap = current.y0 - previous.y1
    line_height = max(previous.font_size, current.font_size, 10.0)
    if gap < -2.0 or gap > max(8.0, line_height * 0.8):
        return False
    overlap = max(0.0, min(previous.x1, current.x1) - max(previous.x0, current.x0))
    narrowest = min(previous.width, current.width)
    if narrowest <= 0 or overlap / narrowest < 0.25:
        return False
    if (
        current.x0 - previous.x0 > max(8.0, line_height * 0.6)
        and re.search(r"[.!?…:;][\"'”’»)\]]*$", previous.text.strip())
    ):
        return False
    return True


def _merge_wrapped_blocks(blocks: list[Block]) -> list[Block]:
    groups: list[list[Block]] = []
    for block in blocks:
        if groups and _blocks_are_wrapped(groups[-1][-1], block):
            groups[-1].append(block)
        else:
            groups.append([block])
    merged: list[Block] = []
    for group in groups:
        text = group[0].text
        for block in group[1:]:
            text = _join_wrapped_text(text, block.text)
        merged.append(
            Block(
                group[0].x0,
                group[0].y0,
                max(block.x1 for block in group),
                group[-1].y1,
                text,
                max(block.font_size for block in group),
            )
        )
    return merged


def _order_blocks(blocks: list[Block], page_width: float) -> list[Block]:
    """Best-effort reading order for one, two or more columns."""
    if len(blocks) < 2:
        return blocks
    narrow = [block for block in blocks if block.width < page_width * 0.72]
    left = [block for block in narrow if block.center_x < page_width * 0.48]
    right = [block for block in narrow if block.center_x > page_width * 0.52]
    is_multi_column = len(left) >= 2 and len(right) >= 2
    if is_multi_column:
        left_edge = max(block.x1 for block in left)
        right_edge = min(block.x0 for block in right)
        if right_edge - left_edge < page_width * 0.02:
            is_multi_column = False
    if not is_multi_column:
        return sorted(blocks, key=lambda b: (round(b.y0, 1), round(b.x0, 1)))
    spanning = sorted(
        [block for block in blocks if block.width >= page_width * 0.78],
        key=lambda b: (b.y0, b.x0),
    )
    narrow_blocks = [block for block in blocks if block.width < page_width * 0.78]
    band_map: dict[int, list[Block]] = {}
    for block in narrow_blocks:
        band = sum(1 for separator in spanning if separator.center_y <= block.center_y)
        band_map.setdefault(band, []).append(block)
    ordered: list[Block] = []
    for band in range(len(spanning) + 1):
        band_blocks = band_map.get(band, [])
        left_col = sorted(
            [block for block in band_blocks if block.center_x < page_width / 2],
            key=lambda b: (round(b.y0, 1), round(b.x0, 1)),
        )
        right_col = sorted(
            [block for block in band_blocks if block.center_x >= page_width / 2],
            key=lambda b: (round(b.y0, 1), round(b.x0, 1)),
        )
        ordered.extend(left_col)
        ordered.extend(right_col)
        if band < len(spanning):
            ordered.append(spanning[band])
    return ordered


def _paragraphs_from_text(text: str) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    paragraphs: list[str] = []
    buffer: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if buffer:
                paragraphs.append(" ".join(buffer).strip())
                buffer = []
            continue
        if buffer and re.search(r"[.!?:;]$", buffer[-1]) and stripped[:1].isupper():
            paragraphs.append(" ".join(buffer).strip())
            buffer = [stripped]
        else:
            buffer.append(stripped)
    if buffer:
        paragraphs.append(" ".join(buffer).strip())
    cleaned = []
    for paragraph in paragraphs:
        paragraph = re.sub(r"\s+", " ", paragraph).strip()
        if paragraph:
            cleaned.append(paragraph)
    return cleaned


def _ocr_page(page: Any, settings: Settings, ocr_language: str) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail="OCR was requested but Tesseract/Pillow is not available.",
        ) from exc
    fitz = _fitz()
    try:
        matrix = fitz.Matrix(settings.ocr_dpi / 72.0, settings.ocr_dpi / 72.0)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        image = Image.open(io.BytesIO(pixmap.tobytes("png")))
        text = pytesseract.image_to_string(
            image,
            lang=ocr_language,
            config="--psm 3",
            timeout=settings.ocr_timeout_seconds,
        )
    except pytesseract.TesseractNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="OCR was requested but Tesseract is not installed in the PDF service.",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=504,
            detail="OCR took too long for a page. Try a smaller page selection.",
        ) from exc
    except pytesseract.TesseractError as exc:
        logger.warning("Tesseract failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="OCR could not process one of the selected pages.",
        ) from exc
    if not text.strip():
        warnings.append("OCR found no text on this page.")
    return _paragraphs_from_text(text), warnings


def _page_text(page: Any, settings: Settings) -> tuple[list[str], list[str]]:
    try:
        blocks = _blocks_from_page(page)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unexpected text block error: %s", exc)
        blocks = []
    ordered = _order_blocks(blocks, float(page.rect.width))
    paragraphs = [
        block.text for block in _merge_wrapped_blocks(ordered) if block.text.strip()
    ]
    warnings: list[str] = []
    text = "\n\n".join(paragraphs).strip()
    if len(text) < settings.ocr_min_chars:
        warnings.append(
            "Little or no extractable text was found; this page may be scanned or image-based."
        )
    return paragraphs, warnings


def extract_document(
    path: Path,
    *,
    selected_pages: list[int],
    ocr_enabled: bool,
    ocr_language: str,
    settings: Settings,
    progress: ProgressCallback | None = None,
    cancel: CancelCallback | None = None,
) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    fitz = _fitz()
    try:
        document = fitz.open(path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="The PDF could not be opened.") from exc
    try:
        if document.needs_pass:
            raise HTTPException(
                status_code=422,
                detail="Password-protected PDFs are not supported. Remove the password first.",
            )
        total_pages = document.page_count
        if not selected_pages:
            raise HTTPException(status_code=422, detail="At least one page must be selected.")
        if any(page < 1 or page > total_pages for page in selected_pages):
            raise HTTPException(
                status_code=422,
                detail=f"Page numbers must be between 1 and {total_pages}.",
            )
        if total_pages > settings.max_pages:
            raise HTTPException(
                status_code=422,
                detail=f"The PDF has more than the {settings.max_pages}-page limit.",
            )
        selected_unique = sorted(set(selected_pages))
        pages_payload: list[dict[str, Any]] = []
        scanned_pages: list[int] = []
        empty_pages: list[int] = []
        ocr_pages: list[int] = []
        for index, page_number in enumerate(selected_unique):
            if cancel and cancel():
                raise JobCancelled("PDF extraction cancelled")
            page = document.load_page(page_number - 1)
            paragraphs, warnings = _page_text(page, settings)
            text = "\n\n".join(paragraphs).strip()
            scanned = len(text) < settings.ocr_min_chars
            method = "text"
            if scanned:
                scanned_pages.append(page_number)
            if scanned and ocr_enabled:
                paragraphs, ocr_warnings = _ocr_page(page, settings, ocr_language)
                warnings.extend(ocr_warnings)
                text = "\n\n".join(paragraphs).strip()
                method = "ocr"
                if text:
                    ocr_pages.append(page_number)
                scanned = len(text) < settings.ocr_min_chars
            if not text:
                empty_pages.append(page_number)
                if not warnings:
                    warnings.append("This page contains no extractable text.")
            pages_payload.append(
                {
                    "page": page_number,
                    "text": text,
                    "paragraphs": paragraphs,
                    "char_count": len(text),
                    "word_count": len(re.findall(r"\b[\wÀ-ÿ'-]+\b", text)),
                    "extraction_method": method,
                    "needs_ocr": scanned,
                    "warnings": sorted(set(warnings)),
                }
            )
            if progress:
                progress(
                    5 + (index + 1) / max(1, len(selected_unique)) * 80,
                    f"Extracted page {page_number} ({index + 1}/{len(selected_unique)}).",
                )
        extracted_pages = sum(1 for page in pages_payload if page["text"])
        if extracted_pages == 0:
            hint = (
                "Enable OCR to process scanned or image-based pages."
                if not ocr_enabled
                else "OCR did not find readable text in the selected pages."
            )
            raise HTTPException(
                status_code=422,
                detail=f"No readable text was found in the selected pages. {hint}",
            )
        parts = [
            f"--- Page {page['page']} ---\n\n{page['text']}" for page in pages_payload
        ]
        plain_text = "\n\n".join(parts).strip() + "\n"
        warnings: list[str] = []
        if empty_pages:
            warnings.append(
                "Some selected pages contain no extractable text: "
                + ", ".join(str(page) for page in empty_pages)
                + "."
            )
        if scanned_pages and not ocr_enabled:
            warnings.append("Some selected pages look scanned. Enable OCR to recognise text.")
        if ocr_pages:
            warnings.append(
                "OCR was used for page(s): " + ", ".join(str(page) for page in ocr_pages) + "."
            )
        return {
            "page_count": total_pages,
            "selected_pages": selected_unique,
            "pages": pages_payload,
            "plain_text": plain_text,
            "ocr_enabled": ocr_enabled,
            "ocr_language": ocr_language,
            "scanned_pages": scanned_pages,
            "empty_pages": empty_pages,
            "ocr_pages": ocr_pages,
            "warnings": warnings,
            "stats": {
                "selected_count": len(selected_unique),
                "pages_with_text": extracted_pages,
                "pages_without_text": len(empty_pages),
                "characters": len(plain_text),
            },
        }
    finally:
        try:
            document.close()
        except Exception:  # noqa: BLE001
            pass
