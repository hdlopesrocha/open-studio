"""Test environment: keep state out of /data and make imports deterministic."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

ROOT = Path(tempfile.mkdtemp(prefix="openstudio-tests-"))
for name in ("files", "state", "cache", "models", "artifacts"):
    (ROOT / name).mkdir(parents=True, exist_ok=True)

os.environ.setdefault("DATA_ROOT", str(ROOT))
os.environ.setdefault("FILES_ROOT", str(ROOT / "files"))
os.environ.setdefault("STATE_ROOT", str(ROOT / "state"))
os.environ.setdefault("CACHE_ROOT", str(ROOT / "cache"))
os.environ.setdefault("MODELS_ROOT", str(ROOT / "models"))
os.environ.setdefault("ARTIFACT_ROOT", str(ROOT / "artifacts"))
os.environ.setdefault("INTERNAL_TOKEN", "test-internal-token")
os.environ.setdefault("REQUIRE_INTERNAL_TOKEN", "false")
os.environ.setdefault("JOBHUB_URL", "http://127.0.0.1:9999")
