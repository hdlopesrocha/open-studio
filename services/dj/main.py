"""Open Studio DJ studio.

A self-contained crate-digging, analysis, style-model and mix-rendering service.
Music never leaves the machine: uploads, analysis, training, generation and
mixdown all run in this container and write into the shared files volume.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from openstudio_common import (
    JOBHUB_URL,
    create_service_app,
    env_int,
    jobhub_headers,
    relative_path,
    remove_path,
    resolve_path,
    sanitize_name,
    utc_now,
)

from . import analysis, planner
from .audio_io import probe_duration
from .db import STORE
from .mixer import EFFECT_PRESETS, EMOTION_PRESETS
from .mixscene import TRANSITION_TYPES, plan_scene
from .model import builtin_model, load_model
from .jobs import runner

log = logging.getLogger("dj")

router = APIRouter(prefix="/api/dj", tags=["dj"])

AUDIO_EXTENSIONS = {
    ".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".aiff", ".aif", ".wma", ".webm",
}
MAX_UPLOAD_MB = env_int("DJ_MAX_UPLOAD_MB", 512)
DEFAULT_DURATION = 180.0


def _json(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(value or "")
        return parsed if parsed is not None else default
    except (TypeError, ValueError):
        return default


def _track_payload(row: dict[str, Any], *, detail: bool = False) -> dict[str, Any]:
    analysis_data = _json(row.get("analysis_json"), {})
    tags = _json(row.get("tags"), [])
    waveform = _json(row.get("waveform_json"), [])
    payload = {
        "id": row["id"],
        "title": row.get("title") or "Untitled track",
        "artist": row.get("artist") or "",
        "path": row.get("path") or "",
        "url": f"/api/files/raw/{row.get('path')}" if row.get("path") else None,
        "mime": row.get("mime") or "",
        "size": int(row.get("size") or 0),
        "duration": round(float(row.get("duration") or 0), 3),
        "bpm": round(float(row.get("bpm") or 0), 2),
        "bpm_confidence": round(float(row.get("bpm_confidence") or 0), 4),
        "key": row.get("key") or "",
        "key_confidence": round(float(row.get("key_confidence") or 0), 4),
        "camelot": row.get("camelot") or "",
        "style": row.get("style") or "",
        "style_confidence": round(float(row.get("style_confidence") or 0), 4),
        "mood": row.get("mood") or "",
        "energy": round(float(row.get("energy") or 0), 4),
        "danceability": round(float(row.get("danceability") or 0), 4),
        "valence": round(float(row.get("valence") or 0), 4),
        "loudness": round(float(row.get("loudness") or 0), 2),
        "tags": tags,
        "waveform": waveform,
        "status": row.get("status") or "uploaded",
        "error": row.get("error") or "",
        "notes": row.get("notes") or "",
        "analyzed": bool(analysis_data),
        "analysis_version": int(analysis_data.get("version") or 0),
        "sections": analysis_data.get("sections") or [],
        "scene_count": int(analysis_data.get("scene_count") or len(analysis_data.get("sections") or [])),
        "summary": analysis_data.get("summary") or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
    if detail:
        payload["analysis"] = analysis_data
    return payload


def _generation_payload(row: dict[str, Any], *, detail: bool = False) -> dict[str, Any]:
    stems = _json(row.get("stems_json"), {})
    payload = {
        "id": row["id"],
        "style": row.get("style") or "",
        "title": row.get("title") or "Untitled generation",
        "prompt": row.get("prompt") or "",
        "path": row.get("path") or "",
        "url": f"/api/files/raw/{row.get('path')}" if row.get("path") else None,
        "stems": stems,
        "duration": round(float(row.get("duration") or 0), 3),
        "bpm": round(float(row.get("bpm") or 0), 2),
        "key": row.get("key") or "",
        "seed": int(row.get("seed") or 0),
        "status": row.get("status") or "queued",
        "error": row.get("error") or "",
        "job_id": row.get("job_id"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
    if detail:
        payload["params"] = _json(row.get("params_json"), {})
        payload["structure"] = _json(row.get("structure_json"), [])
    return payload


def _generation_as_track(row: dict[str, Any]) -> dict[str, Any] | None:
    """Expose a rendered generation to the mix-scene planner."""
    if row.get("status") != "completed" or not row.get("path"):
        return None
    params = _json(row.get("params_json"), {})
    key = str(row.get("key") or "")
    tonic = key.split()[0] if key else ""
    mode = "minor" if "minor" in key.lower() else "major"
    structure = _json(row.get("structure_json"), [])
    analysis_payload = json.dumps(
        {
            "version": 3,
            "sections": structure if isinstance(structure, list) else [],
            "scene_count": len(structure) if isinstance(structure, list) else 0,
            "summary": f"{row.get('style') or 'Generated'} arrangement",
            "rhythm": {},
        },
        ensure_ascii=False,
    )
    return {
        "id": row["id"],
        "title": row.get("title") or "Generated track",
        "artist": "Open Studio · AI",
        "path": row.get("path"),
        "analysis_json": analysis_payload,
        "duration": float(row.get("duration") or 0),
        "bpm": float(row.get("bpm") or 0),
        "key": key,
        "camelot": analysis.camelot_for(tonic, mode) if tonic else "",
        "style": row.get("style") or "House",
        "mood": "Generated",
        "energy": float(params.get("energy") or 0.68),
        "valence": 0.6,
        "status": "generated",
        "source": "generation",
        "generation_id": row["id"],
    }


def _mix_payload(row: dict[str, Any], *, detail: bool = False) -> dict[str, Any]:
    scene = _json(row.get("scene_json"), {})
    payload = {
        "id": row["id"],
        "title": row.get("title") or "Untitled mix",
        "prompt": row.get("prompt") or "",
        "path": row.get("path") or "",
        "url": f"/api/files/raw/{row.get('path')}" if row.get("path") else None,
        "duration": round(float(row.get("duration") or 0), 3),
        "status": row.get("status") or "draft",
        "error": row.get("error") or "",
        "job_id": row.get("job_id"),
        "track_count": len(scene.get("tracks") or []) if isinstance(scene, dict) else 0,
        "master_bpm": scene.get("master_bpm") if isinstance(scene, dict) else None,
        "notes": scene.get("notes") if isinstance(scene, dict) else [],
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
    if detail:
        payload["scene"] = scene if isinstance(scene, dict) and scene.get("tracks") else None
    return payload


def _style_counts() -> dict[str, int]:
    rows = STORE.all(
        "SELECT style, COUNT(*) AS n FROM tracks WHERE status='analyzed' AND style<>'' GROUP BY style"
    )
    return {str(row["style"]): int(row["n"] or 0) for row in rows}


def _style_payload(style: str, *, counts: dict[str, int] | None = None) -> dict[str, Any]:
    style = analysis.canonical_style(style) or style
    counts = counts if counts is not None else _style_counts()
    builtin = builtin_model(style)
    row = STORE.style_model(style)
    model = load_model(row, style)
    return {
        "style": style,
        "label": style,
        "trained": bool(row),
        "track_count": int((row or {}).get("track_count") or 0),
        "available_tracks": counts.get(style, 0),
        "bpm": round(float((row or {}).get("bpm") or model.get("bpm") or 0), 2),
        "energy": round(float((row or {}).get("energy") or model.get("energy") or 0), 4),
        "key": (row or {}).get("key") or model.get("key") or "",
        "mood": model.get("mood") or "",
        "preset": {
            "bpm": builtin["bpm"],
            "energy": builtin["energy"],
            "key": builtin["key"],
            "valence": builtin["valence"],
        },
        "model": model,
        "updated_at": (row or {}).get("updated_at"),
    }


def _all_styles() -> list[dict[str, Any]]:
    counts = _style_counts()
    return [_style_payload(style, counts=counts) for style in analysis.STYLE_PROFILES]


def _analyzed_tracks(style: str | None = None) -> list[dict[str, Any]]:
    tracks = STORE.tracks(style=style or "", limit=2000)
    return [track for track in tracks if track.get("status") == "analyzed" and track.get("analysis_json")]


def _track_or_404(track_id: str) -> dict[str, Any]:
    row = STORE.track(track_id)
    if not row:
        raise HTTPException(status_code=404, detail="Track not found")
    return row


def _generation_or_404(generation_id: str) -> dict[str, Any]:
    row = STORE.generation(generation_id)
    if not row:
        raise HTTPException(status_code=404, detail="Generation not found")
    return row


def _mix_or_404(mix_id: str) -> dict[str, Any]:
    row = STORE.mix(mix_id)
    if not row:
        raise HTTPException(status_code=404, detail="Mix not found")
    return row


async def submit_job(action: str, title: str, params: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "component": "dj",
        "action": action,
        "title": (title or "DJ job")[:200],
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
        raise HTTPException(status_code=503 if response.status_code >= 500 else response.status_code, detail=str(detail)[:1000])
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="The job hub returned an invalid response.") from exc


@router.get("")
async def dj_root() -> dict[str, Any]:
    return {
        "service": "dj",
        "name": "Open Studio DJ Studio",
        "features": ["upload", "analysis", "style-models", "generation", "mix-scenes", "effects"],
        "styles": list(analysis.STYLE_PROFILES),
        "transitions": TRANSITION_TYPES,
    }


@router.get("/overview")
async def overview() -> dict[str, Any]:
    styles = _all_styles()
    generations = STORE.generations(limit=8)
    mixes = STORE.mixes(limit=8)
    track_count = STORE.one("SELECT COUNT(*) AS n FROM tracks")
    analyzed_count = STORE.one("SELECT COUNT(*) AS n FROM tracks WHERE status='analyzed'")
    mix_count = STORE.one("SELECT COUNT(*) AS n FROM mixes")
    generation_count = STORE.one("SELECT COUNT(*) AS n FROM generations")
    return {
        "tracks": int((track_count or {}).get("n") or 0),
        "analyzed": int((analyzed_count or {}).get("n") or 0),
        "styles_trained": sum(1 for style in styles if style["trained"]),
        "generations": int((generation_count or {}).get("n") or 0),
        "mixes": int((mix_count or {}).get("n") or 0),
        "styles": styles,
        "effects": EFFECT_PRESETS,
        "emotions": EMOTION_PRESETS,
        "transitions": TRANSITION_TYPES,
        "recent_generations": [_generation_payload(row) for row in generations],
        "recent_mixes": [_mix_payload(row) for row in mixes],
        "max_upload_mb": MAX_UPLOAD_MB,
        "generated_at": utc_now(),
    }


# Tracks -------------------------------------------------------------------


@router.get("/tracks")
async def list_tracks(
    q: str = "",
    style: str = "",
    limit: int = Query(300, ge=1, le=2000),
) -> dict[str, Any]:
    rows = STORE.tracks(q, analysis.canonical_style(style) or style, limit)
    return {"items": [_track_payload(row) for row in rows], "total": len(rows)}


@router.post("/tracks")
async def upload_track(
    file: UploadFile = File(...),
    title: str = Form(""),
    artist: str = Form(""),
    analyze: bool = Form(True),
) -> dict[str, Any]:
    filename = sanitize_name(file.filename or "track.wav")
    suffix = Path(filename).suffix.lower()
    if suffix not in AUDIO_EXTENSIONS:
        raise HTTPException(status_code=422, detail=f"Unsupported audio format '{suffix or 'unknown'}'.")
    track_id = uuid.uuid4().hex
    folder = resolve_path("dj", "tracks", track_id)
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / filename
    limit = MAX_UPLOAD_MB * 1024 * 1024
    written = 0
    try:
        with destination.open("wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit:
                    raise HTTPException(status_code=413, detail=f"Audio uploads are limited to {MAX_UPLOAD_MB} MB.")
                handle.write(chunk)
    except HTTPException:
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    if written == 0:
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(status_code=422, detail="The uploaded file is empty.")
    duration = probe_duration(destination)
    row = STORE.add_track(
        id=track_id,
        title=(title or Path(filename).stem).strip()[:200],
        artist=artist.strip()[:200],
        path=relative_path(destination),
        mime=file.content_type or "audio/wav",
        size=written,
        duration=duration,
    )
    job = None
    warning = ""
    if analyze:
        try:
            job = await submit_job("analyze_track", f"Analyse {row['title']}", {"track_id": track_id})
            STORE.update_track(track_id, status="queued")
        except HTTPException as exc:
            warning = str(exc.detail)
    return {
        "track": _track_payload(STORE.track(track_id) or row),
        "job": job,
        "warning": warning,
    }


@router.post("/tracks/analyze-all")
async def analyze_all_tracks() -> dict[str, Any]:
    rows = [
        track
        for track in STORE.tracks(limit=2000)
        if track.get("path") and track.get("status") not in {"queued", "analyzing"}
    ]
    jobs: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for row in rows:
        try:
            job = await submit_job("analyze_track", f"Analyse {row['title']}", {"track_id": row["id"]})
            STORE.update_track(row["id"], status="queued", error="")
            jobs.append(job)
        except HTTPException as exc:
            errors.append({"track_id": row["id"], "title": row["title"], "error": str(exc.detail)})
    return {"jobs": jobs, "count": len(jobs), "errors": errors}


@router.get("/tracks/{track_id}")
async def get_track(track_id: str) -> dict[str, Any]:
    return _track_payload(_track_or_404(track_id), detail=True)


@router.patch("/tracks/{track_id}")
async def update_track(track_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    row = _track_or_404(track_id)
    updates: dict[str, Any] = {}
    for field in ("title", "artist", "notes"):
        if field in payload:
            updates[field] = str(payload.get(field) or "").strip()[:2000]
    if "style" in payload:
        style = analysis.canonical_style(str(payload.get("style") or "")) or str(payload.get("style") or "").strip()
        if not style:
            raise HTTPException(status_code=422, detail="Unknown style")
        updates["style"] = style
        updates["style_confidence"] = 1.0
        analysis_data = _json(row.get("analysis_json"), {})
        if isinstance(analysis_data, dict):
            analysis_data["style"] = style
            analysis_data["style_source"] = "manual"
            updates["analysis_json"] = json.dumps(analysis_data, ensure_ascii=False)
    if "mood" in payload:
        updates["mood"] = str(payload.get("mood") or "").strip()[:120]
    if "tags" in payload and isinstance(payload.get("tags"), list):
        updates["tags"] = json.dumps([str(tag)[:60] for tag in payload["tags"]][:30], ensure_ascii=False)
    updated = STORE.update_track(track_id, **updates)
    return _track_payload(updated or row)


@router.delete("/tracks/{track_id}")
async def delete_track(track_id: str) -> dict[str, Any]:
    row = _track_or_404(track_id)
    STORE.delete_track(track_id)
    try:
        folder = resolve_path("dj", "tracks", track_id)
        if folder.exists():
            remove_path(folder)
    except (OSError, ValueError):
        log.warning("Could not remove track folder %s", track_id, exc_info=True)
    return {"ok": True, "id": track_id, "title": row.get("title")}


@router.post("/tracks/{track_id}/analyze")
async def analyze_track(track_id: str) -> dict[str, Any]:
    row = _track_or_404(track_id)
    job = await submit_job("analyze_track", f"Analyse {row['title']}", {"track_id": track_id})
    STORE.update_track(track_id, status="queued", error="")
    return {"job": job, "track": _track_payload(STORE.track(track_id) or row)}


# Styles -------------------------------------------------------------------


@router.get("/styles")
async def list_styles() -> dict[str, Any]:
    return {"items": _all_styles()}


@router.post("/styles/train-all")
async def train_all_styles() -> dict[str, Any]:
    styles = [style for style in _all_styles() if style["available_tracks"] > 0]
    if not styles:
        raise HTTPException(status_code=422, detail="Analyse at least one track before training style models.")
    jobs = []
    for style in styles:
        try:
            jobs.append(await submit_job("train_style", f"Train {style['style']} model", {"style": style["style"]}))
        except HTTPException as exc:
            jobs.append({"style": style["style"], "error": str(exc.detail)})
    return {"jobs": jobs, "styles": [style["style"] for style in styles]}


@router.get("/styles/{style}")
async def get_style(style: str) -> dict[str, Any]:
    canonical = analysis.canonical_style(style)
    if not canonical:
        raise HTTPException(status_code=404, detail="Unknown style")
    return _style_payload(canonical)


@router.post("/styles/{style}/train")
async def train_style(style: str) -> dict[str, Any]:
    canonical = analysis.canonical_style(style)
    if not canonical:
        raise HTTPException(status_code=404, detail="Unknown style")
    tracks = _analyzed_tracks(canonical)
    if not tracks:
        raise HTTPException(
            status_code=422,
            detail=f"No analysed tracks are assigned to {canonical}. Analyse a track or change its style first.",
        )
    job = await submit_job("train_style", f"Train {canonical} model", {"style": canonical})
    return {"job": job, "style": canonical, "track_count": len(tracks)}


@router.delete("/styles/{style}")
async def reset_style_model(style: str) -> dict[str, Any]:
    canonical = analysis.canonical_style(style)
    if not canonical:
        raise HTTPException(status_code=404, detail="Unknown style")
    row = STORE.style_model(canonical)
    if not row:
        raise HTTPException(status_code=404, detail="This style is already using its built-in preset")
    STORE.execute("DELETE FROM style_models WHERE style=?", (canonical,))
    return {"ok": True, "style": canonical}


# Structure and generation -------------------------------------------------


@router.post("/structure")
async def structure(payload: dict[str, Any]) -> dict[str, Any]:
    style = analysis.canonical_style(str(payload.get("style") or "")) or "House"
    model_row = STORE.style_model(style)
    model = load_model(model_row, style)
    duration = float(payload.get("duration") or DEFAULT_DURATION)
    plan = await planner.plan_structure_async(
        style=style,
        duration=duration,
        prompt=str(payload.get("prompt") or ""),
        energy=float(payload.get("energy") if payload.get("energy") is not None else model.get("energy") or 0.68),
        bpm=float(payload.get("bpm") or model.get("bpm") or 0),
        key=str(payload.get("key") or model.get("key") or ""),
        seed=int(payload["seed"]) if payload.get("seed") not in (None, "") else None,
        model=model,
        use_llm=bool(payload.get("use_llm")),
    )
    plan["model"] = {
        "trained": bool(model_row),
        "tracks": model.get("tracks") or 0,
        "bpm": model.get("bpm"),
        "key": model.get("key"),
        "mood": model.get("mood"),
    }
    return plan


@router.get("/generations")
async def list_generations(limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    rows = STORE.generations(limit)
    return {"items": [_generation_payload(row) for row in rows]}


@router.post("/generations")
async def create_generation(payload: dict[str, Any]) -> dict[str, Any]:
    style = analysis.canonical_style(str(payload.get("style") or "")) or "House"
    model_row = STORE.style_model(style)
    model = load_model(model_row, style)
    duration = float(payload.get("duration") or DEFAULT_DURATION)
    prompt = str(payload.get("prompt") or "")
    sections = payload.get("structure") or []
    if not isinstance(sections, list) or not sections:
        plan = await planner.plan_structure_async(
            style=style,
            duration=duration,
            prompt=prompt,
            energy=float(payload.get("energy") if payload.get("energy") is not None else model.get("energy") or 0.68),
            bpm=float(payload.get("bpm") or model.get("bpm") or 0),
            key=str(payload.get("key") or model.get("key") or ""),
            seed=int(payload["seed"]) if payload.get("seed") not in (None, "") else None,
            model=model,
            use_llm=bool(payload.get("use_llm")),
        )
        sections = plan["sections"]
        duration = float(plan.get("duration") or duration)
    bpm = float(payload.get("bpm") or model.get("bpm") or 120)
    sections = planner.normalise_structure(sections, bpm=bpm, duration=duration, style=style)
    duration = float(sections[-1]["end"]) if sections else duration
    title = str(payload.get("title") or f"{style} sketch").strip()[:200]
    params = {
        **{key: value for key, value in payload.items() if key not in {"structure"}},
        "structure": sections,
        "duration": duration,
        "style": style,
    }
    generation = STORE.add_generation(
        style=style,
        title=title,
        prompt=prompt,
        params_json=json.dumps(params, ensure_ascii=False),
        structure_json=json.dumps(sections, ensure_ascii=False),
        status="queued",
    )
    job = await submit_job("generate_track", f"Generate {title}", {"generation_id": generation["id"]})
    STORE.update_generation(generation["id"], job_id=job["id"])
    return {"generation": _generation_payload(STORE.generation(generation["id"]) or generation), "job": job}


@router.get("/generations/{generation_id}")
async def get_generation(generation_id: str) -> dict[str, Any]:
    return _generation_payload(_generation_or_404(generation_id), detail=True)


@router.post("/generations/{generation_id}/retry")
async def retry_generation(generation_id: str) -> dict[str, Any]:
    row = _generation_or_404(generation_id)
    STORE.update_generation(generation_id, status="queued", error="")
    job = await submit_job("generate_track", f"Regenerate {row['title']}", {"generation_id": generation_id})
    STORE.update_generation(generation_id, job_id=job["id"])
    return {"generation": _generation_payload(STORE.generation(generation_id) or row), "job": job}


@router.delete("/generations/{generation_id}")
async def delete_generation(generation_id: str) -> dict[str, Any]:
    row = _generation_or_404(generation_id)
    STORE.delete_generation(generation_id)
    try:
        folder = resolve_path("dj", "generated", generation_id)
        if folder.exists():
            remove_path(folder)
    except (OSError, ValueError):
        log.warning("Could not remove generation folder %s", generation_id, exc_info=True)
    return {"ok": True, "id": generation_id, "title": row.get("title")}


# Mix scenes ---------------------------------------------------------------


@router.get("/mixes")
async def list_mixes(limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    rows = STORE.mixes(limit)
    return {"items": [_mix_payload(row) for row in rows]}


@router.post("/mixes")
async def create_mix(payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title") or "Untitled mix").strip()[:200]
    prompt = str(payload.get("prompt") or "")
    scene = payload.get("scene")
    if not isinstance(scene, dict):
        scene = {}
    row = STORE.add_mix(title=title, prompt=prompt, scene=json.dumps(scene, ensure_ascii=False))
    return _mix_payload(row, detail=True)


@router.get("/mixes/{mix_id}")
async def get_mix(mix_id: str) -> dict[str, Any]:
    return _mix_payload(_mix_or_404(mix_id), detail=True)


@router.patch("/mixes/{mix_id}")
async def update_mix(mix_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    row = _mix_or_404(mix_id)
    updates: dict[str, Any] = {}
    if "title" in payload:
        updates["title"] = str(payload.get("title") or "Untitled mix").strip()[:200]
    if "prompt" in payload:
        updates["prompt"] = str(payload.get("prompt") or "")[:4000]
    if "scene" in payload:
        scene = payload.get("scene")
        if not isinstance(scene, dict):
            raise HTTPException(status_code=422, detail="scene must be an object")
        updates["scene_json"] = json.dumps(scene, ensure_ascii=False)
        updates["status"] = "draft"
        updates["path"] = ""
        updates["duration"] = float(scene.get("duration") or 0)
    updated = STORE.update_mix(mix_id, **updates) or row
    return _mix_payload(updated, detail=True)


@router.delete("/mixes/{mix_id}")
async def delete_mix(mix_id: str) -> dict[str, Any]:
    row = _mix_or_404(mix_id)
    STORE.delete_mix(mix_id)
    try:
        folder = resolve_path("dj", "mixes", mix_id)
        if folder.exists():
            remove_path(folder)
    except (OSError, ValueError):
        log.warning("Could not remove mix folder %s", mix_id, exc_info=True)
    return {"ok": True, "id": mix_id, "title": row.get("title")}


@router.post("/mixes/{mix_id}/scene")
async def create_scene(mix_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    row = _mix_or_404(mix_id)
    prompt = str(payload.get("prompt") if payload.get("prompt") is not None else row.get("prompt") or "")
    track_ids = payload.get("track_ids")
    order: list[str] = [str(item) for item in track_ids] if isinstance(track_ids, list) else []
    if not order:
        existing = _json(row.get("scene_json"), {})
        order = [str(entry.get("track_id")) for entry in (existing.get("tracks") or []) if entry.get("track_id")]
    library = _analyzed_tracks()
    generated = [
        track
        for track in (_generation_as_track(row) for row in STORE.generations(limit=300))
        if track is not None
    ]
    by_id = {track["id"]: track for track in [*library, *generated]}
    if order:
        tracks = [by_id[track_id] for track_id in order if track_id in by_id]
    else:
        tracks = [*library, *generated]
    tracks = [track for track in tracks if track.get("path") and float(track.get("duration") or 0) > 1]
    if not tracks:
        raise HTTPException(status_code=422, detail="Analyse at least one track before creating a mix scene.")
    scene = plan_scene(
        tracks,
        prompt=prompt,
        master_bpm=float(payload.get("master_bpm") or 0),
        transition_beats=int(payload.get("transition_beats") or 16),
        seed=int(payload["seed"]) if payload.get("seed") not in (None, "") else None,
        keep_order=bool(payload.get("keep_order", True)),
        use_sections=bool(payload.get("use_sections", True)),
    )
    scene["created_at"] = utc_now()
    scene["title"] = row.get("title") or "Untitled mix"
    updated = STORE.update_mix(
        mix_id,
        prompt=prompt,
        scene_json=json.dumps(scene, ensure_ascii=False),
        status="draft",
        path="",
        duration=float(scene.get("duration") or 0),
        error="",
    ) or row
    return {"mix": _mix_payload(updated, detail=True), "scene": scene}


@router.post("/mixes/{mix_id}/render")
async def render_mix_route(mix_id: str) -> dict[str, Any]:
    row = _mix_or_404(mix_id)
    scene = _json(row.get("scene_json"), {})
    if not isinstance(scene, dict) or not scene.get("tracks"):
        raise HTTPException(status_code=422, detail="Create a mix scene before rendering.")
    STORE.update_mix(mix_id, status="queued", error="")
    job = await submit_job("render_mix", f"Render {row['title']}", {"mix_id": mix_id})
    STORE.update_mix(mix_id, job_id=job["id"])
    return {"job": job, "mix": _mix_payload(STORE.mix(mix_id) or row)}


@router.get("/effects/presets")
async def effect_presets() -> dict[str, Any]:
    return {
        "effects": EFFECT_PRESETS,
        "emotions": EMOTION_PRESETS,
        "transitions": TRANSITION_TYPES,
    }


_WARMUP_TASK: asyncio.Task[Any] | None = None


async def _warmup() -> None:
    try:
        await asyncio.to_thread(analysis.warmup)
        log.info("DJ audio analysis warmed up")
    except Exception:  # noqa: BLE001 - warmup must never block the service
        log.warning("DJ analysis warmup failed", exc_info=True)


async def _startup_warmup() -> None:
    global _WARMUP_TASK
    _WARMUP_TASK = asyncio.create_task(_warmup(), name="dj-analysis-warmup")


app = create_service_app(
    "dj",
    "Open Studio DJ Studio",
    "Upload, analyse, train style models, generate arrangements and render beat-matched mix scenes with effects.",
    runner=runner,
    extra_routers=[router],
    on_startup=_startup_warmup,
)
