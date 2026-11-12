"""Lyrics drafting through the shared LLM service.

The music service owns the lyricist prompt and section parsing. The LLM
service only provides the OpenAI-compatible transport at
``POST /api/llm/complete``.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

import httpx

from openstudio_common import INTERNAL_TOKEN, build_srt, env, env_float, service_url

from .languages import get_language, lyrics_language_instruction
from .schemas import LyricsDraftRequest

log = logging.getLogger("music.lyrics")

LLM_URL = service_url("llm")
LLM_TIMEOUT = env_float("LLM_TIMEOUT_SECONDS", 300.0)
LLM_MODEL = env("LLM_MODEL", "")

SECTION_TOKENS: list[tuple[str, str]] = [
    ("pre-chorus", "pre-chorus"),
    ("prechorus", "pre-chorus"),
    ("pre chorus", "pre-chorus"),
    ("pré-refrão", "pre-chorus"),
    ("pre-refrao", "pre-chorus"),
    ("precoro", "pre-chorus"),
    ("intro", "intro"),
    ("verse", "verse"),
    ("estrofe", "verse"),
    ("chorus", "chorus"),
    ("refrão", "chorus"),
    ("refrao", "chorus"),
    ("coro", "chorus"),
    ("bridge", "bridge"),
    ("ponte", "bridge"),
    ("puente", "bridge"),
    ("outro", "outro"),
]


class LyricsError(RuntimeError):
    def __init__(self, message: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.status_code = status_code


class LyricsUnavailable(LyricsError):
    def __init__(self, message: str) -> None:
        super().__init__(message, 503)


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Internal-Token": INTERNAL_TOKEN,
        "X-Service": "music",
    }


def _map_section_type(label: str, fallback: str = "verse") -> str:
    lowered = label.lower()
    for token, section_type in SECTION_TOKENS:
        if token in lowered:
            return section_type
    return fallback


def parse_sectioned_lyrics(text: str) -> list[dict[str, str]]:
    """Turn a plain-text lyric draft into the studio's section structure."""
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:text|markdown|lyrics)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    lines = cleaned.splitlines()
    sections: list[dict[str, str]] = []
    current_label: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_label, current_lines
        if current_label is None:
            return
        content = "\n".join(current_lines).strip("\n")
        sections.append(
            {
                "id": uuid.uuid4().hex,
                "type": _map_section_type(current_label),
                "label": re.sub(r"\s+", " ", current_label).strip(),
                "content": content,
                "instructions": "",
            }
        )
        current_label = None
        current_lines = []

    for line in lines:
        match = re.match(
            r"^\s*(?:[-*#>]+\s*)?[\[(]\s*([^\]\)]{1,80})\s*[\])]\s*:?\s*$",
            line,
        )
        if match:
            candidate = re.sub(r"\s+", " ", match.group(1)).strip()
            if any(token in candidate.lower() for token, _ in SECTION_TOKENS):
                flush()
                current_label = candidate
                continue
            # Bracketed production notes inside lyrics are not reliable headers.
            if current_label is not None:
                current_lines.append(line.rstrip())
            else:
                current_lines.append(line.strip())
            continue
        if current_label is not None:
            current_lines.append(line.rstrip())

    flush()

    if not sections:
        body = cleaned.strip()
        if body:
            sections = [
                {
                    "id": uuid.uuid4().hex,
                    "type": "verse",
                    "label": "Verse 1",
                    "content": body,
                    "instructions": "Structure returned without section markers — reorganise as needed.",
                }
            ]
    return sections


DEFAULT_STRUCTURE: list[tuple[str, int]] = [
    ("Verse 1", 4),
    ("Pre-Chorus", 2),
    ("Chorus", 4),
    ("Verse 2", 4),
    ("Chorus", 4),
    ("Bridge", 2),
    ("Chorus", 4),
    ("Outro", 2),
]


def _structure_text(request: LyricsDraftRequest) -> str:
    if request.structure:
        return "\n".join(f"- [{item.label}] — {item.line_count} lines" for item in request.structure)
    return "\n".join(f"- [{label}] — {line_count} lines" for label, line_count in DEFAULT_STRUCTURE)


