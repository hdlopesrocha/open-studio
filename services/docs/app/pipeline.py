"""PDF/text → translate → summarize → speech → subtitles → ZIP workflow."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError

from openstudio_common import (
    FILES_ROOT,
    JobContext,
    ffprobe,
    file_info,
    job_result,
    relative_path,
    resolve_path,
    utc_now,
)

from . import artifacts
from .clients import ServiceCallError, ServiceClients
from .config import settings
from .schemas import PipelineRequest
from .text import clean_text, join_texts, split_paragraphs, strip_page_markers, word_count

logger = logging.getLogger(__name__)

_TERMINAL_PUNCTUATION = re.compile(r"[.!?…:;][\"'”’»)\]]*$")
_CONTINUATION_WORDS = frozenset(
    {
        "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos",
        "das", "em", "no", "na", "nos", "nas", "por", "para", "com", "sem", "e",
        "ou", "que", "se", "como", "quando", "onde", "mas", "nem", "ao", "à",
        "às", "aos", "the", "an", "of", "in", "on", "at", "to", "for", "with",
        "and", "or", "but", "that", "which", "who", "as", "is", "was", "were",
        "are", "be", "been", "being", "from", "by", "not", "its", "their", "his",
        "her", "this", "these", "those",
    }
)

_STAGES = {
    "extract": (1.0, 20.0),
    "translate": (20.0, 46.0),
    "summarize": (46.0, 62.0),
    "tts": (62.0, 87.0),
    "subtitles": (87.0, 92.0),
    "archive": (93.0, 99.0),
}


class DocumentPipeline:
    def __init__(self, ctx: JobContext, config: PipelineRequest, clients: ServiceClients) -> None:
        self.ctx = ctx
        self.config = config
        self.clients = clients
        self.warnings: list[str] = []
        self.stats: dict[str, Any] = {}
        self.languages: dict[str, Any] = {}
        self.source: dict[str, Any] = {}
        self.base_text = ""
        self.base_segments: list[dict[str, Any]] = []
        self.base_canonical: str | None = None
        self.base_variant: str | None = None
        self.content_text = ""
        self.content_segments: list[dict[str, Any]] = []
        self.content_canonical: str | None = None
        self.content_variant: str | None = None
        self.summary_text: str | None = None
        self.summary_language: str | None = None
        self.tts_info: dict[str, Any] = {}
        self._files: dict[str, Path] = {}
        self.started = time.time()
        self.created_at = utc_now()

    # -- helpers -------------------------------------------------------

    async def _report(self, stage: str, fraction: float, message: str) -> None:
        low, high = _STAGES[stage]
        value = low + (high - low) * max(0.0, min(1.0, fraction))
        await self.ctx.report(value, stage=stage, message=message)

    async def _await(self, awaitable: Any) -> Any:
        """Await a long service call while polling for cancellation."""
        task = asyncio.ensure_future(awaitable)
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=2.0)
                if done:
                    return task.result()
                await self.ctx.check()
        except BaseException:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            raise

    def _warn(self, message: str) -> None:
        if message and message not in self.warnings:
            self.warnings.append(message)

    @staticmethod
    def _canonical(value: str | None) -> str | None:
        raw = (value or "").strip().lower().replace("_", "-")
        if not raw or raw in {"auto", "detect", "automatic"}:
            return None
        return raw.split("-")[0]

    @staticmethod
    def _variant(value: str | None) -> str | None:
        raw = (value or "").strip().replace("_", "-")
        lowered = raw.lower()
        if not lowered or lowered in {"auto", "detect", "automatic"}:
            return None
        if lowered in {"pt", "pt-pt"}:
            return "pt-PT"
        if lowered == "pt-br":
            return "pt-BR"
        return raw

    def _save_text(self, kind: str, text: str) -> dict[str, Any]:
        info = artifacts.write_text(self.ctx.job_id, kind, text)
        self._files[kind] = artifacts.text_path(self.ctx.job_id, kind)
        info.pop("text", None)
        return info

    @staticmethod
    def _continues_across_page(text: str) -> bool:
        stripped = text.strip()
        if not stripped or _TERMINAL_PUNCTUATION.search(stripped):
            return False
        if stripped.endswith(("-", "—", "–", ",", ":", ";")):
            return True
        words = re.findall(r"[A-Za-zÀ-ÿ]+", stripped)
        if not words:
            return False
        return len(stripped) >= 60 or words[-1].lower() in _CONTINUATION_WORDS

    def _segments_from_pages(self, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        segments: list[dict[str, Any]] = []
        for page in pages:
            page_number = page.get("page")
            paragraphs = page.get("paragraphs") or split_paragraphs(str(page.get("text") or ""))
            for index, paragraph in enumerate(paragraphs, start=1):
                text = clean_text(str(paragraph))
                if not text:
                    continue
                page_int = int(page_number) if page_number else None
                segments.append(
                    {
                        "id": f"p{page_int}-{index}" if page_int else f"t{len(segments) + 1}",
                        "page": page_int,
                        "text": text,
                    }
                )
        stitched: list[dict[str, Any]] = []
        for segment in segments:
            if stitched:
                previous = stitched[-1]
                if (
                    previous.get("page") is not None
                    and segment.get("page") is not None
                    and previous["page"] != segment["page"]
                    and self._continues_across_page(str(previous.get("text") or ""))
                ):
                    previous["text"] = (
                        f"{str(previous['text']).rstrip()} "
                        f"{str(segment.get('text') or '').lstrip()}"
                    ).strip()
                    continue
            stitched.append(dict(segment))
        return stitched

    @staticmethod
    def _render_segments(segments: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        previous_page: Any = object()
        for segment in segments:
            text = str(segment.get("text") or "").strip()
            if not text:
                continue
            page = segment.get("page")
            if page is not None and page != previous_page:
                parts.append(f"--- Page {int(page)} ---")
            parts.append(text)
            previous_page = page
        return ("\n\n".join(parts).strip() + "\n") if parts else ""

    def _translation_segments(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        segments: list[dict[str, Any]] = []
        for item in result.get("segments") or []:
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            page = item.get("page")
            segments.append(
                {
                    "id": item.get("id"),
                    "page": int(page) if page else None,
                    "text": text,
                }
            )
        if not segments:
            text = strip_page_markers(str(result.get("translated_text") or ""))
            for index, paragraph in enumerate(split_paragraphs(text), start=1):
                segments.append({"id": f"t{index}", "page": None, "text": paragraph})
        return segments

    def _translation_text(self, result: dict[str, Any], segments: list[dict[str, Any]]) -> str:
        display = str(result.get("translated_text") or "")
        if display.strip():
            return display if display.endswith("\n") else display + "\n"
        rendered = self._render_segments(segments)
        return rendered or (join_texts(segment["text"] for segment in segments) + "\n")

    async def _detect_language(self, text: str) -> tuple[str | None, str | None]:
        try:
            payload = await self._await(self.clients.detect_language(text))
        except ServiceCallError as exc:
            self._warn(f"Language detection was unavailable: {exc.message}")
            return None, None
        canonical = payload.get("canonical") or payload.get("language")
        variant = payload.get("variant") or payload.get("language")
        return (
            str(canonical) if canonical else None,
            str(variant) if variant else None,
        )

    async def _ensure_content_language(self) -> None:
        if self.content_variant:
            return
        canonical, variant = await self._detect_language(self.content_text or self.base_text)
        if canonical:
            self.content_canonical = self.content_canonical or canonical
            self.content_variant = variant or canonical
        if self.base_canonical is None:
            self.base_canonical = canonical
            self.base_variant = variant
        if not self.content_canonical:
            self.content_canonical = "en"
            self.content_variant = "en"
            self._warn("The content language could not be detected; English was assumed.")

    # -- stage: extract ------------------------------------------------

    async def _extract(self) -> None:
        await self._report("extract", 0.02, "Reading the document.")
        config = self.config
        if config.input.type == "text":
            text = clean_text(config.input.text or "")
            if not text:
                raise HTTPException(status_code=422, detail="The pasted text is empty")
            pages = [
                {
                    "page": None,
                    "text": text,
                    "paragraphs": split_paragraphs(text),
                    "char_count": len(text),
                }
            ]
            display = text + ("" if text.endswith("\n") else "\n")
            self.source = {
                "type": "text",
                "filename": "Pasted text",
                "page_count": 0,
                "selected_pages": [],
                "ocr_enabled": False,
            }
            await self._report("extract", 0.75, "Prepared the pasted text.")
        else:
            payload: dict[str, Any] = {
                "path": config.input.pdf_path,
                "ocr_enabled": config.input.ocr_enabled,
            }
            if config.input.ocr_language:
                payload["ocr_language"] = config.input.ocr_language
            if config.input.selected_pages:
                payload["selected_pages"] = config.input.selected_pages
            if config.input.start_page is not None:
                payload["start_page"] = config.input.start_page
            if config.input.end_page is not None:
                payload["end_page"] = config.input.end_page
            await self._report("extract", 0.15, "Extracting text from the PDF.")
            result = await self._await(self.clients.extract_pdf(payload))
            pages = result.get("pages") or []
            display = str(result.get("plain_text") or "")
            if not display.strip():
                display = self._render_segments(self._segments_from_pages(pages))
            self.source = {
                "type": "pdf",
                "path": result.get("path") or config.input.pdf_path,
                "filename": result.get("filename") or Path(config.input.pdf_path or "").name,
                "title": result.get("title") or "",
                "page_count": result.get("page_count"),
                "selected_pages": result.get("selected_pages") or [],
                "ocr_enabled": bool(result.get("ocr_enabled")),
                "ocr_language": result.get("ocr_language"),
                "ocr_pages": result.get("ocr_pages") or [],
                "scanned_pages": result.get("scanned_pages") or [],
                "warnings": result.get("warnings") or [],
            }
            for warning in result.get("warnings") or []:
                self._warn(str(warning))
            await self._report("extract", 0.85, "PDF text extracted.")
        segments = self._segments_from_pages(pages)
        if not segments:
            raise HTTPException(
                status_code=422,
                detail="No readable text was found in the selected document.",
            )
        if len(segments) > settings.max_segments:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"The document produced {len(segments):,} paragraphs, above the "
                    f"{settings.max_segments:,}-paragraph limit. Select fewer pages."
                ),
            )
        self.base_segments = segments
        self.base_text = join_texts(segment["text"] for segment in segments)
        self.content_segments = list(segments)
        self.content_text = self.base_text
        if config.input.language and config.input.language.lower() != "auto":
            self.base_canonical = self._canonical(config.input.language)
            self.base_variant = self._variant(config.input.language)
            self.content_canonical = self.base_canonical
            self.content_variant = self.base_variant
        self.languages["source"] = self.base_variant or self.base_canonical or "auto"
        self.languages["content"] = self.content_variant or self.content_canonical or "auto"
        self.stats["extracted_words"] = word_count(self.base_text)
        self.stats["extracted_characters"] = len(self.base_text)
        self.stats["pages"] = len([page for page in pages if str(page.get("text") or "").strip()])
        self._save_text("extracted", display)
        await self._report(
            "extract",
            1.0,
            f"Prepared {self.stats['extracted_words']:,} words from "
            f"{len(segments)} paragraph(s).",
        )

    # -- stage: translate ----------------------------------------------

    async def _translate(self) -> None:
        config = self.config
        if not config.translation.enabled:
            self.languages["content"] = self.content_variant or self.content_canonical or "auto"
            return
        await self._report("translate", 0.02, f"Translating into {config.translation.target_language}.")
        if not self.base_segments:
            raise HTTPException(status_code=422, detail="There is no text to translate")
        payload = config.translation.params()
        payload["segments"] = self.base_segments
        result = await self._await(self.clients.translate(payload))
        segments = self._translation_segments(result)
        if not segments:
            raise HTTPException(
                status_code=502,
                detail="The translation service returned no translated text",
            )
        self._save_text("translation", self._translation_text(result, segments))
        if not self.base_canonical:
            self.base_canonical = result.get("source_language")
            self.base_variant = result.get("source_language_variant") or self.base_canonical
        target_canonical = result.get("target_language_code") or self._canonical(
            result.get("target_language") or config.translation.target_language
        )
        target_variant = result.get("target_language") or config.translation.target_language
        self.content_segments = segments
        self.content_text = join_texts(segment["text"] for segment in segments)
        self.content_canonical = target_canonical
        self.content_variant = target_variant
        self.languages.update(
            {
                "source": self.base_variant or self.base_canonical,
                "translation_source": result.get("source_language"),
                "translation_target": target_variant,
                "translation_target_canonical": target_canonical,
                "content": target_variant,
            }
        )
        self.stats["translated_words"] = word_count(self.content_text)
        self.stats["translated_characters"] = len(self.content_text)
        self.stats["translation_model"] = result.get("model")
        for warning in result.get("warnings") or []:
            self._warn(str(warning))
        if result.get("detected_source_language"):
            self.languages["source_detected"] = True
        await self._report(
            "translate",
            1.0,
            f"Translation ready ({self.stats['translated_words']:,} words).",
        )

    # -- stage: summarize ----------------------------------------------

    async def _summarize(self) -> None:
        config = self.config
        if not config.summary.enabled:
            return
        use_translation = config.summary.from_translation and config.translation.enabled
        text = self.content_text if use_translation else self.base_text
        canonical = self.content_canonical if use_translation else self.base_canonical
        variant = self.content_variant if use_translation else self.base_variant
        if not text.strip():
            raise HTTPException(status_code=422, detail="There is no text to summarize")
        if not variant and not canonical:
            await self._ensure_content_language()
            canonical = self.content_canonical if use_translation else self.base_canonical
            variant = self.content_variant if use_translation else self.base_variant
        language = config.summary.language
        if not language or language.lower() in {"auto", "detect", "automatic"}:
            language = variant
        payload = config.summary.params()
        payload["text"] = text
        payload["language"] = language
        payload["source_language"] = (
            config.summary.source_language
            if config.summary.source_language and config.summary.source_language.lower() != "auto"
            else (canonical or "auto")
        )
        await self._report(
            "summarize",
            0.05,
            f"Summarizing {word_count(text):,} words ({config.summary.length}).",
        )
        result = await self._await(self.clients.summarize(payload))
        summary = str(result.get("summary") or "").strip()
        if not summary:
            raise HTTPException(
                status_code=502,
                detail="The summarization service returned an empty summary",
            )
        self.summary_text = summary
        self.summary_language = result.get("language") or language or variant
        self._save_text("summary", summary + "\n")
        self.languages["summary"] = self.summary_language
        self.stats["summary_words"] = word_count(summary)
        self.stats["summary_input_words"] = result.get("input_words")
        self.stats["summary_chunks"] = result.get("chunk_count")
        self.stats["summary_levels"] = result.get("hierarchy_levels")
        self.stats["summary_model"] = result.get("model")
        for warning in result.get("warnings") or []:
            self._warn(str(warning))
        await self._report(
            "summarize",
            1.0,
            f"Summary ready ({self.stats['summary_words']:,} words).",
        )

    # -- stage: speech -------------------------------------------------

    def _normalize_timeline(self, value: Any) -> list[dict[str, Any]]:
        timeline: list[dict[str, Any]] = []
        if not isinstance(value, list):
            return timeline
        for index, item in enumerate(value, start=1):
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or item.get("sentence") or "").strip()
            if not text:
                continue
            start = float(item.get("start", item.get("start_time", 0)) or 0)
            end = float(item.get("end", item.get("end_time", start + 0.5)) or start + 0.5)
            if end <= start:
                end = start + 0.35
            timeline.append(
                {
                    "index": int(item.get("index", index) or index),
                    "text": text,
                    "start": round(max(0.0, start), 3),
                    "end": round(max(start + 0.05, end), 3),
                }
            )
        return timeline

    @staticmethod
    def _estimate_timeline(text: str, duration: float) -> list[dict[str, Any]]:
        sentences = [
            part.strip()
            for part in re.split(r"(?<=[.!?…])\s+|\n+", text)
            if part.strip()
        ]
        if not sentences:
            sentences = [text.strip()]
        units = [max(1, len(sentence)) for sentence in sentences]
        total = float(sum(units)) or 1.0
        cursor = 0.0
        timeline = []
        for index, (sentence, unit) in enumerate(zip(sentences, units), start=1):
            end = duration if index == len(sentences) else min(duration, cursor + duration * unit / total)
            timeline.append(
                {
                    "index": index,
                    "text": sentence,
                    "start": round(cursor, 3),
                    "end": round(max(cursor + 0.1, end), 3),
                }
            )
            cursor = end
        return timeline

    def _resolve_file(self, value: Any) -> Path:
        if isinstance(value, dict):
            value = value.get("path")
        raw = str(value or "").strip()
        if not raw:
            raise HTTPException(status_code=502, detail="The voice service did not return an audio path")
        path = Path(raw)
        if path.is_absolute():
            resolved = path.resolve()
            root = FILES_ROOT.resolve()
            if resolved != root and root not in resolved.parents:
                raise HTTPException(
                    status_code=422,
                    detail="The voice service returned an audio path outside the shared files root",
                )
            return resolved
        return resolve_path(raw)

    def _copy_into_job(self, source: Path, filename: str) -> Path:
        if not source.is_file():
            raise HTTPException(
                status_code=502,
                detail=f"The generated audio file is missing: {source.name}",
            )
        destination = artifacts.job_dir(self.ctx.job_id) / filename
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        return destination

    @staticmethod
    def _response_path(payload: dict[str, Any]) -> str | None:
        for key in ("path", "relative_path", "output_path", "file"):
            value = payload.get(key)
            if isinstance(value, dict):
                value = value.get("path")
            if value:
                return str(value)
        return None

    async def _finalize_audio(self, source: Path, format_name: str, normalize: bool) -> Path | None:
        output = artifacts.job_dir(self.ctx.job_id) / f"audio.{format_name}"
        try:
            response = await self._await(
                self.clients.ffmpeg_finalize(
                    {
                        "source_path": relative_path(source),
                        "output_path": relative_path(output),
                        "format": format_name,
                        "normalize_audio": bool(normalize),
                        "title": self.config.title or self.ctx.job_id,
                    }
                )
            )
        except ServiceCallError as exc:
            self._warn(
                f"The audio could not be finalized/normalized with FFmpeg ({exc.message}); "
                "the voice output was kept."
            )
            return None
        candidate = self._response_path(response)
        if candidate:
            try:
                path = self._resolve_file(candidate)
            except HTTPException:
                path = None
            if path and path.is_file():
                if path.parent != output.parent or path.name != output.name:
                    output = self._copy_into_job(path, output.name)
                return output
        if output.is_file():
            return output
        self._warn("FFmpeg returned no finalized audio; the voice output was kept.")
        return None

    async def _synthesize(self) -> None:
        config = self.config
        if not config.tts.enabled:
            if config.subtitles.enabled:
                self._warn("Subtitles were requested but speech synthesis is disabled; no timeline is available.")
            return
        if config.tts.text_source == "summary":
            speech_text = self.summary_text or ""
            language = self.summary_language
        else:
            speech_text = self.content_text
            language = self.content_variant
        speech_text = clean_text(strip_page_markers(speech_text))
        if not speech_text:
            raise HTTPException(status_code=422, detail="There is no text to synthesize")
        if len(speech_text) > settings.max_tts_chars:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"The speech text exceeds the {settings.max_tts_chars}-character limit. "
                    "Select fewer pages or narrate the summary."
                ),
            )
        if not language:
            canonical, variant = await self._detect_language(speech_text[:20_000])
            language = variant or canonical or "en"
            self.languages["speech_detected"] = True
            if canonical and not self.content_canonical:
                self.content_canonical = canonical
                self.content_variant = variant or canonical
                self.languages["content"] = self.content_variant
        language = self._variant(config.tts.language) or language
        await self._report("tts", 0.04, f"Synthesizing speech with {config.tts.engine}.")
        payload = config.tts.params(speech_text, language)
        result = await self._await(self.clients.tts_sync(payload))
        source_value = result.get("path") or result.get("audio_path") or result.get("relative_path")
        source = self._resolve_file(source_value)
        format_name = str(result.get("format") or config.tts.format or source.suffix.lstrip(".")).lower().lstrip(".")
        if not format_name:
            format_name = "mp3"
        needs_finalize = config.tts.finalize_with_ffmpeg and (
            config.tts.normalize_audio or source.suffix.lower() != f".{format_name}"
        )
        destination: Path | None = None
        finalized = False
        if needs_finalize:
            await self._report("tts", 0.55, "Finalizing audio with FFmpeg.")
            destination = await self._finalize_audio(
                source, format_name, config.tts.normalize_audio
            )
            finalized = destination is not None
        if destination is None:
            suffix = source.suffix if source.suffix else f".{format_name}"
            if source.suffix and source.suffix.lower().lstrip(".") != format_name:
                format_name = source.suffix.lower().lstrip(".")
            destination = self._copy_into_job(source, f"audio{suffix}")
        self._files["audio"] = destination
        duration = float(result.get("duration_seconds") or 0.0)
        if duration <= 0:
            try:
                probe = await ffprobe(destination)
                duration = float(probe.get("duration") or 0.0)
            except Exception:  # noqa: BLE001
                duration = 0.0
        wav_value = result.get("wav_path") or result.get("master_wav")
        if wav_value and format_name != "wav":
            try:
                wav_source = self._resolve_file(wav_value)
                self._files["wav"] = self._copy_into_job(wav_source, "master.wav")
            except HTTPException as exc:
                self._warn(f"The WAV master could not be copied: {exc.detail}")
        timeline = self._normalize_timeline(result.get("timeline") or result.get("segments"))
        timeline_method = "voice" if timeline else "estimated"
        if not timeline and duration > 0 and config.subtitles.enabled:
            timeline = self._estimate_timeline(speech_text, duration)
            self._warn(
                "The voice service did not return a timeline; subtitle timings were estimated "
                "proportionally to the text length."
            )
        self.tts_info = {
            "engine": result.get("engine") or config.tts.engine,
            "voice_id": result.get("voice_id") or config.tts.voice_id,
            "piper_voice": result.get("piper_voice") or config.tts.piper_voice,
            "voice": result.get("voice") or result.get("voice_name"),
            "language": result.get("language") or language,
            "format": format_name,
            "duration_seconds": round(duration, 3),
            "normalized": bool(config.tts.normalize_audio and finalized),
            "text_source": config.tts.text_source,
            "timeline_method": timeline_method if timeline else None,
            "timeline": timeline,
            "audio_path": relative_path(destination),
            "wav_path": relative_path(self._files["wav"]) if "wav" in self._files else None,
        }
        self.languages["speech"] = self.tts_info["language"]
        self.stats["speech_seconds"] = round(duration, 3)
        self.stats["speech_characters"] = len(speech_text)
        self.stats["subtitle_cues"] = len(timeline)
        if config.subtitles.enabled:
            await self._report("subtitles", 0.1, "Aligning subtitles to the speech timeline.")
            if timeline:
                subtitles = artifacts.write_subtitles(self.ctx.job_id, timeline)
                self._files["subtitles"] = artifacts.job_dir(self.ctx.job_id) / "subtitles.srt"
                self._files["captions"] = artifacts.job_dir(self.ctx.job_id) / "captions.vtt"
                self.stats["subtitle_cues"] = int(subtitles.get("cues") or len(timeline))
                if timeline_method != "voice":
                    self._warn("Subtitle timings were estimated from the audio duration.")
                await self._report("subtitles", 1.0, f"Wrote {self.stats['subtitle_cues']} subtitle cues.")
            else:
                self._warn(
                    "Subtitles were skipped because neither a timeline nor an audio duration was available."
                )
        await self._report("tts", 1.0, f"Speech ready ({duration:.1f}s).")

    # -- stage: archive ------------------------------------------------

    def _manifest(self) -> dict[str, Any]:
        artifact_entries: dict[str, Any] = {}
        for kind, path in self._files.items():
            if path.is_file():
                try:
                    artifact_entries[kind] = file_info(path)
                except ValueError:
                    artifact_entries[kind] = {"name": path.name, "available": True}
        return {
            "job_id": self.ctx.job_id,
            "title": self.config.title or "Document workflow",
            "status": "completed",
            "created_at": self.created_at,
            "completed_at": utc_now(),
            "generator": "Open Studio documents",
            "config": self.config.public_config(),
            "source": self.source,
            "languages": self.languages,
            "stats": self.stats,
            "warnings": self.warnings,
            "artifacts": artifact_entries,
            "audio": {
                key: value
                for key, value in self.tts_info.items()
                if key != "timeline"
            },
            "timeline": self.tts_info.get("timeline") or [],
        }

    async def _archive(self) -> dict[str, Any]:
        await self._report("archive", 0.05, "Writing the manifest.")
        manifest = self._manifest()
        manifest_path = artifacts.write_manifest(self.ctx.job_id, manifest)
        self._files["manifest"] = artifacts.manifest_path(self.ctx.job_id)
        manifest["artifacts"] = {
            kind: file_info(path)
            for kind, path in self._files.items()
            if path.is_file()
        }
        artifacts.write_manifest(self.ctx.job_id, manifest)
        zip_info: dict[str, Any] | None = None
        if self.config.zip.enabled:
            await self._report("archive", 0.45, "Building the ZIP bundle.")
            try:
                zip_info = artifacts.build_zip(self.ctx.job_id)
                self._files["zip"] = artifacts.job_dir(self.ctx.job_id) / "output.zip"
                manifest["artifacts"]["zip"] = zip_info
                artifacts.write_manifest(self.ctx.job_id, manifest)
                self.stats["zip_bytes"] = zip_info.get("size")
            except Exception as exc:  # noqa: BLE001
                logger.exception("Could not build the documents ZIP")
                self._warn(f"The ZIP bundle could not be created: {exc}")
        await self._report("archive", 1.0, "Document bundle ready.")
        files = [
            file_info(path)
            for path in self._files.values()
            if path.is_file()
        ]
        unique: dict[str, dict[str, Any]] = {}
        for entry in files:
            unique[entry["path"]] = entry
        text_paths = {
            kind: relative_path(path)
            for kind, path in self._files.items()
            if kind in {"extracted", "translation", "summary"} and path.is_file()
        }
        data = {
            "text_paths": text_paths,
            "manifest_path": relative_path(artifacts.manifest_path(self.ctx.job_id)),
            "zip_path": relative_path(artifacts.job_dir(self.ctx.job_id) / "output.zip")
            if (artifacts.job_dir(self.ctx.job_id) / "output.zip").is_file()
            else None,
            "source": self.source,
            "languages": self.languages,
            "stats": self.stats,
            "warnings": self.warnings,
            "audio": {
                key: value for key, value in self.tts_info.items() if key != "timeline"
            },
            "subtitles": {
                "cues": self.stats.get("subtitle_cues"),
                "srt": relative_path(self._files["subtitles"]) if "subtitles" in self._files else None,
                "vtt": relative_path(self._files["captions"]) if "captions" in self._files else None,
            },
        }
        parts = [f"{self.stats.get('extracted_words', 0):,} words extracted"]
        if "translation" in self._files:
            parts.append("translation")
        if "summary" in self._files:
            parts.append("summary")
        if "audio" in self._files:
            parts.append(f"{self.stats.get('speech_seconds', 0):.0f}s audio")
        if "subtitles" in self._files:
            parts.append(f"{self.stats.get('subtitle_cues', 0)} cues")
        return job_result(
            files=list(unique.values()),
            data=data,
            message="Document workflow complete: " + ", ".join(parts) + ".",
        )

    # -- run -----------------------------------------------------------

    async def run(self) -> dict[str, Any]:
        await self.ctx.check()
        await self._extract()
        await self.ctx.check()
        await self._translate()
        await self.ctx.check()
        await self._summarize()
        await self.ctx.check()
        await self._synthesize()
        await self.ctx.check()
        result = await self._archive()
        await self.ctx.check()
        await self.ctx.report(100, stage="complete", message="Document workflow complete.")
        return result


async def run_pipeline_job(ctx: JobContext) -> dict[str, Any]:
    try:
        config = PipelineRequest.model_validate(ctx.params or {})
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid pipeline configuration: {exc.errors()}",
        ) from exc
    clients = ServiceClients(settings)
    try:
        return await DocumentPipeline(ctx, config, clients).run()
    except ServiceCallError as exc:
        logger.warning("Documents pipeline dependency failed: %s: %s", exc.service, exc.message)
        raise HTTPException(
            status_code=exc.status_code,
            detail=f"{exc.service}: {exc.message}",
        ) from exc
    finally:
        await clients.close()
