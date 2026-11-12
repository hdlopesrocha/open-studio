"""SQLite persistence for the DJ studio.

Tracks, trained style models, generated tracks and mix scenes live in the
shared state volume so the service can be restarted without losing work.
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from openstudio_common import STATE_ROOT, utc_now

DB_PATH = STATE_ROOT / "dj.db"

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tracks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    artist TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL,
    mime TEXT NOT NULL DEFAULT 'audio/wav',
    size INTEGER NOT NULL DEFAULT 0,
    duration REAL NOT NULL DEFAULT 0,
    bpm REAL NOT NULL DEFAULT 0,
    bpm_confidence REAL NOT NULL DEFAULT 0,
    key TEXT NOT NULL DEFAULT '',
    key_confidence REAL NOT NULL DEFAULT 0,
    camelot TEXT NOT NULL DEFAULT '',
    style TEXT NOT NULL DEFAULT '',
    style_confidence REAL NOT NULL DEFAULT 0,
    mood TEXT NOT NULL DEFAULT '',
    energy REAL NOT NULL DEFAULT 0,
    danceability REAL NOT NULL DEFAULT 0,
    valence REAL NOT NULL DEFAULT 0,
    loudness REAL NOT NULL DEFAULT 0,
    tags TEXT NOT NULL DEFAULT '[]',
    analysis_json TEXT NOT NULL DEFAULT '{}',
    waveform_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'uploaded',
    error TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dj_tracks_created ON tracks(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dj_tracks_style ON tracks(style);

CREATE TABLE IF NOT EXISTS style_models (
    id TEXT PRIMARY KEY,
    style TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    model_json TEXT NOT NULL DEFAULT '{}',
    track_count INTEGER NOT NULL DEFAULT 0,
    bpm REAL NOT NULL DEFAULT 0,
    energy REAL NOT NULL DEFAULT 0,
    key TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generations (
    id TEXT PRIMARY KEY,
    style TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    prompt TEXT NOT NULL DEFAULT '',
    params_json TEXT NOT NULL DEFAULT '{}',
    structure_json TEXT NOT NULL DEFAULT '[]',
    path TEXT NOT NULL DEFAULT '',
    stems_json TEXT NOT NULL DEFAULT '{}',
    duration REAL NOT NULL DEFAULT 0,
    bpm REAL NOT NULL DEFAULT 0,
    key TEXT NOT NULL DEFAULT '',
    seed INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'queued',
    error TEXT NOT NULL DEFAULT '',
    job_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dj_generations_created ON generations(created_at DESC);

CREATE TABLE IF NOT EXISTS mixes (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    prompt TEXT NOT NULL DEFAULT '',
    scene_json TEXT NOT NULL DEFAULT '{}',
    path TEXT NOT NULL DEFAULT '',
    duration REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft',
    error TEXT NOT NULL DEFAULT '',
    job_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dj_mixes_updated ON mixes(updated_at DESC);
"""


def new_id() -> str:
    return uuid.uuid4().hex


