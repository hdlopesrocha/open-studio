"""yt-dlp option construction and artifact collection (no network/subprocess)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from openstudio_common import FILES_ROOT
from services.ytdlp import downloads


def _outdir(name: str) -> Path:
    path = FILES_ROOT / "ytdlp-tests" / name
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    return path


def test_validate_url_accepts_http_and_rejects_other_schemes():
    assert downloads.validate_url(" https://example.test/watch?v=1 ") == "https://example.test/watch?v=1"
    assert downloads.validate_url("http://127.0.0.1:8080/media") == "http://127.0.0.1:8080/media"
    for value in ("", None, "file:///etc/passwd", "ftp://example.test/x", "example.test/x"):
        with pytest.raises(ValueError):
            downloads.validate_url(value)


def test_output_template_and_archive_validation(tmp_path, monkeypatch):
    assert downloads.output_template("") == "%(title).200B [%(id)s].%(ext)s"
    assert downloads.output_template("%(title)s.%(ext)s") == "%(title)s.%(ext)s"
    with pytest.raises(ValueError):
        downloads.output_template("/abs/path/%(title)s.%(ext)s")
    with pytest.raises(ValueError):
        downloads.output_template("../escape/%(title)s.%(ext)s")

    cookie = tmp_path / "cookies.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    monkeypatch.setattr(downloads, "resolve_path", lambda rel: tmp_path / rel)
    assert downloads.cookie_path("cookies.txt") == cookie
    assert downloads.cookie_path("") is None
    with pytest.raises(FileNotFoundError):
        downloads.cookie_path("missing.txt")


def test_download_args_build_expected_command(tmp_path):
    payload = {
        "url": "https://example.test/watch?v=abc",
        "format": "bv*+ba/b",
        "format_sort": ["res:1080", "codec:h264"],
        "extract_audio": True,
        "audio_format": "mp3",
        "audio_quality": "0",
        "subtitles": ["en", "pt"],
        "embed_subs": True,
        "write_thumbnail": True,
        "write_info_json": True,
        "playlist": False,
        "max_downloads": 2,
        "sponsorblock_remove": "sponsor",
        "headers": {"Referer": "https://example.test/"},
        "geo_bypass": False,
        "retries": 3,
    }
    args = downloads.download_args(
        payload,
        outdir=tmp_path / "out",
        paths_file=tmp_path / "paths.txt",
        meta_file=tmp_path / "meta.jsonl",
    )
    assert args[0] == "--newline"
    assert "--ignore-config" in args
    assert args[-1] == payload["url"]
    assert args[-2] == "--"
    assert "--format-sort" in args
    assert "res:1080,codec:h264" in args
    assert "--extract-audio" in args
    assert "mp3" in args
    assert "--sub-langs" in args and "en,pt" in args
    assert "--embed-subs" in args
    assert "--no-playlist" in args
    assert "--no-geo-bypass" in args
    assert "--sponsorblock-remove" in args and "sponsor" in args
    assert "--add-header" in args and "Referer: https://example.test/" in args
    assert "--retries" in args and "3" in args
    assert str(tmp_path / "paths.txt") in args
    assert str(tmp_path / "meta.jsonl") in args


def test_download_args_rejects_header_newlines_and_non_http_url(tmp_path):
    with pytest.raises(ValueError):
        downloads.download_args(
            {"url": "https://example.test/x", "headers": {"X-Test": "a\nb"}},
            outdir=tmp_path,
            paths_file=tmp_path / "paths.txt",
            meta_file=tmp_path / "meta.jsonl",
        )
    with pytest.raises(ValueError):
        downloads.download_args(
            {"url": "file:///etc/passwd"},
            outdir=tmp_path,
            paths_file=tmp_path / "paths.txt",
            meta_file=tmp_path / "meta.jsonl",
        )


def test_collect_outputs_reads_paths_and_metadata(tmp_path):
    outdir = _outdir("collect-metadata")
    video = outdir / "clip.mp4"
    video.write_bytes(b"\x00" * 32)
    subtitle = outdir / "clip.en.vtt"
    subtitle.write_text("WEBVTT\n", encoding="utf-8")
    partial = outdir / "clip.webm.part"
    partial.write_bytes(b"partial")
    info_json = outdir / "clip.info.json"
    info_json.write_text(json.dumps({"title": "Clip", "duration": 42, "uploader": "Ana"}), encoding="utf-8")

    paths_file = tmp_path / "paths.txt"
    paths_file.write_text(f"{video}\n{subtitle}\nNA\n", encoding="utf-8")
    meta_file = tmp_path / "meta.jsonl"
    meta_file.write_text(
        json.dumps({"title": "Clip", "duration": 42, "thumbnail": "NA", "webpage_url": "https://example.test/x"})
        + "\n",
        encoding="utf-8",
    )

    descriptors, metadata, found_info_json = downloads.collect_outputs(outdir, paths_file, meta_file)
    names = {item["name"] for item in descriptors}
    assert names == {"clip.mp4", "clip.en.vtt", "clip.info.json"}
    assert "clip.webm.part" not in names
    assert metadata["title"] == "Clip"
    assert metadata["duration"] == 42
    assert metadata["webpage_url"] == "https://example.test/x"
    assert metadata["info_json"].endswith("clip.info.json")
    assert found_info_json == info_json
    kinds = {item["name"]: item["kind"] for item in descriptors}
    assert kinds["clip.mp4"] == "video"
    assert kinds["clip.en.vtt"] == "subtitle"
    assert kinds["clip.info.json"] == "document"


def test_collect_outputs_ignores_paths_outside_output_dir(tmp_path):
    outdir = _outdir("collect-outside")
    inside = outdir / "inside.mp3"
    inside.write_bytes(b"audio")
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"audio")
    paths_file = tmp_path / "paths.txt"
    paths_file.write_text(f"{outside}\n{inside}\n", encoding="utf-8")

    descriptors, metadata, info_json = downloads.collect_outputs(outdir, paths_file, tmp_path / "missing.jsonl")
    assert [item["name"] for item in descriptors] == ["inside.mp3"]
    assert metadata == {}
    assert info_json is None
