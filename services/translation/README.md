# Translation service

Local neural machine translation for Open Studio. Runs on CPU, loads one model
at a time, and never downloads checkpoints during inference.

## Models

The default OPUS-MT pair is small and recommended for Portuguese ↔ English:

| id | repository | direction |
| --- | --- | --- |
| `opus-mt-pt-en` | `Helsinki-NLP/opus-mt-roa-en` | Portuguese → English |
| `opus-mt-en-pt` | `Helsinki-NLP/opus-mt-tc-big-en-pt` | English → Portuguese |
| `nllb-200-distilled-600M` | `facebook/nllb-200-distilled-600M` | 200 languages (optional) |

Download explicitly (the model volumes live outside the image):

```bash
docker compose run --rm translation download-models --models opus
# optional multilingual support (~2.5 GB)
docker compose run --rm translation download-models --models nllb
# everything
docker compose run --rm translation download-models --models all
```

Files are written to `/data/models/translation`. `/api/translate/models` reports
`available: false` for models that are not installed; OPUS keeps working even
when NLLB is absent. Set `HF_HOME=/data/models/.hf-cache` (already in the
Dockerfile) so any residual Hugging Face metadata stays on the persistent
volume.

## API (gateway prefix `/api/translate`)

- `GET /status`, `GET /languages`, `GET /models`
- `POST /translate` — synchronous
- `POST /translate/job` — central job hub action `translate`
- `POST /detect`
- `POST /internal/translate` — synchronous endpoint used by the documents service

Request parameters: `text` **or** `segments`, `source_language`,
`target_language`, `model`, `num_beams`, `max_length`, `temperature`,
`length_penalty`, `repetition_penalty`, `no_repeat_ngram_size`, `batch_size`,
`preserve_markup`, `glossary`.

`glossary` accepts a mapping (`{"AI": "IA"}`), a list of pairs
(`[["AI", "IA"]]`) or objects (`[{"source": "AI", "target": "IA"}]`).

`preserve_markup` keeps HTML/XML tags, URLs, fenced/inline code, Markdown line
prefixes and `--- Page N ---` markers literal; glossary terms are replaced with
their target spelling without being sent to the model. Page markers are
re-emitted in `translated_text` exactly once.

The job handler writes `/data/files/documents/translation/<job_id>.txt` and
returns it in `files`.

## Environment

| variable | default |
| --- | --- |
| `TRANSLATION_MODELS_DIR` | `/data/models/translation` |
| `TRANSLATION_MODEL_PT_EN` | `Helsinki-NLP/opus-mt-roa-en` |
| `TRANSLATION_MODEL_EN_PT` | `Helsinki-NLP/opus-mt-tc-big-en-pt` |
| `TRANSLATION_MODEL_NLLB` | `facebook/nllb-200-distilled-600M` |
| `MODEL_IDLE_UNLOAD_SECONDS` | `900` |
| `CPU_THREADS` | `4` |
| `MAX_TRANSLATION_CHARS` | `500000` |
| `TRANSLATION_CHUNK_CHARS` | `850` |
| `TRANSLATION_BATCH_SIZE` | `8` |

`temperature=0` uses deterministic decoding; values above zero enable sampling.
`max_length` is the maximum number of generated tokens per fragment.
