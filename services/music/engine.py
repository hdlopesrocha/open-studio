"""Client for the Dockerized ACE-Step 1.5 GGUF/C++ engine.

The engine exposes an asynchronous job API:

* ``GET  /health`` and ``GET /props`` for discovery.
* ``POST /lm`` and ``POST /synth`` return ``{"id": "..."}``.
* ``GET  /job?id=N`` polls status and ``GET /job?id=N&result=1`` returns audio.
* ``POST /job?id=N&cancel=1`` cancels a running job.

Result bodies are multipart/mixed with one audio part (and one latent part) per
generated track. This module keeps that protocol out of the HTTP routers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import time
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from openstudio_common import MODELS_ROOT, env, env_float, human_size, utc_now

from .catalog import (
    ACE_MODELS,
    DEFAULT_MODEL,
    MODEL_ORDER,
    build_model_descriptor,
    known_model_descriptors,
)

log = logging.getLogger("music.engine")

QUANT_ORDER = ["BF16", "Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M"]


class EngineError(RuntimeError):
    """An engine request failed. ``status_code`` is the HTTP status we expose."""

    def __init__(self, message: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.status_code = status_code


class EngineUnavailable(EngineError):
    def __init__(self, message: str) -> None:
        super().__init__(message, 503)


class EngineJobFailed(EngineError):
    def __init__(self, message: str) -> None:
        super().__init__(message, 500)


def _strip_gguf(value: str) -> str:
    return value[:-5] if value.lower().endswith(".gguf") else value


def _model_base(stem: str) -> tuple[str | None, str]:
    """Map an installed GGUF filename stem to a known ACE-Step model id."""
    for model_id in sorted(ACE_MODELS, key=len, reverse=True):
        if stem == model_id:
            return model_id, ""
        if stem.startswith(model_id + "-"):
            suffix = stem[len(model_id) + 1 :]
            quant = next((candidate for candidate in QUANT_ORDER if suffix.upper() == candidate.upper()), "")
            return model_id, quant or suffix
    # Unknown custom checkpoint: still strip a known quantisation suffix so the
    # model id stays stable when the user swaps Q8_0 for Q6_K.
    for quant in QUANT_ORDER:
        if stem.upper().endswith("-" + quant.upper()):
            return stem[: -(len(quant) + 1)], quant
    return None, ""


def _names(value: Any) -> list[str]:
    """Normalise /props model buckets to a list of filenames."""
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        for key in ("name", "file", "filename", "path"):
            if value.get(key):
                return [str(value[key])]
        return [str(item) for item in value.values() if isinstance(item, (str, int))]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_names(item))
        return result
    return [str(value)]


class ACEStepEngine:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or env("ACESTEP_ENGINE_URL", "http://music-engine:8085")).rstrip("/")
        self.models_dir = Path(env("ACESTEP_MODELS_DIR", str(MODELS_ROOT / "acestep")))
        self.health_timeout = env_float("ACESTEP_HEALTH_TIMEOUT_SECONDS", 2.5)
        self.props_timeout = env_float("ACESTEP_PROPS_TIMEOUT_SECONDS", 8.0)
        self.poll_seconds = max(0.25, env_float("ACESTEP_POLL_SECONDS", 3.0))
        self.job_timeout = max(60.0, env_float("ACESTEP_JOB_TIMEOUT_SECONDS", 6 * 60 * 60))
        self.submit_timeout = env_float("ACESTEP_SUBMIT_TIMEOUT_SECONDS", 180.0)
        self.cache_seconds = max(1.0, env_float("ACESTEP_PROBE_CACHE_SECONDS", 4.0))
        self._cache: tuple[float, dict[str, Any]] | None = None
        self._lock = asyncio.Lock()
        self._default_model = env("ACESTEP_DEFAULT_MODEL", DEFAULT_MODEL)

    # ------------------------------------------------------------------ probing
    async def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        try:
            async with httpx.AsyncClient(timeout=timeout or self.props_timeout) as client:
                response = await client.get(f"{self.base_url}{path}", params=params)
        except httpx.TimeoutException as exc:
            raise EngineUnavailable("The ACE-Step engine did not answer in time.") from exc
        except httpx.HTTPError as exc:
            raise EngineUnavailable(
                "The ACE-Step engine is not reachable. It may still be downloading its GGUF models on first start."
            ) from exc
        if response.status_code >= 400:
            detail = response.text[:400] if response.text else f"HTTP {response.status_code}"
            raise EngineError(detail, 422 if response.status_code < 500 else 503)
        try:
            return response.json()
        except ValueError as exc:
            raise EngineError("The ACE-Step engine returned a non-JSON response.", 503) from exc

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.health_timeout) as client:
                response = await client.get(f"{self.base_url}/health")
            body: Any
            try:
                body = response.json()
            except ValueError:
                body = {}
            return {
                "reachable": response.status_code < 400,
                "status_code": response.status_code,
                "status": str(body.get("status") or ("ok" if response.status_code < 400 else "error")),
                "detail": "ACE-Step engine reachable." if response.status_code < 400 else f"HTTP {response.status_code}",
            }
        except httpx.TimeoutException:
            return {"reachable": False, "status_code": None, "status": "offline", "detail": "Health check timed out."}
        except httpx.HTTPError as exc:
            return {"reachable": False, "status_code": None, "status": "offline", "detail": str(exc)}

    @staticmethod
    def _buckets(props: dict[str, Any]) -> dict[str, list[str]]:
        raw = props.get("models") if isinstance(props, dict) else None
        raw = raw if isinstance(raw, dict) else {}
        return {
            "dit": _names(raw.get("dit")),
            "lm": _names(raw.get("lm")),
            "embedding": _names(raw.get("embedding")),
            "vae": _names(raw.get("vae")),
        }

    @staticmethod
    def _choose_lm(files: list[str]) -> str | None:
        if not files:
            return None
        for needle in ("0.6B", "1.7B", "4B"):
            for name in files:
                if needle in name:
                    return name
        return files[0]

    def _descriptors(self, props: dict[str, Any]) -> list[dict[str, Any]]:
        buckets = self._buckets(props)
        dit_files = buckets["dit"]
        if not dit_files:
            return known_model_descriptors(self._default_model)

        lm_file = self._choose_lm(buckets["lm"])
        embedding = buckets["embedding"][0] if buckets["embedding"] else ""
        vae = buckets["vae"][0] if buckets["vae"] else ""

        # One descriptor per DiT base. Prefer the best available quantisation.
        discovered: dict[str, dict[str, Any]] = {}
        for dit_file in dit_files:
            stem = Path(str(dit_file)).name
            stem = _strip_gguf(stem)
            base_id, quant = _model_base(stem)
            unknown = base_id is None
            model_id = base_id or stem
            rank = QUANT_ORDER.index(quant) if quant in QUANT_ORDER else len(QUANT_ORDER)
            existing = discovered.get(model_id)
            if existing is not None and existing["_rank"] <= rank:
                continue
            installed = bool(embedding and vae and dit_file)
            effective_lm = "" if unknown else (lm_file or "")
            files = {
                "dit": str(dit_file),
                "lm": effective_lm,
                "embedding": embedding,
                "vae": vae,
            }
            descriptor = build_model_descriptor(
                model_id,
                installed=installed,
                default_model=self._default_model,
                files=files,
                quantization=quant,
            )
            if not effective_lm:
                capabilities = descriptor["capabilities"]
                capabilities["text_to_music"] = False
                capabilities["extend"] = False
                capabilities["operation_note"] = (
                    "A 5Hz LM GGUF is required for full text-to-music and completion. "
                    "Cover and repaint can still render directly through the DiT."
                )
                descriptor["controls"]["text_to_music"] = False
                descriptor["controls"]["extend"] = False
                descriptor["notes"].append("No 5Hz LM file is installed; full-song generation is disabled.")
            if not embedding or not vae:
                descriptor["notes"].append("The text encoder or VAE GGUF is missing, so this model cannot render.")
            descriptor["_rank"] = rank
            discovered[model_id] = descriptor

        models: list[dict[str, Any]] = []
        for model_id in MODEL_ORDER:
            if model_id in discovered:
                item = discovered.pop(model_id)
                item.pop("_rank", None)
                models.append(item)
            else:
                models.append(
                    build_model_descriptor(
                        model_id,
                        installed=False,
                        default_model=self._default_model,
                    )
                )
        for item in discovered.values():
            item.pop("_rank", None)
            models.append(item)

        def sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
            model_id = item["id"]
            order = MODEL_ORDER.index(model_id) if model_id in MODEL_ORDER else len(MODEL_ORDER)
            return (0 if item.get("recommended") else 1, order, model_id)

        models.sort(key=sort_key)
        return models

    async def probe(self, force: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        async with self._lock:
            if not force and self._cache and now - self._cache[0] < self.cache_seconds:
                return self._cache[1]

            health = await self.health()
            props: dict[str, Any] = {}
            version: str | None = None
            detail = (
                "The ACE-Step engine is offline. Start the music-engine container; on first start it "
                "downloads several gigabytes of GGUF model files."
            )
            if health["reachable"]:
                try:
                    props = await self._get_json("/props", timeout=self.props_timeout)
                    if not isinstance(props, dict):
                        props = {}
                    version = str(props.get("version") or props.get("commit") or "") or None
                    detail = "ACE-Step GGUF engine connected."
                except EngineError as exc:
                    detail = f"The ACE-Step engine is reachable but /props failed: {exc}"
                    props = {}

            models = self._descriptors(props) if props else known_model_descriptors(self._default_model)
            installed = [model for model in models if model.get("installed")]
            available = bool(health["reachable"] and props and installed)
            if health["reachable"] and not props:
                detail = "The ACE-Step engine is reachable but /props returned no model data."
            elif health["reachable"] and props and not installed:
                detail = (
                    "The ACE-Step engine is online but its model directory is incomplete. "
                    "Wait for the first-start download to finish, then retry."
                )
            elif available:
                detail = "ACE-Step GGUF engine ready."

            state = {
                "available": available,
                "detail": detail,
                "version": version,
                "props": props,
                "models": models,
                "buckets": self._buckets(props) if props else {"dit": [], "lm": [], "embedding": [], "vae": []},
                "health": health,
                "engine_url": self.base_url,
                "checked_at": utc_now(),
            }
            self._cache = (now, state)
            return state

    def find_model(self, state: dict[str, Any], model_id: str) -> dict[str, Any] | None:
        return next((model for model in state.get("models") or [] if model.get("id") == model_id), None)

    async def require_model(self, model_id: str, *, workspace: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        state = await self.probe()
        if not state.get("available"):
            raise EngineUnavailable(str(state.get("detail") or "The ACE-Step engine is offline."))
        model = self.find_model(state, model_id)
        if model is None:
            raise EngineError(f"Model '{model_id}' is not installed in the ACE-Step engine.", 404)
        if not model.get("installed"):
            raise EngineError(
                f"Model '{model_id}' needs a complete GGUF set (DiT, LM, text encoder and VAE). "
                "Wait for the first-start download to finish.",
                422,
            )
        files = model.get("files") or {}
        if not files.get("dit"):
            raise EngineError(f"Model '{model_id}' has no DiT file.", 422)
        if workspace in {"full", "extend"} and not files.get("lm"):
            raise EngineError(f"Model '{model_id}' has no 5Hz LM file for {workspace} generation.", 422)
        return state, model

    # ------------------------------------------------------------------ jobs
    async def _post_json(self, path: str, payload: Any) -> str:
        try:
            async with httpx.AsyncClient(timeout=self.submit_timeout) as client:
                response = await client.post(f"{self.base_url}{path}", json=payload)
        except httpx.TimeoutException as exc:
            raise EngineError("The ACE-Step engine timed out while accepting the job.", 503) from exc
        except httpx.HTTPError as exc:
            raise EngineUnavailable("Lost contact with the ACE-Step engine while submitting the job.") from exc
        if response.status_code >= 400:
            detail = response.text[:500] if response.text else f"HTTP {response.status_code}"
            raise EngineError(detail, 422 if response.status_code < 500 else 503)
        try:
            body = response.json()
        except ValueError as exc:
            raise EngineError("The ACE-Step engine returned an unexpected submission response.", 503) from exc
        job_id = body.get("id") if isinstance(body, dict) else None
        if job_id is None:
            raise EngineError("The ACE-Step engine did not return a job id.", 503)
        return str(job_id)

    async def submit_lm(self, payload: dict[str, Any] | list[dict[str, Any]]) -> str:
        return await self._post_json("/lm", payload)

    async def submit_synth(
        self,
        payload: dict[str, Any] | list[dict[str, Any]],
        *,
        source: Path | None = None,
        reference: Path | None = None,
    ) -> str:
        if source is None and reference is None:
            return await self._post_json("/synth", payload)

        if source is not None and not source.exists():
            raise EngineError("The source audio file is not available to the engine.", 422)
        if reference is not None and not reference.exists():
            raise EngineError("The reference audio file is not available to the engine.", 422)

        data = {"request": json.dumps(payload, ensure_ascii=False)}
        handles: list[Any] = []
        try:
            files: dict[str, tuple[str, Any, str]] = {}
            if source is not None:
                handle = source.open("rb")
                handles.append(handle)
                files["audio"] = (
                    source.name,
                    handle,
                    mimetypes.guess_type(source.name)[0] or "application/octet-stream",
                )
            if reference is not None:
                handle = reference.open("rb")
                handles.append(handle)
                files["ref_audio"] = (
                    reference.name,
                    handle,
                    mimetypes.guess_type(reference.name)[0] or "application/octet-stream",
                )
            try:
                async with httpx.AsyncClient(timeout=self.submit_timeout) as client:
                    response = await client.post(f"{self.base_url}/synth", data=data, files=files)
            except httpx.TimeoutException as exc:
                raise EngineError("The ACE-Step engine timed out while accepting the job.", 503) from exc
            except httpx.HTTPError as exc:
                raise EngineUnavailable("Lost contact with the ACE-Step engine while submitting the job.") from exc
            if response.status_code >= 400:
                detail = response.text[:500] if response.text else f"HTTP {response.status_code}"
                raise EngineError(detail, 422 if response.status_code < 500 else 503)
            try:
                body = response.json()
            except ValueError as exc:
                raise EngineError("The ACE-Step engine returned an unexpected submission response.", 503) from exc
            job_id = body.get("id") if isinstance(body, dict) else None
            if job_id is None:
                raise EngineError("The ACE-Step engine did not return a job id.", 503)
            return str(job_id)
        finally:
            for handle in handles:
                handle.close()

    async def job_status(self, job_id: str) -> dict[str, Any]:
        body = await self._get_json("/job", params={"id": job_id}, timeout=20.0)
        if not isinstance(body, dict):
            raise EngineError("The ACE-Step engine returned an invalid job status.", 503)
        return body

    async def wait_job(
        self,
        job_id: str,
        *,
        on_tick: Callable[[float, dict[str, Any]], Awaitable[None]] | None = None,
        check: Callable[[], Awaitable[None]] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + (timeout or self.job_timeout)
        started = time.monotonic()
        while True:
            if check is not None:
                await check()
            try:
                status = await self.job_status(job_id)
            except EngineUnavailable:
                raise
            except EngineError as exc:
                raise EngineError(f"Could not poll ACE-Step job {job_id}: {exc}", exc.status_code) from exc
            state = str(status.get("status") or "running").lower()
            if state == "done":
                return status
            if state in {"failed", "cancelled", "canceled"}:
                detail = str(status.get("error") or status.get("message") or "").strip()
                raise EngineJobFailed(
                    f"ACE-Step job {job_id} {state}." + (f" {detail}" if detail else " Check the engine logs.")
                )
            if on_tick is not None:
                await on_tick(time.monotonic() - started, status)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise EngineError(
                    "The ACE-Step engine job timed out. Try a shorter duration or check the engine logs.",
                    504,
                )
            await asyncio.sleep(min(self.poll_seconds, max(0.25, remaining)))

    async def result(self, job_id: str) -> tuple[bytes, str]:
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.get(
                    f"{self.base_url}/job",
                    params={"id": job_id, "result": "1"},
                )
        except httpx.HTTPError as exc:
            raise EngineUnavailable("Could not retrieve the generated audio from the ACE-Step engine.") from exc
        if response.status_code >= 400:
            detail = response.text[:500] if response.text else f"HTTP {response.status_code}"
            raise EngineError(detail, 422 if response.status_code < 500 else 503)
        return response.content, response.headers.get("content-type", "")

    async def cancel_job(self, job_id: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(f"{self.base_url}/job", params={"id": job_id, "cancel": "1"})
        except Exception:  # noqa: BLE001 - cancellation is best effort
            log.info("Could not cancel ACE-Step job %s", job_id, exc_info=True)

    # ------------------------------------------------------------------ results
    @staticmethod
    def parse_audio_parts(content: bytes, content_type: str) -> list[tuple[bytes, str]]:
        """Extract audio payloads from a multipart/mixed engine result."""
        if "multipart/" not in content_type:
            if content_type.startswith("audio/"):
                return [(content, content_type.split(";")[0].strip())] if content else []
            if content[:4] == b"RIFF":
                return [(content, "audio/wav")]
            if content[:3] == b"ID3" or content[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}:
                return [(content, "audio/mpeg")]
            raise EngineError("The engine returned an audio result in an unknown format.", 503)

        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + content
        )
        parts: list[tuple[bytes, str]] = []
        if message.is_multipart():
            for part in message.iter_parts():
                part_type = part.get_content_type()
                if not part_type.startswith("audio/"):
                    continue
                payload = part.get_payload(decode=True) or b""
                if payload:
                    parts.append((payload, part_type))
        return parts

    def scan_model_files(self) -> dict[str, Any]:
        """List GGUF files on disk, even when the engine is still starting."""
        files: list[dict[str, Any]] = []
        try:
            if self.models_dir.is_dir():
                for path in sorted(self.models_dir.glob("*.gguf")):
                    try:
                        size = path.stat().st_size
                    except OSError:
                        size = 0
                    files.append(
                        {
                            "name": path.name,
                            "size": size,
                            "size_label": human_size(size),
                            "path": str(path),
                        }
                    )
        except OSError:
            pass
        return {"path": str(self.models_dir), "files": files, "count": len(files)}


engine = ACEStepEngine()
