"""Prompt construction for ACE-Step captions and structured lyrics."""

from __future__ import annotations

from typing import Any

from .languages import generation_language_instruction

VOCAL_DESCRIPTIONS = {
    "instrumental": "instrumental only, no vocals, no vocal ad-libs",
    "male": "male lead vocal",
    "female": "female lead vocal",
    "duet": "duet between a male and a female vocalist, trading lines and harmonising",
    "group": "small group vocal, layered harmonies, several distinct voices",
    "choir": "choir vocal, wide harmonious ensemble, restrained diction",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _intensity_word(value: int) -> str:
    if value <= 20:
        return "barely above a whisper"
    if value <= 40:
        return "intimate and restrained"
    if value <= 60:
        return "present and controlled"
    if value <= 80:
        return "powerful and forward"
    return "soaring and full-throated"


def format_lyrics(song: dict[str, Any], sections: list[dict[str, Any]]) -> str:
    """Format lyric sections for ACE-Step, or return the instrumental sentinel."""
    if _text(song.get("vocal_type")) == "instrumental":
        return "[Instrumental]"
    blocks: list[str] = []
    for section in sections:
        content = _text(section.get("content"))
        if not content:
            continue
        label = _text(section.get("label")) or _text(section.get("type")).title() or "Section"
        lines = [line.rstrip() for line in content.splitlines()]
        blocks.append(f"[{label}]\n" + "\n".join(lines))
    return "\n\n".join(blocks).strip()


def performance_notes(sections: list[dict[str, Any]]) -> str:
    notes: list[str] = []
    for section in sections:
        instructions = _text(section.get("instructions"))
        if instructions:
            label = _text(section.get("label")) or _text(section.get("type")).title() or "Section"
            notes.append(f"{label}: {instructions}")
    return "; ".join(notes)


def build_caption(
    song: dict[str, Any],
    sections: list[dict[str, Any]],
    *,
    bpm: int | float | None,
    duration: float,
    mode: str,
    instruction: str = "",
    start_seconds: float | None = None,
    end_seconds: float | None = None,
) -> str:
    title = _text(song.get("title"))
    artist = _text(song.get("artist"))
    genre = _text(song.get("genre")) or "pop"
    subgenre = _text(song.get("subgenre"))
    mood = _text(song.get("mood"))
    style = _text(song.get("style"))
    energy = int(song.get("energy") or 50)
    vocal_type = _text(song.get("vocal_type")) or "female"
    vocal_intensity = int(song.get("vocal_intensity") or 50)

    parts: list[str] = [
        f"A {genre.lower()}" + (f" / {subgenre.lower()}" if subgenre else "") + " song",
        f"mood: {mood}" if mood else "",
        f"energy {energy}/100",
    ]
    if style:
        parts.append(style)
    if bpm:
        parts.append(f"{int(bpm)} BPM")
    parts.append(f"{int(duration)} second arrangement")

    if vocal_type == "instrumental":
        parts.append(VOCAL_DESCRIPTIONS["instrumental"])
    else:
        vocal_bits = [
            VOCAL_DESCRIPTIONS.get(vocal_type, "expressive lead vocal"),
            f"vocal intensity {vocal_intensity}/100 ({_intensity_word(vocal_intensity)})",
        ]
        for key, label in (
            ("singing_style", "singing style"),
            ("vocal_emotion", "emotional expression"),
            ("vocal_range", "vocal range"),
        ):
            value = _text(song.get(key))
            if value and value not in {"—", "-"}:
                vocal_bits.append(f"{label}: {value}")
        parts.append(", ".join(vocal_bits))
        parts.append(
            generation_language_instruction(
                _text(song.get("language")) or "en",
                _text(song.get("language_label")),
                _text(song.get("pronunciation")),
            )
        )
        vocal_prompt = _text(song.get("vocal_prompt"))
        if vocal_prompt:
            parts.append(f"Vocal direction: {vocal_prompt}")

    if mode == "repaint":
        start = float(start_seconds or 0.0)
        end = float(end_seconds or 0.0)
        parts.append(
            f"Selective repaint from {start:.1f}s to {end:.1f}s. "
            "Preserve the surrounding performance, key, tempo, voice identity and arrangement."
        )
    elif mode == "cover":
        parts.append(
            "Create a new cover interpretation of the supplied source audio. "
            "Re-imagine the production while keeping the melodic identity recognisable."
        )
    elif mode == "extend":
        parts.append(
            "Continue the supplied source audio seamlessly. Keep key, tempo, timbre and groove "
            "consistent, then develop the arrangement to a satisfying ending."
        )
    else:
        parts.append("Complete, coherent song structure with a clear intro, development and ending")

    if instruction.strip():
        parts.append(f"Artist direction: {instruction.strip()}")
    if _text(song.get("instructions")):
        parts.append(f"Song brief: {_text(song.get('instructions'))}")
    notes = performance_notes(sections)
    if notes and vocal_type != "instrumental":
        parts.append(f"Section performance notes: {notes}")
    parts.append("Warm, dynamic studio production with clear separation and no clipping")

    if title:
        parts.insert(0, f"Original song titled “{title}”")
    if artist:
        parts.append(f"Artist: {artist}")

    return ". ".join(part.strip().rstrip(".") for part in parts if part and part.strip()) + "."


def format_lyrics_for_text(sections: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for section in sections:
        label = _text(section.get("label")) or _text(section.get("type")) or "Section"
        content = _text(section.get("content"))
        instructions = _text(section.get("instructions"))
        block = f"[{label}]"
        if instructions:
            block += f"\n(performance direction: {instructions})"
        if content:
            block += f"\n{content}"
        blocks.append(block)
    return "\n\n".join(blocks).strip() + ("\n" if blocks else "")
