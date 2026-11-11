"""Language and dialect guidance for lyrics and ACE-Step captions.

ACE-Step expects one base language code (``pt`` for both pt-PT and pt-BR, for
example). Regional variants therefore have to be steered explicitly in the
lyrics prompt and in the generation caption.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageInfo:
    code: str
    label: str
    native_name: str
    script: str
    ace_language: str
    guidance: str
    support: str = "documented"


LANGUAGES: dict[str, LanguageInfo] = {
    "pt-PT": LanguageInfo(
        code="pt-PT",
        label="Portuguese (Portugal)",
        native_name="Português (Portugal)",
        script="Latin",
        ace_language="pt",
        support="dialect-steered",
        guidance=(
            "Use European Portuguese from Portugal (pt-PT), never Brazilian Portuguese. "
            "Use European vocabulary, grammar and phrasing (for example \"a fazer\" rather than "
            "\"fazendo\"; \"tu\" and enclitic pronouns where natural; \"casa de banho\", "
            "\"autocarro\", \"telemóvel\"). Write natural Lisbon/Porto-neutral pronunciation, "
            "with European Portuguese vowel reduction and a soft, non-rhotic final 'r'. "
            "Do not use Brazilian slang, Brazilian contractions, or Brazilian song clichés."
        ),
    ),
    "pt-BR": LanguageInfo(
        code="pt-BR",
        label="Portuguese (Brazil)",
        native_name="Português (Brasil)",
        script="Latin",
        ace_language="pt",
        support="dialect-steered",
        guidance=(
            "Use Brazilian Portuguese (pt-BR) with natural Brazilian vocabulary and grammar. "
            "Avoid European Portuguese structures, vocabulary and pronunciation."
        ),
    ),
    "en-US": LanguageInfo(
        code="en-US",
        label="English (US)",
        native_name="English (United States)",
        script="Latin",
        ace_language="en",
        support="documented",
        guidance="Use contemporary American English spelling, vocabulary and pronunciation.",
    ),
    "en-GB": LanguageInfo(
        code="en-GB",
        label="English (United Kingdom)",
        native_name="English (United Kingdom)",
        script="Latin",
        ace_language="en",
        support="dialect-steered",
        guidance=(
            "Use British English spelling, vocabulary and natural British pronunciation. "
            "Avoid Americanisms and rhotic pronunciation."
        ),
    ),
    "es-ES": LanguageInfo(
        code="es-ES",
        label="Spanish",
        native_name="Español",
        script="Latin",
        ace_language="es",
        guidance="Use natural Castilian Spanish from Spain, with Spain-specific vocabulary and pronunciation.",
    ),
    "fr-FR": LanguageInfo(
        code="fr-FR",
        label="French",
        native_name="Français",
        script="Latin",
        ace_language="fr",
        guidance="Use natural contemporary French from France, including correct liaison and nasal vowels.",
    ),
    "de-DE": LanguageInfo(
        code="de-DE",
        label="German",
        native_name="Deutsch",
        script="Latin",
        ace_language="de",
        guidance="Use natural standard German from Germany with clear pronunciation and natural stress.",
    ),
    "it-IT": LanguageInfo(
        code="it-IT",
        label="Italian",
        native_name="Italiano",
        script="Latin",
        ace_language="it",
        guidance="Use natural contemporary standard Italian with open, resonant vowels and correct double consonants.",
    ),
    "ja-JP": LanguageInfo(
        code="ja-JP",
        label="Japanese",
        native_name="日本語",
        script="Japanese",
        ace_language="ja",
        guidance=(
            "Write natural Japanese lyrics in the script that best suits the song (kanji/kana, "
            "with optional romaji only in pronunciation notes). Respect Japanese mora timing."
        ),
    ),
    "ko-KR": LanguageInfo(
        code="ko-KR",
        label="Korean",
        native_name="한국어",
        script="Hangul",
        ace_language="ko",
        support="prompt-steered",
        guidance="Use natural contemporary Korean lyrics with natural speech levels and syllable timing.",
    ),
    "zh-CN": LanguageInfo(
        code="zh-CN",
        label="Mandarin Chinese",
        native_name="中文（普通话）",
        script="Simplified Chinese",
        ace_language="zh",
        support="prompt-steered",
        guidance="Use natural Mandarin lyrics in simplified Chinese, with natural tonal rhythm.",
    ),
    "ru-RU": LanguageInfo(
        code="ru-RU",
        label="Russian",
        native_name="Русский",
        script="Cyrillic",
        ace_language="ru",
        support="prompt-steered",
        guidance="Use natural Russian with natural stress and phrasing.",
    ),
    "nl-NL": LanguageInfo(
        code="nl-NL",
        label="Dutch",
        native_name="Nederlands",
        script="Latin",
        ace_language="nl",
        support="prompt-steered",
        guidance="Use natural Dutch from the Netherlands with natural stress and vowel length.",
    ),
    "pl-PL": LanguageInfo(
        code="pl-PL",
        label="Polish",
        native_name="Polski",
        script="Latin",
        ace_language="pl",
        support="prompt-steered",
        guidance="Use natural Polish with correct diacritics and natural stress.",
    ),
    "tr-TR": LanguageInfo(
        code="tr-TR",
        label="Turkish",
        native_name="Türkçe",
        script="Latin",
        ace_language="tr",
        support="prompt-steered",
        guidance="Use natural Turkish with correct vowel harmony and stress.",
    ),
    "sv-SE": LanguageInfo(
        code="sv-SE",
        label="Swedish",
        native_name="Svenska",
        script="Latin",
        ace_language="sv",
        support="prompt-steered",
        guidance="Use natural Swedish with natural stress and vowel sounds.",
    ),
    "ca-ES": LanguageInfo(
        code="ca-ES",
        label="Catalan",
        native_name="Català",
        script="Latin",
        ace_language="ca",
        support="prompt-steered",
        guidance="Use natural Catalan with clear open vowels and correct stress.",
    ),
    "gl-ES": LanguageInfo(
        code="gl-ES",
        label="Galician",
        native_name="Galego",
        script="Latin",
        ace_language="gl",
        support="prompt-steered",
        guidance="Use natural Galician with Portuguese-adjacent phonetics and vocabulary.",
    ),
    "ar": LanguageInfo(
        code="ar",
        label="Arabic",
        native_name="العربية",
        script="Arabic",
        ace_language="ar",
        support="prompt-steered",
        guidance="Use natural Modern Standard Arabic or a clearly noted regional register.",
    ),
    "hi-IN": LanguageInfo(
        code="hi-IN",
        label="Hindi",
        native_name="हिन्दी",
        script="Devanagari",
        ace_language="hi",
        support="prompt-steered",
        guidance="Use natural Hindi with natural syllable stress and pronunciation.",
    ),
    "custom": LanguageInfo(
        code="custom",
        label="Other / Custom",
        native_name="Custom language",
        script="Unknown",
        ace_language="",
        support="custom",
        guidance="Follow the user's custom language and pronunciation notes exactly.",
    ),
}


DOCUMENTED_LANGUAGES = {"en", "zh", "ja", "ko", "es", "fr", "de", "it", "pt", "ru"}


def get_language(locale: str, label: str = "") -> LanguageInfo:
    if locale in LANGUAGES:
        info = LANGUAGES[locale]
        if label and label != info.label:
            return LanguageInfo(
                code=info.code,
                label=label,
                native_name=info.native_name,
                script=info.script,
                ace_language=info.ace_language,
                guidance=info.guidance,
                support=info.support,
            )
        return info
    return LanguageInfo(
        code=locale or "custom",
        label=label or locale or "Other / Custom",
        native_name=label or locale or "Custom language",
        script="Unknown",
        ace_language=locale[:2].lower() if len(locale) >= 2 else "",
        guidance="Follow the user's language and pronunciation notes exactly.",
        support="custom",
    )


def ace_language(locale: str) -> str:
    if locale in LANGUAGES:
        return LANGUAGES[locale].ace_language or "en"
    if locale and locale not in {"custom", "other"}:
        return locale.split("-")[0][:2].lower()
    return "en"


def generation_language_instruction(locale: str, label: str, custom: str = "") -> str:
    info = get_language(locale, label)
    parts = [f"Vocal language: {info.label} ({info.code}).", info.guidance]
    if locale == "pt-PT":
        parts.append(
            "European Portuguese pronunciation is mandatory: clearly non-Brazilian, with natural "
            "European vowel reduction and vocabulary. Do not sing this in Brazilian Portuguese."
        )
    if custom.strip():
        parts.append(f"Artist pronunciation direction: {custom.strip()}")
    return " ".join(parts)


def lyrics_language_instruction(locale: str, label: str, custom: str = "") -> str:
    info = get_language(locale, label)
    parts = [f"Write all lyrics in {info.label} ({info.code}) using the {info.script} script."]
    parts.append(info.guidance)
    if locale == "pt-PT":
        parts.append(
            "This must read as a song written by a Portuguese author for Portuguese listeners. "
            "Do not produce a Brazilian Portuguese version and do not translate or localise an existing text."
        )
    if custom.strip():
        parts.append(f"Pronunciation and dialect notes supplied by the artist: {custom.strip()}")
    return " ".join(parts)


def provider_languages() -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for locale, info in LANGUAGES.items():
        if locale == "custom":
            continue
        support = info.support
        note = ""
        if locale in {"pt-PT", "en-GB"}:
            note = "The API accepts one base language code; this regional variant is guided in the prompt."
        elif locale == "pt-BR":
            note = "Brazilian Portuguese shares the pt language code; dialect is prompt-steered."
        elif support == "prompt-steered":
            note = "ACE-Step documents 50+ languages, but quality varies. Treat this language as prompt-steered."
        entries.append(
            {
                "code": info.code,
                "label": info.label,
                "native_name": info.native_name,
                "script": info.script,
                "ace_language": info.ace_language,
                "support": support,
                "note": note,
            }
        )
    entries.append(
        {
            "code": "custom",
            "label": "Other / Custom",
            "native_name": "Custom language",
            "script": "Unknown",
            "ace_language": "",
            "support": "custom",
            "note": "Use a custom language code and add explicit pronunciation direction.",
        }
    )
    return entries
