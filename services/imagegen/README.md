# Image generation service

Unified image service mounted at `/api/images`. It always has a deterministic
Pillow renderer and can optionally use Hugging Face diffusers, ComfyUI or QVAC.

- `GET /providers` → availability, styles, models, runtime, defaults.
- `GET /models` → procedural styles, local/HF diffusers models, ComfyUI
  checkpoints, QVAC model and the full parameter schema.
- `GET /gallery?limit=&offset=&provider=&q=` → recent images from
  `/data/files/images`, read from JSON metadata sidecars.
- `POST /generate` → job (`generate`). Full params: `provider, model, prompt,
  negative_prompt, width, height, steps, guidance, cfg_scale, seed,
  batch_count, sampler, scheduler, init_image, strength, lora, output_format,
  upscale` plus nested `comfyui` options.
- `POST /upscale` → job (`upscale`).
- `POST /internal/video/provider-status` and `/internal/video/generate` →
  VideoStudio-compatible sync API used by the video orchestrator. Requires the
  internal token.

## Providers

| Provider | Requirement | Notes |
| --- | --- | --- |
| `procedural` | Pillow + NumPy | Always works; 8 styles, deterministic by seed, prompt-aware composition and typography. |
| `diffusers` | `INSTALL_DIFFUSERS=1` | SD 1.5 / SDXL / SD-Turbo / FLUX; local models in `/data/models/images` or HF ids. |
| `comfyui` | reachable ComfyUI | API-format workflow with `{{PROMPT}}`, `{{WIDTH}}`, `{{SEED}}`, `{{CHECKPOINT}}`, `{{REFERENCE_IMAGE}}` placeholders. |
| `qvac` | reachable QVAC service | Proxies `/api/qvac/image` and polls the resulting job. |

`provider=auto` prefers ComfyUI if a workflow is configured, otherwise
procedural. Failed non-procedural generation falls back to procedural unless
`allow_fallback=false`.

Generated job files live in `/data/files/images/<job_id>/` with a JSON sidecar
for every image. Video-compatible images live in
`/data/files/video/projects/<project_id>/assets/images/`, with thumbnails in
`assets/thumbnails/` and a project cache manifest in `cache/manifest.json`.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `IMAGEGEN_MODELS_DIR` | `/data/models/images` | diffusers models |
| `VIDEO_PROJECTS_ROOT` | `/data/files/video/projects` | MVS compatibility root |
| `COMFYUI_URL` | `http://comfyui:8188` | ComfyUI server |
| `COMFYUI_WORKFLOW_PATH` | empty | default workflow file/path |
| `QVAC_URL` | `http://qvac:8000` | QVAC service |
| `IMAGEGEN_DEFAULT_PROVIDER` | empty | optional auto override (`procedural`, `diffusers`, …) |
| `DIFFUSERS_CPU_OFFLOAD` | `1` | offload when CUDA is tight |
| `HF_HOME` | `/data/models/huggingface` | Hugging Face cache |
| `MVS_DIFFUSERS_MODEL` | empty | model used by video compatibility diffusers requests |
| `MVS_REQUIRE_INTERNAL_TOKEN` | `0` | require the shared token on `/internal/video/*` (MVS clients may omit it) |

`GET /health`, `GET /providers`, `GET /models`, gallery and procedural
generation work without torch/diffusers/ComfyUI/QVAC.
