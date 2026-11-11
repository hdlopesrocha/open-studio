"""First-run password, sessions and API keys for the public gateway."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openstudio_common import STATE_ROOT

DB_PATH = Path(os.getenv("AUTH_DB", str(STATE_ROOT / "auth.db")))
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "30"))
MIN_PASSWORD = int(os.getenv("MIN_PASSWORD_LENGTH", "8"))


def _now() -> int:
    return int(time.time())


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = encoded.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(digest_hex)),
        )
        return hmac.compare_digest(digest, bytes.fromhex(digest_hex))
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthStore:
    def __init__(self, path: Path = DB_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init()

    def _init(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at INTEGER NOT NULL,
                    last_seen INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    user_agent TEXT DEFAULT '',
                    ip TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS api_keys (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    prefix TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at INTEGER NOT NULL,
                    last_used_at INTEGER
                );
                """
            )
            self._conn.commit()

    def _get_meta(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def _set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            self._conn.commit()

    @property
    def has_password(self) -> bool:
        return bool(self._get_meta("password_hash"))

    @property
    def setup_at(self) -> str | None:
        return self._get_meta("password_set_at")

    def set_password(self, password: str) -> None:
        password = password or ""
        if len(password) < MIN_PASSWORD:
            raise ValueError(f"Password must be at least {MIN_PASSWORD} characters")
        if len(password) > 200:
            raise ValueError("Password is too long")
        if not self.has_password:
            encoded = _hash_password(password)
            self._set_meta("password_hash", encoded)
            self._set_meta("password_set_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        else:
            raise ValueError("Password is already configured")

    def change_password(self, current: str, new: str) -> None:
        encoded = self._get_meta("password_hash") or ""
        if not _verify_password(current, encoded):
            raise PermissionError("Current password is incorrect")
        if len(new) < MIN_PASSWORD:
            raise ValueError(f"Password must be at least {MIN_PASSWORD} characters")
        self._set_meta("password_hash", _hash_password(new))
        self._set_meta("password_set_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self.revoke_all_sessions()

    def check_password(self, password: str) -> bool:
        encoded = self._get_meta("password_hash") or ""
        return _verify_password(password, encoded)

    def create_session(self, *, user_agent: str = "", ip: str = "", days: int = SESSION_DAYS) -> tuple[str, dict[str, Any]]:
        token = secrets.token_urlsafe(40)
        session_id = secrets.token_hex(12)
        now = _now()
        expires = now + max(1, days) * 86400
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions(id,token_hash,created_at,last_seen,expires_at,user_agent,ip) VALUES(?,?,?,?,?,?,?)",
                (session_id, _token_hash(token), now, now, expires, user_agent[:300], ip[:80]),
            )
            self._conn.commit()
        return token, {"id": session_id, "expires_at": expires}

    def session_for(self, token: str, *, touch: bool = True) -> dict[str, Any] | None:
        if not token:
            return None
        now = _now()
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE token_hash=? AND expires_at>?", (_token_hash(token), now)
            ).fetchone()
            if not row:
                return None
            if touch and now - int(row["last_seen"]) > 60:
                self._conn.execute("UPDATE sessions SET last_seen=? WHERE id=?", (now, row["id"]))
                self._conn.commit()
        return {"id": row["id"], "created_at": row["created_at"], "expires_at": row["expires_at"], "type": "session"}

    def api_key_for(self, token: str) -> dict[str, Any] | None:
        if not token.startswith("osk_"):
            return None
        now = _now()
        with self._lock:
            row = self._conn.execute("SELECT * FROM api_keys WHERE token_hash=?", (_token_hash(token),)).fetchone()
            if not row:
                return None
            self._conn.execute("UPDATE api_keys SET last_used_at=? WHERE id=?", (now, row["id"]))
            self._conn.commit()
        return {"id": row["id"], "name": row["name"], "type": "api_key"}

    def revoke_session(self, session_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            self._conn.commit()
        return cursor.rowcount > 0

    def revoke_all_sessions(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM sessions")
            self._conn.commit()

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
        return [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "last_seen": row["last_seen"],
                "expires_at": row["expires_at"],
                "user_agent": row["user_agent"],
                "ip": row["ip"],
            }
            for row in rows
        ]

    def create_api_key(self, name: str) -> dict[str, Any]:
        token = "osk_" + secrets.token_urlsafe(32)
        key_id = secrets.token_hex(8)
        prefix = token[:12]
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO api_keys(id,name,prefix,token_hash,created_at) VALUES(?,?,?,?,?)",
                (key_id, (name or "API key")[:80], prefix, _token_hash(token), now),
            )
            self._conn.commit()
        return {"id": key_id, "name": name, "prefix": prefix, "token": token, "created_at": now}

    def list_api_keys(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM api_keys ORDER BY created_at DESC").fetchall()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "prefix": row["prefix"],
                "created_at": row["created_at"],
                "last_used_at": row["last_used_at"],
            }
            for row in rows
        ]

    def revoke_api_key(self, key_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM api_keys WHERE id=?", (key_id,))
            self._conn.commit()
        return cursor.rowcount > 0

    def cleanup(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE expires_at<=?", (_now(),))
            self._conn.commit()
