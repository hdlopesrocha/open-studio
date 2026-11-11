# Voice service

One Dockerised TTS service for Open Studio with two engines:

- **OmniVoice** – voice cloning, instructed voice design, auto voice and
  Whisper transcription. Heavy, lazy-loaded in a background thread.
- **Piper** – fast ONNX voices (`piper-tts` + `onnxruntime`) with a real
  sentence timeline for SRT generation.

The public API is exposed by the gateway at `/api/voice`. Long work goes
through the shared job hub. The documents pipeline uses the synchronous
`POST /internal/tts` endpoint instead.

## Storage

| What | Path |
| --- | --- |
| Voice profiles | `/data/files/voices/<voice_id>/` with `meta.json`, `reference.wav`, `prompt.pt`, optional `preview.wav` |
| Generated audio | `/data/files/voice/outputs/<output_id>/` with `audio.<fmt>` and `meta.json` |
| Temporary uploads | `/data/files/voice/uploads/` |
| Piper models | `/data/models/piper/<voice-id>/<voice-id>.onnx` + `.onnx.json` |
| Hugging Face cache | `/data/models/huggingface` (`HF_HOME`) |

All paths returned by the API are relative to `/data/files`, so they can be
opened with `/api/files/raw/<path>`.

## Endpoints

### Catalog and voices

- `GET /catalog` – engines, trained voices, Piper catalog, languages (including
  `pt-PT`/`pt-BR` variants), modes, formats, limits, defaults and every advanced
  control.
- `GET /voices` – trained OmniVoice profiles.
- `GET /voices/{id}`, `PATCH /voices/{id}`, `DELETE /voices/{id}`.
- `POST /voices` / `POST /train` – multipart training job:
  `name`, `audio`, optional `transcript`, `language`, `description`, `tags`,
  `consent=true`, `preprocess_prompt`.
- `POST /voices/{id}/retrain` – multipart retrain job; audio is optional when
  only the transcript/language/name changes.
- `GET /voices/{id}/reference`, `GET /voices/{id}/preview`.
- `POST /voices/{id}/preview` / `POST /preview` – preview job.
- `GET /voices/{id}/export`, `POST /voices/import` – ZIP voice profile.
- `POST /transcribe` – multipart Whisper transcription job.

Consent is required for training/retraining. Reference audio must be decodable
by ffmpeg and between `MIN_VOICE_SECONDS` and `MAX_VOICE_SECONDS` (1–30 s by
default; 3–10 s is ideal).

### TTS

- `POST /tts` – job hub job. Params:
  `engine(omnivoice|piper|auto)`, `mode(auto|voice|design)`, `voice_id`,
  `piper_voice`, `text`, `instruct`, `language`, `language_variant`, `speed`,
  `num_step`, `guidance_scale`, `t_shift`, `denoise`, `preprocess_prompt`,
  `postprocess_output`, `seed`, `format(wav|mp3|flac)`, `normalize_text`,
  `pitch`, `normalize_audio`, `duration`, `position_temperature`,
  `class_temperature`, `layer_penalty_factor`, `pad_duration`, `fade_duration`,
  `audio_chunk_duration`, `audio_chunk_threshold`.
- `POST /batch` – job. Provide `items`, `texts`, or `text` plus
  `split_mode=blank-line|line`; up to 50 items.
- `GET /outputs`, `GET /outputs/{id}` (audio), `GET /outputs/{id}/meta`,
  `GET /outputs/{id}/timeline`, `DELETE /outputs/{id}`.
- OpenAI shim: `POST /v1/audio/speech`, `GET /v1/models`, `GET /v1/voices`.
  Any bearer key is accepted; the gateway owns real authentication.
- `POST /internal/tts` – synchronous body with the same TTS fields, returns:

```json
{
  "path": "voice/outputs/abc123/audio.wav",
  "duration_seconds": 12.34,
  "timeline": [{"index": 1, "text": "...", "start": 0.0, "end": 1.8}],
  "format": "wav",
  "engine": "piper",
  "voice": "pt-PT-tugao"
}
```

### Piper

- `GET /piper/voices` – built-in catalog + availability.
- `POST /piper/install` – JSON `{"voice_id":"pt-PT-tugao"}` or
  `{"voice_ids":[...], "force":true}`. Downloads from Hugging Face into
  `/data/models/piper`. It is synchronous (the gateway has no read timeout) but
  can also be pre-seeded with `voice-download-models`.

