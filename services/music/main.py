"""Open Studio music service.

ACE-Step 1.5 songwriting studio: projects, songs, structured lyrics, generation
through the central job hub, takes and exports.
"""

from __future__ import annotations

import logging
import os
import shutil
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import ValidationError

from openstudio_common import (
    FILES_ROOT,
    JOBHUB_URL,
    STATE_ROOT,
    create_service_app,
    jobhub_headers,
    remove_path,
    resolve_path,
    utc_now,
)

from . import lyrics
from .catalog import DEFAULT_MODEL, catalog_payload, engine_descriptor, known_model_descriptors
from .db import (
    PROJECT_FIELDS,
    SONG_FIELDS,
    db,
    default_lyrics_sections,
    new_id,
)
from .engine import engine
from .jobs import prepare_generation, runner, serialize_take
from .schemas import (
    ExportRequest,
    GenerateRequest,
    GenerationJobParams,
    LyricsDraftRequest,
    LyricsUpdate,
    ProjectCreate,
    ProjectUpdate,
    SongCreate,
    SongUpdate,
    TakeUpdate,
)

log = logging.getLogger("music")

router = APIRouter(prefix="/api/music", tags=["music"])


# --------------------------------------------------------------------------- helpers
def _validation_http(exc: ValidationError) -> HTTPException:
    errors = exc.errors()
    detail = errors[0].get("msg") if errors else "Invalid request."
    return HTTPException(status_code=422, detail=str(detail))


async def submit_job(action: str, title: str, params: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "component": "music",
        "action": action,
        "title": (title or "Music job")[:200],
        "params": params,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=jobhub_headers()) as client:
            response = await client.post(f"{JOBHUB_URL}/api/jobs", json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="The central job hub is not reachable. Check that the jobhub service is running.",
        ) from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail") or response.text
        except ValueError:
            detail = response.text or f"HTTP {response.status_code}"
        status = 503 if response.status_code >= 500 else response.status_code
        raise HTTPException(status_code=status, detail=str(detail)[:1000])
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="The job hub returned an invalid response.") from exc


PROJECT_SELECT = """
SELECT p.*,
    (SELECT COUNT(*) FROM songs s WHERE s.project_id = p.id) AS song_count,
    (
        SELECT COUNT(*) FROM takes t
        JOIN songs s ON s.id = t.song_id
        WHERE s.project_id = p.id
    ) AS take_count,
    (
        SELECT MAX(x.updated_at) FROM (
            SELECT MAX(s.updated_at) AS updated_at FROM songs s WHERE s.project_id = p.id
            UNION ALL
            SELECT MAX(t.created_at) AS updated_at FROM takes t
            JOIN songs s ON s.id = t.song_id WHERE s.project_id = p.id
        ) x
    ) AS last_activity
FROM projects p
"""


