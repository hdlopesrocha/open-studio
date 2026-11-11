"""Open Studio AI subtitles service (routes and job handlers)."""

from __future__ import annotations

import asyncio
import logging
import math
import mimetypes
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from openstudio_common import (
    JobContext,
    JobRunner,
    atomic_write_text,
    create_service_app,
    env,
    env_int,
    file_info,
    guess_mime,
    relative_path,
    resolve_path,
    utc_now,
)

from .aligner import (
    align_lyrics,
    parse_lyric_lines,
    proportional_cues_from_lines,
    suggested_total_duration,
)
from .engine import (
    DEFAULT_MODEL,
    ENGINE,
    MODEL_SPECS,
    WHISPER_CACHE,
    canonical_model,
    ctranslate2_version,
    ffmpeg_info,
    gpu_info,
    imported,
    model_cached,
    resolve_compute_type,
    resolve_device,
)
from .formats import build_subtitles, enforce_gap, format_cues_for_result, parse_subtitles
from .languages import language_items, language_name
from .models import (
    AlignRequest,
    ConvertRequest,
    EstimateRequest,
    FromTextRequest,
    TranscribeRequest,
)
from .pipeline import (
    cues_from_segments,
    default_convert_path,
    output_directory,
    probe_duration,
    read_text_input,
    resolve_input_path,
    resolve_output_path,
    run_whisper,
    safe_stem,
    style_from_request,
    submit_job,
    translate_output,
    unique_warnings,
    write_subtitle_outputs,
)
from .translation import TRANSLATION_URL

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("srt")

VERSION = "1.0.0"
router = APIRouter(prefix="/api/srt", tags=["subtitles"])
runner = JobRunner("srt")

REALTIME_FACTORS = {
    "tiny": 0.07,
    "tiny.en": 0.07,
    "base": 0.13,
    "base.en": 0.13,
    "small": 0.30,
    "small.en": 0.30,
    "medium": 0.78,
    "medium.en": 0.78,
    "large-v1": 1.70,
    "large-v2": 1.60,
    "large-v3": 1.55,
    "large": 1.55,
    "distil-large-v3": 0.45,
    "distil-large-v2": 0.42,
    "distil-medium.en": 0.28,
    "distil-small.en": 0.13,
}


def model_catalog() -> list[dict[str, Any]]:
    gpu = gpu_info()
    recommended = "large-v3" if gpu.get("available") else "small"
    items: list[dict[str, Any]] = []
    for spec in MODEL_SPECS:
        item = dict(spec)
        item["downloaded"] = model_cached(spec["id"])
        item["recommended"] = spec["id"] == recommended
        item["languages"] = ["en"] if not spec["multilingual"] else "multilingual"
        items.append(item)
    return items


@router.get("/catalog")
async def catalog() -> dict[str, Any]:
    gpu = gpu_info()
    ffmpeg = ffmpeg_info()
    return {
        "service": "srt",
        "version": VERSION,
        "engine": {
            "name": "faster-whisper",
            "available": imported(),
            "ctranslate2_version": ctranslate2_version(),
            "device": resolve_device(),
            "compute_type": resolve_compute_type(resolve_device()),
            "cache_dir": str(WHISPER_CACHE),
            "loaded_models": ENGINE.loaded_models(),
        },
        "models": model_catalog(),
        "languages": [{"code": "auto", "name": "Auto-detect"}, *language_items()],
        "tasks": [
            {"id": "transcribe", "name": "Transcribe", "description": "Keep the spoken language."},
            {"id": "translate", "name": "Translate to English", "description": "Whisper speech translation."},
        ],
        "output_formats": ["srt", "vtt", "ass"],
        "defaults": {
            "model": DEFAULT_MODEL,
            "language": None,
            "task": "transcribe",
            "beam_size": 5,
            "best_of": 5,
            "patience": 1.0,
            "temperature": 0.0,
            "word_timestamps": False,
            "vad_filter": False,
            "condition_on_previous_text": False,
            "output_format": "srt",
            "translate_to": None,
            "max_line_chars": 42,
            "max_lines": 2,
            "segment_gap": 0.06,
        },
        "limits": {
            "max_line_chars": {"min": 0, "max": 200},
            "max_lines": {"min": 1, "max": 6},
            "beam_size": {"min": 1, "max": 20},
            "batch_audio_minutes": env_int("SRT_MAX_AUDIO_MINUTES", 360),
        },
        "translation": {
            "url": TRANSLATION_URL,
            "link": "/api/translate/languages",
            "param": "translate_to",
            "description": "Optional translation of the finished cues; original files are always kept.",
        },
        "gpu": gpu,
        "ffmpeg": ffmpeg,
        "capabilities": {
            "transcribe": True,
            "align_lyrics": True,
            "from_text": True,
            "convert": True,
            "word_timestamps": True,
            "lrc_lyrics": True,
            "translation": True,
            "engine_installed": imported(),
        },
    }


