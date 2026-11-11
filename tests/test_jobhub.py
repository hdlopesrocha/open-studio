"""Job hub persistence and queue semantics."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("openstudio_jobhub_main", ROOT / "services" / "jobhub" / "main.py")
assert SPEC and SPEC.loader
jobhub = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(jobhub)


def test_create_update_and_cancel(tmp_path: Path):
    store = jobhub.Store(tmp_path / "jobs.db")
    job = store.create(
        {
            "component": "imagegen",
            "action": "generate",
            "title": "Cover",
            "params": {"prompt": "a city"},
        }
    )
    assert job["status"] == "queued"
    assert job["params"]["prompt"] == "a city"

    updated = store.update(job["id"], status="running", progress=42, stage="Sampling")
    assert updated["status"] == "running"
    assert updated["progress"] == 42

    store.append_warning(job["id"], "fallback used")
    store.append_artifacts(job["id"], [{"path": "images/a.png", "kind": "image"}])
    fetched = store.get(job["id"])
    assert fetched["warnings"] == ["fallback used"]
    assert fetched["artifacts"][0]["path"] == "images/a.png"

    items, total = store.list(component="imagegen")
    assert total == 1 and items[0]["id"] == job["id"]
    assert store.delete(job["id"])
    assert store.get(job["id"]) is None


def test_unknown_component_is_rejected(tmp_path: Path):
    store = jobhub.Store(tmp_path / "jobs.db")
    try:
        store.create({"component": "nope", "action": "x"})
    except ValueError as exc:
        assert "Unknown" in str(exc)
    else:
        raise AssertionError("expected ValueError")
