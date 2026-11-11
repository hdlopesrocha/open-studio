# Open Studio

**One private, password-protected studio for music, video, voice, subtitles, images, documents and media tools.**
Every model runs locally in Docker. Every sub-page shares one file tree, one design system, one authentication layer and one global job system.

```
Browser ──► Vue 3 app ──► Gateway (password, sessions, API keys)
                              │
                              ├── Job Hub ── per-component queues × 13
                              ├── Shared Files (/data/files)
                              └── Micro-services (music, video, voice, SRT, images,
                                   documents, translation, summary, PDF, FFmpeg,
                                   yt-dlp, QVAC, LLM)
```

---

## Table of contents

- [What is included](#what-is-included)
- [Screenshots](#screenshots)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [First-run password](#first-run-password)
- [GPU acceleration](#gpu-acceleration)
- [Per-page guide](#per-page-guide)
- [Shared file storage](#shared-file-storage)
- [Global job system](#global-job-system)
- [REST API](#rest-api)
- [Configuration](#configuration)
- [Makefile reference](#makefile-reference)
- [Models and downloads](#models-and-downloads)
- [Docker services](#docker-services)
- [Security and privacy](#security-and-privacy)
- [Troubleshooting](#troubleshooting)
- [Testing and screenshots](#testing-and-screenshots)
- [Repository layout](#repository-layout)
- [Limitations and model licences](#limitations-and-model-licences)
- [Credits](#credits)

---

## What is included

| Area | Functionality |
|---|---|
| **Music** | ACE-Step 1.5 text-to-music, full songs, vocals/instrumental, structured lyrics, LLM lyric drafts, repaint, cover, extend, reference audio, variations, seeds, steps, guidance, BPM, duration, language, exports, project/song library and takes. |
| **Video** | Audio + SRT → analysed timeline → scene plan → procedural / Diffusers / ComfyUI / QVAC artwork → FFmpeg or OpenCV animation → styled subtitles → final MP4/MKV. Scene editor, timeline, image variants, depth maps, audio-reactive effects, pause/cancel, export panel. |
| **Voice** | OmniVoice zero-shot cloning, voice design by attributes, auto voice, Whisper transcription, 646 languages, Piper built-in voices, batch synthesis, retraining, export/import, previews, history. All TTS runs in Docker. |
| **Subtitles** | MP3 + lyrics → frame-accurate SRT using Whisper word timestamps and dynamic-programming lyric alignment. Transcribe, from-text timing, SRT/VTT/ASS conversion, editable cue table, optional cue translation. |
| **Images** | Unified picture generation with procedural, Diffusers, ComfyUI and QVAC providers. Text-to-image, image-to-image, upscaling, batches, seeds, samplers, LoRA, metadata sidecars and gallery. |
| **Documents** | PDF or text → OCR → translate → summarise → narrate → SRT/VTT → manifest + ZIP. Editable artifacts and PDF page previews. |
| **Translation** | One shared service for every page: OPUS-MT pt↔en, optional NLLB-200, detection, segments/page markers, glossaries, markup preservation, sync or job mode. |
| **Summary** | Hierarchical T5 summaries in English/Portuguese with short/medium/long budgets and cross-language output. |
| **FFmpeg** | 20+ operations in its own image: transcode, extract audio, trim, crop video/image, scale, rotate, concat, overlay, burn subtitles, frames, GIF, merge/replace audio, speed, volume, loudnorm, thumbnails, split, raw argv. Probe, progress and cancellation. |
| **yt-dlp** | Its own image and a full web UI/REST API: analyse formats, playlists, search, subtitles, thumbnails, metadata, audio extraction, cookies, SponsorBlock, rate limits, retries, proxies, archives and more. |
| **QVAC** | Tether QVAC SDK in Docker: WAN 2.1/2.2, LTX-2 and MiniMax-H3 text-to-video and image-to-video, QVAC diffusion images, ESRGAN upscaling, model lifecycle, all SDK knobs, mock mode for hardware-free demos. |
| **Files** | Shared file explorer with folders, upload, rename, move, copy, delete, preview, ZIP, extract and search. Actions are in a bottom toolbar; text, audio, images and video preview inline. |
| **Service manager** | Settings → Services enables/disables every optional service, builds images on demand, shows health, opens logs and can delete all shared files. |
| **Style references** | Music Studio accepts reference songs for a named style; ACE-Step uses the reference audio + prompt guidance on the next generation. |
| **Jobs** | Persistent central job hub with one queue per component, configurable parallelism, live SSE progress, cancellation, retry, artifacts and history. |
| **Auth** | First-use password setup (scrypt), HttpOnly sessions, API keys, session revocation, password changes. Every service is behind the gateway. |
| **UI** | Single Vue 3 app, one design system, right-aligned vertical navbar, responsive layout, consistent cards/forms/tables/job feedback. |

### What was de-duplicated

| Old project / service | New shared service |
|---|---|
| translation in micro-talk | `translation` — used by Documents, Subtitles, Translation page and any API client |
| image generation in video-studio | `imagegen` — used by the Images page and the video pipeline |
| media/FFmpeg in micro-talk + video-studio | `ffmpeg` — one media service for all tool pages and document finalisation |
| TTS in micro-talk (Piper) + voice-studio (OmniVoice) | `voice` — one TTS service with two engines |
| job managers in music/video/voice/micro-talk | `jobhub` — one global system with per-component queues |
| separate file stores | `files` — one `/data/files` tree mounted into every container |
| static auth tokens in micro-talk | `gateway` — first-run password, sessions and API keys |
| lyrics/video LLM clients | `llm` — one OpenAI-compatible bridge to Ollama or any compatible endpoint |

---

## Screenshots

All screenshots are real captures of the Vue app running with the deterministic
demo dataset (`make demo` / `npm run build:demo`), so they are reproducible
without downloading models. The workflows and controls shown are the same ones
used with live services.

### Dashboard
![Dashboard](docs/screenshots/dashboard.png)

### Setup — set the password on first use
![First-run password setup](docs/screenshots/setup.png)

### Sign in
![Sign in](docs/screenshots/login.png)

### Music studio
![Music studio](docs/screenshots/music.png)

### Video studio
![Video studio](docs/screenshots/video.png)

### Voice studio
![Voice studio](docs/screenshots/voice.png)

### AI subtitles
![AI subtitles](docs/screenshots/subtitles.png)

### Picture studio
![Picture studio](docs/screenshots/images.png)

### Documents
![Documents](docs/screenshots/documents.png)

### Translation
![Translation](docs/screenshots/translate.png)

### Summaries
![Summaries](docs/screenshots/summary.png)

### FFmpeg workbench
![FFmpeg workbench](docs/screenshots/ffmpeg.png)

### yt-dlp
![yt-dlp](docs/screenshots/ytdlp.png)

### QVAC video
![QVAC video](docs/screenshots/qvac.png)

### Files
![Files](docs/screenshots/files.png)

### Job center
![Job center](docs/screenshots/jobs.png)

### Settings
![Settings](docs/screenshots/settings.png)

---

## Architecture

```mermaid
flowchart LR
  B[Browser<br/>Vue 3] -->|/api + cookies| G[Gateway<br/>password / sessions / keys]
  G -->|auth reverse proxy| S[Micro-services]
  G --> H[Job hub<br/>13 queues]
  H -->|internal job protocol| S
  S <-->|read/write| F[(/data/files)]
  H --> DB[(job SQLite)]
  G --> A[(auth SQLite)]
  S --> J[Job hub progress]
  S --> L[LLM / Ollama]
  V[Video pipeline] --> VA[audio analysis]
  V --> VL[lyrics analysis]
  V --> VP[planner]
  V --> VI[imagegen]
  V --> VN[animation]
  V --> VR[renderer]
  D[Documents] --> P[PDF]
  D --> T[translation]
  D --> U[summary]
  D --> VO[voice]
  D --> FF[FFmpeg]
```

**Design rules**

1. The **gateway** is the only public API. All other services are private and also require a shared internal token.
2. Every long operation is a **job** in the central hub. Components execute jobs through `/internal/jobs/run` and report progress back.
3. Every service reads and writes **the same `/data/files` volume** using files-relative paths.
4. The frontend never talks to a component directly; it always goes through `/api/<service>/...`.
5. Each component has a **single catalog endpoint** so the UI can expose every model option rather than hard-coding controls.

---

## Requirements

### Minimum

- Linux, macOS or Windows with Docker Desktop / Docker Engine + Compose v2.
- 16 GB RAM (32 GB recommended for music/video/QVAC).
- 60 GB free disk for all images plus a basic model set; 120 GB+ if you want
  every optional checkpoint (models are large; see [Models](#models-and-downloads)).
- No GPU required. Everything has a CPU path.

### Recommended

- 32 GB+ RAM.
- NVIDIA GPU with 16 GB+ VRAM (voice, image generation, Whisper, QVAC), or an AMD/Intel GPU with Vulkan for ACE-Step/QVAC.
- 100 GB SSD.
- Ollama model for lyric drafts and video planning: `llama3.2:3b` (small) or `qwen2.5:7b` (better).

> QVAC video generation specifically needs roughly **16 GB VRAM or 20 GB unified memory** for real models. The app detects this and reports it; `QVAC_MOCK=1` produces short placeholder clips on any machine.

---

## Quick start

```bash
git clone <this-repo> open-studio
cd open-studio
make up
```

That single command:

1. creates `./data/{files,state,cache,models,artifacts,home}`;
2. copies `.env.example` to `.env`, generates a random `INTERNAL_TOKEN`, and
   records absolute shared-folder paths for the on-demand service manager;
3. builds and starts only the **always-on core**: `files`, `jobhub`, `admin`,
   `gateway` and the Vue frontend.

Open **http://localhost:8090**.

- The API gateway is also bound to loopback: `http://127.0.0.1:8091/api`.
- The first browser visit shows **Create your studio password**. There is no default password.
- After setup, everything (UI, REST API, file downloads) requires that session or an API key.
- All optional services start **disabled**. Open **Settings → Services** and enable
  only the services you need. The service manager builds the image on first use,
  starts the container, and reports health. Disabling stops and removes the
  container so its RAM/CPU is released. `make up-all` starts everything at once.

### On-demand services

| Default | Behavior |
|---|---|
| **Core only** | `gateway`, `admin`, `files`, `jobhub`, `frontend` are always on. |
| **Disabled by default** | Music, video, voice, subtitles, images, documents, text, FFmpeg, yt-dlp, QVAC, LLM and Ollama. Their Docker profiles are not active, so `make up` does **not** build their images. |
| **Enable** | Settings → Services → **Enable**. The admin service runs `docker compose --profile services up -d --build <service>`; first enable builds the image, later enables reuse it. |
| **Disable** | Stops and removes that container. Images stay cached on disk; the service can be re-enabled quickly. |
| **Dependencies** | Enabling a service starts its required helper services (for example Music starts `music-engine`, Video starts the video helpers + `imagegen`, Documents starts `voice`/`pdf`/`translation`/`summary`/`ffmpeg`). |
| **Health** | Every service shows running/stopped/healthy/unhealthy status in Settings → Services and in `/api/status`. |
| **Operations log** | Every Docker toggle is a normal global job; Settings shows the current job, its compose output and the recent Docker operations. |
| **Network** | Only the frontend and loopback gateway are published. The admin service is the only container with the Docker socket. |

The service manager is reached through the authenticated gateway at
`/api/admin/services`; it uses the repository and Compose file mounted read-only
inside the container and builds into the host Docker daemon.

### Download models (recommended once)

```bash
make models
```

This downloads the LLM, ACE-Step GGUF set, Whisper, OPUS-MT/T5 and Piper voices. QVAC and Diffusers checkpoints download on first use from their pages. To fetch only one family:

```bash
make models-llm
make models-music
make models-whisper
make models-text
make models-piper
```

### Check health

```bash
make health
make ps
make logs
```

### Stop

```bash
make down          # keep all data
make reset         # DESTRUCTIVE: delete containers + ./data
```

---

## First-run password

The gateway stores a **scrypt** password hash in `./data/state/auth.db`. No password is shipped. The first request to `/api/auth/status` reports `setup_required: true`; the UI redirects to `/setup`.

- Password minimum length: 8 (configurable).
- Sessions are random 256-bit tokens stored hashed, sent as an **HttpOnly, SameSite=Lax** cookie.
- Changing the password revokes all other sessions.
- API keys are created in **Settings → API keys**; only a hash is stored. Use them as `Authorization: Bearer osk_...`.
- Login attempts are rate-limited per minute.
- All internal services additionally require `X-Internal-Token`, which the gateway injects.

```bash
# First-run setup from the CLI (also possible in the UI)
curl -c cookies.txt -X POST http://127.0.0.1:8091/api/auth/setup \
  -H 'Content-Type: application/json' \
  -d '{"password":"a-long-password","confirm":"a-long-password"}'

# Create an API key
curl -b cookies.txt -X POST http://127.0.0.1:8091/api/auth/api-keys \
  -H 'Content-Type: application/json' -d '{"name":"n8n"}'

# Use it
curl -H 'Authorization: Bearer osk_...' http://127.0.0.1:8091/api/status
```

---

## GPU acceleration

### NVIDIA

```bash
make up-gpu
```

Adds the NVIDIA device reservation and builds CUDA wheels for:

- **voice** — torch `cu128`, `DEVICE=cuda`, Whisper ASR on GPU
- **imagegen** — torch `cu128`, Diffusers on GPU
- **srt** — CTranslate2 CUDA libraries and `WHISPER_DEVICE=cuda`
- **qvac** — Vulkan/CUDA device access, `QVAC_DEVICE=gpu`
- **ollama** — GPU access for the LLM

Requirements: NVIDIA driver + NVIDIA Container Toolkit.

```bash
make gpu-info
```

### AMD / Intel (Vulkan)

```bash
make up-vulkan
```

Adds `/dev/dri` and rebuilds ACE-Step with `-DGGML_VULKAN=ON`; QVAC, animation and renderer also get DRM devices. This is the path for Radeon/Intel iGPUs.

### CPU

```bash
make up
```

The default. Everything works, just slower. Useful environment variables:

```dotenv
ACESTEP_DEVICE=CPU          # or vulkan
WHISPER_DEVICE=cpu          # or cuda
VOICE_DEVICE=cpu            # or cuda
QVAC_DEVICE=cpu             # or gpu
TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
```

---

## Per-page guide

### Dashboard

Shows service health, active jobs, storage, compute, recent activity and quick links. The cards are live; click a service to open **Settings → System** or a studio card to start.

**Try it:** start a full video production, then open the dashboard to see the video and image jobs progressing in parallel.

---

### Music studio

![Music studio](docs/screenshots/music.png)

Music is project → songs → lyrics/takes. Each song owns its brief, structured lyrics, generation settings and takes.

**Concrete example — write and render a song**

1. **New project** → `Nocturno`, artist `Helena Rocha`.
2. **New song** → title `Nocturno`, language `Portuguese (Portugal)`, genre `Art pop`, mood `Introspective`, BPM `78`, duration `214`, vocal `female`.
3. Open **Lyrics**, add Verse/Chorus/Outro sections, paste lyrics, then **Save lyrics**.
4. Optional: **Draft with LLM** → theme “a city crossed after midnight”, direction “intimate, close-mic, Portuguese”, structure 4 sections → apply the draft.
5. In **Voice & style**, set vocal intensity, singing style, emotion and range.
6. In **Generate** choose:
   - Engine `ACE-Step 1.5 C++`, model `Turbo 2B`
   - Mode `Full song`
   - Variations `2`, seed `438921` (or lock a different seed)
   - Steps `8`, guidance `7`
   - Thinking/planner on, prompt expansion on
   - Source/reference audio only for repaint/cover
7. **Generate**. The job appears in the right panel and in **Jobs**.
8. When takes arrive, play them, favourite one and set it as **Master**.
9. **Export** → WAV/MP3/FLAC or the whole session ZIP.

**Repaint a section**

- Mode `Repaint section`, choose a source take, set `start=60`, `end=78`, cover strength `0.75`, then generate. The engine keeps the rest of the take.

**Cover an existing song**

- Mode `Cover / re-imagine`, pick a source audio file from **Files**, choose a model that supports cover, set instructions, generate.

REST example:

```bash
curl -H 'Authorization: Bearer osk_...' \
  -H 'Content-Type: application/json' \
  http://127.0.0.1:8091/api/music/songs/<song-id>/generate \
  -d '{"mode":"full","variations":2,"seed":438921,"duration":214,"bpm":78,
       "model_id":"acestep-v15-turbo","inference_steps":8,"guidance_scale":7,
       "thinking":true,"use_format":true,"instruction":"intimate analog warmth"}'
```

The response is a **job**; poll `GET /api/jobs/<id>`.

---

### Video studio

![Video studio](docs/screenshots/video.png)

Input: an audio file and an SRT file. Output: a completed music video with planned scenes, artwork, camera motion, transitions and burned-in styled subtitles.

**Concrete example — “Atravessar a Noite”**

1. **New video**.
2. Pick `atravessar-noite.mp3` and `atravessar-noite.srt` (upload them in the picker; they land in shared Files).
3. Style `Cinematic`; image provider `auto` (procedural falls back for free; Diffusers/ComfyUI/QVAC can be selected); animation `ffmpeg`; 1920×1080, 30 fps, H.264; scene target `8 s`; subtitles `karaoke`; audio-reactive `beat pulse` + `bass pulse`.
4. **Create video**. The project opens in the **Editor**.
5. Click **Full pipeline**. Stages: analyse audio → analyse lyrics → plan → generate images → animate → render → subtitles.
6. Watch progress in **Production status** and **Jobs**. The pipeline can be paused/cancelled through the underlying job and retried.
7. Click a scene in the rail to inspect/edit:
   - description, visual prompt, negative prompt
   - camera move (`slow push`, `orbit`, `handheld`…)
   - transition (`dissolve`, `cut`, `zoom blur`…)
   - effects (`grain`, `bloom`, `particles`, `beat pulse`…)
   - duration/timing, lyrics, depth map, image variants
8. **Regenerate scene** with a new prompt, provider or variant count.
9. **Render** with your preferred resolution/codec/subtitle style, then download the MP4, SRT and thumbnail; the ZIP contains all assets.

REST example:

```bash
# Create a project from files already in the shared tree
curl -H 'Authorization: Bearer osk_...' -H 'Content-Type: application/json' \
  http://127.0.0.1:8091/api/video/projects \
  -d '{"name":"atravessar-noite","title":"Atravessar a Noite",
       "artist":"Helena Rocha",
       "audio_path":"uploads/atravessar-noite.mp3",
       "srt_path":"uploads/atravessar-noite.srt",
       "config":{"output":{"resolution":"1080p","fps":30,"codec":"h264"},
                 "scenes":{"style_id":"cinematic","target_duration":8,
                           "image_provider":"auto"},
                 "subtitles":{"burn_in":true}}}'

# Run the whole pipeline as a global job
curl -H 'Authorization: Bearer osk_...' -H 'Content-Type: application/json' \
  http://127.0.0.1:8091/api/video/projects/<project-id>/run \
  -d '{"action":"full","options":{"force":false}}'
```

---

### Voice studio

![Voice studio](docs/screenshots/voice.png)

All TTS runs in Docker. One service exposes two engines:

- **OmniVoice** — zero-shot cloning, design and auto voice, 646 languages, Whisper ASR.
- **Piper** — five fast built-in ONNX voices for Portuguese/English.

**Concrete example — clone a voice and narrate a chapter**

1. **Voices → Train voice**.
2. Name `Helena — close`; record 5–10 seconds or upload a clean WAV/MP3; optional transcript (press **Transcribe**); language `Portuguese (Portugal)`; preprocess on; consent checked.
3. **Train voice**. Wait for the profile and preview.
4. **Studio** → select `Helena — close`, paste the chapter, choose language, speed `1.0`, quality `32`, format `MP3`.
5. Optional: **Advanced** → steps, guidance, t-shift, denoise, seed, text normalisation, preprocess/postprocess.
6. **Generate speech**. Play the waveform, check RTF, download, or open **History**.
7. For a quick built-in voice, choose engine `Piper`, mode `Auto`, pick e.g. `pt-PT-tugao`; no training required.
8. **Design** creates a voice from attributes: `female, low pitch, british accent, whisper` → generate or batch.
9. **Batch** supports blank-line or one-per-line splitting, up to 50 items, and a ZIP with per-item metadata.

REST example:

```bash
curl -H 'Authorization: Bearer osk_...' -H 'Content-Type: application/json' \
  http://127.0.0.1:8091/api/voice/tts \
  -d '{"engine":"omnivoice","mode":"voice","voice_id":"<voice-id>",
       "text":"A cidade fecha os olhos devagar.","language":"pt-PT",
       "speed":1.0,"num_step":32,"format":"mp3","normalize_text":true}'

# OpenAI-compatible endpoint
curl -H 'Authorization: Bearer osk_...' -H 'Content-Type: application/json' \
  http://127.0.0.1:8091/api/voice/v1/audio/speech \
  -d '{"input":"Hello from Open Studio","voice":"auto","response_format":"mp3"}'
```

---

### AI subtitles

![AI subtitles](docs/screenshots/subtitles.png)

The key feature is **mp3 + lyrics → SRT**: Whisper produces word timestamps, then a
normalised dynamic-programming matcher aligns your lyric lines to the audio.

**Concrete example — align “Nocturno”**

1. Choose `music/nocturno/master/nocturno-master.wav`.
2. Paste the lyrics, one line per cue; blank lines are stanza breaks.
3. Model `large-v3`, language `Portuguese`, beam `5`, VAD on, word timestamps on.
4. **Align lyrics**. The job reports progress.
5. Review the editable cue table: adjust times/text, split/merge cues.
6. Download **SRT**, **VTT**, **ASS** or send the file to the video project.
7. Optional: **Translate** to another language (the translation service preserves cue structure).

Other tabs:

- **Transcribe** — speech → subtitles without supplied lyrics.
- **From text** — estimate cue timings from plain text and a known duration.
- **Convert** — SRT ↔ VTT ↔ ASS, with ASS styling options.

REST example:

```bash
curl -H 'Authorization: Bearer osk_...' -H 'Content-Type: application/json' \
  http://127.0.0.1:8091/api/srt/align \
  -d '{"audio_path":"music/nocturno/master/nocturno-master.wav",
       "lyrics":"A cidade fecha os olhos devagar\nEu conto os passos até te encontrar",
       "model":"large-v3","language":"pt","word_timestamps":true,
       "output_format":"srt","max_line_chars":42}'
```

---

### Picture studio

![Picture studio](docs/screenshots/images.png)

Providers:

- **procedural** — deterministic Pillow artwork, always available, no weights.
- **diffusers** — SD 1.5/SDXL/SD-Turbo/FLUX via Hugging Face on CPU or CUDA.
- **comfyui** — external ComfyUI with placeholder-substituted API workflows.
- **qvac** — QVAC's diffusion backend.

**Concrete example — album cover**

1. Prompt: `Porcelain city at dusk, cinematic, violet haze, wet asphalt, anamorphic light`.
2. Negative: `low quality, text, watermark, extra fingers`.
3. Provider `diffusers`, model `FLUX.1 dev` (or `procedural` for instant results).
4. 1024×1024, steps `28`, guidance `3.5`, seed `428193`, batch `4`, sampler `euler`, scheduler `karras`.
5. **Generate 4 images**. Each image gets a JSON sidecar with the full request.
6. Open the gallery, inspect metadata, download or reuse the prompt.
7. **Image-to-image** uses an init image + strength; **Upscale** resizes with Pillow or an ESRGAN provider.

```bash
curl -H 'Authorization: Bearer osk_...' -H 'Content-Type: application/json' \
  http://127.0.0.1:8091/api/images/generate \
  -d '{"provider":"diffusers","model":"stabilityai/sd-turbo",
       "prompt":"porcelain city at dusk","negative_prompt":"text, watermark",
       "width":1024,"height":1024,"steps":8,"guidance":0,"seed":428193,
       "batch_count":4,"output_format":"png"}'
```

The job result contains `images[].path`, thumbnails and sidecars, all usable from every other page.

---

### Documents

![Documents](docs/screenshots/documents.png)

The document pipeline joins the **PDF**, **translation**, **summary**, **voice** and
**FFmpeg** services. It accepts a PDF from Files or pasted text.

**Concrete example — annual report → Portuguese narration + subtitles**

1. Pick `annual-report-2026.pdf` (42 pages).
2. OCR off (text PDF), or on with `eng`/`por` for scans; select pages `1,3,7-9` or a range.
3. Translation on: `auto → Portuguese (Portugal)`, model auto, beam 2.
4. Summary on: `medium`, Portuguese, hierarchical T5.
5. Voice on: `Piper` or `OmniVoice`, voice `Tugão`/`Helena — close`, MP3, normalise, text source `summary`.
6. Subtitles on (`SRT`), ZIP on.
7. **Run document pipeline**. Stages show extraction → translation → summary → narration → subtitles → archive.
8. Edit extracted/translation/summary text inline; save updates the artifacts.
9. Play audio, download SRT/VTT/ZIP, inspect the page previews and manifest.

REST example:

```bash
curl -H 'Authorization: Bearer osk_...' -H 'Content-Type: application/json' \
  http://127.0.0.1:8091/api/docs/run \
  -d '{"title":"Annual report","input":{"type":"pdf",
        "pdf_path":"uploads/annual-report-2026.pdf","start_page":1,"end_page":42},
       "translation":{"enabled":true,"target_language":"pt-PT"},
       "summary":{"enabled":true,"length":"medium","language":"pt-PT"},
       "tts":{"enabled":true,"engine":"piper","piper_voice":"pt-PT-tugao",
              "format":"mp3","text_source":"summary"},
       "subtitles":{"enabled":true,"format":"srt"},"zip":{"enabled":true}}'
```

---

### Translation

![Translation](docs/screenshots/translate.png)

One shared service used by the Translate page, Documents and Subtitles.

- **OPUS-MT** pt↔en is the fast default (PT variants supported).
- **NLLB-200** is optional and can translate many languages; install with `make models-text` or the translation service's `download-models --models nllb`.
- Parameters: beam size, max length, temperature, length/repetition penalties, no-repeat n-gram, batch size, markup preservation, glossary rows.
- Sync mode for short text, **Run as job** for long documents.

**Concrete example:** paste Portuguese lyrics, set target English, detect source, translate, then **Save** to `documents/translation/nocturne-pt-en.txt`. The video or documents page can pick it up immediately.

```bash
curl -H 'Authorization: Bearer osk_...' -H 'Content-Type: application/json' \
  http://127.0.0.1:8091/api/translate/translate \
  -d '{"text":"A cidade fecha os olhos devagar","source_language":"pt",
       "target_language":"en","num_beams":4,"preserve_markup":true}'
```

---

### Summaries

![Summaries](docs/screenshots/summary.png)

Hierarchical T5 map-reduce summaries with `short` (~120 tokens), `medium`
(~240) and `long` (~420) budgets. Options include language, source language,
model, max/min tokens, beams, temperature, chunk size and hierarchical on/off.
Long inputs are chunked and reduced level by level; cross-language summaries go
through the shared translation service.

**Concrete example:** load the annual report extracted text, length `medium`, language `English`, hierarchical on, summarise, edit the result, save to `documents/summary/annual-report-2026-en.txt`.

---

### FFmpeg workbench

![FFmpeg workbench](docs/screenshots/ffmpeg.png)

FFmpeg has its own Docker image and is a first-class service, not a hidden helper.

Operations exposed in the UI and API:

| Operation | What it does |
|---|---|
| `transcode` | video/audio codec, CRF, preset, bitrate, pixel format, resolution, fps, format |
| `extract_audio` | MP3/WAV/FLAC/AAC/Opus/OGG, bitrate, sample rate, channels, loudnorm |
| `trim` | `-ss`, `-to`, duration, stream-copy or frame-accurate |
| `crop_video` / `crop_image` | width/height/x/y, aspect, image format |
| `scale` | fit/fill/stretch, pad colour, flags |
| `rotate` | 90/180/270/arbitrary, h/v flip, image rotate |
| `concat` | ordered inputs, copy or re-encode, optional xfade transitions |
| `overlay` | image/text watermark, 9-grid position, opacity, margin, font/colour, timing |
| `subtitles` | burn SRT/VTT/ASS, font, size, colour, outline, position |
| `frames` | fps or timestamps, JPG/PNG, width |
| `gif` | start, duration, fps, width, palette |
| `merge` / `replace_audio` | mux video+audio, replace or mute original |
| `speed` | video/audio factor, pitch correction |
| `volume` / `normalize` | gain dB, two-pass loudnorm, target LUFS |
| `thumbnail` | time, width |
| `split` / `segment` | fixed-duration segments |
| `metadata` | strip or set metadata |
| `raw` | arbitrary ffmpeg argv (no shell), for advanced users |

Every operation accepts files-relative input/output paths, reports progress, can
run synchronously for short tasks or as a global job for long ones, and cancels
the entire process group.

```bash
# Trim and transcode a video
curl -H 'Authorization: Bearer osk_...' -H 'Content-Type: application/json' \
  http://127.0.0.1:8091/api/ffmpeg/run \
  -d '{"operation":"trim","input_path":"video/projects/demo/output/final_video.mp4",
       "output_path":"ffmpeg/exports/clip.mp4",
       "options":{"start":12.5,"end":42.5,"video_codec":"libx264","crf":20}}'
```

---

### yt-dlp

![yt-dlp](docs/screenshots/ytdlp.png)

yt-dlp runs in its own image with FFmpeg available.

The UI exposes:

- **Analyse** any URL: title, uploader, duration, views, description, thumbnail and every format.
- **Format selection**: preset, exact format ID, custom format string, audio-only.
- **Post-processing**: merge container, output template/folder, subtitles (write/embed/convert), thumbnail (write/embed), info JSON, description, comments, remux/recode, keep video.
- **Playlist**: full playlist, item ranges, reverse, max downloads.
- **Network**: proxy, cookies file/browser, UA, referer, headers, geo bypass, no-check-cert, source address, socket timeout.
- **Rate control**: limit rate, retries, fragment retries, concurrent fragments, sleep intervals.
- **SponsorBlock**: mark/remove categories.
- **Archive**: download archive, no-part, continue.

```bash
# Analyse
curl -H 'Authorization: Bearer osk_...' -H 'Content-Type: application/json' \
  http://127.0.0.1:8091/api/ytdlp/info -d '{"url":"https://www.youtube.com/watch?v=..."}'

# Download best video + audio, embed subtitles and thumbnail
curl -H 'Authorization: Bearer osk_...' -H 'Content-Type: application/json' \
  http://127.0.0.1:8091/api/ytdlp/download \
  -d '{"url":"https://www.youtube.com/watch?v=...","format":"bestvideo*+bestaudio/best",
       "merge_output_format":"mp4","subtitles":true,"subtitle_langs":["pt","en"],
       "embed_subs":true,"embed_thumbnail":true,"write_info_json":true,
       "output_path":"ytdlp/field-recordings"}'
```

Downloaded files appear in **Files** under `ytdlp/<job-id>/` and can be sent straight to FFmpeg, Subtitles, Video or Voice.

---

### QVAC video

![QVAC video](docs/screenshots/qvac.png)

QVAC is Tether's local AI SDK. The QVAC service is a Node 22 Docker image with
`@qvac/sdk`, FFmpeg and Vulkan runtime libraries. The page exposes **all SDK
controls**, not a subset.

- **Video**: `txt2vid` / `img2vid`; WAN 2.1 T2V 1.3B, WAN 2.1 I2V 14B, Wan 2.2 TI2V-5B, Wan 2.2 A14B dual-expert, LTX-2 and MiniMax-H3.
- **Common knobs**: prompt, negative prompt, init image, width, height, `video_frames`, fps, steps, cfg scale, flow shift, seed, scheduler, strength, reference images, LoRA + strength, STG scale/block, reference attention/downscale, temporal tiling, VAE tile size.
- **High-noise expert**: high-noise steps/sample method/scheduler/cfg/flow shift, MoE boundary.
- **Model load**: diffusion source, text encoder, VAE, CLIP vision, audio VAE, connectors, projection, unconditional model, device, threads, backend, offload, VAE tiling, max VRAM, flash attention.
- **Image**: prompt, negative, size, steps, guidance, cfg, seed, batch, sampling method, init image(s), strength, LoRA, upscale.
- **Upscale**: standalone ESRGAN with repeats.
- **Models**: family table, VRAM, mode, installed state, load/unload.

The service reports memory and hardware constraints. If the machine cannot run
QVAC, set `QVAC_MOCK=1` to generate deterministic short clips for UI demos.

```bash
curl -H 'Authorization: Bearer osk_...' -H 'Content-Type: application/json' \
  http://127.0.0.1:8091/api/qvac/video \
  -d '{"mode":"txt2vid","model":"WAN2_1_T2V_1_3B_FP16",
       "prompt":"a slow dolly through a rain-soaked street at 4am",
       "negative_prompt":"blurry, watermark, jitter",
       "width":480,"height":832,"video_frames":33,"fps":16,
       "steps":30,"cfg_scale":6.0,"flow_shift":3.0,"seed":42}'
```

---

### Files

![Files](docs/screenshots/files.png)

One folder for every service. The explorer supports:

- create folder, upload (multi-file), rename, move, copy, delete
- list/grid views, breadcrumbs, filter, search
- image/audio/video preview, text/subtitle preview
- ZIP selected items, extract ZIP
- file stats and disk usage

Everything is addressed by a files-relative path such as
`music/nocturno/master/nocturno-master.wav` or
`video/projects/atravessar-noite/output/final_video.mp4`. Any service can use any
path produced by another service. That is the transparent inter-service layer.

---

### Jobs

![Job center](docs/screenshots/jobs.png)

The hub persists jobs in SQLite and runs **one queue per component**:

```
music (1)   video (2)   voice (1)   srt (1)   imagegen (1)
docs (2)    pdf (2)     translation (2)        summary (1)
ffmpeg (2)  ytdlp (2)   qvac (1)    llm (2)
```

- Heavy components run in parallel without blocking each other.
- Per-component concurrency is configurable in `.env`.
- Jobs have `queued/running/canceling/completed/failed/canceled`, stage, message, progress, warnings, error and artifacts.
- SSE events (`/api/jobs/events`) update the UI live; polling is a fallback.
- Cancel requests are forwarded to the component; FFmpeg/yt-dlp kill their process groups, ACE-Step gets a cancel call, voice/other components stop at checkpoints.
- Retry clones a job with the same parameters. Delete only terminal jobs.
- Artifacts are files-relative paths, immediately downloadable and reusable.

```bash
# Submit any component job
curl -H 'Authorization: Bearer osk_...' -H 'Content-Type: application/json' \
  http://127.0.0.1:8091/api/jobs \
  -d '{"component":"imagegen","action":"generate","title":"Cover",
       "params":{"provider":"procedural","prompt":"porcelain city","width":1024,"height":1024}}'

# Poll / stream
curl -H 'Authorization: Bearer osk_...' http://127.0.0.1:8091/api/jobs
curl -N -H 'Authorization: Bearer osk_...' http://127.0.0.1:8091/api/jobs/events
```

---

### Settings

![Settings](docs/screenshots/settings.png)

- **Security**: change password, list/revoke sessions.
- **API keys**: create, copy once, revoke; examples for jobs, image generation and uploads.
- **System**: service health, storage, CPU/memory/GPU, files root, version.
- **Models & commands**: exact `make` commands for models, GPU starts, tests and logs.
- **Configuration table**: the main `.env` variables.

---

## Shared file storage

Host folder `./data/` is mounted into every container:

```
data/
├── files/                  # ← the single user-visible tree
│   ├── uploads/            # uploads from the file picker
│   ├── music/              # projects/<id>/songs..., takes, exports
│   ├── video/projects/     # input, analysis, planning, assets, output
│   ├── voices/             # trained voice profiles: <id>/reference.wav, prompt.pt, meta.json
│   ├── voice/              # TTS outputs, uploads and transient audio
│   ├── images/             # <job-id>/ images, thumbnails, sidecars
│   ├── documents/          # <job-id>/ text, audio, srt, manifest, zip
│   ├── subtitles/          # <job-id>/ srt, vtt, ass, cues.json
│   ├── ffmpeg/             # operation outputs
│   ├── ytdlp/              # downloaded media
│   ├── qvac/               # generated video/image
│   └── tmp/                # archives and scratch files
├── state/                  # auth.db, jobs.db, internal.token, per-service state
├── models/                 # Hugging Face, GGUF, Piper, Whisper, QVAC
├── cache/                  # analysis/image/video caches
├── home/                   # shared HOME/XDG cache for every container
└── artifacts/              # service artifacts (optional)
```

All paths returned by APIs are **relative to `data/files`**. The frontend builds
`/api/files/raw/<path>` for playback and `/api/files/download?path=<path>` for
downloads. Backups: `make backup` tars `data/files`, `data/state` and `.env`.

---

## Global job system

**API**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/jobs` | List jobs (`component`, `status`, `limit`, `offset`, `parent_id`) |
| `POST` | `/api/jobs` | Create a job (`component`, `action`, `title`, `params`) |
| `GET` | `/api/jobs/{id}` | Job details, result, artifacts, warnings |
| `GET` | `/api/jobs/{id}/events` | Per-job SSE stream |
| `GET` | `/api/jobs/events` | Global SSE stream |
| `POST` | `/api/jobs/{id}/cancel` | Cooperative cancel |
| `POST` | `/api/jobs/{id}/retry` | Clone with the same params |
| `DELETE` | `/api/jobs/{id}` | Delete a terminal job record |
| `GET` | `/api/jobs/queues` | Per-component concurrency/queued/running counts |

**Internal protocol** (component side): `POST /internal/jobs/run` with
`{job_id, action, params}`; progress at `POST /internal/jobs/{id}/progress`;
cancel at `POST /internal/jobs/{id}/cancel`; cancel state at
`GET /internal/jobs/{id}/cancel-state`. Every request carries
`X-Internal-Token`.

**Result shape**

```json
{
  "message": "Generated 4 image(s).",
  "files": [
    {"path": "images/ab12/cover-01.png", "kind": "image", "mime": "image/png", "name": "cover-01.png", "size": 184320}
  ],
  "data": {"seed": 428193, "provider": "diffusers", "images": []}
}
```

Jobs survive gateway/component restarts: queued jobs are requeued, running jobs
are marked recovered and re-dispatched. Components are expected to be
idempotent or to fail safely if a job is retried.

---

## REST API

The gateway serves `/api/...`; interactive OpenAPI is available at
`/api/docs` when `ENABLE_DOCS=1`. All endpoints except health/auth-status/setup/login
require a session cookie or API key.

```bash
# Health (public)
curl http://127.0.0.1:8091/api/health

# Status (authenticated)
curl -H 'Authorization: Bearer osk_...' http://127.0.0.1:8091/api/status

# Upload a file
curl -H 'Authorization: Bearer osk_...' -F file=@master.wav -F path=uploads \
  http://127.0.0.1:8091/api/files/upload

# List, read text, download
curl -H 'Authorization: Bearer osk_...' 'http://127.0.0.1:8091/api/files/list?path=music'
curl -H 'Authorization: Bearer osk_...' 'http://127.0.0.1:8091/api/files/read?path=uploads/lyrics.txt'
curl -OJ -H 'Authorization: Bearer osk_...' \
  'http://127.0.0.1:8091/api/files/download?path=music/nocturno/master/nocturno-master.wav'
```

### Service route map

| Prefix | Service | Example |
|---|---|---|
| `/api/auth/*` | Gateway auth | `POST /api/auth/login` |
| `/api/status` | Aggregated status | `GET /api/status` |
| `/api/jobs/*` | Job hub | `POST /api/jobs` |
| `/api/files/*` | Shared files | `GET /api/files/list` |
| `/api/admin/*` | Service manager | `GET /api/admin/services`, `POST /api/admin/services/{name}/enable` |
| `/api/music/*` | Music | `POST /api/music/songs/{id}/generate` |
| `/api/video/*` | Video | `POST /api/video/projects/{id}/run` |
| `/api/voice/*` | Voice/TTS | `POST /api/voice/tts`, `POST /api/voice/v1/audio/speech` |
| `/api/srt/*` | Subtitles | `POST /api/srt/align` |
| `/api/images/*` | Picture generation | `POST /api/images/generate` |
| `/api/docs/*` | Documents | `POST /api/docs/run` |
| `/api/translate/*` | Translation | `POST /api/translate/translate` |
| `/api/summary/*` | Summary | `POST /api/summary/summarize` |
| `/api/pdf/*` | PDF | `POST /api/pdf/extract` |
| `/api/ffmpeg/*` | FFmpeg | `POST /api/ffmpeg/run` |
| `/api/ytdlp/*` | yt-dlp | `POST /api/ytdlp/download` |
| `/api/qvac/*` | QVAC | `POST /api/qvac/video` |
| `/api/llm/*` | LLM bridge | `POST /api/llm/chat` |

Every service also has `GET /health`, `GET /catalog` or equivalent discovery
routes, and OpenAPI docs inside its container. Documents and videos expose
resource CRUD endpoints; jobs are always via the hub.

---

## Configuration

Copy `.env.example` to `.env` (`make init` does it) and edit. The most important
variables:

| Variable | Default | Purpose |
|---|---|---|
| `OPENSTUDIO_PORT` | `8090` | Published web app port |
| `GATEWAY_PORT` | `8091` | Loopback API port |
| `INTERNAL_TOKEN` | generated | Shared secret between services; also persisted in `data/state/internal.token` |
| `SESSION_COOKIE_SECURE` | `false` | Set true behind HTTPS |
| `MIN_PASSWORD_LENGTH` | `8` | First-run password minimum |
| `OLLAMA_MODEL` | `llama3.2:3b` | Lyrics/planner model |
| `LLM_BASE_URL` | `http://ollama:11434/v1` | Any OpenAI-compatible endpoint |
| `IMAGEGEN_DEFAULT_PROVIDER` | `auto` | procedural/diffusers/comfyui/qvac |
| `COMFYUI_URL` | `http://host.docker.internal:8188` | External ComfyUI |
| `COMFYUI_IMAGE_WORKFLOW` | empty | API-format workflow JSON path |
| `ACESTEP_DEVICE` | `CPU` | `CPU` or `vulkan` |
| `ACESTEP_DOWNLOAD_MODELS` | `true` | Download GGUF on music-engine start |
| `ACESTEP_LM_SIZE` | `0.6B` | 0.6B/1.7B/4B planner |
| `ACESTEP_QUANT` | `Q8_0` | Q4_K_M/Q5_K_M/Q6_K/Q8_0/BF16 |
| `ACESTEP_DIT_VARIANT` | `turbo` | turbo/sft/base |
| `VOICE_DEVICE` | `cpu` | `cuda` for NVIDIA voice |
| `TORCH_INDEX_URL` | CPU wheel index | CUDA override uses cu128 |
| `WHISPER_DEVICE` | `auto` | cpu/cuda |
| `QVAC_DEVICE` | `cpu` | cpu/gpu |
| `QVAC_MOCK` | `0` | 1 = hardware-free demo clips |
| `MUSIC_CONCURRENCY` | `1` | Parallel music jobs |
| `VIDEO_CONCURRENCY` | `2` | Parallel video pipelines |
| `FFMPEG_CONCURRENCY` | `2` | Parallel ffmpeg jobs |
| `YTDLP_CONCURRENCY` | `2` | Parallel downloads |

See [`.env.example`](.env.example) for every option and comment.

---

## Makefile reference

| Target | What it does |
|---|---|
| `make up` | Create data/.env and start the always-on core (optional services stay disabled) |
| `make up-gpu` | Core in NVIDIA mode; services enabled later build with CUDA |
| `make up-vulkan` | Core in AMD/Intel Vulkan mode; services enabled later build with Vulkan |
| `make up-all` | Build/start every optional service immediately |
| `make down` | Stop/remove every profile container, keep data |
| `make ps` | Container status |
| `make logs [SERVICE=...]` | Follow logs |
| `make wait` | Wait for gateway + frontend health |
| `make health` | Probe public app and gateway |
| `make status` | Containers + gateway health |
| `make models` | Download LLM + music + Whisper + text + Piper models |
| `make models-llm/music/whisper/text/piper/images/qvac` | Per-family downloads |
| `make gpu-info` | NVIDIA, `/dev/dri` and Vulkan info |
| `make test` | Python compile/tests + frontend typecheck/build |
| `make verify` | Smoke test a running stack |
| `make screenshots` | Build demo UI and capture `docs/screenshots/*.png` |
| `make demo` | Serve the demo build without backends |
| `make backup` | Tar `data/files`, `data/state`, `.env` |
| `make fix-perms` | Fix `./data` ownership to the current host user |
| `make reset` | **Destructive** wipe of containers and `data/` |
| `make clean` | Remove stopped containers and dangling images |
| `make shell SERVICE=gateway` | Shell into a container |
| `make api-url` | Print API URL and curl example |

---

## Models and downloads

| Component | Model(s) | Approx. download | Runtime |
|---|---|---|---|
| Music | ACE-Step 1.5 Turbo Q8_0 + 0.6B LM + Qwen3 embedding + VAE | ~7.7 GB | GGUF C++ CPU/Vulkan |
| Lyrics/planner | Ollama `llama3.2:3b` (or chosen model) | 2 GB | Ollama CPU/GPU |
| Voice | OmniVoice `k2-fsa/OmniVoice` + Whisper large-v3-turbo | 4–8 GB | Torch CPU/CUDA |
| Voice | 5 Piper voices | ~330 MB | ONNX CPU |
| Subtitles | faster-whisper tiny→large-v3 | 75 MB–3 GB | CTranslate2 CPU/CUDA |
| Translation | OPUS-MT pt↔en, optional NLLB-200 600M | 1.2 GB / 2.4 GB | Torch CPU |
| Summary | T5 EN + PT small | ~500 MB | Torch CPU |
| Images | Optional SD/SDXL/FLUX checkpoints | 2–20 GB | Diffusers CPU/CUDA |
| QVAC | WAN 2.1/2.2, LTX-2, MiniMax-H3 | 4–25 GB per family | QVAC SD.cpp / Vulkan |

Models are cached in `./data/models` and never re-downloaded unless removed.
`make models` is explicit; normal startup does not silently pull multi-gigabyte
weights except ACE-Step's engine (controlled by `ACESTEP_DOWNLOAD_MODELS`).
Optional service images are not built while their service is disabled; the
first enable in Settings builds that image, then caches it for later toggles.

---

## Docker services

| Service | Image | Port | Role |
|---|---|---|---|
| `frontend` | `openstudio/frontend` | `8090:80` | Vue app + nginx proxy |
| `gateway` | `openstudio/gateway` | `127.0.0.1:8091:8000` | Auth, status, reverse proxy |
| `jobhub` | `openstudio/jobhub` | internal | Global job queues + SSE |
| `files` | `openstudio/files` | internal | Shared storage API |
| `llm` | `openstudio/llm` | internal | OpenAI-compatible bridge |
| `ollama` | `ollama/ollama` | internal | Local LLM runtime |
| `music` | `openstudio/music` | internal | Projects/songs/lyrics/takes |
| `music-engine` | `openstudio/music-engine` | internal | ACE-Step GGUF engine |
| `video` | `openstudio/video` | internal | Video orchestrator |
| `video-audio` | `openstudio/video-audio` | internal | Librosa analysis |
| `video-lyrics` | `openstudio/video-lyrics` | internal | SRT analysis |
| `video-planner` | `openstudio/video-planner` | internal | Scene planner |
| `video-animation` | `openstudio/video-animation` | internal | FFmpeg/OpenCV animation |
| `video-renderer` | `openstudio/video-renderer` | internal | Final assemble + subtitles |
| `voice` | `openstudio/voice` | internal | OmniVoice + Piper TTS |
| `srt` | `openstudio/srt` | internal | Whisper + lyric alignment |
| `imagegen` | `openstudio/imagegen` | internal | Procedural/Diffusers/ComfyUI/QVAC images |
| `docs` | `openstudio/docs` | internal | Document pipeline |
| `translation` | `openstudio/translation` | internal | OPUS-MT/NLLB |
| `summary` | `openstudio/summary` | internal | T5 summaries |
| `pdf` | `openstudio/pdf` | internal | PyMuPDF + Tesseract |
| `ffmpeg` | `openstudio/ffmpeg` | internal | Media operations |
| `ytdlp` | `openstudio/ytdlp` | internal | yt-dlp downloads |
| `qvac` | `openstudio/qvac` | internal | Tether QVAC SDK |

All app services mount the same `./data` subdirectories and share
`HOME=/data/home`, so caches, voice profiles, generated media and downloads are
visible across every image. Optional services are behind the `services` Compose
profile and stay stopped until enabled in Settings. Only the frontend port and
the loopback gateway port are published.

---

## Security and privacy

- Single-user, local-first. No telemetry, no cloud calls except model downloads.
- First-run password is mandatory; no default credentials.
- Passwords are **scrypt** hashed with a random salt.
- Session cookies are HttpOnly, SameSite=Lax, optionally Secure.
- API keys are stored hashed and shown once.
- Internal services require `X-Internal-Token`; compose generates a random token.
- The `admin` service mounts the Docker socket so Settings can build/start services. It is reachable only through the authenticated gateway and is intended for a trusted local machine.
- The gateway rejects unauthenticated requests to every `/api/*` route (except health/status/auth/setup/login).
- File paths are sanitised: traversal, absolute paths and unsafe ZIP entries are rejected.
- Bind the app to a trusted LAN/VPN. For internet exposure, put it behind a TLS reverse proxy, set `SESSION_COOKIE_SECURE=true`, and restrict `CORS_ORIGINS`.
- Models and generated content are your responsibility; see licences below.

---

## Troubleshooting

### The page loads but says services are offline

```bash
make ps
make logs
make health
```

The dashboard shows per-service status and the error detail. A single heavy
service (e.g. QVAC without a GPU) can be offline while the rest works.

### `403 Invalid internal token`

This means a running container was started with a different `INTERNAL_TOKEN` than the gateway. The token is now persisted in `data/state/internal.token` and `make up` force-recreates the core with it.

```bash
make down
make up
```

Then disable/re-enable any optional service that was already running. Do not edit
`INTERNAL_TOKEN` manually unless you also delete `data/state/internal.token` and
restart every container.

### `music-engine` says `/data/models/acestep` is not writable

The engine image runs as the host UID/GID recorded by `make init` (`OPENSTUDIO_UID` /
`OPENSTUDIO_GID`). Recreate the data directories with the correct ownership:

```bash
make init
make fix-perms
make down && make up
```

Then enable **Music** in Settings.

### First page keeps redirecting to setup/login

- The auth database is in `./data/state/auth.db`. Removing it resets the password
  (and logs everyone out).
- If you changed `SESSION_COOKIE_SECURE=true` but are on HTTP, the cookie will
  not be stored. Set it back to `false` or use HTTPS.
- Clear the `os_session` cookie and reload.

### Music engine downloads then exits

- Check `docker compose logs music-engine`.
- Ensure `./data/models` is writable and has ≥10 GB free.
- On 32 GB RAM, use `ACESTEP_DIT_VARIANT=turbo`, `ACESTEP_QUANT=Q8_0`,
  `ACESTEP_LM_SIZE=0.6B`, `ACESTEP_KEEP_LOADED=false`.
- Vulkan build requires `/dev/dri`; use `make up-vulkan`.

### Voice service says OmniVoice unavailable

- The heavy OmniVoice stack may have failed to install; check the build log.
- Piper still works. For a smaller first build set `OMNIVOICE_ENABLED=false`
  and use Piper only.
- Hugging Face downloads need network access on first model load.

### Image generation always uses procedural fallback

- `IMAGEGEN_DEFAULT_PROVIDER=auto` falls back when Diffusers/ComfyUI/QVAC is
  unavailable.
- Check the provider card in the Images page; install Diffusers with
  `IMAGEGEN_INSTALL_DIFFUSERS=1` (default) or point `COMFYUI_URL` at a running
  ComfyUI and set a workflow.
- GPU users should use `make up-gpu`.

### QVAC fails or is extremely slow

- QVAC video requires ~16 GB VRAM / 20 GB unified memory for real models.
- Set `QVAC_DEVICE=gpu` only when the device is actually available.
- Use `QVAC_MOCK=1` to verify the UI and job pipeline without models.
- Model load options are exposed on the QVAC **Models** tab.
- The QVAC image installs `@qvac/sdk` and its native worker packages; the first
  build can take 15+ minutes on a slow connection. Build it separately with
  `docker compose build qvac` if you want to keep the rest of the stack
  available while it compiles.

### Whisper alignment is inaccurate

- Use a clean vocal/instrumental mix and the correct language.
- Prefer `large-v3` or `distil-large-v3`.
- Enable VAD, keep word timestamps on, and make sure lyrics match the audio.
- Edit the cue table and export again.

### FFmpeg job hangs or cannot find a file

- All input paths are relative to `/data/files`. Use the file picker or
  `uploads/<name>`.
- Check the active processes panel and cancel the job; it kills the process group.
- For advanced commands use `raw`; it runs `ffmpeg` only, never a shell.

### Docker build runs out of disk

Heavy images are optional. Build the core first:

```bash
docker compose build gateway jobhub files llm frontend
docker compose up -d gateway jobhub files llm frontend
```

Then add services as space allows. `make clean` removes dangling images/build
cache. QVAC, voice and image generation are the largest images.

### Permissions on `./data`

Containers run as root by default; files are readable by the host user. If your
Docker uses rootless mode, `chown -R $(id -u):$(id -g) data`.

---

## Testing and screenshots

```bash
make test          # Python compile + unit tests + frontend typecheck/build
make verify        # against a running stack (set OPENSTUDIO_PASSWORD)
make screenshots   # demo build + headless Chrome capture
```

Backend tests cover shared path safety, SRT round-trips, password/session/API-key
security and job persistence. The full stack was smoke-tested for auth, files,
jobs, image generation, document pipelines, FFmpeg extraction, music project
creation and video project creation.

All service images were built successfully during validation. The always-on
core (`gateway`, `files`, `jobhub`, `admin`, `frontend`) plus `ffmpeg`, `ytdlp`,
`music`, `docs`, `pdf`, `translation`, `summary` and `srt` were launched and
exercised end-to-end. Checks covered first-run password setup, login cookies,
API keys, authenticated proxying, shared-file upload/download, the global job
queue, the document text pipeline, real OPUS-MT translation, real T5 summaries,
FFmpeg extraction, yt-dlp analysis/download/thumbnail extraction, music
project/song/lyrics/style CRUD and video project creation/asset generation.
The largest model images were then removed from this sandbox to demonstrate the
on-demand policy; enabling a service in Settings builds it again from source.
Use the disk budget under [Requirements](#requirements).

Screenshots are generated from the deterministic demo dataset:

```bash
cd frontend
npm run build:demo
npm run preview
# then capture each route
```

The demo dataset lives in `frontend/src/lib/demo.ts` and uses the generated
artwork in `frontend/public/demo/`.

---

## Repository layout

```
open-studio/
├── docker-compose.yml           # core + profiled on-demand services
├── docker-compose.gpu.yml       # NVIDIA override
├── docker-compose.vulkan.yml    # AMD/Intel Vulkan override
├── Makefile                     # one-command workflows
├── .env.example
├── shared/python/
│   ├── openstudio_common/       # config, storage, jobs, service, SRT, media
│   └── mvstudio_shared/         # video models, planner/storage helpers
├── services/
│   ├── gateway/                 # auth, sessions, keys, status, proxy
│   ├── jobhub/                  # global queues + SSE + SQLite
│   ├── files/                   # shared file explorer API
│   ├── llm/                     # OpenAI-compatible bridge
│   ├── music/                   # music projects/songs/lyrics/takes
│   ├── video*/                  # orchestrator + audio/lyrics/planner/animation/renderer
│   ├── voice/                   # OmniVoice + Piper
│   ├── srt/                     # Whisper + DP lyric alignment
│   ├── imagegen/                # procedural/diffusers/comfyui/qvac
│   ├── docs/ pdf/ translation/ summary/
│   ├── ffmpeg/ ytdlp/ qvac/
│   └── ...
├── engines/acestep-cpp/         # ACE-Step GGUF C++ engine image
├── frontend/                    # Vue 3 + Vite + Pinia + TypeScript
│   ├── src/views/               # one page per studio/tool
│   ├── src/components/          # shared UI (nav, jobs, picker, audio...)
│   ├── src/lib/demo.ts          # screenshot/demo dataset
│   └── public/demo/             # generated demo artwork
├── docs/screenshots/            # README screenshots
├── scripts/                     # health, tests, screenshots, demo assets
├── tests/                       # unit tests
└── data/                        # runtime data (gitignored)
```

---

## Limitations and model licences

- **ACE-Step** model weights have their own upstream licence; review before
  commercial use.
- **OmniVoice** weights are CC-BY-NC per the upstream model card; the app code is
  Apache-2.0. Do not assume commercial rights to the weights.
- **Piper** voices have individual dataset licences (CC0, CC BY-NC-ND, etc.).
- **Whisper**, **OPUS-MT**, **NLLB**, **T5**, **SD/FLUX** and **QVAC** model
  families each carry their own licences and terms.
- QVAC real video generation is hardware-hungry; the mock mode is for demos, not
  production output.
- Live video/AI quality depends on the models you install; procedural fallbacks
  are intentionally deterministic and lightweight.
- This is a single-user studio, not a multi-tenant service. Do not expose it
  directly to the public internet without TLS and network controls.

---

## Credits

Open Studio integrates and unifies these upstream projects and their ecosystems:

- **ACE-Step 1.5** / `acestep.cpp` for music generation.
- **OmniVoice** (k2-fsa) and **Piper** (rhasspy/OHF) for speech.
- **faster-whisper / CTranslate2** for transcription.
- **OPUS-MT**, **NLLB-200**, **T5** via Hugging Face Transformers.
- **Stable Diffusion / FLUX** via Diffusers, **ComfyUI**, and **QVAC** (Tether).
- **FFmpeg**, **libass**, **Librosa**, **OpenCV**, **PyMuPDF**, **Tesseract**.
- **yt-dlp** for media extraction.
- **Ollama** for local LLM inference.
- **Vue 3**, **Vite**, **Pinia**, **Vue Router**, **FastAPI**, **SQLite**, **Docker**.

The unified application, gateway/auth, global job system, shared file layer,
QVAC service, SRT alignment, FFmpeg/yt-dlp APIs and the single-style Vue UI are
original integration work for Open Studio.

---

**Open Studio — your machine, your models, your files, one password.**
