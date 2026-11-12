"""Lazy local Marian/OPUS-MT and NLLB-200 translation engine."""

from __future__ import annotations

import gc
import importlib.util
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from fastapi import HTTPException

from openstudio_common import JobCancelled

from .config import Settings
from .languages import ResolvedLanguage, language_catalogue
from .text import Span, chunk_paragraph

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]
CancelCallback = Callable[[], bool]

_WEIGHT_FILES = (
    "model.safetensors",
    "pytorch_model.bin",
    "model.safetensors.index.json",
    "pytorch_model.bin.index.json",
    "tf_model.h5",
)
_TOKENIZER_FILES = (
    "tokenizer.json",
    "tokenizer_config.json",
    "source.spm",
    "target.spm",
    "vocab.json",
    "spiece.model",
    "sentencepiece.bpe.model",
)

MODEL_ALIASES = {
    "auto": "auto",
    "opus": "opus-auto",
    "opus-mt": "opus-auto",
    "opus-mt-auto": "opus-auto",
    "opus-mt-pt-en": "opus-mt-pt-en",
    "pt-en": "opus-mt-pt-en",
    "opus-mt-en-pt": "opus-mt-en-pt",
    "en-pt": "opus-mt-en-pt",
    "nllb": "nllb-200-distilled-600M",
    "nllb-200": "nllb-200-distilled-600M",
    "nllb-200-distilled-600m": "nllb-200-distilled-600M",
    "facebook/nllb-200-distilled-600m": "nllb-200-distilled-600M",
    "helsinki-nlp/opus-mt-roa-en": "opus-mt-pt-en",
    "helsinki-nlp/opus-mt-tc-big-en-pt": "opus-mt-en-pt",
}


@dataclass
class ModelSelection:
    id: str
    family: str
    repo: str
    path: Path
    label: str
    source: ResolvedLanguage
    target: ResolvedLanguage
    prefix: str = ""
    nllb_source: str = ""
    nllb_target: str = ""


@dataclass
class TranslationOptions:
    num_beams: int = 2
    max_length: int = 512
    temperature: float = 0.0
    length_penalty: float = 1.0
    repetition_penalty: float = 1.0
    no_repeat_ngram_size: int = 3
    batch_size: int = 8
    preserve_markup: bool = True
    glossary: dict[str, str] = field(default_factory=dict)


@dataclass
class LoadedModel:
    model_id: str
    family: str
    model: Any
    tokenizer: Any
    loaded_at: float
    last_used: float


@dataclass
class TranslationStats:
    chunks: int = 0
    pieces: int = 0
    batches: int = 0
    empty_outputs: int = 0
    glossary_terms: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "chunks": self.chunks,
            "pieces": self.pieces,
            "batches": self.batches,
            "empty_outputs": self.empty_outputs,
            "glossary_terms": self.glossary_terms,
        }


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _folder_ready(folder: Path) -> bool:
    if not folder.is_dir() or not (folder / "config.json").is_file():
        return False
    # A checkpoint is not ready while the downloader has only written a
    # tiny/partial file. The smallest supported checkpoint is still tens of MB.
    has_weights = any(
        (folder / name).is_file() and (folder / name).stat().st_size > 10 * 1024 * 1024
        for name in _WEIGHT_FILES
    )
    has_tokenizer = any((folder / name).is_file() for name in _TOKENIZER_FILES)
    return has_weights and has_tokenizer


