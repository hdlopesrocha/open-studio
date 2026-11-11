"""Download Piper voices from Hugging Face into ``/data/models/piper``.

Used both by the ``POST /api/voice/piper/install`` endpoint and by the
``voice-download-models`` container helper. Downloads happen in a staging
directory and are moved into place only when both the model and config exist.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

from .config import Settings
from .errors import PiperUnavailableError, VoiceValidationError
from .voices import VOICES, PiperVoice, get_voice

_INSTALL_LOCK = threading.Lock()


def _download(voice: PiperVoice, root: Path, force: bool = False) -> dict[str, Any]:
    destination = Path(root) / voice.id
    if voice.available(root) and not force:
        return {**voice.public(root), "installed": True, "already_installed": True}

    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise PiperUnavailableError(
            "huggingface_hub is not installed; cannot download Piper voices.",
            details={"voice_id": voice.id},
        ) from exc

    root.mkdir(parents=True, exist_ok=True)
    with _INSTALL_LOCK:
        if voice.available(root) and not force:
            return {**voice.public(root), "installed": True, "already_installed": True}

        with tempfile.TemporaryDirectory(prefix=f".download-{voice.id}-", dir=str(root)) as tmp:
            staging = Path(tmp)
            try:
                model_path = hf_hub_download(
                    repo_id=voice.repo_id,
                    filename=voice.repo_model_path,
                    local_dir=str(staging),
                )
                config_path = hf_hub_download(
                    repo_id=voice.repo_id,
                    filename=voice.repo_config_path,
                    local_dir=str(staging),
                )
            except Exception as exc:  # noqa: BLE001
                raise PiperUnavailableError(
                    f"Could not download Piper voice {voice.id} from {voice.repo_id}: {exc}",
                    details={"voice_id": voice.id, "repo_id": voice.repo_id},
                ) from exc

            model_file = Path(model_path)
            config_file = Path(config_path)
            if not model_file.is_file() or model_file.stat().st_size == 0:
                raise PiperUnavailableError(
                    f"Downloaded Piper model for {voice.id} is empty.",
                    details={"voice_id": voice.id},
                )
            if not config_file.is_file():
                raise PiperUnavailableError(
                    f"Downloaded Piper config for {voice.id} is missing.",
                    details={"voice_id": voice.id},
                )

            destination.mkdir(parents=True, exist_ok=True)
            for source, target in (
                (model_file, voice.onnx_path(root)),
                (config_file, voice.config_path(root)),
            ):
                temporary = target.with_name(f".{target.name}.tmp")
                shutil.copyfile(source, temporary)
                temporary.replace(target)

    return {**voice.public(root), "installed": True, "already_installed": False}


def install_voice(
    settings: Settings,
    voice_id: str,
    force: bool = False,
) -> dict[str, Any]:
    try:
        voice = get_voice(voice_id, settings.default_piper_voice)
    except KeyError as exc:
        raise VoiceValidationError(str(exc), details={"voice_id": voice_id}) from exc
    return _download(voice, settings.piper_dir, force=force)


def install_many(
    settings: Settings,
    voice_ids: list[str] | None = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    if voice_ids:
        selected = []
        for voice_id in voice_ids:
            try:
                selected.append(get_voice(voice_id, settings.default_piper_voice))
            except KeyError as exc:
                raise VoiceValidationError(str(exc), details={"voice_id": voice_id}) from exc
    else:
        selected = list(VOICES)
    return [_download(voice, settings.piper_dir, force=force) for voice in selected]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download Piper voices into the model volume.")
    parser.add_argument("voice_ids", nargs="*", help="Voice ids (default: all catalog voices)")
    parser.add_argument("--force", action="store_true", help="Re-download even if installed")
    parser.add_argument("--list", action="store_true", help="List catalog voices and exit")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    if args.list:
        for voice in VOICES:
            state = "installed" if voice.available(settings.piper_dir) else "missing"
            print(f"{voice.id:16} {state:9} {voice.language:8} {voice.name}")
        return 0

    failed = 0
    for voice in args.voice_ids or [item.id for item in VOICES]:
        try:
            result = install_many(settings, [voice], force=args.force)[0]
            print(f"[voice] {result['id']}: {'already installed' if result['already_installed'] else 'installed'}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"[voice] {voice}: failed: {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
