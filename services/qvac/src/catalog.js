'use strict';

const config = require('./config');

function field(name, type, defaultValue, description, extra = {}) {
  return { name, type, default: defaultValue, description, ...extra };
}

const VIDEO_PARAMS = [
  field('mode', 'string', 'txt2vid', 'Generation mode.', { enum: ['txt2vid', 'img2vid'] }),
  field('prompt', 'string', '', 'Text prompt describing the video.', { required: true }),
  field('negative_prompt', 'string', 'blurry, low quality, static, jittery, watermark', 'Negative prompt.'),
  field('init_image', 'string', '', 'First-frame image path relative to the files root (required for img2vid).'),
  field('control_frames', 'array', [], 'Ordered control/keyframe images relative to the files root.'),
  field('width', 'integer', 480, 'Video width in pixels.', { minimum: 16, multiple: 16 }),
  field('height', 'integer', 832, 'Video height in pixels.', { minimum: 16, multiple: 16 }),
  field('video_frames', 'integer', 33, 'Frame count. Frame formula depends on the model family.', { minimum: 1 }),
  field('fps', 'integer', 16, 'Output frame rate.', { minimum: 1, maximum: 120 }),
  field('steps', 'integer', 30, 'Diffusion steps.', { minimum: 1, maximum: 200 }),
  field('cfg_scale', 'number', 6, 'Classifier-free guidance strength.', { minimum: 0, maximum: 30 }),
  field('flow_shift', 'number', 3, 'Flow-matching shift.', { minimum: 0, maximum: 20 }),
  field('seed', 'integer', 42, 'Random seed; -1 for random.'),
  field('scheduler', 'string', '', 'Scheduler override (LTX-2 reference conditioning uses "ltx2").'),
  field('strength', 'number', 0.85, 'img2vid denoise strength (0-1); unsupported by MiniMax-H3.', { minimum: 0, maximum: 1 }),
  field('reference_images', 'array', [], 'Composite reference sheet(s) for LTX-2 IC-LoRA.'),
  field('lora', 'string', '', 'Absolute worker path or model-relative path to a LoRA adapter.'),
  field('lora_strength', 'number', 1, 'LoRA steering strength.', { minimum: -10, maximum: 10 }),
  field('stg_scale', 'number', 0, 'Spatio-temporal guidance scale.'),
  field('stg_block', 'integer', null, 'STG block index.'),
  field('reference_attention_strength', 'number', 1, 'How strongly the output follows reference images.', { minimum: 0, maximum: 10 }),
  field('reference_downscale_factor', 'integer', 1, 'Reference downscale factor; LTX-2 requires 1.', { minimum: 1, maximum: 16 }),
  field('temporal_tiling', 'boolean', false, 'Tile the video VAE along time to cap peak VRAM (LTX-2 only).'),
  field('vae_tile_size', 'integer', null, 'VAE tile size for temporal tiling.', { minimum: 1, maximum: 128 }),
  field('high_noise_steps', 'integer', null, 'High-noise expert steps (Wan 2.2 A14B only).', { minimum: 1, maximum: 200 }),
  field('high_noise_sample_method', 'string', '', 'High-noise expert sampler (Wan 2.2 A14B only).'),
  field('high_noise_scheduler', 'string', '', 'High-noise expert scheduler (Wan 2.2 A14B only).'),
  field('high_noise_cfg_scale', 'number', null, 'High-noise expert CFG (Wan 2.2 A14B only).'),
  field('high_noise_flow_shift', 'number', null, 'High-noise expert flow shift (Wan 2.2 A14B only).'),
  field('moe_boundary', 'number', null, 'Boundary where sampling switches to the low-noise expert.', { minimum: 0, maximum: 1 }),
  field('vae_tiling', 'boolean', true, 'Enable VAE tiling during generation.'),
  field('model_id', 'string', '', 'ID returned by /models/load. Loads the model first when omitted.'),
  field('model', 'string', '', 'Model constant, path or URL used when model_id is omitted.'),
  field('model_config', 'object', {}, 'Full model load configuration when model_id is omitted.'),
  field('output_format', 'string', 'both', 'Save the AVI buffer, an MP4 transcode, or both.', { enum: ['both', 'mp4', 'avi'] }),
  field('timeout', 'number', 86400, 'Maximum generation runtime in seconds.', { minimum: 1 }),
];