@router.get("/models")
async def models() -> dict[str, Any]:
    items = model_catalog()
    return {
        "items": items,
        "total": len(items),
        "default": DEFAULT_MODEL,
        "device": resolve_device(),
        "gpu": gpu_info(),
    }


@router.get("/languages")
async def languages() -> dict[str, Any]:
    items = [{"code": "auto", "name": "Auto-detect"}, *language_items()]
    return {"items": items, "total": len(items)}


# ---------------------------------------------------------------------------
# Job actions
# ---------------------------------------------------------------------------


@runner.action("transcribe")
async def job_transcribe(ctx: JobContext) -> dict[str, Any]:
    request = TranscribeRequest.model_validate(ctx.params)
    audio = resolve_input_path(request.audio_path, label="audio")
    await ctx.check()
    await ctx.report(1.0, "Preparing", f"Inspecting {audio.name}…")
    probed_duration = await probe_duration(audio)
    segments, audio_info, model_info, warnings = await run_whisper(
        ctx,
        audio,
        request,
        force_words=False,
        duration=probed_duration,
    )
    duration = float(probed_duration or audio_info.get("duration") or 0.0)
    if not duration and segments:
        duration = float(segments[-1].get("end") or 0.0)
    cues = cues_from_segments(segments, request, duration=duration or None)
    if not cues:
        raise HTTPException(
            status_code=422,
            detail="Whisper produced no subtitle cues. The audio may be silent or use an unsupported language.",
        )
    detected = audio_info.get("language") or request.language
    if request.language is None and audio_info.get("language_probability", 1.0) < 0.45:
        warnings.append(
            f"Language detection confidence is low ({audio_info.get('language_probability', 0):.0%}); "
            "set the language explicitly for better results."
        )
    output_language = "en" if request.task == "translate" else detected
    await ctx.report(86.0, "Building cues", f"Built {len(cues)} cue(s).")
    translations, target_language = await translate_output(ctx, cues, request, warnings)
    directory = output_directory(ctx.job_id)
    stem = safe_stem(request.title, audio.stem)
    await ctx.report(96.0, "Writing files", "Writing SRT, VTT, ASS and metadata…")
    return await write_subtitle_outputs(
        ctx,
        cues=cues,
        directory=directory,
        stem=stem,
        title=request.title or audio.stem,
        language=output_language,
        duration=duration,
        options=request,
        warnings=warnings,
        model_info=model_info,
        translations=translations,
        translation_language=target_language,
        audio_path=relative_path(audio),
        message=f"Transcribed {duration:.1f}s with {model_info.get('model', request.model)}.",
        extra={
            "task": request.task,
            "audio": audio_info,
            "detected_language": detected,
            "detected_language_name": language_name(detected),
            "segment_count": len(segments),
        },
    )


