"""Procedural style model renderer for the DJ studio.

The renderer turns a trained style model and an arrangement into a complete
multi-stem electronic track. It is intentionally deterministic for a given
seed: the same style model, structure and seed always reproduce the same audio.
"""

from __future__ import annotations

import math
import random
from typing import Any, Callable

import numpy as np
from scipy.signal import butter, lfilter, sosfilt

SR = 44100
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MAJOR_SCALE = [0, 2, 4, 5, 7, 9, 11]
MINOR_SCALE = [0, 2, 3, 5, 7, 8, 10]

MINOR_PROGRESSIONS = [
    [0, 8, 3, 10],
    [0, 5, 8, 7],
    [0, 3, 8, 10],
    [0, 10, 8, 7],
]
MAJOR_PROGRESSIONS = [
    [0, 7, 9, 5],
    [0, 9, 5, 7],
    [0, 5, 9, 7],
    [0, 4, 9, 5],
]

STYLE_FAMILY = {
    "House": "four",
    "Techno": "four",
    "Trance": "four",
    "Disco & Funk": "four",
    "Drum & Bass": "breaks",
    "Hip-Hop": "hiphop",
    "Trap": "trap",
    "R&B": "smooth",
    "Pop": "pop",
    "Rock": "rock",
    "Lo-fi": "lofi",
    "Reggaeton": "dembow",
    "Ambient": "ambient",
    "Cinematic": "cinematic",
}

STYLE_SWING = {
    "House": 0.02, "Techno": 0.0, "Trance": 0.0, "Drum & Bass": 0.0,
    "Hip-Hop": 0.12, "Trap": 0.02, "R&B": 0.08, "Pop": 0.02, "Rock": 0.0,
    "Lo-fi": 0.14, "Disco & Funk": 0.08, "Reggaeton": 0.03, "Ambient": 0.0,
    "Cinematic": 0.0,
}


def midi_hz(midi: float) -> float:
    return 440.0 * (2.0 ** ((float(midi) - 69.0) / 12.0))


def parse_key(value: str) -> tuple[int, str]:
    raw = (value or "A minor").strip()
    parts = raw.replace("_", " ").split()
    tonic = 9
    mode = "minor"
    if parts:
        candidate = parts[0].replace("♯", "#").replace("♭", "b")
        flats = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}
        candidate = flats.get(candidate, candidate)
        if candidate in NOTE_NAMES:
            tonic = NOTE_NAMES.index(candidate)
    if len(parts) > 1 and parts[1].lower().startswith("maj"):
        mode = "major"
    elif "major" in raw.lower():
        mode = "major"
    return tonic, mode


def _rng(seed: int | None) -> random.Random:
    return random.Random(int(seed if seed is not None else 7))


def _env(n: int, attack: float, decay: float, sustain: float, release: float, sr: int = SR) -> np.ndarray:
    n = max(1, int(n))
    a = max(1, int(attack * sr))
    d = max(1, int(decay * sr))
    r = max(1, int(release * sr))
    if a + d + r > n:
        scale = n / float(a + d + r)
        a, d, r = max(1, int(a * scale)), max(1, int(d * scale)), max(1, int(r * scale))
    s = max(0, n - a - d - r)
    env = np.concatenate(
        [
            np.linspace(0.0, 1.0, a, endpoint=False),
            np.linspace(1.0, sustain, d, endpoint=False),
            np.full(s, sustain),
            np.linspace(sustain, 0.0, r),
        ]
    )
    if env.size < n:
        env = np.pad(env, (0, n - env.size))
    return env[:n].astype(np.float32)


def _sine(freq: float, n: int, sr: int = SR, phase: float = 0.0) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / sr
    return np.sin(2 * np.pi * freq * t + phase).astype(np.float32)


def _saw(freq: float, n: int, sr: int = SR, phase: float = 0.0) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / sr
    value = 2.0 * ((freq * t + phase) % 1.0) - 1.0
    return value.astype(np.float32)


def _triangle(freq: float, n: int, sr: int = SR) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / sr
    value = 2.0 * np.abs(2.0 * ((freq * t) % 1.0) - 1.0) - 1.0
    return value.astype(np.float32)


def _noise(n: int, rng: random.Random) -> np.ndarray:
    return np.asarray([rng.uniform(-1.0, 1.0) for _ in range(max(1, n))], dtype=np.float32)


