"""Run blocking model work for a job while streaming progress and cancellation."""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable

from fastapi.concurrency import run_in_threadpool

from openstudio_common import JobCancelled, JobContext


async def run_blocking(
    ctx: JobContext,
    fn: Callable[..., Any],
    *,
    stage: str,
    start_progress: float = 0.0,
    end_progress: float = 100.0,
) -> Any:
    """Execute ``fn(progress, cancel)`` in a worker thread.

    The job hub is polled for cancellation from the event loop. The worker sees
    a thread-safe ``cancel()`` callback and stops at chunk/batch boundaries.
    """
    await ctx.check()
    loop = asyncio.get_running_loop()
    stop = threading.Event()

    def progress(percentage: float, message: str) -> None:
        mapped = start_progress + (end_progress - start_progress) * max(0.0, min(100.0, percentage)) / 100.0
        try:
            asyncio.run_coroutine_threadsafe(
                ctx.report(mapped, stage=stage, message=message),
                loop,
            )
        except RuntimeError:
            pass

    async def watch() -> None:
        try:
            while not stop.is_set():
                await asyncio.sleep(2.0)
                if await ctx.client.cancelled():
                    stop.set()
                    return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - cancellation polling must not kill the job
            return

    watcher = asyncio.create_task(watch())
    try:
        result = await run_in_threadpool(fn, progress, stop.is_set)
    finally:
        stop.set()
        watcher.cancel()
        try:
            await watcher
        except (asyncio.CancelledError, Exception):
            pass
    if stop.is_set():
        raise JobCancelled("Job cancelled by the user")
    return result
