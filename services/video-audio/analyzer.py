"""Musical analysis built on Librosa.

Produces tempo/beat information, strong beats, approximate downbeats, RMS and
band energy envelopes, spectral features and energy-based structural sections.
Tempo alone is never treated as a complete description of song structure.
"""

from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np
from mvstudio_shared.models import (
    AudioAnalysis,
    BandEnergies,
    BeatEvent,
    MusicalSection,
    OnsetEvent,
    TimeSeries,
)
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks

HOP_LENGTH = 512
N_FFT = 2048
UI_RATE = 8.0  # points per second for waveforms and band envelopes


def _safe_norm(values: np.ndarray, reference: float | None = None) -> np.ndarray:
    values = np.nan_to_num(np.asarray(values, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
    reference = reference if reference is not None else float(np.percentile(values, 95))
    if not math.isfinite(reference) or reference <= 1e-9:
        reference = max(float(values.max()), 1e-9)
    return np.clip(values / reference, 0.0, 1.5)


def _downsample(times: np.ndarray, values: np.ndarray, duration: float, rate: float = UI_RATE) -> TimeSeries:
    if len(times) == 0 or len(values) == 0:
        return TimeSeries()
    grid = np.arange(0.0, duration + 1.0 / rate, 1.0 / rate)
    grid = grid[grid <= duration]
    sampled = np.interp(grid, times, values, left=float(values[0]), right=float(values[-1]))
    return TimeSeries(
        times=[round(float(value), 3) for value in grid],
        values=[round(float(value), 4) for value in sampled],
    )


def _format_db(amplitude: float) -> float:
    return round(float(20.0 * math.log10(max(amplitude, 1e-6))), 2)


class AudioAnalyzer:
    def analyze(
        self,
        audio_path: str | Path,
        *,
        sample_rate: int = 22050,
        min_section_seconds: float = 6.0,
        max_sections: int = 24,
    ) -> AudioAnalysis:
        started = time.perf_counter()
        warnings: list[str] = []
        target = Path(audio_path)
        if not target.is_file():
            raise FileNotFoundError(f"Audio file not found: {target}")

        import librosa

        y, sr = librosa.load(str(target), sr=sample_rate, mono=True, res_type="kaiser_fast")
        if y.size < sr:
            raise ValueError("Audio file is too short to analyse")
        y = np.asarray(y, dtype=np.float32)
        peak_amplitude = float(np.max(np.abs(y)))
        if peak_amplitude > 0:
            y = y / max(1.0, peak_amplitude)
        duration = round(len(y) / sr, 3)

        # --- Rhythm ---------------------------------------------------------
        onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP_LENGTH)
        if onset_env.size < 2:
            raise ValueError("Audio has no detectable onsets")
        tempo_value, beat_frames = librosa.beat.beat_track(
            onset_envelope=onset_env,
            sr=sr,
            hop_length=HOP_LENGTH,
            trim=False,
        )
        tempo = float(np.atleast_1d(tempo_value)[0])
        if not math.isfinite(tempo) or tempo <= 0:
            tempo = 120.0
            warnings.append("Tempo detection failed; using a neutral 120 BPM grid.")
        elif tempo < 40 or tempo > 240:
            warnings.append(f"Tempo estimate {tempo:.1f} BPM is unusual; beat grid may be approximate.")
            tempo = min(max(tempo, 40.0), 240.0)
        beat_frames = np.asarray(beat_frames, dtype=int)
        beat_frames = beat_frames[(beat_frames >= 0) & (beat_frames < len(onset_env))]
        beat_times = np.asarray(
            librosa.frames_to_time(beat_frames, sr=sr, hop_length=HOP_LENGTH), dtype=float
        )
        beat_times = beat_times[(beat_times >= 0.0) & (beat_times < duration)]
        if len(beat_times) < 2:
            warnings.append("Very few beats detected; procedural cuts may fall back to energy changes.")
            step = max(0.35, 60.0 / tempo)
            beat_times = np.arange(0.0, duration, step)
            beat_frames = np.asarray(
                librosa.time_to_frames(beat_times, sr=sr, hop_length=HOP_LENGTH), dtype=int
            )
            beat_frames = np.clip(beat_frames, 0, len(onset_env) - 1)
        strengths = _safe_norm(np.asarray(onset_env, dtype=float)[beat_frames])
        strong_cut = float(np.percentile(strengths, 70)) if strengths.size else 0.5

        # Approximate downbeats: choose the 4-beat phase with the strongest mean onset.
        phases = [float(np.mean(strengths[offset::4])) if len(strengths[offset::4]) else 0.0 for offset in range(4)]
        downbeat_phase = int(np.argmax(phases)) if phases else 0
        beats: list[BeatEvent] = []
        downbeats: list[float] = []
        for position, (beat_time, strength) in enumerate(zip(beat_times, strengths)):
            is_downbeat = position % 4 == downbeat_phase
            event = BeatEvent(
                time=round(float(beat_time), 3),
                strength=round(float(strength), 3),
                downbeat=is_downbeat,
                strong=bool(strength >= strong_cut),
            )
            beats.append(event)
            if is_downbeat:
                downbeats.append(round(float(beat_time), 3))
        beat_interval = float(np.median(np.diff(beat_times))) if len(beat_times) > 1 else 60.0 / tempo

        # --- Spectral energy -------------------------------------------------
        stft = librosa.stft(y, n_fft=N_FFT, hop_length=HOP_LENGTH)
        magnitude = np.abs(stft)
        power = magnitude**2
        frame_times = librosa.frames_to_time(
            np.arange(magnitude.shape[1]), sr=sr, hop_length=HOP_LENGTH
        )
        frequencies = librosa.fft_frequencies(sr=sr, n_fft=N_FFT)

        def band(mask: np.ndarray) -> np.ndarray:
            if not np.any(mask):
                return np.zeros(magnitude.shape[1])
            return np.sqrt(np.mean(power[mask, :], axis=0))

        bass = band((frequencies >= 20) & (frequencies < 250))
        mid = band((frequencies >= 250) & (frequencies < 2000))
        high = band((frequencies >= 2000) & (frequencies < 8000))
        rms_frames = librosa.feature.rms(S=magnitude, frame_length=N_FFT, hop_length=HOP_LENGTH)[0]
        centroid_frames = librosa.feature.spectral_centroid(S=magnitude, sr=sr)[0]
        flatness_frames = librosa.feature.spectral_flatness(S=magnitude)[0]

        rms_normalised = _safe_norm(rms_frames)
        bass_normalised = _safe_norm(bass)
        mid_normalised = _safe_norm(mid)
        high_normalised = _safe_norm(high)

        bass_series = _downsample(frame_times, bass_normalised, duration)
        mid_series = _downsample(frame_times, mid_normalised, duration)
        high_series = _downsample(frame_times, high_normalised, duration)
        rms_series = _downsample(frame_times, rms_normalised, duration)
        centroid_series = _downsample(frame_times, _safe_norm(centroid_frames), duration)

        # Peak envelope at UI rate.
        samples_per_bin = max(1, int(round(sr / UI_RATE)))
        usable = (len(y) // samples_per_bin) * samples_per_bin
        peak_bins = (
            np.max(np.abs(y[:usable]).reshape(-1, samples_per_bin), axis=1)
            if usable
            else np.asarray([float(np.max(np.abs(y)))])
        )
        peak_times = np.arange(len(peak_bins)) / UI_RATE
        peak_series = TimeSeries(
            times=[round(float(value), 3) for value in peak_times],
            values=[
                round(float(value) / max(1e-9, float(np.percentile(peak_bins, 99))), 4)
                for value in peak_bins
            ],
        )

        # --- Structure -------------------------------------------------------
        # Very short songs cannot sustain a six-second minimum section length.
        # Scale the minimum down to keep structural changes visible while never
        # accepting micro-sections.
        requested_min = max(2.0, float(min_section_seconds))
        min_seconds = min(requested_min, max(2.0, duration / 7.0))
        second_count = max(2, int(math.ceil(duration)))
        frames_per_second = sr / HOP_LENGTH

        def per_second(values: np.ndarray, reducer="mean") -> np.ndarray:
            output = np.zeros(second_count, dtype=np.float64)
            for index in range(second_count):
                lo = int(index * frames_per_second)
                hi = min(len(values), int((index + 1) * frames_per_second))
                if hi <= lo:
                    output[index] = values[min(lo, len(values) - 1)]
                elif reducer == "max":
                    output[index] = float(np.max(values[lo:hi]))
                else:
                    output[index] = float(np.mean(values[lo:hi]))
            return output

        onset_per_second = per_second(onset_env, "mean")
        rms_per_second = per_second(rms_normalised)
        centroid_per_second = per_second(_safe_norm(centroid_frames))
        flatness_per_second = per_second(_safe_norm(flatness_frames))
        high_ratio_per_second = per_second(
            high_normalised / np.maximum(bass_normalised + mid_normalised + high_normalised, 1e-6)
        )

        feature_matrix = np.stack(
            [
                rms_per_second,
                centroid_per_second,
                flatness_per_second,
                high_ratio_per_second,
                onset_per_second,
            ],
            axis=1,
        )
        for column in range(feature_matrix.shape[1]):
            values = feature_matrix[:, column]
            spread = float(np.median(np.abs(values - np.median(values)))) + 1e-6
            feature_matrix[:, column] = (values - float(np.median(values))) / spread
        feature_matrix = np.apply_along_axis(gaussian_filter1d, 0, feature_matrix, sigma=1.4)

        novelty = np.zeros(second_count)
        window = max(2, int(round(min_seconds / 2)))
        for index in range(window, second_count - window):
            before = np.mean(feature_matrix[max(0, index - window) : index], axis=0)
            after = np.mean(feature_matrix[index : min(second_count, index + window)], axis=0)
            novelty[index] = float(np.linalg.norm(after - before))
        novelty = gaussian_filter1d(novelty, sigma=1.5)
        if novelty.max() > 1e-9:
            novelty = novelty / novelty.max()

        peak_indices, properties = find_peaks(
            novelty,
            distance=max(1, int(round(min_seconds))),
            height=0.18,
            prominence=0.06,
        )
        candidate_scores = list(zip(peak_indices.tolist(), properties.get("prominences", np.zeros_like(peak_indices)).tolist()))
        if len(candidate_scores) > max_sections - 1:
            candidate_scores.sort(key=lambda item: item[1], reverse=True)
            candidate_scores = candidate_scores[: max_sections - 1]
        boundaries = sorted({0.0, float(duration)} | {float(index) for index, _score in candidate_scores if 0 < index < duration})

        # Merge sections that are too short.
        merged = [boundaries[0]]
        for boundary in boundaries[1:]:
            if boundary - merged[-1] < min_seconds and boundary != duration:
                continue
            if duration - boundary < min_seconds and len(merged) > 1:
                continue
            merged.append(boundary)
        if merged[-1] != duration:
            if duration - merged[-1] < min_seconds and len(merged) > 1:
                merged[-1] = duration
            else:
                merged.append(duration)
        boundaries = merged

        section_energies: list[float] = []
        for start, end in zip(boundaries[:-1], boundaries[1:]):
            selector = (frame_times >= start) & (frame_times < end)
            if np.any(selector):
                energy = float(np.mean(rms_normalised[selector]))
            else:
                energy = 0.0
            section_energies.append(energy)
        positive_energies = [energy for energy in section_energies if energy > 1e-6]
        median_energy = float(np.median(positive_energies)) if positive_energies else 0.5
        sections: list[MusicalSection] = []
        for index, (start, end) in enumerate(zip(boundaries[:-1], boundaries[1:])):
            energy = section_energies[index]
            relative = energy / max(median_energy, 1e-6)
            previous = sections[-1].kind if sections else None
            if index == 0 and (relative < 1.12 or duration < 45):
                kind = "intro"
                label = "Intro"
                confidence = 0.45
            elif end >= duration - 0.01 and (relative < 0.85 or (end - start) < 15):
                kind = "outro"
                label = "Outro"
                confidence = 0.4
            elif relative >= 1.22:
                kind = "chorus"
                label = "High-energy section"
                confidence = min(0.85, 0.45 + min(0.4, (relative - 1.0) * 0.3))
            elif relative <= 0.62:
                kind = "breakdown"
                label = "Low-energy breakdown"
                confidence = 0.5
            elif previous == "chorus" and relative < 1.08:
                kind = "verse"
                label = "Settled section"
                confidence = 0.45
            elif previous in (None, "intro"):
                kind = "verse"
                label = "Opening section"
                confidence = 0.4
            else:
                kind = "bridge"
                label = "Transitional section"
                confidence = 0.35
            sections.append(
                MusicalSection(
                    id=index + 1,
                    start=round(float(start), 3),
                    end=round(float(end), 3),
                    label=label,
                    kind=kind,  # type: ignore[arg-type]
                    energy=round(float(energy), 4),
                    energy_relative=round(float(relative), 3),
                    confidence=round(confidence, 3),
                )
            )

        # --- Onsets ----------------------------------------------------------
        onset_times = librosa.onset.onset_detect(
            onset_envelope=onset_env,
            sr=sr,
            hop_length=HOP_LENGTH,
            units="time",
            backtrack=True,
        )
        onset_events: list[OnsetEvent] = []
        for onset_time in np.asarray(onset_times)[:2000]:
            if onset_time < 0 or onset_time >= duration:
                continue
            strength = float(np.interp(onset_time, frame_times, _safe_norm(np.asarray(onset_env))))
            onset_events.append(OnsetEvent(time=round(float(onset_time), 3), strength=round(strength, 3)))

        loudness = _format_db(float(np.sqrt(np.mean(y**2))))
        analysis_seconds = round(time.perf_counter() - started, 2)

        return AudioAnalysis(
            duration=duration,
            sample_rate=sr,
            tempo=round(float(tempo), 2),
            beat_interval=round(float(beat_interval), 4),
            beats=beats,
            downbeats=downbeats,
            sections=sections,
            rms=rms_series,
            peak=peak_series,
            bands=BandEnergies(
                times=bass_series.times,
                bass=bass_series.values,
                mid=mid_series.values,
                high=high_series.values,
            ),
            spectral_centroid=centroid_series,
            onsets=onset_events,
            loudness_db=loudness,
            analysis_seconds=analysis_seconds,
            warnings=warnings,
        )
