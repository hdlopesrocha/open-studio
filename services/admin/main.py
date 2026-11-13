"""Service manager for Open Studio.

The gateway and the always-on core are intentionally small. Every component is
disabled by default and lives behind a Compose profile. This service is the only
container with access to the Docker socket; it builds and starts services on
demand and removes their containers when they are disabled.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import shutil
import signal
import socket
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException

from openstudio_common import (
    FILES_ROOT,
    INTERNAL_TOKEN,
    JOBHUB_URL,
    JobCancelled,
    JobContext,
    JobRunner,
    create_service_app,
    jobhub_headers,
    utc_now,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("admin")

VERSION = "1.0.0"
PROJECT_DIR = Path(os.getenv("OPENSTUDIO_PROJECT_DIR", "/project"))
COMPOSE_FILE = PROJECT_DIR / "docker-compose.yml"
CORE = {"files", "jobhub", "admin", "gateway", "frontend", "chat"}

META: dict[str, dict[str, Any]] = {
    "admin": {"label": "Service Manager", "description": "Builds, starts and stops optional services on demand.", "group": "Core", "requires": []},
    "gateway": {"label": "Gateway", "description": "Password, sessions, API keys and the authenticated reverse proxy.", "group": "Core", "requires": []},
    "files": {"label": "Files", "description": "Shared storage and file explorer API.", "group": "Core", "requires": []},
    "jobhub": {"label": "Job Hub", "description": "Persistent per-component queues and SSE progress.", "group": "Core", "requires": []},
    "frontend": {"label": "Frontend", "description": "Unified Vue application served by nginx.", "group": "Core", "requires": []},
    "chat": {"label": "Chat", "description": "Persistent local ChatGPT-style sessions backed by the LLM bridge.", "group": "Core AI", "requires": ["llm"]},
    "music": {
        "label": "Music Studio",
        "description": "ACE-Step 1.5 projects, songs, lyrics, takes and exports.",
        "group": "Create",
        "requires": ["music-engine"],
    },
    "music-engine": {
        "label": "ACE-Step Engine",
        "description": "GGUF/C++ music inference engine. First start downloads several GB.",
        "group": "Engines",
        "requires": [],
    },
    "dj": {
        "label": "DJ Studio",
        "description": "Track analysis, style models, AI arrangements and beat-matched mix rendering.",
        "group": "Create",
        "requires": [],
    },
    "video": {
        "label": "Video Studio",
        "description": "Video orchestration: analysis, planning, images, animation and render.",
        "group": "Create",
        "requires": ["video-audio", "video-lyrics", "video-planner", "video-animation", "video-renderer", "imagegen"],
    },
    "video-audio": {"label": "Video Audio Analysis", "description": "Librosa beat, section and spectral analysis.", "group": "Video helpers", "requires": []},
    "video-lyrics": {"label": "Video Lyrics Analysis", "description": "SRT parsing, repetition and section mapping.", "group": "Video helpers", "requires": []},
    "video-planner": {"label": "Video Planner", "description": "Deterministic scene planner with optional Ollama enrichment.", "group": "Video helpers", "requires": []},
    "video-animation": {"label": "Video Animation", "description": "FFmpeg and OpenCV camera animation renderer.", "group": "Video helpers", "requires": []},
    "video-renderer": {"label": "Video Renderer", "description": "Final assembly, subtitles and audio muxing.", "group": "Video helpers", "requires": []},
    "voice": {
        "label": "Voice / TTS",
        "description": "OmniVoice cloning/design and fast Piper voices. All TTS runs here.",
        "group": "Create",
        "requires": [],
    },
    "srt": {"label": "AI Subtitles", "description": "Whisper transcription and lyric alignment to SRT/VTT/ASS.", "group": "Create", "requires": []},
    "imagegen": {"label": "Picture Studio", "description": "Procedural, Diffusers, ComfyUI and QVAC image generation.", "group": "Create", "requires": []},
    "docs": {
        "label": "Documents",
        "description": "PDF/text → translate → summarize → narrate → SRT → ZIP.",
        "group": "Text",
        "requires": ["pdf", "translation", "summary", "voice", "ffmpeg"],
    },
    "translation": {"label": "Translation", "description": "Shared OPUS-MT/NLLB translation service.", "group": "Text", "requires": []},
    "summary": {"label": "Summaries", "description": "Hierarchical T5 summaries in English and Portuguese.", "group": "Text", "requires": []},
    "pdf": {"label": "PDF / OCR", "description": "PyMuPDF extraction and Tesseract OCR.", "group": "Text", "requires": []},
    "ffmpeg": {"label": "FFmpeg", "description": "Shared media workbench: trim, crop, transcode, concat and more.", "group": "Tools", "requires": []},
    "ytdlp": {"label": "yt-dlp", "description": "Media analysis and downloads with ffmpeg post-processing.", "group": "Tools", "requires": []},
    "qvac": {"label": "QVAC", "description": "Tether QVAC video/image diffusion and upscaling.", "group": "Create", "requires": []},
    "llm": {"label": "LLM Bridge", "description": "OpenAI-compatible bridge used by lyrics and video planning.", "group": "Core AI", "requires": ["ollama"]},
    "ollama": {"label": "Ollama", "description": "Local LLM runtime. Pull a model with `make models-llm`.", "group": "Core AI", "requires": []},
}

runner = JobRunner("admin")
router = APIRouter(prefix="/api/admin", tags=["services"])
SERVICE_NAME = "admin"
CONTROL_LOCK = asyncio.Lock()

MODEL_ROOT = Path(os.getenv("OPENSTUDIO_MODELS_DIR", "/data/models"))
PIPER_DIR = Path(os.getenv("PIPER_MODELS_DIR", "").strip() or str(FILES_ROOT / "voices" / "piper"))
QVAC_HOME_MODELS = Path(os.getenv("QVAC_HOME_MODELS_DIR", "/data/home/.qvac/models"))
OMNIVOICE_MODEL = os.getenv("OMNIVOICE_MODEL", "k2-fsa/OmniVoice").strip() or "k2-fsa/OmniVoice"
QVAC_URL = os.getenv("QVAC_URL", "http://qvac:8000").rstrip("/")

# Model packs exposed in Settings → Models. Each entry is installed by a
# normal job-hub job, so progress and retries are visible alongside all other
# work. Commands deliberately reuse each service's own downloader.
MODEL_ITEMS: list[dict[str, Any]] = [
    {
        "id": "llm-llama3.2-3b",
        "label": "Llama 3.2 3B",
        "group": "Language",
        "description": "Ollama model used by the lyricist and video planner.",
        "size": "~2.0 GB",
        "kind": "ollama",
        "service": "ollama",
        "model": "llama3.2:3b",
    },
    {
        "id": "llm-qwen3-4b",
        "label": "Qwen3 4B",
        "group": "Language",
        "description": "Command and tool-use model for the Chat agent.",
        "size": "~2.5 GB",
        "kind": "ollama",
        "service": "ollama",
        "model": "qwen3:4b",
    },
    {
        "id": "music-ace-step",
        "label": "ACE-Step 1.5 Turbo (Q8_0)",
        "group": "Music",
        "description": "Fast 2B turbo checkpoint with the shared 5Hz LM, text encoder and VAE.",
        "size": "~4.4 GB",
        "kind": "music",
        "service": "music-engine",
        "variant": "turbo",
        "quant": "Q8_0",
        "lm_size": "0.6B",
    },
    {
        "id": "music-ace-step-base",
        "label": "ACE-Step 1.5 Base (Q8_0)",
        "group": "Music",
        "description": "2B base checkpoint for editing, completion and stem extraction. Uses 50 diffusion steps.",
        "size": "~4.4 GB",
        "kind": "music",
        "service": "music-engine",
        "variant": "base",
        "quant": "Q8_0",
        "lm_size": "0.6B",
    },
    {
        "id": "music-ace-step-sft",
        "label": "ACE-Step 1.5 SFT (Q8_0)",
        "group": "Music",
        "description": "Higher-fidelity 2B SFT checkpoint for final takes. Slower than turbo.",
        "size": "~4.4 GB",
        "kind": "music",
        "service": "music-engine",
        "variant": "sft",
        "quant": "Q8_0",
        "lm_size": "0.6B",
    },
    {
        "id": "music-ace-step-turbo-shift1",
        "label": "ACE-Step 1.5 Turbo · Shift 1",
        "group": "Music",
        "description": "Turbo variant with a lower timestep shift profile for alternate motion character.",
        "size": "~4.4 GB",
        "kind": "music",
        "service": "music-engine",
        "variant": "turbo-shift1",
        "quant": "Q8_0",
        "lm_size": "0.6B",
    },
    {
        "id": "music-ace-step-turbo-shift3",
        "label": "ACE-Step 1.5 Turbo · Shift 3",
        "group": "Music",
        "description": "Turbo variant with a higher timestep shift profile for alternate motion character.",
        "size": "~4.4 GB",
        "kind": "music",
        "service": "music-engine",
        "variant": "turbo-shift3",
        "quant": "Q8_0",
        "lm_size": "0.6B",
    },
    {
        "id": "music-ace-step-turbo-continuous",
        "label": "ACE-Step 1.5 Turbo · Continuous",
        "group": "Music",
        "description": "Turbo checkpoint trained with a continuous noise schedule.",
        "size": "~4.4 GB",
        "kind": "music",
        "service": "music-engine",
        "variant": "turbo-continuous",
        "quant": "Q8_0",
        "lm_size": "0.6B",
    },
    {
        "id": "music-ace-step-xl-base",
        "label": "ACE-Step 1.5 XL Base (Q8_0)",
        "group": "Music",
        "description": "4B XL base checkpoint for the highest-quality editing workflow. Needs substantially more memory.",
        "size": "~7.1 GB",
        "kind": "music",
        "service": "music-engine",
        "variant": "xl-base",
        "quant": "Q8_0",
        "lm_size": "0.6B",
    },
    {
        "id": "whisper-large-v3",
        "label": "Whisper large-v3",
        "group": "Subtitles",
        "description": "Highest-quality faster-whisper transcription model.",
        "size": "~3.0 GB",
        "kind": "whisper",
        "service": "srt",
        "model": "large-v3",
    },
    {
        "id": "whisper-small",
        "label": "Whisper small",
        "group": "Subtitles",
        "description": "Fast, compact Whisper model for quick subtitle drafts.",
        "size": "~500 MB",
        "kind": "whisper",
        "service": "srt",
        "model": "small",
    },
    {
        "id": "whisper-base",
        "label": "Whisper base",
        "group": "Subtitles",
        "description": "Very small model for fast drafts and low-memory machines.",
        "size": "~150 MB",
        "kind": "whisper",
        "service": "srt",
        "model": "base",
    },
    {
        "id": "whisper-medium",
        "label": "Whisper medium",
        "group": "Subtitles",
        "description": "Middle ground between small and large-v3 accuracy.",
        "size": "~1.5 GB",
        "kind": "whisper",
        "service": "srt",
        "model": "medium",
    },
    {
        "id": "translation-opus",
        "label": "OPUS-MT Portuguese ↔ English",
        "group": "Text",
        "description": "Fast bilingual Portuguese/English translation models.",
        "size": "~600 MB",
        "kind": "translation",
        "service": "translation",
        "models": "opus",
    },
    {
        "id": "translation-nllb",
        "label": "NLLB-200 multilingual",
        "group": "Text",
        "description": "Optional 600M multilingual translation model for many languages.",
        "size": "~2.4 GB",
        "kind": "translation",
        "service": "translation",
        "models": "nllb",
    },
    {
        "id": "translation-all",
        "label": "Translation models (all)",
        "group": "Text",
        "description": "Both OPUS-MT and NLLB-200 translation model sets.",
        "size": "~2.4 GB",
        "kind": "translation",
        "service": "translation",
        "models": "all",
    },
    {
        "id": "summary-en",
        "label": "Summary · English",
        "group": "Text",
        "description": "T5 English summarization checkpoint.",
        "size": "~250 MB",
        "kind": "summary",
        "service": "summary",
        "models": "en",
    },
    {
        "id": "summary-pt",
        "label": "Summary · Portuguese",
        "group": "Text",
        "description": "T5 Portuguese summarization checkpoint.",
        "size": "~250 MB",
        "kind": "summary",
        "service": "summary",
        "models": "pt",
    },
    {
        "id": "summary-all",
        "label": "Summary models (all)",
        "group": "Text",
        "description": "English and Portuguese T5 summarization checkpoints.",
        "size": "~500 MB",
        "kind": "summary",
        "service": "summary",
        "models": "all",
    },
    {
        "id": "piper-voices",
        "label": "Piper built-in voices",
        "group": "Voice",
        "description": "Male and female US/UK English, French, German, Spanish and Portuguese voices.",
        "size": "~1.0 GB",
        "kind": "piper",
        "service": "voice",
    },
    {
        "id": "omnivoice",
        "label": "OmniVoice model",
        "group": "Voice",
        "description": "Cloning, voice design and transcription weights. Large first download.",
        "size": "4–8 GB",
        "kind": "omnivoice",
        "service": "voice",
    },
    {
        "id": "image-sd-turbo",
        "label": "SD Turbo",
        "group": "Images",
        "description": "Fast 1–4 step 512px Diffusers checkpoint for previews.",
        "size": "~2.5 GB",
        "kind": "diffusers",
        "service": "imagegen",
        "repo": "stabilityai/sd-turbo",
    },
    {
        "id": "image-sd15",
        "label": "Stable Diffusion 1.5",
        "group": "Images",
        "description": "Classic 512px base model with a large LoRA ecosystem.",
        "size": "~4 GB",
        "kind": "diffusers",
        "service": "imagegen",
        "repo": "runwayml/stable-diffusion-v1-5",
    },
    {
        "id": "image-sdxl",
        "label": "SDXL Base 1.0",
        "group": "Images",
        "description": "1024px photorealistic and illustration model.",
        "size": "~7 GB",
        "kind": "diffusers",
        "service": "imagegen",
        "repo": "stabilityai/stable-diffusion-xl-base-1.0",
    },
    {
        "id": "image-sdxl-turbo",
        "label": "SDXL Turbo",
        "group": "Images",
        "description": "Fast 1–4 step 1024px preview model.",
        "size": "~7 GB",
        "kind": "diffusers",
        "service": "imagegen",
        "repo": "stabilityai/sdxl-turbo",
    },
    {
        "id": "image-flux-schnell",
        "label": "FLUX.1 Schnell",
        "group": "Images",
        "description": "High-quality 4-step FLUX model; needs substantial VRAM and disk.",
        "size": "~24 GB",
        "kind": "diffusers",
        "service": "imagegen",
        "repo": "black-forest-labs/FLUX.1-schnell",
    },
    {
        "id": "qvac-sd21",
        "label": "QVAC SD 2.1 1B Q4",
        "group": "QVAC",
        "description": "CPU-friendly QVAC image diffusion model used by Picture Studio.",
        "size": "~2.1 GB",
        "kind": "qvac",
        "service": "qvac",
        "source": os.getenv("QVAC_IMAGE_MODEL", "SD_V2_1_1B_Q4_0"),
    },
]


def compose_command() -> list[str]:
    command = ["docker", "compose", "--project-directory", str(PROJECT_DIR), "-f", str(COMPOSE_FILE)]
    overrides = os.getenv("COMPOSE_OVERRIDES", "").strip()
    if overrides:
        for token in shlex.split(overrides):
            if token == "-f":
                continue
            candidate = Path(token)
            command += ["-f", str(candidate if candidate.is_absolute() else PROJECT_DIR / candidate)]
    return command


_HOST_DIRS: tuple[str, str] | None = None


async def host_dirs() -> tuple[str, str]:
    """Return the host project and data directories.

    Compose runs inside this container, but bind-mount sources are resolved by
    the Docker daemon on the host. A relative ``OPENSTUDIO_DATA_DIR`` (for
    example the default ``./data``) would therefore become ``/project/data``
    and silently create a second data tree. Read our own mounts through the
    Docker socket so every service managed from here always uses the host
    paths that the core stack was started with.
    """
    global _HOST_DIRS
    if _HOST_DIRS is not None:
        return _HOST_DIRS

    data_dir = ""
    repo_dir = ""
    try:
        process = await asyncio.create_subprocess_exec(
            "docker",
            "inspect",
            socket.gethostname(),
            "--format",
            "{{json .Mounts}}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await process.communicate()
        if process.returncode == 0 and stdout.strip():
            mounts = json.loads(stdout.decode("utf-8", "replace"))
            for mount in mounts if isinstance(mounts, list) else []:
                destination = str(mount.get("Destination") or "")
                source = str(mount.get("Source") or "")
                if destination == "/data/files" and source:
                    data_dir = str(Path(source).parent)
                elif destination == "/project" and source:
                    repo_dir = source
    except (OSError, ValueError):
        log.warning("Could not inspect the admin container mounts", exc_info=True)

    if not data_dir:
        configured = os.getenv("OPENSTUDIO_DATA_DIR", "")
        if os.path.isabs(configured):
            data_dir = configured
        else:
            # There is no way to turn a path relative to the host repository
            # into an absolute host path without Docker's help. Fail loudly
            # rather than writing to /project/data inside the admin container.
            raise RuntimeError(
                "Could not determine the host data directory. "
                "Set OPENSTUDIO_DATA_DIR to an absolute path (make init does this)."
            )
    if not repo_dir:
        configured = os.getenv("OPENSTUDIO_REPO_DIR", "")
        repo_dir = configured if os.path.isabs(configured) else str(PROJECT_DIR)

    _HOST_DIRS = (data_dir, repo_dir)
    return _HOST_DIRS


async def env() -> dict[str, str]:
    data_dir, repo_dir = await host_dirs()
    result = os.environ.copy()
    result["COMPOSE_PROJECT_NAME"] = "openstudio"
    result["OPENSTUDIO_DATA_DIR"] = data_dir
    result["OPENSTUDIO_REPO_DIR"] = repo_dir
    return result


async def run_command(
    args: list[str],
    *,
    ctx: JobContext | None = None,
    timeout: float = 6 * 3600,
    stage_label: str | None = None,
) -> tuple[int, list[str]]:
    log.info("admin command: %s", " ".join(shlex.quote(part) for part in args))
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(PROJECT_DIR),
        env=await env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    lines: list[str] = []
    started = asyncio.get_running_loop().time()
    try:
        assert process.stdout is not None
        while True:
            try:
                raw = await asyncio.wait_for(process.stdout.readline(), timeout=1.0)
            except asyncio.TimeoutError:
                if ctx is not None:
                    await ctx.check()
                if asyncio.get_running_loop().time() - started > timeout:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    raise TimeoutError(f"Command exceeded {timeout:.0f}s")
                continue
            if not raw:
                break
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                lines.append(line)
                if ctx is not None and len(lines) > 500:
                    del lines[:100]
                if ctx is not None:
                    stage = stage_label or ("Building" if "build" in " ".join(args[:8]) else "Applying")
                    progress = min(94.0, 5.0 + len(lines) * 0.6)
                    await ctx.report(progress, stage, line[:180])
        code = await process.wait()
        return code, lines
    finally:
        if process.returncode is None:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            await process.wait()


async def compose_json(args: list[str]) -> Any:
    code, lines = await run_command([*compose_command(), *args], timeout=60)
    if code != 0:
        raise HTTPException(status_code=502, detail="\n".join(lines[-20:]) or "docker compose failed")
    text = "\n".join(lines).strip()
    if not text:
        return []
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        items = []
        for line in text.splitlines():
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return items


async def compose_services() -> list[str]:
    code, lines = await run_command(
        [*compose_command(), "--profile", "services", "config", "--services"], timeout=60
    )
    if code != 0:
        raise HTTPException(status_code=502, detail="\n".join(lines[-20:]))
    return [line.strip() for line in lines if line.strip() and not line.startswith("WARN")]


async def compose_config() -> dict[str, Any]:
    data = await compose_json(["--profile", "services", "config", "--format", "json"])
    return data if isinstance(data, dict) else {}


def required_services(name: str, configured: dict[str, Any]) -> list[str]:
    """Resolve optional dependencies that must be started with ``name``.

    Core services are deliberately excluded: they are always on and recreating
    them from a job would pull the job hub out from under the running job.
    """
    ordered: list[str] = []
    visited: set[str] = set()

    def walk(current: str) -> None:
        if current in visited:
            return
        visited.add(current)
        config = configured.get(current)
        config = config if isinstance(config, dict) else {}
        dependencies: set[str] = set()
        depends_on = config.get("depends_on")
        if isinstance(depends_on, dict):
            dependencies.update(str(item) for item in depends_on)
        elif isinstance(depends_on, list):
            dependencies.update(str(item) for item in depends_on)
        dependencies.update(META.get(current, {}).get("requires") or [])
        for dependency in sorted(dependencies):
            if dependency == name or dependency in CORE or dependency not in configured:
                continue
            walk(dependency)
            if dependency not in ordered:
                ordered.append(dependency)

    walk(name)
    return ordered


async def image_exists(image: str) -> bool:
    if not image:
        return False
    process = await asyncio.create_subprocess_exec(
        "docker", "image", "inspect", image,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    return await process.wait() == 0


def _dir_has_files(path: Path) -> bool:
    try:
        return path.is_dir() and any(entry.is_file() for entry in path.rglob("*"))
    except OSError:
        return False


def _translation_model_ready(path: Path) -> bool:
    """A translation checkpoint needs config, weights and a tokenizer."""
    if not path.is_dir() or not (path / "config.json").is_file():
        return False
    weights = ("model.safetensors", "pytorch_model.bin", "model.safetensors.index.json", "pytorch_model.bin.index.json")
    tokenizers = ("tokenizer.json", "tokenizer_config.json", "source.spm", "vocab.json", "sentencepiece.bpe.model")
    return any((path / name).is_file() and (path / name).stat().st_size > 10 * 1024 * 1024 for name in weights) and any((path / name).is_file() for name in tokenizers)


def _hf_cache(repo: str) -> Path:
    return MODEL_ROOT / "huggingface" / "hub" / f"models--{repo.replace('/', '--')}"


def _hf_present(repo: str) -> bool:
    snapshots = _hf_cache(repo) / "snapshots"
    try:
        return snapshots.is_dir() and any(entry.is_dir() and any(entry.iterdir()) for entry in snapshots.iterdir())
    except OSError:
        return False


def _whisper_present(model: str) -> bool:
    cache = MODEL_ROOT / "whisper"
    if (cache / model).exists():
        return True
    patterns = [
        f"models--Systran--faster-whisper-{model}",
        f"models--Systran--faster-distil-whisper-{model.replace('distil-', '')}",
        f"models--*--*{model}*",
    ]
    return any(next(cache.glob(pattern), None) is not None for pattern in patterns)


def _piper_count() -> int:
    for directory in (PIPER_DIR, MODEL_ROOT / "piper"):
        try:
            count = len(list(directory.rglob("*.onnx")))
        except OSError:
            continue
        if count:
            return count
    return 0


async def _ollama_installed(model: str) -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get("http://ollama:11434/api/tags")
        if response.status_code >= 400:
            return False, f"Ollama returned HTTP {response.status_code}"
        models = response.json().get("models") or []
        names = [str(item.get("name") or item.get("model") or "") for item in models if isinstance(item, dict)]
        installed = any(name == model or name.startswith(model + ":") or name.startswith(model) for name in names)
        return installed, "installed" if installed else "Ollama is running but this model is missing"
    except Exception as exc:  # noqa: BLE001
        return False, f"Ollama is not reachable: {exc}"


async def _qvac_installed(source: str) -> tuple[bool, str]:
    if _dir_has_files(MODEL_ROOT / "qvac") or _dir_has_files(QVAC_HOME_MODELS):
        return True, "QVAC model data is present"
    try:
        async with httpx.AsyncClient(timeout=3.0, headers=jobhub_headers()) as client:
            response = await client.get(f"{QVAC_URL}/api/qvac/models/loaded")
        if response.status_code >= 400:
            return False, f"QVAC returned HTTP {response.status_code}"
        items = response.json().get("items") or []
        names = [str(item.get("modelName") or item.get("name") or "") for item in items if isinstance(item, dict)]
        installed = any(source == name or source in name for name in names)
        return installed, "loaded in QVAC" if installed else "not loaded"
    except Exception as exc:  # noqa: BLE001
        return False, f"QVAC is not reachable: {exc}"


def _acestep_pack_files(item: dict[str, Any]) -> set[str]:
    variant = str(item.get("variant") or "turbo")
    quant = str(item.get("quant") or "Q8_0")
    lm_size = str(item.get("lm_size") or "0.6B")
    return {
        "vae-BF16.gguf",
        "Qwen3-Embedding-0.6B-Q8_0.gguf",
        f"acestep-5Hz-lm-{lm_size}-Q8_0.gguf",
        f"acestep-v15-{variant}-{quant}.gguf",
    }


async def model_status(item: dict[str, Any]) -> dict[str, Any]:
    kind = str(item.get("kind") or "")
    installed = False
    detail = ""
    if kind == "ollama":
        installed, detail = await _ollama_installed(str(item.get("model") or ""))
    elif kind == "music":
        directory = MODEL_ROOT / "acestep"
        required = _acestep_pack_files(item)
        try:
            present = {entry.name for entry in directory.glob("*.gguf")}
        except OSError:
            present = set()
        installed = required.issubset(present)
        missing = sorted(required - present)
        detail = (
            f"{len(required & present)}/{len(required)} GGUF files present"
            if not missing
            else f"missing: {', '.join(missing)}"
        )
    elif kind == "whisper":
        installed = _whisper_present(str(item.get("model") or "large-v3"))
        detail = "installed" if installed else "not downloaded"
    elif kind == "translation":
        directory = MODEL_ROOT / "translation"
        group = str(item.get("models") or "all")
        required = {
            "opus": ("pt-en", "en-pt"),
            "nllb": ("nllb-200-distilled-600M",),
            "all": ("pt-en", "en-pt", "nllb-200-distilled-600M"),
        }.get(group, ("pt-en", "en-pt", "nllb-200-distilled-600M"))
        installed = all(_translation_model_ready(directory / name) for name in required)
        detail = "installed" if installed else f"missing: {', '.join(name for name in required if not _translation_model_ready(directory / name))}"
    elif kind == "summary":
        directory = MODEL_ROOT / "summary"
        group = str(item.get("models") or "all")
        required = {"en": ("en",), "pt": ("pt",), "all": ("en", "pt")}.get(group, ("en", "pt"))
        installed = all(_dir_has_files(directory / name) for name in required)
        detail = "installed" if installed else f"missing: {', '.join(name for name in required if not _dir_has_files(directory / name))}"
    elif kind == "piper":
        count = _piper_count()
        installed = count >= 15
        detail = f"{count}/15 voices installed"
    elif kind == "omnivoice":
        installed = _hf_present(OMNIVOICE_MODEL)
        detail = "installed" if installed else "not downloaded"
    elif kind == "diffusers":
        installed = _hf_present(str(item.get("repo") or ""))
        detail = "installed" if installed else "not downloaded"
    elif kind == "qvac":
        installed, detail = await _qvac_installed(str(item.get("source") or ""))
    return {**item, "installed": installed, "detail": detail}


async def _ensure_service_image(service: str, ctx: JobContext) -> None:
    configured = await compose_config()
    service_cfg = (configured.get("services") or {}).get(service) or {}
    image = str(service_cfg.get("image") or "")
    if image and await image_exists(image):
        return
    await ctx.report(4.0, "Building", f"Building the {service} image before downloading its models")
    code, lines = await run_command([*compose_command(), "build", service], ctx=ctx, timeout=6 * 3600)
    if code != 0:
        raise RuntimeError("\n".join(lines[-30:]) or f"Could not build {service}")


async def _music_engine_busy() -> bool:
    try:
        async with httpx.AsyncClient(timeout=8.0, headers=jobhub_headers()) as client:
            response = await client.get(
                f"{JOBHUB_URL}/api/jobs",
                params={"component": "music", "status": "running,queued", "limit": 1},
            )
        return response.status_code >= 400 or bool(response.json().get("items"))
    except (httpx.HTTPError, ValueError):
        # Do not restart the engine if we cannot prove it is idle.
        return True


async def _restart_music_engine(ctx: JobContext, lines: list[str]) -> None:
    if await _music_engine_busy():
        lines.append("ACE-Step model installed; engine restart skipped because a Music job is active.")
        return
    await ctx.report(95.0, "Reloading engine", "Restarting the ACE-Step engine to discover the new model")
    code, out = await run_command(
        [*compose_command(), "restart", "music-engine"],
        ctx=ctx,
        timeout=900,
        stage_label="Reloading engine",
    )
    lines.extend(out)
    if code != 0:
        lines.append("ACE-Step model installed, but the engine restart failed; restart music-engine manually.")


async def _install_model(ctx: JobContext) -> dict[str, Any]:
    model_id = str(ctx.params.get("model_id") or "")
    item = next((entry for entry in MODEL_ITEMS if entry["id"] == model_id), None)
    if item is None:
        raise ValueError("Unknown model pack")
    kind = str(item.get("kind") or "")
    service = str(item.get("service") or "")
    await ctx.report(2.0, "Preparing", str(item.get("label") or model_id))
    lines: list[str] = []

    if kind == "ollama":
        model = str(item.get("model") or "")
        up_command = [*compose_command(), "--profile", "services", "up", "-d", "--no-deps", "ollama"]
        code, out = await run_command(up_command, ctx=ctx, timeout=900, stage_label="Starting")
        lines.extend(out)
        if code != 0:
            raise RuntimeError("\n".join(out[-30:]) or "Could not start Ollama")
        command = [*compose_command(), "exec", "-T", "ollama", "ollama", "pull", model]
        code, out = await run_command(command, ctx=ctx, timeout=6 * 3600, stage_label="Downloading model")
        lines.extend(out)
        if code != 0:
            raise RuntimeError("\n".join(out[-30:]) or "Ollama pull failed")

    elif kind == "music":
        await _ensure_service_image("music-engine", ctx)
        command = [
            *compose_command(), "--profile", "services", "run", "--rm", "--no-deps",
            "-e", "ACESTEP_CPP_DOWNLOAD_MODELS=true",
            "-e", f"ACESTEP_CPP_DIT_VARIANT={item.get('variant') or 'turbo'}",
            "-e", f"ACESTEP_CPP_QUANT={item.get('quant') or 'Q8_0'}",
            "-e", f"ACESTEP_CPP_LM_SIZE={item.get('lm_size') or '0.6B'}",
            "--entrypoint", "/opt/acestep/download-models.sh", "music-engine",
        ]
        code, out = await run_command(command, ctx=ctx, timeout=12 * 3600, stage_label="Downloading model")
        lines.extend(out)
        if code != 0:
            raise RuntimeError("\n".join(out[-30:]) or "ACE-Step download failed")
        await _restart_music_engine(ctx, lines)

    elif kind == "whisper":
        await _ensure_service_image("srt", ctx)
        model = str(item.get("model") or "large-v3")
        code = (
            "from faster_whisper import WhisperModel; "
            f"WhisperModel({model!r}, download_root='/data/models/whisper')"
        )
        command = [
            *compose_command(), "--profile", "services", "run", "--rm", "--no-deps",
            "--entrypoint", "python", "srt", "-c", code,
        ]
        code_value, out = await run_command(command, ctx=ctx, timeout=6 * 3600, stage_label="Downloading model")
        lines.extend(out)
        if code_value != 0:
            raise RuntimeError("\n".join(out[-30:]) or "Whisper download failed")

    elif kind == "translation":
        await _ensure_service_image("translation", ctx)
        selected = str(item.get("models") or "all")
        command = [
            *compose_command(), "--profile", "services", "run", "--rm", "--no-deps",
            "--entrypoint", "download-models", "translation", "--models", selected,
        ]
        code, out = await run_command(command, ctx=ctx, timeout=6 * 3600, stage_label="Downloading model")
        lines.extend(out)
        if code != 0:
            raise RuntimeError("\n".join(out[-30:]) or "Translation download failed")

    elif kind == "summary":
        await _ensure_service_image("summary", ctx)
        selected = str(item.get("models") or "all")
        command = [
            *compose_command(), "--profile", "services", "run", "--rm", "--no-deps",
            "--entrypoint", "download-models", "summary", "--models", selected,
        ]
        code, out = await run_command(command, ctx=ctx, timeout=6 * 3600, stage_label="Downloading model")
        lines.extend(out)
        if code != 0:
            raise RuntimeError("\n".join(out[-30:]) or "Summary download failed")

    elif kind == "piper":
        await _ensure_service_image("voice", ctx)
        command = [
            *compose_command(), "--profile", "services", "run", "--rm", "--no-deps",
            "--entrypoint", "voice-download-models", "voice",
        ]
        code, out = await run_command(command, ctx=ctx, timeout=6 * 3600, stage_label="Downloading voices")
        lines.extend(out)
        if code != 0:
            raise RuntimeError("\n".join(out[-30:]) or "Piper voice download failed")

    elif kind == "omnivoice":
        await _ensure_service_image("voice", ctx)
        code = (
            "from huggingface_hub import snapshot_download; "
            f"snapshot_download({OMNIVOICE_MODEL!r})"
        )
        command = [
            *compose_command(), "--profile", "services", "run", "--rm", "--no-deps",
            "--entrypoint", "python", "voice", "-c", code,
        ]
        code_value, out = await run_command(command, ctx=ctx, timeout=12 * 3600, stage_label="Downloading model")
        lines.extend(out)
        if code_value != 0:
            raise RuntimeError("\n".join(out[-30:]) or "OmniVoice download failed")

    elif kind == "diffusers":
        await _ensure_service_image("imagegen", ctx)
        repo = str(item.get("repo") or "")
        code = f"from huggingface_hub import snapshot_download; snapshot_download({repo!r})"
        command = [
            *compose_command(), "--profile", "services", "run", "--rm", "--no-deps",
            "--entrypoint", "python", "imagegen", "-c", code,
        ]
        code_value, out = await run_command(command, ctx=ctx, timeout=24 * 3600, stage_label="Downloading model")
        lines.extend(out)
        if code_value != 0:
            raise RuntimeError("\n".join(out[-30:]) or "Diffusers download failed")

    elif kind == "qvac":
        await _ensure_service_image("qvac", ctx)
        up_command = [*compose_command(), "--profile", "services", "up", "-d", "--no-deps", "qvac"]
        code, out = await run_command(up_command, ctx=ctx, timeout=900, stage_label="Starting")
        lines.extend(out)
        if code != 0:
            raise RuntimeError("\n".join(out[-30:]) or "Could not start QVAC")
        await ctx.report(12.0, "Downloading model", "QVAC is loading and caching the model")
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=20.0, read=24 * 3600, write=60.0, pool=20.0),
            headers=jobhub_headers(),
        ) as client:
            response = await client.post(
                f"{QVAC_URL}/api/qvac/models/load",
                json={"modelSrc": str(item.get("source") or "")},
            )
        if response.status_code >= 400:
            raise RuntimeError(f"QVAC rejected the model ({response.status_code}): {response.text[:800]}")
        lines.append(f"QVAC loaded {item.get('source')}")

    else:
        raise ValueError(f"Unsupported model kind: {kind}")

    await ctx.report(98.0, "Verifying", "Checking installed model files")
    status = await model_status(item)
    if not status["installed"]:
        raise RuntimeError(f"Download finished but verification failed: {status['detail']}")
    await ctx.report(100.0, "Complete", f"{item['label']} installed")
    return {
        "message": f"{item['label']} installed.",
        "data": {"model": status, "output": lines[-30:]},
    }


def container_maps(containers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for container in containers:
        service = container.get("Service") or container.get("service")
        if service:
            mapping[service] = container
    return mapping


async def services_payload() -> list[dict[str, Any]]:
    config = await compose_config()
    configured = config.get("services", {}) if isinstance(config.get("services"), dict) else {}
    containers = await compose_json(["ps", "-a", "--format", "json"])
    if isinstance(containers, dict):
        containers = [containers]
    by_service = container_maps([item for item in containers if isinstance(item, dict)])
    names = list(configured.keys())
    for name in META:
        if name not in names:
            names.append(name)
    result: list[dict[str, Any]] = []
    for name in sorted(names):
        cfg = configured.get(name, {}) if isinstance(configured.get(name), dict) else {}
        container = by_service.get(name, {})
        state = str(container.get("State") or container.get("state") or "").lower()
        health = str(container.get("Health") or container.get("health") or "").lower()
        image = str(cfg.get("image") or container.get("Image") or "")
        meta = META.get(name, {})
        is_core = name in CORE
        running = state == "running"
        enabled = running or is_core
        if state == "running":
            health_label = health or "running"
        elif state in {"exited", "created", "dead"}:
            health_label = state
        elif is_core:
            health_label = "core"
        else:
            health_label = "disabled"
        result.append(
            {
                "name": name,
                "label": meta.get("label") or name.replace("-", " ").title(),
                "description": meta.get("description") or cfg.get("description") or "",
                "group": meta.get("group") or ("Core" if is_core else "Services"),
                "core": is_core,
                "enabled": enabled,
                "running": running,
                "state": state or "absent",
                "health": health_label,
                "image": image,
                "image_built": await image_exists(image),
                "requires": meta.get("requires") or [],
                "container": container.get("Name") or container.get("name") or "",
                "status": str(container.get("Status") or container.get("status") or ""),
            }
        )
    return result


def _model_groups(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = ["Language", "Music", "Voice", "Subtitles", "Text", "Images", "QVAC"]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(str(item.get("group") or "Other"), []).append(item)
    return [
        {"group": group, "items": grouped[group]}
        for group in order + sorted(set(grouped) - set(order))
        if group in grouped
    ]


async def submit_model_job(item: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "component": "models",
        "action": "install_model",
        "title": f"Install model · {item['label']}",
        "params": {"model_id": item["id"]},
    }
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=jobhub_headers()) as client:
            response = await client.post(f"{JOBHUB_URL}/api/jobs", json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Job hub unreachable: {exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=response.text[:1000] or "Could not create model job")
    return response.json()


@router.get("/models")
async def list_models() -> dict[str, Any]:
    items = await asyncio.gather(*(model_status(item) for item in MODEL_ITEMS))
    groups = _model_groups(list(items))
    return {
        "items": list(items),
        "groups": groups,
        "total": len(items),
        "installed": sum(1 for item in items if item.get("installed")),
        "generated_at": utc_now(),
    }


@router.post("/models/{model_id}/install")
async def install_model(model_id: str, force: bool = False) -> dict[str, Any]:
    item = next((entry for entry in MODEL_ITEMS if entry["id"] == model_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Unknown model pack")
    status = await model_status(item)
    if status.get("installed") and not force:
        return {"item": status, "job": None, "message": "Model is already installed; use Re-check to verify it"}
    job = await submit_model_job(item)
    return {"item": status, "job": job, "message": f"{item['label']} download queued"}


@router.get("/services")
async def list_services() -> dict[str, Any]:
    items = await services_payload()
    return {
        "items": items,
        "core": [item for item in items if item["core"]],
        "optional": [item for item in items if not item["core"]],
        "enabled": sum(1 for item in items if item["enabled"]),
        "running": sum(1 for item in items if item["running"]),
        "total": len(items),
        "generated_at": utc_now(),
    }


@router.get("/services/{name}/logs")
async def service_logs(name: str, lines: int = 200, x_internal_token: str = Header(default="")) -> dict[str, Any]:
    if x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid internal token")
    lines = max(10, min(1000, lines))
    code, output = await run_command([*compose_command(), "logs", "--no-color", "--tail", str(lines), name], timeout=60)
    return {"service": name, "lines": output, "code": code}


async def submit(action: str, name: str) -> dict[str, Any]:
    if name not in META and name not in CORE:
        raise HTTPException(status_code=404, detail="Unknown service")
    if name in CORE and action != "restart":
        raise HTTPException(status_code=409, detail="Core services are always enabled")
    body = {
        "component": "admin",
        "action": action,
        "title": f"{action.title()} service · {name}",
        "params": {"service": name},
    }
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=jobhub_headers()) as client:
            response = await client.post(f"{JOBHUB_URL}/api/jobs", json=body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Job hub unreachable: {exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=response.text[:1000])
    return response.json()


@router.post("/services/{name}/enable")
async def enable(name: str) -> dict[str, Any]:
    return await submit("enable", name)


@router.post("/services/{name}/disable")
async def disable(name: str) -> dict[str, Any]:
    return await submit("disable", name)


@router.post("/services/{name}/build")
async def build(name: str) -> dict[str, Any]:
    return await submit("build", name)


@router.post("/services/{name}/restart")
async def restart(name: str) -> dict[str, Any]:
    return await submit("restart", name)


@router.post("/files/delete-all")
async def delete_all_files(payload: dict[str, Any]) -> dict[str, Any]:
    if str(payload.get("confirm") or "") != "DELETE":
        raise HTTPException(status_code=422, detail='Send {"confirm":"DELETE"} to confirm')
    root = FILES_ROOT.resolve()
    removed = 0
    freed = 0
    for child in list(root.iterdir()):
        try:
            if child.is_dir():
                freed += sum(f.stat().st_size for f in child.rglob("*") if f.is_file())
                shutil.rmtree(child)
            else:
                freed += child.stat().st_size
                child.unlink()
            removed += 1
        except OSError:
            log.warning("Could not remove %s", child, exc_info=True)
    for name in ("music", "dj", "video", "voice", "voices", "documents", "images", "subtitles", "ffmpeg", "ytdlp", "qvac", "uploads", "tmp"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return {"removed": removed, "bytes_freed": freed, "root": str(root), "deleted_at": utc_now()}


async def _control_locked(ctx: JobContext) -> dict[str, Any]:
    name = str(ctx.params.get("service") or "")
    action = ctx.action
    if not name:
        raise ValueError("service is required")
    if name in CORE and action != "restart":
        raise ValueError("core services are always enabled")
    if action == "enable":
        await ctx.report(2.0, "Starting", f"Preparing {name}")
        configured = await compose_config()
        service_cfg = (configured.get("services") or {}).get(name) or {}
        image = str(service_cfg.get("image") or "")
        built = await image_exists(image) if image else False
        dependencies = required_services(name, configured.get("services") or {})
        # --no-deps keeps Compose from touching the always-on core (most
        # importantly jobhub) just because it is listed as a dependency.
        command = [*compose_command(), "--profile", "services", "up", "-d", "--no-deps"]
        if not built:
            command.append("--build")
            await ctx.report(4.0, "Building", f"Image for {name} is missing; building it now")
        if dependencies:
            await ctx.report(3.0, "Starting", f"Required services: {', '.join(dependencies)}")
        command += [*dependencies, name]
        code, lines = await run_command(command, ctx=ctx)
        if code != 0:
            raise RuntimeError("\n".join(lines[-30:]) or "docker compose up failed")
        await ctx.report(100.0, "Complete", f"{name} enabled")
        return {
            "message": f"{name} enabled",
            "data": {"service": name, "built": not built, "image": image, "output": lines[-20:]},
        }
    if action == "disable":
        await ctx.report(10.0, "Stopping", f"Stopping {name}")
        code, lines = await run_command([*compose_command(), "stop", name], ctx=ctx, timeout=600)
        await run_command([*compose_command(), "rm", "-f", name], ctx=ctx, timeout=600)
        await ctx.report(100.0, "Complete", f"{name} disabled and removed")
        return {"message": f"{name} disabled", "data": {"service": name, "output": lines[-20:]}}
    if action == "build":
        await ctx.report(2.0, "Building", f"Building {name}")
        code, lines = await run_command([*compose_command(), "build", name], ctx=ctx)
        if code != 0:
            raise RuntimeError("\n".join(lines[-30:]) or "docker compose build failed")
        return {"message": f"{name} image built", "data": {"service": name, "output": lines[-20:]}}
    if action == "restart":
        code, lines = await run_command([*compose_command(), "restart", name], ctx=ctx, timeout=600)
        if code != 0:
            raise RuntimeError("\n".join(lines[-30:]) or "restart failed")
        return {"message": f"{name} restarted", "data": {"service": name, "output": lines[-20:]}}
    raise ValueError(f"Unknown action {action}")


async def _control(ctx: JobContext) -> dict[str, Any]:
    # Serialize Docker CLI operations inside the admin process. The job hub
    # already has one admin worker, but this also protects against stale tasks
    # from a previous hub process during a restart.
    async with CONTROL_LOCK:
        return await _control_locked(ctx)


for _action in ("enable", "disable", "build", "restart"):
    runner.register(_action, _control)
runner.register("install_model", _install_model)


app = create_service_app(
    "admin",
    "Open Studio Service Manager",
    "Builds, starts, stops and reports the health of every optional service on demand.",
    runner=runner,
    extra_routers=[router],
)
