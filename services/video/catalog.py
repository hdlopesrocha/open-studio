"""Video catalogue: every style, scene, output, provider and model control.

The frontend renders its controls from this endpoint rather than hard-coding
choices, so new providers/backends only require a backend change here.
"""

from __future__ import annotations

from typing import Any

from mvstudio_shared.config import get_settings
from mvstudio_shared.models import (
    AudioReactiveConfig,
    CameraMove,
    OutputConfig,
    ProjectConfig,
    SceneGenerationConfig,
    SubtitleStyle,
    output_dimensions,
)
from mvstudio_shared.styles import STYLE_PRESETS, style_catalogue

from .settings_store import AISettingsStore

CAMERA_MOVES = [
    {"value": "slow_forward", "label": "Slow push in", "description": "Gentle dolly toward the subject."},
    {"value": "slow_backward", "label": "Slow pull out", "description": "Reveal more of the environment."},
    {"value": "pan_left", "label": "Pan left", "description": "Horizontal move to the left."},
    {"value": "pan_right", "label": "Pan right", "description": "Horizontal move to the right."},
    {"value": "pan_up", "label": "Tilt up", "description": "Rise toward the sky or ceiling."},
    {"value": "pan_down", "label": "Tilt down", "description": "Descend toward the ground."},
    {"value": "rotate_cw", "label": "Slow rotate clockwise", "description": "Subtle clockwise rotation."},
    {"value": "rotate_ccw", "label": "Slow rotate counter-clockwise", "description": "Subtle counter-clockwise rotation."},
    {"value": "handheld", "label": "Handheld drift", "description": "Organic handheld micro-movement."},
    {"value": "parallax", "label": "Depth parallax", "description": "Depth-map-driven parallax when available."},
    {"value": "static", "label": "Static", "description": "No camera movement."},
]

EFFECTS = [
    {"id": "vignette", "label": "Vignette", "description": "Darkened cinematic edges."},
    {"id": "subtle_film_grain", "label": "Subtle grain", "description": "Fine analogue texture."},
    {"id": "film_grain", "label": "Film grain", "description": "Heavier 35mm texture."},
    {"id": "bloom", "label": "Bloom", "description": "Glow around highlights."},
    {"id": "soft_focus", "label": "Soft focus", "description": "Dreamlike diffusion."},
    {"id": "light_leak", "label": "Light leak", "description": "Warm analogue flare."},
    {"id": "chromatic_aberration", "label": "Chromatic aberration", "description": "Lens colour fringing."},
    {"id": "letterbox", "label": "Letterbox", "description": "Cinema bars (16:9)."},
    {"id": "shake", "label": "Camera shake", "description": "Subtle handheld movement."},
    {"id": "particles", "label": "Particles", "description": "Floating dust / fireflies."},
    {"id": "beat_pulse", "label": "Beat pulse", "description": "Brightness pulses on beats."},
    {"id": "bass_pulse", "label": "Bass pulse", "description": "Low-end light pulses."},
]

TRANSITIONS = [
    {"value": "cut", "label": "Hard cut"},
    {"value": "crossfade", "label": "Crossfade"},
    {"value": "dissolve", "label": "Dissolve"},
    {"value": "fade_to_black", "label": "Fade to black"},
    {"value": "fade_to_white", "label": "Fade to white"},
    {"value": "slide_left", "label": "Slide left"},
    {"value": "slide_right", "label": "Slide right"},
    {"value": "slide_up", "label": "Slide up"},
    {"value": "wipe_left", "label": "Wipe left"},
    {"value": "wipe_right", "label": "Wipe right"},
    {"value": "circle", "label": "Circle open"},
]

IMAGE_PROVIDERS = [
    {
        "id": "auto",
        "label": "Auto",
        "description": "Use the best configured provider, with procedural fallback when allowed.",
        "requires": [],
        "ai": True,
    },
    {
        "id": "procedural",
        "label": "Procedural",
        "description": "Deterministic Pillow artwork. No AI model or network required.",
        "requires": [],
        "ai": False,
    },
    {
        "id": "comfyui",
        "label": "ComfyUI",
        "description": "User-managed ComfyUI workflow, checkpoint and sampler settings.",
        "requires": ["ComfyUI", "API workflow"],
        "ai": True,
    },
    {
        "id": "qvac",
        "label": "QVAC",
        "description": "Local QVAC diffusion through the shared imagegen service.",
        "requires": ["QVAC runtime/model"],
        "ai": True,
    },
    {
        "id": "diffusers",
        "label": "Diffusers",
        "description": "Local Hugging Face diffusers pipeline through imagegen.",
        "requires": ["diffusers model"],
        "ai": True,
    },
]

