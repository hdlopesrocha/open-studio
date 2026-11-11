# Subtitles (AI SRT) service

FastAPI service mounted by the gateway at `/api/srt`.

- `GET /catalog`, `GET /models`, `GET /languages`
- `POST /transcribe` → job hub job (`transcribe`)
- `POST /align` → job hub job (`align`)
- `POST /from-text` → job hub job (`from_text`)
- `POST /convert` → synchronous SRT/VTT/ASS conversion (no model)
- `POST /estimate` → processing-time and cue estimate (no model)

Whisper runs through `faster-whisper` (CTranslate2). Models are loaded lazily
and cached under `/data/models/whisper`; `tiny`, `base`, `small`, `medium`,
`large-v3` and `distil-large-v3` are listed in the catalog. The first use of a
model downloads it from Hugging Face unless it is already cached.

Lyrics alignment accepts plain text or LRC. It transcribes with word timestamps,
normalises accents/case/punctuation, matches tokens with `difflib.SequenceMatcher`
plus fuzzy substitutions, splits long lines and fills unmatched lines
proportionally while preserving instrumental gaps. The job result contains
`data.cues`, `data.language`, `data.duration`, `data.warnings` and
`data.files.{srt,vtt,ass}` for the cue editor.

Outputs live in `/data/files/subtitles/<job_id>/`. Optional `translate_to`
also writes `<name>.<lang>.srt|vtt|ass` through the translation service.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `WHISPER_CACHE_DIR` | `/data/models/whisper` | model cache |
| `WHISPER_DEVICE` | `auto` | `auto`, `cpu`, `cuda` |
| `WHISPER_COMPUTE_TYPE` | `auto` | e.g. `int8`, `float16` |
| `WHISPER_CPU_THREADS` | CPU count (max 8) | CPU inference threads |
| `WHISPER_DEFAULT_MODEL` | `small` | catalog/job default |
| `WHISPER_LOCAL_FILES_ONLY` | `0` | disable model downloads |
| `WHISPER_PRELOAD_MODEL` | empty | optional eager load at boot |
| `TRANSLATION_URL` | `http://translation:8000` | cue translation service |

Build a CUDA-enabled image with `--build-arg INSTALL_CUDA=1` and run it with the
NVIDIA container runtime; otherwise the service falls back to CPU `int8`.
