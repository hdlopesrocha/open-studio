"""AI-assisted arrangement planning for the DJ studio.

The local planner is deterministic and always available. When a local LLM is
configured (``DJ_LLM_URL``) callers may opt into it; the returned plan is
validated and normalised before it reaches the synth.
"""

from __future__ import annotations

import json
import math
import os
import random
import re
from typing import Any

from .analysis import STYLE_PROFILES, canonical_style

BAR_BEATS = 4

STYLE_KEY = {
    "House": "A minor", "Techno": "F minor", "Trance": "A minor", "Drum & Bass": "E minor",
    "Hip-Hop": "C minor", "Trap": "F minor", "R&B": "D minor", "Pop": "C major",
    "Rock": "E minor", "Lo-fi": "D minor", "Disco & Funk": "G minor", "Reggaeton": "A minor",
    "Ambient": "C major", "Cinematic": "D minor",
}

ROLE_ENERGY = {
    "intro": 0.34,
    "theme": 0.55,
    "verse": 0.64,
    "build": 0.62,
    "chorus": 0.90,
    "drop": 1.0,
    "breakdown": 0.36,
    "bridge": 0.50,
    "rise": 0.72,
    "outro": 0.30,
}

ROLE_LABEL = {
    "intro": "Intro",
    "theme": "Theme",
    "verse": "Verse",
    "build": "Build",
    "chorus": "Chorus",
    "drop": "Drop",
    "breakdown": "Breakdown",
    "bridge": "Bridge",
    "rise": "Rise",
    "outro": "Outro",
}

ROLE_LAYERS = {
    "intro": ["chords", "arp"],
    "theme": ["drums", "chords", "arp"],
    "verse": ["drums", "bass", "chords", "arp"],
    "build": ["drums", "bass", "chords", "arp", "riser"],
    "chorus": ["drums", "bass", "chords", "arp", "impact"],
    "drop": ["drums", "bass", "chords", "arp", "impact"],
    "breakdown": ["chords", "arp", "fx"],
    "bridge": ["drums", "chords", "arp"],
    "rise": ["drums", "bass", "chords", "arp", "riser"],
    "outro": ["chords", "arp"],
}

CLUB_STYLES = {"House", "Techno", "Trance", "Drum & Bass", "Disco & Funk", "Reggaeton"}
SONG_STYLES = {"Pop", "Rock", "Hip-Hop", "Trap", "R&B"}
AMBIENT_STYLES = {"Ambient", "Lo-fi", "Cinematic"}


def _blueprint(style: str, total_bars: int) -> list[tuple[str, int]]:
    if style in CLUB_STYLES:
        pattern = [("intro", 8), ("build", 8), ("drop", 24), ("breakdown", 12), ("build", 8), ("drop", 24), ("outro", 8)]
    elif style in SONG_STYLES:
        pattern = [("intro", 8), ("verse", 16), ("chorus", 16), ("verse", 16), ("bridge", 8), ("chorus", 16), ("outro", 8)]
    elif style in AMBIENT_STYLES:
        pattern = [("intro", 8), ("theme", 16), ("rise", 12), ("theme", 20), ("breakdown", 8), ("outro", 12)]
    else:
        pattern = [("intro", 8), ("verse", 16), ("chorus", 16), ("breakdown", 8), ("chorus", 16), ("outro", 8)]

    raw_total = sum(bars for _, bars in pattern)
    if total_bars <= 0:
        total_bars = raw_total
    scaled: list[tuple[str, int]] = []
    remaining = total_bars
    for index, (role, bars) in enumerate(pattern):
        if index == len(pattern) - 1:
            value = max(1, remaining)
        else:
            value = max(1, int(round(bars * total_bars / raw_total)))
            value = min(value, max(1, remaining - (len(pattern) - index - 1)))
        scaled.append((role, value))
        remaining -= value
    while remaining > 0:
        role, bars = scaled[-1]
        scaled[-1] = (role, bars + remaining)
        remaining = 0
    return scaled


