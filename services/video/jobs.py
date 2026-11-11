"""Persistent asynchronous job manager with cooperative pause/cancel."""

from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from mvstudio_shared.models import Job, JobKind, JobLog, JobStatus, utcnow
from mvstudio_shared.storage import ProjectStore, atomic_write_json, read_json

logger = logging.getLogger("mvstudio.video.jobs")

MAX_JOB_LOGS = 300


class JobCancelled(RuntimeError):
    pass


class JobConflict(RuntimeError):
    pass


class JobNotFound(RuntimeError):
    pass


class JobContext:
    def __init__(self, manager: "JobManager", job_id: str, control: "JobControl"):
        self.manager = manager
        self.job_id = job_id
        self.control = control

    def update(
        self,
        *,
        progress: float | None = None,
        stage: str | None = None,
        message: str | None = None,
        current_scene: int | None = None,
        scene_total: int | None = None,
        level: str = "info",
    ) -> None:
        self.manager.update(
            self.job_id,
            progress=progress,
            stage=stage,
            message=message,
            current_scene=current_scene,
            scene_total=scene_total,
            level=level,
        )

    def warn(self, message: str) -> None:
        self.manager.add_warning(self.job_id, message)

    def log(self, message: str, level: str = "info") -> None:
        self.manager.update(self.job_id, message=message, level=level)

    def checkpoint(self) -> None:
        self.control.checkpoint()


class JobControl:
    def __init__(self, manager: "JobManager", job_id: str):
        self.manager = manager
        self.job_id = job_id
        self._condition = threading.Condition()
        self._cancel = threading.Event()
        self._paused = False
        self._pause_transitioned = False

    def request_pause(self) -> None:
        with self._condition:
            self._paused = True
            self._condition.notify_all()

    def request_resume(self) -> None:
        with self._condition:
            self._paused = False
            if self._pause_transitioned:
                self.manager._set_running(self.job_id)
                self._pause_transitioned = False
            self._condition.notify_all()

    def request_cancel(self) -> None:
        self._cancel.set()
        with self._condition:
            self._condition.notify_all()

    @property
    def cancel_requested(self) -> bool:
        return self._cancel.is_set()

    def checkpoint(self) -> None:
        if self._cancel.is_set():
            raise JobCancelled()
        with self._condition:
            if self._paused:
                self._pause_transitioned = True
                self.manager._set_paused(self.job_id)
                while self._paused:
                    if self._cancel.is_set():
                        raise JobCancelled()
                    self._condition.wait(timeout=0.5)
                self._pause_transitioned = False
                if self._cancel.is_set():
                    raise JobCancelled()
                self.manager._set_running(self.job_id)