@runner.action("align")
async def job_align(ctx: JobContext) -> dict[str, Any]:
    request = AlignRequest.model_validate(ctx.params)
    audio = resolve_input_path(request.audio_path, label="audio")
    lyrics = read_text_input(request.lyrics, request.lyrics_path, label="lyrics")
    lyric_lines = parse_lyric_lines(lyrics)
    if not lyric_lines:
        raise HTTPException(status_code=422, detail="No lyric lines were found in the supplied lyrics.")
    bias_warning: list[str] = []
    if request.task != "transcribe":
        bias_warning.append(
            "Lyric alignment always transcribes the source language so words match the lyrics; "
            "use translate_to for translated subtitle files."
        )
        request.task = "transcribe"
    if request.use_lyrics_bias and not request.initial_prompt:
        sample = " / ".join(line.text for line in lyric_lines[:6])
        if sample:
            request.initial_prompt = sample[:800]
            bias_warning.append("Used the first lyric lines as an initial prompt to bias recognition.")
    await ctx.check()
    await ctx.report(1.0, "Preparing", f"Aligning {len(lyric_lines)} lyric line(s) to {audio.name}…")
    probed_duration = await probe_duration(audio)
    segments, audio_info, model_info, warnings = await run_whisper(
        ctx,
        audio,
        request,
        force_words=True,
        duration=probed_duration,
    )
    warnings.extend(bias_warning)
    duration = float(probed_duration or audio_info.get("duration") or 0.0)
    if not duration and segments:
        duration = float(segments[-1].get("end") or 0.0)
    duration = max(0.1, duration)
    await ctx.report(84.0, "Aligning lyrics", "Matching lyric tokens to transcript words…")
    cues, stats = align_lyrics(
        lyrics,
        segments,
        duration,
        max_line_chars=request.max_line_chars,
        max_lines=request.max_lines,
        segment_gap=request.segment_gap,
        instrumental_gap=request.instrumental_gap,
    )
    if not cues:
        raise HTTPException(status_code=422, detail="Lyric alignment produced no cues.")
    warnings.extend(stats.warnings)
    detected = audio_info.get("language") or request.language
    await ctx.report(89.0, "Alignment complete", f"Aligned {stats.anchored_lines}/{stats.lines} line(s).")
    translations, target_language = await translate_output(ctx, cues, request, warnings)
    directory = output_directory(ctx.job_id)
    stem = safe_stem(request.title, audio.stem, "-lyrics")
    await ctx.report(96.0, "Writing files", "Writing aligned lyric subtitles…")
    alignment_payload = dict(stats.as_dict())
    alignment_payload["lyric_lines"] = len(lyric_lines)
    return await write_subtitle_outputs(
        ctx,
        cues=cues,
        directory=directory,
        stem=stem,
        title=request.title or f"{audio.stem} lyrics",
        language=detected,
        duration=duration,
        options=request,
        warnings=warnings,
        model_info=model_info,
        stats=stats,
        translations=translations,
        translation_language=target_language,
        audio_path=relative_path(audio),
        message=(
            f"Aligned {len(cues)} cue(s) from {len(lyric_lines)} lyric line(s); "
            f"{stats.matched_ratio * 100:.0f}% token match."
        ),
        extra={
            "task": request.task,
            "audio": audio_info,
            "alignment": alignment_payload,
            "detected_language": detected,
            "detected_language_name": language_name(detected),
            "segment_count": len(segments),
            "lyrics_path": request.lyrics_path,
        },
    )


@runner.action("from_text")
async def job_from_text(ctx: JobContext) -> dict[str, Any]:
    request = FromTextRequest.model_validate(ctx.params)
    text = read_text_input(request.text, request.text_path, label="text")
    await ctx.check()
    await ctx.report(5.0, "Preparing", "Estimating cue timings from text…")
    probed_duration: float | None = None
    audio: Path | None = None
    if request.audio_path:
        audio = resolve_input_path(request.audio_path, label="audio")
        probed_duration = await probe_duration(audio)
    warnings: list[str] = []
    duration = probed_duration or request.duration
    window_start = float(request.start or 0.0)
    window_end = float(request.end) if request.end is not None else None
    if window_end is None:
        if duration:
            window_end = float(duration)
        else:
            suggested = suggested_total_duration(text, words_per_minute=request.words_per_minute)
            duration = suggested or 30.0
            window_end = window_start + duration
            warnings.append(
                "No audio duration was supplied; cue times were estimated from the text length. "
                "Pass an audio file or duration for accurate sync."
            )
    if window_end <= window_start:
        raise HTTPException(status_code=422, detail="The end time must be greater than the start time.")
    cues = proportional_cues_from_lines(
        text,
        window_end,
        start=window_start,
        end=window_end,
        max_line_chars=request.max_line_chars,
        max_lines=request.max_lines,
        gap=request.segment_gap,
        words_per_minute=request.words_per_minute,
    )
    if not cues:
        raise HTTPException(status_code=422, detail="No cue text was found.")
    duration = float(duration or window_end)
    await ctx.report(72.0, "Timing estimated", f"Estimated {len(cues)} cue(s).")
    translations, target_language = await translate_output(ctx, cues, request, warnings)
    directory = output_directory(ctx.job_id)
    stem = safe_stem(request.title, "text-subtitles", "-text")
    await ctx.report(96.0, "Writing files", "Writing SRT, VTT and ASS…")
    return await write_subtitle_outputs(
        ctx,
        cues=cues,
        directory=directory,
        stem=stem,
        title=request.title or "Text subtitles",
        language=None,
        duration=duration,
        options=request,
        warnings=warnings,
        translations=translations,
        translation_language=target_language,
        audio_path=relative_path(audio) if audio else None,
        message=f"Estimated {len(cues)} cue(s) from text.",
        extra={
            "mode": "from_text",
            "word_count": len(text.split()),
            "window": {"start": round(window_start, 3), "end": round(window_end, 3)},
            "words_per_minute": request.words_per_minute,
        },
    )