def _prompt_profile(prompt: str) -> dict[str, Any]:
    text = (prompt or "").lower()
    profile: dict[str, Any] = {"energy": 0.0, "mood": "Balanced", "tags": []}
    if any(word in text for word in ("dark", "warehouse", "noir", "industrial", "aggressive")):
        profile["energy"] -= 0.10
        profile["mood"] = "Driving / Dark"
        profile["tags"].append("dark")
    if any(word in text for word in ("euphoric", "festival", "peak", "anthem", "uplifting", "sunrise")):
        profile["energy"] += 0.12
        profile["mood"] = "Euphoric"
        profile["tags"].append("euphoric")
    if any(word in text for word in ("chill", "dreamy", "sunset", "ambient", "melancholic", "introspective")):
        profile["energy"] -= 0.16
        profile["mood"] = "Dreamy"
        profile["tags"].append("dreamy")
    if any(word in text for word in ("melodic", "emotional", "piano", "vocal", "song")):
        profile["tags"].append("melodic")
    if any(word in text for word in ("groove", "funk", "disco", "house", "dance")):
        profile["tags"].append("groove")
    if any(word in text for word in ("break", "breakbeat", "drum", "dnb", "jungle")):
        profile["tags"].append("breaks")
    return profile


def _mood_for(role: str, valence: float, prompt_mood: str) -> str:
    if role in {"drop", "chorus"}:
        return prompt_mood if prompt_mood != "Balanced" else ("Euphoric" if valence >= 0.55 else "Driving / Dark")
    if role in {"breakdown", "intro", "outro"}:
        return "Dreamy" if valence >= 0.5 else "Introspective"
    if role in {"build", "rise"}:
        return "Tense / Rising"
    return prompt_mood if prompt_mood != "Balanced" else "Balanced"


def _section_prompt(style: str, role: str, mood: str, energy: int) -> str:
    layer_note = {
        "intro": "filtered pads, sparse percussion, anticipation",
        "build": "rising filter, snare roll, tension before the drop",
        "drop": "full drums, sub bass, wide synths, impact",
        "chorus": "open chords, strong hook, bright top end",
        "breakdown": "remove kick, expose harmony, breathe",
        "verse": "steady groove, space for vocals",
        "bridge": "change perspective, filtered transition",
        "theme": "state the motif, leave room for development",
        "rise": "add layers and energy without a hard drop",
        "outro": "thin the arrangement, long release",
    }[role]
    return f"{style} · {mood.lower()} · {energy}% energy · {layer_note}"


