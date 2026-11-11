"""WebSocket endpoints for live project and job progress updates."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder

from .jobs import JobNotFound

router = APIRouter(prefix="/api/video")


def _encode(payload: dict) -> str:
    return json.dumps(jsonable_encoder(payload), ensure_ascii=False, separators=(",", ":"))


@router.websocket("/ws/projects/{project_id}")
async def project_progress(websocket: WebSocket, project_id: str) -> None:
    await websocket.accept()
    store = websocket.app.state.store
    jobs = websocket.app.state.jobs
    try:
        project = store.load(project_id)
    except Exception:
        await websocket.close(code=4404, reason="Project not found")
        return
    last_payload = ""
    tick = 0
    try:
        while True:
            try:
                project = store.load(project_id)
            except Exception:
                await websocket.close(code=4404, reason="Project not found")
                return
            tick += 1
            # Active jobs are cheap; refresh the persisted job list less often.
            job_list = jobs.project_jobs(project_id, limit=10) if tick % 3 == 1 else jobs.active_jobs(project_id)
            if tick % 3 != 1 and not job_list:
                job_list = jobs.project_jobs(project_id, limit=3)
            payload = {
                "type": "snapshot" if tick == 1 else "update",
                "project": project.model_dump(mode="json"),
                "jobs": [job.model_dump(mode="json") for job in job_list],
                "active_jobs": jobs.active_count(),
                "server_time": datetime.now(timezone.utc).isoformat(),
            }
            encoded = _encode(payload)
            comparable = encoded.rsplit('"server_time"', 1)[0]
            if comparable != last_payload:
                await websocket.send_text(encoded)
                last_payload = comparable
            await asyncio.sleep(0.75)
    except WebSocketDisconnect:
        return
    except Exception:
        return


@router.websocket("/ws/jobs/{job_id}")
async def job_progress(websocket: WebSocket, job_id: str) -> None:
    await websocket.accept()
    jobs = websocket.app.state.jobs
    last_payload = ""
    try:
        while True:
            try:
                job = jobs.get(job_id)
            except JobNotFound:
                await websocket.close(code=4404, reason="Job not found")
                return
            payload = {
                "type": "snapshot",
                "job": job.model_dump(mode="json"),
                "server_time": datetime.now(timezone.utc).isoformat(),
            }
            encoded = _encode(payload)
            comparable = encoded.rsplit('"server_time"', 1)[0]
            if comparable != last_payload:
                await websocket.send_text(encoded)
                last_payload = comparable
            if job.is_terminal:
                await asyncio.sleep(0.5)
            await asyncio.sleep(0.75)
    except WebSocketDisconnect:
        return
    except Exception:
        return
