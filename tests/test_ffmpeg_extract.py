"""Real FFmpeg audio-extraction coverage for the shared media workbench."""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from openstudio_common import FILES_ROOT
from services.ffmpeg.executor import ExecutionHooks
from services.ffmpeg.operations import execute_operation


def test_extract_audio_with_real_ffmpeg(tmp_path):
    source = Path(FILES_ROOT) / "ffmpeg" / "extract-input.wav"
    source.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 22050
    t = np.linspace(0, 0.6, int(sample_rate * 0.6), endpoint=False)
    mono = (0.2 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
    wavfile.write(source, sample_rate, np.stack([mono, mono], axis=1))

    hooks = ExecutionHooks(job_id="test-ffmpeg-extract")
    result = asyncio.run(
        execute_operation(
            "extract_audio",
            {
                "input_path": "ffmpeg/extract-input.wav",
                "output_path": "ffmpeg/extract-output.wav",
                "options": {"format": "wav", "channels": 1},
            },
            workdir=tmp_path,
            hooks=hooks,
        )
    )
    assert result.files
    output = Path(result.files[0])
    assert output.is_file()
    rate, data = wavfile.read(output)
    assert rate == sample_rate
    assert data.ndim == 1
    assert len(data) > 1000
    assert result.data["operation"] == "extract_audio"
    assert result.data["format"] == "wav"


def test_ffmpeg_rejects_unknown_operation(tmp_path):
    hooks = ExecutionHooks(job_id="test-ffmpeg-unknown")
    try:
        asyncio.run(
            execute_operation(
                "not-a-real-operation",
                {"input_path": "", "options": {}},
                workdir=tmp_path,
                hooks=hooks,
            )
        )
    except ValueError as exc:
        assert "Unknown FFmpeg operation" in str(exc)
    else:
        raise AssertionError("unknown FFmpeg operation was accepted")
