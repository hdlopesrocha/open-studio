"""Open Studio yt-dlp service.

Wraps yt-dlp for metadata inspection, search, playlists and queued downloads
with ffmpeg post-processing, cookie support and live download progress.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

from openstudio_common import (
    JOBHUB_URL,
    JobRunner,
    MediaError,
    create_service_app,
    jobhub_headers,
    relative_path,
    resolve_path,
    run_process,
    utc_now,
)

from .downloads import (
    YTDLP,
    common_args,
    execute_download,
    extractor_count,
    sanitize_info,
    validate_url,
    version,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ytdlp")

VERSION = "1.0.0"
INFO_TIMEOUT = float(os.getenv("YTDLP_INFO_TIMEOUT", "120"))

runner = JobRunner("ytdlp")
router = APIRouter(prefix="/api/ytdlp", tags=["ytdlp"])


def option(
    name: str,
    type_: str,
    default: Any,
    description: str,
    *,
    enum: list[Any] | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"name": name, "type": type_, "default": default, "description": description}
    if enum:
        data["enum"] = enum
    if minimum is not None:
        data["minimum"] = minimum
    if maximum is not None:
        data["maximum"] = maximum
    return data


OPTIONS = [
    option("url", "string", "", "Media page URL.", ),
    option("format", "string", "bv*+ba/b", "yt-dlp format selector."),
    option("format_sort", "string|array", [], "Format sort fields, for example res:1080 or a list."),
    option("merge_output_format", "string", "mp4", "Container for merged video+audio.", enum=["mp4", "mkv", "webm"]),
    option("output_template", "string", "%(title).200B [%(id)s].%(ext)s", "yt-dlp output template relative to output_path."),
    option("subtitles", "boolean|array", False, "Write subtitles, optionally listing languages."),
    option("subtitle_langs", "string|array", "en", "Subtitle languages, comma-separated or a list."),
    option("embed_subs", "boolean", False, "Embed downloaded subtitles into the media file."),
    option("embed_thumbnail", "boolean", False, "Embed the thumbnail into the media file."),
    option("write_thumbnail", "boolean", False, "Write the thumbnail as a separate file."),
    option("write_info_json", "boolean", False, "Write the full yt-dlp metadata JSON."),
    option("write_description", "boolean", False, "Write the description to a text file."),
    option("write_comments", "boolean", False, "Write comments when the extractor provides them."),
    option("extract_audio", "boolean", False, "Extract audio with ffmpeg instead of keeping video."),
    option("audio_format", "string", "mp3", "Audio format for --extract-audio.", enum=["mp3", "wav", "flac", "aac", "opus", "vorbis", "m4a", "best"]),
    option("audio_quality", "string", "0", "Audio quality (0 is best for MP3/Vorbis)."),
    option("playlist", "boolean", True, "Download the whole playlist when the URL is a playlist."),
    option("playlist_items", "string|array", "", "Playlist item selection, for example 1-5,8."),
    option("match_filter", "string", "", "yt-dlp match filter expression."),
    option("dateafter", "string", "", "Only download uploads on/after YYYYMMDD."),
    option("datebefore", "string", "", "Only download uploads on/before YYYYMMDD."),
    option("max_downloads", "integer", None, "Stop after this many downloads.", minimum=1),
    option("rate_limit", "string", "", "Download rate limit, for example 2M."),
    option("retries", "integer", 10, "Retries for the whole download.", minimum=0, maximum=100),
    option("fragment_retries", "integer", 10, "Retries per fragment.", minimum=0, maximum=100),
    option("concurrent_fragments", "integer", 1, "Parallel fragment downloads.", minimum=1, maximum=32),
    option("proxy", "string", "", "HTTP/SOCKS proxy URL."),
    option("cookies_path", "string", "", "Netscape cookies file relative to the files root."),
    option("cookies_from_browser", "string", "", "Browser cookie source, for example chrome or firefox:profile."),
    option("sponsorblock", "boolean|string|array", False, "Mark SponsorBlock categories (true means all)."),
    option("sponsorblock_remove", "boolean|string|array", False, "Remove SponsorBlock categories."),
    option("archive_path", "string", "", "Download archive path relative to the files root."),
    option("download_archive", "string", "", "Alias for archive_path."),
    option("keep_video", "boolean", False, "Keep the original video after post-processing."),
    option("no_check_certificate", "boolean", False, "Disable TLS certificate verification."),
    option("geo_bypass", "boolean", True, "Try to bypass geo-restrictions."),
    option("user_agent", "string", "", "Override the User-Agent header."),
    option("referer", "string", "", "Set the Referer header."),
    option("headers", "object|array", {}, "Additional request headers as an object or header lines."),
    option("extractor_args", "object|array", {}, "Extractor arguments, for example {youtube: player_client=web}."),
    option("output_path", "string", "", "Output directory relative to the files root. Defaults to ytdlp/<job_id>/."),
    option("write_subs", "boolean", False, "Write subtitle files."),
    option("convert_subs", "string", "", "Convert subtitles to srt, vtt, ass or lrc.", enum=["srt", "vtt", "ass", "lrc", ""]),
    option("remux", "string", "", "Remux the result into this container.", enum=["mp4", "mkv", "webm", ""]),
    option("recode", "string", "", "Re-encode the result into this container.", enum=["mp4", "mkv", "webm", ""]),
    option("sleep_interval", "number", 0, "Seconds to sleep before each download.", minimum=0),
    option("max_sleep_interval", "number", 0, "Maximum randomized sleep interval.", minimum=0),
    option("socket_timeout", "number", 20, "Network socket timeout in seconds.", minimum=1),
    option("source_address", "string", "", "Client-side IP address to bind to."),
    option("prefer_free_formats", "boolean", False, "Prefer free containers (webm/opus) when quality is equal."),
    option("no_part", "boolean", False, "Do not write .part files."),
    option("continue_dl", "boolean", True, "Resume partially downloaded files."),
    option("timeout", "number", 86400, "Maximum download runtime in seconds.", minimum=1),
]


def catalog() -> dict[str, Any]:
    ffmpeg_version = "unavailable"
    try:
        import subprocess

        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        first_line = (result.stdout or "").splitlines()
        ffmpeg_version = first_line[0] if first_line else "unavailable"
    except Exception:  # noqa: BLE001
        pass
    yt_version = version()
    return {
        "service": "ytdlp",
        "version": VERSION,
        "yt_dlp": {"version": yt_version, "executable": YTDLP, "available": yt_version != "unavailable"},
        "extractors": {
            "count": extractor_count(),
            "common": [
                "youtube",
                "youtube:tab",
                "vimeo",
                "soundcloud",
                "bandcamp",
                "twitch",
                "tiktok",
                "instagram",
                "twitter",
                "facebook",
                "dailymotion",
                "bilibili",
                "archive.org",
            ],
        },
        "formats": [
            {"name": "best", "selector": "bv*+ba/b", "description": "Best video plus best audio, merged."},
            {"name": "bestvideo", "selector": "bv*", "description": "Best video-only stream."},
            {"name": "bestaudio", "selector": "ba", "description": "Best audio-only stream."},
            {"name": "audio", "selector": "ba/b", "description": "Audio, falling back to a muxed file."},
            {"name": "1080p", "selector": "bv*[height<=1080]+ba/b[height<=1080]", "description": "Up to 1080p."},
            {"name": "720p", "selector": "bv*[height<=720]+ba/b[height<=720]", "description": "Up to 720p."},
            {"name": "480p", "selector": "bv*[height<=480]+ba/b[height<=480]", "description": "Up to 480p."},
            {"name": "mp4", "selector": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]", "description": "Prefer MP4/M4A streams."},
            {"name": "webm", "selector": "bv*[ext=webm]+ba[ext=webm]/b[ext=webm]", "description": "Prefer WebM/Opus streams."},
        ],
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "description": "Extract audio in mp3/wav/flac/aac/opus/vorbis."},
            {"key": "FFmpegVideoRemuxer", "description": "Remux into another container."},
            {"key": "FFmpegVideoConvertor", "description": "Re-encode into another container."},
            {"key": "FFmpegMerger", "description": "Merge separate video and audio streams."},
            {"key": "FFmpegMetadata", "description": "Write metadata into the media container."},
            {"key": "EmbedSubtitle", "description": "Embed subtitle tracks."},
            {"key": "EmbedThumbnail", "description": "Embed cover art."},
            {"key": "SponsorBlock", "description": "Mark or remove sponsored segments."},
            {"key": "ModifyChapters", "description": "Remove chapters/sponsor segments."},
            {"key": "MoveFiles", "description": "Move finished files into place."},
        ],
        "options": OPTIONS,
        "defaults": {
            "format": "bv*+ba/b",
            "merge_output_format": "mp4",
            "output_template": "%(title).200B [%(id)s].%(ext)s",
            "audio_format": "mp3",
            "retries": 10,
            "fragment_retries": 10,
            "concurrent_fragments": 1,
            "playlist": True,
            "keep_video": False,
            "continue_dl": True,
            "socket_timeout": 20,
        },
        "cookies": {
            "path_field": "cookies_path",
            "note": "Upload a Netscape cookies.txt through /api/files/upload, then pass its files-relative path.",
        },
        "limits": {"max_playlist_entries": 500, "info_timeout_seconds": INFO_TIMEOUT, "max_concurrent_fragments": 32},
        "ffmpeg": ffmpeg_version,
        "generated_at": utc_now(),
    }


async def _submit(payload: dict[str, Any], title: str | None = None) -> dict[str, Any]:
    body = {
        "component": "ytdlp",
        "action": "download",
        "title": title or "yt-dlp · download",
        "params": payload,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=jobhub_headers()) as client:
            response = await client.post(f"{JOBHUB_URL}/api/jobs", json=body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Job hub unreachable: {exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Job hub rejected the job: {response.text[:1000]}")
    return response.json()


async def _run_json(args: list[str], timeout: float = INFO_TIMEOUT) -> dict[str, Any]:
    code, out, err = await run_process([YTDLP, *args], timeout=timeout)
    if code != 0:
        detail = (err or out).strip().splitlines()
        message = "\n".join(detail[-12:]) if detail else "yt-dlp failed"
        raise HTTPException(status_code=422, detail=message)
    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="yt-dlp returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="yt-dlp returned an unexpected payload")
    return data


@router.get("/catalog")
async def get_catalog() -> dict[str, Any]:
    return catalog()




async def cache_thumbnail(result: dict[str, Any], payload: dict[str, Any]) -> str | None:
    """Download the extractor thumbnail into shared storage for reliable previews."""
    url = result.get("thumbnail")
    if not url or not isinstance(url, str):
        thumbs = result.get("thumbnails") or []
        if isinstance(thumbs, list):
            candidates = [item.get("url") for item in reversed(thumbs) if isinstance(item, dict) and item.get("url")]
            url = candidates[0] if candidates else None
    if not url:
        return None
    ident = str(result.get("id") or hashlib.sha1(url.encode("utf-8")).hexdigest()[:12])
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", ident)[:80] or "thumbnail"
    headers = {"User-Agent": "Mozilla/5.0 Open Studio thumbnail cache"}
    if payload.get("referer"):
        headers["Referer"] = str(payload["referer"])
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
            response = await client.get(url)
            if response.status_code != 200 or not response.content:
                return None
            content_type = response.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                return None
            suffix = ".jpg"
            if "png" in content_type:
                suffix = ".png"
            elif "webp" in content_type:
                suffix = ".webp"
            target = resolve_path("ytdlp", "thumbnails", f"{safe}{suffix}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(response.content)
            return relative_path(target)
    except Exception:  # noqa: BLE001
        return None


@router.post("/info")
async def info(payload: dict[str, Any]) -> dict[str, Any]:
    url = validate_url(payload.get("url"))
    args = common_args(payload)
    args += ["--dump-single-json", "--skip-download"]
    if payload.get("flat_playlist"):
        args += ["--flat-playlist"]
    args += ["--", url]
    data = await _run_json(args)
    result = sanitize_info(data)
    result["formats_total"] = result.get("format_count", 0)
    thumbnail_path = await cache_thumbnail(result, payload)
    if thumbnail_path:
        result["thumbnail_path"] = thumbnail_path
    return result


@router.post("/search")
async def search(payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=422, detail="query is required")
    try:
        limit = int(payload.get("limit") or 20)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="limit must be an integer") from exc
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
    options = {key: value for key, value in payload.items() if key not in {"query", "limit"}}
    args = common_args(options)
    args += ["--dump-single-json", "--skip-download", "--flat-playlist", "--", f"ytsearch{limit}:{query}"]
    data = await _run_json(args)
    entries = data.get("entries") or []
    items = [sanitize_info(entry, include_entries=False) for entry in entries if isinstance(entry, dict)]
    return {"query": query, "items": items, "total": len(items), "limit": limit}


@router.post("/playlist")
async def playlist(payload: dict[str, Any]) -> dict[str, Any]:
    url = validate_url(payload.get("url"))
    limit = payload.get("limit")
    args = common_args(payload)
    args += ["--dump-single-json", "--skip-download"]
    if payload.get("flat_playlist", True):
        args += ["--flat-playlist"]
    if limit is not None:
        try:
            count = int(limit)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="limit must be an integer") from exc
        if count < 1 or count > 500:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
        args += ["--playlist-end", str(count)]
    args += ["--", url]
    data = await _run_json(args)
    entries = [entry for entry in (data.get("entries") or []) if isinstance(entry, dict)]
    items = [sanitize_info(entry, include_entries=False) for entry in entries]
    result = sanitize_info(data)
    result["entries"] = items
    result["entry_count"] = data.get("playlist_count") or len(items)
    result["items"] = items
    result["total"] = len(items)
    return result


@router.post("/download")
async def download(payload: dict[str, Any]) -> dict[str, Any]:
    validate_url(payload.get("url"))
    job = await _submit(payload, payload.get("title"))
    return job


@router.post("/download/job")
async def download_job(payload: dict[str, Any]) -> dict[str, Any]:
    validate_url(payload.get("url"))
    job = await _submit(payload, payload.get("title"))
    return job


async def _download_job(ctx) -> dict[str, Any]:
    params = dict(ctx.params or {})
    job_id = ctx.job_id
    workdir = resolve_path("ytdlp", job_id)
    workdir.mkdir(parents=True, exist_ok=True)
    log.info("download job=%s url=%s", job_id, params.get("url"))
    result = await execute_download(
        params,
        job_id=job_id,
        workdir=workdir,
        report=ctx.report,
        check=ctx.check,
    )
    return result


runner.register("download", _download_job)

app = create_service_app(
    "ytdlp",
    "Open Studio yt-dlp",
    "Download media, inspect formats, search and browse playlists with yt-dlp.",
    version=VERSION,
    runner=runner,
    extra_routers=[router],
)


@app.exception_handler(MediaError)
async def media_error_handler(_request, exc: MediaError):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=500, content={"detail": str(exc)})