const IMAGE_PARAMS = [
  field('prompt', 'string', '', 'Text prompt describing the image.', { required: true }),
  field('negative_prompt', 'string', 'blurry, low quality, watermark, text', 'Negative prompt.'),
  field('width', 'integer', 512, 'Image width in pixels.', { minimum: 8, multiple: 8 }),
  field('height', 'integer', 512, 'Image height in pixels.', { minimum: 8, multiple: 8 }),
  field('steps', 'integer', 20, 'Diffusion steps.', { minimum: 1, maximum: 200 }),
  field('guidance', 'number', 3.5, 'Guidance scale (FLUX/SD families).', { minimum: 0, maximum: 30 }),
  field('cfg_scale', 'number', 1, 'Classifier-free guidance scale.', { minimum: 0, maximum: 30 }),
  field('seed', 'integer', -1, 'Random seed; -1 for random.'),
  field('batch_count', 'integer', 1, 'Number of images to generate.', { minimum: 1, maximum: config.limits.maxImageBatch }),
  field('sampling_method', 'string', '', 'Diffusion sampler, for example euler.'),
  field('sampler', 'string', '', 'Alias for sampling_method.'),
  field('scheduler', 'string', '', 'Diffusion scheduler.'),
  field('init_image', 'string', '', 'Source image for img2img, relative to the files root.'),
  field('init_images', 'array', [], 'Ordered reference images for multi-reference editing.'),
  field('strength', 'number', 0.7, 'SDEdit denoise strength (0-1).', { minimum: 0, maximum: 1 }),
  field('lora', 'string', '', 'Absolute worker path or model-relative LoRA adapter.'),
  field('lora_strength', 'number', 1, 'LoRA strength.', { minimum: -10, maximum: 10 }),
  field('upscale', 'boolean|object', false, 'Post-generation ESRGAN upscale: true, false or {repeats:N}.'),
  field('model_id', 'string', '', 'ID returned by /models/load.'),
  field('model', 'string', '', 'Model constant, path or URL used when model_id is omitted.'),
  field('model_config', 'object', {}, 'Full model load configuration when model_id is omitted.'),
  field('output_format', 'string', 'png', 'Output image format.', { enum: ['png'] }),
  field('timeout', 'number', 86400, 'Maximum generation runtime in seconds.', { minimum: 1 }),
];

const UPSCALE_PARAMS = [
  field('image_path', 'string', '', 'PNG/JPEG image relative to the files root.', { required: true }),
  field('model_id', 'string', '', 'Loaded ESRGAN model ID.'),
  field('model', 'string', 'REALESRGAN_X4PLUS', 'ESRGAN constant, path or URL when model_id is omitted.'),
  field('repeats', 'integer', 1, 'Sequential upscale passes.', { minimum: 1, maximum: config.limits.maxUpscaleRepeats }),
  field('tile_size', 'integer', 128, 'ESRGAN tile size.', { minimum: 16, maximum: 1024 }),
  field('output_format', 'string', 'png', 'Output image format.', { enum: ['png'] }),
];