def serialize_project(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["song_count"] = int(item.get("song_count") or 0)
    item["take_count"] = int(item.get("take_count") or 0)
    item["last_activity"] = item.get("last_activity") or item.get("updated_at")
    return item


def project_stats(project_id: str) -> dict[str, Any] | None:
    row = db.fetch_one(f"{PROJECT_SELECT} WHERE p.id = ?", (project_id,))
    return serialize_project(row) if row else None


def song_list_item(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["take_count"] = int(item.get("take_count") or 0)
    item["active_generations"] = int(item.get("active_generations") or 0)
    return item


def require_project(project_id: str) -> dict[str, Any]:
    project = db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def require_song(song_id: str) -> dict[str, Any]:
    song = db.fetch_one("SELECT * FROM songs WHERE id = ?", (song_id,))
    if song is None:
        raise HTTPException(status_code=404, detail="Song not found")
    return song


def song_payload(song_id: str) -> dict[str, Any]:
    song = require_song(song_id)
    lyrics_sections = db.get_lyrics(song_id)
    project = db.fetch_one("SELECT id, title, artist, color FROM projects WHERE id = ?", (song["project_id"],))
    take_count = db.fetch_one("SELECT COUNT(*) AS count FROM takes WHERE song_id = ?", (song_id,))
    selected = None
    if song.get("selected_take_id"):
        row = db.fetch_one("SELECT * FROM takes WHERE id = ?", (song["selected_take_id"],))
        selected = serialize_take(row) if row else None
    data = dict(song)
    data["lyrics"] = {
        "sections": lyrics_sections,
        "updated_at": db.lyrics_updated_at(song_id),
    }
    data["project"] = project
    data["take_count"] = int((take_count or {}).get("count") or 0)
    data["active_generations"] = 0
    data["selected_take"] = selected
    return data


def _project_songs(project_id: str) -> list[dict[str, Any]]:
    rows = db.fetch_all(
        """
        SELECT s.*, p.title AS project_title, p.color AS project_color,
            (SELECT COUNT(*) FROM takes t WHERE t.song_id = s.id) AS take_count
        FROM songs s
        JOIN projects p ON p.id = s.project_id
        WHERE s.project_id = ?
        ORDER BY s.updated_at DESC
        """,
        (project_id,),
    )
    return [song_list_item(row) for row in rows]


def _insert_song(project: dict[str, Any], payload: SongCreate) -> dict[str, Any]:
    now = utc_now()
    song_id = new_id()
    values = payload.model_dump()
    title = str(values.get("title") or "Untitled song").strip()[:200] or "Untitled song"
    artist = str(values.get("artist") or "").strip() or str(project.get("artist") or "")
    columns = ["id", "project_id", *SONG_FIELDS, "selected_take_id", "created_at", "updated_at"]
    placeholders = ", ".join("?" for _ in columns)
    params: list[Any] = [song_id, project["id"]]
    for field in SONG_FIELDS:
        if field == "title":
            params.append(title)
        elif field == "artist":
            params.append(artist)
        else:
            params.append(values.get(field))
    params.extend([None, now, now])
    db.execute(f"INSERT INTO songs ({', '.join(columns)}) VALUES ({placeholders})", tuple(params))
    db.save_lyrics(song_id, default_lyrics_sections())
    return require_song(song_id)


def _delete_song_files(project_id: str, song_id: str) -> None:
    try:
        target = resolve_path("music", project_id, song_id)
    except ValueError:
        return
    if target.exists():
        try:
            remove_path(target)
        except OSError:
            log.warning("Could not remove song folder %s", target, exc_info=True)


def _resources() -> dict[str, Any]:
    resources: dict[str, Any] = {
        "cpu_count": os.cpu_count(),
        "load_avg": None,
        "memory": {},
        "disk": {},
    }
    try:
        resources["load_avg"] = [round(value, 2) for value in os.getloadavg()]
    except (AttributeError, OSError):
        pass
    try:
        import psutil

        memory = psutil.virtual_memory()
        resources["memory"] = {
            "total_mb": round(memory.total / 1024 / 1024),
            "available_mb": round(memory.available / 1024 / 1024),
            "used_mb": round(memory.used / 1024 / 1024),
            "percent": memory.percent,
        }
        try:
            resources["process_memory_mb"] = round(psutil.Process().memory_info().rss / 1024 / 1024)
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001 - resource reporting must never fail the API
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as handle:
                values = {}
                for line in handle:
                    key, _, value = line.partition(":")
                    parts = value.strip().split()
                    if parts:
                        values[key] = int(parts[0])
            total = values.get("MemTotal", 0)
            available = values.get("MemAvailable", 0)
            if total:
                resources["memory"] = {
                    "total_mb": round(total / 1024),
                    "available_mb": round(available / 1024),
                    "used_mb": round((total - available) / 1024),
                    "percent": round((total - available) / total * 100, 1),
                }
        except (OSError, ValueError):
            pass
    for label, path in (
        ("files", FILES_ROOT),
        ("state", STATE_ROOT),
        ("models", engine.models_dir),
    ):
        try:
            usage = shutil.disk_usage(path)
            resources["disk"][label] = {
                "path": str(path),
                "total_gb": round(usage.total / 1024**3, 2),
                "used_gb": round(usage.used / 1024**3, 2),
                "free_gb": round(usage.free / 1024**3, 2),
            }
        except OSError:
            resources["disk"][label] = {"path": str(path), "error": "unavailable"}
    return resources


# --------------------------------------------------------------------------- catalog
async def _engine_state() -> dict[str, Any]:
    """Probe the engine, but never let a malformed /props break the studio."""
    try:
        return await engine.probe()
    except Exception as exc:  # noqa: BLE001 - catalog/system must degrade gracefully
        log.exception("Engine probe failed")
        return {
            "available": False,
            "detail": f"Could not read ACE-Step engine status: {exc}",
            "version": None,
            "props": {},
            "models": known_model_descriptors(DEFAULT_MODEL),
            "buckets": {"dit": [], "lm": [], "embedding": [], "vae": []},
            "health": {"reachable": False, "status": "offline", "detail": str(exc)},
            "engine_url": engine.base_url,
            "checked_at": utc_now(),
        }


@router.get("/catalog")
async def get_catalog() -> dict[str, Any]:
    state = await _engine_state()
    return catalog_payload(state, default_model=DEFAULT_MODEL)


@router.get("/system")
async def get_system() -> dict[str, Any]:
    state = await _engine_state()
    descriptor = engine_descriptor(state, DEFAULT_MODEL)
    models = state.get("models") or []
    return {
        "engine": descriptor,
        "engines": [descriptor],
        "health": state.get("health"),
        "available": bool(state.get("available")),
        "status": descriptor["status"],
        "status_detail": descriptor["status_detail"],
        "version": state.get("version"),
        "engine_url": state.get("engine_url"),
        "model_dir": str(engine.models_dir),
        "installed_files": engine.scan_model_files(),
        "buckets": state.get("buckets") or {},
        "models": models,
        "installed_models": [model for model in models if model.get("installed")],
        "resources": _resources(),
        "checked_at": state.get("checked_at"),
        "timestamp": utc_now(),
    }


# --------------------------------------------------------------------------- projects
@router.get("/projects")
def list_projects(q: str = Query(default="", max_length=200)) -> dict[str, Any]:
    where = ""
    params: list[Any] = []
    if q.strip():
        like = f"%{q.strip()}%"
        where = "WHERE p.title LIKE ? OR p.description LIKE ? OR p.artist LIKE ?"
        params = [like, like, like]
    rows = db.fetch_all(f"{PROJECT_SELECT} {where} ORDER BY COALESCE(last_activity, p.updated_at) DESC", params)
    items = [serialize_project(row) for row in rows]
    return {"items": items, "total": len(items)}


@router.post("/projects", status_code=201)
def create_project(payload: ProjectCreate) -> dict[str, Any]:
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Project title cannot be empty.")
    now = utc_now()
    project_id = new_id()
    db.execute(
        """
        INSERT INTO projects (id, title, description, artist, color, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id,
            title,
            payload.description.strip(),
            payload.artist.strip(),
            payload.color,
            now,
            now,
        ),
    )
    project = project_stats(project_id)
    if project is None:
        raise HTTPException(status_code=500, detail="Could not create the project.")
    return project


@router.get("/projects/{project_id}")
def get_project(project_id: str) -> dict[str, Any]:
    require_project(project_id)
    project = project_stats(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    project["songs"] = _project_songs(project_id)
    return project


@router.patch("/projects/{project_id}")
def update_project(project_id: str, payload: ProjectUpdate) -> dict[str, Any]:
    require_project(project_id)
    updates = payload.model_dump(exclude_unset=True)
    clean: dict[str, Any] = {}
    for key, value in updates.items():
        if key in PROJECT_FIELDS and value is not None:
            if key == "title" and not str(value).strip():
                raise HTTPException(status_code=422, detail="Project title cannot be empty.")
            clean[key] = value.strip() if isinstance(value, str) else value
    if clean:
        now = utc_now()
        columns = ", ".join(f"{key} = ?" for key in clean)
        db.execute(
            f"UPDATE projects SET {columns}, updated_at = ? WHERE id = ?",
            (*clean.values(), now, project_id),
        )
    project = project_stats(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str) -> Response:
    require_project(project_id)
    try:
        folder = resolve_path("music", project_id)
        if folder.exists():
            remove_path(folder)
    except (ValueError, OSError):
        log.warning("Could not remove project files for %s", project_id, exc_info=True)
    db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    return Response(status_code=204)


# --------------------------------------------------------------------------- songs
@router.get("/songs")
def list_songs(
    project_id: str | None = Query(default=None),
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    conditions: list[str] = []
    params: list[Any] = []
    if project_id:
        conditions.append("s.project_id = ?")
        params.append(project_id)
    if q.strip():
        conditions.append("(s.title LIKE ? OR s.artist LIKE ? OR s.genre LIKE ?)")
        like = f"%{q.strip()}%"
        params.extend([like, like, like])
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    total_row = db.fetch_one(f"SELECT COUNT(*) AS count FROM songs s {where}", params)
    rows = db.fetch_all(
        f"""
        SELECT s.*, p.title AS project_title, p.color AS project_color,
            (SELECT COUNT(*) FROM takes t WHERE t.song_id = s.id) AS take_count,
            0 AS active_generations
        FROM songs s
        JOIN projects p ON p.id = s.project_id
        {where}
        ORDER BY s.updated_at DESC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    )
    return {
        "items": [song_list_item(row) for row in rows],
        "total": int((total_row or {}).get("count") or 0),
    }


@router.post("/songs", status_code=201)
def create_song(payload: SongCreate, project_id: str | None = Query(default=None)) -> dict[str, Any]:
    target = project_id or payload.project_id
    if not target:
        raise HTTPException(status_code=422, detail="project_id is required.")
    if project_id and payload.project_id and project_id != payload.project_id:
        raise HTTPException(status_code=422, detail="project_id in the body and query must match.")
    project = require_project(target)
    song = _insert_song(project, payload)
    return song_payload(song["id"])


@router.post("/projects/{project_id}/songs", status_code=201)
def create_project_song(project_id: str, payload: SongCreate) -> dict[str, Any]:
    project = require_project(project_id)
    song = _insert_song(project, payload)
    return song_payload(song["id"])


@router.get("/songs/{song_id}")
def get_song(song_id: str) -> dict[str, Any]:
    return song_payload(song_id)


@router.patch("/songs/{song_id}")
def update_song(song_id: str, payload: SongUpdate) -> dict[str, Any]:
    song = require_song(song_id)
    updates = payload.model_dump(exclude_unset=True)
    clean: dict[str, Any] = {}
    for key, value in updates.items():
        if key in SONG_FIELDS and value is not None:
            if key == "title" and not str(value).strip():
                raise HTTPException(status_code=422, detail="Song title cannot be empty.")
            clean[key] = value.strip() if isinstance(value, str) else value
    if clean:
        now = utc_now()
        columns = ", ".join(f"{key} = ?" for key in clean)
        db.execute(
            f"UPDATE songs SET {columns}, updated_at = ? WHERE id = ?",
            (*clean.values(), now, song_id),
        )
        db.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, song["project_id"]))
    return song_payload(song_id)


