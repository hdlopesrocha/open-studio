"""Async proxy for the QVAC image generation service."""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from openstudio_common import FILES_ROOT, INTERNAL_TOKEN, JOBHUB_URL, env, jobhub_headers, service_url

log = logging.getLogger("imagegen.qvac")

QVAC_URL = env("QVAC_URL", service_url("qvac")).rstrip("/")
IMAGE_ENDPOINT = env("QVAC_IMAGE_ENDPOINT", "/api/qvac/image")
POLL_INTERVAL = max(0.5, float(env("QVAC_POLL_INTERVAL", "2.0")))
TIMEOUT = max(30.0, float(env("QVAC_IMAGE_TIMEOUT", "1200")))
_TERMINAL_OK = {"completed", "complete", "succeeded", "success", "done", "finished"}
_TERMINAL_FAIL = {"failed", "error", "cancelled", "canceled", "interrupted", "timeout"}
_CONTAINER_KEYS = ("images", "files", "outputs", "output", "result", "data", "items", "artifacts", "saved_files")
_IMAGE_KEYS = ("path", "file", "filename", "url", "image_base64", "b64_json", "base64", "image")


class QVACError(RuntimeError):
    pass


def _image_like(value: dict[str, Any]) -> bool:
    return any(key in value for key in _IMAGE_KEYS)


def _collect_items(payload: Any, depth: int = 0) -> list[dict[str, Any] | str]:
    items: list[dict[str, Any] | str] = []
    if depth > 6:
        return items
    if isinstance(payload, dict):
        if _image_like(payload):
            items.append(payload)
            return items
        for key in _CONTAINER_KEYS:
            if key in payload:
                items.extend(_collect_items(payload[key], depth + 1))
    elif isinstance(payload, list):
        for entry in payload:
            items.extend(_collect_items(entry, depth + 1))
    elif isinstance(payload, str):
        if payload.startswith(("http://", "https://", "data:image/")) or payload.lower().endswith(
            (".png", ".jpg", ".jpeg", ".webp")
        ):
            items.append(payload)
    return items


def _job_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("id", "job_id", "jobId", "prompt_id"):
        value = payload.get(key)
        if value:
            return str(value)
    job = payload.get("job")
    if isinstance(job, dict):
        return _job_id(job)
    return None


