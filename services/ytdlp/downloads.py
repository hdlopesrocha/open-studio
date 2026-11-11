"""yt-dlp execution, option mapping and progress parsing."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from openstudio_common import (
    JobCancelled,
    MediaError,
    file_info,
    relative_path,
    resolve_path,
    run_process,
)

log = logging.getLogger("ytdlp.downloads")

YTDLP = shutil.which("yt-dlp") or "yt-dlp"
ProgressReporter = Callable[[float | None, str | None, str | None], Awaitable[None]]
CancelCheck = Callable[[], Awaitable[None]]

PLAYLIST_RE = re.compile(r"\[download\]\s+Downloading item\s+(\d+)\s+of\s+(\d+)")
PERCENT_RE = re.compile(r"(?:PROGRESS\s+|\[download\]\s+)(\d+(?:\.\d+)?)%")
DESTINATION_RE = re.compile(r"\[download\]\s+Destination:\s+(.+)$")
POSTPROCESS_RE = re.compile(r"^\[([A-Za-z0-9_]+)\]\s+(.*)$")

PROCESSES: dict[str, asyncio.subprocess.Process] = {}


class YtDlpRun:
    def __init__(self, code: int, stdout: str, stderr: str, elapsed: float) -> None:
        self.code = code
        self.stdout = stdout
        self.stderr = stderr
        self.elapsed = elapsed


def validate_url(url: Any) -> str:
    text = str(url or "").strip()
    if not text:
        raise ValueError("url is required")
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url must be an http(s) URL")
    return text


def cookie_path(raw: Any) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    path = resolve_path(text)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(text)
    return path


def cookie_browser(raw: Any) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if not re.match(r"^[A-Za-z0-9_+.:-]+$", text):
        raise ValueError("cookies_from_browser contains invalid characters")
    return text


def output_template(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return "%(title).200B [%(id)s].%(ext)s"
    if "\x00" in text:
        raise ValueError("output_template cannot contain null bytes")
    if os.path.isabs(text):
        raise ValueError("output_template must be relative")
    parts = Path(text).parts
    if any(part == ".." for part in parts):
        raise ValueError("output_template cannot contain '..'")
    return text


def archive_path(raw: Any) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    path = resolve_path(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _version() -> str:
    try:
        import subprocess

        result = subprocess.run([YTDLP, "--version"], capture_output=True, text=True, timeout=10, check=False)
        text = (result.stdout or result.stderr).strip()
        return text.splitlines()[0] if text else "unknown"
    except Exception:  # noqa: BLE001
        return "unavailable"


@lru_cache(maxsize=1)
def version() -> str:
    return _version()


def _extractor_count() -> int:
    try:
        import subprocess

        result = subprocess.run([YTDLP, "--list-extractors"], capture_output=True, text=True, timeout=30, check=False)
        return len([line for line in (result.stdout or "").splitlines() if line.strip() and not line.startswith("[")])
    except Exception:  # noqa: BLE001
        return 0


@lru_cache(maxsize=1)
def extractor_count() -> int:
    return _extractor_count()


def _add_header_args(args: list[str], value: Any) -> None:
    if not value:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            text = str(item)
            if "\n" in text or "\r" in text:
                raise ValueError("header values cannot contain newlines")
            args += ["--add-header", f"{key}: {text}"]
    elif isinstance(value, list):
        for item in value:
            text = str(item)
            if "\n" in text or "\r" in text:
                raise ValueError("header values cannot contain newlines")
            args += ["--add-header", text]
    else:
        raise ValueError("headers must be an object or a list of strings")


def _add_extractor_args(args: list[str], value: Any) -> None:
    if not value:
        return
    if isinstance(value, dict):
        parts: list[str] = []
        for key, item in value.items():
            if isinstance(item, list):
                item_text = ",".join(str(entry) for entry in item)
            elif isinstance(item, dict):
                item_text = ";".join(f"{k}={v}" for k, v in item.items())
            else:
                item_text = str(item)
            parts.append(f"{key}:{item_text}")
        if parts:
            args += ["--extractor-args", ";".join(parts)]
    elif isinstance(value, list):
        for item in value:
            args += ["--extractor-args", str(item)]
    else:
        raise ValueError("extractor_args must be an object or list")


def _add_sponsorblock(args: list[str], value: Any, flag: str) -> None:
    if value is None or value is False or value == "":
        return
    if value is True:
        categories = "all"
    elif isinstance(value, list):
        categories = ",".join(str(item) for item in value)
    else:
        categories = str(value)
    args += [flag, categories]


def common_args(payload: dict[str, Any]) -> list[str]:
    """Options shared by info, search, playlist and download commands."""
    args = ["--newline", "--no-colors", "--no-warnings", "--ignore-config"]
    if shutil.which("deno"):
        args += ["--js-runtimes", "deno"]
    if payload.get("proxy"):
        args += ["--proxy", str(payload["proxy"])]
    cookies = cookie_path(payload.get("cookies_path"))
    if cookies is not None:
        args += ["--cookies", str(cookies)]
    browser = cookie_browser(payload.get("cookies_from_browser"))
    if browser:
        args += ["--cookies-from-browser", browser]
    if payload.get("user_agent"):
        args += ["--user-agent", str(payload["user_agent"])]
    if payload.get("referer"):
        args += ["--referer", str(payload["referer"])]
    _add_header_args(args, payload.get("headers"))
    _add_extractor_args(args, payload.get("extractor_args"))
    if payload.get("no_check_certificate"):
        args += ["--no-check-certificates"]
    if payload.get("geo_bypass") is True:
        args += ["--geo-bypass"]
    elif payload.get("geo_bypass") is False:
        args += ["--no-geo-bypass"]
    if payload.get("source_address"):
        args += ["--source-address", str(payload["source_address"])]
    if payload.get("socket_timeout") is not None:
        args += ["--socket-timeout", str(payload["socket_timeout"])]
    if payload.get("retries") is not None:
        args += ["--retries", str(payload["retries"])]
    if payload.get("fragment_retries") is not None:
        args += ["--fragment-retries", str(payload["fragment_retries"])]
    if payload.get("concurrent_fragments") is not None:
        args += ["--concurrent-fragments", str(payload["concurrent_fragments"])]
    if payload.get("rate_limit"):
        args += ["--limit-rate", str(payload["rate_limit"])]
    if payload.get("sleep_interval") is not None:
        args += ["--sleep-interval", str(payload["sleep_interval"])]
    if payload.get("max_sleep_interval") is not None:
        args += ["--max-sleep-interval", str(payload["max_sleep_interval"])]
    if payload.get("prefer_free_formats"):
        args += ["--prefer-free-formats"]
    if payload.get("dateafter"):
        args += ["--dateafter", str(payload["dateafter"])]
    if payload.get("datebefore"):
        args += ["--datebefore", str(payload["datebefore"])]
    if payload.get("match_filter"):
        args += ["--match-filter", str(payload["match_filter"])]
    if payload.get("max_downloads") is not None:
        args += ["--max-downloads", str(payload["max_downloads"])]
    if payload.get("playlist_items"):
        items = payload["playlist_items"]
        if isinstance(items, list):
            items = ",".join(str(item) for item in items)
        args += ["--playlist-items", str(items)]
    if payload.get("playlist") is True:
        args += ["--yes-playlist"]
    elif payload.get("playlist") is False:
        args += ["--no-playlist"]
    _add_sponsorblock(args, payload.get("sponsorblock"), "--sponsorblock-mark")
    _add_sponsorblock(args, payload.get("sponsorblock_remove"), "--sponsorblock-remove")
    return args


def download_args(
    payload: dict[str, Any],
    *,
    outdir: Path,
    paths_file: Path,
    meta_file: Path,
) -> list[str]:
    url = validate_url(payload.get("url"))
    args = common_args(payload)
    args += [
        "--paths",
        f"home:{outdir}",
        "--output",
        output_template(payload.get("output_template")),
        "--print-to-file",
        "after_move:filepath",
        str(paths_file),
        "--print-to-file",
        'after_move:{"title":%(title)j,"duration":%(duration)j,"thumbnail":%(thumbnail)j,'
        '"webpage_url":%(webpage_url)j,"extractor":%(extractor)j,"id":%(id)j,'
        '"uploader":%(uploader)j,"description":%(description)j}',
        str(meta_file),
        "--progress",
        "--progress-template",
        "download:PROGRESS %(progress._percent_str)s %(progress._speed_str)s %(progress._eta_str)s",
    ]
    fmt = str(payload.get("format") or "bv*+ba/b")
    args += ["--format", fmt]
    if payload.get("format_sort"):
        sort = payload["format_sort"]
        if isinstance(sort, list):
            sort = ",".join(str(item) for item in sort)
        args += ["--format-sort", str(sort)]
    if payload.get("merge_output_format"):
        args += ["--merge-output-format", str(payload["merge_output_format"])]
    if payload.get("extract_audio"):
        args += ["--extract-audio"]
        if payload.get("audio_format"):
            args += ["--audio-format", str(payload["audio_format"])]
        if payload.get("audio_quality") is not None:
            args += ["--audio-quality", str(payload["audio_quality"])]
    if payload.get("subtitles"):
        args += ["--write-subs"]
        if not isinstance(payload.get("subtitles"), bool):
            langs = payload["subtitles"]
            if isinstance(langs, list):
                langs = ",".join(str(item) for item in langs)
            args += ["--sub-langs", str(langs)]
    if payload.get("write_subs"):
        args += ["--write-subs"]
    if payload.get("subtitle_langs"):
        langs = payload["subtitle_langs"]
        if isinstance(langs, list):
            langs = ",".join(str(item) for item in langs)
        args += ["--sub-langs", str(langs)]
    if payload.get("embed_subs"):
        args += ["--embed-subs"]
        if "--write-subs" not in args:
            args += ["--write-subs"]
    if payload.get("convert_subs"):
        args += ["--convert-subs", str(payload["convert_subs"])]
    if payload.get("write_thumbnail", True) is not False:
        args += ["--write-thumbnail"]
        if payload.get("convert_thumbnail", True) is not False:
            args += ["--convert-thumbnails", "jpg"]
    if payload.get("embed_thumbnail"):
        args += ["--embed-thumbnail"]
    if payload.get("write_info_json"):
        args += ["--write-info-json"]
    if payload.get("write_description"):
        args += ["--write-description"]
    if payload.get("write_comments"):
        args += ["--write-comments"]
    if payload.get("remux"):
        args += ["--remux-video", str(payload["remux"])]
    if payload.get("recode"):
        args += ["--recode-video", str(payload["recode"])]
    archive = archive_path(payload.get("archive_path") or payload.get("download_archive"))
    if archive is not None:
        args += ["--download-archive", str(archive)]
    if "keep_video" in payload:
        args += ["--keep-video" if payload.get("keep_video") else "--no-keep-video"]
    if payload.get("no_part"):
        args += ["--no-part"]
    if "continue_dl" in payload:
        args += ["--continue" if payload.get("continue_dl") else "--no-continue"]
    args += ["--", url]
    return args


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.terminate()
        except ProcessLookupError:
            return
    try:
        await asyncio.wait_for(process.wait(), timeout=4.0)
        return
    except asyncio.TimeoutError:
        pass
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except ProcessLookupError:
            pass


async def run_download(
    args: list[str],
    *,
    job_id: str,
    report: ProgressReporter | None,
    check: CancelCheck | None,
    timeout: float | None,
) -> YtDlpRun:
    command = [YTDLP, *args]
    log.info("yt-dlp job=%s start: %s", job_id, " ".join(command))
    if report:
        await report(1.0, "Starting", "Starting yt-dlp")
    started = time.monotonic()
    deadline = started + timeout if timeout else None
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    PROCESSES[job_id] = process
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    current_item = 1
    total_items = 1
    max_percent = 0.0
    last_report = 0.0
    last_stage = ""

    async def emit(progress: float, stage: str, message: str | None = None) -> None:
        nonlocal last_report, last_stage
        now = time.monotonic()
        if now - last_report < 0.8 and stage == last_stage and progress < 99:
            return
        last_report = now
        last_stage = stage
        if report:
            try:
                await report(round(min(99.0, progress), 2), stage, message)
            except Exception:  # noqa: BLE001
                log.debug("progress callback failed", exc_info=True)

    async def handle_line(line: str) -> None:
        nonlocal current_item, total_items, max_percent
        if not line:
            return
        playlist_match = PLAYLIST_RE.search(line)
        if playlist_match:
            current_item = int(playlist_match.group(1))
            total_items = max(1, int(playlist_match.group(2)))
            await emit(2.0, "Downloading", f"Item {current_item} of {total_items}")
            return
        destination = DESTINATION_RE.search(line)
        if destination:
            await emit(max(2.0, 2.0 + max_percent * 0.05), "Downloading", "Downloading media")
            return
        percent_match = PERCENT_RE.search(line)
        if percent_match:
            percent = float(percent_match.group(1))
            max_percent = max(max_percent, percent)
            overall = ((current_item - 1) + percent / 100.0) / total_items * 88.0 + 2.0
            await emit(overall, "Downloading", f"{percent:.1f}%")
            return
        postprocess = POSTPROCESS_RE.match(line)
        if postprocess:
            stage_name = postprocess.group(1)
            if stage_name.lower() not in {"download", "youtube", "generic", "info", "debug"}:
                await emit(92.0, "Post-processing", f"{stage_name}: {postprocess.group(2)[:120]}")
            return
        if "has already been downloaded" in line or "Downloading item" in line:
            await emit(max(88.0, 2.0 + max_percent * 0.86), "Downloading", line[:160])

    async def pump(stream, sink: list[str]) -> None:
        while True:
            raw = await stream.readline()
            if not raw:
                break
            text = raw.decode("utf-8", "replace").rstrip()
            if not text:
                continue
            sink.append(text)
            if len(sink) > 4000:
                del sink[:1000]
            await handle_line(text)

    stdout_task = asyncio.create_task(pump(process.stdout, stdout_lines))  # type: ignore[arg-type]
    stderr_task = asyncio.create_task(pump(process.stderr, stderr_lines))  # type: ignore[arg-type]
    cancelled = False
    timed_out = False
    try:
        while True:
            try:
                await asyncio.wait_for(process.wait(), timeout=0.35)
                break
            except asyncio.TimeoutError:
                pass
            if check is not None:
                try:
                    await check()
                except JobCancelled:
                    cancelled = True
                    await emit(2.0, "Cancelling", "Stopping yt-dlp")
                    await _terminate(process)
                    raise
            if deadline is not None and time.monotonic() > deadline:
                timed_out = True
                await _terminate(process)
                break
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        await process.wait()
    finally:
        if process.returncode is None:
            await _terminate(process)
        PROCESSES.pop(job_id, None)
        for task in (stdout_task, stderr_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

    elapsed = time.monotonic() - started
    if cancelled:
        raise JobCancelled("Cancelled by the user")
    if timed_out:
        raise MediaError(f"yt-dlp exceeded the {timeout:.0f}s timeout")
    if process.returncode != 0:
        tail = "\n".join((stderr_lines + stdout_lines)[-25:])
        raise MediaError(tail or "yt-dlp failed")
    if report:
        await report(99.0, "Finalizing", "Collecting downloaded files")
    return YtDlpRun(int(process.returncode or 0), "\n".join(stdout_lines), "\n".join(stderr_lines), round(elapsed, 2))


def _read_json_lines(path: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not path.exists():
        return items
    try:
        for line in path.read_text("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            line = re.sub(r":NA(?=[,}])", ":null", line)
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                items.append(value)
    except OSError:
        pass
    return items


def _read_info_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def collect_outputs(outdir: Path, paths_file: Path, meta_file: Path) -> tuple[list[dict[str, Any]], dict[str, Any], Path | None]:
    candidates: list[Path] = []
    if paths_file.exists():
        for line in paths_file.read_text("utf-8").splitlines():
            text = line.strip()
            if not text or text == "NA":
                continue
            path = Path(text)
            if not path.is_absolute():
                path = outdir / path
            if path.exists() and path.is_file():
                candidates.append(path)
    if outdir.exists():
        for root, dirs, filenames in os.walk(outdir):
            dirs[:] = [name for name in dirs if not name.startswith(".")]
            for name in filenames:
                if name.startswith("."):
                    continue
                if name.endswith((".part", ".ytdl", ".temp", ".frag")):
                    continue
                candidates.append(Path(root) / name)
    unique: dict[str, Path] = {}
    for path in candidates:
        try:
            resolved = path.resolve()
            if resolved != outdir.resolve() and outdir.resolve() not in resolved.parents:
                continue
        except OSError:
            continue
        unique[str(resolved)] = resolved
    files = sorted(unique.values(), key=lambda path: (path.name.endswith(".info.json"), path.name.lower()))
    descriptors: list[dict[str, Any]] = []
    info_json: Path | None = None
    for path in files:
        info = file_info(path)
        descriptor = {
            "path": info["path"],
            "name": info["name"],
            "kind": info["kind"],
            "mime": info["mime"],
            "size": info["size"],
            "modified": info["modified"],
        }
        if path.name.endswith(".info.json"):
            info_json = path
            descriptor["kind"] = "document"
            descriptor["mime"] = "application/json"
        descriptors.append(descriptor)
    metadata: dict[str, Any] = {}
    meta_items = _read_json_lines(meta_file)
    if meta_items:
        first = meta_items[0]
        metadata = {
            "title": first.get("title") if first.get("title") not in (None, "NA") else None,
            "duration": first.get("duration") if first.get("duration") not in (None, "NA") else None,
            "thumbnail": first.get("thumbnail") if first.get("thumbnail") not in (None, "NA") else None,
            "webpage_url": first.get("webpage_url") if first.get("webpage_url") not in (None, "NA") else None,
            "extractor": first.get("extractor") if first.get("extractor") not in (None, "NA") else None,
            "id": first.get("id") if first.get("id") not in (None, "NA") else None,
            "uploader": first.get("uploader") if first.get("uploader") not in (None, "NA") else None,
        }
        if len(meta_items) > 1:
            metadata["items"] = meta_items
    if info_json is not None:
        raw = _read_info_json(info_json)
        for key in ("title", "duration", "thumbnail", "webpage_url", "extractor", "id", "uploader", "description"):
            if metadata.get(key) in (None, "NA") and raw.get(key) not in (None, "NA"):
                metadata[key] = raw.get(key)
        metadata["info_json"] = relative_path(info_json)
        if raw.get("entries") is not None:
            metadata["entry_count"] = len(raw.get("entries") or [])
    return descriptors, metadata, info_json


async def execute_download(    payload: dict[str, Any],
    *,
    job_id: str,
    workdir: Path,
    report: ProgressReporter | None,
    check: CancelCheck | None,
) -> dict[str, Any]:
    outdir_raw = str(payload.get("output_path") or "").strip()
    outdir = resolve_path(outdir_raw) if outdir_raw else workdir
    if outdir.exists() and outdir.is_file():
        raise ValueError("output_path must be a directory")
    outdir.mkdir(parents=True, exist_ok=True)
    state = workdir / ".state"
    state.mkdir(parents=True, exist_ok=True)
    paths_file = state / "paths.txt"
    meta_file = state / "meta.jsonl"
    for path in (paths_file, meta_file):
        path.unlink(missing_ok=True)
    args = download_args(payload, outdir=outdir, paths_file=paths_file, meta_file=meta_file)
    timeout = payload.get("timeout")
    if timeout is None:
        timeout = float(os.getenv("YTDLP_JOB_TIMEOUT", "86400"))
    else:
        timeout = float(timeout)
        if timeout <= 0:
            raise ValueError("timeout must be positive")
    run = await run_download(args, job_id=job_id, report=report, check=check, timeout=timeout)
    descriptors, metadata, info_json = collect_outputs(outdir, paths_file, meta_file)
    if not descriptors:
        raise MediaError("yt-dlp completed but no downloaded files were found")
    thumbnail = await ensure_thumbnail(outdir, descriptors, metadata)
    if thumbnail is not None:
        metadata["thumbnail_path"] = relative_path(thumbnail)
        metadata["thumbnail"] = relative_path(thumbnail)
        if not any(item.get("path") == relative_path(thumbnail) for item in descriptors):
            info = file_info(thumbnail)
            descriptors.append({key: info[key] for key in ("path", "name", "kind", "mime", "size", "modified")})
    metadata["output_dir"] = relative_path(outdir)
    metadata["download_seconds"] = run.elapsed
    message = f"Downloaded {len([item for item in descriptors if item['kind'] in {'video', 'audio', 'image', 'subtitle'}])} file(s)"
    return {
        "message": metadata.get("title") and f"Downloaded {metadata['title']}" or message,
        "files": descriptors,
        "data": {"operation": "download", **metadata, "info_json": relative_path(info_json) if info_json else None},
    }




def _looks_like_thumbnail(path: Path) -> bool:
    return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".avif"} and "thumb" in path.name.lower()


async def ensure_thumbnail(outdir: Path, descriptors: list[dict[str, Any]], metadata: dict[str, Any]) -> Path | None:
    """Return a real thumbnail file, extracting a frame when yt-dlp did not write one."""
    for descriptor in descriptors:
        path = resolve_path(descriptor["path"])
        if path.is_file() and (descriptor.get("kind") == "image" or _looks_like_thumbnail(path)):
            return path
    for descriptor in descriptors:
        if descriptor.get("kind") != "video":
            continue
        source = resolve_path(descriptor["path"])
        if not source.is_file():
            continue
        target = outdir / "thumbnail.jpg"
        duration = float(metadata.get("duration") or 0)
        timestamp = min(2.0, max(0.0, duration * 0.1)) if duration > 0 else 0.0
        code, _, err = await run_process(
            ["ffmpeg", "-hide_banner", "-y", "-ss", f"{timestamp:.3f}", "-i", str(source), "-frames:v", "1", "-q:v", "2", str(target)],
            timeout=120,
        )
        if code == 0 and target.is_file() and target.stat().st_size > 0:
            return target
        if target.exists():
            target.unlink(missing_ok=True)
        return None
    return None

def sanitize_info(info: dict[str, Any], *, include_entries: bool = True) -> dict[str, Any]:
    formats: list[dict[str, Any]] = []
    for fmt in info.get("formats") or []:
        if not isinstance(fmt, dict):
            continue
        formats.append(
            {
                "format_id": fmt.get("format_id"),
                "ext": fmt.get("ext"),
                "resolution": fmt.get("resolution"),
                "width": fmt.get("width"),
                "height": fmt.get("height"),
                "fps": fmt.get("fps"),
                "vcodec": fmt.get("vcodec"),
                "acodec": fmt.get("acodec"),
                "abr": fmt.get("abr"),
                "vbr": fmt.get("vbr"),
                "tbr": fmt.get("tbr"),
                "filesize": fmt.get("filesize"),
                "filesize_approx": fmt.get("filesize_approx"),
                "format_note": fmt.get("format_note"),
                "protocol": fmt.get("protocol"),
                "container": fmt.get("container"),
                "quality": fmt.get("quality"),
                "has_drm": fmt.get("has_drm"),
            }
        )
    result: dict[str, Any] = {
        "id": info.get("id"),
        "title": info.get("title"),
        "description": info.get("description"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader"),
        "uploader_id": info.get("uploader_id"),
        "channel": info.get("channel"),
        "channel_url": info.get("channel_url"),
        "webpage_url": info.get("webpage_url"),
        "original_url": info.get("original_url"),
        "thumbnail": info.get("thumbnail"),
        "thumbnails": info.get("thumbnails"),
        "extractor": info.get("extractor"),
        "extractor_key": info.get("extractor_key"),
        "upload_date": info.get("upload_date"),
        "timestamp": info.get("timestamp"),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "comment_count": info.get("comment_count"),
        "age_limit": info.get("age_limit"),
        "live_status": info.get("live_status"),
        "is_live": info.get("is_live"),
        "availability": info.get("availability"),
        "format_id": info.get("format_id"),
        "format": info.get("format"),
        "ext": info.get("ext"),
        "resolution": info.get("resolution"),
        "width": info.get("width"),
        "height": info.get("height"),
        "fps": info.get("fps"),
        "vcodec": info.get("vcodec"),
        "acodec": info.get("acodec"),
        "filesize": info.get("filesize"),
        "filesize_approx": info.get("filesize_approx"),
        "subtitles": sorted((info.get("subtitles") or {}).keys()),
        "automatic_captions": sorted((info.get("automatic_captions") or {}).keys()),
        "formats": formats,
        "format_count": len(formats),
        "entries": [],
    }
    if include_entries and isinstance(info.get("entries"), list):
        result["entries"] = [
            sanitize_info(entry, include_entries=False)
            for entry in info["entries"][:500]
            if isinstance(entry, dict)
        ]
        result["entry_count"] = info.get("playlist_count") or len(info["entries"])
    return {key: value for key, value in result.items() if value is not None or key in {"entries", "formats"}}


def version() -> str:
    return _version()


def extractor_count() -> int:
    return _extractor_count()
