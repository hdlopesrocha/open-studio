"""Audio analysis, key detection and style inference for the DJ studio.

Librosa is imported lazily so the pure planning/model helpers remain cheap to
import in tests and in the HTTP process before a job needs analysis.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

SAMPLE_RATE = 22050
HOP_LENGTH = 512
N_FFT = 2048
WAVEFORM_POINTS = 480

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

MAJOR_PROFILE = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88], dtype=np.float64
)
MINOR_PROFILE = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17], dtype=np.float64
)

CAMELOT_MAJOR = {
    "C": "8B", "C#": "3B", "D": "10B", "D#": "5B", "E": "12B", "F": "7B",
    "F#": "2B", "G": "9B", "G#": "4B", "A": "11B", "A#": "6B", "B": "1B",
}
CAMELOT_MINOR = {
    "C": "5A", "C#": "12A", "D": "7A", "D#": "2A", "E": "9A", "F": "4A",
    "F#": "11A", "G": "6A", "G#": "1A", "A": "8A", "A#": "3A", "B": "10A",
}

# Feature centroids used by the local style inference engine. They describe a
# typical production for each style rather than a fixed genre rule: uploaded
# tracks are compared with every profile and the closest one wins.
STYLE_PROFILES: dict[str, dict[str, float]] = {
    "House": {"bpm": 124, "energy": 0.68, "dance": 0.86, "low": 0.34, "mid": 0.44, "high": 0.22, "perc": 0.62, "centroid": 0.43},
    "Techno": {"bpm": 134, "energy": 0.82, "dance": 0.72, "low": 0.39, "mid": 0.41, "high": 0.20, "perc": 0.71, "centroid": 0.39},
    "Trance": {"bpm": 138, "energy": 0.80, "dance": 0.78, "low": 0.29, "mid": 0.44, "high": 0.27, "perc": 0.58, "centroid": 0.51},
    "Drum & Bass": {"bpm": 174, "energy": 0.84, "dance": 0.66, "low": 0.40, "mid": 0.38, "high": 0.22, "perc": 0.77, "centroid": 0.45},
    "Hip-Hop": {"bpm": 92, "energy": 0.72, "dance": 0.74, "low": 0.43, "mid": 0.39, "high": 0.18, "perc": 0.66, "centroid": 0.33},
    "Trap": {"bpm": 140, "energy": 0.78, "dance": 0.62, "low": 0.49, "mid": 0.33, "high": 0.18, "perc": 0.59, "centroid": 0.34},
    "R&B": {"bpm": 88, "energy": 0.52, "dance": 0.66, "low": 0.32, "mid": 0.45, "high": 0.23, "perc": 0.42, "centroid": 0.40},
    "Pop": {"bpm": 112, "energy": 0.70, "dance": 0.82, "low": 0.28, "mid": 0.48, "high": 0.24, "perc": 0.52, "centroid": 0.49},
    "Rock": {"bpm": 124, "energy": 0.78, "dance": 0.55, "low": 0.30, "mid": 0.48, "high": 0.22, "perc": 0.64, "centroid": 0.53},
    "Lo-fi": {"bpm": 82, "energy": 0.38, "dance": 0.60, "low": 0.36, "mid": 0.44, "high": 0.20, "perc": 0.35, "centroid": 0.30},
    "Disco & Funk": {"bpm": 116, "energy": 0.72, "dance": 0.88, "low": 0.32, "mid": 0.45, "high": 0.23, "perc": 0.63, "centroid": 0.47},
    "Reggaeton": {"bpm": 96, "energy": 0.70, "dance": 0.78, "low": 0.43, "mid": 0.39, "high": 0.18, "perc": 0.64, "centroid": 0.36},
    "Ambient": {"bpm": 72, "energy": 0.22, "dance": 0.30, "low": 0.30, "mid": 0.42, "high": 0.28, "perc": 0.18, "centroid": 0.35},
    "Cinematic": {"bpm": 95, "energy": 0.56, "dance": 0.35, "low": 0.36, "mid": 0.39, "high": 0.25, "perc": 0.30, "centroid": 0.36},
}

STYLE_LABELS = {
    "Drum & Bass": "Drum & Bass",
    "Disco & Funk": "Disco & Funk",
    "R&B": "R&B",
    "Lo-fi": "Lo-fi",
} | {name: name for name in STYLE_PROFILES}

STYLE_ALIASES = {
    "dnb": "Drum & Bass",
    "drum and bass": "Drum & Bass",
    "drum n bass": "Drum & Bass",
    "edm": "House",
    "electronic": "House",
    "deep house": "House",
    "tech house": "House",
    "afro house": "House",
    "hip hop": "Hip-Hop",
    "rap": "Hip-Hop",
    "trap music": "Trap",
    "rnb": "R&B",
    "r&b": "R&B",
    "soul": "R&B",
    "lofi": "Lo-fi",
    "lo fi": "Lo-fi",
    "disco": "Disco & Funk",
    "funk": "Disco & Funk",
    "reggaeton": "Reggaeton",
    "dancehall": "Reggaeton",
    "film score": "Cinematic",
    "orchestral": "Cinematic",
    "soundtrack": "Cinematic",
    "ambient techno": "Ambient",
}


def canonical_style(value: str | None) -> str:
    raw = (value or "").strip()
    if raw in STYLE_PROFILES:
        return raw
    lowered = raw.lower().replace("_", " ").strip()
    if lowered in STYLE_ALIASES:
        return STYLE_ALIASES[lowered]
    for name in STYLE_PROFILES:
        if lowered == name.lower():
            return name
    return ""


def camelot_for(key: str, mode: str) -> str:
    tonic = (key or "A").strip()
    if tonic not in NOTE_NAMES:
        tonic = "A"
    table = CAMELOT_MINOR if (mode or "").lower().startswith("min") else CAMELOT_MAJOR
    return table.get(tonic, "8A")


def key_name(tonic: int, mode: str) -> str:
    return f"{NOTE_NAMES[int(tonic) % 12]} {mode}"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _normalise(values: np.ndarray) -> np.ndarray:
    values = np.nan_to_num(np.asarray(values, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
    low = float(np.percentile(values, 5)) if values.size else 0.0
    high = float(np.percentile(values, 95)) if values.size else 1.0
    if high - low < 1e-9:
        return np.zeros_like(values)
    return np.clip((values - low) / (high - low), 0.0, 1.0)


def detect_key(chroma_mean: np.ndarray) -> tuple[str, str, float, str]:
    chroma = np.nan_to_num(np.asarray(chroma_mean, dtype=np.float64))
    if float(chroma.sum()) <= 1e-9:
        return "A", "minor", 0.0, "8A"
    chroma = chroma / chroma.sum()
    scores: list[tuple[float, int, str]] = []
    for tonic in range(12):
        for mode, profile in (("major", MAJOR_PROFILE), ("minor", MINOR_PROFILE)):
            rotated = np.roll(profile, tonic)
            score = float(np.corrcoef(chroma, rotated)[0, 1])
            if math.isfinite(score):
                scores.append((score, tonic, mode))
    scores.sort(reverse=True)
    best = scores[0]
    runner_up = scores[1][0] if len(scores) > 1 else best[0] - 0.2
    confidence = float(np.clip((best[0] - runner_up + 0.05) * 2.2, 0.05, 0.99))
    name = key_name(best[1], best[2])
    camelot = camelot_for(NOTE_NAMES[best[1]], best[2])
    return NOTE_NAMES[best[1]], best[2], confidence, camelot


def classify_style(
    *,
    bpm: float,
    energy: float,
    danceability: float,
    low: float,
    mid: float,
    high: float,
    percussiveness: float,
    centroid: float,
) -> tuple[str, float, list[str]]:
    bpm = max(1.0, _safe_float(bpm, 120.0))
    costs: list[tuple[float, str]] = []
    for name, profile in STYLE_PROFILES.items():
        bpm_cost = abs(math.log2(bpm / max(profile["bpm"], 1.0))) / 0.585
        cost = (
            1.85 * bpm_cost
            + 1.55 * abs(energy - profile["energy"])
            + 0.75 * abs(danceability - profile["dance"])
            + 0.65 * abs(low - profile["low"])
            + 0.45 * abs(mid - profile["mid"])
            + 0.45 * abs(high - profile["high"])
            + 0.75 * abs(percussiveness - profile["perc"])
            + 0.65 * abs(centroid - profile["centroid"])
        )
        costs.append((cost, name))
    costs.sort()
    weights = np.array([math.exp(-cost * 2.1) for cost, _ in costs], dtype=np.float64)
    probabilities = weights / max(weights.sum(), 1e-9)
    top_name = costs[0][1]
    confidence = float(np.clip(probabilities[0], 0.05, 0.99))
    tags = [top_name]
    if len(costs) > 1 and probabilities[1] >= 0.12:
        tags.append(costs[1][1])
    return top_name, confidence, tags


def classify_mood(energy: float, valence: float) -> str:
    energy = _safe_float(energy, 0.5)
    valence = _safe_float(valence, 0.5)
    if energy >= 0.74:
        return "Euphoric" if valence >= 0.58 else "Driving / Dark"
    if energy >= 0.48:
        if valence >= 0.64:
            return "Warm / Uplifting"
        if valence <= 0.38:
            return "Melancholic"
        return "Balanced"
    if valence >= 0.55:
        return "Dreamy"
    return "Introspective"


def _energy_curve(rms: np.ndarray, duration: float, points: int = WAVEFORM_POINTS) -> list[float]:
    values = _normalise(rms)
    if values.size == 0:
        return [0.0] * points
    grid = np.linspace(0, values.size - 1, points)
    sampled = np.interp(grid, np.arange(values.size), values)
    return [round(float(value), 4) for value in sampled]


def _bar_boundaries(duration: float, bpm: float, downbeats: list[float] | None) -> tuple[list[float], float]:
    bar_seconds = max(60.0 / max(bpm, 1.0) * 4.0, 0.5)
    boundaries = [0.0]
    for value in sorted(float(item) for item in (downbeats or [])):
        if 0.3 < value < duration - 0.3 and value - boundaries[-1] >= max(0.35, bar_seconds * 0.45):
            boundaries.append(value)
    if boundaries[-1] < duration - 0.1:
        boundaries.append(duration)
    if len(boundaries) < 5:
        bars = max(2, int(round(duration / bar_seconds)))
        boundaries = [min(duration, index * duration / bars) for index in range(bars + 1)]
    return boundaries, bar_seconds


def _feature_matrix(
    *,
    boundaries: list[float],
    frame_times: np.ndarray,
    rms: np.ndarray,
    mfcc: np.ndarray | None,
    chroma: np.ndarray | None,
    centroid: np.ndarray | None,
    bandwidth: np.ndarray | None,
    flatness: np.ndarray | None,
    onset_env: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build bar-synchronous timbre/energy features for structural analysis."""
    frame_count = max(1, len(frame_times))

    def align(feature: np.ndarray | None) -> np.ndarray | None:
        if feature is None:
            return None
        value = np.nan_to_num(np.asarray(feature, dtype=np.float64))
        if value.ndim == 1:
            return value[:frame_count]
        return value[:, :frame_count]

    mfcc = align(mfcc)
    chroma = align(chroma)
    centroid = align(centroid)
    bandwidth = align(bandwidth)
    flatness = align(flatness)
    onset_env = align(onset_env)
    rms = np.nan_to_num(np.asarray(rms, dtype=np.float64))[:frame_count]
    rows: list[list[float]] = []
    for start, end in zip(boundaries, boundaries[1:]):
        mask = (frame_times >= start) & (frame_times < max(end, start + 0.01))
        if not mask.any() and frame_count:
            index = int(np.clip(np.searchsorted(frame_times, (start + end) / 2.0), 0, frame_count - 1))
            mask = np.zeros(frame_count, dtype=bool)
            mask[index] = True
        rms_value = float(np.mean(rms[mask])) if mask.any() else 1e-6
        rms_db = 20.0 * math.log10(max(rms_value, 1e-6))
        onset_values = onset_env[mask] if onset_env is not None and mask.any() else np.zeros(1)
        mfcc_values = mfcc[:, mask] if mfcc is not None and mask.any() else np.zeros((12, 1))
        chroma_values = chroma[:, mask] if chroma is not None and mask.any() else np.zeros((12, 1))
        centroid_value = float(np.mean(centroid[mask])) if centroid is not None and mask.any() else 0.0
        bandwidth_value = float(np.mean(bandwidth[mask])) if bandwidth is not None and mask.any() else 0.0
        flatness_value = float(np.mean(flatness[mask])) if flatness is not None and mask.any() else 0.0
        centroid_norm = float(np.clip(np.log2(max(centroid_value, 40.0) / 40.0) / math.log2(12000.0 / 40.0), 0.0, 1.0))
        bandwidth_norm = float(np.clip(np.log2(max(bandwidth_value, 40.0) / 40.0) / math.log2(12000.0 / 40.0), 0.0, 1.0))
        mfcc_mean = np.mean(mfcc_values[1:13], axis=1)[:12]
        chroma_mean = np.mean(chroma_values, axis=1)[:12]
        rows.append(
            [
                rms_db,
                float(np.mean(onset_values)),
                float(np.std(onset_values)),
                *[float(value) for value in mfcc_mean],
                *[float(value) for value in chroma_mean],
                centroid_norm,
                bandwidth_norm,
                flatness_value,
            ]
        )

    raw = np.asarray(rows, dtype=np.float64)
    if len(raw) < 2:
        levels = np.clip(raw[:, 0] / max(float(np.max(raw[:, 0])), 1e-9), 0.0, 1.0) if len(raw) else np.zeros(1)
        return raw, np.zeros_like(raw), levels
    mean = np.mean(raw, axis=0)
    std = np.std(raw, axis=0)
    std[std < 1e-8] = 1.0
    normalized = (raw - mean) / std
    weights = np.asarray([1.4, 0.8, 0.5] + [0.8] * 12 + [0.6] * 12 + [0.9, 0.6, 0.7], dtype=np.float64)
    normalized *= weights[: normalized.shape[1]]
    norms = np.linalg.norm(normalized, axis=1, keepdims=True)
    norms[norms < 1e-9] = 1.0
    normalized /= norms
    low = float(np.percentile(raw[:, 0], 10))
    high = float(np.percentile(raw[:, 0], 90))
    levels = np.clip((raw[:, 0] - low) / max(high - low, 0.1), 0.0, 1.0)
    return raw, normalized, levels


