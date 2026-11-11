# Documents service

End-to-end document workflow for Open Studio:

```
PDF / pasted text
   → extract (+ OCR)
   → translate (optional)
   → summarize (optional, from translation by default)
   → TTS through voice `/internal/tts`
   → SRT + WebVTT from the returned timeline
   → optional FFmpeg normalization/finalization
   → manifest.json + output.zip
```

No Redis or RQ. Submissions go to the central job hub as component `docs`,
action `pipeline`; execution uses the shared `JobRunner`.

## API (gateway prefix `/api/docs`)

- `GET /capabilities` — input types, PDF/OCR options, translation languages and
  models, summary lengths/languages/models, voice engines/voices (from
  `/api/voice/catalog`), FFmpeg catalog, formats, limits and defaults.
- `POST /run` — submit a `pipeline` job. Returns the central job object.
- `GET /jobs/{job_id}/text/{kind}` — `extracted`, `translation` or `summary`.
- `PATCH /jobs/{job_id}/text/{kind}` `{text}` — persist an edited text.
- `GET /jobs/{job_id}/manifest` — manifest as written on disk.
- `GET /jobs/{job_id}` — compact job summary for the documents UI.

### Pipeline config

```json
{
  "title": "Annual report",
  "input": {
    "type": "pdf",
    "pdf_path": "uploads/pdf/report.pdf",
    "start_page": 1,
    "end_page": 12,
    "selected_pages": null,
    "ocr_enabled": false,
    "ocr_language": "por+eng",
    "language": "auto"
  },
  "translation": {
    "enabled": true,
    "source_language": "auto",
    "target_language": "en",
    "model": "auto",
    "num_beams": 2,
    "max_length": 512,
    "temperature": 0,
    "length_penalty": 1,
    "repetition_penalty": 1,
    "no_repeat_ngram_size": 3,
    "batch_size": 8,
    "preserve_markup": true,
    "glossary": {"Acme": "Acme Corp"}
  },
  "summary": {
    "enabled": true,
    "length": "medium",
    "language": "en",
    "from_translation": true,
    "model": "auto",
    "max_tokens": null,
    "min_tokens": null,
    "num_beams": 3,
    "temperature": 0,
    "chunk_tokens": null,
    "hierarchical": true
  },
  "tts": {
    "enabled": true,
    "engine": "piper",
    "voice_id": null,
    "piper_voice": "pt_PT-tugao-medium",
    "language": "pt-PT",
    "speed": 1,
    "format": "mp3",
    "normalize_audio": true,
    "text_source": "summary",
    "finalize_with_ffmpeg": true,
    "advanced": {}
  },
  "subtitles": {"enabled": true, "format": "srt"},
  "zip": {"enabled": true}
}
```

`input.type` is `pdf` or `text`. For `text`, supply `input.text` (up to
`DOCS_MAX_TEXT_CHARS`) and omit the page fields. For `pdf`, `pdf_path` is
relative to `/data/files` (for example the path returned by
`POST /api/pdf/upload`).

`summary.from_translation=true` summarizes the translated text; set it to
`false` to summarize the original extraction. `tts.text_source` is `content`
(translated text when translation is on) or `summary`.

`subtitles` are built from the voice timeline. If the voice service omits a
timeline, the pipeline estimates proportional timings from
`duration_seconds`; if neither exists, it records a warning and continues.
Both `subtitles.srt` and `captions.vtt` are written when enabled.

Audio finalization: when normalization is requested or the voice output format
differs from the requested one, the pipeline calls FFmpeg
`POST /internal/finalize` with
`{source_path, output_path, format, normalize_audio, title}`. If that endpoint
is unavailable, the voice output is kept and a warning is added. The service
never depends on the FFmpeg endpoint for text-only workflows.

## Output layout

Everything is written under `/data/files/documents/<job_id>/`:

```
extracted.txt      translation.txt   summary.txt
audio.mp3|wav      master.wav        subtitles.srt
captions.vtt       manifest.json     output.zip
```

Jobs report progress per stage (`extract`, `translate`, `summarize`, `tts`,
`subtitles`, `archive`) and poll the job hub for cancellation between stages.

## Environment

| variable | default |
| --- | --- |
| `DOCS_MAX_TEXT_CHARS` | `200000` |
| `DOCS_MAX_TTS_CHARS` | `500000` |
| `DOCS_MAX_PAGES` | `2000` |
| `DOCS_MAX_SEGMENTS` | `5000` |
| `PDF_URL` | `http://pdf:8000` |
| `TRANSLATION_URL` | `http://translation:8000` |
| `SUMMARY_URL` | `http://summary:8000` |
| `VOICE_URL` | `http://voice:8000` |
| `FFMPEG_URL` | `http://ffmpeg:8000` |
| `DOCS_TTS_INTERNAL_PATH` | `/internal/tts` |
| `DOCS_FFMPEG_FINALIZE_PATH` | `/internal/finalize` |
| `DOCS_PDF_TIMEOUT` | `1800` |
| `DOCS_TRANSLATION_TIMEOUT` | `3600` |
| `DOCS_SUMMARY_TIMEOUT` | `3600` |
| `DOCS_TTS_TIMEOUT` | `7200` |
| `DOCS_FFMPEG_TIMEOUT` | `1800` |

## Notes

- Service-to-service calls send `X-Internal-Token` from
  `openstudio_common.jobhub_headers()`.
- Job submissions go to `POST {JOBHUB_URL}/api/jobs`; execution arrives at
  `POST /internal/jobs/run` with `{job_id, action, params}`.
- Edited text is stored immediately but does not automatically regenerate audio
  or subtitles; rerun the pipeline to regenerate downstream artifacts.
