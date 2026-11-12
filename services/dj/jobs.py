"""DJ job handlers: analysis, style training, generation and mix rendering."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import random
import time
from pathlib import Path
from typing import Any

from openstudio_common import JobContext, JobRunner, job_result, relative_path, resolve_path

from . import analysis, planner, synth
from .audio_io import write_json, write_wav
from .db import STORE
from .mixer import render_mix
from .model import generation_defaults, load_model, train_model

log = logging.getLogger("dj.jobs")

runner = JobRunner("dj")


def _json(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(value or "")
        return parsed if parsed is not None else default
    except (TypeError, ValueError):
        return default


def _track(track_id: str) -> dict[str, Any]:
    track = STORE.track(track_id)
    if not track:
        raise ValueError("Track not found")
    return track


async def _analyze(ctx: JobContext) -> dict[str, Any]:
    track_id = str(ctx.params.get("track_id") or "")
    track = _track(track_id)
    source = resolve_path(track["path"])
    if not source.is_file():
        STORE.update_track(track_id, status="failed", error="The uploaded audio file is missing.")
        raise FileNotFoundError(f"Audio file not found: {track['path']}")
    STORE.update_track(track_id, status="analyzing", error="")
    await ctx.report(8.0, "Decoding", f"Reading {track['title']}")
    try:
        result = await asyncio.to_thread(analysis.analyze_file, source, track["title"])
        await ctx.report(74.0, "Modelling", "Key, style, energy and section roles")
        payload = json.dumps(result, ensure_ascii=False)
        waveform = json.dumps(result.get("waveform") or [])
        tags = json.dumps(result.get("tags") or [])
        updated = STORE.update_track(
            track_id,
            duration=float(result.get("duration") or 0),
            bpm=float(result.get("bpm") or 0),
            bpm_confidence=float(result.get("bpm_confidence") or 0),
            key=str(result.get("key") or ""),
            key_confidence=float(result.get("key_confidence") or 0),
            camelot=str(result.get("camelot") or ""),
            style=str(result.get("style") or ""),
            style_confidence=float(result.get("style_confidence") or 0),
            mood=str(result.get("mood") or ""),
            energy=float(result.get("energy") or 0),
            danceability=float(result.get("danceability") or 0),
            valence=float(result.get("valence") or 0),
            loudness=float(result.get("loudness_db") or 0),
            tags=tags,
            analysis_json=payload,
            waveform_json=waveform,
            status="analyzed",
            error="",
        )
        await ctx.report(100.0, "Complete", str(result.get("summary") or "Track analysed"))
        await ctx.client.artifact(
            {
                "path": track["path"],
                "kind": "audio",
                "name": Path(track["path"]).name,
                "mime": track.get("mime") or "audio/wav",
            }
        )
        return job_result(
            message=f"{track['title']} analysed",
            data={
                "track_id": track_id,
                "analysis": result,
                "track": updated,
            },
        )
    except Exception as exc:
        STORE.update_track(track_id, status="failed", error=str(exc)[:2000])
        raise


async def _train_style(ctx: JobContext) -> dict[str, Any]:
    style = str(ctx.params.get("style") or "").strip()
    label = analysis.canonical_style(style) or style
    if not label:
        raise ValueError("style is required")
    await ctx.report(8.0, "Collecting", f"Gathering analysed {label} tracks")
    tracks = [
        track
        for track in STORE.tracks(style=label, limit=1000)
        if track.get("status") == "analyzed" and track.get("analysis_json")
    ]
    if not tracks:
        raise ValueError(f"No analysed tracks are assigned to {label}. Analyse tracks first or change their style.")
    await ctx.report(30.0, "Training", f"{len(tracks)} track(s) · tempo, key, spectrum and section arc")
    model = await asyncio.to_thread(train_model, label, tracks)
    await ctx.report(82.0, "Saving", "Writing the style model")
    stored = STORE.save_style_model(
        style=label,
        label=str(model.get("label") or label),
        model={
            "model_json": json.dumps(model, ensure_ascii=False),
            "track_count": int(model.get("tracks") or 0),
            "bpm": float(model.get("bpm") or 0),
            "energy": float(model.get("energy") or 0),
            "key": str(model.get("key") or ""),
        },
    )
    await ctx.report(100.0, "Complete", f"{label} model trained on {len(tracks)} track(s)")
    return job_result(
        message=f"{label} style model trained",
        data={"style": label, "model": model, "stored": stored},
    )


async def _generate(ctx: JobContext) -> dict[str, Any]:
    generation_id = str(ctx.params.get("generation_id") or "")
    row = STORE.generation(generation_id)
    if not row:
        raise ValueError("Generation not found")
    params = _json(row.get("params_json"), {})
    style = analysis.canonical_style(str(row.get("style") or params.get("style") or "")) or "House"
    model_row = STORE.style_model(style)
    model = load_model(model_row, style)
    defaults = generation_defaults(style=style, model=model, params=params)
    bpm = float(params.get("bpm") or defaults["bpm"] or 120.0)
    energy = float(params.get("energy") if params.get("energy") is not None else defaults["energy"])
    key = str(params.get("key") or defaults["key"] or "A minor")
    brightness = float(params.get("brightness") if params.get("brightness") is not None else defaults["brightness"])
    duration = float(params.get("duration") or 180.0)
    seed = int(params.get("seed") if params.get("seed") not in (None, "") else random.randint(1, 2_000_000_000))
    raw_structure = params.get("structure") or _json(row.get("structure_json"), [])
    structure = planner.normalise_structure(raw_structure, bpm=bpm, duration=duration, style=style)
    duration = min(max(float(structure[-1]["end"]) if structure else duration, 20.0), 900.0)
    STORE.update_generation(generation_id, status="running", error="", seed=seed, bpm=bpm, key=key, duration=duration)
    await ctx.report(5.0, "Planning", f"{style} · {bpm:.0f} BPM · {key}")
    try:
        await ctx.report(18.0, "Synthesising", "Drums, sub bass and harmonic bed")
        started = time.perf_counter()
        loop = asyncio.get_running_loop()

        def progress(percent: float, stage: str, message: str) -> None:
            try:
                future = asyncio.run_coroutine_threadsafe(ctx.report(percent, stage, message), loop)
                future.result(timeout=10)
            except Exception:  # noqa: BLE001 - progress reporting is best effort
                pass

        result = await asyncio.to_thread(
            synth.render_track,
            style=style,
            bpm=bpm,
            key=key,
            duration=duration,
            sections=structure,
            seed=seed,
            energy=energy,
            brightness=brightness,
            model=model,
            progress=progress,
        )
        folder = resolve_path("dj", "generated", generation_id)
        folder.mkdir(parents=True, exist_ok=True)
        await ctx.report(72.0, "Rendering", "Stems and master bus")
        mix_path = folder / "track.wav"
        write_wav(mix_path, result["mix"])
        stems: dict[str, dict[str, Any]] = {}
        for name, audio in result["stems"].items():
            stem_path = folder / f"{name}.wav"
            write_wav(stem_path, audio)
            stems[name] = {
                "path": relative_path(stem_path),
                "url": f"/api/files/raw/{relative_path(stem_path)}",
                "duration": round(len(audio) / synth.SR, 3),
            }
        structure_path = folder / "structure.json"
        write_json(
            structure_path,
            {
                "style": style,
                "bpm": bpm,
                "key": key,
                "seed": seed,
                "sections": structure,
                "prompt": row.get("prompt") or "",
            },
        )
        write_json(folder / "metadata.json", result["metadata"])
        await ctx.report(94.0, "Finalising", "Waveform and metadata")
        updated = STORE.update_generation(
            generation_id,
            status="completed",
            path=relative_path(mix_path),
            stems_json=json.dumps(stems, ensure_ascii=False),
            duration=round(float(result["metadata"].get("duration") or duration), 3),
            bpm=float(result["metadata"].get("bpm") or bpm),
            key=str(result["metadata"].get("key") or key),
            seed=seed,
            error="",
        )
        await ctx.client.artifact(
            {
                "path": relative_path(mix_path),
                "kind": "audio",
                "name": f"{row.get('title') or 'generation'}.wav",
                "mime": "audio/wav",
            }
        )
        await ctx.report(100.0, "Complete", f"Generated {duration:.0f}s in {time.perf_counter() - started:.1f}s")
        return job_result(
            message=f"{row.get('title') or 'Track'} generated",
            data={"generation_id": generation_id, "generation": updated, "stems": stems, "metadata": result["metadata"]},
            files=[{"path": relative_path(mix_path), "kind": "audio"}],
        )
    except Exception as exc:
        STORE.update_generation(generation_id, status="failed", error=str(exc)[:3000])
        raise


async def _render_mix(ctx: JobContext) -> dict[str, Any]:
    mix_id = str(ctx.params.get("mix_id") or "")
    row = STORE.mix(mix_id)
    if not row:
        raise ValueError("Mix not found")
    scene = _json(row.get("scene_json"), {})
    if not isinstance(scene, dict) or not scene.get("tracks"):
        raise ValueError("Create a mix scene before rendering.")
    original_scene = copy.deepcopy(scene)
    scene = copy.deepcopy(scene)
    for entry in scene.get("tracks") or []:
        raw = str(entry.get("path") or "")
        if not raw:
            raise ValueError("A scene track has no audio path.")
        entry["path"] = str(resolve_path(raw))
    folder = resolve_path("dj", "mixes", mix_id)
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / "mix.wav"
    STORE.update_mix(mix_id, status="rendering", error="")
    await ctx.report(3.0, "Preparing", f"{len(scene['tracks'])} tracks · {scene.get('master_bpm', 120)} BPM")
    loop = asyncio.get_running_loop()

    def progress(percent: float, stage: str, message: str) -> None:
        try:
            future = asyncio.run_coroutine_threadsafe(ctx.report(percent, stage, message), loop)
            future.result(timeout=10)
        except Exception:  # noqa: BLE001 - progress reporting is best effort
            pass

    try:
        result = await asyncio.to_thread(render_mix, scene, output, progress=progress)
        for entry, timeline in zip(original_scene.get("tracks") or [], result.get("timeline") or []):
            entry["start"] = timeline.get("start", entry.get("start"))
            entry["timeline_duration"] = timeline.get("duration", entry.get("timeline_duration"))
        original_scene["duration"] = float(result.get("duration") or original_scene.get("duration") or 0)
        original_scene["master_bpm"] = float(result.get("master_bpm") or original_scene.get("master_bpm") or 120)
        write_json(folder / "scene.json", original_scene)
        updated = STORE.update_mix(
            mix_id,
            status="completed",
            path=relative_path(output),
            duration=float(result.get("duration") or 0),
            scene_json=json.dumps(original_scene, ensure_ascii=False),
            error="",
        )
        await ctx.client.artifact(
            {
                "path": relative_path(output),
                "kind": "audio",
                "name": f"{row.get('title') or 'mix'}.wav",
                "mime": "audio/wav",
            }
        )
        await ctx.report(100.0, "Complete", f"Mix rendered · {float(result.get('duration') or 0):.0f}s")
        return job_result(
            message=f"{row.get('title') or 'Mix'} rendered",
            data={"mix_id": mix_id, "mix": updated, "render": result},
            files=[{"path": relative_path(output), "kind": "audio"}],
        )
    except Exception as exc:
        STORE.update_mix(mix_id, status="failed", error=str(exc)[:3000])
        raise


runner.register("analyze_track", _analyze)
runner.register("train_style", _train_style)
runner.register("generate_track", _generate)
runner.register("render_mix", _render_mix)