def _novelty_curve(normalized: np.ndarray, half: int) -> np.ndarray:
    """Foote-style checkerboard novelty on the bar self-similarity matrix."""
    count = len(normalized)
    if count < 3:
        return np.zeros(count, dtype=np.float64)
    similarity = np.clip(normalized @ normalized.T, -1.0, 1.0)
    similarity = (similarity + 1.0) / 2.0
    axis = np.arange(-half, half + 1, dtype=np.float64)
    sigma = max(1.0, half / 2.0)
    window = np.exp(-(axis**2) / (2.0 * sigma**2))
    kernel = np.outer(window, window)
    kernel[: half + 1, : half + 1] *= -1.0
    kernel[half + 1 :, half + 1 :] *= -1.0
    padded = np.pad(similarity, half, mode="edge")
    novelty = np.zeros(count, dtype=np.float64)
    for index in range(count):
        novelty[index] = float(np.sum(padded[index : index + 2 * half + 1, index : index + 2 * half + 1] * kernel))
    novelty -= float(novelty.min())
    peak = float(novelty.max())
    if peak > 1e-9:
        novelty /= peak
    return novelty


def _section_labels(
    *,
    boundaries: list[float],
    selected: list[int],
    levels: np.ndarray,
    novelty: np.ndarray,
    valence: float,
    style: str,
) -> list[dict[str, Any]]:
    song_style = style in {"Pop", "Rock", "Hip-Hop", "R&B", "Trap", "Lo-fi"}
    role_base = {
        "intro": "Intro", "build": "Build", "drop": "Drop", "chorus": "Chorus",
        "breakdown": "Breakdown", "groove": "Groove", "verse": "Verse", "outro": "Outro",
    }
    role_note = {
        "intro": "filtered opening, sparse percussion",
        "build": "rising filter, snare roll, tension",
        "drop": "full drums, sub bass, wide synths",
        "chorus": "main hook, open chords, bright top end",
        "breakdown": "reduced drums, exposed harmony",
        "groove": "steady DJ groove, full rhythm",
        "verse": "song groove with space for vocals",
        "outro": "thinning arrangement and release",
    }
    layers_for = {
        "intro": ["chords", "arp"],
        "build": ["drums", "bass", "chords", "arp", "riser"],
        "drop": ["drums", "bass", "chords", "arp", "impact"],
        "chorus": ["drums", "bass", "chords", "arp", "impact"],
        "breakdown": ["chords", "arp", "fx"],
        "groove": ["drums", "bass", "chords", "arp"],
        "verse": ["drums", "bass", "chords", "arp"],
        "outro": ["chords", "arp"],
    }
    section_levels = [float(np.mean(levels[start:end])) if end > start else 0.0 for start, end in zip(selected, selected[1:])]
    maximum = max(section_levels) if section_levels else 1.0
    maximum = max(maximum, 1e-9)
    draft: list[dict[str, Any]] = []
    for index, (start_index, end_index) in enumerate(zip(selected, selected[1:])):
        level = section_levels[index]
        next_level = section_levels[index + 1] if index + 1 < len(section_levels) else level
        values = levels[start_index:end_index]
        slope = float(np.polyfit(np.arange(len(values)), values, 1)[0]) if len(values) > 1 else 0.0
        if index == 0 and (level <= max(0.55, maximum * 0.82) or (end_index - start_index) <= max(2, round(len(levels) * 0.12))):
            role = "intro"
        elif index == len(section_levels) - 1:
            role = "outro"
        elif level <= max(0.38, maximum * 0.48):
            role = "breakdown"
        elif slope > 0.025 and next_level > level + 0.04 and level < maximum * 0.95:
            role = "build"
        elif level >= max(0.68, maximum * 0.80):
            role = "chorus" if song_style else "drop"
        else:
            role = "verse" if song_style else "groove"
        draft.append(
            {
                "start": float(boundaries[start_index]),
                "end": float(boundaries[end_index]),
                "start_bar": int(start_index),
                "end_bar": int(end_index),
                "bars": int(max(1, end_index - start_index)),
                "level": float(level),
                "role": role,
                "slope": slope,
                "boundary_strength": float(novelty[min(start_index, len(novelty) - 1)]) if len(novelty) else 0.0,
            }
        )

    # A continuous high-energy stretch can be split into several novelty
    # segments by internal drum fills. Merge only adjacent same-role fragments
    # when the boundary is weak and the combined scene stays reasonably short;
    # strong transitions inside a long drop/chorus remain separate scenes.
    max_merge_bars = max(12, int(round(len(levels) * 0.15)))
    merged: list[dict[str, Any]] = []
    for section in draft:
        if (
            merged
            and merged[-1]["role"] == section["role"]
            and section["role"] not in {"intro", "outro"}
            and section["boundary_strength"] < 0.70
            and merged[-1]["bars"] + section["bars"] <= max_merge_bars
        ):
            previous = merged[-1]
            total_bars = max(1, previous["bars"] + section["bars"])
            level = (previous["level"] * previous["bars"] + section["level"] * section["bars"]) / total_bars
            previous.update(
                {
                    "end": section["end"],
                    "end_bar": section["end_bar"],
                    "bars": total_bars,
                    "level": level,
                    "slope": (previous["slope"] + section["slope"]) / 2.0,
                    "boundary_strength": max(previous["boundary_strength"], section["boundary_strength"]),
                }
            )
        else:
            merged.append(section)

    counters: dict[str, int] = {}
    sections: list[dict[str, Any]] = []
    for index, section in enumerate(merged):
        role = section["role"]
        level = float(section["level"])
        counters[role] = counters.get(role, 0) + 1
        base = role_base[role]
        label = base if role in {"intro", "outro"} or counters[role] == 1 else f"{base} {counters[role]}"
        energy = round(float(np.clip(12.0 + level * 88.0, 8.0, 100.0)), 1)
        mood = classify_mood(level, valence)
        sections.append(
            {
                "index": index,
                "scene_id": f"scene-{index + 1}",
                "start": round(float(section["start"]), 3),
                "end": round(float(section["end"]), 3),
                "start_bar": int(section["start_bar"]),
                "end_bar": int(section["end_bar"]),
                "bars": int(section["bars"]),
                "energy": energy,
                "level": round(level, 4),
                "role": role,
                "label": label,
                "mood": mood,
                "filter_hz": int(600 + (level**1.2) * 16000),
                "layers": layers_for[role],
                "boundary_strength": round(float(section["boundary_strength"]), 4),
                "slope": round(float(section["slope"]), 5),
                "summary": f"{label} · {energy:.0f}% energy · {mood} · {role_note[role]}",
            }
        )
    return sections