def _one_pole_lowpass(signal: np.ndarray, cutoff: float, sr: int = SR) -> np.ndarray:
    cutoff = float(min(max(cutoff, 20.0), sr / 2.1))
    alpha = 1.0 - math.exp(-2.0 * math.pi * cutoff / sr)
    return lfilter([alpha], [1.0, alpha - 1.0], signal).astype(np.float32)


def _butter_filter(signal: np.ndarray, cutoff: float, kind: str = "low", sr: int = SR) -> np.ndarray:
    cutoff = float(min(max(cutoff, 20.0), sr / 2.1))
    sos = butter(2, cutoff, btype=kind, fs=sr, output="sos")
    return sosfilt(sos, signal).astype(np.float32)


def _stereo(mono: np.ndarray, width: float = 0.0, sr: int = SR) -> np.ndarray:
    mono = np.nan_to_num(np.asarray(mono, dtype=np.float32))
    if width <= 0:
        return np.stack([mono, mono], axis=1)
    delay = max(1, int(width * sr))
    right = np.concatenate([np.zeros(delay, dtype=np.float32), mono[:-delay]]) if delay < len(mono) else np.zeros_like(mono)
    return np.stack([mono, right], axis=1)


def _add(buffer: np.ndarray, start: int, signal: np.ndarray, gain: float = 1.0) -> None:
    if signal.size == 0 or gain == 0:
        return
    if start >= len(buffer):
        return
    if start < 0:
        signal = signal[-start:]
        start = 0
    end = min(len(buffer), start + len(signal))
    if end <= start:
        return
    buffer[start:end] += signal[: end - start] * float(gain)


def _kick(rng: random.Random, punch: float = 1.0) -> np.ndarray:
    n = int(0.46 * SR)
    t = np.arange(n, dtype=np.float64) / SR
    freq = 48.0 + 95.0 * np.exp(-t * 22.0)
    body = np.sin(2 * np.pi * np.cumsum(freq) / SR)
    env = np.exp(-t * 7.5)
    click = _noise(int(0.012 * SR), rng) * np.exp(-np.arange(int(0.012 * SR)) / (0.004 * SR))
    result = body * env * 0.95 * punch
    result[: len(click)] += click * 0.22
    return np.tanh(result * 1.5).astype(np.float32)


def _snare(rng: random.Random, tone: float = 185.0, decay: float = 16.0) -> np.ndarray:
    n = int(0.28 * SR)
    t = np.arange(n, dtype=np.float64) / SR
    noise = _noise(n, rng)
    noise = _butter_filter(noise, 7200.0, "low") - _butter_filter(noise, 900.0, "high")
    env = np.exp(-t * decay)
    body = np.sin(2 * np.pi * tone * t) * np.exp(-t * 28.0) * 0.35
    return (noise * env * 0.42 + body).astype(np.float32)


def _clap(rng: random.Random) -> np.ndarray:
    n = int(0.3 * SR)
    t = np.arange(n, dtype=np.float64) / SR
    noise = _butter_filter(_noise(n, rng), 5000.0, "low")
    env = np.zeros(n, dtype=np.float32)
    for offset in (0.0, 0.011, 0.021, 0.031):
        start = int(offset * SR)
        length = min(n - start, int(0.19 * SR))
        if length > 0:
            local = np.exp(-np.arange(length) / (0.035 * SR))
            env[start : start + length] += local.astype(np.float32)
    return (noise * env * 0.36).astype(np.float32)


def _hat(rng: random.Random, open_hat: bool = False) -> np.ndarray:
    length = 0.28 if open_hat else 0.075
    n = int(length * SR)
    noise = _noise(n, rng)
    noise = noise - np.concatenate([[0.0], noise[:-1]])
    noise = _butter_filter(noise, 6200.0, "high")
    env = np.exp(-np.arange(n) / ((0.085 if open_hat else 0.018) * SR))
    return (noise * env * (0.16 if open_hat else 0.13)).astype(np.float32)


def _bass_note(freq: float, duration: float, brightness: float = 0.5, sr: int = SR) -> np.ndarray:
    n = max(1, int(duration * sr))
    base = _sine(freq, n)
    harm = np.zeros(n, dtype=np.float32)
    for harmonic, amplitude in ((2, 0.24), (3, 0.12 * brightness), (4, 0.06 * brightness)):
        harm += _sine(freq * harmonic, n, phase=harmonic * 0.7) * amplitude
    value = base * 0.85 + harm
    value = _one_pole_lowpass(value, 220.0 + 900.0 * brightness)
    env = _env(n, 0.008, 0.08, 0.76, min(0.35, max(0.05, duration * 0.25)))
    return np.tanh(value * env * 1.25).astype(np.float32)


