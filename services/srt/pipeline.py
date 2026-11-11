"""Shared job pipeline for transcription, alignment and subtitle output."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException
from pydantic import BaseModel

from openstudio_common import (
    FILES_ROOT,
    JOBHUB_URL,
    JobContext,
    atomic_write_json,
    atomic_write_text,
    ffprobe,
    file_info,
    jobhub_headers,
    resolve_path,
    relative_path,
    sanitize_name,
    timestamp_slug,
    utc_now,
)

from .aligner import AlignStats
from .engine import ENGINE, WhisperEngine, canonical_model
from .formats import build_subtitles, enforce_gap, format_cues_for_result, split_text_for_cues
from .models import WhisperOptions
from .translation import translate_cues

log = logging.getLogger("srt.pipeline")

JOB_COMPONENT = "srt"
VAD_KEYS = {
    "threshold",
    "neg_threshold",
    "min_speech_duration_ms",
    "max_speech_duration_s",
    "min_silence_duration_ms",
    "speech_pad_ms",
    "min_silence_at_max_speech",
    "use_max_poss_sil",
}


# ---------------------------------------------------------------------------
# Paths and media
# ---------------------------------------------------------------------------


def resolve_input_path(value: str, *, label: str = "file", must_exist: bool = True) -> Path:
    raw = (value or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail=f"A {label} path is required")
    candidate = Path(raw)
    if candidate.is_absolute():
        resolved = candidate.expanduser().resolve()
        root = FILES_ROOT.resolve()
        if resolved != root and root not in resolved.parents:
            raise HTTPException(
                status_code=400,
                detail=f"The {label} path must live under the shared files root ({FILES_ROOT})",
            )
        path = resolved
    else:
        path = resolve_path(raw)
    if must_exist and not path.is_file():
        raise HTTPException(status_code=404, detail=f"{label.capitalize()} not found: {raw}")
    return path


def read_text_input(value: str | None, path_value: str | None, *, label: str) -> str:
    if value and value.strip():
        return value
    if path_value:
        path = resolve_input_path(path_value, label=label)
        if path.stat().st_size > 50 * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"{label.capitalize()} file is too large (50 MB limit)")
        try:
            return path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            return path.read_text(encoding="utf-8", errors="replace")
    raise HTTPException(status_code=422, detail=f"Provide {label} text or path")


async def probe_duration(path: Path) -> float | None:
    try:
        info = await ffprobe(path)
        duration = info.get("duration")
        return float(duration) if duration else None
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not probe %s: %s", path, exc)
        return None


def safe_stem(title: str | None, fallback: str, suffix: str = "") -> str:
    base = sanitize_name(title or fallback, "subtitles")[:90]
    if base.lower().endswith((".srt", ".vtt", ".ass")):
        base = base.rsplit(".", 1)[0]
    stem = f"{base}{suffix}"
    return sanitize_name(stem, "subtitles")[:120]


def ensure_suffix(value: str, fmt: str) -> str:
    lower = value.lower()
    if lower.endswith(f".{fmt}"):
        return value
    if lower.endswith((".srt", ".vtt", ".ass")):
        return value.rsplit(".", 1)[0] + f".{fmt}"
    return f"{value}.{fmt}"


def resolve_output_path(value: str, fmt: str) -> Path:
    raw = ensure_suffix(value.strip(), fmt)
    candidate = Path(raw)
    if candidate.is_absolute():
        resolved = candidate.expanduser().resolve()
        root = FILES_ROOT.resolve()
        if resolved != root and root not in resolved.parents:
            raise HTTPException(status_code=400, detail="Output path must live under the shared files root")
        path = resolved
    else:
        path = resolve_path(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def default_convert_path(stem: str, fmt: str) -> Path:
    return resolve_path("subtitles", "converted", f"{timestamp_slug()}-{sanitize_name(stem)}.{fmt}")


def output_directory(job_id: str) -> Path:
    directory = resolve_path("subtitles", sanitize_name(job_id, "job"))
    directory.mkdir(parents=True, exist_ok=True)
    return directory


# ---------------------------------------------------------------------------
# Whisper execution
# ---------------------------------------------------------------------------


def whisper_kwargs(options: WhisperOptions, *, force_words: bool = False) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    language = None
    if options.language:
        language = options.language.replace("_", "-").split("-")[0].lower()
    vad_parameters: dict[str, Any] | None = None
    if options.vad_parameters:
        vad_parameters = {key: value for key, value in options.vad_parameters.items() if key in VAD_KEYS}
        unknown = sorted(set(options.vad_parameters) - VAD_KEYS)
        if unknown:
            warnings.append("Ignored unknown VAD parameter(s): " + ", ".join(unknown))
    kwargs: dict[str, Any] = {
        "language": language,
        "task": options.task,
        "beam_size": options.beam_size,
        "best_of": options.best_of,
        "patience": options.patience,
        "temperature": options.temperature,
        "compression_ratio_threshold": options.compression_ratio_threshold,
        "log_prob_threshold": options.log_prob_threshold,
        "no_speech_threshold": options.no_speech_threshold,
        "condition_on_previous_text": options.condition_on_previous_text,
        "initial_prompt": options.initial_prompt,
        "vad_filter": options.vad_filter,
        "word_timestamps": bool(force_words or options.word_timestamps),
        "prepend_punctuations": options.prepend_punctuations,
        "append_punctuations": options.append_punctuations,
    }
    if vad_parameters:
        kwargs["vad_parameters"] = vad_parameters
    return kwargs, warnings


def segment_to_dict(segment: Any) -> dict[str, Any]:
    raw_words = getattr(segment, "words", None) or []
    words: list[dict[str, Any]] = []
    for word in raw_words:
        start = getattr(word, "start", None)
        end = getattr(word, "end", None)
        probability = getattr(word, "probability", None)
        words.append(
            {
                "word": str(getattr(word, "word", "") or "").strip(),
                "start": round(float(start), 3) if start is not None else None,
                "end": round(float(end), 3) if end is not None else None,
                "probability": round(float(probability), 4) if probability is not None else None,
            }
        )
    temperature = getattr(segment, "temperature", None)
    compression = getattr(segment, "compression_ratio", None)
    avg_logprob = getattr(segment, "avg_logprob", None)
    no_speech = getattr(segment, "no_speech_prob", None)
    return {
        "id": getattr(segment, "id", None),
        "seek": getattr(segment, "seek", None),
        "start": round(float(getattr(segment, "start", 0.0) or 0.0), 3),
        "end": round(float(getattr(segment, "end", 0.0) or 0.0), 3),
        "text": str(getattr(segment, "text", "") or "").strip(),
        "avg_logprob": round(float(avg_logprob), 4) if avg_logprob is not None else None,
        "compression_ratio": round(float(compression), 4) if compression is not None else None,
        "no_speech_prob": round(float(no_speech), 4) if no_speech is not None else None,
        "temperature": float(temperature) if temperature is not None else None,
        "words": words,
    }


def _next_segment(iterator: Any) -> dict[str, Any] | None:
    try:
        return next(iterator)
    except StopIteration:
        return None


async def run_whisper(
    ctx: JobContext,
    audio: Path,
    options: WhisperOptions,
    *,
    force_words: bool,
    duration: float | None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], list[str]]:
    """Run faster-whisper and stream progress/cancellation between segments."""
    kwargs, warnings = whisper_kwargs(options, force_words=force_words)
    model_name = canonical_model(options.model)
    device_hint = options.device if options.device != "auto" else "auto"
    await ctx.report(3.0, "Loading model", f"Loading Whisper {model_name} ({device_hint})…")
    model, model_info = await asyncio.to_thread(
        ENGINE.load,
        model_name,
        device=None if options.device == "auto" else options.device,
        compute_type=options.compute_type,
    )
    warnings.extend(model_info.get("warnings") or [])
    await ctx.report(
        8.0,
        "Transcribing",
        f"Whisper {model_info['model']} on {model_info['device']} ({model_info['compute_type']}).",
    )
    await ctx.check()
    iterator, audio_info = await asyncio.to_thread(model.transcribe, str(audio), **kwargs)
    segments: list[dict[str, Any]] = []
    started = time.monotonic()
    last_progress = 0.0
    last_message = 0.0
    while True:
        await ctx.check()
        segment = await asyncio.to_thread(_next_segment, iterator)
        if segment is None:
            break
        payload = segment_to_dict(segment)
        segments.append(payload)
        now = time.monotonic()
        if duration and duration > 0 and now - last_progress >= 0.4:
            percent = 8.0 + min(77.0, (payload["end"] / duration) * 77.0)
            await ctx.report(percent, "Transcribing", f"Processed {payload['end']:.1f}s of {duration:.1f}s")
            last_progress = now
        elif now - last_message >= 6.0:
            await ctx.report(message=f"Transcribed {len(segments)} segment(s)…")
            last_message = now
    audio_payload = {
        "language": getattr(audio_info, "language", None),
        "language_probability": round(float(getattr(audio_info, "language_probability", 0.0) or 0.0), 4),
        "duration": round(float(getattr(audio_info, "duration", 0.0) or 0.0), 3) or duration,
        "duration_after_vad": round(float(getattr(audio_info, "duration_after_vad", 0.0) or 0.0), 3),
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }
    if not segments:
        warnings.append("Whisper did not detect any speech in this audio.")
    return segments, audio_payload, model_info, warnings


def cues_from_segments(
    segments: list[dict[str, Any]],
    options: WhisperOptions,
    *,
    duration: float | None,
) -> list[dict[str, Any]]:
    cues: list[dict[str, Any]] = []
    for segment_index, segment in enumerate(segments, start=1):
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        chunks = split_text_for_cues(
            text,
            max_line_chars=options.max_line_chars,
            max_lines=options.max_lines,
        )
        if not chunks:
            continue
        start = float(segment.get("start") or 0.0)
        end = max(start + 0.05, float(segment.get("end") or start + 0.05))
        confidence = None
        if segment.get("avg_logprob") is not None:
            confidence = round(max(0.0, min(1.0, math.exp(float(segment["avg_logprob"])))), 3)
        if len(chunks) == 1:
            cues.append(
                {
                    "start": start,
                    "end": end,
                    "text": chunks[0],
                    "confidence": confidence,
                    "source_line": segment_index,
                }
            )
            continue
        from .formats import cue_weight, distribute_window

        weights = [cue_weight(chunk) for chunk in chunks]
        times = distribute_window(start, end, weights, gap=0.04, min_duration=0.3)
        for chunk, (chunk_start, chunk_end) in zip(chunks, times):
            cues.append(
                {
                    "start": chunk_start,
                    "end": chunk_end,
                    "text": chunk,
                    "confidence": confidence,
                    "source_line": segment_index,
                }
            )
    return enforce_gap(cues, gap=options.segment_gap, duration=duration, min_duration=0.25)


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------


def unique_warnings(warnings: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in warnings if item and item.strip()))


def _artifact(path: Path, *, role: str, **extra: Any) -> dict[str, Any]:
    info = file_info(path)
    info["role"] = role
    info.update(extra)
    return info


async def write_subtitle_outputs(
    ctx: JobContext,
    *,
    cues: list[dict[str, Any]],
    directory: Path,
    stem: str,
    title: str,
    language: str | None,
    duration: float,
    options: BaseModel,
    warnings: list[str],
    model_info: dict[str, Any] | None = None,
    stats: AlignStats | dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
    translations: list[str] | None = None,
    translation_language: str | None = None,
    audio_path: str | None = None,
    message: str = "Subtitles ready.",
    ass_style: dict[str, Any] | None = None,
) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    params = options.model_dump(mode="json", exclude_none=True)
    cue_payload = format_cues_for_result(cues)
    all_warnings = unique_warnings(warnings)
    files_map: dict[str, str] = {}
    artifacts: list[dict[str, Any]] = []

    for fmt in ("srt", "vtt", "ass"):
        try:
            content = build_subtitles(cues, fmt, title=title, style=ass_style)
            path = directory / f"{stem}.{fmt}"
            atomic_write_text(path, content)
            relative = relative_path(path)
            files_map[fmt] = relative
            artifact = _artifact(path, role="subtitle", format=fmt, language=language)
            artifacts.append(artifact)
            await ctx.client.artifact(artifact)
        except Exception as exc:  # noqa: BLE001
            all_warnings.append(f"Could not write {fmt.upper()} output: {exc}")

    cues_path = directory / f"{stem}.cues.json"
    atomic_write_json(cues_path, {"language": language, "duration": duration, "cues": cue_payload})
    cues_relative = relative_path(cues_path)
    files_map["cues"] = cues_relative
    cues_artifact = _artifact(cues_path, role="cues", format="json")
    artifacts.append(cues_artifact)
    await ctx.client.artifact(cues_artifact)

    translated_payload: list[dict[str, Any]] | None = None
    translated_files: dict[str, str] = {}
    if translations:
        target = (translation_language or "translated").strip() or "translated"
        translated_cues = []
        for index, cue in enumerate(cues):
            translated = translations[index] if index < len(translations) else ""
            translated_cues.append(
                {
                    "index": index + 1,
                    "start": float(cue.get("start", 0.0)),
                    "end": float(cue.get("end", 0.0)),
                    "text": translated or str(cue.get("text", "")),
                    "original_text": str(cue.get("text", "")),
                }
            )
        translated_payload = format_cues_for_result(translated_cues)
        safe_language = re.sub(r"[^A-Za-z0-9_-]+", "", target)[:16] or "translated"
        for fmt in ("srt", "vtt", "ass"):
            try:
                content = build_subtitles(translated_cues, fmt, title=f"{title} ({target})", style=ass_style)
                path = directory / f"{stem}.{safe_language}.{fmt}"
                atomic_write_text(path, content)
                relative = relative_path(path)
                translated_files[fmt] = relative
                artifact = _artifact(path, role="translated", format=fmt, language=safe_language)
                artifacts.append(artifact)
                await ctx.client.artifact(artifact)
            except Exception as exc:  # noqa: BLE001
                all_warnings.append(f"Could not write translated {fmt.upper()} output: {exc}")

    stats_payload: dict[str, Any]
    if isinstance(stats, AlignStats):
        stats_payload = stats.as_dict()
    elif stats:
        stats_payload = dict(stats)
    else:
        stats_payload = {}
    stats_payload = json.loads(json.dumps(stats_payload, default=str))

    data: dict[str, Any] = {
        "title": title,
        "cues": cue_payload,
        "language": language,
        "duration": round(float(duration or 0.0), 3),
        "warnings": all_warnings,
        "files": files_map,
        "output_format": getattr(options, "output_format", None),
        "model": model_info or {},
        "stats": stats_payload,
        "audio_path": audio_path,
        "cue_count": len(cue_payload),
        "created_at": utc_now(),
    }
    if extra:
        data.update(extra)
    if translated_payload is not None:
        data["translated_cues"] = translated_payload
        data["translation"] = {
            "target_language": translation_language,
            "files": translated_files,
            "cue_count": len(translated_payload),
        }
        files_map["translated"] = translated_files

    metadata = {
        "version": 1,
        "kind": "openstudio.srt.metadata",
        "created_at": utc_now(),
        "title": title,
        "language": language,
        "duration": round(float(duration or 0.0), 3),
        "cue_count": len(cue_payload),
        "files": files_map,
        "warnings": all_warnings,
        "params": params,
        "model": model_info or {},
        "stats": stats_payload,
        "cues": cue_payload,
    }
    metadata_path = directory / f"{stem}.metadata.json"
    atomic_write_json(metadata_path, metadata)
    files_map["metadata"] = relative_path(metadata_path)
    metadata_artifact = _artifact(metadata_path, role="metadata", format="json")
    artifacts.append(metadata_artifact)
    await ctx.client.artifact(metadata_artifact)

    return {"message": message, "files": artifacts, "data": data}


# ---------------------------------------------------------------------------
# Translation and job submission
# ---------------------------------------------------------------------------


async def translate_output(
    ctx: JobContext,
    cues: list[dict[str, Any]],
    options: BaseModel,
    warnings: list[str],
) -> tuple[list[str], str | None]:
    target = getattr(options, "translate_to", None)
    if not target:
        return [], None
    await ctx.check()
    await ctx.report(88.0, "Translating", f"Translating {len(cues)} cue(s) to {target}…")
    language = getattr(options, "language", None)
    translations, translation_warnings = await translate_cues(
        cues,
        target,
        source_language=language,
        model=getattr(options, "translation_model", None),
    )
    warnings.extend(translation_warnings)
    if not translations:
        return [], target
    await ctx.report(94.0, "Translating", f"Translated {len(translations)} cue(s).")
    return translations, target


async def submit_job(action: str, title: str, params: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "component": JOB_COMPONENT,
        "action": action,
        "title": title[:200],
        "params": params,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
            response = await client.post(
                f"{JOBHUB_URL}/api/jobs",
                json=payload,
                headers=jobhub_headers(),
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Job hub is unavailable: {exc}") from exc
    if response.status_code >= 400:
        detail = response.text[:1000]
        try:
            detail = response.json().get("detail", detail)
        except Exception:  # noqa: BLE001
            pass
        raise HTTPException(status_code=502, detail=f"Could not create job: {detail}")
    return response.json()


def style_from_request(request: Any) -> dict[str, Any]:
    style: dict[str, Any] = dict(getattr(request, "style", None) or {})
    fields = (
        "font_name",
        "font_size",
        "primary_color",
        "secondary_color",
        "outline_color",
        "back_color",
        "bold",
        "italic",
        "border_style",
        "outline",
        "shadow",
        "alignment",
        "margin_l",
        "margin_r",
        "margin_v",
        "play_res_x",
        "play_res_y",
    )
    for field in fields:
        value = getattr(request, field, None)
        if value is not None:
            style[field] = value
    return style


__all__ = [
    "cues_from_segments",
    "default_convert_path",
    "ensure_suffix",
    "output_directory",
    "probe_duration",
    "read_text_input",
    "resolve_input_path",
    "resolve_output_path",
    "run_whisper",
    "safe_stem",
    "segment_to_dict",
    "style_from_request",
    "submit_job",
    "translate_output",
    "unique_warnings",
    "whisper_kwargs",
    "write_subtitle_outputs",
]
