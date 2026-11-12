"""Small audio probing/writing helpers shared by DJ jobs and routes."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np


def probe_duration(path: Path | str) -> float:
    target = Path(path)
    try:
        import soundfile as sf

        info = sf.info(str(target))
        if info.frames and info.samplerate:
            return round(float(info.frames) / float(info.samplerate), 3)
    except Exception:  # noqa: BLE001 - ffprobe is the fallback for mp3/m4a
        pass
    try:
        output = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(target),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return round(float(output.stdout.strip()), 3)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def write_wav(path: Path | str, audio: np.ndarray, sample_rate: int = 44100) -> None:
    import soundfile as sf

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = np.nan_to_num(np.asarray(audio, dtype=np.float32))
    if data.ndim == 1:
        data = np.stack([data, data], axis=1)
    sf.write(str(target), data, sample_rate, subtype="PCM_16")


def write_json(path: Path | str, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
