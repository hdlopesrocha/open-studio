"""Persistent storage for voice profiles and generated audio.

Layout (all user files live under ``FILES_ROOT``)::

    voices/<voice_id>/meta.json
    voices/<voice_id>/reference.wav
    voices/<voice_id>/prompt.pt
    voices/<voice_id>/preview.wav          (optional)
    voice/outputs/<output_id>/audio.<fmt>
    voice/outputs/<output_id>/meta.json
"""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from openstudio_common import (
    atomic_write_json,
    read_json,
    relative_path,
    remove_path,
    utc_now,
)

VOICE_ID_RE = re.compile(r"^[0-9a-f]{12}$")
OUTPUT_ID_RE = re.compile(r"^[0-9a-f]{12}$")


class VoiceStore:
    """Persistent reusable voice profiles (OmniVoice prompts)."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, voice_id: str) -> Path:
        if not VOICE_ID_RE.match(voice_id or ""):
            raise KeyError("Voice not found")
        return self.root / voice_id

    def create(self) -> tuple[str, Path]:
        self.ensure()
        voice_id = uuid.uuid4().hex[:12]
        path = self.root / voice_id
        path.mkdir(parents=True, exist_ok=False)
        return voice_id, path

    def delete(self, voice_id: str) -> None:
        remove_path(self._dir(voice_id))

    def exists(self, voice_id: str) -> bool:
        try:
            return self._dir(voice_id).is_dir()
        except KeyError:
            return False

    def meta_path(self, voice_id: str) -> Path:
        return self._dir(voice_id) / "meta.json"

    def reference_path(self, voice_id: str) -> Path:
        return self._dir(voice_id) / "reference.wav"

    def prompt_path(self, voice_id: str) -> Path:
        return self._dir(voice_id) / "prompt.pt"

    def preview_path(self, voice_id: str) -> Path:
        return self._dir(voice_id) / "preview.wav"

    def save_meta(self, voice_id: str, meta: dict[str, Any]) -> None:
        atomic_write_json(self.meta_path(voice_id), meta)

    def get_meta(self, voice_id: str) -> dict[str, Any]:
        path = self.meta_path(voice_id)
        if not path.is_file():
            raise KeyError("Voice not found")
        payload = read_json(path, default=None)
        if not isinstance(payload, dict):
            raise KeyError("Voice not found")
        if not payload.get("id"):
            payload["id"] = voice_id
        return payload

    def list_meta(self) -> list[dict[str, Any]]:
        self.ensure()
        voices: list[dict[str, Any]] = []
        for entry in self.root.iterdir():
            if not entry.is_dir() or not VOICE_ID_RE.match(entry.name):
                continue
            meta_file = entry / "meta.json"
            if not meta_file.is_file():
                continue
            payload = read_json(meta_file, default=None)
            if not isinstance(payload, dict):
                continue
            payload.setdefault("id", entry.name)
            voices.append(payload)
        voices.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return voices


class OutputStore:
    """Generated audio history, one directory per output."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, output_id: str) -> Path:
        if not OUTPUT_ID_RE.match(output_id or ""):
            raise KeyError("Output not found")
        return self.root / output_id

    def create_dir(self) -> tuple[str, Path]:
        self.ensure()
        output_id = uuid.uuid4().hex[:12]
        path = self.root / output_id
        path.mkdir(parents=True, exist_ok=False)
        return output_id, path

    def meta_path(self, output_id: str) -> Path:
        return self._dir(output_id) / "meta.json"

    def save_file(
        self,
        source: Path,
        fmt: str,
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        """Move a finished audio file into a fresh output directory."""
        output_id, directory = self.create_dir()
        fmt = (fmt or source.suffix.lstrip(".") or "wav").lower()
        target = directory / f"audio.{fmt}"
        try:
            shutil.move(str(source), target)
            payload = {
                **meta,
                "id": output_id,
                "filename": target.name,
                "audio_path": relative_path(target),
                "format": fmt,
                "size_bytes": target.stat().st_size,
                "created_at": meta.get("created_at") or utc_now(),
            }
            atomic_write_json(directory / "meta.json", payload)
            return payload
        except Exception:
            remove_path(directory)
            raise

    def save_bytes(self, data: bytes, fmt: str, meta: dict[str, Any]) -> dict[str, Any]:
        self.ensure()
        output_id, directory = self.create_dir()
        fmt = (fmt or "wav").lower()
        target = directory / f"audio.{fmt}"
        try:
            target.write_bytes(data)
            payload = {
                **meta,
                "id": output_id,
                "filename": target.name,
                "audio_path": relative_path(target),
                "format": fmt,
                "size_bytes": len(data),
                "created_at": meta.get("created_at") or utc_now(),
            }
            atomic_write_json(directory / "meta.json", payload)
            return payload
        except Exception:
            remove_path(directory)
            raise

    def get_meta(self, output_id: str) -> dict[str, Any]:
        path = self.meta_path(output_id)
        if not path.is_file():
            raise KeyError("Output not found")
        payload = read_json(path, default=None)
        if not isinstance(payload, dict):
            raise KeyError("Output not found")
        if not payload.get("id"):
            payload["id"] = output_id
        return payload

    def audio_path(self, meta: dict[str, Any]) -> Path:
        output_id = str(meta.get("id") or "")
        directory = self._dir(output_id)
        filename = str(meta.get("filename") or "")
        if not filename or "/" in filename or "\\" in filename:
            raise KeyError("Output audio not found")
        path = directory / filename
        if not path.is_file():
            raise KeyError("Output audio not found")
        return path

    def list_meta(
        self,
        limit: int = 50,
        offset: int = 0,
        engine: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        self.ensure()
        outputs: list[dict[str, Any]] = []
        for entry in self.root.iterdir():
            if not entry.is_dir() or not OUTPUT_ID_RE.match(entry.name):
                continue
            meta_file = entry / "meta.json"
            if not meta_file.is_file():
                continue
            payload = read_json(meta_file, default=None)
            if not isinstance(payload, dict):
                continue
            payload.setdefault("id", entry.name)
            if engine and str(payload.get("engine") or "") != engine:
                continue
            try:
                self.audio_path(payload)
            except KeyError:
                continue
            outputs.append(payload)
        outputs.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        total = len(outputs)
        return outputs[offset : offset + limit], total

    def count(self) -> int:
        if not self.root.exists():
            return 0
        return sum(
            1
            for entry in self.root.iterdir()
            if entry.is_dir() and OUTPUT_ID_RE.match(entry.name) and (entry / "meta.json").is_file()
        )

    def delete(self, output_id: str) -> None:
        self.get_meta(output_id)
        remove_path(self._dir(output_id))


def public_voice(meta: dict[str, Any]) -> dict[str, Any]:
    """UI-facing representation of a trained voice profile."""
    voice_id = meta.get("id")
    return {
        "id": voice_id,
        "name": meta.get("name"),
        "language": meta.get("language"),
        "transcript": meta.get("transcript"),
        "description": meta.get("description"),
        "tags": meta.get("tags") or [],
        "duration_seconds": meta.get("duration_seconds", 0),
        "sample_rate": meta.get("sample_rate"),
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
        "has_preview": bool(meta.get("has_preview")),
        "preview_updated_at": meta.get("preview_updated_at"),
        "consent": bool(meta.get("consent")),
        "reference_url": f"/api/voice/voices/{voice_id}/reference" if voice_id else None,
        "preview_url": f"/api/voice/voices/{voice_id}/preview" if voice_id else None,
    }


def public_output(meta: dict[str, Any], *, include_timeline: bool = False) -> dict[str, Any]:
    """UI-facing representation of a generated output."""
    audio_path = meta.get("audio_path") or ""
    timeline = meta.get("timeline") or []
    payload = {
        "id": meta.get("id"),
        "engine": meta.get("engine"),
        "text": meta.get("text"),
        "text_preview": meta.get("text_preview") or (str(meta.get("text") or "")[:180]),
        "mode": meta.get("mode"),
        "voice_id": meta.get("voice_id"),
        "voice_name": meta.get("voice_name"),
        "piper_voice": meta.get("piper_voice"),
        "voice": meta.get("voice") or meta.get("voice_name") or meta.get("piper_voice") or "auto",
        "instruct": meta.get("instruct"),
        "language": meta.get("language"),
        "language_variant": meta.get("language_variant"),
        "format": meta.get("format"),
        "duration_seconds": meta.get("duration_seconds", 0),
        "generation_seconds": meta.get("generation_seconds", 0),
        "rtf": meta.get("rtf"),
        "seed": meta.get("seed"),
        "created_at": meta.get("created_at"),
        "size_bytes": meta.get("size_bytes", 0),
        "path": audio_path,
        "url": f"/api/files/raw/{audio_path}" if audio_path else None,
        "download_url": f"/api/files/download?path={audio_path}" if audio_path else None,
        "timeline_count": len(timeline) if isinstance(timeline, list) else 0,
    }
    if include_timeline:
        payload["timeline"] = timeline
    if meta.get("params"):
        payload["params"] = meta["params"]
    return payload
