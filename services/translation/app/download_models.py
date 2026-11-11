"""Explicit model downloader for the translation service.

The service never downloads models at inference time. Build the image, then run
the container once with ``download-models`` to populate /data/models/translation.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["TRANSFORMERS_OFFLINE"] = "0"

from .config import settings  # noqa: E402

GROUPS = {
    "opus": ["opus-mt-pt-en", "opus-mt-en-pt"],
    "nllb": ["nllb-200-distilled-600M"],
    "all": ["opus-mt-pt-en", "opus-mt-en-pt", "nllb-200-distilled-600M"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download Open Studio translation models")
    parser.add_argument(
        "--models",
        default="opus",
        help=(
            "Comma-separated model ids or groups: opus, nllb, all, "
            "opus-mt-pt-en, opus-mt-en-pt, nllb-200-distilled-600M"
        ),
    )
    parser.add_argument("--list", action="store_true", help="List models and exit")
    return parser.parse_args()


def selected_models(raw: str) -> list[str]:
    requested: list[str] = []
    for token in [part.strip() for part in raw.split(",") if part.strip()]:
        if token in GROUPS:
            requested.extend(GROUPS[token])
        elif token in settings.models:
            requested.append(token)
        else:
            raise SystemExit(f"Unknown model or group: {token}")
    seen: set[str] = set()
    result: list[str] = []
    for model in requested:
        if model not in seen:
            seen.add(model)
            result.append(model)
    return result


def main() -> int:
    args = parse_args()
    if args.list:
        for model_id, meta in settings.models.items():
            print(f"{model_id:30} {meta['repo']:55} -> {meta['path']}")
        return 0
    models = selected_models(args.models)
    if not models:
        raise SystemExit("No models selected")
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise SystemExit("huggingface_hub is not installed in this image") from exc
    failures = 0
    for model_id in models:
        meta = settings.models[model_id]
        target = Path(meta["path"])
        target.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {model_id} ({meta['repo']}) -> {target}", flush=True)
        try:
            snapshot_download(
                repo_id=meta["repo"],
                local_dir=str(target),
                local_dir_use_symlinks=False,
                resume_download=True,
            )
            print(f"Ready: {model_id}", flush=True)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAILED: {model_id}: {exc}", file=sys.stderr, flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
