"""Project persistence, path safety and asset caching."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import get_settings
from .models import Project, ProjectSummary, project_summary, utcnow


def _files_root() -> Path:
    return get_settings().files_root

PROJECT_SUBDIRS = (
    "input",
    "analysis",
    "planning",
    "assets/images",
    "assets/videos",
    "assets/thumbnails",
    "assets/depth",
    "cache",
    "output",
    "logs/jobs",
)

_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")


class StorageError(RuntimeError):
    pass


class ProjectNotFound(StorageError):
    pass


def slugify(value: str, fallback: str = "project") -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-").lower()
    return slug[:48] or fallback


def make_project_id(name: str) -> str:
    suffix = hashlib.sha256(os.urandom(16)).hexdigest()[:6]
    return f"{slugify(name)}-{suffix}"


def sanitize_filename(filename: str, fallback: str = "file") -> str:
    base = Path(filename or "").name
    base = base.replace("\x00", "")
    if not base or base in {".", ".."}:
        base = fallback
    cleaned = _SAFE_NAME_RE.sub("_", base).strip("._")
    return cleaned[:120] or fallback


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise StorageError(f"Corrupt JSON file {path}: {exc}") from exc


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_under(base: Path, candidate: str | Path) -> Path:
    """Resolve a relative path and refuse anything outside ``base``."""
    base = base.resolve()
    target = (base / candidate).resolve() if not Path(candidate).is_absolute() else Path(candidate).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise StorageError(f"Path escapes the project directory: {candidate}") from exc
    return target


def ensure_within_roots(path: Path, roots: tuple[Path, ...]) -> Path:
    resolved = path.expanduser().resolve()
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return resolved
        except ValueError:
            continue
    raise StorageError(f"Output path is outside the allowed roots: {resolved}")


def disk_usage(path: Path) -> dict[str, int]:
    target = path
    while not target.exists() and target.parent != target:
        target = target.parent
    usage = shutil.disk_usage(target)
    return {"total": usage.total, "used": usage.used, "free": usage.free}


class ProjectPaths:
    def __init__(self, root: Path, project_id: str):
        self.root = root
        self.project_id = project_id
        self.dir = root / project_id
        self.project_file = self.dir / "project.json"
        self.audio_analysis = self.dir / "analysis" / "audio_analysis.json"
        self.lyrics_analysis = self.dir / "analysis" / "lyrics_analysis.json"
        self.musical_events = self.dir / "analysis" / "musical_events.json"
        self.scenes_file = self.dir / "planning" / "scenes.json"
        self.visual_context_file = self.dir / "planning" / "visual_context.json"
        self.images_dir = self.dir / "assets" / "images"
        self.videos_dir = self.dir / "assets" / "videos"
        self.thumbnails_dir = self.dir / "assets" / "thumbnails"
        self.depth_dir = self.dir / "assets" / "depth"
        self.cache_dir = self.dir / "cache"
        self.output_dir = self.dir / "output"
        self.logs_dir = self.dir / "logs"
        self.jobs_dir = self.logs_dir / "jobs"
        self.input_dir = self.dir / "input"

    def ensure(self) -> "ProjectPaths":
        for subdir in PROJECT_SUBDIRS:
            (self.dir / subdir).mkdir(parents=True, exist_ok=True)
        return self

    def rel(self, path: Path | str) -> str:
        """Path relative to the project directory (internal storage format)."""
        target = Path(path).resolve()
        try:
            return target.relative_to(self.dir.resolve()).as_posix()
        except ValueError:
            return str(target)

    def files_rel(self, path: Path | str | None) -> str | None:
        """Path relative to the shared FILES_ROOT (public API format)."""
        if path is None:
            return None
        target = Path(path).resolve()
        try:
            return target.relative_to(_files_root().resolve()).as_posix()
        except ValueError:
            return self.rel(target)

    def to_project_rel(self, path: str | Path | None) -> str | None:
        """Normalise a project-relative, files-relative or absolute path."""
        if path is None:
            return None
        raw = str(path).strip()
        if not raw:
            return None
        candidate = Path(raw)
        if candidate.is_absolute():
            return self.rel(candidate)
        project_candidate = (self.dir / candidate)
        if project_candidate.exists():
            return self.rel(project_candidate)
        files_candidate = _files_root() / candidate
        if files_candidate.exists():
            return self.rel(files_candidate)
        return raw.replace("\\", "/")

    def abs(self, relative: str | Path) -> Path:
        raw = str(relative).replace("\\", "/")
        # Public APIs use files-relative paths such as
        # ``video/projects/<id>/assets/images/x.png``. Accept those as well as
        # the internal project-relative form (``assets/images/x.png``).
        if not Path(raw).is_absolute():
            prefix = f"video/projects/{self.project_id}/"
            if raw.startswith(prefix):
                return resolve_under(_files_root(), raw)
        return resolve_under(self.dir, relative)

    def exists(self) -> bool:
        return self.project_file.is_file()


class ProjectStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def paths(self, project_id: str) -> ProjectPaths:
        if not re.match(r"^[a-z0-9][a-z0-9._-]{0,80}$", project_id or ""):
            raise ProjectNotFound(f"Invalid project id: {project_id!r}")
        return ProjectPaths(self.root, project_id)

    def create(self, project: Project) -> Project:
        paths = self.paths(project.id)
        with self._lock:
            if paths.exists():
                raise StorageError(f"Project {project.id} already exists")
            paths.ensure()
            self.save(project)
        return project

    def load(self, project_id: str) -> Project:
        paths = self.paths(project_id)
        data = read_json(paths.project_file)
        if data is None:
            raise ProjectNotFound(f"Project not found: {project_id}")
        try:
            return Project.model_validate(data)
        except Exception as exc:
            raise StorageError(f"Invalid project metadata for {project_id}: {exc}") from exc

    def save(self, project: Project) -> Project:
        paths = self.paths(project.id)
        paths.ensure()
        project.updated_at = utcnow()
        with self._lock:
            atomic_write_json(paths.project_file, project.model_dump(mode="json"))
        return project

    def patch(self, project_id: str, **updates: Any) -> Project:
        project = self.load(project_id)
        for key, value in updates.items():
            setattr(project, key, value)
        return self.save(project)

    def list(self) -> list[ProjectSummary]:
        projects: list[ProjectSummary] = []
        if not self.root.exists():
            return projects
        for child in self.root.iterdir():
            if not child.is_dir() or not (child / "project.json").is_file():
                continue
            try:
                projects.append(project_summary(self.load(child.name)))
            except Exception:
                continue
        projects.sort(key=lambda item: item.updated_at, reverse=True)
        return projects

    def delete(self, project_id: str) -> None:
        paths = self.paths(project_id)
        if not paths.dir.exists():
            raise ProjectNotFound(f"Project not found: {project_id}")
        shutil.rmtree(paths.dir)

    def all_projects(self) -> list[Project]:
        result: list[Project] = []
        for child in self.root.iterdir() if self.root.exists() else []:
            if child.is_dir() and (child / "project.json").is_file():
                try:
                    result.append(self.load(child.name))
                except Exception:
                    continue
        return result


class AssetCache:
    """A small, file-backed cache manifest scoped to one project."""

    def __init__(self, paths: ProjectPaths):
        self.paths = paths
        self.manifest_path = paths.cache_dir / "manifest.json"
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
            target = self.paths.dir / entry.get("path", "")
            if not target.is_file():
                self._load()["entries"].pop(key, None)
                return None
            return dict(entry)

    def put(self, key: str, relative_path: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            entry = {
                "path": relative_path,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "metadata": metadata or {},
            }
            self._load()["entries"][key] = entry
            atomic_write_json(self.manifest_path, self._data)
            return dict(entry)

    def invalidate(self, key: str) -> None:
        with self._lock:
            if self._load()["entries"].pop(key, None) is not None:
                atomic_write_json(self.manifest_path, self._data)

    def invalidate_scene(self, scene_id: int) -> None:
        prefix = f"scene_{scene_id:03d}"
        with self._lock:
            entries = self._load()["entries"]
            keys = [key for key, value in entries.items() if value.get("metadata", {}).get("scene_id") == scene_id]
            for key in keys:
                entries.pop(key, None)
            if keys:
                atomic_write_json(self.manifest_path, self._data)
            del prefix

    def clear(self) -> None:
        with self._lock:
            self._data = {"version": 1, "entries": {}}
            atomic_write_json(self.manifest_path, self._data)


def project_relative(paths: ProjectPaths, path: Path | str | None) -> str | None:
    if path is None:
        return None
    return paths.rel(path)
