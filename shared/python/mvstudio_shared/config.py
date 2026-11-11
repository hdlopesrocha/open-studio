"""Runtime configuration for the Open Studio video component.

All paths are overridable with environment variables so the same code works in
Docker (shared ``/data`` volumes) and in a local developer checkout. Defaults
match the Open Studio deployment layout:

- projects: ``/data/files/video/projects``
- exports:  ``/data/files/video/exports``
- cache:    ``/data/cache/video``
- models:   ``/data/models``
- config:   ``/data/state/video``
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _env_path(name: str, default: Path | str) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser().resolve() if value else Path(default).expanduser().resolve()


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


# Logical service names used by the video orchestrator. The concrete container
# names differ from the original standalone app so several services can share a
# Docker network.
DEFAULT_SERVICE_URLS = {
    "audio": "http://video-audio:8000",
    "lyrics": "http://video-lyrics:8000",
    "planner": "http://video-planner:8000",
    "images": "http://imagegen:8000/internal/video",
    "animation": "http://video-animation:8000",
    "renderer": "http://video-renderer:8000",
}

# Older name used by the reference project. Kept only for URL resolution.
SERVICE_PORTS = {
    "gateway": 8000,
    "audio": 8000,
    "lyrics": 8000,
    "planner": 8000,
    "images": 8000,
    "animation": 8000,
    "renderer": 8000,
}


@dataclass(frozen=True)
class Settings:
    projects_root: Path
    exports_root: Path
    cache_root: Path
    models_root: Path
    config_root: Path
    data_root: Path
    files_root: Path
    local_services: bool
    gateway_url: str
    service_urls: dict[str, str]
    allowed_output_roots: tuple[Path, ...]
    ffmpeg: str
    ffprobe: str
    ollama_url: str
    ollama_model: str
    comfyui_url: str
    comfyui_image_workflow: str
    comfyui_video_workflow: str
    max_concurrent_jobs: int
    max_upload_mb: int
    allow_external_output: bool
    request_retries: int
    service_timeout_seconds: float
    log_level: str
    cors_origins: tuple[str, ...]

    def service_url(self, name: str) -> str:
        if name in self.service_urls:
            return self.service_urls[name]
        return DEFAULT_SERVICE_URLS.get(name, f"http://{name}:8000")

    @property
    def jobs_root(self) -> Path:
        return self.projects_root


def _service_url(name: str) -> str:
    upper = name.upper().replace("-", "_")
    aliases = {
        "audio": (
            "VIDEO_AUDIO_URL",
            "VIDEO_AUDIO_SERVICE_URL",
            "AUDIO_URL",
            "AUDIO_SERVICE_URL",
        ),
        "lyrics": (
            "VIDEO_LYRICS_URL",
            "VIDEO_LYRICS_SERVICE_URL",
            "LYRICS_URL",
            "LYRICS_SERVICE_URL",
        ),
        "planner": (
            "VIDEO_PLANNER_URL",
            "VIDEO_PLANNER_SERVICE_URL",
            "PLANNER_URL",
            "PLANNER_SERVICE_URL",
        ),
        "images": (
            "IMAGES_SERVICE_URL",
            "IMAGE_SERVICE_URL",
            "IMAGEGEN_URL",
            "IMAGE_GEN_URL",
        ),
        "animation": (
            "VIDEO_ANIMATION_URL",
            "VIDEO_ANIMATION_SERVICE_URL",
            "ANIMATION_URL",
            "ANIMATION_SERVICE_URL",
        ),
        "renderer": (
            "VIDEO_RENDERER_URL",
            "VIDEO_RENDERER_SERVICE_URL",
            "RENDERER_URL",
            "RENDERER_SERVICE_URL",
        ),
    }.get(name, (f"{upper}_URL", f"{upper}_SERVICE_URL"))
    for key in aliases:
        value = os.environ.get(key, "").strip()
        if value:
            return value.rstrip("/")
    return DEFAULT_SERVICE_URLS.get(name, f"http://{name}:8000").rstrip("/")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    data_root = _env_path("DATA_ROOT", os.environ.get("MVSTUDIO_DATA_ROOT", "/data"))
    files_root = _env_path("FILES_ROOT", data_root / "files")
    projects_root = _env_path("PROJECTS_ROOT", files_root / "video" / "projects")
    exports_root = _env_path("EXPORTS_ROOT", files_root / "video" / "exports")
    cache_root = _env_path("CACHE_ROOT", "/data/cache/video")
    models_root = _env_path("MODELS_ROOT", "/data/models")
    config_root = _env_path("CONFIG_ROOT", "/data/state/video")

    service_urls = {name: _service_url(name) for name in DEFAULT_SERVICE_URLS}

    output_roots_raw = os.environ.get("MVSTUDIO_ALLOWED_OUTPUT_ROOTS", "").strip()
    allowed_output_roots = tuple(
        Path(item).expanduser().resolve()
        for item in output_roots_raw.split(":")
        if item.strip()
    )
    if not allowed_output_roots:
        allowed_output_roots = (projects_root, exports_root)

    return Settings(
        projects_root=projects_root,
        exports_root=exports_root,
        cache_root=cache_root,
        models_root=models_root,
        config_root=config_root,
        data_root=data_root,
        files_root=files_root,
        local_services=_env_bool("MVSTUDIO_LOCAL_SERVICES", False),
        gateway_url=os.environ.get("MVSTUDIO_GATEWAY_URL", "http://gateway:8000").rstrip("/"),
        service_urls=service_urls,
        allowed_output_roots=allowed_output_roots,
        ffmpeg=os.environ.get("FFMPEG_BIN", "ffmpeg"),
        ffprobe=os.environ.get("FFPROBE_BIN", "ffprobe"),
        ollama_url=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
        ollama_model=os.environ.get("OLLAMA_MODEL", "llama3.2"),
        comfyui_url=os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/"),
        comfyui_image_workflow=os.environ.get("COMFYUI_IMAGE_WORKFLOW", ""),
        comfyui_video_workflow=os.environ.get("COMFYUI_VIDEO_WORKFLOW", ""),
        max_concurrent_jobs=max(1, _env_int("VIDEO_MAX_CONCURRENT_JOBS", _env_int("MVSTUDIO_MAX_CONCURRENT_JOBS", 2))),
        max_upload_mb=_env_int("MAX_UPLOAD_MB", _env_int("MVSTUDIO_MAX_UPLOAD_MB", 4096)),
        allow_external_output=_env_bool("ALLOW_EXTERNAL_OUTPUT", _env_bool("MVSTUDIO_ALLOW_EXTERNAL_OUTPUT", True)),
        request_retries=_env_int("MVSTUDIO_REQUEST_RETRIES", 3),
        service_timeout_seconds=_env_float("MVSTUDIO_SERVICE_TIMEOUT", 900.0),
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        cors_origins=tuple(
            item.strip()
            for item in os.environ.get(
                "MVSTUDIO_CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173,tauri://localhost,http://tauri.localhost,https://tauri.localhost,null",
            ).split(",")
            if item.strip()
        ),
    )


def reset_settings_cache() -> None:
    """Used by tests after changing environment variables."""
    get_settings.cache_clear()
