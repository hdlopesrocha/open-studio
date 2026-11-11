"""Shared LLM gateway for lyrics, video planning and text tooling.

Supports any OpenAI-compatible endpoint (Ollama, llama.cpp, LM Studio, vLLM)
and exposes every generation control the UI needs. No prompt logic lives here;
the calling service owns its prompts.
"""

from __future__ import annotations

import os
from typing import Any, AsyncIterator

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from openstudio_common import create_service_app, env, env_bool, env_int, service_url

BASE_URL = env("LLM_BASE_URL", "http://ollama:11434/v1").rstrip("/")
API_KEY = env("LLM_API_KEY", "")
DEFAULT_MODEL = env("LLM_MODEL", "llama3.2:3b")
TIMEOUT = float(env("LLM_TIMEOUT_SECONDS", "300"))
NATIVE_OLLAMA = env_bool("LLM_OLLAMA_NATIVE", True)


def headers() -> dict[str, str]:
    result = {"Content-Type": "application/json"}
    if API_KEY:
        result["Authorization"] = f"Bearer {API_KEY}"
    return result


async def models() -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=headers()) as client:
            response = await client.get(f"{BASE_URL}/models")
            if response.status_code == 200:
                data = response.json().get("data", [])
                return [{"id": m.get("id"), "object": m.get("object", "model"), "owned_by": m.get("owned_by", "local")} for m in data]
    except Exception:  # noqa: BLE001
        pass
    return []


app = create_service_app(
    "llm",
    "Open Studio LLM",
    "OpenAI-compatible bridge used by lyrics and video planning.",
)


@app.get("/api/llm/health")
async def llm_health() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=3.0, headers=headers()) as client:
            response = await client.get(f"{BASE_URL}/models")
            return {
                "status": "ok" if response.status_code == 200 else "degraded",
                "base_url": BASE_URL,
                "reachable": response.status_code == 200,
                "model": DEFAULT_MODEL,
                "models": await models(),
            }
    except Exception as exc:  # noqa: BLE001
        return {"status": "offline", "base_url": BASE_URL, "reachable": False, "model": DEFAULT_MODEL, "error": str(exc)}


@app.get("/api/llm/models")
async def list_models() -> dict[str, Any]:
    items = await models()
    return {"items": items, "default": DEFAULT_MODEL, "base_url": BASE_URL}


@app.post("/api/llm/chat")
async def chat(payload: dict[str, Any], request: Request):
    messages = payload.get("messages") or []
    if not messages and payload.get("prompt"):
        messages = [{"role": "user", "content": str(payload["prompt"])}]
    if not messages:
        raise HTTPException(status_code=422, detail="messages or prompt is required")
    body = {
        "model": payload.get("model") or DEFAULT_MODEL,
        "messages": messages,
        "temperature": payload.get("temperature", 0.7),
        "top_p": payload.get("top_p", 0.95),
        "max_tokens": payload.get("max_tokens", 2048),
        "stream": bool(payload.get("stream", False)),
    }
    for key in ("stop", "seed", "presence_penalty", "frequency_penalty", "response_format"):
        if payload.get(key) is not None:
            body[key] = payload[key]
    url = f"{BASE_URL}/chat/completions"
    if body["stream"]:
        client = httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=None, write=30.0))
        upstream_request = client.build_request("POST", url, headers=headers(), json=body)
        try:
            upstream = await client.send(upstream_request, stream=True)
        except Exception as exc:  # noqa: BLE001
            await client.aclose()
            raise HTTPException(status_code=502, detail=f"LLM unreachable: {exc}") from exc

        async def stream() -> AsyncIterator[bytes]:
            try:
                async for chunk in upstream.aiter_raw():
                    if await request.is_disconnected():
                        break
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        return StreamingResponse(stream(), media_type="text/event-stream")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers()) as client:
            response = await client.post(url, json=body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM unreachable: {exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text[:2000])
    return response.json()


@app.post("/api/llm/complete")
async def complete(payload: dict[str, Any]) -> dict[str, Any]:
    result = await chat({"messages": [{"role": "user", "content": payload.get("prompt", "")}], **payload})
    choices = result.get("choices") or []
    return {
        "text": (choices[0].get("message", {}).get("content") if choices else "") or "",
        "model": result.get("model"),
        "usage": result.get("usage"),
        "raw": result,
    }


@app.post("/api/llm/embeddings")
async def embeddings(payload: dict[str, Any]) -> dict[str, Any]:
    body = {"model": payload.get("model") or DEFAULT_MODEL, "input": payload.get("input")}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers()) as client:
            response = await client.post(f"{BASE_URL}/embeddings", json=body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM unreachable: {exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text[:2000])
    return response.json()
