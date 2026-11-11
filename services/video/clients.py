"""HTTP client for video orchestrator -> microservice calls.

The image generator is the shared Open Studio ``imagegen`` service. Its
MVS-compatible endpoints live under ``/internal/video`` and are selected with
``IMAGES_SERVICE_URL`` (for example ``http://imagegen:8000/internal/video``).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from fastapi.encoders import jsonable_encoder
from mvstudio_shared.config import get_settings
from openstudio_common import INTERNAL_TOKEN, jobhub_headers

logger = logging.getLogger("mvstudio.video.client")

DEFAULT_TIMEOUTS = {
    "audio": 1800.0,
    "lyrics": 300.0,
    "planner": 900.0,
    "images": 1200.0,
    "animation": 7200.0,
    "renderer": 7200.0,
}


class ServiceError(RuntimeError):
    def __init__(self, service: str, message: str, *, status_code: int | None = None):
        super().__init__(f"{service}: {message}")
        self.service = service
        self.message = message
        self.status_code = status_code


class ServiceClient:
    def __init__(self, *, local: bool | None = None):
        self.settings = get_settings()
        self.local = self.settings.local_services if local is None else local
        self._local_clients: dict[str, Any] = {}

    def _headers(self) -> dict[str, str]:
        return {"X-Internal-Token": INTERNAL_TOKEN, **{k: v for k, v in jobhub_headers().items() if k == "X-Service"}}

    def _local_client(self, service: str):
        """In-process testing hook.

        Docker/local production always uses HTTP. The optional local mode makes
        service unit tests possible without starting five uvicorn processes.
        """
        if service in self._local_clients:
            return self._local_clients[service]
        module_names = {
            "audio": ["services.video_audio.app:app"],
            "lyrics": ["services.video_lyrics.app:app"],
            "planner": ["services.video_planner.app:app"],
            "animation": ["services.video_animation.app:app"],
            "renderer": ["services.video_renderer.app:app"],
            "images": ["services.imagegen.app:app", "services.imagegen.main:app"],
        }
        import importlib

        from fastapi.testclient import TestClient

        module = None
        errors: list[str] = []
        for candidate in module_names[service]:
            module_path, app_name = candidate.split(":")
            try:
                module = importlib.import_module(module_path)
                app = getattr(module, app_name)
                break
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{candidate}: {exc}")
                module = None
        if module is None:
            raise ServiceError(
                service,
                "Local in-process service unavailable (" + "; ".join(errors) + "); use HTTP",
            )
        client = TestClient(app)
        self._local_clients[service] = client
        return client

    def _url(self, service: str, path: str) -> str:
        base = self.settings.service_url(service).rstrip("/")
        if service == "images" and not base.endswith("/internal/video"):
            # Accept both ``IMAGES_SERVICE_URL=http://imagegen:8000`` and the
            # documented MVS-compatible base with /internal/video.
            from urllib.parse import urlsplit

            if urlsplit(base).path in {"", "/"}:
                base += "/internal/video"
        return f"{base}/{path.lstrip('/')}"

    def post(
        self,
        service: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        retries: int | None = None,
    ) -> dict[str, Any]:
        timeout = timeout or DEFAULT_TIMEOUTS.get(service, 600.0)
        attempts = max(1, self.settings.request_retries if retries is None else retries)
        body = jsonable_encoder(payload or {})
        last_exception: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                if self.local:
                    response = self._local_client(service).post(
                        path,
                        json=body,
                        headers=self._headers(),
                        timeout=timeout,
                    )
                    if response.status_code >= 400:
                        detail = response.text
                        try:
                            parsed = response.json()
                            detail = parsed.get("detail", detail)
                        except Exception:  # noqa: BLE001
                            pass
                        raise ServiceError(service, str(detail), status_code=response.status_code)
                    return response.json()
                with httpx.Client(timeout=httpx.Timeout(timeout, connect=15.0)) as client:
                    response = client.post(self._url(service, path), json=body, headers=self._headers())
                if response.status_code >= 400:
                    detail = response.text[:2000]
                    try:
                        parsed = response.json()
                        detail = parsed.get("detail", detail)
                    except Exception:  # noqa: BLE001
                        pass
                    error = ServiceError(service, str(detail), status_code=response.status_code)
                    if response.status_code >= 500 and attempt < attempts:
                        last_exception = error
                        time.sleep(min(2.0 * attempt, 8.0))
                        continue
                    raise error
                return response.json()
            except ServiceError:
                raise
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exception = exc
                if attempt < attempts:
                    logger.warning(
                        "Service %s unreachable (attempt %d/%d): %s",
                        service,
                        attempt,
                        attempts,
                        exc,
                    )
                    time.sleep(min(2.0 * attempt, 8.0))
                    continue
                raise ServiceError(service, f"Service unreachable: {exc}") from exc
            except Exception as exc:  # noqa: BLE001
                last_exception = exc
                if attempt < attempts:
                    logger.warning("Service %s call failed (attempt %d): %s", service, attempt, exc)
                    time.sleep(min(1.5 * attempt, 6.0))
                    continue
                raise ServiceError(service, str(exc)) from exc
        raise ServiceError(service, f"Call failed: {last_exception}")

    def get(
        self,
        service: str,
        path: str,
        *,
        timeout: float = 10.0,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(self._url(service, path), params=params, headers=self._headers())
        if response.status_code >= 400:
            raise ServiceError(service, response.text[:1000], status_code=response.status_code)
        return response.json()

    def health(self, service: str, *, timeout: float = 4.0) -> dict[str, Any]:
        if self.local and service != "images":
            try:
                response = self._local_client(service).get("/health", timeout=timeout)
                if response.status_code == 200:
                    return {"available": True, **response.json()}
                return {"available": False, "detail": f"HTTP {response.status_code}"}
            except Exception as exc:  # noqa: BLE001
                return {"available": False, "detail": str(exc)}
        base = self.settings.service_url(service).rstrip("/")
        candidates = [f"{base}/health"]
        detail = "unavailable"
        if service == "images":
            # IMAGES_SERVICE_URL points at /internal/video; the health endpoint
            # is served by the imagegen root.
            if base.endswith("/internal/video"):
                root = base[: -len("/internal/video")]
                candidates = [f"{root}/health", f"{base}/provider-status", f"{base}/providers"]
        for url in candidates:
            try:
                with httpx.Client(timeout=timeout) as client:
                    response = client.get(url, headers=self._headers())
                if response.status_code == 200:
                    try:
                        return {"available": True, **response.json()}
                    except Exception:  # noqa: BLE001
                        return {"available": True, "detail": "ok"}
            except Exception as exc:  # noqa: BLE001
                detail = str(exc)
                continue
        return {"available": False, "detail": detail}