const LOAD_PARAMS = [
  field('modelSrc', 'string', '', 'Diffusion/upscaler model constant, path or URL.', { required: true }),
  field('modelType', 'string', 'sdcpp-generation', 'QVAC model type.', { enum: ['sdcpp-generation', 'diffusion'] }),
  field('device', 'string', config.device, 'Inference device.', { enum: ['gpu', 'cpu'] }),
  field('threads', 'integer', 4, 'CPU threads.', { minimum: 1, maximum: 128 }),
  field('mode', 'string', '', 'Model config mode: video or upscale.'),
  field('t5XxlModelSrc', 'string', '', 'UMT5-XXL text encoder constant/path/URL.'),
  field('vaeModelSrc', 'string', '', 'Video/image VAE constant/path/URL.'),
  field('clipVisionModelSrc', 'string', '', 'OpenCLIP ViT-H/14 vision encoder (Wan I2V).'),
  field('llmModelSrc', 'string', '', 'LLM text encoder (FLUX, LTX-2, MiniMax-H3, Qwen).'),
  field('audioVaeModelSrc', 'string', '', 'Audio VAE (LTX-2, MiniMax-H3).'),
  field('embeddingsConnectorsModelSrc', 'string', '', 'LTX-2 embedding connectors; selects the LTX-2 layout.'),
  field('projectionModelSrc', 'string', '', 'Qwen-Image-2.1 vision projector.'),
  field('uncondModelSrc', 'string', '', 'Ideogram 4 unconditional diffusion model.'),
  field('highNoiseDiffusionModelSrc', 'string', '', 'Wan 2.2 A14B high-noise diffusion model.'),
  field('clipLModelSrc', 'string', '', 'SDXL/SD3 CLIP-L text encoder.'),
  field('clipGModelSrc', 'string', '', 'SDXL/SD3 CLIP-G text encoder.'),
  field('diffusion_fa', 'boolean', true, 'Enable flash attention in the diffusion engine.'),
  field('offload_to_cpu', 'boolean', true, 'Offload weights to CPU when possible.'),
  field('params_backend', 'string', 'vae=cpu', 'Per-component backend override.'),
  field('vae_tiling', 'boolean', true, 'Enable VAE tiling.'),
  field('backend', 'string', '', 'Diffusion backend override.'),
  field('max_vram', 'string|number', config.maxVram || '', 'Maximum VRAM budget.'),
  field('stream_layers', 'boolean', false, 'Stream layers for very large models.'),
  field('flash_attn', 'boolean', false, 'Flash attention for Qwen image models.'),
  field('prediction', 'string', '', 'Prediction type, for example v or flux2_flow.'),
  field('lora_apply_mode', 'string', '', 'LoRA apply mode, for example at_runtime.'),
  field('upscaler', 'object', {}, 'Paired ESRGAN upscaler: {type:"esrgan", model_src, tile_size}.'),
  field('family', 'string', '', 'Optional family hint used for parameter validation.'),
  field('mock', 'boolean', config.mock, 'Mock-load the model without touching native libraries.'),
];

const KNOWN_MODELS = [
  { name: 'WAN2_1_T2V_1_3B_FP16', family: 'wan2.1_t2v', kind: 'diffusion', file: 'gguf', modes: ['txt2vid'], description: 'Wan 2.1 text-to-video 1.3B diffusion model.' },
  { name: 'WAN2_1_I2V_14B_Q4_K_M', family: 'wan2.1_i2v', kind: 'diffusion', file: 'gguf', modes: ['img2vid'], description: 'Wan 2.1 image-to-video 14B Q4_K_M diffusion model.' },
  { name: 'WAN2_2_TI2V_5B_Q5_K_S', family: 'wan2.2_ti2v', kind: 'diffusion', file: 'gguf', modes: ['txt2vid', 'img2vid'], description: 'Wan 2.2 TI2V-5B Turbo Q5_K_S diffusion model.' },
  { name: 'LTX_2_3_22B_Q5_K_M', family: 'ltx2', kind: 'diffusion', file: 'gguf', modes: ['txt2vid', 'img2vid'], description: 'LTX-2.3 22B Q5_K_M diffusion model with optional synchronized audio.' },
  { name: 'UMT5_XXL_FP16', family: 'wan2.1_t2v', kind: 'text_encoder', file: 'safetensors', modes: [], description: 'UMT5-XXL FP16 text encoder shared by Wan 2.1 and Wan 2.2.' },
  { name: 'WAN_2_1_COMFYUI_REPACKAGED_VAE', family: 'wan2.1_t2v', kind: 'vae', file: 'safetensors', modes: [], description: 'Wan 2.1 repackaged VAE.' },
  { name: 'WAN_2_2_COMFYUI_REPACKAGED_VAE', family: 'wan2.2_ti2v', kind: 'vae', file: 'safetensors', modes: [], description: 'Wan 2.2 repackaged VAE.' },
  { name: 'CLIP_VISION_H', family: 'wan2.1_i2v', kind: 'clip_vision', file: 'safetensors', modes: [], description: 'OpenCLIP ViT-H/14 vision encoder for Wan I2V.' },
  { name: 'LTX_2_3_VIDEO_VAE', family: 'ltx2', kind: 'vae', file: 'safetensors', modes: [], description: 'LTX-2 video VAE.' },
  { name: 'LTX_2_3_AUDIO_VAE', family: 'ltx2', kind: 'audio_vae', file: 'safetensors', modes: [], description: 'LTX-2 audio VAE for synchronized 48 kHz audio.' },
  { name: 'LTX_2_3_22B_DISTILLED_EMBEDDINGS_CONNECTORS', family: 'ltx2', kind: 'connectors', file: 'safetensors', modes: [], description: 'LTX-2 distilled text-embedding connectors.' },
  { name: 'GEMMA_3_12B_Q4_K_XL', family: 'ltx2', kind: 'text_encoder', file: 'gguf', modes: [], description: 'Gemma 3 12B Q4_K_XL text encoder for LTX-2.' },
  { name: 'SD_V2_1_1B_Q8_0', family: 'sd1_sd2', kind: 'diffusion', file: 'gguf', modes: ['txt2img', 'img2img'], description: 'Stable Diffusion 2.1 1B Q8_0 all-in-one image model.' },
  { name: 'FLUX_2_KLEIN_4B_Q4_0', family: 'flux2_klein', kind: 'diffusion', file: 'gguf', modes: ['txt2img', 'img2img'], description: 'FLUX.2-klein 4B Q4_0 image diffusion model.' },
  { name: 'FLUX_2_KLEIN_4B_VAE', family: 'flux2_klein', kind: 'vae', file: 'safetensors', modes: [], description: 'FLUX.2-klein VAE.' },
  { name: 'QWEN3_4B_Q4_K_M', family: 'flux2_klein', kind: 'text_encoder', file: 'gguf', modes: [], description: 'Qwen3 4B text encoder used by FLUX.2-klein.' },
  { name: 'REALESRGAN_X4PLUS', family: 'esrgan', kind: 'upscaler', file: 'pth', modes: ['upscale'], description: 'Real-ESRGAN x4plus upscaler.' },
  { name: 'REALESRGAN_X4PLUS_ANIME_6B', family: 'esrgan', kind: 'upscaler', file: 'pth', modes: ['upscale'], description: 'Real-ESRGAN x4plus anime 6B upscaler.' },
];

