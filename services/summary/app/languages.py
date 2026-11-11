"""Language detection and validation for summarization."""

from __future__ import annotations

import re
from dataclasses import dataclass

LANGUAGE_NAMES = {
    "en": "English",
    "pt": "Portuguese",
    "pt-PT": "Portuguese (Portugal)",
    "pt-BR": "Portuguese (Brazil)",
}

_ALIASES = {
    "en": ("en", "en"),
    "en-us": ("en", "en"),
    "en-gb": ("en", "en"),
    "english": ("en", "en"),
    "inglês": ("en", "en"),
    "ingles": ("en", "en"),
    "pt": ("pt", "pt-PT"),
    "pt-pt": ("pt", "pt-PT"),
    "pt-br": ("pt", "pt-BR"),
    "portuguese": ("pt", "pt-PT"),
    "português": ("pt", "pt-PT"),
    "portugues": ("pt", "pt-PT"),
}

_PT_HINTS = {
    "não", "uma", "para", "com", "isso", "este", "esta", "como", "mais", "dos",
    "das", "pelo", "pela", "você", "voce", "também", "tambem", "porque", "quando",
    "muito", "documento", "texto", "é", "são", "está", "estão", "ser", "foi", "há",
}
_EN_HINTS = {
    "the", "and", "this", "that", "with", "from", "have", "has", "are", "was",
    "were", "for", "not", "you", "your", "document", "text", "will", "would",
    "there", "their", "is", "it", "of", "to", "in", "on", "at", "be", "by",
}


@dataclass(frozen=True)
class SummaryLanguages:
    source: str
    target: str
    target_variant: str
    source_variant: str

    @property
    def source_name(self) -> str:
        return LANGUAGE_NAMES.get(self.source, self.source)

    @property
    def target_name(self) -> str:
        return LANGUAGE_NAMES.get(self.target_variant, self.target_variant)


def normalize_language(value: str | None, default: str = "en") -> tuple[str, str]:
    raw = (value or default).strip().replace("_", "-").lower()
    if raw in {"", "auto", "detect", "automatic"}:
        return "auto", "auto"
    if raw in _ALIASES:
        return _ALIASES[raw]
    if raw in {"pt-pt", "pt-br"}:
        return _ALIASES[raw]
    base = raw.split("-")[0]
    if base in {"en", "pt"}:
        return (base, "pt-BR" if raw.endswith("-br") else ("pt-PT" if base == "pt" else "en"))
    raise ValueError(f"Unsupported language: {value}")


def detect_language(text: str) -> tuple[str, str]:
    sample = re.sub(r"\s+", " ", (text or "")).strip()
    if not sample:
        raise ValueError("There is no text to summarize.")
    words = re.findall(r"[A-Za-zÀ-ÿ']+", sample.lower())
    pt_hits = sum(word in _PT_HINTS for word in words)
    en_hits = sum(word in _EN_HINTS for word in words)
    if len(words) <= 8 and pt_hits != en_hits:
        return ("pt", "pt-PT") if pt_hits > en_hits else ("en", "en")
    try:
        from langdetect import DetectorFactory, detect_langs

        DetectorFactory.seed = 0
        candidates = detect_langs(sample[:5000])
        for candidate in candidates:
            language = candidate.lang.lower()
            if language == "pt" and candidate.prob > 0.15:
                return "pt", "pt-PT"
            if language == "en" and candidate.prob > 0.15:
                return "en", "en"
    except Exception:  # langdetect missing or failed
        pass
    if pt_hits > en_hits:
        return "pt", "pt-PT"
    if en_hits > pt_hits:
        return "en", "en"
    raise ValueError(
        "The summary source language could not be detected. Select it explicitly."
    )


def resolve_languages(
    source_language: str | None,
    summary_language: str | None,
    text: str,
) -> SummaryLanguages:
    source_raw = (source_language or "auto").strip()
    if source_raw.lower() in {"auto", "", "detect", "automatic"}:
        source, source_variant = detect_language(text)
    else:
        source, source_variant = normalize_language(source_raw)
    if source not in {"en", "pt"}:
        raise ValueError(
            "The summarization models support Portuguese and English. "
            "Translate the document first, then summarize the translation."
        )
    target_raw = (summary_language or "auto").strip()
    if target_raw.lower() in {"auto", "", "detect", "automatic"}:
        target, target_variant = source, source_variant
    else:
        target, target_variant = normalize_language(target_raw)
    if target not in {"en", "pt"}:
        raise ValueError(
            "Summaries can be generated in English or Portuguese only. "
            "Translate the summary afterwards for other languages."
        )
    return SummaryLanguages(
        source=source,
        target=target,
        target_variant=target_variant,
        source_variant=source_variant,
    )