@router.delete("/songs/{song_id}", status_code=204)
def delete_song(song_id: str) -> Response:
    song = require_song(song_id)
    _delete_song_files(str(song["project_id"]), song_id)
    db.execute("DELETE FROM songs WHERE id = ?", (song_id,))
    return Response(status_code=204)


@router.post("/songs/{song_id}/duplicate", status_code=201)
def duplicate_song(song_id: str) -> dict[str, Any]:
    source = require_song(song_id)
    now = utc_now()
    copy_id = new_id()
    values = {field: source.get(field) for field in SONG_FIELDS}
    values["title"] = f"{source.get('title') or 'Untitled song'} (copy)"[:200]
    columns = ["id", "project_id", *SONG_FIELDS, "selected_take_id", "created_at", "updated_at"]
    placeholders = ", ".join("?" for _ in columns)
    params: list[Any] = [copy_id, source["project_id"]]
    params.extend(values[field] for field in SONG_FIELDS)
    params.extend([None, now, now])
    db.execute(f"INSERT INTO songs ({', '.join(columns)}) VALUES ({placeholders})", tuple(params))
    sections = [
        {
            "type": section.get("type"),
            "label": section.get("label"),
            "content": section.get("content"),
            "instructions": section.get("instructions"),
        }
        for section in db.get_lyrics(song_id)
    ]
    db.save_lyrics(copy_id, sections or default_lyrics_sections())
    return song_payload(copy_id)


