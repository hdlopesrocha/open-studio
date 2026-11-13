# Open Studio service contracts

This file is the integration contract between the Vue app, the gateway, the job
hub and every component service. Do not change a public response shape without
updating this file and the frontend.

## Shared rules

- All user files live under `/data/files` (`FILES_ROOT`). Return paths relative
  to that root (for example `music/demo/song/take.wav`). The frontend shows them
  through `/api/files/raw/<path>` and downloads through `/api/files/download?path=`.
- State (SQLite DBs, auth, job DB) lives under `/data/state`.
- Models live under `/data/models`.
- Every service is a FastAPI app created with
  `openstudio_common.create_service_app(...)`, so it has `GET /health`.
- The public gateway exposes every service at `/api/<service>/<path>` and adds
  `X-Internal-Token`. Services must call each other with the same header
  (`openstudio_common.jobhub_headers()` / `INTERNAL_TOKEN`).
- Long work is submitted to the job hub. `POST /api/jobs` with:
  ```json
  {"component":"music","action":"generate","title":"...","params":{...}}
  ```
  The hub dispatches `POST <service>/internal/jobs/run` with
  `{"job_id","action","params"}`. Use `JobRunner` from `openstudio_common` to
  register handlers and `JobContext.report(progress, stage, message)` to stream
  progress. Cancellation arrives at `/internal/jobs/{job_id}/cancel` and is
  checked with `ctx.check()`.
- Job result shape:
  ```json
  {"message":"...","files":[{"path":"...","kind":"audio","mime":"audio/wav","name":"...","size":123}],"data":{}}
  ```
  Files are optional. Keep all extra data JSON serializable.
- Errors: FastAPI `{"detail":"..."}`; 400/404/409/413/422/429/500/503.
- Every list endpoint returns `{"items":[...], "total": n}` where sensible.
- Timestamps are ISO-8601 UTC strings.
- File pickers in the frontend use `GET /api/files/list?path=&kind=audio|video|image|subtitle|document`.
- Uploads use `POST /api/files/upload` (multipart `file`, `path`) and then pass
  the returned relative path into a service.

## Gateway / auth (already implemented)

- `GET /api/auth/status`, `POST /api/auth/setup`, `POST /api/auth/login`,
  `POST /api/auth/logout`, `GET /api/auth/me`, `POST /api/auth/change-password`,
  sessions and API keys.
- `GET /api/status`, `GET /api/system/info`.
- Transparent proxy `/api/<service>/...`.
- First run requires setting a password; the app is unusable until then.

## Job hub (already implemented)

- `GET/POST /api/jobs`, `GET /api/jobs/{id}`, cancel, retry, delete.
- `GET /api/jobs/queues`, `GET /api/jobs/events` (SSE), `GET /api/jobs/{id}/events`.
- Components: `music`, `video`, `voice`, `srt`, `imagegen`, `translation`,
  `summary`, `pdf`, `docs`, `ffmpeg`, `ytdlp`, `qvac`, `llm`.
- Per-component concurrency is configurable (`MUSIC_CONCURRENCY`, etc.);
  components run in parallel with each other.

## Music — `/api/music`

REST resources plus job actions.

- `GET /catalog` → `{engines, models, languages, defaults, options, capabilities}`.
  Each model exposes all ACE-Step controls: text-to-music, repaint, cover,
  extend, variations, seed, steps, guidance, thinking, prompt expansion,
  reference audio, source audio, BPM, duration, vocal language.
- `GET /system` → engine health, installed GGUF files, resources.
- `GET/POST /styles`, `DELETE /styles/{id}` → named style reference profiles. `POST /songs/{id}/generate` accepts `style_id`; the service uses the profile reference audio + prompt guidance.
- Projects CRUD: `GET/POST /projects`, `GET/PATCH/DELETE /projects/{id}`.
- Songs CRUD: `GET/POST /songs`, `GET/PATCH/DELETE /songs/{id}`, `POST /songs/{id}/duplicate`.
- `GET/PUT /songs/{id}/lyrics` → `{sections:[{id,type,label,content,instructions}]}`.
- `POST /songs/{id}/generate` → job hub job. Params:
  `provider, model_id, mode(full|repaint|cover|extend), variations, seed,
  inference_steps, guidance_scale, thinking, use_format, enhance_prompt,
  instruction, duration, bpm, source_path, reference_path, start_seconds,
  end_seconds, cover_strength, infer_method(ode|sde), audio_format,
  lm_batch_size, synth_batch_size`.
- `POST /lyrics/draft` → job (params: song_id, title, theme, direction, genre,
  mood, energy, language, vocal_type, structure).
- `GET /songs/{id}/takes`, `PATCH /takes/{id}` (favorite/notes),
  `POST /songs/{id}/select-take`, `DELETE /takes/{id}`.
- `POST /export` → job (audio format or zip).
- Job actions: `generate`, `lyrics_draft`, `export`.
- Files: `music/<project_id>/<song_id>/...`.
- DB: `/data/state/music.db`.

## Video — `/api/video`

Orchestrates video-audio, video-lyrics, video-planner, video-animation,
video-renderer and the shared imagegen service.

