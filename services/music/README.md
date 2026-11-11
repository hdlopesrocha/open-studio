# Music service

FastAPI service for the ACE-Step 1.5 songwriting studio. It owns projects,
songs, structured lyrics, takes, generation/export jobs and the shared SQLite
database at `STATE_ROOT/music.db`.

## Runtime

| Variable | Default | Purpose |
| --- | --- | --- |
| `ACESTEP_ENGINE_URL` | `http://music-engine:8085` | GGUF/C++ engine base URL |
| `ACESTEP_MODELS_DIR` | `MODELS_ROOT/acestep` | GGUF directory shown in `/system` |
| `ACESTEP_DEFAULT_MODEL` | `acestep-v15-turbo` | default model id |
| `ACESTEP_POLL_SECONDS` | `3` | engine job polling interval |
| `ACESTEP_JOB_TIMEOUT_SECONDS` | `21600` | engine job timeout |
| `LLM_URL` | `http://llm:8000` | shared LLM service |
| `LLM_TIMEOUT_SECONDS` | `300` | lyricist timeout |
| `JOBHUB_URL` | `http://jobhub:8000` | central job hub |
| `STATE_ROOT` | `/data/state` | SQLite state root |
| `FILES_ROOT` | `/data/files` | shared output files root |

Generated audio lives under
`FILES_ROOT/music/<project_id>/<song_id>/takes/`; exports live under
`.../exports/`. Files are addressed by paths relative to `FILES_ROOT`.

## Endpoints

All routes are under `/api/music`:

- `GET /catalog`, `GET /system`
- projects: `GET/POST /projects`, `GET/PATCH/DELETE /projects/{id}`
- songs: `GET/POST /songs`, `GET/PATCH/DELETE /songs/{id}`,
  `POST /songs/{id}/duplicate`
- lyrics: `GET/PUT /songs/{id}/lyrics`, `POST /lyrics/draft`
- generation: `POST /songs/{id}/generate`
- takes: `GET /songs/{id}/takes`, `PATCH/DELETE /takes/{id}`,
  `POST /songs/{id}/select-take`
- export: `POST /export`

Generation, lyric drafting and export submit jobs to `JOBHUB_URL` with
`component=music`. The hub dispatches them back to
`POST /internal/jobs/run` with actions `generate`, `lyrics_draft` and
`export`.