# --------------------------------------------------------------------------- lyrics
@router.get("/songs/{song_id}/lyrics")
def get_lyrics(song_id: str) -> dict[str, Any]:
    require_song(song_id)
    return {"sections": db.get_lyrics(song_id)}


@router.put("/songs/{song_id}/lyrics")
def put_lyrics(song_id: str, payload: LyricsUpdate) -> dict[str, Any]:
    require_song(song_id)
    sections = db.save_lyrics(song_id, [section.model_dump() for section in payload.sections])
    return {"sections": sections}


def _lyrics_take(song: dict[str, Any], take_id: str | None) -> dict[str, Any] | None:
    """Resolve an explicit take, then the selected master, then the latest take."""
    song_id = str(song.get("id") or "")
    if take_id:
        take = db.fetch_one(
            "SELECT id, duration FROM takes WHERE id = ? AND song_id = ?", (take_id, song_id)
        )
        if take is None:
            raise HTTPException(status_code=404, detail="Take not found for this song.")
        return take
    selected_id = song.get("selected_take_id")
    if selected_id:
        take = db.fetch_one(
            "SELECT id, duration FROM takes WHERE id = ? AND song_id = ?", (selected_id, song_id)
        )
        if take is not None:
            return take
    return db.fetch_one(
        "SELECT id, duration FROM takes WHERE song_id = ? ORDER BY position DESC, created_at DESC LIMIT 1",
        (song_id,),
    )


