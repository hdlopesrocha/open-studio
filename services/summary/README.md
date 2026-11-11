# Summary service

Local document summarization for Open Studio. T5 models run on CPU with
token-aware chunking and hierarchical map-reduce for long documents.

## Models

| id | repository | language |
| --- | --- | --- |
| `t5-small-en` | `farleyknight/cnn_dailymail-summarization-t5-small-2022-09-08` | English |
| `t5-small-pt` | `rhaymison/t5-portuguese-small-summarization` | Portuguese |

Download explicitly:

```bash
docker compose run --rm summary download-models --models all
# only one language
docker compose run --rm summary download-models --models en
```

Models are stored in `/data/models/summary/{en,pt}`. The service never downloads
at inference time and `/api/summary/models` reports missing checkpoints as
`available: false`.

## API (gateway prefix `/api/summary`)

- `GET /status`, `GET /lengths`, `GET /languages`, `GET /models`
- `POST /summarize` — synchronous
- `POST /summarize/job` — central job hub action `summarize`
- `POST /internal/summarize` — synchronous endpoint for the documents pipeline

Parameters: `text`, `length` (`short|medium|long`), `language`,
`source_language`, `model`, `max_tokens`, `min_tokens`, `num_beams`,
`temperature`, `chunk_tokens`, `hierarchical`.

- Length budgets: short 120, medium 240, long 420 tokens (overridable with
  `max_tokens`).
- `chunk_tokens` controls the map step's token window (default 480, capped by
  the T5 context size).
- `hierarchical=true` summarises every chunk and recursively reduces the partial
  summaries. `false` performs a single pass over the beginning of the document.
- When `language` differs from the source, the summary is generated in the
  source language and translated through `/internal/translate` on the local
  translation service.

Job output: `/data/files/documents/summary/<job_id>.txt`.

## Environment

| variable | default |
| --- | --- |
| `SUMMARY_MODELS_DIR` | `/data/models/summary` |
| `SUMMARY_MODEL_EN` | `farleyknight/cnn_dailymail-summarization-t5-small-2022-09-08` |
| `SUMMARY_MODEL_PT` | `rhaymison/t5-portuguese-small-summarization` |
| `SUMMARY_MAX_INPUT_CHARS` | `500000` |
| `SUMMARY_MAX_INPUT_TOKENS` | `480` |
| `SUMMARY_MAX_CHUNKS` | `300` |
| `SUMMARY_SHORT_TOKENS` | `120` |
| `SUMMARY_MEDIUM_TOKENS` | `240` |
| `SUMMARY_LONG_TOKENS` | `420` |
| `TRANSLATION_SERVICE_URL` | `http://translation:8000` |
| `MODEL_IDLE_UNLOAD_SECONDS` | `900` |
