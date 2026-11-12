"""End-to-end DJ scene mixing with synthetic tracks."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from services.dj import mixer


def test_render_mix_writes_a_real_audio_file(tmp_path, monkeypatch):
    sr = 22050

    def fake_load_track(path, sample_rate=sr):
        # A deterministic stereo tone per source path.
        seconds = 1.2
        t = np.linspace(0, seconds, int(sample_rate * seconds), endpoint=False)
        frequency = 220.0 if "a" in str(path) else 330.0
        tone = 0.15 * np.sin(2 * np.pi * frequency * t)
        return np.stack([tone, tone], axis=1).astype(np.float32)

    fake_soundfile = types.SimpleNamespace(
        write=lambda path, audio, rate, subtype=None: wavfile.write(
            path,
            rate,
            np.clip(audio * 32767, -32768, 32767).astype(np.int16),
        )
    )
    monkeypatch.setattr(mixer, "load_track", fake_load_track)
    monkeypatch.setitem(sys.modules, "soundfile", fake_soundfile)

    scene = {
        "title": "Test mix",
        "master_bpm": 120,
        "seed": 3,
        "tracks": [
            {
                "title": "A",
                "path": "/fake/a.wav",
                "in": 0,
                "out": 1.0,
                "bpm": 120,
                "gain_db": 0,
                "effects": [{"type": "drive", "amount": 0.1}],
                "transition": {"type": "crossfade", "beats": 2},
            },
            {
                "title": "B",
                "path": "/fake/b.wav",
                "in": 0,
                "out": 1.0,
                "bpm": 126,
                "gain_db": -1,
                "effects": [],
                "transition": {"type": "cut", "beats": 0},
            },
        ],
    }
    output = tmp_path / "mix.wav"
    result = mixer.render_mix(scene, output, sr=sr)
    assert output.is_file()
    assert output.stat().st_size > 1000
    assert result["tracks"] == 2
    assert result["duration"] > 1.5
    assert len(result["timeline"]) == 2
    rate, audio = wavfile.read(output)
    assert rate == sr
    assert audio.ndim == 2
    assert audio.shape[1] == 2
    assert np.max(np.abs(audio)) > 100
