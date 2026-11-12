"""Mix rendering, beat matching and the effect rack for the DJ studio."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable

import numpy as np
from scipy.signal import butter, fftconvolve, sosfilt

SR = 44100
Progress = Callable[[float, str, str], None]

EFFECT_PRESETS = [
    {
        "id": "filter_sweep",
        "label": "Filter sweep",
        "description": "Low/high-pass automation for tension, drops and mood flips.",
        "defaults": {"mode": "lowpass", "from_hz": 18000, "to_hz": 350, "amount": 0.8},
    },
    {
        "id": "reverb",
        "label": "Reverb",
        "description": "Synthetic room tail that opens or softens a section.",
        "defaults": {"amount": 0.24},
    },
    {
        "id": "delay",
        "label": "Tempo delay",
        "description": "Beat-synced echoes, useful for breakdowns and echo-outs.",
        "defaults": {"beats": 0.75, "feedback": 0.38, "amount": 0.28},
    },
    {
        "id": "drive",
        "label": "Drive",
        "description": "Saturation that makes a drop feel louder and more aggressive.",
        "defaults": {"amount": 0.3},
    },
    {
        "id": "bitcrush",
        "label": "Bitcrush",
        "description": "Reduce bit depth and sample rate for a harder, glitchier emotion.",
        "defaults": {"amount": 0.35},
    },
    {
        "id": "chorus",
        "label": "Chorus",
        "description": "Wide modulated doubles for dreamy, floating sections.",
        "defaults": {"amount": 0.3},
    },
    {
        "id": "gate",
        "label": "Rhythm gate",
        "description": "Beat-synced gate for stutter builds and chopped transitions.",
        "defaults": {"beats": 0.25, "amount": 0.6},
    },
    {
        "id": "stutter",
        "label": "Stutter",
        "description": "Repeat a short slice to create a build or transition.",
        "defaults": {"beats": 0.25, "repeat": 4, "amount": 0.7},
    },
    {
        "id": "tape_stop",
        "label": "Tape stop",
        "description": "Pitch-down stop that turns a section inside out.",
        "defaults": {"duration": 1.2, "amount": 0.8},
    },
    {
        "id": "lowpass",
        "label": "Low-pass",
        "description": "Static darkening; lower cutoff for a deeper, filtered mood.",
        "defaults": {"cutoff": 3200, "amount": 0.7},
    },
    {
        "id": "highpass",
        "label": "High-pass",
        "description": "Remove weight for a build, intro or thin breakdown.",
        "defaults": {"cutoff": 500, "amount": 0.7},
    },
    {
        "id": "gain",
        "label": "Gain / ride",
        "description": "Level automation for hand-off and drop control.",
        "defaults": {"db": 0.0},
    },
]

EMOTION_PRESETS = [
    {"id": "euphoric", "label": "Euphoric", "effects": [{"type": "highpass", "cutoff": 380, "amount": 0.6}, {"type": "reverb", "amount": 0.2}], "note": "Open the top end, add air and a short room."},
    {"id": "dark", "label": "Dark / warehouse", "effects": [{"type": "lowpass", "cutoff": 2400, "amount": 0.9}, {"type": "drive", "amount": 0.25}], "note": "Filter down and add saturation."},
    {"id": "dreamy", "label": "Dreamy", "effects": [{"type": "chorus", "amount": 0.42}, {"type": "reverb", "amount": 0.34}], "note": "Wide chorus and a long tail."},
    {"id": "aggressive", "label": "Aggressive", "effects": [{"type": "drive", "amount": 0.48}, {"type": "bitcrush", "amount": 0.22}], "note": "Hard saturation and a little bit reduction."},
    {"id": "intimate", "label": "Intimate", "effects": [{"type": "lowpass", "cutoff": 5200, "amount": 0.5}, {"type": "reverb", "amount": 0.28}, {"type": "gain", "db": -2.0}], "note": "Pull the sound closer and quieter."},
    {"id": "rising", "label": "Rising tension", "effects": [{"type": "filter_sweep", "mode": "highpass", "from_hz": 5000, "to_hz": 100, "amount": 0.8}, {"type": "gate", "beats": 0.25, "amount": 0.35}], "note": "High-pass into a rhythmic gate."},
]


def _as_stereo(audio: np.ndarray) -> np.ndarray:
    audio = np.nan_to_num(np.asarray(audio, dtype=np.float32))
    if audio.ndim == 1:
        return np.stack([audio, audio], axis=1)
    if audio.shape[1] == 1:
        return np.repeat(audio, 2, axis=1)
    return audio[:, :2]


def load_track(path: Path | str, sample_rate: int = SR) -> np.ndarray:
    import librosa

    audio, _ = librosa.load(str(path), sr=sample_rate, mono=False, res_type="kaiser_fast")
    audio = np.asarray(audio)
    # librosa returns (channels, samples) for mono=False; the renderer works
    # with a (samples, channels) array.
    if audio.ndim == 2 and audio.shape[0] <= 2 and audio.shape[1] > audio.shape[0]:
        audio = audio.T
    return _as_stereo(audio)


def _clamp_segment(audio: np.ndarray, start: float, end: float, sr: int) -> tuple[int, int]:
    first = max(0, min(len(audio), int(round(float(start) * sr))))
    last = max(first, min(len(audio), int(round(float(end) * sr))))
    return first, last


def _stereo_filter(audio: np.ndarray, cutoff: float, mode: str, sr: int) -> np.ndarray:
    cutoff = float(min(max(cutoff, 20.0), sr / 2.1))
    kind = "low" if mode in {"low", "lowpass", "lp"} else "high"
    sos = butter(2, cutoff, btype=kind, fs=sr, output="sos")
    return sosfilt(sos, audio, axis=0).astype(np.float32)


def _automated_filter(
    segment: np.ndarray,
    *,
    from_hz: float,
    to_hz: float,
    mode: str,
    sr: int,
    block_size: int = 4096,
) -> np.ndarray:
    if segment.size == 0:
        return segment
    from_hz = float(min(max(from_hz, 25.0), sr / 2.2))
    to_hz = float(min(max(to_hz, 25.0), sr / 2.2))
    if abs(math.log2(max(from_hz, 1.0) / max(to_hz, 1.0))) < 0.02:
        return _stereo_filter(segment, from_hz, mode, sr)
    kind = "low" if mode in {"low", "lowpass", "lp"} else "high"
    out = np.empty_like(segment, dtype=np.float32)
    state: np.ndarray | None = None
    length = len(segment)
    for start in range(0, length, block_size):
        end = min(length, start + block_size)
        fraction = start / max(1, length - 1)
        cutoff = float(2 ** (math.log2(from_hz) * (1.0 - fraction) + math.log2(to_hz) * fraction))
        sos = butter(2, cutoff, btype=kind, fs=sr, output="sos")
        if state is None:
            state = np.zeros((sos.shape[0], 2, 2), dtype=np.float32)
        filtered, state = sosfilt(sos, segment[start:end], axis=0, zi=state)
        out[start:end] = filtered
    return out


def _reverb(audio: np.ndarray, amount: float, seed: int = 7) -> np.ndarray:
    amount = float(min(max(amount, 0.0), 1.0))
    if amount <= 0:
        return audio
    rng = np.random.default_rng(seed)
    length = int(1.35 * SR)
    time = np.arange(length, dtype=np.float32) / SR
    left = rng.standard_normal(length).astype(np.float32) * np.exp(-time * 3.1)
    right = rng.standard_normal(length).astype(np.float32) * np.exp(-time * 3.4)
    left /= max(float(np.sqrt(np.sum(left**2))), 1e-9)
    right /= max(float(np.sqrt(np.sum(right**2))), 1e-9)
    wet_left = fftconvolve(audio[:, 0], left, mode="full")[: len(audio)]
    wet_right = fftconvolve(audio[:, 1], right, mode="full")[: len(audio)]
    wet = np.stack([wet_left, wet_right], axis=1).astype(np.float32)
    return (audio * (1.0 - amount * 0.5) + wet * amount * 0.5).astype(np.float32)


def _delay(audio: np.ndarray, *, beats: float, feedback: float, amount: float, beat_seconds: float) -> np.ndarray:
    amount = float(min(max(amount, 0.0), 1.0))
    if amount <= 0:
        return audio
    delay_samples = max(1, int(beat_seconds * float(beats) * SR))
    out = audio.copy()
    feedback = float(min(max(feedback, 0.0), 0.85))
    for repeat in range(1, 7):
        shift = delay_samples * repeat
        if shift >= len(audio):
            break
        gain = amount * (feedback ** (repeat - 1)) * 0.7
        out[shift:] += audio[:-shift] * gain
    return out.astype(np.float32)


def _drive(audio: np.ndarray, amount: float) -> np.ndarray:
    amount = float(min(max(amount, 0.0), 1.0))
    gain = 1.0 + amount * 8.0
    return (np.tanh(audio * gain) / math.tanh(gain)).astype(np.float32)


def _bitcrush(audio: np.ndarray, amount: float) -> np.ndarray:
    amount = float(min(max(amount, 0.0), 1.0))
    bits = max(2, int(16 - amount * 13))
    steps = 2**bits
    hold = max(1, int(1 + amount * 12))
    crushed = np.round(audio * steps) / steps
    if hold > 1:
        indices = (np.arange(len(crushed)) // hold) * hold
        crushed = crushed[np.clip(indices, 0, len(crushed) - 1)]
    return crushed.astype(np.float32)


def _chorus(audio: np.ndarray, amount: float) -> np.ndarray:
    amount = float(min(max(amount, 0.0), 1.0))
    if amount <= 0:
        return audio
    length = len(audio)
    time = np.arange(length, dtype=np.float32) / SR
    out = audio.copy()
    for offset_ms, rate in ((14.0, 0.31), (23.0, 0.17)):
        delay = (offset_ms + np.sin(2 * math.pi * rate * time) * 3.0) * SR / 1000.0
        positions = np.arange(length, dtype=np.float32) - delay
        positions = np.clip(positions, 0, length - 1)
        for channel in range(2):
            out[:, channel] += np.interp(positions, np.arange(length), audio[:, channel]).astype(np.float32) * amount * 0.28
    return out.astype(np.float32)


def _gate(audio: np.ndarray, *, beats: float, amount: float, beat_seconds: float) -> np.ndarray:
    amount = float(min(max(amount, 0.0), 1.0))
    step = max(1, int(beat_seconds * float(beats) * SR))
    pattern = np.ones(len(audio), dtype=np.float32)
    for start in range(0, len(audio), step * 2):
        pattern[start : start + step] = 1.0 - amount * 0.25
        pattern[start + step : start + step * 2] = 1.0 - amount * 0.9
    return (audio * pattern[:, None]).astype(np.float32)


def _stutter(audio: np.ndarray, *, beats: float, repeat: int, amount: float, beat_seconds: float) -> np.ndarray:
    if len(audio) == 0:
        return audio
    slice_len = max(1, int(beat_seconds * float(beats) * SR))
    out = audio.copy()
    start = min(len(audio) - 1, int(len(audio) * 0.55))
    chunk = audio[start : min(len(audio), start + slice_len)].copy()
    if len(chunk) == 0:
        return audio
    cursor = start
    for _ in range(max(1, int(repeat))):
        end = min(len(out), cursor + len(chunk))
        out[cursor:end] = out[cursor:end] * (1.0 - amount) + chunk[: end - cursor] * amount
        cursor = end
        if cursor >= len(out):
            break
    return out


def _tape_stop(audio: np.ndarray, *, duration: float, amount: float) -> np.ndarray:
    window = max(2, int(duration * SR))
    start = max(0, len(audio) - window)
    piece = audio[start:].copy()
    if len(piece) < 8:
        return audio
    ratio = np.linspace(1.0, 0.02, len(piece), dtype=np.float32)
    positions = np.cumsum(ratio)
    positions = np.clip(positions, 0, len(piece) - 1)
    stopped = np.stack(
        [np.interp(positions, np.arange(len(piece)), piece[:, channel]) for channel in range(2)],
        axis=1,
    ).astype(np.float32)
    audio = audio.copy()
    audio[start:] = audio[start:] * (1.0 - amount) + stopped * amount
    return audio


def _gain(audio: np.ndarray, db: float) -> np.ndarray:
    return (audio * (10.0 ** (float(db) / 20.0))).astype(np.float32)


def apply_effects(
    audio: np.ndarray,
    effects: list[dict[str, Any]],
    *,
    beat_seconds: float,
    sr: int = SR,
    seed: int = 7,
) -> np.ndarray:
    if not effects:
        return audio
    result = audio.astype(np.float32).copy()
    for index, effect in enumerate(effects):
        if not isinstance(effect, dict):
            continue
        kind = str(effect.get("type") or effect.get("id") or "").lower()
        start, end = _clamp_segment(
            result,
            effect.get("start") or 0.0,
            effect.get("end") or len(result) / sr,
            sr,
        )
        if end - start < 32:
            continue
        segment = result[start:end].copy()
        amount = float(effect.get("amount") if effect.get("amount") is not None else 0.5)
        if kind == "filter_sweep" or kind in {"lowpass", "highpass"}:
            mode = str(effect.get("mode") or ("lowpass" if kind == "lowpass" else "highpass" if kind == "highpass" else "lowpass"))
            if kind == "filter_sweep":
                from_hz = float(effect.get("from_hz") or 18000.0)
                to_hz = float(effect.get("to_hz") or 350.0)
            elif kind == "lowpass":
                from_hz = to_hz = float(effect.get("cutoff") or 3200.0)
            else:
                from_hz = to_hz = float(effect.get("cutoff") or 500.0)
            processed = _automated_filter(segment, from_hz=from_hz, to_hz=to_hz, mode=mode, sr=sr)
            segment = segment * (1.0 - amount) + processed * amount
        elif kind == "reverb":
            segment = _reverb(segment, amount, seed=seed + index)
        elif kind == "delay":
            segment = _delay(
                segment,
                beats=float(effect.get("beats") or 0.75),
                feedback=float(effect.get("feedback") or 0.38),
                amount=amount,
                beat_seconds=beat_seconds,
            )
        elif kind == "drive":
            segment = _drive(segment, amount)
        elif kind == "bitcrush":
            segment = _bitcrush(segment, amount)
        elif kind == "chorus":
            segment = _chorus(segment, amount)
        elif kind == "gate":
            segment = _gate(segment, beats=float(effect.get("beats") or 0.25), amount=amount, beat_seconds=beat_seconds)
        elif kind == "stutter":
            segment = _stutter(
                segment,
                beats=float(effect.get("beats") or 0.25),
                repeat=int(effect.get("repeat") or 4),
                amount=amount,
                beat_seconds=beat_seconds,
            )
        elif kind == "tape_stop":
            segment = _tape_stop(segment, duration=float(effect.get("duration") or 1.2), amount=amount)
        elif kind == "gain":
            segment = _gain(segment, float(effect.get("db") or 0.0))
        result[start:end] = segment
    return result


def _stretch(audio: np.ndarray, rate: float) -> np.ndarray:
    if abs(rate - 1.0) < 0.006 or len(audio) < SR * 2:
        return audio
    import librosa

    rate = float(min(max(rate, 0.72), 1.38))
    channels = [
        librosa.effects.time_stretch(audio[:, channel].astype(np.float32), rate=rate)
        for channel in range(audio.shape[1])
    ]
    length = min(len(channel) for channel in channels)
    return np.stack([channel[:length] for channel in channels], axis=1).astype(np.float32)


def _pitch(audio: np.ndarray, semitones: float) -> np.ndarray:
    if abs(semitones) < 0.01 or len(audio) < SR * 2:
        return audio
    import librosa

    channels = [
        librosa.effects.pitch_shift(audio[:, channel].astype(np.float32), sr=SR, n_steps=float(semitones))
        for channel in range(audio.shape[1])
    ]
    length = min(len(channel) for channel in channels)
    return np.stack([channel[:length] for channel in channels], axis=1).astype(np.float32)


def _equal_power(length: int, incoming: bool) -> np.ndarray:
    t = np.linspace(0.0, math.pi / 2.0, max(1, length), dtype=np.float32)
    return np.sin(t) if incoming else np.cos(t)


def _transition_curve(entry: dict[str, Any], length: int) -> tuple[np.ndarray, np.ndarray]:
    curve = str(entry.get("curve") or "equal_power")
    if curve == "cut" or length <= 0:
        return np.ones(length, dtype=np.float32), np.ones(length, dtype=np.float32)
    return _equal_power(length, False), _equal_power(length, True)


def render_mix(
    scene: dict[str, Any],
    output_path: Path | str,
    *,
    progress: Progress | None = None,
    sr: int = SR,
) -> dict[str, Any]:
    import soundfile as sf

    entries = [entry for entry in (scene.get("tracks") or []) if entry.get("path")]
    if not entries:
        raise ValueError("The mix scene has no tracks.")
    master_bpm = float(scene.get("master_bpm") or scene.get("bpm") or 120.0)
    beat = 60.0 / max(master_bpm, 1.0)
    buffers: list[np.ndarray] = []
    for index, entry in enumerate(entries):
        if progress:
            progress(8.0 + index / max(1, len(entries)) * 52.0, "Loading", f"Loading {entry.get('title', 'track')}")
        path = Path(str(entry["path"]))
        audio = load_track(path, sample_rate=sr)
        first, last = _clamp_segment(audio, entry.get("in", 0.0), entry.get("out", len(audio) / sr), sr)
        audio = audio[first:last].copy()
        if audio.size == 0:
            raise ValueError(f"Track {entry.get('title', path.name)} has an empty in/out range.")
        track_bpm = float(entry.get("bpm") or master_bpm)
        audio = _stretch(audio, master_bpm / max(track_bpm, 1.0))
        if entry.get("pitch_shift"):
            audio = _pitch(audio, float(entry["pitch_shift"]))
        gain_db = float(entry.get("gain_db") or 0.0)
        if abs(gain_db) > 0.01:
            audio = _gain(audio, gain_db)
        audio = apply_effects(audio, list(entry.get("effects") or []), beat_seconds=beat, sr=sr, seed=int(scene.get("seed") or 7) + index)
        if progress:
            progress(8.0 + (index + 0.8) / max(1, len(entries)) * 52.0, "Processing", f"Effects on {entry.get('title', 'track')}")
        buffers.append(audio.astype(np.float32))

    starts: list[float] = [0.0]
    overlaps: list[int] = []
    for index in range(1, len(buffers)):
        previous = entries[index - 1]
        transition = previous.get("transition") or {}
        transition_beats = float(transition.get("beats") or 16)
        max_overlap = int(min(len(buffers[index - 1]) * 0.72, len(buffers[index]) * 0.72))
        overlap = min(max_overlap, int(transition_beats * beat * sr))
        if str(transition.get("type") or "") == "cut":
            overlap = 0
        overlaps.append(overlap)
        starts.append(starts[-1] + len(buffers[index - 1]) / sr - overlap / sr)

    for index in range(len(buffers) - 1):
        overlap = overlaps[index]
        if overlap <= 0:
            # A hard cut still needs a few milliseconds of de-click.
            de_click = min(256, len(buffers[index]), len(buffers[index + 1]))
            if de_click > 0:
                buffers[index][-de_click:] *= np.linspace(1.0, 0.0, de_click, dtype=np.float32)[:, None]
                buffers[index + 1][:de_click] *= np.linspace(0.0, 1.0, de_click, dtype=np.float32)[:, None]
            continue
        transition = entries[index].get("transition") or {}
        transition_type = str(transition.get("type") or "crossfade")
        outgoing = buffers[index]
        incoming = buffers[index + 1]
        out_curve, in_curve = _transition_curve(transition, overlap)
        if transition_type == "filter_sweep":
            tail = outgoing[-overlap:].copy()
            outgoing[-overlap:] = _automated_filter(
                tail, from_hz=18000.0, to_hz=300.0, mode="lowpass", sr=sr
            )
            head = incoming[:overlap].copy()
            incoming[:overlap] = _automated_filter(head, from_hz=1500.0, to_hz=18000.0, mode="highpass", sr=sr)
        elif transition_type == "bass_swap":
            head = incoming[:overlap].copy()
            incoming[:overlap] = _automated_filter(head, from_hz=220.0, to_hz=18000.0, mode="lowpass", sr=sr)
        elif transition_type == "echo_out":
            outgoing[-overlap:] = _delay(
                outgoing[-overlap:],
                beats=0.75,
                feedback=0.45,
                amount=0.35,
                beat_seconds=beat,
            )
        outgoing[-overlap:] *= out_curve[:, None]
        incoming[:overlap] *= in_curve[:, None]

    # First fade-in and final fade-out.
    first_fade = min(len(buffers[0]), int(beat * 2 * sr))
    if first_fade > 0:
        buffers[0][:first_fade] *= np.linspace(0.0, 1.0, first_fade, dtype=np.float32)[:, None]
    last_fade = min(len(buffers[-1]), int(beat * 4 * sr))
    if last_fade > 0:
        buffers[-1][-last_fade:] *= np.linspace(1.0, 0.0, last_fade, dtype=np.float32)[:, None]

    total = max(int(start * sr) + len(buffer) for start, buffer in zip(starts, buffers)) + int(1.5 * sr)
    output = np.zeros((total, 2), dtype=np.float32)
    for start, buffer in zip(starts, buffers):
        offset = int(start * sr)
        end = min(total, offset + len(buffer))
        output[offset:end] += buffer[: end - offset]
    if progress:
        progress(76.0, "Mastering", "Soft limiter and fade-out")
    peak = float(np.max(np.abs(output)))
    if peak > 0:
        output = output / peak * 0.94
    output = np.tanh(output * 1.08).astype(np.float32)
    output = _stereo_filter(output, 24.0, "high", sr)
    output = np.nan_to_num(output).astype(np.float32)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_path), output, sr, subtype="PCM_16")
    if progress:
        progress(96.0, "Writing", "Final mix written")
    return {
        "path": str(output_path),
        "duration": round(len(output) / sr, 3),
        "sample_rate": sr,
        "master_bpm": master_bpm,
        "tracks": len(buffers),
        "timeline": [
            {"title": entry.get("title"), "start": round(start, 3), "duration": round(len(buffer) / sr, 3)}
            for entry, start, buffer in zip(entries, starts, buffers)
        ],
    }
