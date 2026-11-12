"""Shared configuration helpers for every Open Studio service."""

from __future__ import annotations

import os
from pathlib import Path

SERVICE_NAME = os.getenv("SERVICE_NAME", "openstudio")


def env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return default if value is None else value


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def env_list(name: str, default: list[str] | None = None) -> list[str]:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return list(default or [])
    if raw.strip().startswith("["):
        import json

        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass
    return [part.strip() for part in raw.split(",") if part.strip()]


DATA_ROOT = Path(env("DATA_ROOT", "/data"))
FILES_ROOT = Path(env("FILES_ROOT", str(DATA_ROOT / "files")))
STATE_ROOT = Path(env("STATE_ROOT", str(DATA_ROOT / "state")))
INTERNAL_TOKEN_FILE = STATE_ROOT / "internal.token"
CACHE_ROOT = Path(env("CACHE_ROOT", str(DATA_ROOT / "cache")))
MODELS_ROOT = Path(env("MODELS_ROOT", str(DATA_ROOT / "models")))
ARTIFACT_ROOT = Path(env("ARTIFACT_ROOT", str(DATA_ROOT / "artifacts")))

JOBHUB_URL = env("JOBHUB_URL", "http://jobhub:8000").rstrip("/")
FILES_SERVICE_URL = env("FILES_SERVICE_URL", "http://files:8000").rstrip("/")


def _resolve_internal_token() -> str:
    """Prefer the token in shared state so every container stays in sync.

    Compose can be restarted or an optional service can be started later with a
    different .env value; the shared file is the single source of truth. If it
    does not exist yet, the environment value is written there on startup.
    """
    from_env = env("INTERNAL_TOKEN", "change-me-internal")
    try:
        if INTERNAL_TOKEN_FILE.is_file():
            value = INTERNAL_TOKEN_FILE.read_text("utf-8").strip()
            if value:
                return value
    except OSError:
        pass
    return from_env


INTERNAL_TOKEN = _resolve_internal_token()
SERVICE_TIMEOUT = env_float("SERVICE_TIMEOUT", 900.0)
MAX_UPLOAD_MB = env_int("MAX_UPLOAD_MB", 4096)

# Every service writes user-facing files under one shared tree.
KIND_DIRS = {
    "music": "music",
    "dj": "dj",
    "video": "video",
    "voice": "voice",
    "voices": "voices",
    "documents": "documents",
    "images": "images",
    "subtitles": "subtitles",
    "ffmpeg": "ffmpeg",
    "ytdlp": "ytdlp",
    "qvac": "qvac",
    "uploads": "uploads",
    "tmp": "tmp",
}


def ensure_internal_token() -> None:
    """Persist the token for containers that start after the core."""
    try:
        INTERNAL_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not INTERNAL_TOKEN_FILE.is_file() or not INTERNAL_TOKEN_FILE.read_text("utf-8").strip():
            INTERNAL_TOKEN_FILE.write_text(INTERNAL_TOKEN, encoding="utf-8")
            INTERNAL_TOKEN_FILE.chmod(0o600)
    except OSError:
        pass


def ensure_dirs() -> None:
    for path in (DATA_ROOT, FILES_ROOT, STATE_ROOT, CACHE_ROOT, MODELS_ROOT, ARTIFACT_ROOT, DATA_ROOT / "home"):
        path.mkdir(parents=True, exist_ok=True)
    ensure_internal_token()
    for name in KIND_DIRS.values():
        (FILES_ROOT / name).mkdir(parents=True, exist_ok=True)


def service_url(name: str, default_port: int = 8000) -> str:
    """Resolve an internal service URL, allowing docker-compose overrides."""
    key = name.upper().replace("-", "_") + "_URL"
    return env(key, f"http://{name}:{default_port}").rstrip("/")


def files_path(*parts: str) -> Path:
    """Return a safe path under the shared files root."""
    from .storage import resolve_path

    return resolve_path(*parts)


def jobhub_headers() -> dict[str, str]:
    return {"X-Internal-Token": INTERNAL_TOKEN, "X-Service": SERVICE_NAME}
