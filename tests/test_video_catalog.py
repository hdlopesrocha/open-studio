"""Video catalog and project configuration tests without running a render."""

from __future__ import annotations

import os
from pathlib import Path


def test_video_catalog_exposes_scene_and_output_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("FILES_ROOT", str(tmp_path / "data" / "files"))
    monkeypatch.setenv("PROJECTS_ROOT", str(tmp_path / "data" / "files" / "video" / "projects"))
    monkeypatch.setenv("EXPORTS_ROOT", str(tmp_path / "data" / "files" / "video" / "exports"))
    monkeypatch.setenv("CACHE_ROOT", str(tmp_path / "data" / "cache" / "video"))
    monkeypatch.setenv("MODELS_ROOT", str(tmp_path / "data" / "models"))
    monkeypatch.setenv("CONFIG_ROOT", str(tmp_path / "data" / "state" / "video"))
    for directory in ("projects", "exports", "cache", "models", "state"):
        (tmp_path / "data" / ("files/video" if directory in {"projects", "exports"} else directory)).mkdir(parents=True, exist_ok=True)

    from services.video.catalog import build_catalog
    from services.video.settings_store import AISettingsStore

    catalog = build_catalog(AISettingsStore())
    assert "run_actions" in catalog
    assert "output_sizes" in catalog
    assert "styles" in catalog
    assert catalog["output_sizes"]
    assert catalog["styles"]
    assert any(item.get("id") == "analyze" for item in catalog["run_actions"])


def test_video_project_store_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data2"))
    monkeypatch.setenv("FILES_ROOT", str(tmp_path / "data2" / "files"))
    monkeypatch.setenv("PROJECTS_ROOT", str(tmp_path / "data2" / "files" / "video" / "projects"))
    monkeypatch.setenv("EXPORTS_ROOT", str(tmp_path / "data2" / "files" / "video" / "exports"))
    monkeypatch.setenv("CACHE_ROOT", str(tmp_path / "data2" / "cache" / "video"))
    monkeypatch.setenv("MODELS_ROOT", str(tmp_path / "data2" / "models"))
    monkeypatch.setenv("CONFIG_ROOT", str(tmp_path / "data2" / "state" / "video"))
    from mvstudio_shared.models import Project
    from mvstudio_shared.storage import ProjectStore

    root = Path(os.environ["PROJECTS_ROOT"])
    root.mkdir(parents=True, exist_ok=True)
    store = ProjectStore(root)
    project = store.create(Project(id="catalog-test", name="Test video", title="Test video"))
    loaded = store.load(project.id)
    assert loaded.title == "Test video"
    assert store.list()
    store.delete(project.id)
    try:
        store.load(project.id)
    except Exception:
        pass
    else:
        raise AssertionError("deleted video project was still loadable")