const VIDEO_FAMILIES = {
  'wan2.1_t2v': {
    label: 'Wan 2.1 T2V',
    kind: 'video',
    modes: ['txt2vid'],
    modelType: 'sdcpp-generation',
    modelConfigMode: 'video',
    requires: {
      modelSrc: ['WAN2_1_T2V_1_3B_FP16'],
      t5XxlModelSrc: ['UMT5_XXL_FP16'],
      vaeModelSrc: ['WAN_2_1_COMFYUI_REPACKAGED_VAE'],
    },
    constraints: { dimensionMultipleOf: 16, frames: '4k+1', maxFrames: 81, minFrames: 17, defaultFps: 16, defaultFlowShift: 3, supportsAudioVae: false },
  },
  'wan2.1_i2v': {
    label: 'Wan 2.1 I2V',
    kind: 'video',
    modes: ['img2vid'],
    modelType: 'sdcpp-generation',
    modelConfigMode: 'video',
    requires: {
      modelSrc: ['WAN2_1_I2V_14B_Q4_K_M'],
      t5XxlModelSrc: ['UMT5_XXL_FP16'],
      vaeModelSrc: ['WAN_2_1_COMFYUI_REPACKAGED_VAE'],
      clipVisionModelSrc: ['CLIP_VISION_H'],
    },
    constraints: { dimensionMultipleOf: 16, frames: '4k+1', maxFrames: 81, minFrames: 17, defaultFps: 16, defaultFlowShift: 3, supportsAudioVae: false },
  },
  'wan2.2_ti2v': {
    label: 'Wan 2.2 TI2V-5B',
    kind: 'video',
    modes: ['txt2vid', 'img2vid'],
    modelType: 'sdcpp-generation',
    modelConfigMode: 'video',
    requires: {
      modelSrc: ['WAN2_2_TI2V_5B_Q5_K_S'],
      t5XxlModelSrc: ['UMT5_XXL_FP16'],
      vaeModelSrc: ['WAN_2_2_COMFYUI_REPACKAGED_VAE'],
    },
    constraints: { dimensionMultipleOf: 32, frames: '4k+1', maxFrames: 257, minFrames: 5, defaultFps: 24, defaultFlowShift: 5, supportsAudioVae: false },
  },
  'wan2.2_a14b': {
    label: 'Wan 2.2 A14B dual-expert',
    kind: 'video',
    modes: ['txt2vid'],
    modelType: 'sdcpp-generation',
    modelConfigMode: 'video',
    requires: {
      modelSrc: ['<low-noise diffusion model path>'],
      highNoiseDiffusionModelSrc: ['<high-noise diffusion model path>'],
      t5XxlModelSrc: ['UMT5_XXL_FP16'],
      vaeModelSrc: ['WAN_2_2_COMFYUI_REPACKAGED_VAE'],
    },
    constraints: { dimensionMultipleOf: 16, frames: '4k+1', maxFrames: 257, minFrames: 5, defaultFps: 16, defaultFlowShift: 5, supportsAudioVae: false, dualExpert: true },
  },
  ltx2: {
    label: 'LTX-2',
    kind: 'video',
    modes: ['txt2vid', 'img2vid'],
    modelType: 'sdcpp-generation',
    modelConfigMode: 'video',
    requires: {
      modelSrc: ['LTX_2_3_22B_Q5_K_M'],
      llmModelSrc: ['GEMMA_3_12B_Q4_K_XL'],
      vaeModelSrc: ['LTX_2_3_VIDEO_VAE'],
      embeddingsConnectorsModelSrc: ['LTX_2_3_22B_DISTILLED_EMBEDDINGS_CONNECTORS'],
      audioVaeModelSrc: ['LTX_2_3_AUDIO_VAE'],
    },
    constraints: {
      dimensionMultipleOf: 32,
      frames: '8k+1',
      maxFrames: 257,
      minFrames: 9,
      referenceMinFrames: 121,
      defaultFps: 24,
      supportsAudioVae: true,
      supportsTemporalTiling: true,
      supportsReferenceConditioning: true,
    },
  },
  minimax_h3: {
    label: 'MiniMax-H3',
    kind: 'video',
    modes: ['txt2vid', 'img2vid'],
    modelType: 'sdcpp-generation',
    modelConfigMode: 'video',
    requires: {
      modelSrc: ['<MiniMax-H3 diffusion model path>'],
      llmModelSrc: ['<Qwen3-VL text encoder path>'],
      vaeModelSrc: ['<MiniMax-H3 video VAE path>'],
      audioVaeModelSrc: ['<optional MiniMax-H3 audio VAE path>'],
    },
    constraints: {
      dimensionMultipleOf: 32,
      frames: '17k+5',
      maxFrames: 260,
      minFrames: 5,
      fixedFps: 24,
      defaultFps: 24,
      supportsAudioVae: true,
      rejectsStrength: true,
    },
  },
};

