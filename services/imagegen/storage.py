"""Shared-storage helpers for generated images, sidecars and the gallery."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from openstudio_common import (
    FILES_ROOT,
    atomic_write_bytes,
    atomic_write_json,
    env,
    file_info,
    read_json,
    resolve_path,
    relative_path,
    sanitize_name,
)

IMAGES_DIR = FILES_ROOT / "images"
VIDEO_PROJECTS_ROOT = Path(env("VIDEO_PROJECTS_ROOT", str(FILES_ROOT / "video" / "projects"))).expanduser()
_PROJECT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}$")
_SLUG = re.compile(r"[^a-z0-9]+")


def ensure_dirs() -> None:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)


def slugify(value: str, fallback: str = "image", max_length: int = 48) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = _SLUG.sub("-", ascii_value).strip("-")
    return (slug[:max_length].strip("-") or fallback)


def normalize_format(value: str | None) -> str:
    value = (value or "png").strip().lower().lstrip(".")
    if value in {"jpg", "jpeg"}:
        return "jpeg"
    if value not in {"png", "jpeg", "webp"}:
        raise ValueError("output_format must be png, jpeg or webp")
    return value


def extension_for(value: str | None) -> str:
    fmt = normalize_format(value)
    return "jpg" if fmt == "jpeg" else fmt


def job_directory(job_id: str) -> Path:
    ensure_dirs()
    directory = resolve_path("images", sanitize_name(job_id, "job"))
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def resolve_input_image(value: str, *, label: str = "image") -> Path:
    raw = (value or "").strip()
    if not raw:
        raise ValueError(f"A {label} path is required")
    candidate = Path(raw)
    if candidate.is_absolute():
        resolved = candidate.expanduser().resolve()
        root = FILES_ROOT.resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError(f"The {label} path must live under {FILES_ROOT}")
        path = resolved
    else:
        path = resolve_path(raw)
    if not path.is_file():
        raise FileNotFoundError(raw)
    return path


def save_pil(image: Image.Image, path: Path, fmt: str, quality: int = 92) -> None:
    fmt = normalize_format(fmt)
    path.parent.mkdir(parents=True, exist_ok=True)
    image = image.convert("RGB") if fmt == "jpeg" or image.mode not in {"RGB", "RGBA"} else image
    buffer = io.BytesIO()
    if fmt == "jpeg":
        image.save(buffer, format="JPEG", quality=max(40, min(100, int(quality))), optimize=True, progressive=True)
    elif fmt == "webp":
        image.save(buffer, format="WEBP", quality=max(40, min(100, int(quality))), method=6)
    else:
        image.save(buffer, format="PNG", optimize=True)
    atomic_write_bytes(path, buffer.getvalue())


def thumbnail(image: Image.Image, max_edge: int = 480) -> Image.Image:
    copy = image.convert("RGB")
    copy.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    return copy


def save_thumbnail_jpeg(image: Image.Image, path: Path, max_edge: int = 480, quality: int = 86) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    thumb = thumbnail(image, max_edge)
    buffer = io.BytesIO()
    thumb.save(buffer, format="JPEG", quality=quality, optimize=True)
    atomic_write_bytes(path, buffer.getvalue())


def descriptive_stem(prompt: str, prefix: str, seed: int, index: int) -> str:
    words = slugify(prompt, "artwork", 44)
    base = f"{slugify(prefix, 'image', 20)}-{words}-{seed}-{index + 1:02d}"
    return sanitize_name(base, "image")[:100]


def write_sidecar(image_path: Path, metadata: dict[str, Any]) -> Path:
    sidecar = image_path.with_suffix(".json")
    atomic_write_json(sidecar, metadata)
    return sidecar


def write_job_manifest(directory: Path, payload: dict[str, Any]) -> Path:
    path = directory / "manifest.json"
    atomic_write_json(path, payload)
    return path


def artifact(path: Path, *, role: str, **extra: Any) -> dict[str, Any]:
    info = file_info(path)
    info["role"] = role
    info.update(extra)
    return info


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Video (MVS) project compatibility
# ---------------------------------------------------------------------------


def project_directory(project_id: str) -> Path:
    if not _PROJECT_ID.match(project_id or ""):
        raise ValueError(f"Invalid project id: {project_id!r}")
    root = VIDEO_PROJECTS_ROOT
    root.mkdir(parents=True, exist_ok=True)
    directory = (root / project_id).resolve()
    if root.resolve() not in directory.parents:
        raise ValueError("Project path escapes the video projects root")
    (directory / "assets" / "images").mkdir(parents=True, exist_ok=True)
    (directory / "assets" / "thumbnails").mkdir(parents=True, exist_ok=True)
    (directory / "cache").mkdir(parents=True, exist_ok=True)
    return directory


def stable_hash(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def project_relative(project_dir: Path, path: Path) -> str:
    return path.resolve().relative_to(project_dir.resolve()).as_posix()


class AssetCache:
    """Small project-scoped cache manifest."""

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = project_dir
        self.manifest_path = project_dir / "cache" / "manifest.json"
        self._lock = threading.RLock()
        self._data: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        if self._data is None:
            self._data = read_json(self.manifest_path, default={"version": 1, "entries": {}}) or {
                "version": 1,
                "entries": {},
            }
            self._data.setdefault("entries", {})
        return self._data

    def key(self, *parts: Any) -> str:
        return stable_hash(parts)

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._load()["entries"].get(key)
            if not entry:
                return None
            target = self.project_dir / entry.get("path", "")
            if not target.is_file():
                self._load()["entries"].pop(key, None)
                return None
            return dict(entry)

    def put(self, key: str, relative: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            entry = {
                "path": relative,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "metadata": metadata or {},
            }
            self._load()["entries"][key] = entry
            atomic_write_json(self.manifest_path, self._data)
            return dict(entry)


# ---------------------------------------------------------------------------
# Gallery
# ---------------------------------------------------------------------------


def _sidecar_image_path(data: dict[str, Any]) -> Path | None:
    value = data.get("path")
    if not isinstance(value, str) or not value:
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        resolved = candidate.resolve()
        root = FILES_ROOT.resolve()
        if resolved != root and root not in resolved.parents:
            return None
        return resolved if resolved.is_file() else None
    try:
        resolved = resolve_path(value)
    except ValueError:
        return None
    return resolved if resolved.is_file() else None


def gallery_items(
    *,
    limit: int = 60,
    offset: int = 0,
    provider: str = "",
    query: str = "",
) -> dict[str, Any]:
    ensure_dirs()
    needle = (query or "").strip().lower()
    provider_filter = (provider or "").strip().lower()
    entries: list[dict[str, Any]] = []
    scanned = 0
    for root, dirs, files in os.walk(IMAGES_DIR):
        dirs[:] = [directory for directory in dirs if not directory.startswith(".")]
        for name in files:
            if not name.endswith(".json") or name == "manifest.json":
                continue
            scanned += 1
            if scanned > 20000:
                break
            sidecar = Path(root) / name
            try:
                data = read_json(sidecar, default=None)
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(data, dict) or data.get("kind") != "imagegen.metadata":
                continue
            image_path = _sidecar_image_path(data)
            if image_path is None:
                continue
            prompt = str(data.get("prompt") or "")
            title = str(data.get("title") or "")
            model = str(data.get("model") or "")
            entry_provider = str(data.get("provider") or "")
            if provider_filter and entry_provider.lower() != provider_filter:
                continue
            if needle and needle not in " ".join([prompt, title, model, str(data.get("negative_prompt") or "")]).lower():
                continue
            thumbnail_value = data.get("thumbnail_path")
            thumbnail_path = None
            if isinstance(thumbnail_value, str) and thumbnail_value:
                try:
                    candidate = resolve_path(thumbnail_value)
                    if candidate.is_file():
                        thumbnail_path = thumbnail_value
                except ValueError:
                    pass
            created = data.get("created_at") or ""
            try:
                stat = image_path.stat()
            except OSError:
                continue
            entries.append(
                {
                    "id": image_path.stem,
                    "path": relative_path(image_path),
                    "thumbnail_path": thumbnail_path,
                    "sidecar_path": relative_path(sidecar),
                    "prompt": prompt,
                    "negative_prompt": data.get("negative_prompt") or "",
                    "title": title,
                    "provider": entry_provider,
                    "model": model,
                    "width": data.get("width"),
                    "height": data.get("height"),
                    "seed": data.get("seed"),
                    "variant": data.get("variant"),
                    "created_at": created or datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    "mtime": stat.st_mtime,
                    "url": f"/api/files/raw/{relative_path(image_path)}",
                }
            )
        if scanned > 20000:
            break
    entries.sort(key=lambda item: (str(item.get("created_at") or ""), item.get("mtime") or 0), reverse=True)
    total = len(entries)
    page = entries[offset : offset + limit]
    for item in page:
        item.pop("mtime", None)
    return {"items": page, "total": total, "limit": limit, "offset": offset}


__all__ = [
    "AssetCache",
    "IMAGES_DIR",
    "VIDEO_PROJECTS_ROOT",
    "artifact",
    "descriptive_stem",
    "ensure_dirs",
    "extension_for",
    "gallery_items",
    "job_directory",
    "normalize_format",
    "project_directory",
    "project_relative",
    "resolve_input_image",
    "save_pil",
    "save_thumbnail_jpeg",
    "slugify",
    "stable_hash",
    "thumbnail",
    "utc_iso",
    "write_job_manifest",
    "write_sidecar",
]
