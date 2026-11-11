"""ACE-Step 1.5 model family, capabilities and studio options.

The engine is the source of truth for which GGUF files actually exist. This
module describes every model the studio can present, so the UI still has a
complete catalog while the engine is downloading or offline.
"""

from __future__ import annotations

from typing import Any

from openstudio_common import env

from .languages import provider_languages

DEFAULT_MODEL = env("ACESTEP_DEFAULT_MODEL", "acestep-v15-turbo")
DEFAULT_PROVIDER = "ace_step"

MODE_TASKS: dict[str, str] = {
    "full": "text2music",
    "repaint": "repaint",
    "cover": "cover",
    "extend": "complete",
}

MODE_CAPABILITY: dict[str, str] = {
    "full": "text_to_music",
    "repaint": "repaint",
    "cover": "cover",
    "extend": "extend",
}

ACE_MODELS: dict[str, dict[str, Any]] = {
    "acestep-v15-turbo": {
        "name": "ACE-Step 1.5 Turbo",
        "short_name": "Turbo",
        "parameters": "2B",
        "vram_gb": 4.7,
        "default_steps": 8,
        "default_guidance": 1.0,
        "quality": "Very high",
        "speed": "Fast · 8 diffusion steps",
        "family": "turbo",
        "recommended": True,
        "description": "The best starting point for consumer hardware. DiT generation with 5Hz LM planning.",
    },
    "acestep-v15-sft": {
        "name": "ACE-Step 1.5 SFT",
        "short_name": "SFT",
        "parameters": "2B",
        "vram_gb": 4.7,
        "default_steps": 50,
        "default_guidance": 1.0,
        "quality": "High",
        "speed": "Moderate · 50 diffusion steps",
        "family": "sft",
        "recommended": False,
        "description": "Higher-fidelity 2B model at a much slower step count. Better for final takes than rapid iteration.",
    },
    "acestep-v15-base": {
        "name": "ACE-Step 1.5 Base",
        "short_name": "Base",
        "parameters": "2B",
        "vram_gb": 4.7,
        "default_steps": 50,
        "default_guidance": 1.0,
        "quality": "Medium",
        "speed": "Moderate · 50 diffusion steps",
        "family": "base",
        "recommended": False,
        "description": "Supports the complete editing toolbox, including completion and stem extraction.",
    },
    "acestep-v15-xl-turbo": {
        "name": "ACE-Step 1.5 XL Turbo",
        "short_name": "XL Turbo",
        "parameters": "4B",
        "vram_gb": 9.0,
        "default_steps": 8,
        "default_guidance": 1.0,
        "quality": "Superior",
        "speed": "Fast for its size · 8 steps",
        "family": "xl-turbo",
        "recommended": False,
        "description": "4B XL decoder with turbo step count. Requires substantially more memory than the 2B models.",
    },
    "acestep-v15-xl-sft": {
        "name": "ACE-Step 1.5 XL SFT",
        "short_name": "XL SFT",
        "parameters": "4B",
        "vram_gb": 9.0,
        "default_steps": 50,
        "default_guidance": 1.0,
        "quality": "Superior",
        "speed": "Slow · 50 steps",
        "family": "xl-sft",
        "recommended": False,
        "description": "4B XL decoder with SFT tuning. Requires workstation-class memory.",
    },
    "acestep-v15-xl-base": {
        "name": "ACE-Step 1.5 XL Base",
        "short_name": "XL Base",
        "parameters": "4B",
        "vram_gb": 9.0,
        "default_steps": 50,
        "default_guidance": 1.0,
        "quality": "High",
        "speed": "Slow · 50 steps",
        "family": "xl-base",
        "recommended": False,
        "description": "4B base model with the complete editing toolbox. Requires substantial memory.",
    },
    "acestep-v15-turbo-shift1": {
        "name": "ACE-Step 1.5 Turbo (shift 1)",
        "short_name": "Turbo shift 1",
        "parameters": "2B",
        "vram_gb": 4.7,
        "default_steps": 8,
        "default_guidance": 1.0,
        "quality": "Very high",
        "speed": "Fast · 8 steps",
        "family": "turbo",
        "recommended": False,
        "description": "Turbo variant with a different timestep shift profile.",
    },
    "acestep-v15-turbo-shift3": {
        "name": "ACE-Step 1.5 Turbo (shift 3)",
        "short_name": "Turbo shift 3",
        "parameters": "2B",
        "vram_gb": 4.7,
        "default_steps": 8,
        "default_guidance": 1.0,
        "quality": "Very high",
        "speed": "Fast · 8 steps",
        "family": "turbo",
        "recommended": False,
        "description": "Turbo variant with a different timestep shift profile.",
    },
    "acestep-v15-turbo-continuous": {
        "name": "ACE-Step 1.5 Turbo (continuous)",
        "short_name": "Turbo continuous",
        "parameters": "2B",
        "vram_gb": 4.7,
        "default_steps": 8,
        "default_guidance": 1.0,
        "quality": "Very high",
        "speed": "Fast · 8 steps",
        "family": "turbo",
        "recommended": False,
        "description": "Turbo variant trained with a continuous noise schedule.",
    },
}

