"""FastAPI application for the Open Studio video orchestrator."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from fastapi.staticfiles import StaticFiles
from mvstudio_shared.config import get_settings
from mvstudio_shared.models import utcnow
from mvstudio_shared.storage import ProjectStore
from openstudio_common import JobRunner, create_service_app

from .clients import ServiceClient
from .jobs import JobManager
from .pipeline import build_runner
from .routes import router
from .runner import register_handlers
from .settings_store import AISettingsStore
from .system import collect_status
from .ws import router as ws_router

logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("mvstudio.video")


def create_app() -> Any:
    settings = get_settings()
    for directory in (
        settings.projects_root,
        settings.exports_root,
        settings.cache_root,
        settings.models_root,
        settings.config_root,
    ):
        Path(directory).mkdir(parents=True, exist_ok=True)

    store = ProjectStore(settings.projects_root)
    ai_store = AISettingsStore()
    client = ServiceClient()
    pipeline_runner = build_runner(store, client, ai_store)
    jobs = JobManager(store, max_workers=settings.max_concurrent_jobs, runner=pipeline_runner)

    runner = JobRunner("video")
    register_handlers(runner, jobs, None, store)

    async def on_startup() -> None:
        recovered = jobs.recover_interrupted_jobs()
        if recovered:
            logger.warning("Marked %d interrupted job(s) from a previous video session", recovered)
        logger.info(
            "Video orchestrator ready: projects=%s cache=%s exports=%s",
            settings.projects_root,
            settings.cache_root,
            settings.exports_root,
        )

    async def on_shutdown() -> None:
        jobs.shutdown()
        logger.info("Video orchestrator stopped")

    app = create_service_app(
        "video",
        "Open Studio Video API",
        (
            "Orchestrates audio analysis, lyric analysis, story planning, scene images, "
            "animation, subtitle rendering and FFmpeg export."
        ),
        runner=runner,
        extra_routers=[router, ws_router],
        on_startup=on_startup,
        on_shutdown=on_shutdown,
    )

    app.state.store = store
    app.state.ai_store = ai_store
    app.state.client = client
    app.state.jobs = jobs
    app.state.pipeline_runner = pipeline_runner
    app.state.started_at = time.time()
    app.state.gateway_started_iso = utcnow().isoformat()

    # Convenience for direct service browsing; the gateway exposes the same
    # files through /api/files/raw.
    app.mount(
        "/media/projects",
        StaticFiles(directory=str(settings.projects_root), follow_symlink=False),
        name="project-media",
    )

    @app.get("/api/video/health")
    async def video_health() -> dict[str, Any]:
        return {
            "service": "video",
            "status": "ok",
            "version": "1.0.0",
            "projects": len(store.list()),
            "active_jobs": jobs.active_count(),
        }

    @app.get("/api/video/info")
    async def video_info() -> dict[str, Any]:
        return collect_status(
            store=store,
            client=client,
            manager=jobs,
            ai_store=ai_store,
            started_at=app.state.started_at,
            uptime_seconds=time.time() - app.state.started_at,
        )

    return app


app = create_app()