def plan_structure(
    *,
    style: str = "House",
    duration: float = 180.0,
    prompt: str = "",
    energy: float = 0.68,
    bpm: float = 0.0,
    key: str = "",
    seed: int | None = None,
    model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an editable arrangement with intro/build/drop/breakdown roles."""
    style = canonical_style(style) or "House"
    profile = STYLE_PROFILES[style]
    prompt_profile = _prompt_profile(prompt)
    if not bpm:
        bpm = float((model or {}).get("bpm") or profile["bpm"])
    bpm = float(min(max(bpm, 55.0), 200.0))
    if not key:
        key = str((model or {}).get("key") or STYLE_KEY.get(style, "A minor"))
    duration = float(min(max(duration, 20.0), 900.0))
    bar_seconds = 60.0 / bpm * BAR_BEATS
    total_bars = max(8, int(round(duration / bar_seconds)))
    blueprint = _blueprint(style, total_bars)
    target_energy = float(min(max(energy + prompt_profile["energy"], 0.15), 1.0))
    rng = random.Random(seed if seed is not None else 7)
    valence = float((model or {}).get("valence") or (0.62 if "major" in key.lower() else 0.45))
    learned_curve = [float(value) for value in ((model or {}).get("section_curve") or []) if isinstance(value, (int, float))]
    sections: list[dict[str, Any]] = []
    cursor = 0
    for index, (role, bars) in enumerate(blueprint):
        start = cursor * bar_seconds
        end = min(duration, (cursor + bars) * bar_seconds)
        if end - start < 0.5:
            break
        role_energy = ROLE_ENERGY[role]
        # Add a gentle, deterministic arc so repeated generations are not flat.
        jitter = (rng.random() - 0.5) * 0.06
        level = role_energy * (0.72 + target_energy * 0.55)
        if learned_curve:
            position = (index + 0.5) / max(1, len(blueprint))
            position = min(0.999, max(0.0, position))
            curve_index = position * (len(learned_curve) - 1)
            lower = int(curve_index)
            upper = min(len(learned_curve) - 1, lower + 1)
            fraction = curve_index - lower
            learned = learned_curve[lower] * (1.0 - fraction) + learned_curve[upper] * fraction
            level *= 0.68 + 0.64 * learned
        level = float(min(max(level + jitter, 0.12), 1.0))
        section_energy = round(level * 100, 1)
        mood = _mood_for(role, valence, prompt_profile["mood"])
        layer_set = list(ROLE_LAYERS[role])
        if role in {"drop", "chorus"} and target_energy > 0.75:
            layer_set.append("impact")
        if role == "breakdown" and style in {"Drum & Bass", "Techno"}:
            layer_set = ["drums", "chords", "fx"]
        sections.append(
            {
                "id": f"sec-{index}",
                "index": index,
                "role": role,
                "label": ROLE_LABEL[role],
                "start": round(start, 3),
                "end": round(end, 3),
                "bars": bars,
                "energy": section_energy,
                "mood": mood,
                "filter_hz": int(650 + level**1.4 * 17000),
                "layers": layer_set,
                "prompt": _section_prompt(style, role, mood, round(section_energy)),
            }
        )
        cursor += bars
    return {
        "source": "local-planner",
        "style": style,
        "bpm": round(bpm, 2),
        "key": key,
        "duration": round(float(sections[-1]["end"]) if sections else duration, 3),
        "total_bars": cursor,
        "prompt": prompt,
        "energy": round(target_energy, 3),
        "mood": prompt_profile["mood"],
        "tags": prompt_profile["tags"],
        "sections": sections,
    }


def normalise_structure(
    sections: list[dict[str, Any]],
    *,
    bpm: float,
    duration: float,
    style: str = "House",
) -> list[dict[str, Any]]:
    """Validate user-edited sections and fill timing from bar counts."""
    bar_seconds = 60.0 / max(float(bpm or 120.0), 1.0) * BAR_BEATS
    cleaned: list[dict[str, Any]] = []
    cursor = 0.0
    for index, raw in enumerate(sections or []):
        if not isinstance(raw, dict):
            continue
        bars = int(raw.get("bars") or 0)
        start = float(raw.get("start") if raw.get("start") is not None else cursor)
        if bars <= 0:
            end = float(raw.get("end") or start + bar_seconds * 4)
            bars = max(1, int(round((end - start) / bar_seconds)))
        end = float(raw.get("end") or (start + bars * bar_seconds))
        if end <= start:
            end = start + bars * bar_seconds
        role = str(raw.get("role") or "groove").lower()
        if role not in ROLE_LABEL and role != "groove":
            role = "verse"
        label = str(raw.get("label") or ROLE_LABEL.get(role, "Section")).strip()[:80]
        layers = [str(item) for item in (raw.get("layers") or ROLE_LAYERS.get(role, ["drums", "bass", "chords"])) if str(item)]
        cleaned.append(
            {
                "id": str(raw.get("id") or f"sec-{index}"),
                "index": index,
                "role": role,
                "label": label or "Section",
                "start": round(start, 3),
                "end": round(end, 3),
                "bars": bars,
                "energy": round(float(raw.get("energy") if raw.get("energy") is not None else 65), 1),
                "mood": str(raw.get("mood") or "Balanced")[:80],
                "filter_hz": int(raw.get("filter_hz") or 12000),
                "layers": layers,
                "prompt": str(raw.get("prompt") or "")[:500],
            }
        )
        cursor = round(end, 3)
    if not cleaned:
        return plan_structure(style=style, duration=duration, bpm=bpm)["sections"]
    # Keep the last section inside the requested duration.
    if duration > 0 and cleaned[-1]["end"] > duration + 1:
        cleaned[-1]["end"] = round(duration, 3)
    return cleaned


def _extract_json(text: str) -> Any:
    if not text:
        return None
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    candidate = match.group(1) if match else text
    start = candidate.find("[")
    end = candidate.rfind("]")
    if start >= 0 and end > start:
        try:
            return json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            pass
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


async def llm_structure(
    *,
    style: str,
    duration: float,
    prompt: str,
    bpm: float,
    key: str,
    energy: float,
) -> dict[str, Any] | None:
    """Ask the local LLM bridge for an arrangement; return None on any failure."""
    url = os.getenv("DJ_LLM_URL", "").strip().rstrip("/")
    if not url:
        return None
    try:
        import httpx

        instruction = (
            "You are a music arrangement planner. Return only a JSON array of sections. "
            "Each item needs role (intro|build|drop|breakdown|chorus|verse|bridge|rise|theme|outro), "
            "label, bars, energy (0-100), mood, layers (array of drums,bass,chords,arp,fx,riser,impact) "
            "and prompt. Keep total bars close to the target. "
            f"Style: {style}. BPM: {bpm}. Key: {key}. Duration: {duration}s. Energy: {energy}. "
            f"Brief: {prompt or 'instrumental arrangement'}"
        )
        from openstudio_common import jobhub_headers

        async with httpx.AsyncClient(timeout=15.0, headers=jobhub_headers()) as client:
            response = await client.post(f"{url}/api/llm/complete", json={"prompt": instruction, "temperature": 0.35, "max_tokens": 1400})
        if response.status_code >= 400:
            return None
        text = str((response.json() or {}).get("text") or "")
        payload = _extract_json(text)
        sections = payload.get("sections") if isinstance(payload, dict) else payload
        if not isinstance(sections, list) or not sections:
            return None
        bar_seconds = 60.0 / max(bpm, 1.0) * BAR_BEATS
        total_bars = max(8, int(round(duration / bar_seconds)))
        scaled = []
        raw_total = sum(max(1, int(item.get("bars") or 0)) for item in sections if isinstance(item, dict)) or total_bars
        for index, item in enumerate(sections):
            if not isinstance(item, dict):
                continue
            bars = max(1, int(round(int(item.get("bars") or 4) * total_bars / raw_total)))
            scaled.append({**item, "bars": bars, "id": f"sec-{index}"})
        if not scaled:
            return None
        cleaned = normalise_structure(scaled, bpm=bpm, duration=duration, style=style)
        return {
            "source": "local-llm",
            "style": style,
            "bpm": bpm,
            "key": key,
            "duration": cleaned[-1]["end"] if cleaned else duration,
            "total_bars": sum(int(item.get("bars") or 0) for item in cleaned),
            "prompt": prompt,
            "energy": energy,
            "mood": "LLM planned",
            "tags": ["llm"],
            "sections": cleaned,
        }
    except Exception:  # noqa: BLE001 - planning must never fail because the LLM is offline
        return None


async def plan_structure_async(
    *,
    style: str = "House",
    duration: float = 180.0,
    prompt: str = "",
    energy: float = 0.68,
    bpm: float = 0.0,
    key: str = "",
    seed: int | None = None,
    model: dict[str, Any] | None = None,
    use_llm: bool = False,
) -> dict[str, Any]:
    local = plan_structure(
        style=style,
        duration=duration,
        prompt=prompt,
        energy=energy,
        bpm=bpm,
        key=key,
        seed=seed,
        model=model,
    )
    if use_llm:
        remote = await llm_structure(
            style=local["style"],
            duration=duration,
            prompt=prompt,
            bpm=float(local["bpm"]),
            key=str(local["key"]),
            energy=energy,
        )
        if remote:
            return remote
    return local
