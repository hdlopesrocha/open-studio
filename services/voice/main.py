"""Open Studio voice service.

One Docker service with two TTS engines:

* ``omnivoice`` – cloning, design, auto mode and Whisper transcription.
* ``piper`` – fast built-in ONNX voices with sentence timelines.

All long operations are submitted to the central job hub. The documents
pipeline uses the synchronous ``POST /internal/tts`` endpoint instead.
"""

from __future__ import annotations

import io
import json
import logging
import os
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

import httpx
from fastapi import (
    APIRouter,
    Body,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response

from openstudio_common import (
    INTERNAL_TOKEN,
    JOBHUB_URL,
    JobRunner,
    create_service_app,
    env_bool,
    jobhub_headers,
    relative_path,
    remove_path,
    utc_now,
)

from . import audio
from .config import Settings
from .download_models import install_many
from .errors import VoiceError
from .jobs import register_handlers
from .languages import LANGUAGE_IDS, LANGUAGE_PAYLOAD, PORTUGUESE_VARIANT_IDS
from .model_manager import ModelManager
from .piper_engine import PiperEngine
from .runtime import VoiceRuntime
from .schemas import (
    BatchTTSRequest,
    OpenAISpeechRequest,
    PiperInstallRequest,
    PreviewRequest,
    TTSRequest,
    VoiceUpdate,
)
from .storage import (
    OutputStore,
    VoiceStore,
    public_output,
    public_voice,
)
from .voices import VOICES, language_matches

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("openstudio.voice")

STARTED = time.time()
OPENAI_VOICE_ALIASES = {
    "auto",
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "fable",
    "nova",
    "onyx",
    "sage",
    "shimmer",
    "verse",
}

settings = Settings.from_env()
voices = VoiceStore(settings.voices_dir)
outputs = OutputStore(settings.outputs_dir)
manager = ModelManager(settings)
piper = PiperEngine(settings)
runtime = VoiceRuntime(settings, voices, outputs, manager, piper)
runner = JobRunner("voice")
register_handlers(runner, runtime)


async def _startup() -> None:
    for path in (
        settings.voice_dir,
        settings.voices_dir,
        settings.outputs_dir,
        settings.uploads_dir,
        settings.piper_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
    # Only remove stale uploads. A service restart must not delete files that a
    # just-requeued job still needs.
    cutoff = time.time() - 24 * 3600
    for stale in settings.uploads_dir.glob("*"):
        try:
            if stale.is_file() and stale.stat().st_mtime < cutoff:
                stale.unlink(missing_ok=True)
        except OSError:
            pass
    manager.start_loading()
    logger.info(
        "Voice service ready: device=%s omnivoice_enabled=%s piper_dir=%s",
        settings.device,
        settings.omnivoice_enabled,
        settings.piper_dir,
    )


async def _shutdown() -> None:
    piper.unload()


def _health_payload() -> dict[str, Any]:
    omni = manager.health()
    installed = sum(1 for voice in VOICES if voice.available(settings.piper_dir))
    piper_health = piper.status(voices_installed=installed, voices_total=len(VOICES))
    status = omni.get("status", "error")
    message = omni.get("message") or ""
    if status == "error" and omni.get("error"):
        message = f"{message}: {omni['error']}" if message else str(omni["error"])
    if status == "unavailable":
        piper_note = (
            "Piper is available; select engine=piper to keep generating speech."
            if piper_health["available"]
            else "Piper is also unavailable in this image."
        )
        message = f"{message} {piper_note}".strip()
    return {
        "service": "voice",
        "status": status,
        "version": settings.app_version,
        "uptime_seconds": round(time.time() - STARTED, 1),
        "message": message,
        "engines": {"omnivoice": omni, "piper": piper_health},
        "piper_available": piper_health["available"],
        "piper_voices_installed": installed,
        "voices": len(voices.list_meta()),
        "outputs": outputs.count(),
    }


app = create_service_app(
    "voice",
    "Open Studio Voice",
    "One TTS service with OmniVoice cloning/design and fast Piper voices.",
    runner=runner,
    version=settings.app_version,
    on_startup=_startup,
    on_shutdown=_shutdown,
)

# Replace the generic liveness route with an engine-aware health payload. The
# shared app still owns /health; downstream monitors only need HTTP 200, while
# the UI can see that OmniVoice is unavailable and Piper still works.
app.router.routes = [
    route for route in app.router.routes if getattr(route, "path", None) != "/health"
]


@app.get("/health", tags=["system"])
async def health() -> dict[str, Any]:
    return _health_payload()


@app.exception_handler(VoiceError)
async def voice_error_handler(_request, exc: VoiceError):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


router = APIRouter(prefix="/api/voice", tags=["voice"])


# ── Helpers ────────────────────────────────────────────────────────────────


def _safe_suffix(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if 1 < len(suffix) <= 9 and suffix[1:].isalnum():
        return suffix
    return ".bin"


def _parse_tags(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass
    return [item.strip() for item in raw.split(",") if item.strip()]


def _validate_language(language: str | None) -> str | None:
    if language is None:
        return None
    language = language.strip()
    if not language:
        return None
    if language not in LANGUAGE_IDS and language not in PORTUGUESE_VARIANT_IDS:
        raise HTTPException(status_code=422, detail=f"Unknown language: {language}")
    return language


async def _save_upload(upload: UploadFile, max_bytes: int) -> Path:
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    target = settings.uploads_dir / f"{uuid.uuid4().hex}{_safe_suffix(upload.filename)}"
    total = 0
    try:
        with target.open("wb") as handle:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Upload is larger than {max_bytes // (1024 * 1024)} MB",
                    )
                handle.write(chunk)
        if total == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        return target
    except Exception:
        target.unlink(missing_ok=True)
        raise


def _cleanup_upload(path: Path | None) -> None:
    if path is not None:
        path.unlink(missing_ok=True)


async def _submit(action: str, title: str, params: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "component": "voice",
        "action": action,
        "title": title[:200],
        "params": params,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{JOBHUB_URL}/api/jobs",
                headers=jobhub_headers(),
                json=payload,
            )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Job hub unavailable: {exc}") from exc
    if response.status_code >= 400:
        detail = response.text[:2000]
        try:
            detail = response.json().get("detail", detail)
        except Exception:  # noqa: BLE001
            pass
        raise HTTPException(status_code=502, detail=f"Could not create job: {detail}")
    job = response.json()
    job.setdefault("job_id", job.get("id"))
    return job


def _validate_request_or_422(req: TTSRequest) -> None:
    try:
        runtime.validate_request(req)
    except VoiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _voice_or_404(voice_id: str) -> dict[str, Any]:
    try:
        return voices.get_meta(voice_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Voice not found") from exc


def _omnivoice_error_detail() -> str:
    return str(manager.error or manager.status_message or "OmniVoice is unavailable")


def _preview_inputs(voice_id: str, text: str | None) -> str | None:
    _voice_or_404(voice_id)
    if manager.status in {"unavailable", "error"}:
        raise HTTPException(status_code=503, detail=_omnivoice_error_detail())
    if not voices.prompt_path(voice_id).is_file():
        raise HTTPException(
            status_code=409,
            detail="This voice has no trained prompt. Retrain it first.",
        )
    if text is not None and not isinstance(text, str):
        raise HTTPException(status_code=422, detail="Preview text must be a string")
    if text is not None and len(text) > 300:
        raise HTTPException(status_code=422, detail="Preview text is limited to 300 characters")
    return (text or "").strip() or None


def _output_or_404(output_id: str) -> dict[str, Any]:
    try:
        return outputs.get_meta(output_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Output not found") from exc


# ── Catalog / health ───────────────────────────────────────────────────────


def _engine_catalog() -> list[dict[str, Any]]:
    omni = manager.health()
    installed = sum(1 for voice in VOICES if voice.available(settings.piper_dir))
    piper_health = piper.status(voices_installed=installed, voices_total=len(VOICES))
    return [
        {
            "id": "omnivoice",
            "name": "OmniVoice",
            "description": "Voice cloning, instructed design and auto voices with Whisper ASR.",
            "status": omni["status"],
            "available": omni["status"] in {"ok", "loading"},
            "model_loaded": omni["model_loaded"],
            "device": omni["device"],
            "modes": ["auto", "voice", "design"],
            "formats": list(audio.SUPPORTED_FORMATS),
            "transcribe": True,
            "message": omni["message"],
        },
        {
            "id": "piper",
            "name": "Piper",
            "description": "Fast local ONNX neural speech with built-in voices.",
            "status": piper_health["status"],
            "available": piper_health["available"],
            "models_dir": piper_health["models_dir"],
            "voices_total": len(VOICES),
            "voices_installed": installed,
            "modes": ["piper"],
            "formats": list(audio.PIPER_FORMATS),
            "pitch_supported": False,
            "transcribe": False,
        },
    ]


_ADVANCED_CONTROLS = [
    {"key": "num_step", "label": "Diffusion steps", "type": "int", "min": 1, "max": 128, "default": 32, "engine": "omnivoice"},
    {"key": "guidance_scale", "label": "Guidance scale", "type": "float", "min": 0, "max": 20, "step": 0.1, "default": 2.0, "engine": "omnivoice"},
    {"key": "t_shift", "label": "Time shift", "type": "float", "min": 0, "max": 10, "step": 0.01, "default": 0.1, "engine": "omnivoice"},
    {"key": "denoise", "label": "Denoise", "type": "bool", "default": True, "engine": "omnivoice"},
    {"key": "preprocess_prompt", "label": "Preprocess reference prompt", "type": "bool", "default": True, "engine": "omnivoice"},
    {"key": "postprocess_output", "label": "Postprocess output", "type": "bool", "default": True, "engine": "omnivoice"},
    {"key": "normalize_text", "label": "Normalize text", "type": "bool", "default": False, "engine": "omnivoice"},
    {"key": "position_temperature", "label": "Position temperature", "type": "float", "min": 0, "max": 100, "step": 0.1, "default": 5.0, "engine": "omnivoice"},
    {"key": "class_temperature", "label": "Class temperature", "type": "float", "min": 0, "max": 10, "step": 0.1, "default": 0.0, "engine": "omnivoice"},
    {"key": "layer_penalty_factor", "label": "Layer penalty", "type": "float", "min": 0, "max": 100, "step": 0.1, "default": 5.0, "engine": "omnivoice"},
    {"key": "pad_duration", "label": "Pad duration (s)", "type": "float", "min": 0, "max": 5, "step": 0.01, "default": 0.1, "engine": "omnivoice"},
    {"key": "fade_duration", "label": "Fade duration (s)", "type": "float", "min": 0, "max": 5, "step": 0.01, "default": 0.1, "engine": "omnivoice"},
    {"key": "audio_chunk_duration", "label": "Audio chunk duration (s)", "type": "float", "min": 0.1, "max": 120, "step": 0.1, "default": 15.0, "engine": "omnivoice"},
    {"key": "audio_chunk_threshold", "label": "Audio chunk threshold (s)", "type": "float", "min": 0, "max": 600, "step": 0.1, "default": 30.0, "engine": "omnivoice"},
    {"key": "duration", "label": "Fixed duration (s)", "type": "float", "min": 0.5, "max": 600, "step": 0.1, "default": None, "engine": "omnivoice"},
    {"key": "speed", "label": "Speed", "type": "float", "min": 0.25, "max": 4, "step": 0.05, "default": 1.0, "engine": "both"},
    {"key": "pitch", "label": "Pitch (semitones)", "type": "float", "min": -24, "max": 24, "step": 0.5, "default": 0, "engine": "piper", "note": "Rejected unless the voice declares support."},
    {"key": "normalize_audio", "label": "Normalize loudness", "type": "bool", "default": False, "engine": "both"},
    {"key": "seed", "label": "Seed", "type": "int", "min": 0, "max": 4_294_967_295, "default": None, "engine": "omnivoice"},
]


@router.get("/catalog")
async def catalog() -> dict[str, Any]:
    installed = sum(1 for voice in VOICES if voice.available(settings.piper_dir))
    piper_voices = [voice.public(settings.piper_dir) for voice in VOICES]
    trained = [public_voice(meta) for meta in voices.list_meta()]
    return {
        "service": "voice",
        "engines": _engine_catalog(),
        "voices": trained,
        "piper_voices": piper_voices,
        "voices_by_engine": {"omnivoice": trained, "piper": piper_voices},
        "languages": LANGUAGE_PAYLOAD["languages"],
        "popular_languages": LANGUAGE_PAYLOAD["popular"],
        "variants": LANGUAGE_PAYLOAD["variants"],
        "modes": [
            {"id": "auto", "name": "Auto", "engine": "omnivoice", "description": "Generate with a neutral automatic voice."},
            {"id": "voice", "name": "Cloned voice", "engine": "omnivoice", "description": "Use a trained reference profile."},
            {"id": "design", "name": "Voice design", "engine": "omnivoice", "description": "Describe the voice with an instruction."},
            {"id": "piper", "name": "Piper voice", "engine": "piper", "description": "Use a small built-in ONNX voice."},
        ],
        "formats": list(audio.SUPPORTED_FORMATS),
        "piper_formats": list(audio.PIPER_FORMATS),
        "batch_split_modes": ["blank-line", "line"],
        "limits": {
            "max_input_chars": settings.max_input_chars,
            "piper_max_text_chars": settings.piper_max_text_chars,
            "max_upload_mb": settings.max_upload_mb,
            "min_voice_seconds": settings.min_voice_seconds,
            "max_voice_seconds": settings.max_voice_seconds,
            "max_import_mb": settings.max_import_mb,
            "max_batch_items": settings.max_batch_items,
            "max_sentences": settings.max_sentences,
            "max_instruct_chars": 600,
            "max_preview_chars": 300,
            "sample_rate": 24_000,
        },
        "defaults": {
            "engine": "omnivoice",
            "mode": "auto",
            "voice_id": None,
            "piper_voice": settings.default_piper_voice,
            "instruct": None,
            "language": None,
            "language_variant": None,
            "speed": 1.0,
            "num_step": 32,
            "guidance_scale": 2.0,
            "t_shift": 0.1,
            "denoise": True,
            "preprocess_prompt": True,
            "postprocess_output": True,
            "seed": None,
            "format": "wav",
            "normalize_text": False,
            "pitch": 0.0,
            "normalize_audio": False,
        },
        "defaults_by_engine": {
            "omnivoice": {
                "mode": "auto",
                "format": "wav",
                "speed": 1.0,
                "num_step": 32,
                "guidance_scale": 2.0,
                "t_shift": 0.1,
            },
            "piper": {
                "piper_voice": settings.default_piper_voice,
                "format": "mp3",
                "speed": 1.0,
                "pitch": 0.0,
                "normalize_audio": False,
            },
        },
        "advanced_defaults": {
            "position_temperature": 5.0,
            "class_temperature": 0.0,
            "layer_penalty_factor": 5.0,
            "pad_duration": 0.1,
            "fade_duration": 0.1,
            "audio_chunk_duration": 15.0,
            "audio_chunk_threshold": 30.0,
            "duration": None,
        },
        "advanced": _ADVANCED_CONTROLS,
        "options": {
            "engines": ["omnivoice", "piper"],
            "speeds": {"omnivoice": [0.25, 4.0], "piper": [0.5, 2.0]},
            "languages": len(LANGUAGE_PAYLOAD["languages"]),
            "preview_text": settings.preview_text,
            "sentence_gap_ms": settings.sentence_gap_ms,
            "piper_voices_installed": installed,
        },
        "capabilities": {
            "clone": manager.status in {"ok", "loading"},
            "design": manager.status in {"ok", "loading"},
            "auto": manager.status in {"ok", "loading"},
            "transcribe": manager.status in {"ok", "loading"},
            "piper": piper.module_available(),
            "timeline": True,
            "srt": True,
            "batch": True,
            "openai_compatible": True,
            "internal_sync_tts": True,
            "job_actions": ["tts", "batch", "train", "preview", "transcribe"],
        },
        "health": {"omnivoice": manager.health(), "piper": piper.status(installed, len(VOICES))},
    }


@router.get("/health")
async def voice_health() -> dict[str, Any]:
    return _health_payload()


@router.get("/languages")
async def languages() -> dict[str, Any]:
    return LANGUAGE_PAYLOAD


# ── Voices ─────────────────────────────────────────────────────────────────


@router.get("/voices")
async def list_voices() -> dict[str, Any]:
    items = [public_voice(meta) for meta in voices.list_meta()]
    return {"items": items, "total": len(items), "voices": items}


@router.get("/voices/{voice_id}")
async def get_voice(voice_id: str) -> dict[str, Any]:
    return public_voice(_voice_or_404(voice_id))


@router.post("/voices", status_code=202)
async def create_voice(
    name: str = Form(..., max_length=60),
    audio_file: UploadFile = File(..., alias="audio"),
    transcript: str | None = Form(None),
    language: str | None = Form(None),
    consent: bool = Form(False),
    preprocess_prompt: bool = Form(True),
    description: str | None = Form(None),
    tags: str | None = Form(None),
) -> dict[str, Any]:
    return await _submit_train(
        name=name,
        language=language,
        transcript=transcript,
        transcript_provided=transcript is not None,
        upload=audio_file,
        voice_id=None,
        consent=consent,
        preprocess_prompt=preprocess_prompt,
        description=description,
        tags=tags,
    )


@router.post("/train", status_code=202)
async def train_voice(
    name: str = Form(..., max_length=60),
    audio_file: UploadFile = File(..., alias="audio"),
    transcript: str | None = Form(None),
    language: str | None = Form(None),
    consent: bool = Form(False),
    preprocess_prompt: bool = Form(True),
    description: str | None = Form(None),
    tags: str | None = Form(None),
) -> dict[str, Any]:
    return await _submit_train(
        name=name,
        language=language,
        transcript=transcript,
        transcript_provided=transcript is not None,
        upload=audio_file,
        voice_id=None,
        consent=consent,
        preprocess_prompt=preprocess_prompt,
        description=description,
        tags=tags,
    )


async def _submit_train(
    *,
    name: str,
    language: str | None,
    transcript: str | None,
    transcript_provided: bool,
    upload: UploadFile | None,
    voice_id: str | None,
    consent: bool,
    preprocess_prompt: bool,
    description: str | None,
    tags: str | None,
) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Voice name is required")
    if not consent:
        raise HTTPException(
            status_code=400,
            detail=(
                "Consent confirmation is required. Only clone voices you own or "
                "have explicit permission to use."
            ),
        )
    if manager.status in {"unavailable", "error"}:
        raise HTTPException(status_code=503, detail=_omnivoice_error_detail())
    language_value = _validate_language(language)
    temp_path: Path | None = None
    if upload is not None:
        temp_path = await _save_upload(upload, settings.max_upload_mb * 1024 * 1024)
    if upload is None and voice_id is None:
        raise HTTPException(status_code=400, detail="A reference audio file is required")

    try:
        params = {
            "name": name,
            "language": language_value,
            "transcript": (transcript or "").strip() or None,
            "transcript_provided": transcript_provided,
            "audio_path": relative_path(temp_path) if temp_path else None,
            "voice_id": voice_id,
            "consent": True,
            "preprocess_prompt": preprocess_prompt,
            "description": (description or "").strip() or None,
            "tags": _parse_tags(tags),
        }
        action = "train"
        title = f"Train voice · {name}"
        if voice_id:
            title = f"Retrain voice · {name}"
        return await _submit(action, title, params)
    except Exception:
        _cleanup_upload(temp_path)
        raise


@router.post("/voices/{voice_id}/retrain", status_code=202)
async def retrain_voice(
    voice_id: str,
    audio_file: UploadFile | None = File(None, alias="audio"),
    transcript: str | None = Form(None),
    language: str | None = Form(None),
    name: str | None = Form(None, max_length=60),
    consent: bool = Form(False),
    preprocess_prompt: bool = Form(True),
    description: str | None = Form(None),
    tags: str | None = Form(None),
) -> dict[str, Any]:
    meta = _voice_or_404(voice_id)
    if not consent:
        raise HTTPException(
            status_code=400,
            detail=(
                "Consent confirmation is required. Only clone voices you own or "
                "have explicit permission to use."
            ),
        )
    if (
        audio_file is None
        and transcript is None
        and language is None
        and name is None
        and description is None
        and tags is None
    ):
        raise HTTPException(
            status_code=400,
            detail="Provide new audio, a transcript, a language, a name, a description or tags",
        )
    new_name = (name or "").strip() if name is not None else None
    if name is not None and not new_name:
        raise HTTPException(status_code=400, detail="Voice name cannot be empty")
    retrain_name = new_name or str(meta.get("name") or "").strip() or "Voice"
    return await _submit_train(
        name=retrain_name,
        language=language,
        transcript=transcript,
        transcript_provided=transcript is not None,
        upload=audio_file,
        voice_id=voice_id,
        consent=consent,
        preprocess_prompt=preprocess_prompt,
        description=description,
        tags=tags,
    )


@router.patch("/voices/{voice_id}")
async def update_voice(voice_id: str, payload: VoiceUpdate) -> dict[str, Any]:
    meta = _voice_or_404(voice_id)
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes:
        if not changes["name"]:
            raise HTTPException(status_code=422, detail="Voice name cannot be empty")
        meta["name"] = changes["name"]
    if "language" in changes:
        meta["language"] = _validate_language(changes["language"])
    if "transcript" in changes:
        meta["transcript"] = changes["transcript"]
    if "description" in changes:
        meta["description"] = changes["description"]
    if "tags" in changes:
        meta["tags"] = changes["tags"] or []
    meta["updated_at"] = utc_now()
    voices.save_meta(voice_id, meta)
    return public_voice(meta)


@router.delete("/voices/{voice_id}")
async def delete_voice(voice_id: str) -> dict[str, Any]:
    _voice_or_404(voice_id)
    manager.invalidate_voice(voice_id)
    voices.delete(voice_id)
    return {"ok": True, "id": voice_id}


@router.get("/voices/{voice_id}/reference")
async def get_reference(voice_id: str, download: bool = Query(False)) -> FileResponse:
    _voice_or_404(voice_id)
    path = voices.reference_path(voice_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Reference audio not found")
    return FileResponse(
        path,
        media_type="audio/wav",
        filename=f"voice-{voice_id}-reference.wav" if download else None,
    )


@router.get("/voices/{voice_id}/preview")
async def get_preview(voice_id: str, download: bool = Query(False)) -> FileResponse:
    _voice_or_404(voice_id)
    path = voices.preview_path(voice_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Preview has not been generated")
    return FileResponse(
        path,
        media_type="audio/wav",
        filename=f"voice-{voice_id}-preview.wav" if download else None,
    )


@router.get("/voices/{voice_id}/export")
async def export_voice(voice_id: str) -> Response:
    meta = _voice_or_404(voice_id)
    reference = voices.reference_path(voice_id)
    prompt = voices.prompt_path(voice_id)
    if not reference.is_file() or not prompt.is_file():
        raise HTTPException(
            status_code=409,
            detail="Voice profile is incomplete and cannot be exported",
        )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
        archive.write(reference, arcname="reference.wav")
        archive.write(prompt, arcname="prompt.pt")
        preview = voices.preview_path(voice_id)
        if preview.is_file():
            archive.write(preview, arcname="preview.wav")
    buffer.seek(0)
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="openstudio-voice-{voice_id}.zip"'
        },
    )


@router.post("/voices/import", status_code=201)
async def import_voice(
    archive: UploadFile = File(...),
    consent: bool = Form(False),
) -> dict[str, Any]:
    max_import_bytes = settings.max_import_mb * 1024 * 1024
    data = await _read_upload_bytes(archive, max_import_bytes)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as bundle:
            uncompressed = sum(item.file_size for item in bundle.infolist())
            if uncompressed > max_import_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"Voice archive expands beyond {settings.max_import_mb} MB",
                )
            names = set(bundle.namelist())
            required = {"meta.json", "reference.wav", "prompt.pt"}
            if not required.issubset(names):
                raise HTTPException(
                    status_code=400,
                    detail="Voice archive must contain meta.json, reference.wav and prompt.pt",
                )
            meta = json.loads(bundle.read("meta.json"))
            if not isinstance(meta, dict):
                raise HTTPException(status_code=400, detail="meta.json must contain a JSON object")
            reference_bytes = bundle.read("reference.wav")
            prompt_bytes = bundle.read("prompt.pt")
            preview_bytes = bundle.read("preview.wav") if "preview.wav" in names else None
    except HTTPException:
        raise
    except (zipfile.BadZipFile, json.JSONDecodeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid voice archive: {exc}") from exc

    if not reference_bytes or not prompt_bytes:
        raise HTTPException(status_code=400, detail="Voice archive contains empty files")

    voice_id, directory = voices.create()
    try:
        reference = voices.reference_path(voice_id)
        reference.write_bytes(reference_bytes)
        duration = await run_in_threadpool(audio.probe_duration, reference)
        if duration < settings.min_voice_seconds:
            raise HTTPException(status_code=400, detail="Imported reference audio is too short")
        if duration > settings.max_voice_seconds:
            raise HTTPException(status_code=400, detail="Imported reference audio is too long")
        voices.prompt_path(voice_id).write_bytes(prompt_bytes)
        preview = voices.preview_path(voice_id)
        if preview_bytes:
            preview.write_bytes(preview_bytes)
        now = utc_now()
        name = str(meta.get("name") or "Imported voice").strip() or "Imported voice"
        imported = {
            **meta,
            "id": voice_id,
            "name": name,
            "duration_seconds": round(duration, 3),
            "sample_rate": 24_000,
            "created_at": now,
            "updated_at": now,
            "has_preview": bool(preview_bytes),
            "preview_updated_at": now if preview_bytes else None,
            "reference_filename": "reference.wav",
            "prompt_filename": "prompt.pt",
            "consent": bool(consent) or bool(meta.get("consent")),
        }
        voices.save_meta(voice_id, imported)
        return public_voice(imported)
    except HTTPException:
        remove_path(directory)
        raise
    except Exception as exc:  # noqa: BLE001
        remove_path(directory)
        logger.exception("Voice import failed")
        raise HTTPException(status_code=400, detail=f"Could not import voice profile: {exc}") from exc


async def _read_upload_bytes(upload: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Upload is larger than {max_bytes // (1024 * 1024)} MB",
            )
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    return b"".join(chunks)


# ── Preview / transcription jobs ───────────────────────────────────────────


@router.post("/preview", status_code=202)
async def submit_preview(payload: PreviewRequest) -> dict[str, Any]:
    _preview_inputs(payload.voice_id, payload.text)
    return await _submit(
        "preview",
        "Voice preview",
        {"voice_id": payload.voice_id, "text": payload.text},
    )


@router.post("/voices/{voice_id}/preview", status_code=202)
async def submit_voice_preview(
    voice_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    text: str | None = Query(None, max_length=300),
) -> dict[str, Any]:
    body_text = payload.get("text") if isinstance(payload, dict) else None
    resolved_text = body_text if body_text is not None else text
    _preview_inputs(voice_id, resolved_text)
    return await _submit(
        "preview",
        "Voice preview",
        {"voice_id": voice_id, "text": resolved_text},
    )


@router.post("/transcribe", status_code=202)
async def submit_transcribe(
    audio_file: UploadFile = File(..., alias="audio"),
) -> dict[str, Any]:
    if manager.status in {"unavailable", "error"}:
        raise HTTPException(status_code=503, detail=_omnivoice_error_detail())
    upload = await _save_upload(audio_file, settings.max_upload_mb * 1024 * 1024)
    try:
        return await _submit(
            "transcribe",
            f"Transcribe · {audio_file.filename or upload.name}",
            {"audio_path": relative_path(upload), "filename": audio_file.filename},
        )
    except Exception:
        _cleanup_upload(upload)
        raise


# ── TTS / batch ────────────────────────────────────────────────────────────


@router.post("/tts", status_code=202)
async def submit_tts(req: TTSRequest) -> dict[str, Any]:
    _validate_request_or_422(req)
    params = req.model_dump()
    title = f"Voice · {req.text[:70]}"
    return await _submit("tts", title, params)


@router.post("/batch", status_code=202)
async def submit_batch(req: BatchTTSRequest) -> dict[str, Any]:
    items = list(req.items or [])
    if not items:
        raise HTTPException(status_code=422, detail="At least one batch item is required")
    if len(items) > settings.max_batch_items:
        raise HTTPException(
            status_code=422,
            detail=f"Batch supports at most {settings.max_batch_items} items",
        )
    for item in items:
        _validate_request_or_422(req.to_tts_request(item))
    params = req.model_dump(exclude={"text", "texts", "split_mode"})
    params["items"] = items
    title = f"Voice batch · {len(items)} item(s)"
    return await _submit("batch", title, params)


# ── Piper ──────────────────────────────────────────────────────────────────


@router.get("/piper/voices")
async def piper_voices(language: str | None = Query(None, max_length=20)) -> dict[str, Any]:
    installed = sum(1 for voice in VOICES if voice.available(settings.piper_dir))
    items = [
        voice.public(settings.piper_dir)
        for voice in VOICES
        if language_matches(language, voice.language)
    ]
    return {
        "items": items,
        "total": len(items),
        "voices": items,
        "engines": _engine_catalog(),
        "default_voice": settings.default_piper_voice,
        "pitch_supported": False,
        "formats": list(audio.PIPER_FORMATS),
        "voices_total": len(VOICES),
        "voices_installed": installed,
        "models_dir": str(settings.piper_dir),
        "available": piper.module_available(),
    }


@router.post("/piper/install")
async def piper_install(payload: PiperInstallRequest) -> dict[str, Any]:
    ids: list[str] = []
    if payload.voice_id:
        ids.append(payload.voice_id)
    ids.extend(payload.voice_ids or [])
    # De-duplicate while preserving order.
    ids = list(dict.fromkeys(item for item in ids if item))
    if not ids:
        raise HTTPException(status_code=422, detail="Provide voice_id or voice_ids")
    try:
        installed = await run_in_threadpool(install_many, settings, ids, payload.force)
    except VoiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {
        "ok": True,
        "installed": True,
        "installed_voices": installed,
        "items": installed,
        "voices": [voice.public(settings.piper_dir) for voice in VOICES],
    }


# ── Outputs / history ──────────────────────────────────────────────────────


@router.get("/outputs")
async def list_outputs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    engine: str | None = Query(None, max_length=20),
) -> dict[str, Any]:
    items, total = outputs.list_meta(limit=limit, offset=offset, engine=engine)
    public = [public_output(meta) for meta in items]
    return {
        "items": public,
        "total": total,
        "limit": limit,
        "offset": offset,
        "outputs": public,
    }


@router.get("/outputs/{output_id}")
async def get_output(output_id: str, download: bool = Query(False)) -> FileResponse:
    meta = _output_or_404(output_id)
    try:
        path = outputs.audio_path(meta)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Output audio not found") from exc
    fmt = str(meta.get("format") or path.suffix.lstrip("."))
    return FileResponse(
        path,
        media_type=audio.MIME_TYPES.get(fmt, "application/octet-stream"),
        filename=f"openstudio-voice-{output_id}.{fmt}" if download else None,
    )


@router.get("/outputs/{output_id}/meta")
async def get_output_meta(output_id: str) -> dict[str, Any]:
    return public_output(_output_or_404(output_id), include_timeline=True)


@router.get("/outputs/{output_id}/timeline")
async def get_output_timeline(output_id: str) -> dict[str, Any]:
    meta = _output_or_404(output_id)
    return {
        "output_id": output_id,
        "duration_seconds": meta.get("duration_seconds", 0),
        "timeline": meta.get("timeline") or [],
        "format": meta.get("format"),
        "engine": meta.get("engine"),
    }


@router.delete("/outputs/{output_id}")
async def delete_output(output_id: str) -> dict[str, Any]:
    _output_or_404(output_id)
    outputs.delete(output_id)
    return {"ok": True, "id": output_id}


# ── OpenAI-compatible shim ─────────────────────────────────────────────────


@router.get("/v1/models")
async def openai_models() -> dict[str, Any]:
    now = int(time.time())
    data = [
        {"id": "omnivoice", "object": "model", "created": now, "owned_by": "local"},
        {"id": "piper", "object": "model", "created": now, "owned_by": "local"},
    ]
    data.extend(
        {
            "id": voice.id,
            "object": "model",
            "created": now,
            "owned_by": "local",
            "engine": "piper",
        }
        for voice in VOICES
    )
    return {"object": "list", "data": data}


@router.get("/v1/voices")
async def openai_voices() -> dict[str, Any]:
    data: list[dict[str, Any]] = []
    for meta in voices.list_meta():
        data.append(
            {
                "id": meta.get("id"),
                "name": meta.get("name"),
                "language": meta.get("language"),
                "duration_seconds": meta.get("duration_seconds"),
                "engine": "omnivoice",
            }
        )
    for voice in VOICES:
        data.append(
            {
                "id": voice.id,
                "name": voice.name,
                "language": voice.language,
                "engine": "piper",
                "available": voice.available(settings.piper_dir),
            }
        )
    return {"object": "list", "data": data}


def _resolve_openai_request(req: OpenAISpeechRequest) -> TTSRequest:
    voice_value = (req.voice or "auto").strip()
    voice_lower = voice_value.lower()
    model_lower = (req.model or "").strip().lower()
    engine = (req.engine or "").strip().lower()
    piper_voice: str | None = None
    voice_id: str | None = None
    mode = "auto"
    instruct = req.instruct
    style_instruct = req.style_instruct

    piper_match = next((v for v in VOICES if v.id.lower() == voice_lower), None)
    trained_match = None
    if piper_match is None:
        for meta in voices.list_meta():
            if (
                str(meta.get("id", "")).lower() == voice_lower
                or str(meta.get("name", "")).strip().lower() == voice_lower
            ):
                trained_match = meta
                break

    explicit_piper = (
        engine == "piper"
        or model_lower.startswith("piper")
        or model_lower in {v.id.lower() for v in VOICES}
    )

    if piper_match is not None:
        engine = "piper"
        piper_voice = piper_match.id
    elif explicit_piper:
        engine = "piper"
        piper_voice = voice_value if voice_lower not in OPENAI_VOICE_ALIASES else None
    elif trained_match is not None:
        engine = "omnivoice"
        mode = "voice"
        voice_id = str(trained_match["id"])
    elif voice_lower.startswith("design:"):
        engine = "omnivoice"
        mode = "design"
        instruct = voice_value.split(":", 1)[1].strip() or instruct
    else:
        # OpenAI aliases select OmniVoice auto mode. An arbitrary voice name is
        # treated as a voice-design instruction, matching the studio shim.
        engine = "omnivoice"
        if voice_lower in OPENAI_VOICE_ALIASES:
            mode = "auto"
        else:
            mode = "design"
            instruct = instruct or voice_value

    if engine not in {"omnivoice", "piper"}:
        engine = "omnivoice"

    return TTSRequest(
        engine=engine,  # type: ignore[arg-type]
        mode=mode,  # type: ignore[arg-type]
        voice_id=voice_id,
        piper_voice=piper_voice,
        instruct=instruct,
        style_instruct=style_instruct,
        language=req.language,
        language_variant=req.language_variant,
        speed=req.speed,
        seed=req.seed,
        pitch=req.pitch,
        format=req.response_format,
        normalize_text=req.normalize_text,
        normalize_audio=req.normalize_audio,
        text=req.input,
    )


@router.post("/v1/audio/speech")
async def openai_speech(req: OpenAISpeechRequest) -> Response:
    tts_req = _resolve_openai_request(req)
    _validate_request_or_422(tts_req)
    try:
        output = await runtime.synthesize(tts_req)
    except VoiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    path = outputs.audio_path(output)
    fmt = str(output.get("format") or req.response_format)
    return Response(
        content=path.read_bytes(),
        media_type=audio.MIME_TYPES.get(fmt, "application/octet-stream"),
        headers={
            "X-Output-Id": str(output.get("id")),
            "X-Audio-Duration": f"{float(output.get('duration_seconds') or 0):.3f}",
            "X-Generation-Seconds": f"{float(output.get('generation_seconds') or 0):.3f}",
            "X-RTF": (
                f"{float(output['rtf']):.4f}" if output.get("rtf") is not None else ""
            ),
            "Content-Disposition": f'inline; filename="openstudio-voice-{output.get("id")}.{fmt}"',
        },
    )


# ── Internal synchronous TTS for the documents pipeline ────────────────────


@app.post("/internal/tts")
async def internal_tts(
    payload: TTSRequest,
    x_internal_token: str = Header(default=""),
) -> dict[str, Any]:
    if x_internal_token != INTERNAL_TOKEN and env_bool("REQUIRE_INTERNAL_TOKEN", True):
        raise HTTPException(status_code=403, detail="Invalid internal token")
    _validate_request_or_422(payload)
    try:
        output = await runtime.synthesize(payload)
    except VoiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    public = public_output(output, include_timeline=True)
    return {
        "path": public.get("path"),
        "duration_seconds": public.get("duration_seconds", 0),
        "timeline": public.get("timeline") or [],
        "format": public.get("format"),
        "engine": public.get("engine"),
        "voice": public.get("voice"),
        "output_id": public.get("id"),
        "url": public.get("url"),
    }


app.include_router(router)
