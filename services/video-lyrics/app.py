"""Lyrics / SRT analysis microservice for the Open Studio video component."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from mvstudio_shared.config import get_settings
from mvstudio_shared.models import AudioAnalysis, LyricsAnalysis
from mvstudio_shared.storage import ensure_within_roots
from openstudio_common import create_service_app
from pydantic import BaseModel, Field

from .analyzer import LyricsAnalyzer

logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("mvstudio.lyrics")

router = APIRouter(tags=["analysis"])


class LyricsAnalyzeRequest(BaseModel):
    srt_path: str
    audio_analysis: AudioAnalysis | None = None
    gap_threshold: float = Field(default=6.0, ge=1.0, le=30.0)


def _resolve_srt(path: str) -> Path:
    settings = get_settings()
    candidate = Path(path)
    if not candidate.is_absolute():
        files_candidate = settings.files_root / path
        candidate = files_candidate if files_candidate.exists() else settings.projects_root / path
    return ensure_within_roots(candidate, (settings.projects_root,))


@router.post("/analyze", response_model=LyricsAnalysis)
def analyze(request: LyricsAnalyzeRequest) -> LyricsAnalysis:
    try:
        srt_path = _resolve_srt(request.srt_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not srt_path.is_file():
        raise HTTPException(status_code=404, detail=f"Subtitle file not found: {srt_path.name}")
    logger.info("Analysing lyrics %s", srt_path)
    try:
        result = LyricsAnalyzer().analyze(
            srt_path,
            audio_analysis=request.audio_analysis,
            gap_threshold=request.gap_threshold,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Lyrics analysis failed")
        raise HTTPException(status_code=500, detail=f"Lyrics analysis failed: {exc}") from exc
    logger.info(
        "Analysed lyrics: %d lines, %d sections, language=%s",
        len(result.lines),
        len(result.sections),
        result.language,
    )
    return result


app = create_service_app(
    "video-lyrics",
    "Open Studio Video Lyrics Analysis",
    "SRT parsing, lyric grouping, repetition detection and musical section association.",
    extra_routers=[router],
)