const IMAGE_FAMILIES = {
  flux2_klein: {
    label: 'FLUX.2-klein',
    kind: 'image',
    modes: ['txt2img', 'img2img'],
    modelType: 'sdcpp-generation',
    requires: {
      modelSrc: ['FLUX_2_KLEIN_4B_Q4_0'],
      llmModelSrc: ['QWEN3_4B_Q4_K_M'],
      vaeModelSrc: ['FLUX_2_KLEIN_4B_VAE'],
    },
    constraints: { dimensionMultipleOf: 8, initImageNeedsPrediction: 'flux2_flow', supportsUpscale: true, initImagesMutuallyExclusive: true },
  },
  qwen_image_2_1: {
    label: 'Qwen-Image-2.1',
    kind: 'image',
    modes: ['txt2img', 'img2img', 'reference'],
    modelType: 'sdcpp-generation',
    requires: {
      modelSrc: ['<Qwen-Image-2.1 diffusion model path>'],
      llmModelSrc: ['<Qwen3-VL encoder path>'],
      vaeModelSrc: ['<Qwen-Image-2.1 VAE path>'],
      projectionModelSrc: ['<Qwen3-VL vision projector path>'],
    },
    constraints: { dimensionMultipleOf: 8, supportsUpscale: false, supportsInitImages: true, initImagesMutuallyExclusive: true, outputCanBeRgba: true },
  },
  ideogram4: {
    label: 'Ideogram 4',
    kind: 'image',
    modes: ['txt2img'],
    modelType: 'sdcpp-generation',
    requires: {
      modelSrc: ['<Ideogram 4 diffusion model path>'],
      uncondModelSrc: ['<Ideogram 4 unconditional model path>'],
      llmModelSrc: ['<Qwen3-VL encoder path>'],
      vaeModelSrc: ['<Ideogram 4 VAE path>'],
    },
    constraints: { dimensionMultipleOf: 8, structuredJsonPrompt: true, supportsUpscale: true },
  },
  sd1_sd2: {
    label: 'Stable Diffusion 1.x / 2.x',
    kind: 'image',
    modes: ['txt2img', 'img2img'],
    modelType: 'sdcpp-generation',
    requires: { modelSrc: ['SD_V2_1_1B_Q8_0'] },
    constraints: { dimensionMultipleOf: 8, sdeditStrength: true, supportsUpscale: true, singleFile: true },
  },
  sdxl_sd3: {
    label: 'SDXL / SD3',
    kind: 'image',
    modes: ['txt2img', 'img2img'],
    modelType: 'sdcpp-generation',
    requires: { modelSrc: ['<SDXL/SD3 diffusion model path>'], clipLModelSrc: [], clipGModelSrc: [], t5XxlModelSrc: [] },
    constraints: { dimensionMultipleOf: 8, sdeditStrength: true, supportsUpscale: true },
  },
  esrgan: {
    label: 'Real-ESRGAN',
    kind: 'upscale',
    modes: ['upscale'],
    modelType: 'sdcpp-generation',
    modelConfigMode: 'upscale',
    requires: { modelSrc: ['REALESRGAN_X4PLUS', 'REALESRGAN_X4PLUS_ANIME_6B'] },
    constraints: { repeats: { minimum: 1, maximum: config.limits.maxUpscaleRepeats }, rgbOnly: true },
  },
};

