"""Video renderer microservice."""

from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, HTTPException
from mvstudio_shared.config import get_settings
from mvstudio_shared.models import OutputConfig, Scene, SubtitleStyle
from openstudio_common import create_service_app
from pydantic import BaseModel, Field

from .assembler import RenderError, render_project_video

logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("mvstudio.renderer")

router = APIRouter(tags=["render"])

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _project_lock(project_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(project_id, threading.Lock())


class RenderRequest(BaseModel):
    project_id: str
    scenes: list[Scene] = Field(min_length=1)
    audio_path: str
    subtitle_path: str
    output: OutputConfig = Field(default_factory=OutputConfig)
    subtitle_style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    title: str = ""


@router.post("/render")
def render(request: RenderRequest) -> dict:
    lock = _project_lock(request.project_id)
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A render is already running for this project")
    try:
        result = render_project_video(
            project_id=request.project_id,
            scenes=request.scenes,
            audio_path=request.audio_path,
            subtitle_path=request.subtitle_path,
            output=request.output,
            subtitle_style=request.subtitle_style,
            title=request.title,
        )
    except RenderError as exc:
        logger.exception("Render failed")
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Render failed")
        raise HTTPException(status_code=500, detail=f"Render failed: {exc}") from exc
    finally:
        lock.release()
    logger.info("Render complete: %s", result.get("video_path"))
    return result


app = create_service_app(
    "video-renderer",
    "Open Studio Video Renderer",
    "Assemble animated scenes, music, transitions and subtitles with FFmpeg.",
    extra_routers=[router],
)