ANIMATION_BACKENDS = [
    {
        "id": "ffmpeg",
        "label": "FFmpeg",
        "description": "Fast CPU camera moves, filters and audio-reactive effects.",
        "requires": ["FFmpeg"],
        "ai": False,
    },
    {
        "id": "opencv",
        "label": "OpenCV",
        "description": "Frame-based animation with optional depth-map parallax.",
        "requires": ["OpenCV"],
        "ai": False,
    },
    {
        "id": "ai",
        "label": "AI image-to-video",
        "description": "Optional ComfyUI video workflow; falls back to FFmpeg when configured.",
        "requires": ["ComfyUI", "image-to-video workflow"],
        "ai": True,
    },
]

SUBTITLE_FONTS = [
    "DejaVu Sans",
    "DejaVu Serif",
    "Noto Sans",
    "Noto Serif",
    "Liberation Sans",
    "Liberation Serif",
    "Arial",
    "Helvetica",
    "Verdana",
    "Georgia",
]


def _output_sizes() -> list[dict[str, Any]]:
    sizes: list[dict[str, Any]] = []
    for resolution in ("720p", "1080p"):
        for aspect in ("16:9", "9:16", "1:1"):
            width, height = output_dimensions(resolution, aspect)
            sizes.append(
                {
                    "resolution": resolution,
                    "aspect_ratio": aspect,
                    "width": width,
                    "height": height,
                    "label": f"{resolution} · {aspect} ({width}×{height})",
                }
            )
    return sizes


def _style_options() -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for style in STYLE_PRESETS.values():
        options.append(
            {
                "id": style.id,
                "name": style.name,
                "description": style.description,
                "palette": list(style.palette),
                "lighting": style.lighting,
                "art_direction": style.art_direction,
                "prompt_suffix": style.prompt_suffix,
                "negative_prompt": style.negative_prompt,
                "default_effects": list(style.default_effects),
                "preferred_transitions": list(style.preferred_transitions),
            }
        )
    return options