class JobManager:
    def __init__(
        self,
        store: ProjectStore,
        *,
        max_workers: int = 2,
        runner: Callable[[JobContext, Job], dict[str, Any]] | None = None,
    ):
        self.store = store
        self.runner = runner or (lambda context, job: {})
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="mvstudio-job")
        self._jobs: dict[str, Job] = {}
        self._controls: dict[str, JobControl] = {}
        self._active_projects: set[str] = set()
        self._lock = threading.RLock()
        self._shutdown = False

    # ------------------------------------------------------------------
    # Startup / persistence
    # ------------------------------------------------------------------
    def recover_interrupted_jobs(self) -> int:
        recovered = 0
        if not self.store.root.exists():
            return recovered
        for project_dir in self.store.root.iterdir():
            jobs_dir = project_dir / "logs" / "jobs"
            if not jobs_dir.is_dir():
                continue
            for job_file in jobs_dir.glob("*.json"):
                data = read_json(job_file)
                if not data:
                    continue
                try:
                    job = Job.model_validate(data)
                except Exception:
                    continue
                if job.status in {
                    JobStatus.queued,
                    JobStatus.running,
                    JobStatus.paused,
                    JobStatus.canceling,
                }:
                    job.status = JobStatus.interrupted
                    job.ended_at = utcnow()
                    job.error = (
                        "The gateway restarted before this job finished. Run the job again; "
                        "completed analysis and cached assets will be reused."
                    )
                    job.message = "Interrupted by gateway restart"
                    job.logs.append(
                        JobLog(level="warning", message=job.error)
                    )
                    atomic_write_json(job_file, job.model_dump(mode="json"))
                    try:
                        project = self.store.load(job.project_id)
                        if project.status == "processing":
                            project.status = "idle"
                            project.last_error = job.error
                            self.store.save(project)
                    except Exception:
                        pass
                    recovered += 1
        if recovered:
            logger.warning("Marked %d interrupted job(s) after restart", recovered)
        return recovered

    def _job_path(self, project_id: str, job_id: str) -> Path:
        return self.store.paths(project_id).jobs_dir / f"{job_id}.json"

    def _persist(self, job: Job) -> None:
        path = self._job_path(job.project_id, job.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, job.model_dump(mode="json"))

    def _append_project_log(self, job: Job, message: str, level: str) -> None:
        try:
            log_path = self.store.paths(job.project_id).logs_dir / "pipeline.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).isoformat()
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{timestamp} [{level.upper()}] [{job.id}] {message}\n")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                return job.model_copy(deep=True)
        # Fall back to disk after a restart.
        if self.store.root.exists():
            for project_dir in self.store.root.iterdir():
                job_file = project_dir / "logs" / "jobs" / f"{job_id}.json"
                if job_file.is_file():
                    data = read_json(job_file)
                    if data:
                        return Job.model_validate(data)
        raise JobNotFound(f"Job not found: {job_id}")

    def project_jobs(self, project_id: str, limit: int = 50) -> list[Job]:
        jobs: dict[str, Job] = {}
        try:
            jobs_dir = self.store.paths(project_id).jobs_dir
            if jobs_dir.is_dir():
                for job_file in jobs_dir.glob("*.json"):
                    data = read_json(job_file)
                    if not data:
                        continue
                    try:
                        job = Job.model_validate(data)
                        jobs[job.id] = job
                    except Exception:
                        continue
        except Exception:
            pass
        with self._lock:
            for job in self._jobs.values():
                if job.project_id == project_id:
                    jobs[job.id] = job.model_copy(deep=True)
        ordered = sorted(
            jobs.values(),
            key=lambda job: job.created_at,
            reverse=True,
        )
        return ordered[:limit]

    def active_jobs(self, project_id: str | None = None) -> list[Job]:
        with self._lock:
            jobs = [
                job.model_copy(deep=True)
                for job in self._jobs.values()
                if not job.is_terminal and (project_id is None or job.project_id == project_id)
            ]
        return jobs

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for job in self._jobs.values() if not job.is_terminal)

    # ------------------------------------------------------------------
    # Create / control
    # ------------------------------------------------------------------
    def create_job(
        self,
        project_id: str,
        kind: JobKind,
        options: dict[str, Any] | None = None,
    ) -> Job:
        project = self.store.load(project_id)
        with self._lock:
            if project_id in self._active_projects:
                raise JobConflict("Another job is already running for this project")
            job = Job(
                id="job_" + uuid.uuid4().hex[:14],
                project_id=project_id,
                kind=kind,
                status=JobStatus.queued,
                stage="queued",
                message="Waiting to start",
                options=options or {},
            )
            self._jobs[job.id] = job
            self._controls[job.id] = JobControl(self, job.id)
            self._active_projects.add(project_id)
            project.status = "processing"
            project.last_error = None
            self.store.save(project)
            self._persist(job)
            self._append_project_log(job, f"Job queued: {kind.value}", "info")
            control = self._controls[job.id]
        try:
            self.executor.submit(self._execute, job.id)
        except Exception:
            with self._lock:
                self._active_projects.discard(project_id)
            raise
        _ = control
        return job.model_copy(deep=True)

    def pause(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobNotFound(job_id)
            if job.is_terminal:
                raise JobConflict("The job has already finished")
            control = self._controls.get(job_id)
            if not control:
                raise JobConflict("The job is no longer controllable")
            job.pause_requested = True
            if job.status == JobStatus.paused:
                job.message = "Paused"
            else:
                job.message = "Pause requested; the current scene will finish first"
            self._append_log(job, job.message, "info")
            self._persist(job)
            self._append_project_log(job, job.message, "info")
            snapshot = job.model_copy(deep=True)
        # Never hold the manager lock while acquiring the control condition:
        # the runner acquires the condition and then calls back into the manager.
        control.request_pause()
        return snapshot

    def resume(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobNotFound(job_id)
            if job.is_terminal:
                raise JobConflict("The job has already finished")
            control = self._controls.get(job_id)
            if not control:
                raise JobConflict("The job is no longer controllable")
            job.pause_requested = False
            job.message = "Resuming"
            self._persist(job)
            self._append_project_log(job, "Job resumed", "info")
        control.request_resume()
        return self.get(job_id)

    def cancel(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobNotFound(job_id)
            if job.is_terminal:
                return job.model_copy(deep=True)
            control = self._controls.get(job_id)
            if not control:
                return job.model_copy(deep=True)
            job.cancel_requested = True
            job.status = JobStatus.canceling
            job.message = "Cancellation requested"
            self._append_log(job, job.message, "warning")
            self._persist(job)
            self._append_project_log(job, "Cancellation requested", "warning")
            snapshot = job.model_copy(deep=True)
        control.request_cancel()
        return snapshot

    def retry(self, job_id: str) -> Job:
        job = self.get(job_id)
        if not job.is_terminal:
            raise JobConflict("The original job is still running")
        return self.create_job(job.project_id, job.kind, dict(job.options))

    # ------------------------------------------------------------------
    # Internal state changes
    # ------------------------------------------------------------------
    def _append_log(self, job: Job, message: str, level: str) -> None:
        job.logs.append(JobLog(level=level, message=message, scene_id=job.current_scene))
        if len(job.logs) > MAX_JOB_LOGS:
            job.logs = job.logs[-MAX_JOB_LOGS:]

    def update(
        self,
        job_id: str,
        *,
        progress: float | None = None,
        stage: str | None = None,
        message: str | None = None,
        current_scene: int | None = None,
        scene_total: int | None = None,
        level: str = "info",
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            if job.cancel_requested and job.status not in {
                JobStatus.canceling,
                JobStatus.canceled,
                JobStatus.failed,
                JobStatus.interrupted,
            }:
                job.status = JobStatus.canceling
            if job.status not in {JobStatus.canceled, JobStatus.failed, JobStatus.interrupted, JobStatus.completed}:
                if progress is not None:
                    job.progress = round(max(job.progress, min(100.0, progress)), 1)
                if stage is not None:
                    job.stage = stage
                if message is not None:
                    job.message = message
                if current_scene is not None:
                    job.current_scene = current_scene
                if scene_total is not None:
                    job.scene_total = scene_total
                if message:
                    self._append_log(job, message, level)
                    if level in {"warning", "error"}:
                        self._append_project_log(job, message, level)
                self._persist(job)

    def _set_paused(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.is_terminal:
                return
            job.status = JobStatus.paused
            job.pause_requested = True
            job.message = "Paused"
            self._append_log(job, "Job paused", "info")
            self._persist(job)
            self._append_project_log(job, "Job paused", "info")

    def _set_running(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.is_terminal:
                return
            job.status = JobStatus.running
            job.pause_requested = False
            job.message = "Running"
            self._append_log(job, "Job resumed", "info")
            self._persist(job)

    def add_warning(self, job_id: str, message: str) -> None:
        message = message.strip()
        if not message:
            return
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            if message not in job.warnings:
                job.warnings.append(message)
                self._append_log(job, message, "warning")
                self._append_project_log(job, message, "warning")
                try:
                    project = self.store.load(job.project_id)
                    if message not in project.warnings:
                        project.warnings.append(message)
                        project.warnings = project.warnings[-40:]
                        self.store.save(project)
                except Exception:
                    pass
            self._persist(job)

    # ------------------------------------------------------------------
    # Runner
    # ------------------------------------------------------------------
    def _execute(self, job_id: str) -> None:
        control = self._controls[job_id]
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = JobStatus.running
            job.started_at = utcnow()
            job.progress = 0.0
            job.stage = "starting"
            job.message = "Starting"
            self._append_log(job, "Job started", "info")
            self._persist(job)
            self._append_project_log(job, "Job started", "info")
            job_snapshot = job.model_copy(deep=True)
        context = JobContext(self, job_id, control)
        try:
            control.checkpoint()
            result = self.runner(context, job_snapshot) or {}
            control.checkpoint()
            self._complete(job_id, result)
        except JobCancelled:
            self._cancel_finish(job_id)
        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            detail = str(exc) or exc.__class__.__name__
            self._fail(job_id, detail)

    def _complete(self, job_id: str, result: dict[str, Any]) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            if job.cancel_requested:
                self._cancel_finish(job_id)
                return
            job.status = JobStatus.completed
            job.progress = 100.0
            job.stage = "completed"
            job.message = str(result.get("message") or "Completed")
            job.ended_at = utcnow()
            job.result = result
            self._append_log(job, "Job completed", "info")
            self._persist(job)
            self._append_project_log(job, "Job completed", "info")
            project = self.store.load(job.project_id)
            project.status = "idle"
            project.last_error = None
            self.store.save(project)
            self._active_projects.discard(job.project_id)
            self._controls.pop(job_id, None)

    def _fail(self, job_id: str, detail: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = JobStatus.failed
            job.stage = "failed"
            job.message = detail
            job.error = detail
            job.ended_at = utcnow()
            self._append_log(job, f"Job failed: {detail}", "error")
            self._persist(job)
            self._append_project_log(job, f"Job failed: {detail}", "error")
            try:
                project = self.store.load(job.project_id)
                project.status = "error"
                project.last_error = detail
                self.store.save(project)
            except Exception:
                pass
            self._active_projects.discard(job.project_id)
            self._controls.pop(job_id, None)

    def _cancel_finish(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = JobStatus.canceled
            job.stage = "canceled"
            job.message = "Canceled"
            job.ended_at = utcnow()
            self._append_log(job, "Job canceled", "warning")
            self._persist(job)
            self._append_project_log(job, "Job canceled", "warning")
            try:
                project = self.store.load(job.project_id)
                project.status = "idle"
                project.last_error = "Job canceled"
                self.store.save(project)
            except Exception:
                pass
            self._active_projects.discard(job.project_id)
            self._controls.pop(job_id, None)

    def shutdown(self) -> None:
        self._shutdown = True
        for control in list(self._controls.values()):
            control.request_cancel()
        self.executor.shutdown(wait=False, cancel_futures=True)