@router.get("/songs/{song_id}/lyrics.srt")
def export_lyrics_srt(song_id: str, take_id: str | None = Query(default=None)) -> Response:
    """Download the structured lyrics as SRT, timed to the selected/latest take."""
    song = require_song(song_id)
    take = _lyrics_take(song, take_id)
    take_duration = float((take or {}).get("duration") or 0)
    song_duration = float(song.get("duration") or 0)
    duration = take_duration if take_duration > 0 else (song_duration if song_duration > 0 else 60.0)
    body = lyrics.build_lyrics_srt(
        db.get_lyrics(song_id),
        duration,
        fallback_duration=song_duration or 60.0,
    )
    filename = lyrics.srt_filename(str(song.get("title") or "lyrics"))
    headers = {
        "Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}",
        "Cache-Control": "no-store",
    }
    return Response(content=body, media_type="application/x-subrip; charset=utf-8", headers=headers)


def _lyrics_job_params(payload: LyricsDraftRequest, song: dict[str, Any] | None) -> dict[str, Any]:
    raw = payload.model_dump(mode="json")
    if song is None:
        return raw
    provided = payload.model_fields_set
    fallbacks = {
        "title": song.get("title"),
        "genre": song.get("genre"),
        "subgenre": song.get("subgenre"),
        "style": song.get("style"),
        "mood": song.get("mood"),
        "energy": song.get("energy"),
        "language": song.get("language"),
        "language_label": song.get("language_label"),
        "vocal_type": song.get("vocal_type"),
    }
    for key, value in fallbacks.items():
        if key not in provided and value not in (None, ""):
            raw[key] = value
    if "theme" not in provided:
        raw["theme"] = song.get("instructions") or song.get("style") or song.get("title") or raw.get("theme") or ""
    if "direction" not in provided:
        raw["direction"] = song.get("vocal_prompt") or raw.get("direction") or ""
    return raw