function modelCatalog(sdkConstants = [], { installed = new Set(), loaded = new Set(), sizes = {} } = {}) {
  const availableConstants = new Set(sdkConstants);
  return KNOWN_MODELS.map((model) => ({
    ...model,
    resolved: availableConstants.has(model.name),
    available: availableConstants.has(model.name) || config.mock,
    mockAvailable: config.mock,
    installed: installed.has(model.name) || loaded.has(model.name),
    size_bytes: Number(sizes[model.name]) || null,
  }));
}

function requiredModels(definition) {
  const names = new Set();
  for (const values of Object.values((definition && definition.requires) || {})) {
    for (const value of Array.isArray(values) ? values : []) {
      const name = String(value || '').trim();
      if (!name || name.startsWith('<')) continue;
      names.add(name);
    }
  }
  return [...names];
}

function hasPlaceholders(definition) {
  return Object.values((definition && definition.requires) || {}).some((values) =>
    (Array.isArray(values) ? values : []).some((value) =>
      String(value || '').trim().startsWith('<'),
    ),
  );
}

function familyCatalog(families, models) {
  const definitions = new Map(models.map((model) => [model.name, model]));
  return Object.fromEntries(
    Object.entries(families).map(([key, definition]) => {
      const required = requiredModels(definition);
      const missing = required.filter((name) => !definitions.has(name));
      const placeholders = hasPlaceholders(definition);
      const installed = required.length > 0 && required.every((name) => {
        const model = definitions.get(name);
        return Boolean(model && model.installed);
      });
      const sizeBytes = required.reduce((sum, name) => {
        const model = definitions.get(name);
        return sum + (model && Number(model.size_bytes) ? Number(model.size_bytes) : 0);
      }, 0);
      return [
        key,
        {
          ...definition,
          install: {
            available: !placeholders && missing.length === 0 && required.length > 0,
            installed,
            models: required,
            missing,
            placeholders,
            size_bytes: sizeBytes || null,
          },
        },
      ];
    }),
  );
}

function familyForModel(modelName) {
  const entry = KNOWN_MODELS.find((model) => model.name === modelName);
  return entry ? entry.family : null;
}