def _chord_note(freq: float, duration: float, brightness: float, sr: int = SR) -> np.ndarray:
    n = max(1, int(duration * sr))
    value = np.zeros(n, dtype=np.float32)
    value += _saw(freq, n) * 0.42
    value += _saw(freq * 1.004, n, phase=0.13) * 0.28
    value += _sine(freq * 0.5, n) * 0.18
    value += _sine(freq * 2.0, n) * (0.10 * brightness)
    value = _one_pole_lowpass(value, 900.0 + 5200.0 * brightness)
    env = _env(n, 0.02, 0.12, 0.78, min(0.7, max(0.18, duration * 0.4)))
    return (value * env * 0.38).astype(np.float32)


def _pluck(freq: float, duration: float, sr: int = SR) -> np.ndarray:
    n = max(1, int(duration * sr))
    value = _triangle(freq, n) * 0.55 + _sine(freq * 2.0, n) * 0.18
    env = np.exp(-np.arange(n) / (max(0.03, duration * 0.22) * sr)).astype(np.float32)
    return (value * env * 0.28).astype(np.float32)


def _pad_note(freq: float, duration: float, sr: int = SR) -> np.ndarray:
    n = max(1, int(duration * sr))
    value = (
        _sine(freq, n) * 0.45
        + _sine(freq * 1.002, n, phase=0.25) * 0.35
        + _saw(freq * 0.5, n) * 0.18
    )
    value = _one_pole_lowpass(value, 2600.0)
    env = _env(n, min(0.8, duration * 0.25), 0.2, 0.75, min(1.2, duration * 0.4))
    return (value * env * 0.24).astype(np.float32)


