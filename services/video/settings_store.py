"""Persistent AI / provider settings managed by the desktop app."""

from __future__ import annotations

import threading

from mvstudio_shared.config import get_settings
from mvstudio_shared.models import AISettings
from mvstudio_shared.storage import atomic_write_json, read_json


class AISettingsStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.path = self.settings.config_root / "ai_settings.json"
        self._lock = threading.RLock()

    def defaults(self) -> AISettings:
        settings = self.settings
        return AISettings(
            ollama_url=settings.ollama_url,
            ollama_model=settings.ollama_model,
            comfyui_url=settings.comfyui_url,
            image_workflow_path=settings.comfyui_image_workflow,
            video_workflow_path=settings.comfyui_video_workflow,
        )

    def load(self) -> AISettings:
        with self._lock:
            data = read_json(self.path)
            if not data:
                return self.defaults()
            try:
                settings = AISettings.model_validate(data)
            except Exception:
                return self.defaults()
            defaults = self.defaults()
            merged = settings.model_dump()
            for key, value in defaults.model_dump().items():
                if merged.get(key) in ("", None) and value not in ("", None):
                    merged[key] = value
            return AISettings.model_validate(merged)

    def save(self, settings: AISettings) -> AISettings:
        with self._lock:
            self.settings.config_root.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self.path, settings.model_dump(mode="json"))
        return settings