function buildCatalog({ sdkInfo, memory, installed = new Set(), loaded = [] }) {
  const loadedNames = new Set(
    (loaded || [])
      .map((item) => String(item && (item.modelName || item.model) || ''))
      .filter(Boolean),
  );
  const models = modelCatalog((sdkInfo && sdkInfo.constants) || [], {
    installed,
    loaded: loadedNames,
    sizes: (sdkInfo && sdkInfo.model_sizes) || {},
  });
  return {
    service: 'qvac',
    version: config.version,
    sdk: {
      package: '@qvac/sdk',
      declared_version: config.sdkPackageVersion,
      sdk_version: (sdkInfo && sdkInfo.version) || null,
      available: Boolean(sdkInfo && sdkInfo.available),
      error: sdkInfo ? sdkInfo.error : null,
      constants_count: sdkInfo ? (sdkInfo.constants || []).length : 0,
      constants: sdkInfo ? (sdkInfo.constants || []) : [],
      mock: config.mock,
    },
    models,
    model_families: {
      video: familyCatalog(VIDEO_FAMILIES, models),
      image: familyCatalog(IMAGE_FAMILIES, models),
    },
    devices: {
      requested: config.device,
      supported: ['gpu', 'cpu'],
      gpu_available: Boolean(memory && memory.gpu && memory.gpu.available),
      vulkan: Boolean(memory && memory.vulkan && memory.vulkan.available),
      memory: memory || null,
    },
    modes: {
      video: ['txt2vid', 'img2vid'],
      image: ['txt2img', 'img2img', 'reference'],
      upscale: ['upscale'],
    },
    constraints: {
      video: {
        width_height_multiple_of: 16,
        strict_multiple_of_32: ['ltx2', 'wan2.2_ti2v', 'minimax_h3'],
        frame_formulas: { wan: '4k+1', ltx2: '8k+1 (max 257)', minimax_h3: '17k+5 at 24 fps' },
        fps: { minimum: 1, maximum: 120, minimax_h3: 24 },
        steps: { minimum: 1, maximum: config.limits.maxSteps },
        seed: { minimum: -1 },
        max_frames: config.limits.maxVideoFrames,
      },
      image: {
        width_height_multiple_of: 8,
        batch_count: { minimum: 1, maximum: config.limits.maxImageBatch },
        seed: { minimum: -1 },
        upscale_repeats: { minimum: 1, maximum: config.limits.maxUpscaleRepeats },
      },
      hardware: config.requirements,
    },
    parameters: {
      video: VIDEO_PARAMS,
      image: IMAGE_PARAMS,
      upscale: UPSCALE_PARAMS,
      model_load: LOAD_PARAMS,
    },
    defaults: {
      device: config.device,
      video: {
        mode: 'txt2vid',
        negative_prompt: 'blurry, low quality, static, jittery, watermark',
        width: 480,
        height: 832,
        video_frames: 33,
        fps: 16,
        steps: 30,
        cfg_scale: 6,
        flow_shift: 3,
        seed: 42,
        vae_tiling: true,
      },
      image: {
        negative_prompt: 'blurry, low quality, watermark, text',
        width: 512,
        height: 512,
        steps: 20,
        guidance: 3.5,
        cfg_scale: 1,
        seed: -1,
        batch_count: 1,
      },
      model_load: {
        modelType: 'sdcpp-generation',
        device: config.device,
        threads: 4,
        diffusion_fa: true,
        offload_to_cpu: true,
        vae_tiling: true,
        params_backend: 'vae=cpu',
      },
      upscale: { model: 'REALESRGAN_X4PLUS', repeats: 1, tile_size: 128 },
    },
    memory: memory || null,
    mock: config.mock,
    endpoints: [
      'GET /health',
      'GET /api/qvac/catalog',
      'GET /api/qvac/status',
      'POST /api/qvac/models/install',
      'POST /api/qvac/models/load',
      'POST /api/qvac/models/unload',
      'GET /api/qvac/models/loaded',
      'POST /api/qvac/video',
      'POST /api/qvac/image',
      'POST /api/qvac/upscale',
      'POST /internal/jobs/run',
      'POST /internal/jobs/{job_id}/cancel',
      'GET /internal/jobs/{job_id}/cancel-state',
    ],
    generated_at: new Date().toISOString(),
  };
}

module.exports = {
  VIDEO_PARAMS,
  IMAGE_PARAMS,
  UPSCALE_PARAMS,
  LOAD_PARAMS,
  KNOWN_MODELS,
  VIDEO_FAMILIES,
  IMAGE_FAMILIES,
  buildCatalog,
  modelCatalog,
  familyForModel,
};
