"""Explicit catalog of supported Piper voices.

Only voices listed here can be loaded. User input never becomes a filesystem
path: all paths are built from the fixed catalog entry and the model root.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PiperVoice:
    id: str
    name: str
    language: str
    language_name: str
    engine: str
    quality: str
    sample_rate: int
    repo_id: str
    repo_model_path: str
    repo_config_path: str
    license: str
    description: str
    gender: str = "unspecified"
    pitch_supported: bool = False

    def onnx_path(self, root: Path | str) -> Path:
        return Path(root) / self.id / f"{self.id}.onnx"

    def config_path(self, root: Path | str) -> Path:
        return Path(root) / self.id / f"{self.id}.onnx.json"

    def available(self, root: Path | str) -> bool:
        return self.onnx_path(root).is_file() and self.config_path(root).is_file()

    def public(self, root: Path | str) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("repo_id", None)
        payload.pop("repo_model_path", None)
        payload.pop("repo_config_path", None)
        payload["available"] = self.available(root)
        payload["download_hint"] = (
            None
            if payload["available"]
            else f'POST /api/voice/piper/install {{"voice_id":"{self.id}"}}'
        )
        if payload["available"]:
            try:
                payload["size_bytes"] = self.onnx_path(root).stat().st_size
            except OSError:
                payload["size_bytes"] = None
        else:
            payload["size_bytes"] = None
        return payload


VOICES: tuple[PiperVoice, ...] = (
    PiperVoice(
        id="pt-PT-tugao",
        name="Tugão",
        language="pt-PT",
        language_name="Portuguese (Portugal)",
        engine="piper",
        quality="medium",
        sample_rate=22050,
        repo_id="rhasspy/piper-voices",
        repo_model_path="pt/pt_PT/tugão/medium/pt_PT-tugão-medium.onnx",
        repo_config_path="pt/pt_PT/tugão/medium/pt_PT-tugão-medium.onnx.json",
        license="CC0 (voice dataset)",
        description="European Portuguese neural voice, male single speaker, 22.05 kHz.",
        gender="male",
    ),
    PiperVoice(
        id="pt-PT-dii",
        name="Dii",
        language="pt-PT",
        language_name="Portuguese (Portugal)",
        engine="piper",
        quality="medium",
        sample_rate=22050,
        repo_id="OpenVoiceOS/pipertts_pt-PT_dii",
        repo_model_path="dii_pt-PT.onnx",
        repo_config_path="dii_pt-PT.onnx.json",
        license="CC BY-NC-ND 4.0",
        description="European Portuguese neural voice, female single speaker, 22.05 kHz.",
        gender="female",
    ),
    PiperVoice(
        id="pt-BR-faber",
        name="Faber",
        language="pt-BR",
        language_name="Portuguese (Brazil)",
        engine="piper",
        quality="medium",
        sample_rate=22050,
        repo_id="rhasspy/piper-voices",
        repo_model_path="pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx",
        repo_config_path="pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx.json",
        license="CC0 (voice dataset)",
        description="Brazilian Portuguese neural voice, male single speaker, 22.05 kHz.",
        gender="male",
    ),
    PiperVoice(
        id="pt-BR-dii",
        name="Dii",
        language="pt-BR",
        language_name="Portuguese (Brazil)",
        engine="piper",
        quality="medium",
        sample_rate=22050,
        repo_id="OpenVoiceOS/pipertts_pt-BR_dii",
        repo_model_path="dii_pt-BR.onnx",
        repo_config_path="dii_pt-BR.onnx.json",
        license="CC BY-NC-ND 4.0",
        description="Brazilian Portuguese neural voice, female single speaker, 22.05 kHz.",
        gender="female",
    ),
    PiperVoice(
        id="en-US-lessac",
        name="Lessac",
        language="en-US",
        language_name="English (United States)",
        engine="piper",
        quality="medium",
        sample_rate=22050,
        repo_id="rhasspy/piper-voices",
        repo_model_path="en/en_US/lessac/medium/en_US-lessac-medium.onnx",
        repo_config_path="en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
        license="Lessac Blizzard 2013 license",
        description="US English neural voice, female single speaker, 22.05 kHz.",
        gender="female",
    ),
)

VOICE_BY_ID = {voice.id: voice for voice in VOICES}
DEFAULT_PIPER_VOICE = "pt-PT-tugao"


def get_voice(voice_id: str | None, default: str = DEFAULT_PIPER_VOICE) -> PiperVoice:
    voice = VOICE_BY_ID.get((voice_id or default).strip())
    if voice is None:
        raise KeyError(
            f"Unknown Piper voice: {voice_id}. Available voices: {', '.join(VOICE_BY_ID)}"
        )
    return voice


def language_matches(requested: str | None, voice_language: str) -> bool:
    """Match languages, allowing ``pt`` for either Portuguese variant."""
    req = (requested or "").lower().replace("_", "-")
    lang = (voice_language or "").lower().replace("_", "-")
    if not req:
        return True
    req_base = req.split("-", 1)[0]
    lang_base = lang.split("-", 1)[0]
    if req_base != lang_base:
        return False
    # An unqualified "pt" accepts either variant. A qualified variant must
    # match exactly so the UI never claims the wrong regional accent.
    if "-" in req and req != lang:
        return False
    return True


def voices_for_language(language: str | None) -> list[PiperVoice]:
    if not language:
        return list(VOICES)
    return [voice for voice in VOICES if language_matches(language, voice.language)]


def catalog(root: Path | str, language: str | None = None) -> list[dict[str, Any]]:
    return [voice.public(root) for voice in voices_for_language(language)]
