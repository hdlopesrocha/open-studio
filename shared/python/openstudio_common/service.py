"""Reusable FastAPI plumbing shared by all Open Studio micro-services."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import INTERNAL_TOKEN, SERVICE_NAME, ensure_dirs, env_bool
from .jobs import CancellationRegistry, JobCancelled, JobContext, JobClient
from .storage import ensure_storage

log = logging.getLogger("openstudio.service")

JobHandler = Callable[[JobContext], Awaitable[dict[str, Any]]]


class JobRunner:
    """Registry mapping a component action to an async handler."""

    def __init__(self, component: str) -> None:
        self.component = component
        self.handlers: dict[str, JobHandler] = {}
        self.registry = CancellationRegistry()

    def action(self, name: str) -> Callable[[JobHandler], JobHandler]:
        def decorator(fn: JobHandler) -> JobHandler:
            self.handlers[name] = fn
            return fn

        return decorator

    def register(self, name: str, fn: JobHandler) -> None:
        self.handlers[name] = fn

    def internal_router(self) -> APIRouter:
        router = APIRouter(prefix="/internal", tags=["internal"])

        @router.post("/jobs/run")
        async def run_job(payload: dict[str, Any], x_internal_token: str = Header(default="")) -> dict[str, Any]:
            if x_internal_token != INTERNAL_TOKEN:
                raise HTTPException(status_code=403, detail="Invalid internal token")
            action = payload.get("action") or ""
            job_id = payload.get("job_id") or ""
            params = payload.get("params") or {}
            handler = self.handlers.get(action)
            if handler is None:
                raise HTTPException(status_code=422, detail=f"Unknown action '{action}' for {self.component}")
            if not job_id:
                raise HTTPException(status_code=422, detail="job_id is required")
            await self.registry.register(job_id)
            client = JobClient(job_id)
            ctx = JobContext(job_id=job_id, action=action, params=params, client=client, registry=self.registry)
            try:
                result = await handler(ctx)
                return {"result": result or {}}
            except JobCancelled:
                return {"cancelled": True, "result": {"message": "Cancelled"}}
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001
                log.exception("Job %s (%s) failed", job_id, action)
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            finally:
                await client.close()
                await self.registry.clear(job_id)

        @router.post("/jobs/{job_id}/cancel")
        async def cancel_job(job_id: str, x_internal_token: str = Header(default="")) -> dict[str, Any]:
            if x_internal_token != INTERNAL_TOKEN:
                raise HTTPException(status_code=403, detail="Invalid internal token")
            await self.registry.cancel(job_id)
            return {"ok": True, "job_id": job_id}

        @router.get("/jobs/{job_id}/cancel-state")
        async def cancel_state(job_id: str, x_internal_token: str = Header(default="")) -> dict[str, Any]:
            if x_internal_token != INTERNAL_TOKEN:
                raise HTTPException(status_code=403, detail="Invalid internal token")
            event = await self.registry.register(job_id)
            return {"job_id": job_id, "cancel_requested": event.is_set()}

        return router


def create_service_app(
    name: str,
    title: str,
    description: str,
    *,
    runner: JobRunner | None = None,
    version: str = "1.0.0",
    extra_routers: list[APIRouter] | None = None,
    on_startup: Callable[[], Awaitable[None]] | None = None,
    on_shutdown: Callable[[], Awaitable[None]] | None = None,
) -> FastAPI:
    started = time.time()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        ensure_dirs()
        ensure_storage()
        if on_startup:
            await on_startup()
        log.info("%s starting", name)
        yield
        if on_shutdown:
            await on_shutdown()
        log.info("%s stopped", name)

    app = FastAPI(
        title=title,
        description=description,
        version=version,
        lifespan=lifespan,
        docs_url="/docs" if env_bool("ENABLE_DOCS", True) else None,
        redoc_url="/redoc" if env_bool("ENABLE_DOCS", True) else None,
        openapi_url="/openapi.json" if env_bool("ENABLE_DOCS", True) else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    @app.middleware("http")
    async def internal_guard(request: Request, call_next):
        """Defence in depth: private services still require the shared token.

        Disable with REQUIRE_INTERNAL_TOKEN=false for local unit tests. The
        gateway always injects the header, and service-to-service calls use the
        same helper. Health/doc routes and /internal/* stay reachable; the
        /internal/* handlers validate the token themselves.
        """
        if not env_bool("REQUIRE_INTERNAL_TOKEN", True):
            return await call_next(request)
        path = request.url.path
        if path in {"/", "/health", "/docs", "/redoc", "/openapi.json"} or path.startswith("/internal/"):
            return await call_next(request)
        if request.headers.get("x-internal-token") != INTERNAL_TOKEN:
            return JSONResponse(status_code=403, content={"detail": "Invalid internal token"})
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def value_error_handler(_: Request, exc: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(FileNotFoundError)
    async def missing_handler(_: Request, exc: FileNotFoundError):
        return JSONResponse(status_code=404, content={"detail": f"Not found: {exc}"})

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "service": name,
            "status": "ok",
            "version": version,
            "uptime_seconds": round(time.time() - started, 1),
        }

    @app.get("/")
    async def root() -> dict[str, Any]:
        return {"name": title, "service": name, "version": version, "docs": "/docs", "health": "/health"}

    for router in extra_routers or []:
        app.include_router(router)

    if runner is not None:
        app.include_router(runner.internal_router())
        app.state.runner = runner

    return app


async def gather_limited(tasks: list[Awaitable[Any]], limit: int = 4) -> list[Any]:
    semaphore = asyncio.Semaphore(limit)

    async def run(task: Awaitable[Any]) -> Any:
        async with semaphore:
            return await task

    return await asyncio.gather(*(run(task) for task in tasks), return_exceptions=True)
