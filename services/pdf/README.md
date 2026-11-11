# PDF service

Path-based PDF extraction for Open Studio. Every path is relative to
`/data/files` (never an absolute host path).

## Stack

- PyMuPDF for page inspection, rendering and layout-aware text extraction.
- Tesseract + `pytesseract` for optional OCR (`eng`, `por` installed in the
  image; add more `tesseract-ocr-*` packages and rebuild to extend the list).
- Multi-column reading-order heuristics, wrapped-line reconstruction and
  hyphenation repair adapted from MicroTalk.

## API (gateway prefix `/api/pdf`)

- `GET /status`, `GET /ocr-languages`, `GET /languages`
- `POST /inspect` `{path}`
- `POST /extract` `{path, start_page, end_page, selected_pages, ocr_enabled, ocr_language}`
- `POST /extract/job` — central job hub action `extract`
- `GET /preview?path=&page=&width=&save=` → PNG
  (`save=true` writes `documents/pdf/previews/<name>-page-XXXX.png` and returns
  its files-relative path in `X-Preview-Path`)
- `POST /upload` multipart `file` → stores under `uploads/pdf/...`

Extraction writes `documents/pdf/<job_id>/extracted.txt` plus `pages.json` for
job submissions. Page markers (`--- Page N ---`) are preserved in the text so
translation and TTS keep page boundaries.

`ocr_language` accepts Tesseract language codes separated by `+`, for example
`por+eng`. Installed languages are validated before extraction.

## Environment

| variable | default |
| --- | --- |
| `MAX_UPLOAD_MB` | `200` |
| `MAX_PDF_PAGES` | `2000` |
| `OCR_LANGUAGES` | `por+eng` |
| `OCR_ENABLED_DEFAULT` | `false` |
| `OCR_DPI` | `200` |
| `OCR_TIMEOUT_SECONDS` | `180` |
| `OCR_MIN_CHARS` | `40` |
| `PDF_PREVIEW_WIDTH` | `480` |

The API only accepts files whose header starts with `%PDF-`. Password-protected
PDFs are rejected with a clear 422 error.
