"""Security tests for first-run password, sessions and API keys."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("openstudio_gateway_auth", ROOT / "services" / "gateway" / "auth.py")
assert SPEC and SPEC.loader
auth_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(auth_module)


def test_password_setup_and_login(tmp_path: Path):
    store = auth_module.AuthStore(tmp_path / "auth.db")
    assert not store.has_password
    with pytest.raises(ValueError):
        store.set_password("short")
    store.set_password("a-strong-password")
    assert store.has_password
    assert store.check_password("a-strong-password")
    assert not store.check_password("wrong")
    with pytest.raises(ValueError):
        store.set_password("another-password")


def test_sessions_and_api_keys(tmp_path: Path):
    store = auth_module.AuthStore(tmp_path / "auth.db")
    store.set_password("a-strong-password")
    token, session = store.create_session()
    assert session["id"]
    found = store.session_for(token)
    assert found and found["id"] == session["id"]
    assert store.session_for("not-a-token") is None
    assert store.revoke_session(session["id"])
    assert store.session_for(token) is None

    created = store.create_api_key("automation")
    assert created["token"].startswith("osk_")
    found_key = store.api_key_for(created["token"])
    assert found_key and found_key["name"] == "automation"
    assert store.api_key_for("osk_invalid") is None
    assert store.revoke_api_key(created["id"])


def test_change_password_revokes_sessions(tmp_path: Path):
    store = auth_module.AuthStore(tmp_path / "auth.db")
    store.set_password("a-strong-password")
    token, _ = store.create_session()
    with pytest.raises(PermissionError):
        store.change_password("wrong", "new-strong-password")
    store.change_password("a-strong-password", "new-strong-password")
    assert store.check_password("new-strong-password")
    assert store.session_for(token) is None