- `GET /catalog` → styles, camera moves, effects, transitions, output sizes,
  codecs, animation backends, image providers, defaults.
- `GET/POST /projects`, `GET/PATCH/DELETE /projects/{id}`.
  JSON create: `{name,title,artist,audio_path,srt_path,config}` where paths are
  files-relative. Copy input into `video/projects/<id>/input/`.
- `GET /projects/{id}/analysis/audio|lyrics|events`, `GET /projects/{id}/plan`,
  `GET /projects/{id}/scenes`.
- `PUT /projects/{id}/scenes/{scene_id}`, `POST .../scenes/reorder`,
  `POST .../scenes/{scene_id}/image`, `.../depth-map`, `.../select-image`.
- `GET /projects/{id}/assets` → list of files-relative assets.
- `POST /projects/{id}/run` `{action,options}` → job hub job. Actions:
  `analyze`, `plan`, `images`, `animate`, `render`, `full`, `regenerate`.
- Job actions: `analyze`, `plan`, `images`, `animate`, `render`, `full`,
  `regenerate`.
- Scene config exposes prompt, negative prompt, camera move, transition,
  duration, effects, image provider/variants, depth map, audio-reactive
  beat/bass pulses and particles, output resolution/fps/codec/subtitle style.
- Files: `video/projects/<id>/...`.

## Voice — `/api/voice`

One TTS service with two engines: `omnivoice` (cloning/design/auto, Whisper ASR)
and `piper` (fast built-in voices). All TTS runs in Docker.

- `GET /catalog` → engines, voices, languages, modes, formats, limits,
  advanced defaults, all advanced controls.
- `GET /voices`, `GET/POST /voices` (multipart train), `PATCH/DELETE
  /voices/{id}`, `GET /voices/{id}/reference|preview`, `POST
  /voices/{id}/preview`, retrain, export/import, `POST /transcribe`.
- `GET /piper/voices` → built-in Piper catalog and availability.
- `POST /tts` → job hub job (synchronous is not required). Full params:
  `engine, mode(auto|voice|design), voice_id, piper_voice, text, instruct,
  language, language_variant, speed, num_step, guidance_scale, t_shift,
  denoise, preprocess_prompt, postprocess_output, seed, format,
  normalize_text, pitch, normalize_audio`.
- `POST /batch` → job (items/split mode).
- `POST /train`, `POST /preview`, `POST /transcribe` → jobs.
- `GET /outputs`, `GET /outputs/{id}`, delete.
- OpenAI-compatible `POST /v1/audio/speech`, `GET /v1/models`, `GET /v1/voices`.
- Internal sync endpoint `POST /internal/tts` for the documents pipeline:
  returns `{path, duration_seconds, timeline:[{index,text,start,end}], format}`.
- Job actions: `tts`, `batch`, `train`, `preview`, `transcribe`.
- Files: `voice/outputs/<id>/...`, `voices/<id>/...` (profiles live in the shared `voices/` folder).

## Subtitles (AI SRT) — `/api/srt`

Whisper transcription plus lyric alignment.

- `GET /catalog` → Whisper models, languages, defaults, translation link.
- `POST /transcribe` (job) params: `audio_path, model, language, task,
  beam_size, vad_filter, word_timestamps, temperature, initial_prompt,
  condition_on_previous_text, no_speech_threshold, output_format(srt|vtt|ass),
  translate_to`.
- `POST /align` (job) params: `audio_path, lyrics, model, language, ...` —
  aligns provided lyric lines to the audio and writes SRT/VTT/ASS.
- `POST /from-text` (job) — estimate timings from plain text + duration.
- `POST /convert` — SRT ↔ VTT ↔ ASS without a model.
- Job actions: `transcribe`, `align`, `from_text`.
- Files: `subtitles/<job>/...`.

## Images — `/api/images`

- `GET /providers` → procedural, diffusers, comfyui, qvac + availability/models.
- `GET /models` → model catalog with all parameters.
- `POST /generate` (job) params: `provider, model, prompt, negative_prompt,
  width, height, steps, guidance, cfg_scale, seed, batch_count, sampler,
  scheduler, init_image, strength, lora, upscale, output_format`.
- `POST /upscale` (job).
- `GET /gallery` → recent generated images from shared storage.
- Video compatibility: `POST /internal/video/provider-status` and
  `POST /internal/video/generate` matching MVS `GenerateImageRequest`.
- Job actions: `generate`, `upscale`.
- Files: `images/...`.

## Translation — `/api/translate`

- `GET /status`, `GET /languages`, `GET /models`.
- `POST /translate` (sync) and `POST /translate/job` (job).
  Params: `text` or `segments`, `source_language`, `target_language`, `model`,
  `num_beams`, `max_length`, `temperature`, `length_penalty`,
  `repetition_penalty`, `no_repeat_ngram_size`, `batch_size`,
  `preserve_markup`, `glossary`.
- `POST /detect`.
- Job action: `translate`.
- Outputs: `documents/translation/...` (text artifacts).

## Summary — `/api/summary`