def build_catalog(ai_store: AISettingsStore) -> dict[str, Any]:
    settings = get_settings()
    ai = ai_store.load()
    project_defaults = ProjectConfig().model_dump(mode="json")
    output_defaults = OutputConfig().model_dump(mode="json")
    scene_defaults = SceneGenerationConfig().model_dump(mode="json")
    subtitle_defaults = SubtitleStyle().model_dump(mode="json")
    reactive_defaults = AudioReactiveConfig().model_dump(mode="json")
    camera_defaults = CameraMove().model_dump(mode="json")

    run_actions = [
        {
            "id": "analyze",
            "label": "Analyse audio & lyrics",
            "description": "Beat, tempo, section and lyric analysis.",
            "options": ["force"],
        },
        {
            "id": "plan",
            "label": "Plan scenes",
            "description": "Deterministic or Ollama-enhanced scene plan.",
            "options": ["force"],
        },
        {
            "id": "images",
            "label": "Generate images",
            "description": "Generate scene artwork through the selected image provider.",
            "options": ["scene_ids", "force", "variant", "variants"],
        },
        {
            "id": "animate",
            "label": "Animate scenes",
            "description": "Render per-scene clips with the selected animation backend.",
            "options": ["scene_ids", "force"],
        },
        {
            "id": "render",
            "label": "Render final video",
            "description": "Assemble transitions, subtitles and audio into the final video.",
            "options": ["output"],
        },
        {
            "id": "full",
            "label": "Full pipeline",
            "description": "Analysis, planning, images, animation and final render.",
            "options": ["skip_images", "skip_animation", "force", "output", "config"],
        },
        {
            "id": "regenerate",
            "label": "Regenerate scenes",
            "description": "Regenerate selected scene images and/or clips.",
            "options": [
                "scene_ids",
                "prompt",
                "negative_prompt",
                "camera",
                "transition",
                "visual_effects",
                "seed",
                "image",
                "animation",
                "variants",
            ],
        },
    ]

    return {
        "component": "video",
        "version": "1.0.0",
        "styles": _style_options(),
        "style_ids": [style["id"] for style in _style_options()],
        "camera_moves": CAMERA_MOVES,
        "effects": EFFECTS,
        "transitions": TRANSITIONS,
        "output_sizes": _output_sizes(),
        "resolutions": [
            {"value": "720p", "label": "720p"},
            {"value": "1080p", "label": "1080p"},
        ],
        "aspect_ratios": [
            {"value": "16:9", "label": "16:9 landscape"},
            {"value": "9:16", "label": "9:16 vertical"},
            {"value": "1:1", "label": "1:1 square"},
        ],
        "fps": [24, 25, 30, 60],
        "codecs": [
            {"value": "h264", "label": "H.264 (broad compatibility)"},
            {"value": "h265", "label": "H.265 (smaller, slower)"},
        ],
        "qualities": [
            {"value": "draft", "label": "Draft"},
            {"value": "standard", "label": "Standard"},
            {"value": "high", "label": "High"},
        ],
        "presets": [
            "ultrafast",
            "superfast",
            "veryfast",
            "faster",
            "fast",
            "medium",
            "slow",
            "slower",
            "veryslow",
        ],
        "audio_bitrates": ["128k", "192k", "256k", "320k"],
        "animation_backends": ANIMATION_BACKENDS,
        "image_providers": IMAGE_PROVIDERS,
        "planner_modes": [
            {"value": "auto", "label": "Auto (Ollama when available)"},
            {"value": "ollama", "label": "Require Ollama"},
            {"value": "deterministic", "label": "Deterministic only"},
        ],
        "subtitle_styles": {
            "defaults": subtitle_defaults,
            "fonts": SUBTITLE_FONTS,
            "positions": ["bottom", "center", "top"],
            "alignments": ["left", "center", "right"],
            "controls": [
                "font_family",
                "font_size",
                "primary_color",
                "highlight_color",
                "outline_color",
                "outline_width",
                "shadow",
                "background",
                "background_opacity",
                "background_color",
                "position",
                "margin_v",
                "max_line_width",
                "alignment",
                "karaoke",
            ],
        },
        "audio_reactive": {
            "defaults": reactive_defaults,
            "controls": ["enabled", "beat_pulse", "bass_pulse", "beat_cuts", "particles", "intensity"],
        },
        "camera_defaults": camera_defaults,
        "defaults": {
            "project": project_defaults,
            "output": output_defaults,
            "scenes": scene_defaults,
            "subtitles": subtitle_defaults,
            "audio_reactive": reactive_defaults,
            "ai": project_defaults.get("ai", {}),
        },
        "limits": {
            "min_scene_duration": 1.0,
            "max_scene_duration": 120.0,
            "image_variants": 4,
            "max_upload_mb": settings.max_upload_mb,
            "max_concurrent_jobs": settings.max_concurrent_jobs,
        },
        "run_actions": run_actions,
        "job_actions": [action["id"] for action in run_actions],
        "comfyui": {
            "url": ai.comfyui_url,
            "image_workflow_path": ai.image_workflow_path,
            "video_workflow_path": ai.video_workflow_path,
            "image_steps": ai.image_steps,
            "image_cfg": ai.image_cfg,
            "image_checkpoint": ai.image_checkpoint,
            "video_steps": ai.video_steps,
            "video_cfg": ai.video_cfg,
            "video_checkpoint": ai.video_checkpoint,
            "placeholders": [
                "PROMPT",
                "NEGATIVE_PROMPT",
                "WIDTH",
                "HEIGHT",
                "SEED",
                "STEPS",
                "CFG",
                "CHECKPOINT",
                "PREFIX",
                "REFERENCE_IMAGE",
                "DURATION",
                "FPS",
                "FRAMES",
            ],
        },
        "ollama": {
            "url": ai.ollama_url,
            "model": ai.ollama_model,
            "description": "Optional local LLM for richer scene descriptions.",
        },
        "providers": {
            "imagegen_url": settings.service_url("images"),
            "ollama_url": ai.ollama_url,
            "comfyui_url": ai.comfyui_url,
            "images": IMAGE_PROVIDERS,
            "animation": ANIMATION_BACKENDS,
        },
        "models": {
            "note": "Use GET /api/video/ai/models for live Ollama and ComfyUI inventory.",
            "ollama": [ai.ollama_model] if ai.ollama_model else [],
            "comfyui": [
                item
                for item in (ai.image_checkpoint, ai.video_checkpoint)
                if item
            ],
            "imagegen": [provider["id"] for provider in IMAGE_PROVIDERS],
        },
        "ai_settings": ai.model_dump(mode="json"),
        "actions": {
            "create_project": {
                "json": ["name", "title", "artist", "audio_path", "srt_path", "config"],
                "multipart": ["name", "title", "artist", "audio", "srt", "config"],
            },
            "run": ["action", "options"],
        },
    }