MODEL_ORDER = list(ACE_MODELS)

EXTEND_FAMILIES = {"base", "sft", "xl-base", "xl-sft"}
STEM_FAMILIES = {"base", "xl-base"}


def _is_known(model_id: str) -> bool:
    return model_id in ACE_MODELS


def model_capabilities(model_id: str, info: dict[str, Any] | None = None) -> dict[str, Any]:
    info = info if info is not None else ACE_MODELS.get(model_id, {})
    known = bool(info)
    family = str(info.get("family") or "unknown")
    extend = known and family in EXTEND_FAMILIES
    stems = known and family in STEM_FAMILIES
    return {
        "text_to_music": True,
        "lyrics": True,
        "instrumental": True,
        "vocals": True,
        "cover": known,
        "repaint": known,
        "extend": extend,
        "source_audio": known,
        "reference_audio": known,
        "variations": True,
        "multiple_variations": True,
        "seed": True,
        "seed_control": True,
        "steps": True,
        "inference_steps": True,
        "guidance": True,
        "guidance_control": True,
        "prompt_expansion": known,
        "thinking": False,
        "bpm": True,
        "bpm_control": True,
        "duration": True,
        "duration_control": True,
        "vocal_language": True,
        "vocal_only": False,
        "vocal_regeneration": False,
        "arrangement_edit": False,
        "stem_extraction": stems,
        "max_variations": 4,
        "max_duration_seconds": 600,
        "operation_note": (
            "Full generations use the 5Hz LM for audio codes. Cover and repaint run directly "
            "through the DiT without the LM. Completion/extension requires a base or SFT checkpoint."
            if known
            else "Unverified custom checkpoint: only basic text-to-music is exposed until its family is known."
        ),
    }


def model_controls(info: dict[str, Any], capabilities: dict[str, Any]) -> dict[str, Any]:
    return {
        "text_to_music": capabilities["text_to_music"],
        "repaint": capabilities["repaint"],
        "cover": capabilities["cover"],
        "extend": capabilities["extend"],
        "variations": {"min": 1, "max": int(capabilities.get("max_variations") or 4)},
        "seed": {"supported": True, "random": -1},
        "steps": {
            "supported": True,
            "min": 1,
            "max": 200,
            "default": int(info.get("default_steps") or 8),
        },
        "inference_steps": {
            "supported": True,
            "min": 1,
            "max": 200,
            "default": int(info.get("default_steps") or 8),
        },
        "guidance": {
            "supported": True,
            "min": 0,
            "max": 30,
            "default": float(info.get("default_guidance") or 1.0),
        },
        "guidance_scale": {
            "supported": True,
            "min": 0,
            "max": 30,
            "default": float(info.get("default_guidance") or 1.0),
        },
        "thinking": {"supported": False, "note": "The GGUF engine always plans full songs with its LM."},
        "prompt_expansion": {"supported": bool(capabilities.get("prompt_expansion"))},
        "reference_audio": {"supported": bool(capabilities.get("reference_audio"))},
        "source_audio": {"supported": bool(capabilities.get("source_audio"))},
        "bpm": {"supported": True, "min": 30, "max": 300},
        "duration": {"supported": True, "min": 5, "max": int(capabilities.get("max_duration_seconds") or 600)},
        "vocal_language": {"supported": True},
        "instrumental": {"supported": True},
        "vocals": {"supported": True},
    }


