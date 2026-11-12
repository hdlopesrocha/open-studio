"""Prompt-aware mix scene planning.

A scene is a plain JSON document: ordered tracks, in/out points, beat-matched
timeline starts, transition choices and effect racks. The planner makes musical
decisions from analysis data and the brief; the renderer executes the scene
sample-accurately.
"""

from __future__ import annotations

import json
import random
from typing import Any

from .analysis import STYLE_PROFILES, canonical_style

TRANSITION_TYPES = ["crossfade", "filter_sweep", "bass_swap", "echo_out", "cut"]


def _energy(entry: dict[str, Any]) -> float:
    try:
        return float(entry.get("energy") or 0.5)
    except (TypeError, ValueError):
        return 0.5


def _analysis_payload(track: dict[str, Any]) -> dict[str, Any]:
    raw = track.get("analysis_json")
    if isinstance(raw, dict):
        return raw
    try:
        payload = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _sections(track: dict[str, Any]) -> list[dict[str, Any]]:
    sections = _analysis_payload(track).get("sections")
    return [section for section in sections or [] if isinstance(section, dict)]


def _downbeats(track: dict[str, Any]) -> list[float]:
    rhythm = _analysis_payload(track).get("rhythm") or {}
    values = rhythm.get("downbeats") or []
    return sorted(float(value) for value in values if isinstance(value, (int, float)))


def _nearest(values: list[float], target: float) -> float:
    if not values:
        return target
    return min(values, key=lambda value: abs(value - target))


def _camelot_compatible(a: str, b: str) -> bool:
    if not a or not b:
        return True
    try:
        number_a = int("".join(ch for ch in a if ch.isdigit()))
        number_b = int("".join(ch for ch in b if ch.isdigit()))
        letter_a = "".join(ch for ch in a if ch.isalpha()).upper()
        letter_b = "".join(ch for ch in b if ch.isalpha()).upper()
    except ValueError:
        return True
    if letter_a == letter_b:
        return abs(number_a - number_b) in {0, 1, 11}
    return number_a == number_b


def _prompt_profile(prompt: str) -> dict[str, Any]:
    text = (prompt or "").lower()
    profile = {"mood": "balanced", "transition_bias": "", "effects": [], "notes": []}
    if any(word in text for word in ("dark", "warehouse", "noir", "industrial")):
        profile.update(mood="dark", transition_bias="filter_sweep", effects=["lowpass", "drive"])
        profile["notes"].append("dark warehouse arc: filtered hand-offs and a little drive")
    if any(word in text for word in ("euphoric", "festival", "peak", "anthem", "sunrise")):
        profile.update(mood="euphoric", transition_bias="echo_out", effects=["reverb", "highpass"])
        profile["notes"].append("peak-time arc: long builds, bright openings and echo tails")
    if any(word in text for word in ("dreamy", "sunset", "melodic", "chill", "ambient")):
        profile.update(mood="dreamy", transition_bias="crossfade", effects=["reverb", "chorus"])
        profile["notes"].append("dreamy arc: longer blends, chorus and reverb")
    if any(word in text for word in ("aggressive", "hard", "industrial", "rave")):
        profile.update(mood="aggressive", transition_bias="cut", effects=["drive", "bitcrush"])
        profile["notes"].append("aggressive arc: tighter cuts and saturated hand-offs")
    if "bass" in text or "sub" in text:
        profile["effects"].append("lowpass")
        profile["notes"].append("protect the low end with bass swaps")
    return profile


def _append_effect(entry: dict[str, Any], effect: dict[str, Any], *, head: bool, tail: bool, clip_duration: float) -> None:
    if head:
        effect = {**effect, "start": 0.0, "end": min(16.0, max(2.0, clip_duration * 0.25))}
    elif tail:
        effect = {**effect, "start": max(0.0, clip_duration - min(16.0, max(2.0, clip_duration * 0.25))), "end": clip_duration}
    entry.setdefault("effects", []).append(effect)


def _section_role(section: dict[str, Any]) -> str:
    return str(section.get("role") or section.get("section_type") or "groove").lower()


