"""Shared file explorer API.

Every service mounts the same volume and writes through the same relative-path
namespace exposed here. The file explorer, media players and file pickers in the
Vue app all use this service.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from openstudio_common import (
    INTERNAL_TOKEN,
    FILES_ROOT,
    atomic_write_text,
    create_service_app,
    ensure_storage,
    extract_zip,
    file_info,
    human_size,
    list_directory,
    parse_range,
    read_json,
    relative_path,
    remove_path,
    resolve_path,
    sanitize_name,
    search_files,
    unique_path,
    zip_paths,
)

router = APIRouter(prefix="/api/files", tags=["files"])


def verify(token: str) -> None:
    if token != INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid internal token")


def info(path: Path) -> dict[str, Any]:
    data = file_info(path)
    data["size_label"] = human_size(data["size"])
    if path.is_dir():
        try:
            data["children"] = len([p for p in path.iterdir() if not p.name.startswith(".")])
        except OSError:
            data["children"] = 0
    return data


@router.get("")
@router.get("/list")
async def list_files(
    path: str = "",
    q: str = "",
    kind: str = "",
    limit: int = Query(2000, ge=1, le=10000),
    x_internal_token: str = Header(default=""),
) -> dict[str, Any]:
    verify(x_internal_token)
    target = resolve_path(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Folder not found")
    if not target.is_dir():
        return {"path": relative_path(target), "items": [info(target)], "parent": None}
    items = list_directory(path, q, kind, limit)
    parent = relative_path(target.parent) if target != FILES_ROOT else None
    return {
        "path": relative_path(target),
        "parent": parent,
        "items": items,
        "count": len(items),
        "breadcrumbs": _breadcrumbs(relative_path(target)),
    }


def _breadcrumbs(rel: str) -> list[dict[str, str]]:
    parts = [p for p in rel.split("/") if p]
    crumbs = [{"name": "Files", "path": ""}]
    current = ""
    for part in parts:
        current = f"{current}/{part}".strip("/")
        crumbs.append({"name": part, "path": current})
    return crumbs


@router.get("/tree")
async def tree(
    path: str = "",
    depth: int = Query(2, ge=0, le=8),
    x_internal_token: str = Header(default=""),
) -> dict[str, Any]:
    verify(x_internal_token)
    root = resolve_path(path)
    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=404, detail="Folder not found")

    def walk(node: Path, level: int) -> list[dict[str, Any]]:
        if level > depth:
            return []
        children: list[dict[str, Any]] = []
        for child in sorted(node.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if child.name.startswith("."):
                continue
            entry = info(child)
            if child.is_dir() and level < depth:
                entry["children"] = walk(child, level + 1)
            children.append(entry)
        return children

    return {"path": relative_path(root), "children": walk(root, 0)}


@router.get("/stat")
async def stat(path: str, x_internal_token: str = Header(default="")) -> dict[str, Any]:
    verify(x_internal_token)
    target = resolve_path(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return info(target)


@router.get("/search")
async def search(
    q: str,
    kind: str = "",
    limit: int = Query(300, ge=1, le=2000),
    x_internal_token: str = Header(default=""),
) -> dict[str, Any]:
    verify(x_internal_token)
    if not q.strip():
        return {"items": [], "query": q}
    return {"items": search_files(q, kind, limit), "query": q}


@router.get("/kinds")
async def kinds(x_internal_token: str = Header(default="")) -> dict[str, Any]:
    verify(x_internal_token)
    summary: dict[str, dict[str, Any]] = {}
    for top in sorted(FILES_ROOT.iterdir()):
        if not top.is_dir() or top.name.startswith("."):
            continue
        files = 0
        size = 0
        for base, dirs, names in os.walk(top):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in names:
                if name.startswith("."):
                    continue
                try:
                    size += (Path(base) / name).stat().st_size
                    files += 1
                except OSError:
                    pass
        summary[top.name] = {"files": files, "size": size, "size_label": human_size(size)}
    total = shutil.disk_usage(FILES_ROOT)
    return {
        "root": str(FILES_ROOT),
        "kinds": summary,
        "total_files": sum(v["files"] for v in summary.values()),
        "total_size": sum(v["size"] for v in summary.values()),
        "disk": {"total": total.total, "used": total.used, "free": total.free, "free_label": human_size(total.free)},
    }


@router.post("/mkdir")
async def mkdir(payload: dict[str, Any], x_internal_token: str = Header(default="")) -> dict[str, Any]:
    verify(x_internal_token)
    path = payload.get("path") or ""
    name = sanitize_name(payload.get("name") or "New folder")
    target = resolve_path(path, name)
    target.mkdir(parents=True, exist_ok=False)
    return info(target)


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    path: str = Form("uploads"),
    overwrite: bool = Form(False),
    x_internal_token: str = Header(default=""),
) -> dict[str, Any]:
    verify(x_internal_token)
    directory = resolve_path(path)
    directory.mkdir(parents=True, exist_ok=True)
    name = sanitize_name(file.filename or "upload")
    target = directory / name
    if target.exists() and not overwrite:
        target = unique_path(directory, name, suffix=Path(name).suffix)
    suffix = ".part"
    temporary = target.with_name(target.name + suffix)
    size = 0
    try:
        with temporary.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                handle.write(chunk)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {"file": info(target), "size": size}


@router.post("/write")
async def write(payload: dict[str, Any], x_internal_token: str = Header(default="")) -> dict[str, Any]:
    verify(x_internal_token)
    target = resolve_path(payload.get("path") or "")
    if target.is_dir():
        raise HTTPException(status_code=422, detail="Path is a folder")
    atomic_write_text(target, str(payload.get("content") or ""))
    return info(target)


@router.get("/read")
async def read(
    path: str,
    max_chars: int = Query(200_000, ge=1, le=2_000_000),
    x_internal_token: str = Header(default=""),
) -> dict[str, Any]:
    verify(x_internal_token)
    target = resolve_path(path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    data = target.read_bytes()[: max_chars * 4]
    text = data.decode("utf-8", "replace")
    truncated = len(text) > max_chars or target.stat().st_size > len(data)
    return {"path": relative_path(target), "content": text[:max_chars], "truncated": truncated, "size": target.stat().st_size}


@router.post("/rename")
async def rename(payload: dict[str, Any], x_internal_token: str = Header(default="")) -> dict[str, Any]:
    verify(x_internal_token)
    source = resolve_path(payload.get("path") or "")
    if not source.exists():
        raise HTTPException(status_code=404, detail="File not found")
    new_name = sanitize_name(payload.get("new_name") or "")
    if not new_name:
        raise HTTPException(status_code=422, detail="new_name is required")
    target = source.parent / new_name
    if target.exists() and target != source:
        raise HTTPException(status_code=409, detail="A file with that name already exists")
    source.rename(target)
    return info(target)


@router.post("/move")
async def move(payload: dict[str, Any], x_internal_token: str = Header(default="")) -> dict[str, Any]:
    verify(x_internal_token)
    paths = payload.get("paths") or ([payload["path"]] if payload.get("path") else [])
    destination = resolve_path(payload.get("destination") or "")
    if not destination.is_dir():
        raise HTTPException(status_code=422, detail="Destination must be a folder")
    copy = bool(payload.get("copy"))
    moved: list[dict[str, Any]] = []
    for raw in paths:
        source = resolve_path(raw)
        if not source.exists():
            continue
        target = destination / source.name
        if target.exists():
            target = unique_path(destination, source.name, suffix=source.suffix)
        if copy:
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
        else:
            shutil.move(str(source), str(target))
        moved.append(info(target))
    return {"items": moved, "copied": copy}


@router.delete("")
async def delete(payload: dict[str, Any], x_internal_token: str = Header(default="")) -> dict[str, Any]:
    verify(x_internal_token)
    paths = payload.get("paths") or ([payload["path"]] if payload.get("path") else [])
    removed: list[str] = []
    for raw in paths:
        target = resolve_path(raw)
        if target == FILES_ROOT:
            raise HTTPException(status_code=422, detail="Cannot delete the files root")
        if target.exists():
            remove_path(target)
            removed.append(raw)
    return {"removed": removed}


@router.post("/zip")
async def make_zip(payload: dict[str, Any], x_internal_token: str = Header(default="")) -> dict[str, Any]:
    verify(x_internal_token)
    paths = payload.get("paths") or []
    if not paths:
        raise HTTPException(status_code=422, detail="paths are required")
    destination = resolve_path(payload.get("output") or f"tmp/{sanitize_name(payload.get('name') or 'archive')}.zip")
    if destination.suffix.lower() != ".zip":
        destination = destination.with_suffix(".zip")
    if destination.exists():
        destination = unique_path(destination.parent, destination.name, suffix=".zip")
    resolved = [resolve_path(p) for p in paths]
    for item in resolved:
        if not item.exists():
            raise HTTPException(status_code=404, detail=f"Not found: {relative_path(item)}")
    await asyncio.to_thread(zip_paths, resolved, destination)
    return info(destination)


@router.post("/extract")
async def unzip(payload: dict[str, Any], x_internal_token: str = Header(default="")) -> dict[str, Any]:
    verify(x_internal_token)
    archive = resolve_path(payload.get("path") or "")
    if not archive.is_file() or zipfile.is_zipfile(archive) is False:
        raise HTTPException(status_code=422, detail="Not a ZIP archive")
    destination = resolve_path(payload.get("destination") or f"{archive.parent.relative_to(FILES_ROOT)}/{archive.stem}")
    names = await asyncio.to_thread(extract_zip, archive, destination)
    return {"path": relative_path(destination), "entries": names[:2000], "count": len(names)}


@router.get("/raw/{path:path}")
async def raw(path: str, request: Request, download: bool = False, x_internal_token: str = Header(default="")):
    verify(x_internal_token)
    target = resolve_path(path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return _range_response(target, request, download)


@router.get("/download")
async def download(path: str, request: Request, x_internal_token: str = Header(default="")):
    verify(x_internal_token)
    target = resolve_path(path)
    if target.is_dir():
        archive = resolve_path(f"tmp/download-{target.name}.zip")
        await asyncio.to_thread(zip_paths, [target], archive)
        return _range_response(archive, request, True)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return _range_response(target, request, True)


def _range_response(path: Path, request: Request, download: bool) -> StreamingResponse:
    size = path.stat().st_size
    mime = file_info(path)["mime"]
    start, end = 0, size - 1
    status = 200
    parsed = parse_range(request.headers.get("range"), size)
    if parsed:
        start, end = parsed
        status = 206
    length = max(0, end - start + 1)
    headers = {
        "Content-Length": str(length),
        "Content-Type": mime,
        "Accept-Ranges": "bytes",
    }
    if parsed:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Disposition"] = f"{'attachment' if download else 'inline'}; filename*=UTF-8''{path.name}"

    async def iterator() -> AsyncIterator[bytes]:
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = await asyncio.to_thread(handle.read, min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(iterator(), status_code=status, headers=headers, media_type=mime)


@router.get("/config")
async def config(x_internal_token: str = Header(default="")) -> dict[str, Any]:
    verify(x_internal_token)
    return {"root": str(FILES_ROOT), "kinds": [p.name for p in FILES_ROOT.iterdir() if p.is_dir()]}


app = create_service_app(
    "files",
    "Open Studio Files",
    "Shared storage and file explorer backend used by every service.",
    extra_routers=[router],
)
