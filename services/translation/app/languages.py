"""Language catalogue, normalisation and source-language detection."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# code -> (English name, NLLB-200 language token)
LANGUAGES: dict[str, tuple[str, str]] = {
    "af": ("Afrikaans", "afr_Latn"),
    "am": ("Amharic", "amh_Ethi"),
    "ar": ("Arabic", "arb_Arab"),
    "az": ("Azerbaijani", "azj_Latn"),
    "bg": ("Bulgarian", "bul_Cyrl"),
    "bn": ("Bengali", "ben_Beng"),
    "bo": ("Tibetan", "bod_Tibt"),
    "bs": ("Bosnian", "bos_Latn"),
    "ca": ("Catalan", "cat_Latn"),
    "cs": ("Czech", "ces_Latn"),
    "cy": ("Welsh", "cym_Latn"),
    "da": ("Danish", "dan_Latn"),
    "de": ("German", "deu_Latn"),
    "el": ("Greek", "ell_Grek"),
    "en": ("English", "eng_Latn"),
    "eo": ("Esperanto", "epo_Latn"),
    "es": ("Spanish", "spa_Latn"),
    "et": ("Estonian", "est_Latn"),
    "eu": ("Basque", "eus_Latn"),
    "fa": ("Persian", "pes_Arab"),
    "fi": ("Finnish", "fin_Latn"),
    "fo": ("Faroese", "fao_Latn"),
    "fr": ("French", "fra_Latn"),
    "ga": ("Irish", "gle_Latn"),
    "gl": ("Galician", "glg_Latn"),
    "gu": ("Gujarati", "guj_Gujr"),
    "ha": ("Hausa", "hau_Latn"),
    "he": ("Hebrew", "heb_Hebr"),
    "hi": ("Hindi", "hin_Deva"),
    "hr": ("Croatian", "hrv_Latn"),
    "hu": ("Hungarian", "hun_Latn"),
    "hy": ("Armenian", "hye_Armn"),
    "id": ("Indonesian", "ind_Latn"),
    "is": ("Icelandic", "isl_Latn"),
    "it": ("Italian", "ita_Latn"),
    "ja": ("Japanese", "jpn_Jpan"),
    "ka": ("Georgian", "kat_Geor"),
    "kk": ("Kazakh", "kaz_Cyrl"),
    "km": ("Khmer", "khm_Khmr"),
    "ko": ("Korean", "kor_Hang"),
    "ku": ("Kurdish (Kurmanji)", "kmr_Latn"),
    "ky": ("Kyrgyz", "kir_Cyrl"),
    "lb": ("Luxembourgish", "ltz_Latn"),
    "lo": ("Lao", "lao_Laoo"),
    "lt": ("Lithuanian", "lit_Latn"),
    "lv": ("Latvian", "lvs_Latn"),
    "mk": ("Macedonian", "mkd_Cyrl"),
    "ml": ("Malayalam", "mal_Mlym"),
    "mn": ("Mongolian", "khk_Cyrl"),
    "mr": ("Marathi", "mar_Deva"),
    "ms": ("Malay", "msa_Latn"),
    "mt": ("Maltese", "mlt_Latn"),
    "my": ("Burmese", "mya_Mymr"),
    "ne": ("Nepali", "npi_Deva"),
    "nl": ("Dutch", "nld_Latn"),
    "no": ("Norwegian", "nob_Latn"),
    "pa": ("Punjabi", "pan_Guru"),
    "pl": ("Polish", "pol_Latn"),
    "ps": ("Pashto", "pbt_Arab"),
    "pt": ("Portuguese", "por_Latn"),
    "ro": ("Romanian", "ron_Latn"),
    "ru": ("Russian", "rus_Cyrl"),
    "sd": ("Sindhi", "snd_Arab"),
    "si": ("Sinhala", "sin_Sinh"),
    "sk": ("Slovak", "slk_Latn"),
    "sl": ("Slovenian", "slv_Latn"),
    "so": ("Somali", "som_Latn"),
    "sq": ("Albanian", "als_Latn"),
    "sr": ("Serbian", "srp_Cyrl"),
    "sv": ("Swedish", "swe_Latn"),
    "sw": ("Swahili", "swh_Latn"),
    "ta": ("Tamil", "tam_Taml"),
    "te": ("Telugu", "tel_Telu"),
    "tg": ("Tajik", "tgk_Cyrl"),
    "th": ("Thai", "tha_Thai"),
    "tl": ("Tagalog", "tgl_Latn"),
    "tr": ("Turkish", "tur_Latn"),
    "uk": ("Ukrainian", "ukr_Cyrl"),
    "ur": ("Urdu", "urd_Arab"),
    "uz": ("Uzbek", "uzn_Latn"),
    "vi": ("Vietnamese", "vie_Latn"),
    "yo": ("Yoruba", "yor_Latn"),
    "zh": ("Chinese (Simplified)", "zho_Hans"),
    "zh-Hant": ("Chinese (Traditional)", "zho_Hant"),
    "zu": ("Zulu", "zul_Latn"),
}

# Variant spellings that resolve to a base language and a display variant.
VARIANTS: dict[str, tuple[str, str]] = {
    "pt-pt": ("pt", "pt-PT"),
    "pt-br": ("pt", "pt-BR"),
    "en-us": ("en", "en"),
    "en-gb": ("en", "en"),
    "zh-hans": ("zh", "zh"),
    "zh-cn": ("zh", "zh"),
    "zh-sg": ("zh", "zh"),
    "zh-hant": ("zh-Hant", "zh-Hant"),
    "zh-tw": ("zh-Hant", "zh-Hant"),
    "zh-hk": ("zh-Hant", "zh-Hant"),
}

_NAME_ALIASES = {
    "portuguese": "pt",
    "português": "pt",
    "portugues": "pt",
    "english": "en",
    "inglês": "en",
    "ingles": "en",
    "spanish": "es",
    "español": "es",
    "espanol": "es",
    "french": "fr",
    "français": "fr",
    "francais": "fr",
    "german": "de",
    "deutsch": "de",
    "italian": "it",
    "italiano": "it",
    "dutch": "nl",
    "nederlands": "nl",
    "russian": "ru",
    "ukrainian": "uk",
    "polish": "pl",
    "romanian": "ro",
    "greek": "el",
    "turkish": "tr",
    "arabic": "ar",
    "hebrew": "he",
    "persian": "fa",
    "farsi": "fa",
    "hindi": "hi",
    "bengali": "bn",
    "urdu": "ur",
    "tamil": "ta",
    "telugu": "te",
    "malayalam": "ml",
    "marathi": "mr",
    "gujarati": "gu",
    "punjabi": "pa",
    "nepali": "ne",
    "sinhala": "si",
    "thai": "th",
    "vietnamese": "vi",
    "indonesian": "id",
    "malay": "ms",
    "tagalog": "tl",
    "filipino": "tl",
    "chinese": "zh",
    "mandarin": "zh",
    "japanese": "ja",
    "korean": "ko",
    "swedish": "sv",
    "danish": "da",
    "norwegian": "no",
    "finnish": "fi",
    "estonian": "et",
    "latvian": "lv",
    "lithuanian": "lt",
    "hungarian": "hu",
    "catalan": "ca",
    "galician": "gl",
    "basque": "eu",
    "albanian": "sq",
    "macedonian": "mk",
    "bosnian": "bs",
    "croatian": "hr",
    "serbian": "sr",
    "slovenian": "sl",
    "slovak": "sk",
    "czech": "cs",
    "bulgarian": "bg",
    "icelandic": "is",
    "irish": "ga",
    "welsh": "cy",
    "afrikaans": "af",
    "swahili": "sw",
    "amharic": "am",
    "yoruba": "yo",
    "zulu": "zu",
    "hausa": "ha",
    "somali": "so",
    "khmer": "km",
    "lao": "lo",
    "burmese": "my",
    "georgian": "ka",
    "armenian": "hy",
    "azerbaijani": "az",
    "kazakh": "kk",
    "uzbek": "uz",
    "kyrgyz": "ky",
    "tajik": "tg",
    "mongolian": "mn",
    "pashto": "ps",
    "kurdish": "ku",
    "sindhi": "sd",
    "tibetan": "bo",
    "maltese": "mt",
    "luxembourgish": "lb",
    "faroese": "fo",
    "esperanto": "eo",
}

_LANGDETECT_ALIASES = {
    "nb": "no",
    "nn": "no",
    "iw": "he",
    "in": "id",
    "ji": "yi",
    "zh-cn": "zh",
    "zh-tw": "zh-Hant",
    "pt-br": "pt",
    "pt-pt": "pt",
    "fil": "tl",
}

_OPUS_LANGUAGES = {"pt", "en"}

_PT_HINTS = {
    "não", "uma", "para", "com", "isso", "este", "esta", "como", "mais", "dos", "das",
    "pelo", "pela", "você", "voce", "também", "tambem", "porque", "quando", "muito",
    "documento", "texto", "é", "são", "está", "estão", "ser", "foi", "há", "os", "as",
}
_EN_HINTS = {
    "the", "and", "this", "that", "with", "from", "have", "has", "are", "was", "were",
    "for", "not", "you", "your", "document", "text", "will", "would", "there", "their",
    "is", "it", "of", "to", "in", "on", "at", "be", "by",
}


@dataclass(frozen=True)
class ResolvedLanguage:
    code: str
    variant: str
    name: str
    nllb_code: str
    opus: bool


@dataclass
class Detection:
    code: str
    variant: str
    confidence: float = 0.0
    candidates: list[dict[str, Any]] = field(default_factory=list)


class UnsupportedLanguage(ValueError):
    def __init__(self, message: str, *, value: str = "") -> None:
        super().__init__(message)
        self.value = value


def language_name(code: str) -> str:
    base, _ = normalize_language(code)
    return LANGUAGES.get(base, (base, ""))[0]


def nllb_code(code: str) -> str:
    base, _ = normalize_language(code)
    entry = LANGUAGES.get(base)
    if not entry:
        raise UnsupportedLanguage(f"Unsupported language: {code}", value=code)
    return entry[1]


def opus_supported(code: str) -> bool:
    try:
        base, _ = normalize_language(code)
    except UnsupportedLanguage:
        return False
    return base in _OPUS_LANGUAGES


def normalize_language(value: str | None, default: str = "en") -> tuple[str, str]:
    """Return ``(base_code, display_variant)`` for a language code or name.

    ``auto`` returns ``("auto", "auto")`` so callers can detect it explicitly.
    """
    raw = (value or default).strip().replace("_", "-")
    lowered = raw.lower()
    if lowered in {"", "auto", "detect", "automatic"}:
        return "auto", "auto"
    if lowered in VARIANTS:
        return VARIANTS[lowered]
    if lowered in LANGUAGES:
        variant = "pt-PT" if lowered == "pt" else raw if raw in LANGUAGES else lowered
        return lowered, variant
    if lowered in _NAME_ALIASES:
        base = _NAME_ALIASES[lowered]
        return base, base
    if raw in LANGUAGES:
        return raw, raw
    # Accept e.g. "pt_BR" already normalised, and BCP-47 fallbacks.
    base_part = lowered.split("-")[0]
    if base_part in LANGUAGES:
        if base_part == "pt":
            return "pt", "pt-BR" if lowered.endswith("-br") else "pt-PT"
        return base_part, base_part
    raise UnsupportedLanguage(f"Unsupported language: {value}", value=str(value))


def resolved_language(value: str, default: str = "en") -> ResolvedLanguage:
    base, variant = normalize_language(value, default)
    if base == "auto":
        raise UnsupportedLanguage("The language must be selected explicitly", value=value)
    name, token = LANGUAGES[base]
    return ResolvedLanguage(
        code=base,
        variant=variant,
        name=name,
        nllb_code=token,
        opus=base in _OPUS_LANGUAGES,
    )


def language_catalogue() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for code, (name, token) in sorted(LANGUAGES.items(), key=lambda item: item[1][0].lower()):
        variants = [code]
        for variant, (base, label) in VARIANTS.items():
            if base == code and label not in variants:
                variants.append(label)
        items.append(
            {
                "code": code,
                "name": name,
                "nllb_code": token,
                "opus": code in _OPUS_LANGUAGES,
                "variants": variants,
            }
        )
    return items


def _short_text_hints(text: str) -> tuple[str | None, int, int]:
    words = re.findall(r"[A-Za-zÀ-ÿ']+", text.lower())
    pt_hits = sum(1 for word in words if word in _PT_HINTS)
    en_hits = sum(1 for word in words if word in _EN_HINTS)
    if len(words) <= 8:
        if pt_hits > en_hits:
            return "pt", pt_hits, en_hits
        if en_hits > pt_hits:
            return "en", pt_hits, en_hits
    return None, pt_hits, en_hits


def detect_language_detailed(text: str) -> Detection:
    sample = re.sub(r"\s+", " ", (text or "")).strip()
    if not sample:
        raise ValueError("There is no text to detect a language from.")
    hinted, pt_hits, en_hits = _short_text_hints(sample)
    if hinted:
        return Detection(hinted, "pt-PT" if hinted == "pt" else "en", 1.0, [])
    candidates: list[dict[str, Any]] = []
    try:
        from langdetect import DetectorFactory, detect_langs

        DetectorFactory.seed = 0
        raw_candidates = detect_langs(sample[:5000])
        for candidate in raw_candidates:
            canonical = _LANGDETECT_ALIASES.get(candidate.lang.lower(), candidate.lang.lower())
            base, variant = normalize_language(canonical, default="en") if canonical in LANGUAGES or canonical in VARIANTS else (canonical, canonical)
            candidates.append(
                {
                    "language": canonical,
                    "base": base,
                    "variant": variant,
                    "confidence": round(float(candidate.prob), 4),
                    "supported": base in LANGUAGES,
                }
            )
        for candidate in candidates:
            if candidate["supported"] and candidate["confidence"] >= 0.12:
                return Detection(
                    candidate["base"],
                    candidate["variant"],
                    candidate["confidence"],
                    candidates,
                )
    except Exception:  # langdetect unavailable or failed on very short text
        pass
    if pt_hits > en_hits:
        return Detection("pt", "pt-PT", 0.5, candidates)
    if en_hits > pt_hits:
        return Detection("en", "en", 0.5, candidates)
    raise ValueError(
        "The source language could not be detected. Select it explicitly."
    )


def detect_language(text: str) -> str:
    return detect_language_detailed(text).code