class TranslationEngine:
    """Thread-safe, single-model cache.

    Only one checkpoint is resident at a time. Imports of torch and transformers
    happen on first use, so status, language and model catalogue routes work in
    an image without the model runtime installed.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        self._current: LoadedModel | None = None
        self._torch: Any | None = None
        self._threads_configured = False

    # -- discovery -----------------------------------------------------

    def available(self, model_id: str) -> bool:
        meta = self.settings.models.get(model_id)
        return bool(meta and _folder_ready(Path(meta["path"])))

    def model_entries(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for model_id, meta in self.settings.models.items():
            family = meta["family"]
            item: dict[str, Any] = {
                "id": model_id,
                "name": meta["label"],
                "family": family,
                "repo": meta["repo"],
                "path": meta["path"],
                "available": self.available(model_id),
                "installed": self.available(model_id),
                "requires": ["torch", "transformers", "sentencepiece"],
                "direction": None,
                "languages": None,
            }
            if model_id == "opus-mt-pt-en":
                item["direction"] = "pt-en"
                item["languages"] = {"source": ["pt"], "target": ["en"]}
            elif model_id == "opus-mt-en-pt":
                item["direction"] = "en-pt"
                item["languages"] = {"source": ["en"], "target": ["pt", "pt-PT", "pt-BR"]}
            else:
                item["languages"] = {
                    "source": [entry["code"] for entry in language_catalogue()],
                    "target": [entry["code"] for entry in language_catalogue()],
                }
                item["multilingual"] = True
            items.append(item)
        return items

    def models_payload(self) -> dict[str, Any]:
        items = self.model_entries()
        loaded = self._current.model_id if self._current else None
        return {
            "items": items,
            "total": len(items),
            "default": "auto",
            "loaded": loaded,
            "opts": ["auto", "opus-mt-pt-en", "opus-mt-en-pt", "nllb-200-distilled-600M"],
            "defaults": {
                "num_beams": self.settings.num_beams,
                "max_length": self.settings.max_length,
                "temperature": 0.0,
                "length_penalty": 1.0,
                "repetition_penalty": 1.0,
                "no_repeat_ngram_size": 3,
                "batch_size": self.settings.batch_size,
                "preserve_markup": True,
            },
            "parameters": [
                {"name": "num_beams", "type": "integer", "min": 1, "max": 16},
                {"name": "max_length", "type": "integer", "min": 8, "max": 4096},
                {"name": "temperature", "type": "number", "min": 0, "max": 2},
                {"name": "length_penalty", "type": "number", "min": -5, "max": 5},
                {"name": "repetition_penalty", "type": "number", "min": 0.1, "max": 5},
                {"name": "no_repeat_ngram_size", "type": "integer", "min": 0, "max": 10},
                {"name": "batch_size", "type": "integer", "min": 1, "max": 64},
                {"name": "preserve_markup", "type": "boolean"},
                {"name": "glossary", "type": "object"},
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
            "loaded_since": round(current.loaded_at, 3) if current else None,
            "models": {item["id"]: item["available"] for item in self.model_entries()},
            "opus_pairs": {
                "pt-en": self.available("opus-mt-pt-en"),
                "en-pt": self.available("opus-mt-en-pt"),
            },
            "nllb_available": self.available("nllb-200-distilled-600M"),
            "device": "cpu",
            "cpu_threads": self.settings.cpu_threads,
            "runtime": {
                "torch": _module_available("torch"),
                "transformers": _module_available("transformers"),
                "sentencepiece": _module_available("sentencepiece"),
                "langdetect": _module_available("langdetect"),
            },
            "models_dir": self.settings.models_dir,
            "limits": {
                "max_input_chars": self.settings.max_input_chars,
                "max_segments": self.settings.max_segments,
                "max_chunk_chars": self.settings.max_chunk_chars,
                "max_input_tokens": self.settings.max_input_tokens,
            },
            "defaults": {
                "source_language": self.settings.default_source_language,
                "target_language": self.settings.default_target_language,
                "num_beams": self.settings.num_beams,
                "max_length": self.settings.max_length,
                "batch_size": self.settings.batch_size,
            },
        }

    # -- model selection ----------------------------------------------

    def _missing_model(self, model_id: str) -> HTTPException:
        meta = self.settings.models[model_id]
        return HTTPException(
            status_code=503,
            detail=(
                f"The translation model '{model_id}' is not installed in {meta['path']}. "
                "Install it with: docker compose run --rm translation download-models "
                f"--models {model_id}"
            ),
        )

    def resolve_model(
        self,
        requested: str | None,
        source: ResolvedLanguage,
        target: ResolvedLanguage,
    ) -> ModelSelection:
        if source.code == target.code:
            return ModelSelection(
                id="identity",
                family="identity",
                repo="",
                path=Path(),
                label="Identity (same language)",
                source=source,
                target=target,
            )
        raw = (requested or "auto").strip()
        model_id = MODEL_ALIASES.get(raw.lower(), raw)
        pair = {source.code, target.code}
        if model_id == "auto":
            model_id = (
                f"opus-mt-{source.code}-{target.code}"
                if pair == {"pt", "en"}
                else "nllb-200-distilled-600M"
            )
        if model_id == "opus-auto":
            if pair != {"pt", "en"}:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "The OPUS-MT models only support Portuguese ↔ English. "
                        "Select the NLLB-200 model for other languages."
                    ),
                )
            model_id = f"opus-mt-{source.code}-{target.code}"
        if model_id not in self.settings.models:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Unknown translation model '{requested}'. "
                    f"Available models: {', '.join(self.settings.models)}"
                ),
            )
        meta = self.settings.models[model_id]
        if meta["family"] == "opus-mt":
            expected = model_id.replace("opus-mt-", "")
            if expected != f"{source.code}-{target.code}":
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"{model_id} only translates {expected.replace('-', ' → ')}. "
                        "Use model=auto or select the matching direction."
                    ),
                )
        if not self.available(model_id):
            raise self._missing_model(model_id)
        prefix = ""
        if model_id == "opus-mt-en-pt":
            prefix = ">>pob<< " if target.variant == "pt-BR" else ">>por<< "
        return ModelSelection(
            id=model_id,
            family=meta["family"],
            repo=meta["repo"],
            path=Path(meta["path"]),
            label=meta["label"],
            source=source,
            target=target,
            prefix=prefix,
            nllb_source=source.nllb_code,
            nllb_target=target.nllb_code,
        )

    # -- runtime -------------------------------------------------------

    def _torch_module(self) -> Any:
        if self._torch is not None:
            return self._torch
        if not _module_available("torch"):
            raise HTTPException(
                status_code=503,
                detail="PyTorch is not installed in the translation service image.",
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

    def _load(self, selection: ModelSelection) -> LoadedModel:
        if self._current and self._current.model_id == selection.id:
            self._current.last_used = time.time()
            return self._current
        if self._current:
            logger.info("Unloading translation model %s", self._current.model_id)
            self._current.model = None
            self._current.tokenizer = None
            self._current = None
            gc.collect()
            if self._torch is not None:
                try:
                    self._torch.cuda.empty_cache()
                except Exception:  # noqa: BLE001
                    pass
        if not _folder_ready(selection.path):
            raise self._missing_model(selection.id)
        try:
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=503,
                detail=(
                    "The translation runtime (transformers) is not installed. "
                    "Rebuild the translation service image."
                ),
            ) from exc
        logger.info("Loading translation model %s from %s", selection.id, selection.path)
        started = time.time()
        try:
            tokenizer = AutoTokenizer.from_pretrained(
                str(selection.path),
                local_files_only=True,
            )
            if selection.family == "nllb":
                tokenizer.src_lang = selection.nllb_source
            model = AutoModelForSeq2SeqLM.from_pretrained(
                str(selection.path),
                local_files_only=True,
            )
            model.to("cpu")
            model.eval()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to load translation model %s", selection.id)
            raise HTTPException(
                status_code=503,
                detail=(
                    f"The translation model '{selection.id}' could not be loaded. "
                    "Reinstall the model files and try again."
                ),
            ) from exc
        loaded = LoadedModel(
            model_id=selection.id,
            family=selection.family,
            model=model,
            tokenizer=tokenizer,
            loaded_at=started,
            last_used=time.time(),
        )
        self._current = loaded
        logger.info("Loaded %s in %.1fs", selection.id, time.time() - started)
        return loaded

    # -- text protection ----------------------------------------------

    @staticmethod
    def _mask(
        text: str,
        pattern: re.Pattern[str],
        replacements: dict[str, str],
        value: Callable[[re.Match[str]], str] | None = None,
    ) -> str:
        def replace(match: re.Match[str]) -> str:
            token = f"\ue000{len(replacements)}\ue001"
            replacements[token] = value(match) if value else match.group(0)
            return token

        return pattern.sub(replace, text)

    def protected_spans(
        self,
        text: str,
        preserve_markup: bool,
        glossary: dict[str, str],
    ) -> list[Span]:
        """Split a chunk into translatable and literal spans.

        Literal spans are never sent to the model, so HTML/XML tags, URLs,
        fenced code, page markers and glossary terms survive byte-for-byte.
        """
        replacements: dict[str, str] = {}
        masked = text
        if preserve_markup:
            masked = self._mask(masked, re.compile(r"```.*?```", re.S), replacements)
            masked = self._mask(masked, re.compile(r"`[^`\n]+`"), replacements)
            masked = self._mask(masked, re.compile(r"https?://[^\s<>\"']+"), replacements)
            masked = self._mask(masked, re.compile(r"</?[A-Za-z][^<>\n]{0,300}>"), replacements)
        masked = self._mask(
            masked,
            re.compile(r"(?m)^[ \t]*---[ \t]*Page[ \t]+\d+[ \t]*---[ \t]*$"),
            replacements,
        )
        if preserve_markup:
            masked = self._mask(
                masked,
                re.compile(r"(?m)^[ \t]{0,3}(?:#{1,6}[ \t]+|>[- \t]?|[-*+][ \t]+|\d{1,3}\.[ \t]+)"),
                replacements,
            )
        if glossary:
            terms = sorted((term for term in glossary if term), key=len, reverse=True)
            if terms:
                alternation = "|".join(re.escape(term) for term in terms)
                pattern = re.compile(rf"(?i)(?<![\wÀ-ÿ])(?:{alternation})(?![\wÀ-ÿ])")
                lookup = {term.lower(): target for term, target in glossary.items()}
                masked = self._mask(
                    masked,
                    pattern,
                    replacements,
                    lambda match: lookup.get(match.group(0).lower(), match.group(0)),
                )
        token_pattern = re.compile(r"\ue000(\d+)\ue001")
        spans: list[Span] = []
        cursor = 0
        for match in token_pattern.finditer(masked):
            if match.start() > cursor:
                spans.append(Span(masked[cursor : match.start()], literal=False))
            token = match.group(0)
            if token in replacements:
                spans.append(Span(replacements[token], literal=True))
            cursor = match.end()
        if cursor < len(masked):
            spans.append(Span(masked[cursor:], literal=False))
        return spans

    # -- token-aware splitting ----------------------------------------

    @staticmethod
    def _token_length(tokenizer: Any, text: str) -> int:
        try:
            return len(tokenizer.encode(text, add_special_tokens=False))
        except Exception:  # noqa: BLE001
            return max(1, len(text) // 4)

    def _split_long_word(self, tokenizer: Any, word: str, max_tokens: int) -> list[str]:
        pieces: list[str] = []
        queue = [word]
        while queue:
            piece = queue.pop(0)
            if self._token_length(tokenizer, piece) <= max_tokens or len(piece) <= 1:
                pieces.append(piece)
                continue
            midpoint = max(1, len(piece) // 2)
            queue.insert(0, piece[midpoint:])
            queue.insert(0, piece[:midpoint])
        return pieces

    def _split_by_tokens(self, tokenizer: Any, text: str, max_tokens: int) -> list[str]:
        if not text:
            return []
        if self._token_length(tokenizer, text) <= max_tokens:
            return [text]
        pieces: list[str] = []
        current: list[str] = []
        count = 0
        for word in text.split(" "):
            if not word:
                if current:
                    current.append(word)
                continue
            word_tokens = self._token_length(tokenizer, word) + 1
            if word_tokens > max_tokens:
                if current:
                    pieces.append(" ".join(current))
                    current = []
                    count = 0
                pieces.extend(self._split_long_word(tokenizer, word, max_tokens))
                continue
            if current and count + word_tokens > max_tokens:
                pieces.append(" ".join(current))
                current = [word]
                count = word_tokens
            else:
                current.append(word)
                count += word_tokens
        if current:
            pieces.append(" ".join(current))
        return [piece for piece in pieces if piece]

    # -- generation ----------------------------------------------------

    def _generate_batch(
        self,
        loaded: LoadedModel,
        selection: ModelSelection,
        texts: list[str],
        options: TranslationOptions,
    ) -> list[str]:
        torch = self._torch_module()
        if not texts:
            return []
        prompts = [f"{selection.prefix}{text}" for text in texts]
        tokenizer = loaded.tokenizer
        kwargs: dict[str, Any] = {}
        if selection.family == "nllb":
            # NLLB selects the source language before tokenisation and the
            # target language with a forced decoder start token.
            tokenizer.src_lang = selection.nllb_source
            target_id = tokenizer.convert_tokens_to_ids(selection.nllb_target)
            unknown = getattr(tokenizer, "unk_token_id", None)
            if target_id is None or (unknown is not None and target_id == unknown):
                raise HTTPException(
                    status_code=500,
                    detail=f"The NLLB tokenizer does not know language token {selection.nllb_target}.",
                )
            kwargs["forced_bos_token_id"] = target_id
        max_input = max(64, min(self.settings.max_input_tokens, 512))
        encoded = tokenizer(
            prompts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=max_input,
        )
        model_max = int(getattr(loaded.model.config, "max_length", 512) or 512)
        if model_max <= 0 or model_max > 4096:
            model_max = 512
        kwargs.update(
            {
                "max_new_tokens": max(8, min(int(options.max_length), model_max)),
                "num_beams": max(1, int(options.num_beams)),
                "length_penalty": float(options.length_penalty),
                "repetition_penalty": float(options.repetition_penalty),
                "early_stopping": True,
            }
        )
        if options.no_repeat_ngram_size and options.no_repeat_ngram_size > 0:
            kwargs["no_repeat_ngram_size"] = int(options.no_repeat_ngram_size)
        if options.temperature and options.temperature > 0:
            kwargs["do_sample"] = True
            kwargs["temperature"] = float(options.temperature)
        try:
            with torch.inference_mode():
                generated = loaded.model.generate(**encoded, **kwargs)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Translation generation failed")
            raise HTTPException(
                status_code=500,
                detail="The translation model failed to generate text for this document.",
            ) from exc
        decoded = tokenizer.batch_decode(generated, skip_special_tokens=True)
        return [str(item).strip() for item in decoded]

    # -- public translation -------------------------------------------

    def translate_segments(
        self,
        segments: list[dict[str, Any]],
        selection: ModelSelection,
        options: TranslationOptions,
        *,
        progress: ProgressCallback | None = None,
        cancel: CancelCallback | None = None,
    ) -> tuple[list[dict[str, Any]], TranslationStats]:
        stats = TranslationStats(glossary_terms=len(options.glossary))
        if selection.family == "identity":
            return (
                [
                    {
                        "id": segment.get("id"),
                        "page": segment.get("page"),
                        "text": str(segment.get("text") or ""),
                    }
                    for segment in segments
                ],
                stats,
            )
        with self._lock:
            if cancel and cancel():
                raise JobCancelled("Translation job cancelled")
            loaded = self._load(selection)
            if selection.family == "nllb":
                loaded.tokenizer.src_lang = selection.nllb_source
            token_limit = max(64, min(self.settings.max_input_tokens - 8, 480))
            # Build a flat work list so all spans are translated in batches.
            work: list[str] = []
            chunk_plans: list[dict[str, Any]] = []
            for seg_index, segment in enumerate(segments):
                text = str(segment.get("text") or "")
                for chunk in chunk_paragraph(text, self.settings.max_chunk_chars):
                    spans = self.protected_spans(
                        chunk,
                        options.preserve_markup,
                        options.glossary,
                    )
                    plan: list[tuple[bool, Any]] = []
                    for span in spans:
                        if span.literal:
                            plan.append((True, span.text))
                            continue
                        raw = span.text
                        if not raw:
                            continue
                        core = raw.strip()
                        if not core:
                            plan.append((True, raw))
                            continue
                        lead = raw[: len(raw) - len(raw.lstrip())]
                        trail = raw[len(raw.rstrip()) :]
                        ids: list[int] = []
                        for piece in self._split_by_tokens(loaded.tokenizer, core, token_limit):
                            ids.append(len(work))
                            work.append(piece)
                        plan.append((False, (lead, trail, ids)))
                    chunk_plans.append({"seg_index": seg_index, "plan": plan})
                    stats.chunks += 1
            stats.pieces = len(work)
            if not work:
                literal_chunks: dict[int, list[str]] = {}
                for chunk in chunk_plans:
                    pieces = []
                    for literal, payload in chunk["plan"]:
                        if literal:
                            pieces.append(str(payload))
                        else:
                            lead, trail, _ids = payload
                            pieces.append(f"{lead}{trail}")
                    literal_chunks.setdefault(chunk["seg_index"], []).append("".join(pieces))
                output = [
                    {
                        "id": segment.get("id"),
                        "page": segment.get("page"),
                        "text": " ".join(literal_chunks.get(index, [])).strip(),
                    }
                    for index, segment in enumerate(segments)
                ]
                return output, stats
            batch_size = max(1, int(options.batch_size))
            batches = [
                work[start : start + batch_size]
                for start in range(0, len(work), batch_size)
            ]
            stats.batches = len(batches)
            translated: list[str] = []
            for index, batch in enumerate(batches):
                if cancel and cancel():
                    raise JobCancelled("Translation job cancelled")
                outputs = self._generate_batch(loaded, selection, batch, options)
                if len(outputs) < len(batch):
                    outputs.extend(batch[len(outputs) :])
                for source, result in zip(batch, outputs):
                    if not result.strip():
                        stats.empty_outputs += 1
                        translated.append(source)
                    else:
                        translated.append(result)
                if progress:
                    percentage = 3 + (index + 1) / max(1, len(batches)) * 94
                    progress(
                        min(97.0, percentage),
                        f"Translated batch {index + 1} of {len(batches)}.",
                    )
            loaded.last_used = time.time()
        translated_chunks: dict[int, list[str]] = {}
        for chunk in chunk_plans:
            pieces: list[str] = []
            for literal, payload in chunk["plan"]:
                if literal:
                    pieces.append(str(payload))
                    continue
                lead, trail, ids = payload
                text = " ".join(translated[piece_id] for piece_id in ids if piece_id < len(translated))
                pieces.append(f"{lead}{text}{trail}")
            translated_chunks.setdefault(chunk["seg_index"], []).append("".join(pieces))
        output: list[dict[str, Any]] = []
        for index, segment in enumerate(segments):
            original = str(segment.get("text") or "")
            translated_text = " ".join(translated_chunks.get(index, []))
            if original.strip() and not translated_text.strip():
                translated_text = original
                stats.empty_outputs += 1
            output.append(
                {
                    "id": segment.get("id"),
                    "page": segment.get("page"),
                    "text": translated_text.strip(),
                }
            )
        return output, stats

    # -- lifecycle -----------------------------------------------------

    def maybe_unload_idle(self) -> None:
        if not self.settings.idle_unload_seconds:
            return
        with self._lock:
            if (
                self._current
                and time.time() - self._current.last_used > self.settings.idle_unload_seconds
            ):
                logger.info("Unloading idle translation model %s", self._current.model_id)
                self._current.model = None
                self._current.tokenizer = None
                self._current = None
                gc.collect()

    def unload(self) -> None:
        with self._lock:
            if self._current:
                logger.info("Unloading translation model %s", self._current.model_id)
                self._current.model = None
                self._current.tokenizer = None
                self._current = None
                gc.collect()


def build_plain_text(segments: Iterable[dict[str, Any]]) -> str:
    """Render translated segments, preserving explicit PDF page boundaries."""
    parts: list[str] = []
    previous_page: Any = object()
    any_text = False
    for segment in segments:
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        page = segment.get("page")
        if page is not None and page != previous_page:
            parts.append(f"--- Page {int(page)} ---")
        parts.append(text)
        previous_page = page
        any_text = True
    if not any_text:
        return ""
    return "\n\n".join(parts).strip() + "\n"


def pages_from_segments(segments: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    pages: dict[int, list[str]] = {}
    for segment in segments:
        page = segment.get("page")
        text = str(segment.get("text") or "").strip()
        if page is None or not text:
            continue
        pages.setdefault(int(page), []).append(text)
    return [
        {"page": page, "text": "\n\n".join(paragraphs)}
        for page, paragraphs in sorted(pages.items())
    ]