# ---------------------------------------------------------------------------
# Synchronous endpoints
# ---------------------------------------------------------------------------


@router.post("/convert")
async def convert(request: ConvertRequest) -> dict[str, Any]:
    target = request.target_format
    if target not in {"srt", "vtt", "ass"}:
        raise HTTPException(status_code=422, detail="output_format must be srt, vtt or ass")
    source_format = request.source_format
    cues: list[dict[str, Any]]
    source_path: Path | None = None
    if request.cues:
        raw_cues = request.cues
        cues = enforce_gap(
            [
                {
                    "start": cue.get("start", 0.0),
                    "end": cue.get("end", cue.get("start", 0.0)),
                    "text": str(cue.get("text", "")),
                }
                for cue in raw_cues
            ],
            gap=0.0,
            duration=None,
            min_duration=0.2,
        )
        source_format = source_format if source_format != "auto" else "cues"
    else:
        text = request.content
        if not text:
            source_path = resolve_input_path(request.path or "", label="subtitle")
            text = read_text_input(None, str(source_path), label="subtitle")
            if source_format == "auto":
                suffix = source_path.suffix.lower().lstrip(".")
                if suffix in {"srt", "vtt", "ass"}:
                    source_format = suffix  # type: ignore[assignment]
        if not text or not text.strip():
            raise HTTPException(status_code=422, detail="The subtitle input is empty.")
        try:
            cues = parse_subtitles(text, source_format)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Could not parse subtitles: {exc}") from exc
        cues = enforce_gap(cues, gap=0.0, duration=None, min_duration=0.2)
    if not cues:
        raise HTTPException(status_code=422, detail="No cues were found in the input.")
    style = style_from_request(request)
    try:
        content = build_subtitles(cues, target, title=request.title, style=style)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    cue_payload = format_cues_for_result(cues)
    saved_path: Path | None = None
    if request.output_path:
        saved_path = resolve_output_path(request.output_path, target)
    elif request.save:
        saved_path = default_convert_path(request.title or "subtitles", target)
    if saved_path:
        atomic_write_text(saved_path, content)
    response: dict[str, Any] = {
        "format": target,
        "source_format": source_format,
        "content": content,
        "cues": cue_payload,
        "count": len(cue_payload),
        "title": request.title,
        "saved": saved_path is not None,
        "path": relative_path(saved_path) if saved_path else None,
        "filename": saved_path.name if saved_path else None,
        "mime": guess_mime(saved_path) if saved_path else mimetypes.types_map.get(f".{target}", "text/plain"),
        "created_at": utc_now(),
    }
    if saved_path:
        response["file"] = file_info(saved_path)
    return response


