"""Audio IO, conversion and merging helpers.

Heavy audio libraries (numpy, soundfile) are imported inside the functions so
the API process can start even on a minimal image. ffmpeg/ffprobe are provided
by the Docker image.
"""

from __future__ import annotations

import io
import math
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any

SAMPLE_RATE = 24_000
MIME_TYPES = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "flac": "audio/flac",
}
SUPPORTED_FORMATS = tuple(MIME_TYPES)
PIPER_FORMATS = ("wav", "mp3")


class AudioConversionError(RuntimeError):
    """Raised when ffmpeg cannot decode, encode or probe an audio file."""


def _run_ffmpeg(cmd: list[str], timeout: int = 900) -> None:
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise AudioConversionError("Audio conversion timed out") from exc
    except FileNotFoundError as exc:
        raise AudioConversionError("ffmpeg is not installed in this image") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        tail = "\n".join(detail.splitlines()[-12:])
        raise AudioConversionError(tail or "ffmpeg failed")


def convert_to_wav(src: Path, dst: Path, sample_rate: int = SAMPLE_RATE) -> None:
    """Decode any ffmpeg-supported input to mono 16-bit PCM WAV."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            str(dst),
        ]
    )
    if not dst.is_file() or dst.stat().st_size <= 44:
        raise AudioConversionError("Converted audio file is empty")


def _atempo_chain(tempo: float) -> list[str]:
    """Build a valid atempo chain for any tempo (each stage is 0.5–2.0)."""
    filters: list[str] = []
    value = max(0.01, float(tempo))
    while value < 0.5:
        filters.append("atempo=0.5")
        value /= 0.5
    while value > 2.0:
        filters.append("atempo=2.0")
        value /= 2.0
    if abs(value - 1.0) > 0.0001:
        filters.append(f"atempo={value:.6f}")
    return filters


def _source_sample_rate(src: Path) -> int:
    try:
        with wave.open(str(src), "rb") as reader:
            return int(reader.getframerate()) or SAMPLE_RATE
    except Exception:  # noqa: BLE001
        pass
    try:
        import soundfile as sf

        info = sf.info(str(src))
        return int(info.samplerate) or SAMPLE_RATE
    except Exception:  # noqa: BLE001
        return SAMPLE_RATE


def audio_filters(
    *,
    sample_rate: int,
    normalize: bool = False,
    pitch_semitones: float = 0.0,
) -> list[str]:
    filters: list[str] = []
    pitch = float(pitch_semitones or 0.0)
    if abs(pitch) > 0.0001:
        factor = 2.0 ** (pitch / 12.0)
        shifted_rate = max(1000, int(round(sample_rate * factor)))
        filters.append(f"asetrate={shifted_rate}")
        filters.append(f"aresample={sample_rate}")
        filters.extend(_atempo_chain(1.0 / factor))
    if normalize:
        filters.append("dynaudnorm=f=200:g=15:p=0.90")
    return filters


def convert_wav_to(
    src: Path,
    dst: Path,
    fmt: str,
    *,
    normalize: bool = False,
    pitch_semitones: float = 0.0,
    timeout: int = 900,
) -> None:
    """Convert a WAV file to wav/mp3/flac, optionally normalizing or pitching."""
    fmt = (fmt or "wav").lower()
    if fmt not in MIME_TYPES:
        raise AudioConversionError(f"Unsupported audio format: {fmt}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    filters = audio_filters(
        sample_rate=_source_sample_rate(src),
        normalize=normalize,
        pitch_semitones=pitch_semitones,
    )
    if fmt == "wav" and not filters:
        if src.resolve() != dst.resolve():
            shutil.copyfile(src, dst)
        return

    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-vn"]
    if filters:
        args += ["-af", ",".join(filters)]
    if fmt == "mp3":
        args += ["-c:a", "libmp3lame", "-b:a", "192k"]
    elif fmt == "flac":
        args += ["-c:a", "flac"]
    else:
        args += ["-c:a", "pcm_s16le"]
    args.append(str(dst))
    _run_ffmpeg(args, timeout=timeout)
    if not dst.is_file() or dst.stat().st_size == 0:
        raise AudioConversionError("Converted audio file is empty")


def probe_duration(path: Path) -> float:
    """Return duration in seconds with soundfile and an ffprobe fallback."""
    try:
        import soundfile as sf

        return float(sf.info(str(path)).duration)
    except Exception:  # noqa: BLE001
        pass
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        return float(proc.stdout.decode().strip())
    except Exception as exc:  # noqa: BLE001
        raise AudioConversionError("Could not read audio duration") from exc


def write_wav(path: Path, audio: Any, sample_rate: int = SAMPLE_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import soundfile as sf

        sf.write(str(path), audio, sample_rate, format="WAV", subtype="PCM_16")
    except Exception as exc:  # noqa: BLE001
        raise AudioConversionError(f"Could not write WAV audio: {exc}") from exc


def write_audio_file(
    dst: Path,
    audio: Any,
    sample_rate: int,
    fmt: str,
    *,
    normalize: bool = False,
) -> None:
    """Write a float waveform as the requested format via a temporary WAV."""
    fmt = (fmt or "wav").lower()
    if fmt not in MIME_TYPES:
        raise AudioConversionError(f"Unsupported audio format: {fmt}")
    if fmt == "wav" and not normalize:
        write_wav(dst, audio, sample_rate)
        return
    with tempfile.TemporaryDirectory(prefix="voice-encode-") as tmp:
        wav_path = Path(tmp) / "audio.wav"
        write_wav(wav_path, audio, sample_rate)
        convert_wav_to(wav_path, dst, fmt, normalize=normalize, timeout=900)


def encode_audio(audio: Any, sample_rate: int, fmt: str) -> bytes:
    """Encode a float waveform into bytes (used by small internal helpers)."""
    with tempfile.TemporaryDirectory(prefix="voice-encode-") as tmp:
        path = Path(tmp) / f"audio.{fmt}"
        write_audio_file(path, audio, sample_rate, fmt)
        return path.read_bytes()


def wave_duration(path: Path) -> tuple[float, int]:
    with wave.open(str(path), "rb") as reader:
        rate = int(reader.getframerate())
        frames = int(reader.getnframes())
        return (frames / float(rate) if rate else 0.0), rate


def merge_wav_chunks(
    paths: list[Path],
    texts: list[str],
    destination: Path,
    gap_seconds: float,
) -> tuple[list[dict[str, Any]], float]:
    """Concatenate sentence WAVs and build a real start/end timeline."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_params: tuple[int, int, int] | None = None
    frames_written = 0
    timeline: list[dict[str, Any]] = []
    with wave.open(str(destination), "wb") as output:
        for index, (path, text) in enumerate(zip(paths, texts, strict=False)):
            with wave.open(str(path), "rb") as source:
                params = (
                    int(source.getframerate()),
                    int(source.getsampwidth()),
                    int(source.getnchannels()),
                )
                if source_params is None:
                    source_params = params
                    output.setframerate(params[0])
                    output.setsampwidth(params[1])
                    output.setnchannels(params[2])
                elif params != source_params:
                    raise AudioConversionError(
                        "Generated sentence chunks have inconsistent audio formats"
                    )
                rate = params[0]
                if index > 0 and gap_seconds > 0:
                    gap_frames = int(rate * gap_seconds)
                    output.writeframes(b"\x00" * gap_frames * params[1] * params[2])
                    frames_written += gap_frames
                start = frames_written / float(rate)
                remaining = int(source.getnframes())
                while True:
                    frames = source.readframes(min(65536, max(1, remaining)))
                    if not frames:
                        break
                    output.writeframes(frames)
                    written = len(frames) // (params[1] * params[2])
                    frames_written += written
                    remaining -= written
                end = frames_written / float(rate)
                if end > start:
                    timeline.append(
                        {
                            "index": len(timeline) + 1,
                            "text": text,
                            "start": round(start, 3),
                            "end": round(end, 3),
                        }
                    )
    duration = frames_written / float(source_params[0]) if source_params else 0.0
    return timeline, duration


def duration_of(audio: Any, sample_rate: int) -> float:
    try:
        return float(len(audio)) / float(sample_rate)
    except Exception:  # noqa: BLE001
        return 0.0


def pitch_is_identity(value: float | None) -> bool:
    try:
        return math.isclose(float(value or 0.0), 0.0, abs_tol=0.0001)
    except (TypeError, ValueError):
        return True


def bytes_to_tempfile(data: bytes, suffix: str = ".wav") -> Path:
    handle = tempfile.NamedTemporaryFile(prefix="voice-audio-", suffix=suffix, delete=False)
    try:
        handle.write(data)
        handle.flush()
        return Path(handle.name)
    finally:
        handle.close()


def wav_bytes(audio: Any, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    try:
        import soundfile as sf

        sf.write(buffer, audio, sample_rate, format="WAV", subtype="PCM_16")
    except Exception as exc:  # noqa: BLE001
        raise AudioConversionError(f"Could not encode WAV audio: {exc}") from exc
    return buffer.getvalue()
