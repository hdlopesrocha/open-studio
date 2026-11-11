"""Minimal ComfyUI API client with placeholder-driven workflows."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from openstudio_common import FILES_ROOT, MODELS_ROOT, env

log = logging.getLogger("imagegen.comfyui")

PLACEHOLDER_DEFAULTS = {
    "PROMPT": "",
    "NEGATIVE_PROMPT": "",
    "WIDTH": 1024,
    "HEIGHT": 1024,
    "SEED": 1,
    "STEPS": 28,
    "CFG": 6.0,
    "CHECKPOINT": "",
    "PREFIX": "openstudio",
    "REFERENCE_IMAGE": "",
}
_SOLE_PLACEHOLDER_RE = re.compile(r"^\{\{([A-Z0-9_]+)\}\}$")


class ComfyUIError(RuntimeError):
    pass


class ComfyUIUnavailable(ComfyUIError):
    pass


def _replace(value: Any, replacements: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: _replace(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace(item, replacements) for item in value]
    if isinstance(value, str):
        sole = _SOLE_PLACEHOLDER_RE.match(value)
        if sole and sole.group(1) in replacements:
            return replacements[sole.group(1)]
        result = value
        for key, replacement in replacements.items():
            result = result.replace("{{" + key + "}}", str(replacement))
        return result
    return value


def resolve_reference(value: str | None) -> str | None:
    if not value:
        return None
    candidate = Path(value).expanduser()
    roots = (FILES_ROOT.resolve(), MODELS_ROOT.resolve())
    if candidate.is_absolute():
        resolved = candidate.resolve()
        if not any(resolved == root or root in resolved.parents for root in roots):
            return None
        return str(resolved) if resolved.is_file() else None
    for root in roots:
        resolved = (root / value).resolve()
        if (resolved == root or root in resolved.parents) and resolved.is_file():
            return str(resolved)
    return None


class ComfyUIClient:
    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base_url = (base_url or env("COMFYUI_URL", "http://comfyui:8188")).rstrip("/")
        self.timeout = timeout

    def available(self) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=4.0) as client:
                response = client.get(f"{self.base_url}/system_stats")
            if response.status_code != 200:
                return False, f"ComfyUI responded with HTTP {response.status_code}"
            stats = response.json()
            devices = stats.get("devices") or []
            if devices:
                device = devices[0]
                name = device.get("name", "unknown device")
                kind = device.get("type", "")
                vram_total = device.get("vram_total")
                vram_free = device.get("vram_free")
                detail = f"available ({name} {kind}".strip()
                if vram_total and vram_free:
                    detail += f", {vram_free / 1024**3:.1f}/{vram_total / 1024**3:.1f} GB VRAM free"
                detail += ")"
                return True, detail
            return True, "available"
        except Exception as exc:  # noqa: BLE001
            return False, f"ComfyUI is not reachable at {self.base_url}: {exc}"

    def checkpoints(self) -> list[str]:
        try:
            with httpx.Client(timeout=8.0) as client:
                response = client.get(f"{self.base_url}/object_info/CheckpointLoaderSimple")
            if response.status_code != 200:
                return []
            data = response.json()
            node = data.get("CheckpointLoaderSimple", {})
            required = node.get("input", {}).get("required", {})
            ckpt = required.get("ckpt_name")
            if isinstance(ckpt, list) and ckpt and isinstance(ckpt[0], list):
                return [str(item) for item in ckpt[0]]
            return []
        except Exception:  # noqa: BLE001
            return []

    def load_workflow(self, workflow_path: str | None, workflow: dict[str, Any] | None = None) -> dict[str, Any]:
        if workflow:
            if not isinstance(workflow, dict):
                raise ComfyUIError("Inline ComfyUI workflow must be a JSON object")
            if "prompt" in workflow and isinstance(workflow["prompt"], dict):
                return workflow["prompt"]
            return workflow
        if not workflow_path:
            raise ComfyUIError("No ComfyUI workflow is configured")
        path = Path(workflow_path).expanduser()
        if not path.is_absolute():
            candidate = FILES_ROOT / workflow_path
            if candidate.is_file():
                path = candidate
        if not path.is_file():
            raise ComfyUIError(f"ComfyUI workflow file not found: {workflow_path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise ComfyUIError(f"Could not read ComfyUI workflow {path.name}: {exc}") from exc
        if not isinstance(data, dict):
            raise ComfyUIError("ComfyUI workflow must be a JSON object in API format")
        if "prompt" in data and isinstance(data["prompt"], dict):
            data = data["prompt"]
        return data

    def upload_image(self, image_path: str | Path, name: str) -> str:
        path = Path(image_path)
        if not path.is_file():
            raise ComfyUIError(f"Reference image not found: {path}")
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    f"{self.base_url}/upload/image",
                    files={"image": (name, path.read_bytes(), "application/octet-stream")},
                    data={"type": "input", "overwrite": "true"},
                )
            if response.status_code != 200:
                raise ComfyUIError(f"ComfyUI image upload failed: HTTP {response.status_code}")
            return response.json().get("name", name)
        except httpx.HTTPError as exc:
            raise ComfyUIUnavailable(f"ComfyUI upload failed: {exc}") from exc

    def queue_prompt(self, workflow: dict[str, Any]) -> str:
        client_id = uuid.uuid4().hex
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    f"{self.base_url}/prompt",
                    json={"prompt": workflow, "client_id": client_id},
                )
        except httpx.HTTPError as exc:
            raise ComfyUIUnavailable(f"Could not reach ComfyUI: {exc}") from exc
        if response.status_code != 200:
            raise ComfyUIError(f"ComfyUI rejected the workflow: HTTP {response.status_code}: {response.text[:1200]}")
        payload = response.json()
        prompt_id = payload.get("prompt_id")
        if not prompt_id:
            raise ComfyUIError(f"ComfyUI did not return a prompt id: {payload}")
        return str(prompt_id)

    def wait_for_result(self, prompt_id: str, timeout: float = 600.0) -> list[dict[str, Any]]:
        deadline = time.monotonic() + timeout
        with httpx.Client(timeout=30.0) as client:
            while time.monotonic() < deadline:
                try:
                    response = client.get(f"{self.base_url}/history/{prompt_id}")
                except httpx.HTTPError as exc:
                    raise ComfyUIUnavailable(f"Lost connection to ComfyUI while waiting: {exc}") from exc
                if response.status_code == 200:
                    history = response.json()
                    entry = history.get(prompt_id)
                    if entry:
                        status = entry.get("status", {})
                        if status.get("status_str") == "error":
                            messages = status.get("messages", [])
                            raise ComfyUIError(f"ComfyUI workflow failed: {str(messages)[:1500]}")
                        files: list[dict[str, Any]] = []
                        for node_output in (entry.get("outputs") or {}).values():
                            for key in ("images", "gifs", "videos"):
                                for item in node_output.get(key, []) or []:
                                    if isinstance(item, dict) and item.get("filename"):
                                        files.append(item)
                        if files:
                            return files
                        if status.get("completed"):
                            raise ComfyUIError("ComfyUI finished but produced no image/video output")
                time.sleep(1.0)
        raise ComfyUIError(f"ComfyUI generation timed out after {timeout:.0f}s")

    def download(self, file_info: dict[str, Any]) -> tuple[bytes, str]:
        params = {
            "filename": file_info.get("filename", ""),
            "subfolder": file_info.get("subfolder", ""),
            "type": file_info.get("type", "output"),
        }
        try:
            with httpx.Client(timeout=120.0) as client:
                response = client.get(f"{self.base_url}/view", params=params)
        except httpx.HTTPError as exc:
            raise ComfyUIUnavailable(f"Could not download ComfyUI output: {exc}") from exc
        if response.status_code != 200:
            raise ComfyUIError(f"ComfyUI output download failed with HTTP {response.status_code}")
        filename = str(file_info.get("filename", "output.png"))
        return response.content, Path(filename).suffix.lower() or ".png"

    def generate(
        self,
        *,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        seed: int = 1,
        prefix: str = "openstudio",
        steps: int = 28,
        cfg: float = 6.0,
        checkpoint: str = "",
        workflow_path: str | None = None,
        workflow: dict[str, Any] | None = None,
        reference_image: str | None = None,
        timeout: float = 600.0,
        extra_replacements: dict[str, Any] | None = None,
    ) -> tuple[bytes, str, dict[str, Any]]:
        prepared_workflow = self.load_workflow(workflow_path, workflow)
        reference_name = ""
        reference = resolve_reference(reference_image)
        if reference and "{{REFERENCE_IMAGE}}" in json.dumps(prepared_workflow, ensure_ascii=False):
            reference_name = self.upload_image(reference, f"openstudio_ref_{prefix}{Path(reference).suffix or '.png'}")
        replacements = dict(PLACEHOLDER_DEFAULTS)
        replacements.update(
            {
                "PROMPT": prompt,
                "NEGATIVE_PROMPT": negative_prompt,
                "WIDTH": width,
                "HEIGHT": height,
                "SEED": seed,
                "STEPS": steps,
                "CFG": cfg,
                "CHECKPOINT": checkpoint,
                "PREFIX": prefix,
                "REFERENCE_IMAGE": reference_name,
            }
        )
        if extra_replacements:
            replacements.update(extra_replacements)
        prepared = _replace(prepared_workflow, replacements)
        prompt_id = self.queue_prompt(prepared)
        files = self.wait_for_result(prompt_id, timeout=timeout)
        binary, extension = self.download(files[0])
        metadata = {
            "prompt_id": prompt_id,
            "workflow": str(workflow_path or "inline"),
            "filename": files[0].get("filename", ""),
            "extension": extension,
            "reference_uploaded": reference_name or None,
        }
        return binary, extension, metadata


def checkpoints(url: str = "") -> list[str]:
    return ComfyUIClient(url).checkpoints()


__all__ = ["ComfyUIClient", "ComfyUIError", "ComfyUIUnavailable", "checkpoints", "resolve_reference"]