def build_model_descriptor(
    model_id: str,
    *,
    installed: bool,
    default_model: str,
    files: dict[str, Any] | None = None,
    quantization: str = "",
) -> dict[str, Any]:
    info = ACE_MODELS.get(model_id, {})
    known = bool(info)
    capabilities = model_capabilities(model_id, info if known else None)
    family = str(info.get("family") or "custom")
    notes: list[str] = []
    if model_id == default_model:
        notes.append("Default music model for new songs.")
    if model_id.startswith("acestep-v15-xl"):
        notes.append("XL 4B models need roughly 9 GB of weights and are not suitable for low-memory machines.")
    if family in {"base", "xl-base"}:
        notes.append("Completion, add-layer and stem extraction require a base checkpoint.")
    if family in {"sft", "xl-sft"}:
        notes.append("SFT checkpoints support completion and take longer to render.")
    if model_id in {"acestep-v15-turbo-shift1", "acestep-v15-turbo-shift3"}:
        notes.append("Only the timestep shift differs from the standard turbo checkpoint.")
    if not known:
        notes.append("Custom GGUF checkpoint discovered by the engine. Editing modes stay disabled until verified.")

    descriptor: dict[str, Any] = {
        "id": model_id,
        "name": info.get("name", model_id),
        "short_name": info.get("short_name", model_id),
        "family": family,
        "parameters": info.get("parameters", "Unknown"),
        "vram_gb": info.get("vram_gb"),
        "default_steps": int(info.get("default_steps") or 8),
        "default_guidance": float(info.get("default_guidance") or 1.0),
        "quality": info.get("quality", "Unverified"),
        "speed": info.get("speed", "Unknown"),
        "description": info.get(
            "description",
            "Custom ACE-Step checkpoint discovered on the engine. Capability coverage is conservative.",
        ),
        "recommended": bool(info.get("recommended")) or model_id == default_model,
        "installed": bool(installed),
        "is_default": model_id == default_model,
        "documented": known,
        "capabilities": capabilities,
        "controls": model_controls(info, capabilities),
        "quantization": quantization or "unknown",
        "notes": notes,
        "files": files or {},
    }
    return descriptor


def known_model_descriptors(default_model: str, installed_ids: set[str] | None = None) -> list[dict[str, Any]]:
    installed_ids = installed_ids or set()
    return [
        build_model_descriptor(
            model_id,
            installed=model_id in installed_ids,
            default_model=default_model,
        )
        for model_id in MODEL_ORDER
    ]


def global_capabilities() -> dict[str, Any]:
    return {
        "text_to_music": True,
        "repaint": True,
        "cover": True,
        "extend": True,
        "source_audio": True,
        "reference_audio": True,
        "variations": True,
        "seed": True,
        "seed_control": True,
        "steps": True,
        "inference_steps": True,
        "guidance": True,
        "guidance_control": True,
        "prompt_expansion": True,
        "thinking": False,
        "bpm": True,
        "bpm_control": True,
        "duration": True,
        "duration_control": True,
        "vocal_language": True,
        "max_variations": 4,
        "max_duration_seconds": 600,
        "engine": "acestep.cpp / GGUF",
    }


def defaults(default_model: str = DEFAULT_MODEL) -> dict[str, Any]:
    info = ACE_MODELS.get(default_model, {})
    return {
        "provider": DEFAULT_PROVIDER,
        "model_id": default_model,
        "mode": "full",
        "variations": 2,
        "seed": None,
        "inference_steps": int(info.get("default_steps") or 8),
        "guidance_scale": float(info.get("default_guidance") or 1.0),
        "thinking": False,
        "use_format": False,
        "enhance_prompt": False,
        "duration": 150,
        "bpm": 96,
        "language": "pt-PT",
        "vocal_type": "female",
        "source_path": None,
        "reference_path": None,
        "start_seconds": 0.0,
        "end_seconds": None,
        "cover_strength": 0.75,
        "infer_method": "ode",
        "audio_format": "wav",
        "lm_batch_size": 1,
        "synth_batch_size": 2,
        "export_format": "wav",
    }


