# DJ Studio

On-demand crate-digging, style training and mix-rendering service.

## Capabilities

- Upload WAV/MP3/FLAC/M4A/OGG/OPUS into the shared files tree.
- Analyse tempo, beat grid, key/Camelot, style, mood, energy, danceability,
  valence, spectral balance, percussiveness, waveform and section roles.
- Train a compact style model per style from analysed records. The model stores
  tempo distribution, key probabilities, spectral profile, swing, energy arc
  and mood.
- Plan an editable arrangement locally or through the optional local `llm`
  service (`DJ_LLM_URL`).
- Render multi-stem tracks procedurally from the model and arrangement.
- Plan beat-matched mix scenes from whole tracks or from multiple detected
  sections per track, with in/out points, transitions and effect racks.
- Render mix scenes with equal-power crossfades, filter sweeps, bass swaps,
  echo-outs, cuts, reverb, delay, drive, bitcrush, chorus, gates, stutters and
  tape stops.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/dj/overview` | Counts, style models, presets and recent work |
| GET/POST | `/api/dj/tracks` | List tracks / multipart upload |
| PATCH/DELETE | `/api/dj/tracks/{id}` | Edit metadata / remove a track |
| POST | `/api/dj/tracks/{id}/analyze` | Queue analysis |
| GET | `/api/dj/styles` | Built-in and trained style models |
| POST | `/api/dj/styles/{style}/train` | Train a style model |
| POST | `/api/dj/structure` | AI/local arrangement plan |
| GET/POST | `/api/dj/generations` | List/create generated tracks |
| GET/POST/DELETE | `/api/dj/mixes` | Mix scene CRUD |
| POST | `/api/dj/mixes/{id}/scene` | AI mix-scene plan |
| POST | `/api/dj/mixes/{id}/render` | Queue mix render |
| GET | `/api/dj/effects/presets` | Effect and emotion presets |

All long operations are normal job-hub jobs on the `dj` queue.

## Storage

- Metadata: `$STATE_ROOT/dj.db`
- Source tracks: `$FILES_ROOT/dj/tracks/<id>/`
- Generated stems: `$FILES_ROOT/dj/generated/<id>/`
- Mix renders: `$FILES_ROOT/dj/mixes/<id>/`

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `DJ_MAX_UPLOAD_MB` | `512` | Upload limit per file |
| `DJ_LLM_URL` | `http://llm:8000` | Optional LLM bridge for planning |
| `DJ_CONCURRENCY` | `1` | Job-hub concurrency for generation/mix jobs |
