"""SQLite persistence for the music studio.

One connection is shared by the service and guarded by a re-entrant lock. The
FastAPI routes and the job hub callbacks run in different threads, so a
``check_same_thread=False`` connection is the simplest reliable option for a
single-process service. WAL keeps reads non-blocking.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from openstudio_common import STATE_ROOT, utc_now


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    artist TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT 'lime',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS songs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    artist TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT 'pt-PT',
    language_label TEXT NOT NULL DEFAULT 'Portuguese (Portugal)',
    genre TEXT NOT NULL DEFAULT 'Pop',
    subgenre TEXT NOT NULL DEFAULT '',
    style TEXT NOT NULL DEFAULT '',
    mood TEXT NOT NULL DEFAULT 'Introspective',
    energy INTEGER NOT NULL DEFAULT 48,
    bpm INTEGER NOT NULL DEFAULT 96,
    duration REAL NOT NULL DEFAULT 150,
    vocal_type TEXT NOT NULL DEFAULT 'female',
    vocal_intensity INTEGER NOT NULL DEFAULT 55,
    singing_style TEXT NOT NULL DEFAULT 'Melodic',
    vocal_emotion TEXT NOT NULL DEFAULT 'Intimate',
    vocal_range TEXT NOT NULL DEFAULT 'Alto',
    vocal_prompt TEXT NOT NULL DEFAULT '',
    pronunciation TEXT NOT NULL DEFAULT '',
    instructions TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT 'ace_step',
    model_id TEXT NOT NULL DEFAULT 'acestep-v15-turbo',
    selected_take_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_songs_project ON songs(project_id);
CREATE INDEX IF NOT EXISTS idx_songs_updated ON songs(updated_at DESC);

CREATE TABLE IF NOT EXISTS lyrics_sections (
    id TEXT PRIMARY KEY,
    song_id TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    type TEXT NOT NULL DEFAULT 'verse',
    label TEXT NOT NULL DEFAULT 'Verse',
    content TEXT NOT NULL DEFAULT '',
    instructions TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lyrics_song ON lyrics_sections(song_id, position);

CREATE TABLE IF NOT EXISTS takes (
    id TEXT PRIMARY KEY,
    song_id TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    job_id TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    path TEXT NOT NULL,
    duration REAL NOT NULL DEFAULT 0,
    seed TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    is_favorite INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_takes_song ON takes(song_id, position);
CREATE INDEX IF NOT EXISTS idx_takes_created ON takes(created_at DESC);

CREATE TABLE IF NOT EXISTS styles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    reference_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


PROJECT_FIELDS = ["title", "description", "artist", "color"]

SONG_FIELDS = [
    "title",
    "artist",
    "language",
    "language_label",
    "genre",
    "subgenre",
    "style",
    "mood",
    "energy",
    "bpm",
    "duration",
    "vocal_type",
    "vocal_intensity",
    "singing_style",
    "vocal_emotion",
    "vocal_range",
    "vocal_prompt",
    "pronunciation",
    "instructions",
    "provider",
    "model_id",
]

SECTION_TYPES = {"intro", "verse", "pre-chorus", "chorus", "bridge", "outro"}


def new_id() -> str:
    return uuid.uuid4().hex


def section_type(value: str, label: str = "") -> str:
    candidate = (value or "").strip().lower()
    if candidate in SECTION_TYPES:
        return candidate
    lowered = (label or "").lower()
    if "pre" in lowered and "chorus" in lowered:
        return "pre-chorus"
    for token in ("intro", "verse", "chorus", "bridge", "outro"):
        if token in lowered:
            return token
    return "verse"


def default_lyrics_sections() -> list[dict[str, Any]]:
    now = utc_now()
    return [
        {
            "id": new_id(),
            "type": "verse",
            "label": "Verse 1",
            "content": "",
            "instructions": "",
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": new_id(),
            "type": "chorus",
            "label": "Chorus",
            "content": "",
            "instructions": "",
            "created_at": now,
            "updated_at": now,
        },
    ]


def normalise_sections(sections: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    now = utc_now()
    normalised: list[dict[str, Any]] = []
    for raw in sections or []:
        label = str(raw.get("label") or "Section").strip()[:120] or "Section"
        kind = section_type(str(raw.get("type") or ""), label)
        normalised.append(
            {
                "id": str(raw.get("id") or new_id()),
                "type": kind,
                "label": label,
                "content": str(raw.get("content") or ""),
                "instructions": str(raw.get("instructions") or ""),
                "created_at": now,
                "updated_at": now,
            }
        )
    return normalised


class MusicDatabase:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA busy_timeout = 30000")
        return self._conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = self._connection()
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        with self.transaction() as connection:
            yield connection

    def initialize(self) -> None:
        with self.transaction() as connection:
            connection.executescript(SCHEMA)

    def fetch_one(self, query: str, params: tuple[Any, ...] | list[Any] = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection().execute(query, tuple(params)).fetchone()
            return dict(row) if row is not None else None

    def fetch_all(self, query: str, params: tuple[Any, ...] | list[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection().execute(query, tuple(params)).fetchall()
            return [dict(row) for row in rows]

    def execute(self, query: str, params: tuple[Any, ...] | list[Any] = ()) -> int:
        with self.transaction() as connection:
            cursor = connection.execute(query, tuple(params))
            return cursor.rowcount

    def executemany(self, query: str, values: list[tuple[Any, ...]]) -> int:
        with self.transaction() as connection:
            cursor = connection.executemany(query, values)
            return cursor.rowcount

    # ------------------------------------------------------------------ lyrics
    def get_lyrics(self, song_id: str) -> list[dict[str, Any]]:
        rows = self.fetch_all(
            "SELECT id, type, label, content, instructions FROM lyrics_sections WHERE song_id = ? ORDER BY position ASC",
            (song_id,),
        )
        return rows

    def lyrics_updated_at(self, song_id: str) -> str | None:
        row = self.fetch_one(
            "SELECT MAX(updated_at) AS updated_at FROM lyrics_sections WHERE song_id = ?",
            (song_id,),
        )
        return (row or {}).get("updated_at")

    def save_lyrics(self, song_id: str, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        now = utc_now()
        normalised = normalise_sections(sections)
        with self.transaction() as connection:
            connection.execute("DELETE FROM lyrics_sections WHERE song_id = ?", (song_id,))
            seen: set[str] = set()
            for position, section in enumerate(normalised):
                section_id = section["id"]
                if section_id in seen or connection.execute(
                    "SELECT 1 FROM lyrics_sections WHERE id = ?", (section_id,)
                ).fetchone():
                    section_id = new_id()
                    section["id"] = section_id
                seen.add(section_id)
                connection.execute(
                    """
                    INSERT INTO lyrics_sections
                    (id, song_id, position, type, label, content, instructions, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        section["id"],
                        song_id,
                        position,
                        section["type"],
                        section["label"],
                        section["content"],
                        section["instructions"],
                        now,
                        now,
                    ),
                )
            connection.execute(
                "UPDATE songs SET updated_at = ? WHERE id = ?",
                (now, song_id),
            )
            row = connection.execute("SELECT project_id FROM songs WHERE id = ?", (song_id,)).fetchone()
            if row is not None:
                connection.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, row["project_id"]))
        return [
            {
                "id": section["id"],
                "type": section["type"],
                "label": section["label"],
                "content": section["content"],
                "instructions": section["instructions"],
            }
            for section in normalised
        ]

    # ------------------------------------------------------------------ takes
    def next_take_position(self, song_id: str) -> int:
        row = self.fetch_one(
            "SELECT COALESCE(MAX(position), -1) + 1 AS next_position FROM takes WHERE song_id = ?",
            (song_id,),
        )
        return int((row or {}).get("next_position") or 0)

    def save_takes(self, song_id: str, takes: list[dict[str, Any]]) -> None:
        if not takes:
            return
        now = utc_now()
        with self.transaction() as connection:
            for take in takes:
                connection.execute(
                    """
                    INSERT INTO takes
                    (id, song_id, job_id, position, path, duration, seed, metadata_json,
                     is_favorite, notes, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        take["id"],
                        song_id,
                        take.get("job_id"),
                        int(take.get("position") or 0),
                        take["path"],
                        float(take.get("duration") or 0),
                        str(take["seed"]) if take.get("seed") is not None else None,
                        json.dumps(take.get("metadata") or {}, ensure_ascii=False),
                        1 if take.get("is_favorite") else 0,
                        str(take.get("notes") or ""),
                        take.get("created_at") or now,
                    ),
                )
            row = connection.execute(
                "SELECT selected_take_id, project_id FROM songs WHERE id = ?", (song_id,)
            ).fetchone()
            if row is not None and not row["selected_take_id"]:
                connection.execute(
                    "UPDATE songs SET selected_take_id = ?, updated_at = ? WHERE id = ?",
                    (takes[0]["id"], now, song_id),
                )
            else:
                connection.execute("UPDATE songs SET updated_at = ? WHERE id = ?", (now, song_id))
            if row is not None:
                connection.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, row["project_id"]))

    def delete_take(self, take_id: str) -> dict[str, Any] | None:
        row = self.fetch_one("SELECT * FROM takes WHERE id = ?", (take_id,))
        if row is None:
            return None
        now = utc_now()
        with self.transaction() as connection:
            song = connection.execute(
                "SELECT selected_take_id, project_id FROM songs WHERE id = ?", (row["song_id"],)
            ).fetchone()
            connection.execute("DELETE FROM takes WHERE id = ?", (take_id,))
            if song is not None and song["selected_take_id"] == take_id:
                replacement = connection.execute(
                    "SELECT id FROM takes WHERE song_id = ? ORDER BY position ASC LIMIT 1",
                    (row["song_id"],),
                ).fetchone()
                connection.execute(
                    "UPDATE songs SET selected_take_id = ?, updated_at = ? WHERE id = ?",
                    (replacement["id"] if replacement else None, now, row["song_id"]),
                )
            elif song is not None:
                connection.execute(
                    "UPDATE songs SET updated_at = ? WHERE id = ?", (now, row["song_id"])
                )
            if song is not None:
                connection.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, song["project_id"]))
        return row


db = MusicDatabase(STATE_ROOT / "music.db")