def _pick_track_sections(
    track: dict[str, Any],
    *,
    index: int,
    total: int,
    use_sections: bool,
) -> list[dict[str, Any] | None]:
    """Choose up to two musically useful scenes from one track."""
    sections = [
        section
        for section in _sections(track)
        if float(section.get("end") or 0) - float(section.get("start") or 0) >= 6.0
    ]
    if not use_sections or not sections:
        return [None]
    first_roles = {"intro", "theme", "groove", "verse", "build"}
    last_roles = {"drop", "chorus", "outro"}
    middle_roles = {"breakdown", "build", "groove", "verse"}
    if index == 0:
        preferred = first_roles
    elif index == total - 1:
        preferred = last_roles
    else:
        preferred = middle_roles
    primary = next((section for section in sections if _section_role(section) in preferred), None)
    if primary is None:
        primary = max(sections, key=lambda section: float(section.get("energy") or 0))
    chosen: list[dict[str, Any]] = [primary]

    def after(section: dict[str, Any]) -> float:
        return float(section.get("start") or 0) >= float(primary.get("end") or 0) - 0.5

    candidates: list[dict[str, Any]] = []
    if index == total - 1:
        candidates = [section for section in sections if _section_role(section) == "outro" and after(section)]
    else:
        candidates = [section for section in sections if _section_role(section) in {"drop", "chorus"} and after(section)]
        if not candidates:
            candidates = [
                section
                for section in sections
                if _section_role(section) in {"build", "breakdown", "groove", "verse"} and after(section)
            ]
    if candidates:
        secondary = candidates[0]
        if secondary is not primary:
            chosen.append(secondary)
    chosen.sort(key=lambda section: float(section.get("start") or 0))
    return chosen


