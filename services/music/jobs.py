"""Music job handlers registered with the central job hub."""

from __future__ import annotations

import asyncio
import json
import logging
import zipfile
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError

from openstudio_common import (
    FILES_ROOT,
    JobCancelled,
    JobContext,
    JobRunner,
    atomic_write_bytes,
    relative_path,
    resolve_path,
    unique_path,
    utc_now,
)

from . import audio, lyrics, prompts
from .catalog import MODE_CAPABILITY, MODE_TASKS
from .db import db, new_id
from .engine import EngineError, EngineUnavailable, engine
from .languages import ace_language
from .schemas import ExportRequest, GenerationJobParams, LyricsDraftRequest

log = logging.getLogger("music.jobs")

runner = JobRunner("music")


def engine_http_exception(exc: EngineError) -> HTTPException:
    if isinstance(exc, EngineUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    status = getattr(exc, "status_code", 503)
    if status in {404, 409, 413, 422}:
        return HTTPException(status_code=status, detail=str(exc))
    return HTTPException(status_code=500 if status < 500 else 503, detail=str(exc))


def _validation_exception(exc: ValidationError) -> HTTPException:
    errors = exc.errors()
    detail = errors[0].get("msg") if errors else "Invalid parameters."
    return HTTPException(status_code=422, detail=str(detail))


def resolve_input_path(raw: str | None) -> Path | None:
    """Resolve a files-relative path, also accepting an absolute path under FILES_ROOT."""
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("/"):
        resolved = Path(text).resolve()
        root = FILES_ROOT.resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError("Audio paths must live under the shared files root.")
        rel = resolved.relative_to(root).as_posix()
        return resolve_path(rel)
    return resolve_path(text)


def _require_file(path: Path | None, label: str) -> Path | None:
    if path is None:
        return None
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=422, detail=f"{label} audio is missing: {path.name}")
    return path