def build_prompt(request: LyricsDraftRequest) -> tuple[str, str]:
    language_info = get_language(request.language, request.language_label)
    language_instruction = lyrics_language_instruction(
        request.language,
        request.language_label or language_info.label,
    )
    vocal_note = (
        "This is an instrumental track: the lyrics editor should stay empty."
        if request.vocal_type == "instrumental"
        else f"Vocal arrangement: {request.vocal_type}."
    )
    system_prompt = f"""You are a senior songwriter and lyricist working inside a private local music studio.
{language_instruction}

Write original, singable, emotionally specific lyrics. Make every line work rhythmically.
Use concrete images instead of generic pop phrases. Do not include explanations, titles, translation
notes, romanisation, production notes, or any preamble. Do not copy existing songs.

The output MUST use exactly this plain-text section format:
[Intro]
line one
line two

[Verse 1]
...

Only use section headers from the requested structure. Preserve clear line breaks. The lyricist's
first loyalty is to the requested language and regional variant. Never translate an existing lyric
unless explicitly instructed. Return lyrics only, written in {language_info.label} ({language_info.code})."""

    user_prompt = f"""Song title: {request.title or "(untitled)"}
Genre: {request.genre}{f" / {request.subgenre}" if request.subgenre else ""}
Musical style: {request.style or "—"}
Mood: {request.mood or "—"}
Energy: {request.energy}/100
{vocal_note}
Creative brief: {request.theme or request.direction}
Additional direction: {request.direction or "—"}

Requested structure (follow this order):
{_structure_text(request)}

Write the lyrics now. Keep the section labels exactly as shown. Do not add new sections unless the brief
needs a short intro or outro. If a language needs non-Latin script, use its natural script."""
    return system_prompt, user_prompt


SECTION_LABELS: dict[str, str] = {
    "intro": "Intro",
    "verse": "Verse",
    "pre-chorus": "Pre-Chorus",
    "chorus": "Chorus",
    "bridge": "Bridge",
    "outro": "Outro",
    "instrumental": "Instrumental",
}


def lyric_lines(content: str) -> list[str]:
    """Return the non-empty lyric lines in performance order."""
    normal = str(content or "").replace("\r\n", "\n").replace("\r", "\n")
    return [line.strip() for line in normal.split("\n") if line.strip()]


def section_weight(section: dict[str, Any]) -> int:
    """Share duration by line count; empty/instrumental sections keep a slot."""
    lines = lyric_lines(section.get("content") or "")
    return len(lines) if lines else 2


def section_label(section: dict[str, Any]) -> str:
    label = str(section.get("label") or "").strip()
    if label and label.lower() != "section":
        return label
    kind = str(section.get("type") or "").strip().lower()
    return SECTION_LABELS.get(kind) or (kind.replace("-", " ").title() if kind else "Section")


def _safe_duration(duration: Any, fallback: float = 60.0) -> float:
    """Never emit zero-length cues when a take has no probed duration yet."""
    try:
        value = float(duration or 0)
    except (TypeError, ValueError):
        value = 0.0
    if value <= 0:
        try:
            value = float(fallback or 0)
        except (TypeError, ValueError):
            value = 0.0
    return value if value > 0 else 60.0


def lyric_section_spans(
    sections: list[dict[str, Any]], duration: Any, *, fallback_duration: float = 60.0
) -> list[dict[str, Any]]:
    """Lay sections out proportionally to their line counts over the take duration."""
    weights = [section_weight(section) for section in sections]
    total_weight = sum(weights)
    if not sections or total_weight <= 0:
        return []
    seconds = _safe_duration(duration, fallback_duration)
    cursor = 0
    spans: list[dict[str, Any]] = []
    for section, weight in zip(sections, weights):
        start = seconds * cursor / total_weight
        cursor += weight
        end = seconds * cursor / total_weight
        spans.append(
            {
                "section": section,
                "label": section_label(section),
                "lines": lyric_lines(section.get("content") or ""),
                "start": start,
                "end": end,
            }
        )
    return spans


def build_lyrics_srt(
    sections: list[dict[str, Any]],
    duration: Any,
    *,
    fallback_duration: float = 60.0,
    empty_label: str = "Instrumental",
) -> str:
    """Build deterministic SRT cues from the song's structured lyrics.

    Section labels are included with the first lyric line of each section so a
    player can show both context and the sung line. Instrumental or empty
    sections become a single label cue instead of disappearing from the sheet.
    """
    spans = lyric_section_spans(sections, duration, fallback_duration=fallback_duration)
    if not spans:
        return build_srt([{"start": 0.0, "end": _safe_duration(duration, fallback_duration), "text": f"[{empty_label}]"}])
    cues: list[dict[str, Any]] = []
    for span in spans:
        label = str(span["label"])
        lines: list[str] = span["lines"]
        start = float(span["start"])
        end = float(span["end"])
        if not lines:
            cues.append({"start": start, "end": max(start + 0.05, end), "text": f"[{label}]"})
            continue
        line_span = max(0.05, (end - start) / len(lines))
        for index, line in enumerate(lines):
            cue_start = start + index * line_span
            cue_end = start + (index + 1) * line_span
            text = f"[{label}]\n{line}" if index == 0 else line
            cues.append({"start": cue_start, "end": max(cue_start + 0.05, cue_end), "text": text})
    return build_srt(cues)


