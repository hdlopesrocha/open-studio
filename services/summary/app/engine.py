"""Lazy T5 summarization with hierarchical map-reduce."""

from __future__ import annotations

import gc
import importlib.util
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx
from fastapi import HTTPException

from openstudio_common import JobCancelled, jobhub_headers

from .config import Settings
from .languages import SummaryLanguages
from .text import (
    clean_text,
    sentence_split,
    split_long_piece,
    split_paragraphs,
    word_count,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]
CancelCallback = Callable[[], bool]

_WEIGHT_FILES = (
    "model.safetensors",
    "pytorch_model.bin",
    "model.safetensors.index.json",
    "pytorch_model.bin.index.json",
)
_TOKENIZER_FILES = ("tokenizer.json", "spiece.model", "tokenizer_config.json")

MODEL_ALIASES = {
    "auto": "auto",
    "en": "t5-small-en",
    "english": "t5-small-en",
    "t5-en": "t5-small-en",
    "t5-small-en": "t5-small-en",
    "farleyknight/cnn_dailymail-summarization-t5-small-2022-09-08": "t5-small-en",
    "pt": "t5-small-pt",
    "portuguese": "t5-small-pt",
    "pt-pt": "t5-small-pt",
    "pt-br": "t5-small-pt",
    "t5-pt": "t5-small-pt",
    "t5-small-pt": "t5-small-pt",
    "rhaymison/t5-portuguese-small-summarization": "t5-small-pt",
}


@dataclass
class SummaryOptions:
    length: str = "medium"
    max_tokens: int | None = None
    min_tokens: int | None = None
    num_beams: int = 3
    temperature: float = 0.0
    chunk_tokens: int | None = None
    hierarchical: bool = True


@dataclass
class SummaryModel:
    id: str
    language: str
    repo: str
    path: Path
    label: str


@dataclass
class LoadedSummaryModel:
    model_id: str
    language: str
    model: Any
    tokenizer: Any
    loaded_at: float
    last_used: float


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _folder_ready(folder: Path) -> bool:
    if not folder.is_dir() or not (folder / "config.json").is_file():
        return False
    has_weights = any((folder / name).is_file() for name in _WEIGHT_FILES)
    has_tokenizer = any((folder / name).is_file() for name in _TOKENIZER_FILES)
    return has_weights and has_tokenizer


class SummarizationEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        self._current: LoadedSummaryModel | None = None
        self._torch: Any | None = None
        self._threads_configured = False

    # -- discovery -----------------------------------------------------

    def model_dir(self, language: str) -> Path:
        return Path(self.settings.model_directories[language])

    def model_available(self, language: str) -> bool:
        return _folder_ready(self.model_dir(language))

    def model_entries(self) -> list[dict[str, Any]]:
        items = []
        for language, model_id in (("en", "t5-small-en"), ("pt", "t5-small-pt")):
            repo = self.settings.model_repositories[language]
            path = self.model_dir(language)
            available = self.model_available(language)
            items.append(
                {
                    "id": model_id,
                    "name": (
                        "T5 small — English summaries"
                        if language == "en"
                        else "T5 small — Portuguese summaries"
                    ),
                    "language": language,
                    "family": "t5",
                    "repo": repo,
                    "path": str(path),
                    "available": available,
                    "installed": available,
                    "requires": ["torch", "transformers", "sentencepiece"],
                }
            )
        return items

    def models_payload(self) -> dict[str, Any]:
        items = self.model_entries()
        return {
            "items": items,
            "total": len(items),
            "default": "auto",
            "loaded": self._current.model_id if self._current else None,
            "length_budgets": self.settings.token_budgets,
            "defaults": {
                "length": "medium",
                "num_beams": self.settings.num_beams,
                "temperature": 0.0,
                "chunk_tokens": self.settings.max_input_tokens,
                "hierarchical": True,
            },
            "parameters": [
                {"name": "length", "type": "string", "values": ["short", "medium", "long"]},
                {"name": "max_tokens", "type": "integer", "min": 16, "max": 4096},
                {"name": "min_tokens", "type": "integer", "min": 0, "max": 4096},
                {"name": "num_beams", "type": "integer", "min": 1, "max": 16},
                {"name": "temperature", "type": "number", "min": 0, "max": 2},
                {"name": "chunk_tokens", "type": "integer", "min": 64, "max": 2048},
                {"name": "hierarchical", "type": "boolean"},
            ],
            "runtime": {
                "torch": _module_available("torch"),
                "transformers": _module_available("transformers"),
                "sentencepiece": _module_available("sentencepiece"),
                "langdetect": _module_available("langdetect"),
            },
        }

    def status(self) -> dict[str, Any]:
        current = self._current
        return {
            "loaded_model": current.model_id if current else None,
            "loaded_language": current.language if current else None,
            "loaded_since": round(current.loaded_at, 3) if current else None,
            "available": {
                language: self.model_available(language) for language in ("en", "pt")
            },
            "model_ids": {
                "en": "t5-small-en",
                "pt": "t5-small-pt",
            },
            "model_repositories": self.settings.model_repositories,
            "models_dir": self.settings.models_dir,
            "device": "cpu",
            "cpu_threads": self.settings.cpu_threads,
            "runtime": {
                "torch": _module_available("torch"),
                "transformers": _module_available("transformers"),
                "sentencepiece": _module_available("sentencepiece"),
                "langdetect": _module_available("langdetect"),
            },
            "length_budgets": self.settings.token_budgets,
            "limits": {
                "max_input_chars": self.settings.max_input_chars,
                "max_input_tokens": self.settings.max_input_tokens,
                "max_chunks": self.settings.max_chunks,
                "max_output_tokens": self.settings.max_output_tokens,
            },
        }

    def resolve_model(self, requested: str | None, language: str) -> SummaryModel:
        raw = (requested or "auto").strip()
        model_id = MODEL_ALIASES.get(raw.lower(), raw)
        if model_id == "auto":
            model_id = f"t5-small-{language}"
        if model_id not in {"t5-small-en", "t5-small-pt"}:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Unknown summary model '{requested}'. "
                    "Available models: t5-small-en, t5-small-pt"
                ),
            )
        model_language = "en" if model_id.endswith("-en") else "pt"
        if model_language != language:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{model_id} is a {model_language} model but the source text is {language}. "
                    "Use model=auto or select a matching source language."
                ),
            )
        path = self.model_dir(language)
        if not self.model_available(language):
            raise HTTPException(
                status_code=503,
                detail=(
                    f"The summarization model for {language} is not installed in {path}. "
                    "Install it with: docker compose run --rm summary download-models "
                    f"--models {model_id}"
                ),
            )
        return SummaryModel(
            id=model_id,
            language=language,
            repo=self.settings.model_repositories[language],
            path=path,
            label=self.model_entries()[0 if language == "en" else 1]["name"],
        )

    # -- runtime -------------------------------------------------------

    def _torch_module(self) -> Any:
        if self._torch is not None:
            return self._torch
        if not _module_available("torch"):
            raise HTTPException(
                status_code=503,
                detail="PyTorch is not installed in the summary service image.",
            )
        import torch  # type: ignore

        if not self._threads_configured:
            torch.set_num_threads(max(1, self.settings.cpu_threads))
            try:
                torch.set_num_interop_threads(max(1, min(self.settings.cpu_threads, 4)))
            except RuntimeError:
                pass
            self._threads_configured = True
        self._torch = torch
        return torch

    def _load(self, model: SummaryModel) -> LoadedSummaryModel:
        if self._current and self._current.model_id == model.id:
            self._current.last_used = time.time()
            return self._current
        if self._current:
            logger.info("Unloading summary model %s", self._current.model_id)
            self._current.model = None
            self._current.tokenizer = None
            self._current = None
            gc.collect()
        if not _folder_ready(model.path):
            raise HTTPException(
                status_code=503,
                detail=f"The summarization model '{model.id}' is not installed.",
            )
        try:
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=503,
                detail=(
                    "The summarization runtime (transformers) is not installed. "
                    "Rebuild the summary service image."
                ),
            ) from exc
        logger.info("Loading summary model %s from %s", model.id, model.path)
        started = time.time()
        try:
            tokenizer = AutoTokenizer.from_pretrained(str(model.path), local_files_only=True)
            loaded_model = AutoModelForSeq2SeqLM.from_pretrained(
                str(model.path), local_files_only=True
            )
            loaded_model.to("cpu")
            loaded_model.eval()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to load summary model %s", model.id)
            raise HTTPException(
                status_code=503,
                detail=(
                    f"The summarization model '{model.id}' could not be loaded. "
                    "Reinstall the model files and try again."
                ),
            ) from exc
        loaded = LoadedSummaryModel(
            model_id=model.id,
            language=model.language,
            model=loaded_model,
            tokenizer=tokenizer,
            loaded_at=started,
            last_used=time.time(),
        )
        self._current = loaded
        logger.info("Loaded %s in %.1fs", model.id, time.time() - started)
        return loaded

    # -- tokenisation and chunking -------------------------------------

    def _token_length(self, tokenizer: Any, text: str) -> int:
        try:
            return len(tokenizer.encode(text, add_special_tokens=False))
        except Exception:  # noqa: BLE001
            return max(1, len(text) // 4)

    def _effective_input_tokens(self, tokenizer: Any, requested: int | None) -> int:
        model_max = int(getattr(tokenizer, "model_max_length", 512) or 512)
        if model_max > 4096:
            model_max = 512
        wanted = max(64, int(requested or self.settings.max_input_tokens))
        return min(model_max, max(64, wanted), 1024)

    def _split_sentence_to_fit(self, tokenizer: Any, sentence: str, max_tokens: int) -> list[str]:
        pieces: list[str] = []
        words = sentence.split()
        current: list[str] = []
        for word in words:
            candidate = " ".join(current + [word]).strip()
            if current and self._token_length(tokenizer, candidate) > max_tokens:
                pieces.append(" ".join(current))
                current = [word]
            else:
                current.append(word)
        if current:
            pieces.append(" ".join(current))
        safe: list[str] = []
        for piece in pieces:
            if self._token_length(tokenizer, piece) <= max_tokens:
                safe.append(piece)
                continue
            tokens = max(1, self._token_length(tokenizer, piece))
            step = max(50, int(len(piece) * max_tokens / tokens) // 2)
            for start in range(0, len(piece), step):
                safe.append(piece[start : start + step])
        return [piece for piece in safe if piece.strip()]

    def _chunk_text(self, tokenizer: Any, text: str, chunk_tokens: int) -> list[str]:
        max_tokens = max(64, chunk_tokens - 12)
        sentences: list[str] = []
        for paragraph in split_paragraphs(text):
            for sentence in sentence_split(paragraph):
                for piece in split_long_piece(sentence, max(400, chunk_tokens * 3)):
                    if self._token_length(tokenizer, piece) > max_tokens:
                        sentences.extend(self._split_sentence_to_fit(tokenizer, piece, max_tokens))
                    else:
                        sentences.append(piece)
        chunks: list[str] = []
        current: list[str] = []
        current_tokens = 0
        for sentence in sentences:
            tokens = self._token_length(tokenizer, sentence) + 1
            if current and current_tokens + tokens > max_tokens:
                chunks.append(" ".join(current))
                current = [sentence]
                current_tokens = tokens
            else:
                current.append(sentence)
                current_tokens += tokens
        if current:
            chunks.append(" ".join(current))
        return [chunk for chunk in chunks if chunk.strip()]

    def _group_summaries(self, tokenizer: Any, summaries: list[str], max_tokens: int) -> list[str]:
        groups: list[str] = []
        current: list[str] = []
        current_tokens = 0
        for summary in summaries:
            tokens = self._token_length(tokenizer, summary) + 1
            if current and current_tokens + tokens > max_tokens:
                groups.append("\n\n".join(current))
                current = [summary]
                current_tokens = tokens
            else:
                current.append(summary)
                current_tokens += tokens
        if current:
            groups.append("\n\n".join(current))
        return groups

    # -- generation ----------------------------------------------------

    def _generate(
        self,
        loaded: LoadedSummaryModel,
        text: str,
        max_tokens: int,
        min_tokens: int,
        options: SummaryOptions,
        input_tokens: int,
    ) -> str:
        prefix = self.settings.prompt_en if loaded.language == "en" else self.settings.prompt_pt
        prompt = prefix + text.strip()
        encoded = loaded.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=max(64, input_tokens),
        )
        if int(encoded["input_ids"].shape[-1]) < 4:
            return ""
        model_max = int(getattr(loaded.model.config, "max_length", 512) or 512)
        if model_max <= 0 or model_max > 4096:
            model_max = 512
        max_new = max(8, min(int(max_tokens), model_max))
        kwargs: dict[str, Any] = {
            "max_new_tokens": max_new,
            "num_beams": max(1, int(options.num_beams)),
            "early_stopping": True,
            "no_repeat_ngram_size": 3,
            "length_penalty": 1.0,
        }
        if min_tokens > 0:
            kwargs["min_new_tokens"] = min(int(min_tokens), max_new - 1)
        if options.temperature and options.temperature > 0:
            kwargs["do_sample"] = True
            kwargs["temperature"] = float(options.temperature)
        try:
            torch = self._torch_module()
            with torch.inference_mode():
                generated = loaded.model.generate(**encoded, **kwargs)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Summary generation failed")
            raise HTTPException(
                status_code=500,
                detail="The local summarization model failed to generate a summary.",
            ) from exc
        result = loaded.tokenizer.batch_decode(generated, skip_special_tokens=True)[0]
        result = clean_text(result)
        result = re.sub(
            r"^(?:summari[sz]e|sumarize|resuma|resumo)\s*:\s*", "", result, flags=re.I
        )
        return result.strip()

    def _translate_summary(self, summary: str, languages: SummaryLanguages) -> str:
        url = f"{self.settings.translation_service_url.rstrip('/')}/internal/translate"
        try:
            with httpx.Client(
                timeout=self.settings.translation_timeout_seconds,
                headers=jobhub_headers(),
            ) as client:
                response = client.post(
                    url,
                    json={
                        "text": summary,
                        "source_language": languages.source,
                        "target_language": languages.target_variant,
                        "model": "auto",
                    },
                )
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=504,
                detail="The summary was generated but the translation request timed out.",
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    "The translation service is unavailable, so the summary could not be "
                    "produced in the requested language."
                ),
            ) from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise HTTPException(
                status_code=502,
                detail=f"The summary translation failed: {detail}",
            )
        translated = clean_text(str(response.json().get("translated_text") or ""))
        if not translated:
            raise HTTPException(
                status_code=502,
                detail="The translation service returned an empty summary.",
            )
        return translated

    # -- public summarization -----------------------------------------

    def _budget(self, options: SummaryOptions) -> int:
        if options.max_tokens:
            budget = int(options.max_tokens)
        else:
            budget = self.settings.token_budgets.get(options.length, self.settings.medium_tokens)
        return max(16, min(self.settings.max_output_tokens, budget))

    def summarize(
        self,
        text: str,
        languages: SummaryLanguages,
        options: SummaryOptions,
        model_requested: str | None = None,
        progress: ProgressCallback | None = None,
        cancel: CancelCallback | None = None,
    ) -> dict[str, Any]:
        started = time.time()
        if not text.strip():
            raise HTTPException(status_code=422, detail="There is no text to summarize.")
        if len(text) > self.settings.max_input_chars:
            raise HTTPException(
                status_code=413,
                detail=f"The text exceeds the {self.settings.max_input_chars}-character limit.",
            )
        model = self.resolve_model(model_requested, languages.source)
        budget = self._budget(options)
        min_tokens = max(0, int(options.min_tokens or 0))
        if min_tokens >= budget:
            min_tokens = max(0, budget - 8)
        warnings: list[str] = []
        chunk_count = 0
        hierarchy_levels = 0
        with self._lock:
            if cancel and cancel():
                raise JobCancelled("Summary job cancelled")
            loaded = self._load(model)
            input_tokens = self._effective_input_tokens(loaded.tokenizer, options.chunk_tokens)
            chunks = self._chunk_text(loaded.tokenizer, text, input_tokens)
            if not chunks:
                raise HTTPException(status_code=422, detail="There is no text to summarize.")
            chunk_count = len(chunks)
            if chunk_count > self.settings.max_chunks:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        "The document requires too many model passes. "
                        "Select fewer pages or a shorter text."
                    ),
                )
            if progress:
                progress(4, f"Prepared {chunk_count} chunk(s).")
            if chunk_count == 1:
                summary = self._generate(
                    loaded, chunks[0], budget, min_tokens, options, input_tokens
                )
            elif not options.hierarchical:
                summary = self._generate(
                    loaded, chunks[0], budget, min_tokens, options, input_tokens
                )
                warnings.append(
                    "Hierarchical summarization was disabled, so only the beginning of "
                    "the document was summarized."
                )
                if progress:
                    progress(88, "Generated a single-pass summary.")
            else:
                map_budget = max(48, min(budget, budget // 3 + 60))
                map_min = min(min_tokens, map_budget - 8) if min_tokens else 0
                current: list[str] = []
                for index, chunk in enumerate(chunks):
                    if cancel and cancel():
                        raise JobCancelled("Summary job cancelled")
                    piece = self._generate(
                        loaded, chunk, map_budget, map_min, options, input_tokens
                    )
                    if piece:
                        current.append(piece)
                    if progress:
                        progress(
                            5 + (index + 1) / max(1, chunk_count) * 55,
                            f"Summarized chunk {index + 1} of {chunk_count}.",
                        )
                if not current:
                    raise HTTPException(
                        status_code=500,
                        detail="The local summarization model returned no usable summaries.",
                    )
                hierarchy_levels = 1
                while len(current) > 1:
                    combined = sum(
                        self._token_length(loaded.tokenizer, item) + 1 for item in current
                    )
                    if combined <= input_tokens - 32:
                        break
                    groups = self._group_summaries(
                        loaded.tokenizer, current, max(64, input_tokens - 20)
                    )
                    if len(groups) >= len(current):
                        midpoint = max(1, len(current) // 2)
                        groups = [
                            "\n\n".join(current[:midpoint]),
                            "\n\n".join(current[midpoint:]),
                        ]
                    next_round = []
                    for index, group in enumerate(groups):
                        if cancel and cancel():
                            raise JobCancelled("Summary job cancelled")
                        piece = self._generate(
                            loaded, group, map_budget, 0, options, input_tokens
                        )
                        if piece:
                            next_round.append(piece)
                        if progress:
                            progress(
                                min(90, 60 + hierarchy_levels * 5 + index * 2),
                                f"Reducing summaries, level {hierarchy_levels + 1}.",
                            )
                    if not next_round:
                        raise HTTPException(
                            status_code=500,
                            detail="The model returned no usable intermediate summaries.",
                        )
                    current = next_round
                    hierarchy_levels += 1
                    if hierarchy_levels > 12:
                        raise HTTPException(
                            status_code=500,
                            detail="The document could not be reduced to a summary.",
                        )
                if cancel and cancel():
                    raise JobCancelled("Summary job cancelled")
                summary = self._generate(
                    loaded,
                    "\n\n".join(current),
                    budget,
                    min_tokens,
                    options,
                    input_tokens,
                )
                hierarchy_levels += 1
            loaded.last_used = time.time()
        if not summary.strip():
            raise HTTPException(
                status_code=500,
                detail=(
                    "The local model returned an empty summary. "
                    "Try a different page range or less text."
                ),
            )
        if progress:
            progress(92, "Finalising the summary.")
        translated = False
        final_summary = summary
        if languages.source != languages.target:
            if cancel and cancel():
                raise JobCancelled("Summary job cancelled")
            final_summary = self._translate_summary(summary, languages)
            translated = True
            if cancel and cancel():
                raise JobCancelled("Summary job cancelled")
            warnings.append(
                "The summary was generated in the source language and then machine-translated "
                "to the requested language."
            )
        source_numbers = set(re.findall(r"\b\d[\d.,%:/-]*\b", text))
        summary_numbers = set(re.findall(r"\b\d[\d.,%:/-]*\b", final_summary))
        missing = source_numbers - summary_numbers
        if source_numbers and len(missing) > max(1, len(source_numbers) // 2):
            warnings.append(
                "Some numerical values from the source are not present in the compact "
                "summary. Review the source for critical figures."
            )
        warnings.append(
            "Summaries are generated by a compact local model. "
            "Verify names, dates and figures before relying on them."
        )
        duration = round(time.time() - started, 2)
        logger.info(
            "Summarized %s words (%s chunks, %s levels) in %.1fs",
            word_count(text),
            chunk_count,
            hierarchy_levels,
            duration,
        )
        return {
            "summary": final_summary.strip() + "\n",
            "source_language": languages.source,
            "source_language_variant": languages.source_variant,
            "language": languages.target_variant,
            "target_language_code": languages.target,
            "translated": translated,
            "length": options.length,
            "model": model.id,
            "model_repo": model.repo,
            "input_words": word_count(text),
            "output_words": word_count(final_summary),
            "chunk_count": chunk_count,
            "hierarchy_levels": hierarchy_levels,
            "parameters": {
                "max_tokens": budget,
                "min_tokens": min_tokens,
                "num_beams": options.num_beams,
                "temperature": options.temperature,
                "chunk_tokens": input_tokens,
                "hierarchical": options.hierarchical,
            },
            "duration_seconds": duration,
            "warnings": warnings,
        }

    # -- lifecycle -----------------------------------------------------

    def maybe_unload_idle(self) -> None:
        if not self.settings.idle_unload_seconds:
            return
        with self._lock:
            if (
                self._current
                and time.time() - self._current.last_used > self.settings.idle_unload_seconds
            ):
                logger.info("Unloading idle summary model %s", self._current.model_id)
                self._current.model = None
                self._current.tokenizer = None
                self._current = None
                gc.collect()

    def unload(self) -> None:
        with self._lock:
            if self._current:
                logger.info("Unloading summary model %s", self._current.model_id)
                self._current.model = None
                self._current.tokenizer = None
                self._current = None
                gc.collect()


def build_languages_payload() -> list[dict[str, str]]:
    return [
        {"id": "en", "label": "English"},
        {"id": "pt-PT", "label": "Portuguese (Portugal)"},
        {"id": "pt-BR", "label": "Portuguese (Brazil)"},
    ]


def build_lengths(settings: Settings) -> list[dict[str, Any]]:
    return [
        {"id": "short", "label": "Short", "max_tokens": settings.short_tokens},
        {"id": "medium", "label": "Medium", "max_tokens": settings.medium_tokens},
        {"id": "long", "label": "Long", "max_tokens": settings.long_tokens},
    ]