def serialize_take(row: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    try:
        metadata = json.loads(row.get("metadata_json") or "{}")
    except (TypeError, ValueError):
        metadata = {}
    rel = str(row.get("path") or "")
    return {
        "id": row["id"],
        "song_id": row["song_id"],
        "job_id": row.get("job_id"),
        "position": int(row.get("position") or 0),
        "path": rel,
        "url": f"/api/files/raw/{rel}" if rel else None,
        "name": Path(rel).name if rel else "",
        "duration": round(float(row.get("duration") or 0), 3),
        "seed": row.get("seed"),
        "metadata": metadata,
        "is_favorite": bool(row.get("is_favorite")),
        "notes": row.get("notes") or "",
        "created_at": row.get("created_at"),
    }


def _song_sections(song_id: str) -> list[dict[str, Any]]:
    return db.get_lyrics(song_id)


async def prepare_generation(params: GenerationJobParams) -> dict[str, Any]:
    """Validate a generation request and build the ACE-Step request payload.

    Shared by the HTTP preflight and the job handler so the API rejects bad
    operations immediately while retried jobs are validated again.
    """
    song = db.fetch_one("SELECT * FROM songs WHERE id = ?", (params.song_id,))
    if song is None:
        raise HTTPException(status_code=404, detail="Song not found")
    sections = _song_sections(params.song_id)
    style = None
    if params.style_id:
        style = db.fetch_one("SELECT * FROM styles WHERE id = ?", (params.style_id,))
        if style is None:
            raise HTTPException(status_code=404, detail="Style profile not found")
        if not params.reference_path:
            params.reference_path = str(style.get("reference_path") or "")

    try:
        source = _require_file(resolve_input_path(params.source_path), "Source")
        reference = _require_file(resolve_input_path(params.reference_path), "Reference")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if params.mode in {"repaint", "cover", "extend"} and source is None:
        raise HTTPException(status_code=422, detail=f"{params.mode} requires source_path audio.")
    if params.mode == "repaint" and params.end_seconds is None:
        raise HTTPException(status_code=422, detail="repaint requires end_seconds.")

    try:
        _state, model = await engine.require_model(params.model_id, workspace=params.mode)
    except EngineError as exc:
        raise engine_http_exception(exc) from exc
    capabilities = model.get("capabilities") or {}
    capability_key = MODE_CAPABILITY[params.mode]
    if not capabilities.get(capability_key):
        raise HTTPException(
            status_code=422,
            detail=(
                f"{model.get('name', params.model_id)} does not support {params.mode} operations. "
                f"{capabilities.get('operation_note') or 'Choose another operation or model.'}"
            ),
        )
    max_variations = int(capabilities.get("max_variations") or 4)
    if params.variations > max_variations:
        raise HTTPException(
            status_code=422,
            detail=f"This configuration supports at most {max_variations} takes per generation.",
        )
    if params.reference_path and not capabilities.get("reference_audio"):
        raise HTTPException(status_code=422, detail="The selected model does not support reference audio.")

    source_duration: float | None = None
    if source is not None:
        source_duration = await audio.probe_duration(source)
        if params.mode == "repaint" and source_duration and (params.end_seconds or 0) > source_duration + 0.75:
            raise HTTPException(
                status_code=422,
                detail=f"The repaint range extends beyond the source audio ({source_duration:.1f}s).",
            )

    duration = float(params.duration or song.get("duration") or 150)
    bpm = int(params.bpm or song.get("bpm") or 0)
    synth_batch = int(params.synth_batch_size or params.variations)
    lm_batch = int(params.lm_batch_size or 1)
    if synth_batch * lm_batch > 9:
        raise HTTPException(status_code=422, detail="At most 9 takes can be rendered from one planning pass.")

    files = model.get("files") or {}
    if not files.get("dit"):
        raise HTTPException(status_code=422, detail="The selected model has no DiT file installed.")
    if params.mode in {"full", "extend"} and not files.get("lm"):
        raise HTTPException(status_code=422, detail="The selected model has no 5Hz LM file installed.")

    warnings: list[str] = []
    if params.thinking:
        warnings.append(
            "The GGUF engine always uses its 5Hz LM for full songs; the thinking toggle is informational."
        )
    if params.enhance_prompt:
        warnings.append("Prompt expansion is expressed through the caption; the GGUF engine has no separate toggle.")
    if params.mode in {"cover", "repaint"}:
        warnings.append("Cover/repaint run directly through the DiT; the 5Hz planner is skipped.")

    caption = (params.caption or "").strip() or prompts.build_caption(
        song,
        sections,
        bpm=bpm or None,
        duration=duration,
        mode=params.mode,
        instruction=params.instruction,
        start_seconds=params.start_seconds,
        end_seconds=params.end_seconds,
    )
    if style and (style.get("prompt") or style.get("description")):
        style_note = (style.get("prompt") or style.get("description") or "").strip()
        if style_note:
            caption = f"{caption}\n\nStyle reference ({style.get('name')}): {style_note}"
    lyrics_text = params.lyrics if params.lyrics is not None else prompts.format_lyrics(song, sections)
    base_payload: dict[str, Any] = {
        "caption": caption,
        "lyrics": lyrics_text,
        "bpm": bpm,
        "duration": duration,
        "vocal_language": params.vocal_language or ace_language(str(song.get("language") or "en")),
        "seed": params.seed if params.seed is not None else -1,
        "lm_batch_size": lm_batch,
        "synth_batch_size": synth_batch,
        "inference_steps": params.inference_steps or int(model.get("default_steps") or 8),
        "guidance_scale": (
            params.guidance_scale
            if params.guidance_scale is not None
            else float(model.get("default_guidance") or 1.0)
        ),
        "task_type": MODE_TASKS[params.mode],
        "output_format": audio.engine_output_format(params.audio_format),
        "use_cot_caption": bool(params.use_format),
        "synth_model": files["dit"],
        "lm_model": files.get("lm") or "",
        "solver": "sde" if params.infer_method == "sde" else "euler",
    }
    if params.mode == "repaint":
        base_payload["repainting_start"] = params.start_seconds or 0.0
        base_payload["repainting_end"] = params.end_seconds
    if params.mode == "cover":
        base_payload["audio_cover_strength"] = params.cover_strength
    if params.track:
        base_payload["track"] = params.track

    return {
        "song": song,
        "sections": sections,
        "source": source,
        "reference": reference,
        "source_duration": source_duration,
        "model": model,
        "base_payload": base_payload,
        "synth_batch": synth_batch,
        "lm_batch": lm_batch,
        "duration": duration,
        "bpm": bpm,
        "warnings": warnings,
    }


def _parse_lm_result(content: bytes, content_type: str) -> list[dict[str, Any]]:
    if "json" not in content_type.lower() and not content.lstrip().startswith((b"[", b"{")):
        raise EngineError("The 5Hz planner returned an unexpected result format.", 503)
    try:
        body = json.loads(content)
    except ValueError as exc:
        raise EngineError("The 5Hz planner returned invalid JSON.", 503) from exc
    items = body if isinstance(body, list) else [body]
    requests: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if not item.get("audio_codes"):
            raise EngineError(
                "The 5Hz planner did not produce audio codes; check the engine logs and model files.",
                503,
            )
        requests.append(dict(item))
    if not requests:
        raise EngineError("The 5Hz planner returned no usable request.", 503)
    return requests


async def _wait_engine(
    ctx: JobContext,
    job_id: str,
    *,
    stage: str,
    message: str,
    start: float,
    end: float,
) -> None:
    last_report = [0.0]

    async def tick(elapsed: float, _status: dict[str, Any]) -> None:
        await ctx.check()
        if elapsed - last_report[0] < 10 and last_report[0] > 0:
            return
        last_report[0] = elapsed
        progress = min(end, start + min(1.0, elapsed / 90.0) * (end - start))
        suffix = f" ({int(elapsed)}s elapsed)" if elapsed >= 3 else ""
        await ctx.report(round(progress, 1), stage, f"{message}{suffix}")

    await ctx.report(start, stage, message)
    await engine.wait_job(job_id, on_tick=tick, check=ctx.check)


def _seed_for(
    index: int,
    *,
    base_seed: int | None,
    enriched: list[dict[str, Any]],
    synth_batch: int,
) -> int | None:
    if enriched:
        request_index = min(index // max(1, synth_batch), len(enriched) - 1)
        request_seed = enriched[request_index].get("seed")
        if isinstance(request_seed, int) and request_seed >= 0:
            return request_seed + (index % max(1, synth_batch))
    if isinstance(base_seed, int) and base_seed >= 0:
        return base_seed + index
    return None


@runner.action("generate")
async def handle_generate(ctx: JobContext) -> dict[str, Any]:
    try:
        params = GenerationJobParams.model_validate(ctx.params)
    except ValidationError as exc:
        raise _validation_exception(exc) from exc

    await ctx.report(2, "Preparing", "Reading the song brief and validating the engine.")
    prepared = await prepare_generation(params)
    song = prepared["song"]
    model = prepared["model"]
    base_payload: dict[str, Any] = prepared["base_payload"]
    source: Path | None = prepared["source"]
    reference: Path | None = prepared["reference"]
    warnings: list[str] = list(prepared["warnings"])
    synth_batch = int(prepared["synth_batch"])
    lm_batch = int(prepared["lm_batch"])

    enriched: list[dict[str, Any]] = []
    engine_job_id: str | None = None
    try:
        if params.mode in {"full", "extend"}:
            await ctx.report(5, "Planning", "The 5Hz planner is writing the song structure and audio codes.")
            lm_payload = dict(base_payload)
            lm_payload["lm_batch_size"] = lm_batch
            engine_job_id = await engine.submit_lm(lm_payload)
            await _wait_engine(
                ctx,
                engine_job_id,
                stage="Planning",
                message="Generating lyrics structure and 5Hz audio codes.",
                start=8,
                end=30,
            )
            await ctx.check()
            content, content_type = await engine.result(engine_job_id)
            engine_job_id = None
            enriched = _parse_lm_result(content, content_type)
        else:
            enriched = []

        if enriched:
            operational = {
                "synth_model": base_payload["synth_model"],
                "lm_model": base_payload["lm_model"],
                "synth_batch_size": synth_batch,
                "output_format": base_payload["output_format"],
                "task_type": base_payload["task_type"],
                "vocal_language": base_payload["vocal_language"],
                "duration": base_payload["duration"],
                "bpm": base_payload["bpm"],
                "seed": base_payload["seed"],
                "lm_batch_size": lm_batch,
                "inference_steps": base_payload["inference_steps"],
                "guidance_scale": base_payload["guidance_scale"],
                "solver": base_payload["solver"],
            }
            for item in enriched:
                item.update(operational)
                if not item.get("caption"):
                    item["caption"] = base_payload["caption"]
                if params.caption and params.caption.strip():
                    item["caption"] = base_payload["caption"]
                if base_payload["lyrics"]:
                    item["lyrics"] = base_payload["lyrics"]
                item.setdefault("lyrics", "")
                for key in ("repainting_start", "repainting_end", "audio_cover_strength", "track"):
                    if key in base_payload:
                        item[key] = base_payload[key]
            synth_payload: dict[str, Any] | list[dict[str, Any]] = (
                enriched[0] if len(enriched) == 1 else enriched
            )
        else:
            synth_payload = base_payload

        await ctx.report(32, "Rendering", "The DiT is rendering the song at 48 kHz.")
        parts: list[tuple[bytes, str]] = []
        # Multipart /synth requests carry one AceRequest. When LM batching
        # produced several requests and source/reference audio is attached,
        # submit them one by one instead of sending an unsupported array part.
        if isinstance(synth_payload, list) and (source is not None or reference is not None):
            total = len(synth_payload)
            for item_index, item in enumerate(synth_payload, start=1):
                await ctx.check()
                engine_job_id = await engine.submit_synth(item, source=source, reference=reference)
                await _wait_engine(
                    ctx,
                    engine_job_id,
                    stage="Rendering",
                    message=f"Waiting for the DiT and VAE to render variation {item_index} of {total}.",
                    start=35,
                    end=92,
                )
                await ctx.check()
                content, content_type = await engine.result(engine_job_id)
                engine_job_id = None
                parts.extend(await asyncio.to_thread(engine.parse_audio_parts, content, content_type))
        else:
            engine_job_id = await engine.submit_synth(synth_payload, source=source, reference=reference)
            await _wait_engine(
                ctx,
                engine_job_id,
                stage="Rendering",
                message="Waiting for the DiT and VAE to finish rendering.",
                start=35,
                end=92,
            )
            await ctx.check()
            content, content_type = await engine.result(engine_job_id)
            engine_job_id = None
            await ctx.check()
            parts = await asyncio.to_thread(engine.parse_audio_parts, content, content_type)
        if not parts:
            raise EngineError("The engine returned no audio parts. Check the music-engine logs.", 500)
    except JobCancelled:
        if engine_job_id is not None:
            await engine.cancel_job(engine_job_id)
        raise
    except EngineError as exc:
        if engine_job_id is not None:
            await engine.cancel_job(engine_job_id)
        raise engine_http_exception(exc) from exc

    expected = lm_batch * synth_batch if params.mode in {"full", "extend"} else synth_batch
    if len(parts) < expected:
        warnings.append(f"The engine returned {len(parts)} of {expected} requested take(s).")

    await ctx.report(94, "Finalising", "Writing the rendered take(s) into the shared library.")
    project_id = str(song["project_id"])
    song_id = str(song["id"])
    takes_dir = resolve_path("music", project_id, song_id, "takes")
    takes_dir.mkdir(parents=True, exist_ok=True)
    start_position = db.next_take_position(song_id)
    created_at = utc_now()
    created_rows: list[dict[str, Any]] = []
    file_records: list[dict[str, Any]] = []

    for index, (data, mime) in enumerate(parts):
        source_extension = audio.extension_for_mime(mime)
        destination = unique_path(
            takes_dir,
            f"take-{start_position + index + 1:02d}{source_extension}",
            suffix=source_extension,
        )
        await asyncio.to_thread(atomic_write_bytes, destination, data)
        desired_extension = audio.extension_for_format(params.audio_format)
        if destination.suffix.lower() != desired_extension:
            converted = destination.with_suffix(desired_extension)
            if converted.exists():
                converted = unique_path(
                    takes_dir,
                    f"take-{start_position + index + 1:02d}{desired_extension}",
                    suffix=desired_extension,
                )
            await audio.convert_audio(destination, converted, params.audio_format)
            destination.unlink(missing_ok=True)
            destination = converted
        duration = await audio.probe_duration(destination, fallback=prepared["duration"])
        seed = _seed_for(
            index,
            base_seed=params.seed,
            enriched=enriched,
            synth_batch=synth_batch,
        )
        metadata = {
            "engine": "ace_step",
            "engine_flavor": "cpp-gguf",
            "model": params.model_id,
            "quantization": model.get("quantization"),
            "mode": params.mode,
            "task_type": base_payload["task_type"],
            "bpm": prepared["bpm"],
            "vocal_language": base_payload["vocal_language"],
            "requested_duration": prepared["duration"],
            "inference_steps": base_payload["inference_steps"],
            "guidance_scale": base_payload["guidance_scale"],
            "synth_batch_size": synth_batch,
            "lm_batch_size": lm_batch,
            "audio_format": params.audio_format,
            "infer_method": params.infer_method,
            "seed": seed,
            "thinking": params.thinking,
            "use_format": params.use_format,
            "enhance_prompt": params.enhance_prompt,
            "instruction": params.instruction,
            "track": params.track,
            "source_path": relative_path(source) if source is not None else None,
            "reference_path": relative_path(reference) if reference is not None else None,
            "job_id": ctx.job_id,
            "warnings": warnings,
        }
        created_rows.append(
            {
                "id": new_id(),
                "song_id": song_id,
                "job_id": ctx.job_id,
                "position": start_position + index,
                "path": destination.relative_to(FILES_ROOT.resolve()).as_posix(),
                "duration": duration,
                "seed": seed,
                "metadata": metadata,
                "is_favorite": False,
                "notes": "",
                "created_at": created_at,
            }
        )
        file_records.append(audio.file_record(destination, "audio"))

    if not created_rows:
        raise HTTPException(status_code=500, detail="The engine finished without producing a readable take.")

    db.save_takes(song_id, created_rows)
    if warnings:
        try:
            await ctx.client.progress(warnings=warnings)
        except Exception:  # noqa: BLE001 - warnings are informational
            log.info("Could not attach warnings to job %s", ctx.job_id, exc_info=True)

    take_rows = [
        db.fetch_one("SELECT * FROM takes WHERE id = ?", (row["id"],)) or row for row in created_rows
    ]
    takes = [serialize_take(row) for row in take_rows]
    song_after = db.fetch_one("SELECT selected_take_id FROM songs WHERE id = ?", (song_id,)) or {}
    await ctx.report(99, "Finalising", f"{len(takes)} take(s) ready.")
    return {
        "message": f"{len(takes)} take{'s' if len(takes) != 1 else ''} ready.",
        "files": file_records,
        "data": {
            "takes": takes,
            "song_id": song_id,
            "job_id": ctx.job_id,
            "mode": params.mode,
            "model_id": params.model_id,
            "task_type": base_payload["task_type"],
            "selected_take_id": song_after.get("selected_take_id"),
            "warnings": warnings,
        },
    }


@runner.action("lyrics_draft")
async def handle_lyrics_draft(ctx: JobContext) -> dict[str, Any]:
    raw = dict(ctx.params)
    song: dict[str, Any] | None = None
    if raw.get("song_id"):
        song = db.fetch_one("SELECT * FROM songs WHERE id = ?", (raw["song_id"],))
        if song is None:
            raise HTTPException(status_code=404, detail="Song not found")
        if not raw.get("title"):
            raw["title"] = song.get("title") or ""
        if not raw.get("theme"):
            raw["theme"] = song.get("instructions") or song.get("style") or song.get("title") or ""
        if not raw.get("direction"):
            raw["direction"] = song.get("vocal_prompt") or ""
        if not raw.get("genre"):
            raw["genre"] = song.get("genre") or "Pop"
        if not raw.get("subgenre"):
            raw["subgenre"] = song.get("subgenre") or ""
        if not raw.get("style"):
            raw["style"] = song.get("style") or ""
        if not raw.get("mood"):
            raw["mood"] = song.get("mood") or ""
        if "energy" not in raw:
            raw["energy"] = song.get("energy") or 50
        if "language" not in raw:
            raw["language"] = song.get("language") or "pt-PT"
        if not raw.get("language_label"):
            raw["language_label"] = song.get("language_label") or ""
        if "vocal_type" not in raw:
            raw["vocal_type"] = song.get("vocal_type") or "female"

    try:
        request = LyricsDraftRequest.model_validate(raw)
    except ValidationError as exc:
        raise _validation_exception(exc) from exc

    await ctx.report(5, "Checking lyricist", "Contacting the shared LLM service.")
    try:
        await lyrics.ensure_available()
    except lyrics.LyricsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    await ctx.report(20, "Writing", "The local lyricist is drafting the song.")
    await ctx.check()
    try:
        result = await lyrics.draft(request)
    except lyrics.LyricsError as exc:
        status = 503 if exc.status_code not in {409, 422} else exc.status_code
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    await ctx.check()

    sections = result["sections"]
    saved = False
    if request.save and request.song_id:
        saved_sections = db.save_lyrics(request.song_id, sections)
        sections = saved_sections
        saved = True

    await ctx.report(95, "Finalising", "Lyrics draft ready.")
    return {
        "message": f"{len(sections)} lyric section{'s' if len(sections) != 1 else ''} drafted.",
        "files": [],
        "data": {
            "takes": [],
            "sections": sections,
            "song_id": request.song_id,
            "provider": result.get("provider"),
            "model": result.get("model"),
            "attempts": result.get("attempts"),
            "saved": saved,
        },
    }


def _pick_take(song_id: str, take_id: str | None) -> dict[str, Any]:
    if take_id:
        take = db.fetch_one("SELECT * FROM takes WHERE id = ? AND song_id = ?", (take_id, song_id))
        if take is None:
            raise HTTPException(status_code=404, detail="Take not found for this song.")
        return take
    song = db.fetch_one("SELECT selected_take_id FROM songs WHERE id = ?", (song_id,)) or {}
    if song.get("selected_take_id"):
        take = db.fetch_one("SELECT * FROM takes WHERE id = ?", (song["selected_take_id"],))
        if take is not None:
            return take
    take = db.fetch_one("SELECT * FROM takes WHERE song_id = ? ORDER BY position ASC LIMIT 1", (song_id,))
    if take is None:
        raise HTTPException(status_code=404, detail="Generate a take before exporting audio.")
    return take


def _take_source(take: dict[str, Any]) -> Path:
    try:
        path = resolve_path(str(take.get("path") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="The take file path is invalid.") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The selected audio file is missing.")
    return path


def _export_song_payload(
    song: dict[str, Any],
    sections: list[dict[str, Any]],
    takes: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "title": song.get("title"),
        "artist": song.get("artist"),
        "language": song.get("language"),
        "language_label": song.get("language_label"),
        "genre": song.get("genre"),
        "subgenre": song.get("subgenre"),
        "style": song.get("style"),
        "mood": song.get("mood"),
        "energy": song.get("energy"),
        "bpm": song.get("bpm"),
        "duration_seconds": song.get("duration"),
        "vocal": {
            "type": song.get("vocal_type"),
            "intensity": song.get("vocal_intensity"),
            "singing_style": song.get("singing_style"),
            "emotion": song.get("vocal_emotion"),
            "range": song.get("vocal_range"),
            "prompt": song.get("vocal_prompt"),
            "pronunciation": song.get("pronunciation"),
        },
        "instructions": song.get("instructions"),
        "provider": song.get("provider"),
        "model_id": song.get("model_id"),
        "selected_take_id": song.get("selected_take_id"),
        "lyrics": sections,
        "takes": [
            {
                "take": int(take.get("position") or 0) + 1,
                "path": take.get("path"),
                "duration": round(float(take.get("duration") or 0), 3),
                "seed": take.get("seed"),
                "created_at": take.get("created_at"),
                "favorite": bool(take.get("is_favorite")),
                "notes": take.get("notes") or "",
                "metadata": serialize_take(take)["metadata"],
            }
            for take in takes
        ],
        "exported_at": utc_now(),
        "tool": "Open Studio music",
    }


def _build_song_zip(
    destination: Path,
    folder: str,
    song: dict[str, Any],
    sections: list[dict[str, Any]],
    takes: list[dict[str, Any]],
    master: Path,
    include_all_takes: bool,
) -> None:
    payload = _export_song_payload(song, sections, takes)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{folder}/song.json", json.dumps(payload, ensure_ascii=False, indent=2))
        archive.writestr(f"{folder}/lyrics.txt", prompts.format_lyrics_for_text(sections))
        archive.writestr(
            f"{folder}/README.txt",
            "Made with Open Studio, a local AI music studio.\n"
            "This session includes the master take, song metadata and structured lyrics.\n",
        )
        if master.exists():
            archive.write(master, f"{folder}/master{master.suffix or '.wav'}")
        if include_all_takes:
            for take in takes:
                try:
                    path = resolve_path(str(take.get("path") or ""))
                except ValueError:
                    continue
                if path.is_file():
                    archive.write(
                        path,
                        f"{folder}/takes/take-{int(take.get('position') or 0) + 1:02d}{path.suffix or '.wav'}",
                    )


@runner.action("export")
async def handle_export(ctx: JobContext) -> dict[str, Any]:
    try:
        params = ExportRequest.model_validate(ctx.params)
    except ValidationError as exc:
        raise _validation_exception(exc) from exc
    fmt, kind = params.resolved()
    if not params.song_id and not params.project_id:
        raise HTTPException(status_code=422, detail="song_id or project_id is required.")
    await ctx.check()

    # ------------------------------------------------------------------ project
    if kind == "project" or (params.project_id and not params.song_id):
        project_id = params.project_id
        if not project_id:
            song = db.fetch_one("SELECT project_id FROM songs WHERE id = ?", (params.song_id,))
            project_id = (song or {}).get("project_id")
        if not project_id:
            raise HTTPException(status_code=404, detail="Project not found")
        project = db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        songs = db.fetch_all("SELECT * FROM songs WHERE project_id = ? ORDER BY created_at ASC", (project_id,))
        if not songs:
            raise HTTPException(status_code=422, detail="This project has no songs to export.")

        await ctx.report(8, "Preparing", "Collecting the project and its takes.")
        exports_dir = resolve_path("music", project_id, "exports")
        exports_dir.mkdir(parents=True, exist_ok=True)
        folder = audio.safe_filename(str(project.get("title") or "project"), "project")
        destination = unique_path(exports_dir, f"{folder}-project.zip", suffix=".zip")
        take_rows_all: list[dict[str, Any]] = []

        def build_project() -> None:
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("project.json", json.dumps(project, ensure_ascii=False, indent=2))
                for index, song in enumerate(songs, start=1):
                    sections = _song_sections(song["id"])
                    takes = db.fetch_all(
                        "SELECT * FROM takes WHERE song_id = ? ORDER BY position ASC", (song["id"],)
                    )
                    take_rows_all.extend(takes)
                    song_folder = f"{index:02d}-{audio.safe_filename(str(song.get('title') or 'song'), 'song')}"
                    payload = _export_song_payload(song, sections, takes)
                    archive.writestr(
                        f"songs/{song_folder}/song.json",
                        json.dumps(payload, ensure_ascii=False, indent=2),
                    )
                    archive.writestr(f"songs/{song_folder}/lyrics.txt", prompts.format_lyrics_for_text(sections))
                    for take in takes:
                        try:
                            path = resolve_path(str(take.get("path") or ""))
                        except ValueError:
                            continue
                        if path.is_file():
                            archive.write(
                                path,
                                f"songs/{song_folder}/takes/take-{int(take.get('position') or 0) + 1:02d}{path.suffix or '.wav'}",
                            )

        await ctx.report(25, "Packaging", "Writing project metadata, lyrics and takes into the archive.")
        await ctx.check()
        try:
            await asyncio.to_thread(build_project)
        except (OSError, zipfile.BadZipFile) as exc:
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail="Could not build the project archive.") from exc
        await ctx.report(96, "Finalising", "Project archive ready.")
        return {
            "message": "Project archive ready.",
            "files": [audio.file_record(destination, "archive")],
            "data": {
                "takes": [serialize_take(row) for row in take_rows_all],
                "project_id": project_id,
                "kind": "project",
                "format": "zip",
            },
        }

    # ------------------------------------------------------------------ song
    song = db.fetch_one("SELECT * FROM songs WHERE id = ?", (params.song_id,))
    if song is None:
        raise HTTPException(status_code=404, detail="Song not found")
    song_id = str(song["id"])
    take = _pick_take(song_id, params.take_id)
    source = _take_source(take)
    sections = _song_sections(song_id)
    exports_dir = resolve_path("music", str(song["project_id"]), song_id, "exports")
    exports_dir.mkdir(parents=True, exist_ok=True)
    base_name = audio.safe_filename(str(song.get("title") or "song"), "song")
    take_number = int(take.get("position") or 0) + 1

    if kind == "zip":
        await ctx.report(8, "Preparing", "Collecting song metadata, lyrics and takes.")
        takes = db.fetch_all("SELECT * FROM takes WHERE song_id = ? ORDER BY position ASC", (song_id,))
        destination = unique_path(exports_dir, f"{base_name}-session.zip", suffix=".zip")
        master = source
        temporary_master: Path | None = None
        if source.suffix.lower() != audio.extension_for_format(fmt):
            temporary_master = exports_dir / f".master-{take['id']}.{fmt}"
            await audio.convert_audio(source, temporary_master, fmt)
            master = temporary_master
        try:
            await ctx.report(35, "Packaging", "Writing song.json, lyrics.txt and audio into the session archive.")
            await ctx.check()
            await asyncio.to_thread(
                _build_song_zip,
                destination,
                base_name,
                song,
                sections,
                takes,
                master,
                params.include_all_takes,
            )
        except (OSError, zipfile.BadZipFile) as exc:
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail="Could not build the session package.") from exc
        finally:
            if temporary_master is not None:
                temporary_master.unlink(missing_ok=True)
        await ctx.report(96, "Finalising", "Session archive ready.")
        return {
            "message": "Session archive ready.",
            "files": [audio.file_record(destination, "archive")],
            "data": {
                "takes": [serialize_take(take)] if not params.include_all_takes else [serialize_take(row) for row in takes],
                "song_id": song_id,
                "kind": "zip",
                "format": "zip",
                "master_take_id": take["id"],
            },
        }

    await ctx.report(12, "Preparing", f"Converting the selected take to {fmt.upper()}.")
    await ctx.check()
    destination = unique_path(exports_dir, f"{base_name}-take-{take_number:02d}.{fmt}", suffix=f".{fmt}")
    try:
        await audio.convert_audio(source, destination, fmt)
    except Exception as exc:  # noqa: BLE001
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Audio export failed: {exc}") from exc
    duration = await audio.probe_duration(destination, fallback=float(take.get("duration") or 0))
    await ctx.report(96, "Finalising", "Audio export ready.")
    return {
        "message": f"{fmt.upper()} export ready.",
        "files": [audio.file_record(destination, "audio")],
        "data": {
            "takes": [serialize_take(take)],
            "song_id": song_id,
            "kind": "audio",
            "format": fmt,
            "duration": duration,
            "take_id": take["id"],
        },
    }