def options() -> dict[str, Any]:
    return {
        "modes": [
            {
                "id": "full",
                "label": "Full song",
                "task_type": "text2music",
                "requires_source": False,
                "requires_range": False,
                "description": "Create a complete song from the brief and lyrics.",
            },
            {
                "id": "repaint",
                "label": "Repaint section",
                "task_type": "repaint",
                "requires_source": True,
                "requires_range": True,
                "description": "Regenerate a time range while preserving the rest of the source audio.",
            },
            {
                "id": "cover",
                "label": "Cover / re-imagine",
                "task_type": "cover",
                "requires_source": True,
                "requires_range": False,
                "description": "Re-interpret source audio in a new style.",
            },
            {
                "id": "extend",
                "label": "Extend / complete",
                "task_type": "complete",
                "requires_source": True,
                "requires_range": False,
                "description": "Continue or complete source audio. Requires a base or SFT model.",
            },
        ],
        "audio_formats": [
            {"id": "wav", "label": "WAV 16-bit", "extension": ".wav", "mime": "audio/wav", "engine_output": "wav16"},
            {"id": "wav24", "label": "WAV 24-bit", "extension": ".wav", "mime": "audio/wav", "engine_output": "wav24"},
            {"id": "wav32", "label": "WAV 32-bit", "extension": ".wav", "mime": "audio/wav", "engine_output": "wav32"},
            {"id": "mp3", "label": "MP3", "extension": ".mp3", "mime": "audio/mpeg", "engine_output": "mp3"},
            {
                "id": "flac",
                "label": "FLAC",
                "extension": ".flac",
                "mime": "audio/flac",
                "engine_output": "wav16",
                "note": "Rendered by the engine as WAV and converted losslessly with ffmpeg.",
            },
        ],
        "export_formats": [
            {"id": "wav", "label": "WAV", "extension": ".wav", "mime": "audio/wav"},
            {"id": "mp3", "label": "MP3", "extension": ".mp3", "mime": "audio/mpeg"},
            {"id": "flac", "label": "FLAC", "extension": ".flac", "mime": "audio/flac"},
            {"id": "zip", "label": "Session ZIP", "extension": ".zip", "mime": "application/zip"},
        ],
        "infer_methods": [
            {"id": "ode", "label": "ODE (deterministic)", "solver": "euler"},
            {"id": "sde", "label": "SDE (ancestral)", "solver": "sde"},
        ],
        "vocal_types": [
            {"value": "female", "label": "Female", "description": "A single lead voice"},
            {"value": "male", "label": "Male", "description": "A single lead voice"},
            {"value": "duet", "label": "Duet", "description": "Two voices in dialogue"},
            {"value": "group", "label": "Group", "description": "Small ensemble harmonies"},
            {"value": "choir", "label": "Choir", "description": "Wide choral ensemble"},
            {"value": "instrumental", "label": "Instrumental", "description": "No vocals at all"},
        ],
        "section_types": [
            {"value": "intro", "label": "Intro"},
            {"value": "verse", "label": "Verse"},
            {"value": "pre-chorus", "label": "Pre-Chorus"},
            {"value": "chorus", "label": "Chorus"},
            {"value": "bridge", "label": "Bridge"},
            {"value": "outro", "label": "Outro"},
        ],
        "genres": {
            "Pop": ["Art pop", "Dream pop", "Synth-pop", "Indie pop", "Ballad", "Electropop"],
            "Rock": ["Indie rock", "Alternative rock", "Post-rock", "Garage rock", "Soft rock"],
            "Hip-Hop": ["Boom bap", "Trap", "Lo-fi hip-hop", "Alternative rap", "Conscious hip-hop"],
            "Electronic": ["Synthwave", "House", "Techno", "Ambient", "Downtempo", "Trip-hop"],
            "R&B / Soul": ["Neo-soul", "Contemporary R&B", "Motown", "Quiet storm"],
            "Jazz": ["Vocal jazz", "Bossa nova", "Nu-jazz", "Swing", "Modal jazz"],
            "Classical": ["Orchestral", "Modern classical", "Chamber", "Choral"],
            "Folk": ["Indie folk", "Singer-songwriter", "Contemporary folk", "World folk"],
            "Fado": ["Fado canção", "Fado tradicional", "Alternative fado"],
            "Latin": ["Bolero", "Latin pop", "Bossa nova", "Reggaeton"],
            "Metal": ["Progressive metal", "Doom metal", "Symphonic metal", "Post-metal"],
            "Country / Americana": ["Americana", "Alt-country", "Bluegrass", "Country ballad"],
            "Ambient / Cinematic": ["Score", "Drone", "Soundscape", "Neoclassical"],
            "World": ["Portuguese", "Brazilian", "Nordic", "West African", "Japanese", "Indian"],
            "K-pop": ["Contemporary K-pop", "K-ballad", "K-rap"],
            "Experimental": ["Avant-pop", "Collage", "Art song", "Noise"],
        },
        "moods": [
            "Introspective",
            "Melancholic",
            "Dreamy",
            "Romantic",
            "Hopeful",
            "Uplifting",
            "Playful",
            "Dark",
            "Defiant",
            "Haunting",
            "Nostalgic",
            "Epic",
            "Serene",
            "Restless",
        ],
        "energy_labels": [
            {"value": 0, "label": "Still"},
            {"value": 25, "label": "Low"},
            {"value": 50, "label": "Mid"},
            {"value": 75, "label": "High"},
            {"value": 100, "label": "Peak"},
        ],
        "singing_styles": [
            "Melodic",
            "Intimate",
            "Breathy",
            "Belting",
            "Falsetto",
            "Spoken word",
            "Rap",
            "Chant",
            "Crooner",
            "Ornamented",
        ],
        "vocal_emotions": [
            "Intimate",
            "Tender",
            "Yearning",
            "Joyful",
            "Defiant",
            "Haunting",
            "Playful",
            "Mournful",
            "Serene",
            "Ecstatic",
            "Restrained",
        ],
        "vocal_ranges": ["Soprano", "Mezzo-soprano", "Alto", "Tenor", "Baritone", "Bass", "Unspecified"],
        "style_suggestions": [
            "intimate",
            "cinematic",
            "analog warmth",
            "live room",
            "nylon guitar",
            "muted trumpet",
            "brushed drums",
            "wide stereo",
            "lo-fi texture",
            "orchestral swell",
            "close vocal",
            "modal harmony",
            "tape saturation",
            "sparse arrangement",
        ],
        "project_colors": [
            {"id": "lime", "label": "Lime", "hex": "#d9ff6b"},
            {"id": "coral", "label": "Coral", "hex": "#ff7c5c"},
            {"id": "mint", "label": "Mint", "hex": "#83f0c4"},
            {"id": "blue", "label": "Blue", "hex": "#82b9ff"},
            {"id": "amber", "label": "Amber", "hex": "#ffc46b"},
            {"id": "rose", "label": "Rose", "hex": "#f48bb2"},
        ],
        "structures": [
            {"id": "pop-standard", "label": "Pop standard", "sections": ["Intro", "Verse 1", "Pre-Chorus", "Chorus", "Verse 2", "Chorus", "Bridge", "Chorus", "Outro"]},
            {"id": "radio-edit", "label": "Radio edit", "sections": ["Verse 1", "Pre-Chorus", "Chorus", "Verse 2", "Chorus", "Outro"]},
            {"id": "ballad", "label": "Ballad", "sections": ["Intro", "Verse 1", "Chorus", "Verse 2", "Chorus", "Bridge", "Chorus", "Outro"]},
            {"id": "short", "label": "Short", "sections": ["Verse 1", "Chorus", "Verse 2", "Chorus"]},
        ],
    }


