"""QVAC image-provider concurrency handling."""

from __future__ import annotations

import asyncio

import pytest

from services.imagegen import qvac


def test_qvac_concurrency_rejections_are_classified():
    assert qvac._is_concurrency_rejection(RuntimeError("another diffusion request is already running on this model"))
    assert qvac._is_concurrency_rejection(RuntimeError("REQUEST_REJECTED_BY_POLICY"))
    assert not qvac._is_concurrency_rejection(RuntimeError("model not found"))


def test_qvac_generate_serializes_and_retries(monkeypatch):
    active = 0
    peak = 0
    calls = 0

    async def fake_generate(params, *, on_poll=None):
        nonlocal active, peak, calls
        calls += 1
        active += 1
        peak = max(peak, active)
        try:
            if calls == 1:
                raise qvac.QVACError("another diffusion request is already running on this model")
            await asyncio.sleep(0.01)
            return {"images": [{"data": b"ok"}], "metadata": {}}
        finally:
            active -= 1

    async def no_sleep(_seconds):
        return None

    async def idle(_timeout=None):
        return True

    monkeypatch.setattr(qvac, "_generate_locked", fake_generate)
    monkeypatch.setattr(qvac, "_wait_for_qvac_idle", idle)
    monkeypatch.setattr(qvac.asyncio, "sleep", no_sleep)
    result = asyncio.run(qvac.generate({"prompt": "test"}))
    assert result["images"][0]["data"] == b"ok"
    assert calls == 2
    assert peak == 1


def test_qvac_idle_checks_canceling_and_runtime_jobs():
    class Response:
        def __init__(self, payload, status=200):
            self.status_code = status
            self._payload = payload

        def json(self):
            return self._payload

    class Client:
        def __init__(self, jobs, runtime):
            self.jobs = jobs
            self.runtime = runtime
            self.requests = []

        async def get(self, url, params=None):
            self.requests.append((url, params))
            if url.endswith("/api/jobs"):
                return Response(self.jobs)
            return Response(self.runtime)

    client = Client({"items": [{"id": "cancel-me"}]}, {"active_jobs": []})
    assert asyncio.run(qvac._jobhub_qvac_idle(client)) is False
    assert client.requests[0][1] == {"component": "qvac", "status": "running,canceling"}

    client.jobs = {"items": []}
    client.runtime = {"active_jobs": [{"job_id": "still-generating"}]}
    assert asyncio.run(qvac._jobhub_qvac_idle(client)) is True
    assert asyncio.run(qvac._qvac_runtime_idle(client)) is False

    client.runtime = {"active_jobs": []}
    assert asyncio.run(qvac._qvac_runtime_idle(client)) is True


def test_qvac_retry_aborts_when_slot_never_clears(monkeypatch):
    calls = 0
    idle_checks = 0

    async def reject(_params, *, on_poll=None):
        nonlocal calls
        calls += 1
        raise qvac.QVACError("another diffusion request is already running on this model")

    async def no_sleep(_seconds):
        return None

    async def busy(_timeout=None):
        nonlocal idle_checks
        idle_checks += 1
        return idle_checks == 1

    qvac._CONSECUTIVE_REJECTIONS = 0
    qvac._REJECTION_COOLDOWN_UNTIL = 0.0
    monkeypatch.setattr(qvac, "_generate_locked", reject)
    monkeypatch.setattr(qvac, "_wait_for_qvac_idle", busy)
    monkeypatch.setattr(qvac.asyncio, "sleep", no_sleep)

    with pytest.raises(qvac.QVACError, match="did not become idle"):
        asyncio.run(qvac.generate({"prompt": "test"}))
    assert calls == 1


def test_qvac_repeated_rejections_open_a_circuit_breaker(monkeypatch):
    calls = 0

    async def reject(_params, *, on_poll=None):
        nonlocal calls
        calls += 1
        raise qvac.QVACError("another diffusion request is already running on this model")

    async def idle(_timeout=None):
        return True

    async def no_sleep(_seconds):
        return None

    qvac._CONSECUTIVE_REJECTIONS = 0
    qvac._REJECTION_COOLDOWN_UNTIL = 0.0
    monkeypatch.setattr(qvac, "_generate_locked", reject)
    monkeypatch.setattr(qvac, "_wait_for_qvac_idle", idle)
    monkeypatch.setattr(qvac.asyncio, "sleep", no_sleep)

    with pytest.raises(qvac.QVACError, match="slot is stuck"):
        asyncio.run(qvac.generate({"prompt": "test"}))
    assert calls == qvac._REJECTION_CIRCUIT_THRESHOLD

    with pytest.raises(qvac.QVACError, match="cooling down"):
        asyncio.run(qvac.generate({"prompt": "test"}))
    assert calls == qvac._REJECTION_CIRCUIT_THRESHOLD

    qvac._CONSECUTIVE_REJECTIONS = 0
    qvac._REJECTION_COOLDOWN_UNTIL = 0.0
