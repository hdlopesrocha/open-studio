"""Style model training for the DJ studio.

Each style model is a compact statistical profile of the analysed tracks in
that style: tempo distribution, key probabilities, energy/valence, spectral
balance, section arc and groove parameters. The synth reads this profile, so
training on a handful of tracks changes the generated music immediately.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from typing import Any

import numpy as np

from .analysis import STYLE_PROFILES, canonical_style, classify_mood
from .planner import STYLE_KEY
from .synth import STYLE_SWING


def _json(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(value or "")
        return parsed if parsed is not None else default
    except (TypeError, ValueError):
        return default


def _analysis(track: dict[str, Any]) -> dict[str, Any]:
    payload = _json(track.get("analysis_json"), {})
    return payload if isinstance(payload, dict) else {}


def _mean(values: list[float], default: float = 0.0) -> float:
    return float(sum(values) / len(values)) if values else default


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return float(math.sqrt(sum((value - mean) ** 2 for value in values) / len(values)))


def builtin_model(style: str) -> dict[str, Any]:
    style = canonical_style(style) or "House"
    profile = STYLE_PROFILES[style]
    key = STYLE_KEY.get(style, "A minor")
    mode = "major" if "major" in key else "minor"
    return {
        "version": 1,
        "style": style,
        "label": f"{style} (built-in)",
        "trained": False,
        "tracks": 0,
        "bpm": float(profile["bpm"]),
        "bpm_std": 0.0,
        "energy": float(profile["energy"]),
        "danceability": float(profile["dance"]),
        "valence": 0.62 if mode == "major" else 0.45,
        "brightness": float(profile["centroid"]),
        "percussiveness": float(profile["perc"]),
        "low": float(profile["low"]),
        "mid": float(profile["mid"]),
        "high": float(profile["high"]),
        "swing": float(STYLE_SWING.get(style, 0.02)),
        "key": key,
        "mode": mode,
        "keys": {key: 1.0},
        "section_curve": [0.28, 0.34, 0.42, 0.55, 0.72, 0.86, 0.94, 1.0, 0.9, 0.7, 0.56, 0.62, 0.78, 0.9, 0.72, 0.4],
    }


def train_model(style: str, tracks: list[dict[str, Any]]) -> dict[str, Any]:
    style = canonical_style(style) or style or "House"
    usable = [track for track in tracks if isinstance(_analysis(track), dict) and _analysis(track)]
    if len(usable) < 1:
        raise ValueError(f"No analysed tracks are assigned to {style}.")
    bpms = [float(track.get("bpm") or _analysis(track).get("bpm") or 0) for track in usable]
    bpms = [bpm for bpm in bpms if bpm > 0]
    energies = [float(track.get("energy") or _analysis(track).get("energy") or 0.5) for track in usable]
    valence = [float(track.get("valence") or _analysis(track).get("valence") or 0.5) for track in usable]
    dance = [float(track.get("danceability") or _analysis(track).get("danceability") or 0.5) for track in usable]
    low = [float((_analysis(track).get("spectral") or {}).get("low") or 0.33) for track in usable]
    mid = [float((_analysis(track).get("spectral") or {}).get("mid") or 0.42) for track in usable]
    high = [float((_analysis(track).get("spectral") or {}).get("high") or 0.22) for track in usable]
    brightness = [float((_analysis(track).get("spectral") or {}).get("centroid_normalised") or 0.4) for track in usable]
    perc = [float((_analysis(track).get("spectral") or {}).get("percussiveness") or 0.5) for track in usable]
    keys = Counter(str(track.get("key") or _analysis(track).get("key") or "A minor") for track in usable)
    key_total = max(1, sum(keys.values()))
    key_probabilities = {key: round(count / key_total, 4) for key, count in keys.most_common(12)}
    primary_key = keys.most_common(1)[0][0]
    mode = "major" if "major" in primary_key else "minor"

    curve_samples: list[list[float]] = []
    for track in usable:
        analysis = _analysis(track)
        waveform = analysis.get("waveform") or []
        if len(waveform) >= 16:
            values = np.asarray(waveform, dtype=np.float64)
            positions = np.linspace(0, len(values) - 1, 16)
            curve_samples.append([float(value) for value in np.interp(positions, np.arange(len(values)), values)])
    if curve_samples:
        section_curve = np.mean(np.asarray(curve_samples), axis=0)
        section_curve = section_curve / max(float(section_curve.max()), 1e-9)
        section_curve = [round(float(value), 4) for value in section_curve]
    else:
        section_curve = builtin_model(style)["section_curve"]

    preset = STYLE_PROFILES.get(style, STYLE_PROFILES["House"])
    model = {
        "version": 1,
        "style": style,
        "label": f"{style} · learned",
        "trained": True,
        "tracks": len(usable),
        "bpm": round(_mean(bpms, preset["bpm"]), 2),
        "bpm_std": round(_std(bpms), 2),
        "energy": round(_mean(energies, preset["energy"]), 4),
        "danceability": round(_mean(dance, preset["dance"]), 4),
        "valence": round(_mean(valence, 0.55), 4),
        "brightness": round(_mean(brightness, preset["centroid"]), 4),
        "percussiveness": round(_mean(perc, preset["perc"]), 4),
        "low": round(_mean(low, preset["low"]), 4),
        "mid": round(_mean(mid, preset["mid"]), 4),
        "high": round(_mean(high, preset["high"]), 4),
        "swing": STYLE_SWING.get(style, 0.02),
        "key": primary_key,
        "mode": mode,
        "keys": key_probabilities,
        "section_curve": section_curve,
        "mood": classify_mood(_mean(energies, preset["energy"]), _mean(valence, 0.55)),
    }
    return model


def load_model(model_row: dict[str, Any] | None, style: str) -> dict[str, Any]:
    if model_row:
        payload = _json(model_row.get("model_json"), {})
        if isinstance(payload, dict) and payload:
            return {**builtin_model(style), **payload, "model_id": model_row.get("id"), "trained": True}
    return builtin_model(style)


def generation_defaults(
    *,
    style: str,
    model: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    style = canonical_style(style) or "House"
    bpm = params.get("bpm")
    energy = params.get("energy")
    key = params.get("key")
    brightness = params.get("brightness")
    return {
        "style": style,
        "bpm": float(bpm if bpm not in (None, "") else model.get("bpm") or STYLE_PROFILES[style]["bpm"]),
        "energy": float(energy if energy not in (None, "") else model.get("energy") or STYLE_PROFILES[style]["energy"]),
        "key": str(key or model.get("key") or STYLE_KEY.get(style, "A minor")),
        "brightness": float(brightness if brightness not in (None, "") else model.get("brightness") or STYLE_PROFILES[style]["centroid"]),
        "swing": float(model.get("swing") or STYLE_SWING.get(style, 0.02)),
        "model": model,
    }
