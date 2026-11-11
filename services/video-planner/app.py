"""Story planner microservice for the Open Studio video component."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from mvstudio_shared.config import get_settings
from mvstudio_shared.models import (
    AISettings,
    AudioAnalysis,
    LyricsAnalysis,
    PlanResult,
    ProjectConfig,
)
from openstudio_common import create_service_app
from pydantic import BaseModel, Field

from .planner import StoryPlanner

logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("mvstudio.planner")

router = APIRouter(tags=["planning"])


class PlanRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=80)
    project_name: str = "Music Video"
    title: str = ""
    artist: str = ""
    audio_analysis: AudioAnalysis | None = None
    lyrics_analysis: LyricsAnalysis
    config: ProjectConfig = Field(default_factory=ProjectConfig)
    ai_settings: AISettings | None = None


@router.post("/plan", response_model=PlanResult)
def plan(request: PlanRequest) -> PlanResult:
    logger.info(
        "Planning project %s (%d lyric sections, %s mode)",
        request.project_id,
        len(request.lyrics_analysis.sections),
        request.config.ai.llm_mode,
    )
    try:
        result = StoryPlanner().plan(
            project_id=request.project_id,
            project_name=request.project_name,
            title=request.title,
            audio=request.audio_analysis,
            lyrics=request.lyrics_analysis,
            config=request.config,
            ai_settings=request.ai_settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        # Raised when an explicitly requested AI provider is unavailable and
        # fallback has been disabled in project settings.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Story planning failed")
        raise HTTPException(status_code=500, detail=f"Story planning failed: {exc}") from exc
    logger.info("Planned %d scenes using %s", len(result.scenes), result.planner)
    return result


app = create_service_app(
    "video-planner",
    "Open Studio Video Story Planner",
    "Structure-aware deterministic story planning with optional local Ollama enhancement.",
    extra_routers=[router],
)
