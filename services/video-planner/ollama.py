"""Provider integration for the story planner (local Ollama, optional)."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError


class SceneEnhancement(BaseModel):
    scene_id: int
    description: str = Field(min_length=5, max_length=600)
    visual_prompt: str = Field(min_length=10, max_length=2500)


class OllamaEnhancement(BaseModel):
    scenes: list[SceneEnhancement] = Field(default_factory=list)
    art_direction: str = Field(default="", max_length=800)
    visual_style_prompt: str = Field(default="", max_length=1200)


class OllamaUnavailable(RuntimeError):
    pass


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("Ollama response must be a JSON object")
    return data


class OllamaPlanner:
    def __init__(self, base_url: str, model: str, timeout: float = 180.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def available(self) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{self.base_url}/api/tags")
            if response.status_code != 200:
                return False, f"Ollama responded with HTTP {response.status_code}"
            payload = response.json()
            models = {entry.get("name", "") for entry in payload.get("models", [])}
            if self.model not in models:
                short = {name.split(":")[0] for name in models}
                if self.model.split(":")[0] not in short:
                    return False, (
                        f"Ollama is running but model '{self.model}' is not installed. "
                        f"Install it with: ollama pull {self.model}"
                    )
            return True, "available"
        except Exception as exc:
            return False, f"Ollama is not reachable at {self.base_url}: {exc}"

    def enhance(self, prompt: str) -> OllamaEnhancement:
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a visual director for a music video. Return only valid JSON. "
                        "Never invent timings or new scenes. Preserve the supplied scene IDs, "
                        "character descriptions and visual style. Keep one coherent narrative."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "options": {"temperature": 0.7, "num_predict": 4096},
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(f"{self.base_url}/api/chat", json=payload)
        except Exception as exc:
            raise OllamaUnavailable(f"Ollama request failed: {exc}") from exc
        if response.status_code != 200:
            detail = response.text[:500]
            raise OllamaUnavailable(f"Ollama returned HTTP {response.status_code}: {detail}")
        try:
            body = response.json()
            content = body.get("message", {}).get("content")
            if not content:
                raise ValueError("Ollama returned an empty response")
            data = _extract_json(content)
            return OllamaEnhancement.model_validate(data)
        except (ValueError, ValidationError, json.JSONDecodeError) as exc:
            raise OllamaUnavailable(f"Ollama returned invalid structured JSON: {exc}") from exc