class Store:
    def __init__(self, path: Path | str = DB_PATH) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def execute(self, sql: str, args: tuple[Any, ...] = ()) -> int:
        with self._lock:
            cursor = self._conn.execute(sql, args)
            self._conn.commit()
            return cursor.rowcount

    def one(self, sql: str, args: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(sql, args).fetchone()
        return dict(row) if row else None

    def all(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [dict(row) for row in rows]

    # Tracks -----------------------------------------------------------------
    def add_track(self, **fields: Any) -> dict[str, Any]:
        now = utc_now()
        track_id = fields.pop("id", None) or new_id()
        values = {
            "id": track_id,
            "title": fields.get("title") or "Untitled track",
            "artist": fields.get("artist") or "",
            "path": fields.get("path") or "",
            "mime": fields.get("mime") or "audio/wav",
            "size": int(fields.get("size") or 0),
            "duration": float(fields.get("duration") or 0),
            "status": fields.get("status") or "uploaded",
            "notes": fields.get("notes") or "",
            "created_at": now,
            "updated_at": now,
        }
        self.execute(
            """INSERT INTO tracks
            (id, title, artist, path, mime, size, duration, status, notes, created_at, updated_at)
            VALUES (:id, :title, :artist, :path, :mime, :size, :duration, :status, :notes, :created_at, :updated_at)""",
            values,
        )
        return self.track(track_id)  # type: ignore[return-value]

    def track(self, track_id: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM tracks WHERE id=?", (track_id,))

    def tracks(self, query: str = "", style: str = "", limit: int = 300) -> list[dict[str, Any]]:
        where = ["1=1"]
        args: list[Any] = []
        if query:
            where.append("(lower(title) LIKE ? OR lower(artist) LIKE ? OR lower(tags) LIKE ?)")
            needle = f"%{query.lower()}%"
            args.extend([needle, needle, needle])
        if style:
            where.append("style=?")
            args.append(style)
        args.append(limit)
        return self.all(f"SELECT * FROM tracks WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT ?", tuple(args))

    def update_track(self, track_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {
            "title",
            "artist",
            "duration",
            "bpm",
            "bpm_confidence",
            "key",
            "key_confidence",
            "camelot",
            "style",
            "style_confidence",
            "mood",
            "energy",
            "danceability",
            "valence",
            "loudness",
            "tags",
            "analysis_json",
            "waveform_json",
            "status",
            "error",
            "notes",
        }
        updates: list[str] = []
        args: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            updates.append(f"{key}=?")
            args.append(value)
        if not updates:
            return self.track(track_id)
        updates.append("updated_at=?")
        args.append(utc_now())
        args.append(track_id)
        self.execute(f"UPDATE tracks SET {', '.join(updates)} WHERE id=?", tuple(args))
        return self.track(track_id)

    def delete_track(self, track_id: str) -> bool:
        return self.execute("DELETE FROM tracks WHERE id=?", (track_id,)) > 0

    # Style models -----------------------------------------------------------
    def style_model(self, style: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM style_models WHERE style=?", (style,))

    def style_models(self) -> list[dict[str, Any]]:
        return self.all("SELECT * FROM style_models ORDER BY style")

    def save_style_model(self, *, style: str, label: str, model: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        existing = self.style_model(style)
        if existing:
            self.execute(
                """UPDATE style_models SET label=?, model_json=?, track_count=?, bpm=?, energy=?, key=?, updated_at=?
                WHERE style=?""",
                (
                    label,
                    model.get("model_json") or "{}",
                    int(model.get("track_count") or 0),
                    float(model.get("bpm") or 0),
                    float(model.get("energy") or 0),
                    model.get("key") or "",
                    now,
                    style,
                ),
            )
            return self.style_model(style)  # type: ignore[return-value]
        model_id = new_id()
        self.execute(
            """INSERT INTO style_models
            (id, style, label, model_json, track_count, bpm, energy, key, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                model_id,
                style,
                label,
                model.get("model_json") or "{}",
                int(model.get("track_count") or 0),
                float(model.get("bpm") or 0),
                float(model.get("energy") or 0),
                model.get("key") or "",
                now,
                now,
            ),
        )
        return self.style_model(style)  # type: ignore[return-value]

    # Generations ------------------------------------------------------------
    def add_generation(self, **fields: Any) -> dict[str, Any]:
        now = utc_now()
        generation_id = new_id()
        self.execute(
            """INSERT INTO generations
            (id, style, title, prompt, params_json, structure_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                generation_id,
                fields.get("style") or "",
                fields.get("title") or "Untitled generation",
                fields.get("prompt") or "",
                fields.get("params_json") or "{}",
                fields.get("structure_json") or "[]",
                fields.get("status") or "queued",
                now,
                now,
            ),
        )
        return self.generation(generation_id)  # type: ignore[return-value]

    def generation(self, generation_id: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM generations WHERE id=?", (generation_id,))

    def generations(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.all("SELECT * FROM generations ORDER BY created_at DESC LIMIT ?", (limit,))

    def update_generation(self, generation_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {
            "style",
            "title",
            "prompt",
            "params_json",
            "structure_json",
            "path",
            "stems_json",
            "duration",
            "bpm",
            "key",
            "seed",
            "status",
            "error",
            "job_id",
        }
        updates: list[str] = []
        args: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            updates.append(f"{key}=?")
            args.append(value)
        if not updates:
            return self.generation(generation_id)
        updates.append("updated_at=?")
        args.append(utc_now())
        args.append(generation_id)
        self.execute(f"UPDATE generations SET {', '.join(updates)} WHERE id=?", tuple(args))
        return self.generation(generation_id)

    def delete_generation(self, generation_id: str) -> bool:
        return self.execute("DELETE FROM generations WHERE id=?", (generation_id,)) > 0

    # Mixes ------------------------------------------------------------------
    def add_mix(self, *, title: str, prompt: str = "", scene: str = "{}") -> dict[str, Any]:
        now = utc_now()
        mix_id = new_id()
        self.execute(
            """INSERT INTO mixes (id, title, prompt, scene_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'draft', ?, ?)""",
            (mix_id, title or "Untitled mix", prompt, scene, now, now),
        )
        return self.mix(mix_id)  # type: ignore[return-value]

    def mix(self, mix_id: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM mixes WHERE id=?", (mix_id,))

    def mixes(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.all("SELECT * FROM mixes ORDER BY updated_at DESC LIMIT ?", (limit,))

    def update_mix(self, mix_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {"title", "prompt", "scene_json", "path", "duration", "status", "error", "job_id"}
        updates: list[str] = []
        args: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            updates.append(f"{key}=?")
            args.append(value)
        if not updates:
            return self.mix(mix_id)
        updates.append("updated_at=?")
        args.append(utc_now())
        args.append(mix_id)
        self.execute(f"UPDATE mixes SET {', '.join(updates)} WHERE id=?", tuple(args))
        return self.mix(mix_id)

    def delete_mix(self, mix_id: str) -> bool:
        return self.execute("DELETE FROM mixes WHERE id=?", (mix_id,)) > 0


STORE = Store()