@router.post("/lyrics/draft", status_code=202)
async def draft_lyrics(payload: LyricsDraftRequest) -> dict[str, Any]:
    song: dict[str, Any] | None = None
    if payload.song_id:
        song = require_song(payload.song_id)
    try:
        await lyrics.ensure_available()
    except lyrics.LyricsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    title = payload.title or (song or {}).get("title") or "Lyrics draft"
    params = _lyrics_job_params(payload, song)
    job = await submit_job("lyrics_draft", f"Lyrics · {title}", params)
    return job


# --------------------------------------------------------------------------- generation
@router.post("/songs/{song_id}/generate", status_code=202)
async def generate_song(song_id: str, payload: GenerateRequest) -> dict[str, Any]:
    song = require_song(song_id)
    try:
        params = GenerationJobParams(song_id=song_id, **payload.model_dump())
    except ValidationError as exc:
        raise _validation_http(exc) from exc
    await prepare_generation(params)
    params_json = params.model_dump(mode="json")
    job = await submit_job("generate", f"{song.get('title') or 'Song'} · {payload.mode}", params_json)
    now = utc_now()
    db.execute(
        "UPDATE songs SET provider = ?, model_id = ?, updated_at = ? WHERE id = ?",
        (payload.provider, payload.model_id, now, song_id),
    )
    db.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, song["project_id"]))
    return job


@router.get("/songs/{song_id}/takes")
def list_takes(song_id: str) -> dict[str, Any]:
    require_song(song_id)
    rows = db.fetch_all("SELECT * FROM takes WHERE song_id = ? ORDER BY position ASC", (song_id,))
    items = [serialize_take(row) for row in rows]
    return {"items": items, "total": len(items)}


@router.patch("/takes/{take_id}")
def update_take(take_id: str, payload: TakeUpdate) -> dict[str, Any]:
    take = db.fetch_one("SELECT * FROM takes WHERE id = ?", (take_id,))
    if take is None:
        raise HTTPException(status_code=404, detail="Take not found")
    updates = payload.model_dump(exclude_unset=True)
    if "is_favorite" in updates and updates["is_favorite"] is not None:
        db.execute("UPDATE takes SET is_favorite = ? WHERE id = ?", (1 if updates["is_favorite"] else 0, take_id))
    if "notes" in updates and updates["notes"] is not None:
        db.execute("UPDATE takes SET notes = ? WHERE id = ?", (updates["notes"], take_id))
    row = db.fetch_one("SELECT * FROM takes WHERE id = ?", (take_id,))
    return serialize_take(row or take)