def _riser(duration: float, rng: random.Random, sr: int = SR) -> np.ndarray:
    n = max(1, int(duration * sr))
    noise = _noise(n, rng)
    # Segmented band-pass sweep, cheap and effective.
    result = np.zeros(n, dtype=np.float32)
    segments = 24
    block = max(1, n // segments)
    for index in range(segments):
        start = index * block
        end = min(n, start + block + block // 3)
        cutoff = 500.0 * (2.0 ** (index / segments * 5.0))
        piece = _butter_filter(noise[start:end], cutoff, "high")
        result[start : start + min(len(piece), n - start)] += piece[: n - start]
    env = np.linspace(0.0, 1.0, n) ** 2
    return (result * env * 0.14).astype(np.float32)


def _impact(rng: random.Random, sr: int = SR) -> np.ndarray:
    n = int(1.2 * sr)
    t = np.arange(n, dtype=np.float64) / sr
    low = np.sin(2 * np.pi * (55.0 * np.exp(-t * 2.4) + 28.0) * t) * np.exp(-t * 4.0)
    noise = _butter_filter(_noise(n, rng), 1800.0, "low") * np.exp(-t * 6.0)
    return ((low * 0.6 + noise * 0.2) * 1.8).astype(np.float32)


def _chord_midi(tonic: int, mode: str, degree: int) -> list[int]:
    scale = MAJOR_SCALE if mode == "major" else MINOR_SCALE
    root_pc = (tonic + scale[degree % 7]) % 12
    root = 48 + root_pc
    if mode == "major":
        intervals = [0, 4, 7, 11]
    else:
        intervals = [0, 3, 7, 10]
    return [root + interval for interval in intervals]


def _drum_events(family: str, role: str, bar: int, energy: float, rng: random.Random, swing: float) -> list[tuple[float, str, float]]:
    events: list[tuple[float, str, float]] = []
    dense = 0.78 + energy * 0.32
    if family in {"four", "pop"}:
        for beat in range(4):
            events.append((beat, "kick", 0.95 if beat % 2 == 0 else 0.85))
        events.extend([(1, "clap", 0.72), (3, "clap", 0.78)])
        for step in np.arange(0, 4, 0.5):
            swing_offset = swing * (0.5 if int(step * 2) % 2 else 0.0)
            events.append((step + swing_offset, "hat", (0.30 if int(step * 2) % 2 else 0.44) * dense))
        if energy > 0.55:
            for beat in (0.5, 1.5, 2.5, 3.5):
                events.append((beat, "ohat", 0.27 * dense))
        if family == "four" and role in {"drop", "chorus"}:
            events.append((2, "perc", 0.35))
    elif family == "breaks":
        events.extend([(0, "kick", 1.0), (2.5, "kick", 0.75), (3.75, "kick", 0.62)])
        events.extend([(1, "snare", 0.82), (3, "snare", 0.9)])
        for step in np.arange(0, 4, 0.25):
            events.append((step, "hat", (0.35 if int(step * 4) % 2 else 0.22) * dense))
    elif family == "hiphop":
        events.extend([(0, "kick", 1.0), (2.5, "kick", 0.82), (2.75, "kick", 0.55)])
        events.extend([(1, "snare", 0.86), (3, "snare", 0.9)])
        for step in np.arange(0, 4, 0.5):
            events.append((step + swing * (0.5 if int(step * 2) % 2 else 0.0), "hat", (0.42 if int(step * 2) % 2 else 0.28) * dense))
        if energy > 0.6:
            events.append((3.75, "kick", 0.45))
    elif family == "trap":
        events.extend([(0, "kick", 1.0), (2.75, "kick", 0.85)])
        events.append((2, "clap", 0.9))
        for index, step in enumerate(np.arange(0, 4, 0.25)):
            velocity = (0.24 if index % 2 else 0.42) * dense
            events.append((step, "hat", velocity))
        if energy > 0.7:
            for step in np.arange(3.5, 4.0, 0.125):
                events.append((step, "hat", 0.25))
    elif family == "dembow":
        events.extend([(0, "kick", 1.0), (2, "kick", 0.95)])
        events.extend([(0.75, "snare", 0.62), (1.5, "snare", 0.68), (2.75, "snare", 0.64), (3.5, "snare", 0.7)])
        for step in np.arange(0, 4, 0.5):
            events.append((step, "hat", 0.28 * dense))
    elif family == "rock":
        events.extend([(0, "kick", 1.0), (2, "kick", 0.9)])
        events.extend([(1, "snare", 0.9), (3, "snare", 0.88)])
        for step in np.arange(0, 4, 0.5):
            events.append((step, "hat", 0.30 * dense))
    elif family == "smooth":
        events.extend([(0, "kick", 0.82), (2.5, "kick", 0.62)])
        events.extend([(1, "snare", 0.65), (3, "snare", 0.7)])
        for step in np.arange(0, 4, 0.5):
            events.append((step + swing * 0.5, "hat", 0.22 * dense))
    elif family == "lofi":
        events.extend([(0, "kick", 0.85), (2.5, "kick", 0.65)])
        events.extend([(1, "snare", 0.65), (3, "snare", 0.7)])
        for step in np.arange(0, 4, 0.5):
            events.append((step + swing * (0.5 if int(step * 2) % 2 else 0.0), "hat", 0.2 * dense))
    elif family == "ambient":
        if energy > 0.48:
            events.append((0, "kick", 0.35))
    elif family == "cinematic":
        if energy > 0.55:
            events.extend([(0, "kick", 0.45), (2, "kick", 0.35)])
        if energy > 0.7:
            events.append((2, "snare", 0.3))

    if role == "build":
        for step in np.arange(0, 4, 0.25):
            events.append((step, "snare", 0.18 + 0.45 * (step / 4.0)))
    if role in {"breakdown", "intro", "outro"}:
        events = [event for event in events if event[1] in {"hat", "ohat", "perc"}]
    if role in {"drop", "chorus"} and energy > 0.7:
        events.append((0, "impact", 1.0))
    return events


def _bass_events(family: str, role: str, bar: int) -> list[tuple[float, float]]:
    if role in {"intro", "breakdown", "outro"}:
        return [(0.0, 4.0)]
    if family == "four":
        return [(0.5, 0.42), (1.5, 0.42), (2.5, 0.42), (3.5, 0.42), (3.75, 0.25)]
    if family == "breaks":
        return [(0.0, 0.6), (1.75, 0.35), (2.5, 0.5), (3.5, 0.4)]
    if family == "hiphop":
        return [(0.0, 1.2), (2.5, 0.8), (3.0, 0.6)]
    if family == "trap":
        return [(0.0, 1.7), (2.75, 0.9)]
    if family == "dembow":
        return [(0.0, 0.55), (0.75, 0.4), (2.0, 0.55), (2.75, 0.4)]
    if family in {"rock", "pop"}:
        return [(0.0, 1.0), (2.0, 0.9)]
    if family == "smooth":
        return [(0.0, 1.8), (2.5, 0.9)]
    if family == "lofi":
        return [(0.0, 1.8), (2.5, 0.75)]
    if family in {"ambient", "cinematic"}:
        return [(0.0, 4.0)]
    return [(0.0, 0.9), (2.0, 0.8)]


def _arp_pattern(family: str) -> list[float]:
    if family in {"four", "trance"}:
        return list(np.arange(0, 4, 0.25))
    if family in {"breaks", "trap"}:
        return [0.0, 0.25, 0.75, 1.0, 1.5, 2.0, 2.5, 2.75, 3.0, 3.5]
    return list(np.arange(0, 4, 0.5))


def render_track(
    *,
    style: str,
    bpm: float,
    key: str,
    duration: float,
    sections: list[dict[str, Any]],
    seed: int | None = None,
    energy: float = 0.68,
    brightness: float = 0.5,
    model: dict[str, Any] | None = None,
    progress: Callable[[float, str, str], None] | None = None,
) -> dict[str, Any]:
    """Render a track and return float32 stereo stems plus metadata."""
    rng = _rng(seed)
    style = style or "House"
    family = STYLE_FAMILY.get(style, "four")
    tonic, mode = parse_key(key)
    bpm = float(min(max(bpm or 120.0, 55.0), 200.0))
    duration = float(min(max(duration or 180.0, 20.0), 900.0))
    beat = 60.0 / bpm
    bar = beat * 4
    total = int(math.ceil(duration * SR))
    drums = np.zeros(total, dtype=np.float32)
    bass = np.zeros(total, dtype=np.float32)
    harmony = np.zeros(total, dtype=np.float32)
    arp = np.zeros(total, dtype=np.float32)
    fx = np.zeros(total, dtype=np.float32)
    swing = float((model or {}).get("swing") or STYLE_SWING.get(style, 0.02))
    energy = float(min(max(energy, 0.05), 1.0))
    brightness = float(min(max(brightness, 0.0), 1.0))
    progressions = MINOR_PROGRESSIONS if mode == "minor" else MAJOR_PROGRESSIONS
    progression = progressions[(int(seed or 0) // 7) % len(progressions)]
    kick_sample = _kick(rng)
    snare_sample = _snare(rng)
    clap_sample = _clap(rng)
    hat_sample = _hat(rng)
    ohat_sample = _hat(rng, True)
    perc_sample = _hat(rng)
    impact_sample = _impact(rng)

    section_list = sections or []
    for section_index, section in enumerate(section_list):
        if progress:
            progress(
                18.0 + (section_index / max(1, len(section_list))) * 52.0,
                "Synthesising",
                f"{section.get('label') or section.get('role')} · {section.get('energy')}%",
            )
        role = str(section.get("role") or "groove")
        layers = set(section.get("layers") or [])
        start = float(section.get("start") or 0.0)
        end = float(section.get("end") or (start + bar * 4))
        section_energy = float(section.get("energy") or 60) / 100.0
        section_energy = (section_energy + energy) * 0.5
        if end <= start:
            continue
        first_bar = int(math.floor(start / bar))
        last_bar = max(first_bar + 1, int(math.ceil(end / bar)))
        for bar_index in range(first_bar, last_bar):
            bar_start = bar_index * bar
            if bar_start >= duration:
                break
            bar_energy = section_energy * (0.92 + 0.08 * math.sin(bar_index * 0.7))
            chord = _chord_midi(tonic, mode, progression[bar_index % len(progression)])
            chord_root = chord[0]

            if "drums" in layers:
                for beat_pos, instrument, velocity in _drum_events(family, role, bar_index, bar_energy, rng, swing):
                    at = bar_start + beat_pos * beat
                    if at >= end - 0.01:
                        continue
                    sample = {
                        "kick": kick_sample,
                        "snare": snare_sample,
                        "clap": clap_sample,
                        "hat": hat_sample,
                        "ohat": ohat_sample,
                        "perc": perc_sample,
                        "impact": impact_sample,
                    }.get(instrument)
                    if sample is None:
                        continue
                    gain = velocity * (0.72 + bar_energy * 0.32)
                    _add(drums, int(at * SR), sample, gain)

            if "bass" in layers:
                for beat_pos, beats in _bass_events(family, role, bar_index):
                    at = bar_start + beat_pos * beat
                    if at >= end - 0.02:
                        continue
                    note_len = beats * beat
                    note = _bass_note(midi_hz(chord_root - 12), note_len, brightness=brightness)
                    _add(bass, int(at * SR), note, 0.9 * (0.65 + bar_energy * 0.5))

            if "chords" in layers:
                chord_duration = min(bar, max(beat * 0.9, end - bar_start))
                for midi in chord:
                    note = _chord_note(midi_hz(midi + 12), chord_duration, brightness=brightness)
                    _add(harmony, int(bar_start * SR), note, 0.72 * (0.5 + bar_energy * 0.5))
                if role in {"drop", "chorus"} and family in {"four", "pop", "rock"}:
                    for offbeat in (0.5, 1.5, 2.5, 3.5):
                        stab_len = beat * 0.32
                        for midi in chord[:3]:
                            note = _pluck(midi_hz(midi + 24), stab_len)
                            _add(arp, int((bar_start + offbeat * beat) * SR), note, 0.38)

            if "arp" in layers and family not in {"ambient", "cinematic", "smooth", "lofi"}:
                pattern = _arp_pattern(family)
                for index, beat_pos in enumerate(pattern):
                    at = bar_start + beat_pos * beat
                    if at >= end - 0.01:
                        continue
                    midi = chord[1 + index % 3] + 24 + (12 if index % 4 == 3 else 0)
                    note = _pluck(midi_hz(midi), min(beat * 0.45, 0.5))
                    _add(arp, int(at * SR), note, 0.32 * (0.55 + bar_energy * 0.45))

            if "riser" in layers and bar_index == first_bar:
                riser = _riser(max(bar, end - start), rng)
                _add(fx, int(start * SR), riser, 0.8)
            if "impact" in layers and bar_index == first_bar:
                _add(fx, int(start * SR), impact_sample, 0.8)

    # Sidechain the harmonic layers against the kick grid for a club feel.
    if family in {"four", "breaks", "dembow"}:
        sidechain = np.ones(total, dtype=np.float32)
        step = max(1, int(beat * SR))
        for start in range(0, total, step):
            length = min(step, total - start)
            curve = 0.55 + 0.45 * np.linspace(0.0, 1.0, length)
            sidechain[start : start + length] *= curve.astype(np.float32)
        harmony *= sidechain
        arp *= sidechain

    # Gentle filtering keeps pads from masking the bass on big systems.
    harmony = _butter_filter(harmony, 9000.0, "low")
    arp = _butter_filter(arp, 12000.0, "low")

    stems = {
        "drums": _stereo(drums, 0.0),
        "bass": _stereo(bass, 0.0),
        "harmony": _stereo(harmony, 0.007),
        "arp": _stereo(arp, 0.012),
        "fx": _stereo(fx, 0.004),
    }
    mix = (
        stems["drums"] * 0.94
        + stems["bass"] * 0.82
        + stems["harmony"] * 0.72
        + stems["arp"] * 0.55
        + stems["fx"] * 0.65
    )
    mix = np.stack(
        [_butter_filter(mix[:, 0], 24.0, "high"), _butter_filter(mix[:, 1], 24.0, "high")],
        axis=1,
    )
    mix = np.tanh(mix * 1.1)
    peak = float(np.max(np.abs(mix)))
    if peak > 0:
        mix = mix / peak * 0.92
    fade = min(int(0.06 * SR), len(mix) // 4)
    if fade > 0:
        mix[:fade] *= np.linspace(0.0, 1.0, fade, dtype=np.float32)[:, None]
    out_fade = min(int(1.4 * SR), len(mix) // 3)
    if out_fade > 0:
        mix[-out_fade:] *= np.linspace(1.0, 0.0, out_fade, dtype=np.float32)[:, None]

    metadata = {
        "style": style,
        "family": family,
        "bpm": round(bpm, 2),
        "key": key,
        "duration": round(total / SR, 3),
        "energy": round(energy, 3),
        "brightness": round(brightness, 3),
        "seed": int(seed if seed is not None else 7),
        "sections": sections,
        "stems": list(stems),
    }
    return {"mix": mix.astype(np.float32), "stems": stems, "metadata": metadata}
