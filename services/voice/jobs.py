"""Job hub handlers for the voice component.

Public submit routes create a job in the central hub. The hub calls back into
``/internal/jobs/run`` and these handlers do the actual work while reporting
progress and checking cancellation at segment boundaries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from openstudio_common import (
    JobContext,
    JobRunner,
    guess_mime,
    kind_of,
    relative_path,
    resolve_path,
)

from . import audio
from .errors import VoiceError
from .runtime import VoiceRuntime
from .schemas import BatchTTSRequest, TTSRequest
from .storage import public_output, public_voice


def _validation_error(exc: ValidationError) -> HTTPException:
    errors = exc.errors()
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.get("loc", ()))
        message = first.get("msg", "Invalid request")
        detail = f"{location}: {message}" if location else message
    else:  # pragma: no cover
        detail = str(exc)
    return HTTPException(status_code=422, detail=detail)


def _file_entry(path: Path, kind: str = "audio", name: str | None = None) -> dict[str, Any]:
    suffix = path.suffix.lower().lstrip(".")
    mime = audio.MIME_TYPES.get(suffix) or guess_mime(path)
    return {
        "path": relative_path(path),
        "kind": kind_of(path) if kind == "audio" else kind,
        "mime": mime,
        "name": name or path.name,
        "size": path.stat().st_size,
    }


def _resolve_audio(params: dict[str, Any], key: str = "audio_path") -> Path | None:
    raw = params.get(key)
    if raw is None or str(raw).strip() == "":
        return None
    path = resolve_path(str(raw))
    if not path.is_file():
        raise HTTPException(status_code=422, detail="Uploaded audio file was not found")
    return path


def _cleanup_upload(path: Path | None) -> None:
    if path is None:
        return
    try:
        rel = relative_path(path)
    except ValueError:
        return
    if rel.startswith("voice/uploads/"):
        path.unlink(missing_ok=True)


def _output_data(output: dict[str, Any]) -> dict[str, Any]:
    public = public_output(output, include_timeline=True)
    return {
        "output": public,
        "output_id": public.get("id"),
        "path": public.get("path"),
        "duration_seconds": public.get("duration_seconds"),
        "timeline": public.get("timeline") or [],
        "format": public.get("format"),
        "engine": public.get("engine"),
        "voice": public.get("voice"),
    }


def register_handlers(runner: JobRunner, runtime: VoiceRuntime) -> None:
    async def reporter(ctx: JobContext):
        async def report(progress: float, stage: str, message: str | None = None) -> None:
            await ctx.report(progress, stage, message)

        return report

    @runner.action("tts")
    async def run_tts(ctx: JobContext) -> dict[str, Any]:
        try:
            req = TTSRequest.model_validate(ctx.params)
        except ValidationError as exc:
            raise _validation_error(exc) from exc
        try:
            output = await runtime.synthesize(
                req,
                reporter=await reporter(ctx),
                checker=ctx.check,
            )
        except VoiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        public = public_output(output, include_timeline=True)
        audio_path = resolve_path(public["path"])
        return {
            "message": "Speech generation complete.",
            "files": [_file_entry(audio_path)],
            "data": _output_data(output),
        }

    @runner.action("batch")
    async def run_batch(ctx: JobContext) -> dict[str, Any]:
        try:
            req = BatchTTSRequest.model_validate(ctx.params)
        except ValidationError as exc:
            raise _validation_error(exc) from exc
        try:
            outputs = await runtime.synthesize_batch(
                req,
                reporter=await reporter(ctx),
                checker=ctx.check,
            )
        except VoiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        files: list[dict[str, Any]] = []
        items: list[dict[str, Any]] = []
        for output in outputs:
            public = public_output(output, include_timeline=True)
            items.append(public)
            path = resolve_path(public["path"])
            files.append(_file_entry(path))
        return {
            "message": f"Batch complete: {len(items)} item(s).",
            "files": files,
            "data": {"items": items, "count": len(items)},
        }

    @runner.action("train")
    async def run_train(ctx: JobContext) -> dict[str, Any]:
        params = ctx.params or {}
        upload = _resolve_audio(params)
        completed = False
        try:
            meta = await runtime.train_voice(
                name=str(params.get("name") or ""),
                language=params.get("language"),
                transcript=params.get("transcript"),
                transcript_provided=bool(params.get("transcript_provided", False)),
                audio_path=upload,
                voice_id=params.get("voice_id"),
                preprocess_prompt=bool(params.get("preprocess_prompt", True)),
                consent=bool(params.get("consent", False)),
                description=params.get("description"),
                tags=params.get("tags"),
                reporter=await reporter(ctx),
                checker=ctx.check,
            )
            completed = True
        except VoiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        finally:
            # Keep uploads for failed/cancelled jobs so a hub retry can run.
            if completed:
                _cleanup_upload(upload)
        voice = public_voice(meta)
        files: list[dict[str, Any]] = []
        reference = runtime.voices.reference_path(meta["id"])
        if reference.is_file():
            files.append(_file_entry(reference))
        return {
            "message": "Voice profile ready.",
            "files": files,
            "data": {"voice": voice, "voice_id": meta["id"]},
        }

    @runner.action("preview")
    async def run_preview(ctx: JobContext) -> dict[str, Any]:
        params = ctx.params or {}
        voice_id = str(params.get("voice_id") or "")
        try:
            result = await runtime.generate_preview(
                voice_id=voice_id,
                text=params.get("text"),
                reporter=await reporter(ctx),
                checker=ctx.check,
            )
        except VoiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        files: list[dict[str, Any]] = []
        preview = runtime.voices.preview_path(voice_id)
        if preview.is_file():
            files.append(_file_entry(preview))
        return {
            "message": "Voice preview ready.",
            "files": files,
            "data": result,
        }

    @runner.action("transcribe")
    async def run_transcribe(ctx: JobContext) -> dict[str, Any]:
        upload = _resolve_audio(ctx.params or {})
        if upload is None:
            raise HTTPException(status_code=422, detail="audio_path is required")
        completed = False
        try:
            result = await runtime.transcribe_audio(
                upload,
                reporter=await reporter(ctx),
                checker=ctx.check,
            )
            completed = True
        except VoiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        finally:
            # Keep uploads for failed/cancelled jobs so a hub retry can run.
            if completed:
                _cleanup_upload(upload)
        return {
            "message": "Transcription complete.",
            "files": [],
            "data": {"text": result.get("text", ""), "filename": result.get("filename")},
        }
