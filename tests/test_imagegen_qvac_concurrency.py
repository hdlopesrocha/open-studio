"""QVAC image-provider concurrency handling."""

from __future__ import annotations

import asyncio

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

    async def idle():
        return True

    monkeypatch.setattr(qvac, "_generate_locked", fake_generate)
    monkeypatch.setattr(qvac, "_wait_for_qvac_idle", idle)
    monkeypatch.setattr(qvac.asyncio, "sleep", no_sleep)
    result = asyncio.run(qvac.generate({"prompt": "test"}))
    assert result["images"][0]["data"] == b"ok"
    assert calls == 2
    assert peak == 1
