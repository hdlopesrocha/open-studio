"""Optional cue translation through the Open Studio translation service."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from openstudio_common import INTERNAL_TOKEN, env, jobhub_headers, service_url

log = logging.getLogger("srt.translation")

TRANSLATION_URL = env("TRANSLATION_URL", service_url("translation")).rstrip("/")
_LANG = re.compile(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})?$")


def valid_language(value: str) -> bool:
    return bool(value and _LANG.match(value.strip()))


def _extract_translations(payload: Any, expected: int) -> list[str]:
    if isinstance(payload, list):
        items: list[Any] = payload
    elif isinstance(payload, dict):
        nested = payload.get("result")
        if isinstance(nested, dict):
            payload = {**payload, **nested}
        items = (
            payload.get("translations")
            or payload.get("segments")
            or payload.get("items")
            or payload.get("translated")
            or []
        )
        if not items and isinstance(payload.get("text"), str):
            text = payload["text"]
            parts = [part.strip() for part in text.split("\n")]
            if expected > 1 and len(parts) == expected:
                items = parts
            else:
                items = [text]
        if isinstance(items, str):
            items = [items]
    else:
        return []
    translations: list[str] = []
    for item in items:
        if isinstance(item, str):
            translations.append(item.strip())
        elif isinstance(item, dict):
            value = (
                item.get("translation")
                or item.get("translated_text")
                or item.get("text")
                or item.get("target")
                or ""
            )
            translations.append(str(value).strip())
        else:
            translations.append("")
    return translations


async def translate_cues(
    cues: list[dict[str, Any]],
    target_language: str,
    *,
    source_language: str | None = None,
    model: str | None = None,
    timeout: float = 600.0,
) -> tuple[list[str], list[str]]:
    """Translate cue texts, returning one string per input cue where possible."""
    warnings: list[str] = []
    target = (target_language or "").strip()
    if not valid_language(target):
        raise ValueError(f"Invalid target language code: {target_language!r}")
    if not cues:
        return [], warnings
    payload: dict[str, Any] = {
        "segments": [
            {
                "index": index,
                "text": str(cue.get("text", "")),
                "start": float(cue.get("start", 0.0)),
                "end": float(cue.get("end", 0.0)),
            }
            for index, cue in enumerate(cues, start=1)
        ],
        "source_language": source_language if source_language and source_language != "auto" else "auto",
        "target_language": target,
        "preserve_markup": False,
    }
    if model:
        payload["model"] = model
    headers = {**jobhub_headers(), "X-Internal-Token": INTERNAL_TOKEN}
    endpoints = [
        f"{TRANSLATION_URL}/internal/translate",
        f"{TRANSLATION_URL}/api/translate",
        f"{TRANSLATION_URL}/translate",
    ]
    last_error: str | None = None
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=20.0), headers=headers) as client:
        for endpoint in endpoints:
            try:
                response = await client.post(endpoint, json=payload)
            except httpx.HTTPError as exc:
                last_error = f"{endpoint}: {exc}"
                continue
            if response.status_code in {404, 405}:
                last_error = f"{endpoint}: HTTP {response.status_code}"
                continue
            if response.status_code >= 400:
                detail = response.text[:500]
                try:
                    detail = response.json().get("detail", detail)
                except Exception:  # noqa: BLE001
                    pass
                last_error = f"translation service returned HTTP {response.status_code}: {detail}"
                continue
            try:
                data = response.json()
            except Exception:  # noqa: BLE001
                last_error = "translation service returned invalid JSON"
                continue
            translations = _extract_translations(data, len(cues))
            if not translations or not any(translations):
                last_error = "translation service returned no translations"
                continue
            if len(translations) < len(cues):
                warnings.append(
                    f"Translation returned {len(translations)} of {len(cues)} cues; "
                    "missing cues keep their original text."
                )
                translations.extend(str(cue.get("text", "")) for cue in cues[len(translations) :])
            elif len(translations) > len(cues):
                warnings.append(f"Translation returned {len(translations)} cues for {len(cues)} inputs; extras ignored.")
                translations = translations[: len(cues)]
            return translations, warnings
    warnings.append(
        "Translation was requested but failed"
        + (f": {last_error}" if last_error else "")
        + ". Original-language subtitles were still written."
    )
    log.warning("Cue translation failed: %s", last_error)
    return [], warnings