@router.post("/estimate")
async def estimate(request: EstimateRequest) -> dict[str, Any]:
    warnings: list[str] = []
    duration = float(request.duration or 0.0)
    if request.audio_path:
        audio = resolve_input_path(request.audio_path, label="audio")
        probed = await probe_duration(audio)
        if probed:
            duration = probed
        else:
            warnings.append("Could not read the audio duration; the estimate assumes the supplied duration.")
    text_lines = 0
    word_count = 0
    if request.text and request.text.strip():
        lines = parse_lyric_lines(request.text)
        text_lines = len(lines)
        word_count = len(request.text.split())
        if not duration:
            duration = suggested_total_duration(request.text)
            warnings.append("Estimated duration from the supplied text. Pass an audio file or duration for accuracy.")
    if duration <= 0:
        raise HTTPException(status_code=422, detail="Provide audio_path, duration or enough text to estimate.")
    model = canonical_model(request.model)
    device = request.device if request.device != "auto" else resolve_device()
    compute = resolve_compute_type(device)
    gpu_available = gpu_info().get("available", False) if device == "cuda" else False
    if device == "cuda" and not gpu_available:
        warnings.append("CUDA was requested but no GPU is visible; the estimate uses CPU speed.")
        device = "cpu"
        compute = resolve_compute_type(device)
    base_factor = REALTIME_FACTORS.get(model, 0.6)
    factor = base_factor if device == "cpu" else max(0.035, base_factor / 9.0)
    if request.word_timestamps:
        factor *= 1.18
    if request.task == "translate":
        factor *= 1.12
    estimated = duration * factor + 2.5
    spec = next((item for item in MODEL_SPECS if item["id"] == model), None)
    cached = model_cached(model)
    download_seconds = 0.0
    if not cached and spec:
        download_seconds = round(float(spec["disk_mb"]) / 20.0, 1)
    estimated_cues = max(1, math.ceil(duration / 2.8))
    if text_lines:
        estimated_cues = min(estimated_cues, text_lines)
    if duration > 1800 and device == "cpu" and model in {"medium", "large-v3", "large-v2", "large-v1"}:
        warnings.append(
            "This is a long recording on CPU with a large model. Consider small/base for a draft, "
            "or large-v3 on a GPU for final lyrics."
        )
    return {
        "audio_path": request.audio_path,
        "duration": round(duration, 3),
        "model": model,
        "device": device,
        "compute_type": compute,
        "task": request.task,
        "realtime_factor": round(factor, 4),
        "estimated_seconds": round(estimated + download_seconds, 1),
        "estimated_processing_seconds": round(estimated, 1),
        "model_cached": cached,
        "download_required": not cached,
        "download_estimate_seconds": download_seconds,
        "estimated_cue_count": estimated_cues,
        "estimated_word_count": round(duration * 2.6) if duration else word_count,
        "text_line_count": text_lines,
        "text_word_count": word_count,
        "warnings": warnings,
        "note": "Estimates vary with CPU, GPU, audio noise and language.",
    }


# ---------------------------------------------------------------------------
# Job submission endpoints
# ---------------------------------------------------------------------------


@router.post("/transcribe")
async def submit_transcribe(request: TranscribeRequest) -> dict[str, Any]:
    resolve_input_path(request.audio_path, label="audio")
    stem = Path(request.audio_path).stem
    title = request.title or f"Transcribe {stem}"
    params = request.model_dump(mode="json", exclude_none=True)
    return await submit_job("transcribe", title, params)


@router.post("/align")
async def submit_align(request: AlignRequest) -> dict[str, Any]:
    resolve_input_path(request.audio_path, label="audio")
    if request.lyrics_path:
        resolve_input_path(request.lyrics_path, label="lyrics")
    stem = Path(request.audio_path).stem
    title = request.title or f"Align lyrics · {stem}"
    params = request.model_dump(mode="json", exclude_none=True)
    return await submit_job("align", title, params)


@router.post("/from-text")
async def submit_from_text(request: FromTextRequest) -> dict[str, Any]:
    if request.text_path:
        resolve_input_path(request.text_path, label="text")
    if request.audio_path:
        resolve_input_path(request.audio_path, label="audio")
    title = request.title or "Subtitles from text"
    params = request.model_dump(mode="json", exclude_none=True)
    return await submit_job("from_text", title, params)


async def _startup() -> None:
    WHISPER_CACHE.mkdir(parents=True, exist_ok=True)
    preload = env("WHISPER_PRELOAD_MODEL", "").strip()
    if preload:
        log.info("Preloading Whisper model %s…", preload)
        try:
            await asyncio.to_thread(ENGINE.load, preload)
        except Exception:  # noqa: BLE001
            log.warning("Whisper preload failed; continuing with lazy loading", exc_info=True)
    log.info("SRT service ready (faster-whisper installed=%s, device=%s)", imported(), resolve_device())


app = create_service_app(
    "srt",
    "Open Studio Subtitles",
    "Whisper transcription, lyric alignment, subtitle conversion and optional translation.",
    runner=runner,
    version=VERSION,
    extra_routers=[router],
    on_startup=_startup,
)
