"""Readiness checks must not accept partial translation checkpoints."""

from __future__ import annotations

from pathlib import Path


def _checkpoint(root: Path, weight_bytes: int) -> Path:
    folder = root / "model"
    folder.mkdir(parents=True)
    (folder / "config.json").write_text("{}")
    (folder / "tokenizer.json").write_text("{}")
    weight = folder / "pytorch_model.bin"
    with weight.open("wb") as handle:
        handle.truncate(weight_bytes)
    return folder


def test_translation_engine_rejects_partial_weights(tmp_path):
    from services.translation.app.engine import _folder_ready

    assert not _folder_ready(_checkpoint(tmp_path / "small", 1024))
    assert _folder_ready(_checkpoint(tmp_path / "ready", 11 * 1024 * 1024))


def test_admin_translation_readiness_rejects_partial_weights(tmp_path):
    from services.admin.main import _translation_model_ready

    assert not _translation_model_ready(_checkpoint(tmp_path / "small", 1024))
    assert _translation_model_ready(_checkpoint(tmp_path / "ready", 11 * 1024 * 1024))
