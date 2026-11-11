"""Safe shared-storage helpers.

All user-visible files live under ``FILES_ROOT`` and are addressed by relative
POSIX paths. Every service mounts the same volume, so a file produced by the
music service is immediately visible to the video, voice, ffmpeg, qvac and
file-explorer services.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import tempfile
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator

from .config import FILES_ROOT, KIND_DIRS, MAX_UPLOAD_MB

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ ()\[\]-]+")
_MEDIA_KINDS = {
    "audio": {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".aiff", ".aif", ".wma"},
    "video": {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".mpeg", ".mpg"},
    "image": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".avif", ".svg"},
    "subtitle": {".srt", ".vtt", ".ass", ".ssa"},
    "document": {".pdf", ".txt", ".md", ".json", ".csv", ".docx", ".epub"},
    "archive": {".zip", ".tar", ".gz", ".tgz", ".7z"},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def ensure_storage() -> None:
    FILES_ROOT.mkdir(parents=True, exist_ok=True)
    for sub in KIND_DIRS.values():
        (FILES_ROOT / sub).mkdir(parents=True, exist_ok=True)


def sanitize_name(name: str, fallback: str = "file") -> str:
    name = unicodedata.normalize("NFKC", os.path.basename(name or "")).strip()
    name = _SAFE_NAME.sub("_", name).strip(" .")
    if not name:
        name = fallback
    return name[:180]


def sanitize_relpath(rel: str) -> str:
    raw = (rel or "").replace("\\", "/").strip()
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise ValueError("Absolute paths are not allowed")
    rel = str(PurePosixPath(raw))
    if rel in {"", "."}:
        return ""
    parts = [p for p in rel.split("/") if p not in {"", "."}]
    if any(p == ".." for p in parts):
        raise ValueError("Path traversal is not allowed")
    return "/".join(parts)


def resolve_path(*parts: str) -> Path:
    rel = sanitize_relpath("/".join(str(p) for p in parts if p not in (None, "")))
    path = (FILES_ROOT / rel).resolve() if rel else FILES_ROOT.resolve()
    root = FILES_ROOT.resolve()
    if path != root and root not in path.parents:
        raise ValueError("Path escapes the shared files root")
    return path


def relative_path(path: Path | str) -> str:
    resolved = Path(path).resolve()
    root = FILES_ROOT.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("Path is outside the shared files root")
    if resolved == root:
        return ""
    return resolved.relative_to(root).as_posix()


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    ensure_parent(path)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def unique_path(directory: Path, filename: str, suffix: str = "") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stem = Path(filename).stem
    ext = suffix or Path(filename).suffix
    candidate = directory / f"{stem}{ext}"
    index = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{index}{ext}"
        index += 1
    return candidate


def guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def kind_of(path: Path | str) -> str:
    suffix = Path(str(path)).suffix.lower()
    for kind, suffixes in _MEDIA_KINDS.items():
        if suffix in suffixes:
            return kind
    return "other"


def human_size(num: int | float) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def file_info(path: Path, root: Path | None = None) -> dict[str, Any]:
    root = root or FILES_ROOT
    stat = path.stat()
    rel = path.resolve().relative_to(root.resolve()).as_posix()
    return {
        "name": path.name,
        "path": rel,
        "is_dir": path.is_dir(),
        "size": 0 if path.is_dir() else stat.st_size,
        "size_label": human_size(0 if path.is_dir() else stat.st_size),
        "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "mime": "inode/directory" if path.is_dir() else guess_mime(path),
        "kind": "folder" if path.is_dir() else kind_of(path),
        "url": f"/api/files/raw/{rel}",
    }


def list_directory(rel: str = "", query: str = "", kind: str = "", limit: int = 2000) -> list[dict[str, Any]]:
    path = resolve_path(rel)
    if not path.exists():
        raise FileNotFoundError(rel)
    if not path.is_dir():
        raise NotADirectoryError(rel)
    needle = query.strip().lower()
    items: list[dict[str, Any]] = []
    for entry in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if entry.name.startswith("."):
            continue
        info = file_info(entry)
        if needle and needle not in info["name"].lower():
            continue
        if kind and kind not in {"all", info["kind"]}:
            continue
        items.append(info)
        if len(items) >= limit:
            break
    return items


def walk_files(root: Path | None = None, max_files: int = 20000) -> Iterator[Path]:
    root = root or FILES_ROOT
    count = 0
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if name.startswith("."):
                continue
            yield Path(base) / name
            count += 1
            if count >= max_files:
                return


def search_files(query: str, kind: str = "", limit: int = 300) -> list[dict[str, Any]]:
    needle = query.strip().lower()
    results: list[dict[str, Any]] = []
    for path in walk_files():
        if needle and needle not in path.name.lower() and needle not in relative_path(path).lower():
            continue
        if kind and kind_of(path) != kind:
            continue
        results.append(file_info(path))
        if len(results) >= limit:
            break
    return results


def copy_into(src: Path, directory: Path, filename: str | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = unique_path(directory, sanitize_name(filename or src.name))
    shutil.copy2(src, target)
    return target


def move_path(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        if dst.is_dir():
            dst = unique_path(dst.parent, dst.name, suffix="")
        else:
            dst = unique_path(dst.parent, dst.name, suffix=dst.suffix)
    shutil.move(str(src), str(dst))
    return dst


def remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def zip_paths(paths: Iterable[Path], destination: Path) -> Path:
    ensure_parent(destination)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            if path.is_dir():
                for child in path.rglob("*"):
                    if child.is_file():
                        archive.write(child, child.relative_to(path.parent).as_posix())
            elif path.is_file():
                archive.write(path, path.name)
    return destination


def extract_zip(archive: Path, destination: Path) -> list[str]:
    destination.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    root = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if root not in target.parents and target != root:
                raise ValueError("Archive contains an unsafe path")
            bundle.extract(member, destination)
            names.append(member.filename)
    return names


def ensure_upload_size(size: int) -> None:
    if size > MAX_UPLOAD_MB * 1024 * 1024:
        raise ValueError(f"Upload exceeds the {MAX_UPLOAD_MB} MB limit")


def parse_range(range_header: str | None, file_size: int) -> tuple[int, int] | None:
    if not range_header or not range_header.startswith("bytes="):
        return None
    spec = range_header[6:].split(",")[0].strip()
    if "-" not in spec:
        return None
    start_s, end_s = spec.split("-", 1)
    try:
        if start_s == "":
            length = int(end_s)
            start = max(0, file_size - length)
            end = file_size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else file_size - 1
    except ValueError:
        return None
    if start < 0 or start >= file_size or end < start:
        return None
    return start, min(end, file_size - 1)


def timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
