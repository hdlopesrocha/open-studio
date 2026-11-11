"""Files, subtitles, manifests and ZIP bundles for document jobs."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any, Iterable

from openstudio_common import (
    atomic_write_json,
    atomic_write_text,
    build_srt,
    build_vtt,
    file_info,
    normalize_cues,
    read_json,
    relative_path,
    resolve_path,
    utc_now,
)

from .text import word_count

TEXT_KINDS = {
    "extracted": ("extracted.txt", "Extracted text"),
    "translation": ("translation.txt", "Translation"),
    "summary": ("summary.txt", "Summary"),
}
_JOB_ID = re.compile(r"^[A-Fa-f0-9][A-Fa-f0-9-]{7,79}$")


def safe_job_id(job_id: str) -> str:
    if not job_id or not _JOB_ID.fullmatch(job_id):
        raise ValueError("Invalid job id")
    return job_id


def job_dir(job_id: str, *, create: bool = True) -> Path:
    path = resolve_path("documents", safe_job_id(job_id))
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def text_path(job_id: str, kind: str, *, create: bool = False) -> Path:
    if kind not in TEXT_KINDS:
        raise ValueError(f"Unknown text kind: {kind}")
    return job_dir(job_id, create=create) / TEXT_KINDS[kind][0]


def text_info(job_id: str, kind: str) -> dict[str, Any]:
    path = text_path(job_id, kind)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    text = path.read_text(encoding="utf-8")
    return {
        "kind": kind,
        "label": TEXT_KINDS[kind][1],
        "filename": path.name,
        "path": relative_path(path),
        "characters": len(text),
        "words": word_count(text),
        "size_bytes": path.stat().st_size,
        "updated_at": utc_now(),
        "available": True,
    }


def write_text(job_id: str, kind: str, text: str) -> dict[str, Any]:
    path = text_path(job_id, kind, create=True)
    atomic_write_text(path, text)
    info = text_info(job_id, kind)
    info["text"] = text
    return info


def read_text(job_id: str, kind: str) -> dict[str, Any]:
    path = text_path(job_id, kind)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    text = path.read_text(encoding="utf-8")
    return {
        "job_id": job_id,
        "kind": kind,
        "label": TEXT_KINDS[kind][1],
        "text": text,
        "characters": len(text),
        "words": word_count(text),
        "size_bytes": path.stat().st_size,
        "path": relative_path(path),
    }


def write_subtitles(job_id: str, timeline: Iterable[dict[str, Any]]) -> dict[str, Any]:
    cues = normalize_cues(list(timeline))
    folder = job_dir(job_id)
    srt_path = folder / "subtitles.srt"
    vtt_path = folder / "captions.vtt"
    atomic_write_text(srt_path, build_srt(cues))
    atomic_write_text(vtt_path, build_vtt(cues))
    return {
        "cues": len(cues),
        "srt": file_info(srt_path),
        "vtt": file_info(vtt_path),
        "segments": cues,
    }


def manifest_path(job_id: str) -> Path:
    return job_dir(job_id, create=False) / "manifest.json"


def read_manifest(job_id: str) -> dict[str, Any] | None:
    data = read_json(manifest_path(job_id))
    return data if isinstance(data, dict) else None


def write_manifest(job_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
    data = dict(manifest)
    data["updated_at"] = utc_now()
    atomic_write_json(manifest_path(job_id), data)
    return data


def update_manifest_text(job_id: str, kind: str, info: dict[str, Any]) -> None:
    manifest = read_manifest(job_id)
    if not manifest:
        return
    artifacts = manifest.setdefault("artifacts", {})
    entry = {key: value for key, value in info.items() if key != "text"}
    try:
        entry.update(file_info(text_path(job_id, kind)))
    except (OSError, ValueError):
        pass
    entry["kind"] = kind
    artifacts[kind] = entry
    stats = manifest.setdefault("stats", {})
    stats[f"{kind}_words"] = info.get("words")
    stats[f"{kind}_characters"] = info.get("characters")
    manifest["updated_at"] = utc_now()
    atomic_write_json(manifest_path(job_id), manifest)


def job_files(job_id: str) -> list[dict[str, Any]]:
    folder = job_dir(job_id, create=False)
    if not folder.is_dir():
        return []
    return [
        file_info(path)
        for path in sorted(folder.iterdir())
        if path.is_file() and not path.name.startswith(".") and path.name != "output.zip"
    ]


def build_zip(job_id: str) -> dict[str, Any]:
    folder = job_dir(job_id)
    files = [
        path
        for path in sorted(folder.iterdir())
        if path.is_file() and not path.name.startswith(".") and path.name != "output.zip"
    ]
    archive = folder / "output.zip"
    if not files:
        raise ValueError("There are no files to archive")
    try:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
            for path in files:
                bundle.write(path, path.name)
    except Exception:
        archive.unlink(missing_ok=True)
        raise
    info = file_info(archive)
    info["files"] = [relative_path(path) for path in files]
    return info
