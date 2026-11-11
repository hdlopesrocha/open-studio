"""Async HTTP clients used by the documents pipeline."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from openstudio_common import jobhub_headers

from .config import Settings

logger = logging.getLogger(__name__)


class ServiceCallError(Exception):
    def __init__(
        self,
        service: str,
        message: str,
        *,
        status_code: int = 502,
        code: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.service = service
        self.message = message
        self.status_code = status_code
        self.code = code or f"{service}_error"
        self.details = details or {}


def _error_payload(response: httpx.Response) -> tuple[str, str]:
    message = f"The {response.request.url.host} service rejected the request."
    code = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = payload.get("detail")
            error = payload.get("error")
            if isinstance(error, dict):
                code = str(error.get("code") or "")
                message = str(error.get("message") or message)
            elif isinstance(detail, dict):
                code = str(detail.get("code") or "")
                message = str(detail.get("message") or detail)
            elif detail is not None:
                message = str(detail)
    except ValueError:
        if response.text:
            message = response.text[:1000]
    return code, message


def _public_status(status: int) -> int:
    if status in {401, 403}:
        return 502
    if status in {404, 409, 413, 422, 429, 503, 504}:
        return status
    if status >= 500:
        return 502
    return status if 400 <= status < 500 else 502


class ServiceClients:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        timeout = httpx.Timeout(settings.tts_timeout, connect=15.0, write=120.0)
        self._http = httpx.AsyncClient(
            timeout=timeout,
            headers=jobhub_headers(),
            follow_redirects=False,
        )
        self.pdf = settings.pdf_url.rstrip("/")
        self.translation = settings.translation_url.rstrip("/")
        self.summary = settings.summary_url.rstrip("/")
        self.voice = settings.voice_url.rstrip("/")
        self.ffmpeg = settings.ffmpeg_url.rstrip("/")

    async def close(self) -> None:
        await self._http.aclose()

    # -- low level -----------------------------------------------------

    async def _request(
        self,
        service: str,
        method: str,
        url: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
        retries: int = 0,
    ) -> httpx.Response:
        last: Exception | None = None
        attempts = max(1, retries + 1)
        for attempt in range(attempts):
            try:
                response = await self._http.request(
                    method,
                    url,
                    json=json,
                    params=params,
                    timeout=timeout,
                )
            except httpx.TimeoutException as exc:
                last = exc
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise ServiceCallError(
                    service,
                    f"The {service} service did not respond in time.",
                    status_code=504,
                    code=f"{service}_timeout",
                ) from exc
            except httpx.HTTPError as exc:
                last = exc
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise ServiceCallError(
                    service,
                    f"The {service} service is unavailable.",
                    status_code=503,
                    code=f"{service}_unavailable",
                ) from exc
            if response.status_code >= 400:
                code, message = _error_payload(response)
                raise ServiceCallError(
                    service,
                    message,
                    status_code=_public_status(response.status_code),
                    code=code,
                    details={"upstream_status": response.status_code},
                )
            return response
        raise ServiceCallError(
            service,
            f"The {service} service is unavailable.",
            status_code=503,
            code=f"{service}_unavailable",
        ) from last

    async def _json(
        self,
        service: str,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        response = await self._request(service, method, url, **kwargs)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ServiceCallError(
                service,
                f"The {service} service returned an invalid response.",
                status_code=502,
                code=f"{service}_invalid_response",
            ) from exc
        if not isinstance(payload, dict):
            raise ServiceCallError(
                service,
                f"The {service} service returned an unexpected response.",
                status_code=502,
                code=f"{service}_invalid_response",
            )
        return payload

    # -- capabilities --------------------------------------------------

    async def capabilities(self) -> dict[str, Any]:
        calls: dict[str, tuple[str, str]] = {
            "pdf_status": ("pdf", f"{self.pdf}/api/pdf/status"),
            "pdf_ocr_languages": ("pdf", f"{self.pdf}/api/pdf/ocr-languages"),
            "translation_languages": ("translation", f"{self.translation}/api/translate/languages"),
            "translation_models": ("translation", f"{self.translation}/api/translate/models"),
            "translation_status": ("translation", f"{self.translation}/api/translate/status"),
            "summary_lengths": ("summary", f"{self.summary}/api/summary/lengths"),
            "summary_languages": ("summary", f"{self.summary}/api/summary/languages"),
            "summary_models": ("summary", f"{self.summary}/api/summary/models"),
            "summary_status": ("summary", f"{self.summary}/api/summary/status"),
            "tts_catalog": ("voice", f"{self.voice}/api/voice/catalog"),
            "ffmpeg_catalog": ("ffmpeg", f"{self.ffmpeg}/api/ffmpeg/catalog"),
        }

        async def run(key: str, service: str, url: str) -> dict[str, Any]:
            try:
                return {
                    "ok": True,
                    "data": await self._json(
                        service,
                        "GET",
                        url,
                        timeout=self.settings.capabilities_timeout,
                        retries=0,
                    ),
                }
            except ServiceCallError as exc:
                return {
                    "ok": False,
                    "error": {"code": exc.code, "message": exc.message},
                }
            except Exception as exc:  # noqa: BLE001
                return {
                    "ok": False,
                    "error": {"code": "capabilities_error", "message": str(exc)},
                }

        values = await asyncio.gather(
            *(run(key, service, url) for key, (service, url) in calls.items())
        )
        result: dict[str, Any] = {}
        for key, value in zip(calls, values):
            result[key] = value.get("data") if value.get("ok") else {
                "available": False,
                "error": value.get("error"),
            }
        return result

    # -- pipeline calls ------------------------------------------------

    async def extract_pdf(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._json(
            "pdf",
            "POST",
            f"{self.pdf}/api/pdf/extract",
            json=payload,
            timeout=self.settings.pdf_timeout,
            retries=0,
        )

    async def detect_language(self, text: str) -> dict[str, Any]:
        return await self._json(
            "translation",
            "POST",
            f"{self.translation}/api/translate/detect",
            json={"text": text[:20_000]},
            timeout=120,
            retries=1,
        )

    async def translate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._json(
            "translation",
            "POST",
            f"{self.translation}/internal/translate",
            json=payload,
            timeout=self.settings.translation_timeout,
            retries=0,
        )

    async def summarize(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._json(
            "summary",
            "POST",
            f"{self.summary}/internal/summarize",
            json=payload,
            timeout=self.settings.summary_timeout,
            retries=0,
        )

    async def tts_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._json(
            "voice",
            "POST",
            f"{self.voice}{self.settings.tts_internal_path}",
            json=payload,
            timeout=self.settings.tts_timeout,
            retries=0,
        )

    async def ffmpeg_finalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._json(
            "ffmpeg",
            "POST",
            f"{self.ffmpeg}{self.settings.ffmpeg_finalize_path}",
            json=payload,
            timeout=self.settings.ffmpeg_timeout,
            retries=0,
        )
