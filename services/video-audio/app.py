"""Audio analysis microservice for the Open Studio video component."""

from __future__ import annotations

import importlib.metadata
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from mvstudio_shared.config import get_settings
from mvstudio_shared.media import MediaError
from mvstudio_shared.models import AudioAnalysis
from mvstudio_shared.storage import ensure_within_roots
from openstudio_common import create_service_app
from pydantic import BaseModel, Field

from .analyzer import AudioAnalyzer

logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("mvstudio.audio")

router = APIRouter(tags=["analysis"])


class AnalyzeRequest(BaseModel):
    audio_path: str
    sample_rate: int = Field(default=22050, ge=8000, le=48000)
    min_section_seconds: float = Field(default=6.0, ge=2.0, le=30.0)
    max_sections: int = Field(default=24, ge=2, le=80)


def _resolve_audio(path: str) -> Path:
    settings = get_settings()
    candidate = Path(path)
    if not candidate.is_absolute():
        files_candidate = settings.files_root / path
        candidate = files_candidate if files_candidate.exists() else settings.projects_root / path
    return ensure_within_roots(candidate, (settings.projects_root,))


@router.get("/info")
def info() -> dict:
    try:
        librosa_version = importlib.metadata.version("librosa")
    except importlib.metadata.PackageNotFoundError:
        librosa_version = "unavailable"
    return {
        "service": "video-audio",
        "librosa": librosa_version,
        "ffmpeg": get_settings().ffmpeg,
    }


@router.post("/analyze", response_model=AudioAnalysis)
def analyze(request: AnalyzeRequest) -> AudioAnalysis:
    try:
        audio_path = _resolve_audio(request.audio_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not audio_path.is_file():
        raise HTTPException(status_code=404, detail=f"Audio file not found: {audio_path.name}")
    logger.info("Analysing %s", audio_path)
    try:
        result = AudioAnalyzer().analyze(
            audio_path,
            sample_rate=request.sample_rate,
            min_section_seconds=request.min_section_seconds,
            max_sections=request.max_sections,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MediaError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Audio analysis failed")
        raise HTTPException(status_code=500, detail=f"Audio analysis failed: {exc}") from exc
    logger.info(
        "Analysed %s: %.1fs, %.1f BPM, %d beats, %d sections",
        audio_path.name,
        result.duration,
        result.tempo,
        len(result.beats),
        len(result.sections),
    )
    return result


app = create_service_app(
    "video-audio",
    "Open Studio Video Audio Analysis",
    "Beat, tempo, band-energy and structural analysis for local music videos.",
    extra_routers=[router],
)
