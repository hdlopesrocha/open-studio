# Initial data

This folder is the seed state for a **new** Open Studio data directory.

`make init` copies `initial_data/.` into `./data/` when `./data` is empty.
After the first initialization, a `data/.initialized` marker prevents the seed
from overwriting your live state on later restarts.

Put files you want available on first boot here:

- `state/` — SQLite databases and service state (for example a prepared
  `auth.db` is generally **not** recommended; create the password in the UI).
- `files/` — shared uploads, generated media, and voice profiles.
- `files/voices/` — trained OmniVoice profiles.
- `files/voices/piper/` — downloaded Piper ONNX voices.
- `models/` — LLM, Whisper, music, translation, summary and image models.
- `home/` — shared service home directory.
- `cache/`, `artifacts/`, `exports/` — optional cache/output seed folders.

The whole `./data` tree is bind-mounted and survives container restarts,
`make down`, and `make up`. Docker images are also reused on restart; use
`make rebuild` only after changing source code.