@router.post("/songs/{song_id}/select-take")
def select_take(song_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    require_song(song_id)
    take_id = payload.get("take_id") if "take_id" in payload else payload.get("id")
    if take_id:
        take = db.fetch_one("SELECT id FROM takes WHERE id = ? AND song_id = ?", (take_id, song_id))
        if take is None:
            raise HTTPException(status_code=404, detail="Take not found for this song.")
        db.execute(
            "UPDATE songs SET selected_take_id = ?, updated_at = ? WHERE id = ?",
            (take_id, utc_now(), song_id),
        )
    else:
        db.execute(
            "UPDATE songs SET selected_take_id = NULL, updated_at = ? WHERE id = ?",
            (utc_now(), song_id),
        )
    return song_payload(song_id)


@router.delete("/takes/{take_id}", status_code=204)
def delete_take(take_id: str) -> Response:
    take = db.delete_take(take_id)
    if take is None:
        raise HTTPException(status_code=404, detail="Take not found")
    try:
        path = resolve_path(str(take.get("path") or ""))
        if path.is_file():
            path.unlink(missing_ok=True)
            parent = path.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
    except (ValueError, OSError):
        log.warning("Could not remove take file %s", take.get("path"), exc_info=True)
    return Response(status_code=204)




# --------------------------------------------------------------------------- custom styles
def _style_payload(row: dict[str, Any]) -> dict[str, Any]:
    tags = str(row.get("tags") or "")
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row.get("description") or "",
        "prompt": row.get("prompt") or "",
        "tags": [part.strip() for part in tags.split(",") if part.strip()],
        "reference_path": row["reference_path"],
        "reference_url": f"/api/files/raw/{row['reference_path']}",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@router.get("/styles")
def list_styles() -> dict[str, Any]:
    rows = db.fetch_all("SELECT * FROM styles ORDER BY created_at DESC")
    return {"items": [_style_payload(row) for row in rows], "total": len(rows)}


@router.post("/styles", status_code=201)
def create_style(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    reference = str(payload.get("reference_path") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Style name is required.")
    if not reference:
        raise HTTPException(status_code=422, detail="A reference audio file is required.")
    try:
        path = resolve_path(reference)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Reference audio file was not found in shared storage.")
    if path.suffix.lower() not in {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".aiff", ".aif"}:
        raise HTTPException(status_code=422, detail="Reference audio must be a supported audio file.")
    tags = payload.get("tags") or ""
    if isinstance(tags, list):
        tags = ", ".join(str(item).strip() for item in tags if str(item).strip())
    now = utc_now()
    style_id = new_id()
    db.execute(
        """
        INSERT INTO styles (id, name, description, prompt, tags, reference_path, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            style_id,
            name[:120],
            str(payload.get("description") or "")[:2000],
            str(payload.get("prompt") or "")[:2000],
            str(tags)[:500],
            reference,
            now,
            now,
        ),
    )
    row = db.fetch_one("SELECT * FROM styles WHERE id = ?", (style_id,))
    return _style_payload(row or {})


@router.delete("/styles/{style_id}", status_code=204)
def delete_style(style_id: str) -> Response:
    if db.fetch_one("SELECT id FROM styles WHERE id = ?", (style_id,)) is None:
        raise HTTPException(status_code=404, detail="Style profile not found")
    db.execute("DELETE FROM styles WHERE id = ?", (style_id,))
    return Response(status_code=204)


# --------------------------------------------------------------------------- export
@router.post("/export", status_code=202)
async def export_audio(payload: ExportRequest) -> dict[str, Any]:
    fmt, kind = payload.resolved()
    if not payload.song_id and not payload.project_id:
        raise HTTPException(status_code=422, detail="song_id or project_id is required.")
    if not shutil.which("ffmpeg"):
        raise HTTPException(status_code=503, detail="ffmpeg is not available in the music container.")
    if kind == "project" or (payload.project_id and not payload.song_id):
        project_id = payload.project_id
        if not project_id and payload.song_id:
            song_row = require_song(payload.song_id)
            project_id = str(song_row["project_id"])
        if not project_id:
            raise HTTPException(status_code=404, detail="Project not found")
        project = require_project(project_id)
        songs = db.fetch_all("SELECT id FROM songs WHERE project_id = ?", (project["id"],))
        if not songs:
            raise HTTPException(status_code=422, detail="This project has no songs to export.")
    else:
        require_song(payload.song_id or "")
        if payload.take_id:
            take = db.fetch_one(
                "SELECT id FROM takes WHERE id = ? AND song_id = ?",
                (payload.take_id, payload.song_id),
            )
            if take is None:
                raise HTTPException(status_code=404, detail="Take not found for this song.")
        else:
            count = db.fetch_one(
                "SELECT COUNT(*) AS count FROM takes WHERE song_id = ?", (payload.song_id,)
            )
            if not int((count or {}).get("count") or 0):
                raise HTTPException(status_code=404, detail="Generate a take before exporting audio.")
    params = payload.model_dump(mode="json")
    params["format"] = fmt
    params["kind"] = kind
    title = "Export session" if kind in {"zip", "project"} else f"Export {fmt.upper()}"
    job = await submit_job("export", title, params)
    return job


# --------------------------------------------------------------------------- app
async def _startup() -> None:
    db.initialize()
    log.info("Music database ready at %s", db.path)


app = create_service_app(
    "music",
    "Open Studio Music",
    "ACE-Step 1.5 songwriting studio with projects, lyrics, takes and exports.",
    runner=runner,
    extra_routers=[router],
    on_startup=_startup,
)