def _status(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("status", "state"):
        value = payload.get(key)
        if isinstance(value, str):
            return value.lower()
    job = payload.get("job")
    if isinstance(job, dict):
        return _status(job)
    return ""


def _extension(value: str) -> str:
    suffix = Path(value.split("?", 1)[0]).suffix.lower()
    return suffix if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"} else ".png"


async def _fetch_url(client: httpx.AsyncClient, url: str) -> tuple[bytes, str]:
    response = await client.get(url)
    if response.status_code >= 400:
        raise QVACError(f"Could not download QVAC image: HTTP {response.status_code}")
    return response.content, _extension(url)


def _read_shared_file(value: str) -> tuple[bytes, str] | None:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = FILES_ROOT / value
    try:
        resolved = candidate.resolve()
        root = FILES_ROOT.resolve()
        if resolved != root and root not in resolved.parents:
            return None
        if resolved.is_file():
            return resolved.read_bytes(), _extension(resolved.name)
    except OSError:
        return None
    return None


async def _materialise(
    client: httpx.AsyncClient,
    item: dict[str, Any] | str,
) -> tuple[bytes, str, dict[str, Any]] | None:
    if isinstance(item, str):
        if item.startswith(("http://", "https://")):
            data, extension = await _fetch_url(client, item)
            return data, extension, {"url": item}
        if item.startswith("data:image/"):
            try:
                header, encoded = item.split(",", 1)
                extension = "." + header.split("/", 1)[1].split(";", 1)[0]
                return base64.b64decode(encoded), _extension("x" + extension), {"base64": True}
            except (ValueError, binascii.Error):
                return None
        shared = _read_shared_file(item)
        if shared:
            return shared[0], shared[1], {"path": item}
        return None
    for key in ("image_base64", "b64_json", "base64"):
        encoded = item.get(key)
        if isinstance(encoded, str) and encoded:
            try:
                payload = encoded.split(",", 1)[1] if encoded.startswith("data:image/") else encoded
                return base64.b64decode(payload), _extension(str(item.get("filename") or "x.png")), {"base64": True}
            except (ValueError, binascii.Error):
                continue
    for key in ("path", "file", "filename"):
        value = item.get(key)
        if isinstance(value, str) and value:
            shared = _read_shared_file(value)
            if shared:
                return shared[0], _extension(str(item.get("filename") or value)), {"path": value}
    for key in ("url", "image_url"):
        value = item.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            data, extension = await _fetch_url(client, value)
            return data, extension, {"url": value}
    value = item.get("image")
    if isinstance(value, str):
        return await _materialise(client, value)
    return None


async def generate(
    params: dict[str, Any],
    *,
    on_poll: Callable[[str, float], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """Submit to QVAC, wait for its job and return image bytes."""
    prompt = str(params.get("prompt") or "").strip()
    if not prompt:
        raise QVACError("prompt is required for QVAC image generation")
    payload = {
        "prompt": prompt,
        "negative_prompt": params.get("negative_prompt") or "",
        "width": int(params.get("width") or 1024),
        "height": int(params.get("height") or 1024),
        "steps": int(params.get("steps") or 28),
        "guidance": params.get("guidance"),
        "cfg_scale": params.get("cfg_scale"),
        "seed": params.get("seed"),
        "batch_count": int(params.get("batch_count") or 1),
        "sampling_method": params.get("sampler") or params.get("sampling_method"),
        "upscale": params.get("upscale"),
        "model": params.get("model") or None,
        "init_image": params.get("init_image"),
        "init_images": params.get("init_images"),
    }
    payload = {key: value for key, value in payload.items() if value not in (None, "")}
    headers = {**jobhub_headers(), "X-Internal-Token": INTERNAL_TOKEN}
    warnings: list[str] = []
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=20.0), headers=headers) as client:
        try:
            response = await client.post(f"{QVAC_URL}{IMAGE_ENDPOINT}", json=payload)
        except httpx.HTTPError as exc:
            raise QVACError(f"QVAC is not reachable at {QVAC_URL}: {exc}") from exc
        if response.status_code >= 400:
            raise QVACError(f"QVAC rejected the request (HTTP {response.status_code}): {response.text[:800]}")
        try:
            data: Any = response.json()
        except Exception as exc:  # noqa: BLE001
            raise QVACError(f"QVAC returned invalid JSON: {exc}") from exc

        job_id = _job_id(data)
        status = _status(data)
        items = _collect_items(data)
        if not items and job_id:
            endpoints = [
                f"{QVAC_URL}/api/qvac/jobs/{job_id}",
                f"{QVAC_URL}/api/qvac/job/{job_id}",
                f"{QVAC_URL}/api/jobs/{job_id}",
                f"{JOBHUB_URL}/api/jobs/{job_id}",
            ]
            last_error: str | None = None
            while time.monotonic() - started < TIMEOUT:
                await asyncio.sleep(POLL_INTERVAL)
                status = ""
                for endpoint in endpoints:
                    try:
                        poll = await client.get(endpoint)
                    except httpx.HTTPError as exc:
                        last_error = str(exc)
                        continue
                    if poll.status_code >= 400:
                        last_error = f"HTTP {poll.status_code} from {endpoint}"
                        continue
                    try:
                        data = poll.json()
                    except Exception:  # noqa: BLE001
                        continue
                    status = _status(data)
                    if on_poll:
                        await on_poll(status or "running", time.monotonic() - started)
                    items = _collect_items(data)
                    if items and (not status or status in _TERMINAL_OK):
                        break
                    if status in _TERMINAL_FAIL:
                        raise QVACError(f"QVAC job {job_id} failed with status {status}")
                    if items:
                        break
                if items:
                    break
            else:
                raise QVACError(
                    f"QVAC job {job_id} did not finish within {TIMEOUT:.0f}s"
                    + (f" ({last_error})" if last_error else "")
                )
        if not items:
            if status in _TERMINAL_FAIL:
                raise QVACError(f"QVAC job failed with status {status}")
            raise QVACError("QVAC completed without returning an image")

        images: list[dict[str, Any]] = []
        for item in items:
            materialised = await _materialise(client, item)
            if not materialised:
                warnings.append("QVAC returned an image reference that could not be downloaded.")
                continue
            content, extension, meta = materialised
            if len(content) < 100:
                warnings.append("QVAC returned an empty image payload.")
                continue
            images.append(
                {
                    "data": content,
                    "extension": extension,
                    "metadata": {
                        "qvac_job_id": job_id,
                        "source": item if isinstance(item, dict) else {"value": item},
                        **meta,
                    },
                }
            )
        if not images:
            raise QVACError("QVAC returned no usable image data")
    return {
        "images": images,
        "metadata": {
            "provider": "qvac",
            "endpoint": f"{QVAC_URL}{IMAGE_ENDPOINT}",
            "job_id": job_id,
            "status": status or "completed",
            "elapsed_seconds": round(time.monotonic() - started, 2),
        },
        "warnings": warnings,
    }


async def status() -> dict[str, Any]:
    """Cheap health probe for the provider catalogue."""
    async with httpx.AsyncClient(timeout=4.0, headers=jobhub_headers()) as client:
        for endpoint in (f"{QVAC_URL}/health", f"{QVAC_URL}/api/qvac/status", f"{QVAC_URL}/api/qvac/catalog"):
            try:
                response = await client.get(endpoint)
            except httpx.HTTPError as exc:
                return {"available": False, "url": QVAC_URL, "detail": f"not reachable: {exc}"}
            if response.status_code == 200:
                try:
                    data = response.json()
                except Exception:  # noqa: BLE001
                    data = {}
                return {"available": True, "url": QVAC_URL, "detail": data if isinstance(data, dict) else {}}
            if response.status_code not in {404, 405}:
                return {"available": False, "url": QVAC_URL, "detail": f"HTTP {response.status_code}"}
    return {"available": False, "url": QVAC_URL, "detail": "no health endpoint"}


__all__ = ["QVACError", "QVAC_URL", "generate", "status"]
