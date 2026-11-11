"""Explicit model downloader for the summary service."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["TRANSFORMERS_OFFLINE"] = "0"

from .config import settings  # noqa: E402

GROUPS = {
    "en": ["t5-small-en"],
    "pt": ["t5-small-pt"],
    "all": ["t5-small-en", "t5-small-pt"],
}

MODELS = {
    "t5-small-en": {
        "language": "en",
        "repo": settings.model_en_repo,
        "revision": settings.model_en_revision,
        "path": settings.model_directories["en"],
    },
    "t5-small-pt": {
        "language": "pt",
        "repo": settings.model_pt_repo,
        "revision": settings.model_pt_revision,
        "path": settings.model_directories["pt"],
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download Open Studio summary models")
    parser.add_argument(
        "--models",
        default="all",
        help="Comma-separated model ids or groups: en, pt, all, t5-small-en, t5-small-pt",
    )
    parser.add_argument("--list", action="store_true", help="List models and exit")
    return parser.parse_args()


def selected_models(raw: str) -> list[str]:
    requested: list[str] = []
    for token in [part.strip() for part in raw.split(",") if part.strip()]:
        if token in GROUPS:
            requested.extend(GROUPS[token])
        elif token in MODELS:
            requested.append(token)
        else:
            raise SystemExit(f"Unknown model or group: {token}")
    return list(dict.fromkeys(requested))


def main() -> int:
    args = parse_args()
    if args.list:
        for model_id, meta in MODELS.items():
            print(f"{model_id:15} {meta['repo']:60} -> {meta['path']}")
        return 0
    models = selected_models(args.models)
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise SystemExit("huggingface_hub is not installed in this image") from exc
    failures = 0
    for model_id in models:
        meta = MODELS[model_id]
        target = Path(meta["path"])
        target.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {model_id} ({meta['repo']}) -> {target}", flush=True)
        try:
            snapshot_download(
                repo_id=meta["repo"],
                revision=meta["revision"],
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