def plan_scene(
    tracks: list[dict[str, Any]],
    *,
    prompt: str = "",
    master_bpm: float = 0.0,
    transition_beats: int = 16,
    seed: int | None = None,
    keep_order: bool = True,
    use_sections: bool = True,
    segments: int | None = None,
    target_duration: float | None = None,
) -> dict[str, Any]:
    if not tracks:
        raise ValueError("Add at least one analysed track before creating a mix scene.")
    usable = [track for track in tracks if track.get("path") and float(track.get("duration") or 0) > 1.0]
    if not usable:
        raise ValueError("The selected tracks have no usable audio.")
    if not keep_order:
        usable = sorted(usable, key=lambda item: (float(item.get("energy") or 0.5), str(item.get("camelot") or "")))
    bpms = [float(track.get("bpm") or 120.0) for track in usable if float(track.get("bpm") or 0) > 0]
    target_bpm = float(master_bpm or (sum(bpms) / len(bpms) if bpms else 120.0))
    target_bpm = round(min(max(target_bpm, 65.0), 185.0), 2)
    beat = 60.0 / target_bpm
    rng = random.Random(seed if seed is not None else 19)
    profile = _prompt_profile(prompt)
    entries: list[dict[str, Any]] = []
    notes: list[str] = []
    default_segments = len(usable) * (2 if len(usable) <= 8 else 1)
    max_scene_entries = max(1, min(64, int(segments))) if segments is not None else default_segments
    allow_secondaries = len(usable) <= 8
    for index, track in enumerate(usable):
        duration = float(track.get("duration") or 0)
        style = canonical_style(track.get("style")) or "House"
        style_energy = float(STYLE_PROFILES.get(style, {}).get("energy") or 0.6)
        bpm = float(track.get("bpm") or target_bpm)
        beat_track = 60.0 / max(bpm, 1.0)
        bar_track = beat_track * 4.0
        downbeats = _downbeats(track)
        chosen = _pick_track_sections(track, index=index, total=len(usable), use_sections=use_sections)
        if not allow_secondaries:
            chosen = chosen[:1]
        for chosen_section in chosen:
            if len(entries) >= max_scene_entries:
                break
            if chosen_section is None:
                in_seconds = min(duration * 0.10, max(beat_track * 8, 8.0))
                out_seconds = max(in_seconds + 8.0, duration - min(duration * 0.10, max(beat_track * 16, 16.0)))
                if duration < 45:
                    in_seconds = 0.0
                    out_seconds = duration
                section_label = ""
                section_role = ""
                section_energy = 0.0
                section_id = ""
            else:
                in_seconds = float(chosen_section.get("start") or 0.0)
                out_seconds = float(chosen_section.get("end") or duration)
                section_label = str(chosen_section.get("label") or chosen_section.get("role") or "Section")
                section_role = _section_role(chosen_section)
                section_energy = float(chosen_section.get("energy") or 0.0) / 100.0
                section_id = str(chosen_section.get("scene_id") or chosen_section.get("index") or "")
            # Quantise trims to downbeats when the scene is a whole-track fallback.
            if chosen_section is None and downbeats:
                in_seconds = _nearest(downbeats, in_seconds)
                out_seconds = _nearest(downbeats, out_seconds)
            elif chosen_section is None and bar_track > 0:
                in_seconds = round(in_seconds / bar_track) * bar_track
                out_seconds = round(out_seconds / bar_track) * bar_track
            in_seconds = max(0.0, min(duration, in_seconds))
            out_seconds = min(duration, max(in_seconds + 4.0, out_seconds))
            energy = section_energy or _energy(track) or style_energy
            entries.append(
                {
                    "entry_id": f"{track.get('id') or ''}-{section_id or len(entries)}",
                    "track_id": str(track.get("id") or ""),
                    "source_track_id": str(track.get("id") or ""),
                    "section_id": section_id,
                    "section_label": section_label,
                    "section_role": section_role,
                    "title": str(track.get("title") or "Untitled"),
                    "artist": str(track.get("artist") or ""),
                    "path": str(track.get("path") or ""),
                    "style": style,
                    "mood": str(chosen_section.get("mood") if chosen_section else track.get("mood") or ""),
                    "bpm": round(bpm, 2),
                    "master_bpm": target_bpm,
                    "key": str(track.get("key") or ""),
                    "camelot": str(track.get("camelot") or ""),
                    "duration": round(duration, 3),
                    "in": round(in_seconds, 3),
                    "out": round(out_seconds, 3),
                    "energy": round(energy, 4),
                    "gain_db": round((0.5 - energy) * 2.4, 2),
                    "effects": [],
                    "transition": {},
                }
            )
    if target_duration and target_duration > 0 and entries:
        raw_total = sum(max(0.1, float(entry["out"]) - float(entry["in"])) for entry in entries)
        if raw_total > float(target_duration):
            ratio = max(0.02, float(target_duration) / raw_total)
            for entry in entries:
                clip = max(0.1, float(entry["out"]) - float(entry["in"]))
                entry["out"] = round(float(entry["in"]) + max(4.0, clip * ratio), 3)

    for index, entry in enumerate(entries):
        nxt = entries[index + 1] if index + 1 < len(entries) else None
        clip_duration = max(0.1, float(entry["out"]) - float(entry["in"]))
        current_energy = float(entry["energy"])
        next_energy = float(nxt["energy"]) if nxt else current_energy
        compatible = _camelot_compatible(str(entry.get("camelot") or ""), str(nxt.get("camelot") or "")) if nxt else True
        jump = next_energy - current_energy
        same_track = bool(nxt and entry.get("source_track_id") == nxt.get("source_track_id"))
        gap = float(nxt.get("in") or 0.0) - float(entry.get("out") or 0.0) if nxt else 0.0
        if not nxt:
            beats = max(8, transition_beats)
            transition_type = "crossfade"
        elif same_track:
            # Move between two scenes of the same source track. Adjacent scenes
            # cut cleanly on the bar; non-adjacent jumps get a short filter sweep.
            if gap <= 1.0:
                beats = 1
                transition_type = "cut"
            else:
                beats = max(4, min(8, int(transition_beats)))
                transition_type = "filter_sweep"
        else:
            beats = max(4, int(transition_beats))
            if abs(jump) > 0.18:
                beats = min(48, beats + 8)
            if not compatible:
                beats = min(32, beats + 4)
            if profile["transition_bias"]:
                transition_type = profile["transition_bias"]
            elif not compatible:
                transition_type = "filter_sweep"
            elif jump < -0.12:
                transition_type = "echo_out"
            elif jump > 0.16:
                transition_type = "bass_swap"
            else:
                transition_type = "crossfade"
            if transition_type == "cut" and abs(jump) < 0.08:
                transition_type = "crossfade"
            if rng.random() < 0.08 and transition_type == "crossfade":
                transition_type = "cut"
        entry["transition"] = {
            "type": transition_type,
            "beats": beats,
            "curve": "equal_power" if transition_type in {"crossfade", "filter_sweep", "bass_swap", "echo_out"} else "cut",
            "bars": round(beats / 4.0, 2),
        }
        # Mood effects decorate the entrance or exit without changing the mix
        # architecture. They are editable in the UI.
        if "dark" in profile["mood"] and index > 0:
            _append_effect(entry, {"type": "filter_sweep", "mode": "lowpass", "from_hz": 1600, "to_hz": 18000, "amount": 0.7}, head=True, tail=False, clip_duration=clip_duration)
        elif "euphoric" in profile["mood"] and index > 0:
            _append_effect(entry, {"type": "filter_sweep", "mode": "highpass", "from_hz": 900, "to_hz": 40, "amount": 0.8}, head=True, tail=False, clip_duration=clip_duration)
            _append_effect(entry, {"type": "reverb", "amount": 0.18}, head=False, tail=True, clip_duration=clip_duration)
        elif "dreamy" in profile["mood"]:
            _append_effect(entry, {"type": "reverb", "amount": 0.24}, head=False, tail=True, clip_duration=clip_duration)
            _append_effect(entry, {"type": "chorus", "amount": 0.28}, head=True, tail=False, clip_duration=clip_duration)
        elif "aggressive" in profile["mood"]:
            _append_effect(entry, {"type": "drive", "amount": 0.32}, head=False, tail=False, clip_duration=clip_duration)
        if "drive" in profile["effects"] and not any(effect.get("type") == "drive" for effect in entry["effects"]):
            _append_effect(entry, {"type": "drive", "amount": 0.22}, head=False, tail=False, clip_duration=clip_duration)
        if "lowpass" in profile["effects"] and index > 0:
            _append_effect(entry, {"type": "filter_sweep", "mode": "lowpass", "from_hz": 3500, "to_hz": 18000, "amount": 0.6}, head=True, tail=False, clip_duration=clip_duration)
        section_note = f" · {entry['section_label']}" if entry.get("section_label") else ""
        notes.append(
            f"{index + 1}. {entry['title']}{section_note} · {entry['bpm']:.0f} BPM · "
            f"{entry['key'] or 'unknown key'} · {entry['transition']['type']} ({beats} beats)"
        )

    starts: list[float] = []
    cursor = 0.0
    for index, entry in enumerate(entries):
        length = max(0.1, float(entry["out"]) - float(entry["in"]))
        if index == 0:
            starts.append(0.0)
        else:
            previous = entries[index - 1]
            transition = previous.get("transition") or {}
            overlap = float(transition.get("beats") or transition_beats) * beat
            overlap = min(overlap, length * 0.75)
            starts.append(max(0.0, cursor - overlap))
        cursor = starts[-1] + length
        entry["start"] = round(starts[-1], 3)
        entry["timeline_duration"] = round(length, 3)
    total_duration = max(float(entry["start"]) + max(0.1, float(entry["out"]) - float(entry["in"])) for entry in entries)
    if not notes:
        notes.append("A single-track scene: fade in, ride the energy, fade out.")
    notes.append(f"Master tempo {target_bpm:.1f} BPM · {len(entries)} segments · {total_duration:.1f}s")
    if target_duration and target_duration > 0:
        notes.append(f"Target duration {float(target_duration):.0f}s")
    return {
        "source": "dj-ai-sections" if use_sections else "dj-ai",
        "prompt": prompt,
        "mood": profile["mood"],
        "master_bpm": target_bpm,
        "beat_seconds": round(beat, 5),
        "duration": round(total_duration + 1.5, 3),
        "tracks": entries,
        "notes": notes,
        "created_at": None,
    }