Piper supports WAV and MP3, speed 0.5–2.0, optional loudness normalization
(`normalize_audio`, ffmpeg `dynaudnorm`), and sentence-level timeline entries
with real start/end times. Pitch is rejected unless a catalog voice declares
`pitch_supported: true` (none of the bundled voices do).

## Jobs

Actions: `tts`, `batch`, `train`, `preview`, `transcribe`.

Submit routes POST to `JOBHUB_URL/api/jobs` with
`{component:"voice", action, title, params}` and return the job hub job.
Multipart uploads are first written under `/data/files/voice/uploads/`, then
the relative path is put in `params.audio_path`; the job handler deletes the
upload afterwards. Handlers call `ctx.report(...)` and `ctx.check()`.

Cancellation for OmniVoice happens between text segments (model calls are not
preemptible); for Piper between sentences. Partial output directories and
temporary files are removed on cancellation.

## Health and engine failures

`GET /health` and `GET /api/voice/health` return an engine-aware payload:

```json
{
  "service": "voice",
  "status": "unavailable",
  "message": "OmniVoice is not installed ... Piper is available ...",
  "engines": {
    "omnivoice": {"status": "unavailable", "available": false, "message": "..."},
    "piper": {"status": "ok", "available": true, "voices_installed": 2}
  },
  "piper_available": true
}
```

`status` mirrors the OmniVoice engine (`loading`, `ok`, `unavailable`,
`error`). A missing `omnivoice` package never prevents the process from
starting or Piper from generating audio. When the package is absent, requests
with `engine=omnivoice` fail with HTTP 503 and a clear message; `engine=piper`
continues to work.

## Docker

The image is Python 3.11 slim and installs ffmpeg, libsndfile1, build tools,
PyTorch, `piper-tts`, `onnxruntime` and the OmniVoice stack.

```bash
# CPU
docker build -f services/voice/Dockerfile \
  --build-arg DEVICE=cpu \
  --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu \
  -t openstudio-voice .

# CUDA
docker build -f services/voice/Dockerfile \
  --build-arg DEVICE=cuda \
  --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cu128 \
  -t openstudio-voice:cu128 .
```

`DEVICE` becomes the runtime default. Set `DEVICE=cpu` or `DEVICE=cuda` in
compose; `DEVICE=auto` also works if a GPU is present. `TORCH_INDEX_URL` must
match `DEVICE`.

For a Piper-only image, copy `requirements-piper.txt` over
`requirements.txt` (or point the Dockerfile `COPY` at it) and skip the torch
install step; the service will report OmniVoice as unavailable and keep all
Piper endpoints working.

### Environment

| Variable | Default | Description |
| --- | --- | --- |
| `DEVICE` | `cpu` | `cpu`, `cuda`, `cuda:0`, `auto` |
| `OMNIVOICE_ENABLED` | `true` | Set `false` for a Piper-only deployment |
| `OMNIVOICE_MODEL` | `k2-fsa/OmniVoice` | HF model id |
| `OMNIVOICE_ASR_MODEL` | `openai/whisper-large-v3-turbo` | Whisper model |
| `OMNIVOICE_ASR_DEVICE` | unset | Optional ASR device override |
| `OMNIVOICE_LOAD_ASR` | `false` | Load ASR during warm-up |
| `MAX_INPUT_CHARS` | `8000` | OmniVoice text limit |
| `PIPER_MAX_TEXT_CHARS` | `200000` | Piper text limit |
| `VOICE_MAX_UPLOAD_MB` | `50` | Reference/transcription upload limit |
| `MIN_VOICE_SECONDS` / `MAX_VOICE_SECONDS` | `1.0` / `30.0` | Reference audio constraints |
| `MAX_IMPORT_MB` | `200` | Voice ZIP import limit |
| `DEFAULT_PIPER_VOICE` | `pt-PT-tugao` | Default Piper voice |
| `PIPER_SENTENCE_GAP_MS` | `120` | Silence between Piper sentences |
| `HF_HOME` | `/data/models/huggingface` | Hugging Face cache |

`OMNIVOICE_LORA_ADAPTER`, `OMNIVOICE_FLASHINFER` and
`OMNIVOICE_FLASHINFER_CUDA_GRAPH` are passed through for advanced deployments.