def srt_filename(title: str) -> str:
    """ASCII-safe download filename for a song's lyric sheet."""
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", str(title or "").strip()).strip("-_.")
    return f"{(base[:80] or 'lyrics')}-lyrics.srt"


async def health() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=3.0, headers=_headers()) as client:
            response = await client.get(f"{LLM_URL}/api/llm/health")
        if response.status_code >= 400:
            return {
                "reachable": False,
                "status": "offline",
                "detail": f"LLM service returned HTTP {response.status_code}.",
            }
        body = response.json()
        if not isinstance(body, dict):
            body = {}
        reachable = bool(body.get("reachable"))
        model = str(LLM_MODEL or body.get("model") or "llama3.2:3b")
        models = body.get("models") or []
        model_ids = [str(item.get("id") or "") for item in models if isinstance(item, dict)]
        detail = body.get("error") or ("LLM ready." if reachable else "The local LLM backend is offline.")
        if reachable and models and model:
            if not any(candidate == model or candidate.startswith(model) or model in candidate for candidate in model_ids):
                reachable = False
                detail = (
                    f"The local LLM is reachable but model '{model}' is not installed. "
                    f"Run: make models-llm (or: ollama pull {model})."
                )
        elif reachable and not models:
            base_url = str(body.get("base_url") or "")
            if "11434" in base_url or "ollama" in base_url.lower():
                reachable = False
                detail = (
                    f"Ollama is reachable but no model is installed. "
                    f"Run: make models-llm (or: ollama pull {model})."
                )
        return {
            "reachable": reachable,
            "status": "model-missing" if reachable is False and "not installed" in detail else (body.get("status") or ("ok" if reachable else "offline")),
            "model": model,
            "models": models,
            "detail": detail,
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {"reachable": False, "status": "offline", "detail": str(exc)}


async def ensure_available() -> None:
    status = await health()
    if not status.get("reachable"):
        raise LyricsUnavailable(
            "The local lyricist is offline. Start the LLM service and its model backend, then retry. "
            f"{status.get('detail') or ''}".strip()
        )


async def _complete(prompt: str, *, temperature: float) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "prompt": prompt,
        "temperature": temperature,
        "top_p": 0.92,
        "max_tokens": 1600,
        "stream": False,
    }
    if LLM_MODEL:
        payload["model"] = LLM_MODEL
    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT, headers=_headers()) as client:
            response = await client.post(f"{LLM_URL}/api/llm/complete", json=payload)
    except httpx.TimeoutException as exc:
        raise LyricsUnavailable(
            "The local lyricist timed out. Try a smaller model or a shorter brief."
        ) from exc
    except httpx.HTTPError as exc:
        raise LyricsUnavailable(
            "Could not reach the local lyricist. Check the LLM service and its model backend."
        ) from exc
    if response.status_code >= 400:
        detail = response.text[:500] if response.text else f"HTTP {response.status_code}"
        try:
            body = response.json()
            if isinstance(body, dict):
                value = body.get("detail") or body.get("error") or body.get("message")
                if isinstance(value, dict):
                    value = value.get("message") or value.get("detail")
                if value:
                    detail = str(value)[:1000]
        except (ValueError, TypeError):
            pass
        raise LyricsUnavailable(f"The local lyricist returned HTTP {response.status_code}: {detail}")
    try:
        body = response.json()
    except ValueError as exc:
        raise LyricsUnavailable("The local lyricist returned an unexpected response format.") from exc
    if not isinstance(body, dict):
        raise LyricsUnavailable("The local lyricist returned an unexpected response format.")
    return body


async def draft(request: LyricsDraftRequest) -> dict[str, Any]:
    """Generate an unsaved lyric draft. Raises LyricsUnavailable when offline."""
    system_prompt, user_prompt = build_prompt(request)
    base_prompt = f"{system_prompt}\n\n{user_prompt}"
    last_error = "The local lyricist returned an empty response."
    for attempt in range(2):
        prompt = base_prompt
        if attempt == 1:
            prompt += (
                "\n\nYour previous response was empty or lacked usable section headers. "
                "Return ONLY the lyrics with bracketed section headers. Do not explain anything."
            )
        body = await _complete(prompt, temperature=0.82 if attempt == 0 else 0.55)
        content = str(body.get("text") or "")
        if not content.strip():
            choices = ((body.get("raw") or {}).get("choices") or []) if isinstance(body.get("raw"), dict) else []
            if choices:
                content = str((choices[0].get("message") or {}).get("content") or "")
        sections = parse_sectioned_lyrics(content)
        if sections:
            return {
                "sections": sections,
                "provider": "llm",
                "model": body.get("model") or LLM_MODEL or None,
                "attempts": attempt + 1,
            }
        last_error = "The local model returned lyrics without usable section headers."
        log.warning("Lyrics draft attempt %s produced no sections", attempt + 1)
    raise LyricsError(last_error, 503)