def engine_descriptor(state: dict[str, Any], default_model: str = DEFAULT_MODEL) -> dict[str, Any]:
    models = state.get("models") or []
    installed_ids = [model["id"] for model in models if model.get("installed")]
    available = bool(state.get("available"))
    return {
        "id": DEFAULT_PROVIDER,
        "name": "ACE-Step 1.5",
        "kind": "music",
        "accent": "lime",
        "available": available,
        "status": "online" if available else "offline",
        "status_detail": state.get("detail") or "ACE-Step engine status unknown.",
        "version": state.get("version"),
        "backend": "CPU / CUDA / Vulkan (GGUF)",
        "engine": "acestep.cpp / GGUF",
        "default_model": default_model,
        "can_unload": False,
        "models": installed_ids,
        "catalog": [model["id"] for model in models],
        "languages": provider_languages(),
        "files": state.get("buckets") or {},
        "description": (
            "The primary local music engine: ACE-Step 1.5 served by the Dockerized GGUF/C++ "
            "pipeline. It runs on CPU and can use CUDA or Vulkan when available."
        ),
        "limitations": [
            "The GGUF engine consumes the same ACE-Step 1.5 checkpoints as the official Python API but exposes a different HTTP API.",
            "Full text-to-music generation runs the 5Hz language model to create audio codes. Cover and repaint bypass the LM.",
            "The engine reports running/done rather than percentage progress; the studio reports real pipeline stages and elapsed time.",
            "Vocal-only regeneration is not exposed by this engine. Use repaint over the relevant section.",
            "Thinking/COT toggles from the official API are not exposed by the GGUF engine; full songs always use the LM planner.",
            "The Docker image downloads model weights on first start. Plan for a multi-gigabyte download.",
            "Dialects such as pt-PT versus pt-BR remain prompt-steered because the model uses a base language code.",
        ],
        "setup_hint": (
            "Start the music-engine container and follow its logs. The engine is ready once the "
            "first-start GGUF download finishes and /props reports a complete model set."
        ),
        "docs_url": "https://github.com/ServeurpersoCom/acestep.cpp",
        "restart_instructions": (
            "Restart the music-engine container to release cached model memory or after changing "
            "the model volume."
        ),
    }


def catalog_payload(
    state: dict[str, Any],
    *,
    default_model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    return {
        "engines": [engine_descriptor(state, default_model)],
        "models": state.get("models") or known_model_descriptors(default_model),
        "languages": provider_languages(),
        "defaults": defaults(default_model),
        "options": options(),
        "capabilities": global_capabilities(),
    }