def _sections(
    *,
    duration: float,
    bpm: float,
    rms: np.ndarray,
    frame_times: np.ndarray,
    valence: float,
    style: str,
    downbeats: list[float] | None = None,
    mfcc: np.ndarray | None = None,
    chroma: np.ndarray | None = None,
    centroid: np.ndarray | None = None,
    bandwidth: np.ndarray | None = None,
    flatness: np.ndarray | None = None,
    onset_env: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    """Detect structural scenes on bar boundaries using timbre/harmony novelty.

    The old implementation sliced the track into fixed 4/8/16-bar chunks. This
    version builds bar-level MFCC/chroma/spectral/energy features, computes a
    checkerboard novelty curve on the self-similarity matrix, and picks the
    strongest change points with a minimum section length. The result follows
    the actual arrangement instead of an arbitrary grid.
    """
    from scipy.signal import find_peaks

    boundaries, bar_seconds = _bar_boundaries(duration, bpm, downbeats)
    raw, normalized, levels = _feature_matrix(
        boundaries=boundaries,
        frame_times=frame_times,
        rms=rms,
        mfcc=mfcc,
        chroma=chroma,
        centroid=centroid,
        bandwidth=bandwidth,
        flatness=flatness,
        onset_env=onset_env,
    )
    count = len(levels)
    if count < 2:
        selected = [0, count]
        novelty = np.zeros(count, dtype=np.float64)
    else:
        half = max(2, min(8, int(round(count / 12.0))))
        novelty = _novelty_curve(normalized, half)
        energy_change = np.abs(np.diff(levels, prepend=levels[0]))
        score = novelty + 0.35 * energy_change
        target = max(2, min(18, int(round(count / 8.0)) + 1))
        min_bars = max(2, min(8, int(round(count / 16.0))))
        selected_points: list[int] = []
        # Consider both local novelty peaks and strong energy transitions.
        candidates = set(int(value) for value in find_peaks(score, distance=min_bars, prominence=0.015)[0])
        candidates.update(int(value) for value in np.argsort(score)[::-1][: max(4, target * 2)])
        for candidate in sorted(candidates, key=lambda value: float(score[value]), reverse=True):
            if candidate < min_bars or count - candidate < min_bars:
                continue
            if all(abs(candidate - chosen) >= min_bars for chosen in selected_points):
                selected_points.append(candidate)
            if len(selected_points) >= target - 1:
                break
        if not selected_points and count >= 4:
            selected_points = [count // 2]
        selected = [0, *sorted(selected_points), count]
    sections = _section_labels(
        boundaries=boundaries,
        selected=selected,
        levels=levels,
        novelty=novelty,
        valence=valence,
        style=style,
    )
    # Guarantee complete coverage and useful diagnostic information.
    for section in sections:
        section["section_type"] = section["role"]
    return sections


def warmup() -> None:
    """Compile the librosa/numba paths before the first user upload."""
    import librosa

    rng = np.random.default_rng(7)
    y = (rng.standard_normal(SAMPLE_RATE * 2) * 0.05).astype(np.float32)
    onset = librosa.onset.onset_strength(y=y, sr=SAMPLE_RATE, hop_length=HOP_LENGTH)
    librosa.beat.beat_track(onset_envelope=onset, sr=SAMPLE_RATE, hop_length=HOP_LENGTH)
    stft = np.abs(librosa.stft(y, n_fft=N_FFT, hop_length=HOP_LENGTH))
    librosa.feature.spectral_centroid(S=stft, sr=SAMPLE_RATE)
    librosa.feature.rms(S=stft, frame_length=N_FFT, hop_length=HOP_LENGTH)
    librosa.feature.chroma_cqt(y=y, sr=SAMPLE_RATE, hop_length=HOP_LENGTH)
    librosa.effects.hpss(y)


def analyze_file(path: Path | str, title: str = "") -> dict[str, Any]:
    """Analyse an audio file and return a JSON-serialisable analysis payload."""
    import librosa

    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"Audio file not found: {target}")
    y, sr = librosa.load(str(target), sr=SAMPLE_RATE, mono=True, res_type="kaiser_fast")
    y = np.nan_to_num(np.asarray(y, dtype=np.float32))
    if y.size < sr // 2:
        raise ValueError("Audio is too short to analyse (minimum 0.5 seconds).")
    peak = float(np.max(np.abs(y)))
    if peak > 0:
        y = y / max(1.0, peak)
    duration = float(len(y) / sr)

    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP_LENGTH)
    tempo_value, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_env, sr=sr, hop_length=HOP_LENGTH, trim=False
    )
    bpm = float(np.atleast_1d(tempo_value)[0])
    if not math.isfinite(bpm) or bpm <= 0:
        bpm = 120.0
    bpm = float(min(max(bpm, 40.0), 240.0))
    frame_array = np.asarray(beat_frames, dtype=int)
    frame_array = frame_array[(frame_array >= 0) & (frame_array < len(onset_env))]
    beat_times = np.asarray(
        librosa.frames_to_time(frame_array, sr=sr, hop_length=HOP_LENGTH),
        dtype=np.float64,
    )
    beat_times = beat_times[(beat_times >= 0) & (beat_times < duration)]
    if beat_times.size < 2:
        beat_times = np.arange(0.0, duration, 60.0 / bpm)
    downbeat_phase = 0
    if beat_times.size >= 4:
        local_strengths = np.asarray(onset_env[frame_array[: len(beat_times)]], dtype=np.float64)
        phase_scores = [float(np.mean(local_strengths[offset::4])) if local_strengths[offset::4].size else 0.0 for offset in range(4)]
        downbeat_phase = int(np.argmax(phase_scores)) if phase_scores else 0
    downbeats = [round(float(value), 3) for value in beat_times[downbeat_phase::4][:600]]
    beat_interval = float(np.median(np.diff(beat_times))) if beat_times.size > 1 else 60.0 / bpm
    beat_regularity = 1.0
    if beat_times.size > 3:
        deviations = np.diff(beat_times)
        beat_regularity = float(np.clip(1.0 - np.std(deviations) / max(np.mean(deviations), 1e-6), 0.0, 1.0))

    stft = librosa.stft(y, n_fft=N_FFT, hop_length=HOP_LENGTH)
    magnitude = np.abs(stft)
    power = magnitude**2
    frequencies = librosa.fft_frequencies(sr=sr, n_fft=N_FFT)
    frame_times = librosa.frames_to_time(np.arange(magnitude.shape[1]), sr=sr, hop_length=HOP_LENGTH)
    total_power = float(power.sum()) + 1e-9
    low = float(power[frequencies < 250].sum() / total_power)
    mid = float(power[(frequencies >= 250) & (frequencies < 2500)].sum() / total_power)
    high = float(power[frequencies >= 2500].sum() / total_power)

    rms = librosa.feature.rms(S=magnitude, frame_length=N_FFT, hop_length=HOP_LENGTH)[0]
    rms_db = 20.0 * np.log10(np.maximum(rms, 1e-6))
    loudness = float(np.mean(rms_db))
    energy = float(np.clip((float(np.percentile(rms_db, 90)) + 40.0) / 40.0, 0.0, 1.0))

    centroid_series = librosa.feature.spectral_centroid(S=magnitude, sr=sr)[0]
    rolloff_series = librosa.feature.spectral_rolloff(S=magnitude, sr=sr, roll_percent=0.85)[0]
    bandwidth_series = librosa.feature.spectral_bandwidth(S=magnitude, sr=sr)[0]
    flatness_series = librosa.feature.spectral_flatness(S=magnitude)[0]
    centroid = float(np.mean(centroid_series))
    rolloff = float(np.mean(rolloff_series))
    bandwidth = float(np.mean(bandwidth_series))
    flatness = float(np.mean(flatness_series))
    zcr = float(np.mean(librosa.feature.zero_crossing_rate(y, hop_length=HOP_LENGTH)))
    centroid_norm = float(np.clip(np.log2(max(centroid, 40.0) / 40.0) / math.log2(12000.0 / 40.0), 0.0, 1.0))

    harmonic, percussive = librosa.effects.hpss(y)
    percussive_energy = float(np.sum(percussive.astype(np.float64) ** 2))
    harmonic_energy = float(np.sum(harmonic.astype(np.float64) ** 2))
    percussiveness = float(np.clip(percussive_energy / max(percussive_energy + harmonic_energy, 1e-9), 0.0, 1.0))

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=HOP_LENGTH)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13, hop_length=HOP_LENGTH)
    chroma_mean = np.mean(chroma, axis=1)
    tonic_name, mode, key_confidence, camelot = detect_key(chroma_mean)
    key = f"{tonic_name} {mode}"

    danceability = float(
        np.clip(
            0.36
            + 0.28 * beat_regularity
            + 0.18 * min(1.0, low / 0.40)
            + 0.18 * math.exp(-((bpm - 118.0) ** 2) / (2 * 28.0**2)),
            0.0,
            1.0,
        )
    )
    major_bias = 1.0 if mode == "major" else 0.0
    valence = float(np.clip(0.18 + 0.34 * major_bias + 0.28 * centroid_norm + 0.20 * danceability, 0.0, 1.0))
    style, style_confidence, style_tags = classify_style(
        bpm=bpm,
        energy=energy,
        danceability=danceability,
        low=low,
        mid=mid,
        high=high,
        percussiveness=percussiveness,
        centroid=centroid_norm,
    )
    mood = classify_mood(energy, valence)
    sections = _sections(
        duration=duration,
        bpm=bpm,
        rms=rms,
        frame_times=frame_times,
        valence=valence,
        style=style,
        downbeats=downbeats,
        mfcc=mfcc,
        chroma=chroma,
        centroid=centroid_series,
        bandwidth=bandwidth_series,
        flatness=flatness_series,
        onset_env=onset_env,
    )
    tags = list(dict.fromkeys([*style_tags, mood, f"{round(bpm)} BPM", camelot]))
    if bpm < 90:
        tags.append("Downtempo")
    elif bpm >= 150:
        tags.append("Fast")
    if energy >= 0.75:
        tags.append("High energy")

    analysis = {
        "version": 3,
        "duration": round(duration, 3),
        "bpm": round(bpm, 2),
        "bpm_confidence": round(float(np.clip(1.0 - abs(bpm - round(bpm)) / max(bpm, 1.0), 0.02, 0.99)), 3),
        "beat_interval": round(beat_interval, 5),
        "beat_regularity": round(beat_regularity, 4),
        "key": key,
        "mode": mode,
        "camelot": camelot,
        "key_confidence": round(key_confidence, 4),
        "style": style,
        "style_confidence": round(style_confidence, 4),
        "mood": mood,
        "energy": round(energy, 4),
        "danceability": round(danceability, 4),
        "valence": round(valence, 4),
        "loudness_db": round(loudness, 2),
        "tags": tags,
        "spectral": {
            "centroid": round(centroid, 2),
            "centroid_normalised": round(centroid_norm, 4),
            "rolloff": round(rolloff, 2),
            "bandwidth": round(bandwidth, 2),
            "flatness": round(flatness, 6),
            "zcr": round(zcr, 5),
            "percussiveness": round(percussiveness, 4),
            "low": round(low, 4),
            "mid": round(mid, 4),
            "high": round(high, 4),
        },
        "rhythm": {
            "beat_count": int(beat_times.size),
            "beat_regularity": round(beat_regularity, 4),
            "downbeat_phase": downbeat_phase,
            "downbeats": downbeats,
            "beat_times": [round(float(value), 3) for value in beat_times[:4000]],
        },
        "sections": sections,
        "scene_count": len(sections),
        "section_method": "bar-timbre-harmony-novelty",
        "waveform": _energy_curve(rms, duration),
    }
    analysis["summary"] = (
        f"{style} · {round(bpm)} BPM · {key} ({camelot}) · {mood} · "
        f"energy {round(energy * 100)}%"
    )
    return analysis