- `GET /status`, `GET /lengths`, `GET /languages`, `GET /models`.
- `POST /summarize` (sync), `POST /summarize/job` (job): `text`, `length`,
  `language`, `source_language`, `model`, `max_tokens`, `min_tokens`,
  `num_beams`, `temperature`, `chunk_tokens`, `hierarchical`.
- Job action: `summarize`.
- Outputs: `documents/summary/...`.

## PDF — `/api/pdf`

- `GET /status`, `GET /ocr-languages`, `GET /languages`.
- `POST /inspect` `{path}`.
- `POST /extract` `{path,start_page,end_page,selected_pages,ocr_enabled,ocr_language}`.
- `POST /extract/job` → job.
- `GET /preview?path=&page=&width=` → PNG.
- `POST /upload` multipart → store under `uploads/pdf/...`.
- Job action: `extract`.
- Files: `documents/pdf/...`.

## Documents — `/api/docs`

PDF/text → translate → summarize → TTS → SRT/VTT → ZIP.

- `GET /capabilities` → inputs, translation/summary/TTS options, formats.
- `POST /run` → job (params: `input{type,pdf_path|text,pages,ocr,...}`,
  `translation{enabled,source,target,...}`, `summary{...}`, `tts{...}`,
  `subtitles{enabled,format}`, `zip{enabled}`).
- `GET /jobs/{job_id}/text/{kind}` / `PATCH` for editable extracted,
  translation and summary text.
- Job action: `pipeline`.
- Files: `documents/<job_id>/...`.

## FFmpeg — `/api/ffmpeg`

- `GET /catalog` → operations, codecs, formats, filters.
- `POST /probe` → metadata.
- `POST /run` → job for named operations: `transcode`, `extract_audio`,
  `trim`, `crop_video`, `crop_image`, `scale`, `rotate`, `concat`, `overlay`,
  `subtitles`, `frames`, `gif`, `merge`, `replace_audio`, `speed`, `volume`,
  `normalize`, `thumbnail`, `raw`.
- Every operation accepts `input_path` / `output_path` (files-relative) and all
  relevant options. `raw` accepts an argv list, validated as a list of strings.
- Sync `POST /probe`, `POST /run-sync` allowed for short operations.
- Job actions mirror the operation names.
- Files: `ffmpeg/<job>/...`.

## yt-dlp — `/api/ytdlp`

- `GET /catalog` → formats, postprocessors, defaults, version.
- `POST /info` `{url,cookies_path,proxy,extractor_args}` → metadata + formats.
- `POST /search` `{query,limit}`.
- `POST /playlist` `{url,...}`.
- `POST /download` (job): `url,format,format_sort,merge_output_format,
  output_template,subtitles,subtitle_langs,embed_subs,embed_thumbnail,
  write_thumbnail,write_info_json,write_description,write_comments,
  extract_audio,audio_format,audio_quality,playlist,playlist_items,
  match_filter,dateafter,datebefore,max_downloads,rate_limit,retries,
  fragment_retries,concurrent_fragments,proxy,cookies_path,cookies_from_browser,
  sponsorblock,sponsorblock_remove,archive_path,keep_video,no_check_certificate,
  geo_bypass,user_agent,referer,headers,output_path`.
- `POST /download/job` → job action `download`.
- Files: `ytdlp/<job>/...`; `thumbnail_path` is a files-relative cached/extracted thumbnail (usually JPG).

## QVAC — `/api/qvac` (Node service)

- `GET /catalog` → model families/constants, install status, device and memory info, modes.
- `GET /status` → SDK version, loaded model, GPU/unified memory.
- `POST /models/install` `{family}` → download and verify every asset in a QVAC model pack.
- `POST /models/load`, `POST /models/unload`, `GET /models/loaded`.
- `POST /video` (job): all QVAC video params (txt2vid/img2vid, prompt,
  negative_prompt, init_image, width, height, video_frames, fps, steps,
  cfg_scale, flow_shift, seed, scheduler, strength, reference_images, lora,
  lora_strength, reference_attention_strength, reference_downscale_factor,
  temporal_tiling, vae_tile_size, high_noise_*).
- `POST /image` (job): all QVAC diffusion params (prompt, negative_prompt,
  init_image, init_images, width, height, steps, guidance, cfg_scale, seed,
  batch_count, sampling_method, upscale).
- `POST /upscale` (job).
- Job actions: `video`, `image`, `upscale`.
- Files: `qvac/...`.

## Service manager — `/api/admin`

- `GET /models` → static model packs plus live QVAC family packs; QVAC installation is handled through the standard model job.
- `GET /services` → all core + optional services with `enabled`, `running`, `health`, `image_built`, `requires`.
- `POST /services/{name}/enable|disable|build|restart` → central job (`component:"admin"`).
  Enable builds only when the image is missing; disable stops and removes the container.
- `GET /services/{name}/logs?lines=200` → recent compose logs.
- `POST /files/delete-all` `{confirm:"DELETE"}` → clear the shared files tree.

## LLM — `/api/llm`

- `GET /health`, `GET /models`, `POST /chat`, `POST /complete`,
  `POST /embeddings`. OpenAI-compatible, streams when `stream=true`.
