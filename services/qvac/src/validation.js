'use strict';

const config = require('./config');
const { HttpError } = require('./errors');
const { VIDEO_PARAMS, IMAGE_PARAMS, UPSCALE_PARAMS, LOAD_PARAMS, VIDEO_FAMILIES, IMAGE_FAMILIES, familyForModel } = require('./catalog');

const VIDEO_FIELDS = new Set(VIDEO_PARAMS.map((item) => item.name));
const IMAGE_FIELDS = new Set(IMAGE_PARAMS.map((item) => item.name));
const UPSCALE_FIELDS = new Set(UPSCALE_PARAMS.map((item) => item.name));
const LOAD_FIELDS = new Set(LOAD_PARAMS.map((item) => item.name));

function assertObject(value, label) {
  if (value === undefined || value === null) return {};
  if (typeof value !== 'object' || Array.isArray(value)) throw new HttpError(422, `${label} must be an object`);
  return value;
}

function rejectUnknown(payload, allowed, label) {
  const unknown = Object.keys(payload).filter((key) => !allowed.has(key) && !['title', 'family', 'sync'].includes(key));
  if (unknown.length) {
    throw new HttpError(422, `Unknown ${label} field(s): ${unknown.join(', ')}`);
  }
}

function requiredString(value, name) {
  if (typeof value !== 'string' || value.trim() === '') throw new HttpError(422, `${name} is required`);
  return value.trim();
}

function optionalString(value, name, maxLength = 20000) {
  if (value === undefined || value === null || value === '') return undefined;
  if (typeof value !== 'string') throw new HttpError(422, `${name} must be a string`);
  if (value.length > maxLength) throw new HttpError(422, `${name} is too long`);
  if (value.includes('\0')) throw new HttpError(422, `${name} cannot contain null bytes`);
  return value;
}

function intValue(value, name, { minimum, maximum, fallback } = {}) {
  if (value === undefined || value === null || value === '') return fallback;
  const parsed = Number(value);
  if (!Number.isInteger(parsed)) throw new HttpError(422, `${name} must be an integer`);
  if (minimum !== undefined && parsed < minimum) throw new HttpError(422, `${name} must be >= ${minimum}`);
  if (maximum !== undefined && parsed > maximum) throw new HttpError(422, `${name} must be <= ${maximum}`);
  return parsed;
}

function numberValue(value, name, { minimum, maximum, fallback } = {}) {
  if (value === undefined || value === null || value === '') return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new HttpError(422, `${name} must be a number`);
  if (minimum !== undefined && parsed < minimum) throw new HttpError(422, `${name} must be >= ${minimum}`);
  if (maximum !== undefined && parsed > maximum) throw new HttpError(422, `${name} must be <= ${maximum}`);
  return parsed;
}

function booleanValue(value, name, fallback) {
  if (value === undefined || value === null || value === '') return fallback;
  if (typeof value === 'boolean') return value;
  if (value === 0 || value === 1) return Boolean(value);
  if (typeof value === 'string') {
    if (['true', '1', 'yes', 'on'].includes(value.toLowerCase())) return true;
    if (['false', '0', 'no', 'off'].includes(value.toLowerCase())) return false;
  }
  throw new HttpError(422, `${name} must be a boolean`);
}

function enumValue(value, name, allowed, fallback) {
  if (value === undefined || value === null || value === '') return fallback;
  const text = String(value);
  if (!allowed.includes(text)) throw new HttpError(422, `${name} must be one of: ${allowed.join(', ')}`);
  return text;
}

function validateDimensions(widthValue, heightValue, family, kind) {
  const limits = kind === 'video'
    ? { maxWidth: config.limits.maxWidth, maxHeight: config.limits.maxHeight, minimum: 16 }
    : { maxWidth: 8192, maxHeight: 8192, minimum: 8 };
  const width = intValue(widthValue, 'width', { minimum: limits.minimum, maximum: limits.maxWidth });
  const height = intValue(heightValue, 'height', { minimum: limits.minimum, maximum: limits.maxHeight });
  const multiple = family && family.constraints && family.constraints.dimensionMultipleOf
    ? family.constraints.dimensionMultipleOf
    : (kind === 'video' ? 16 : 8);
  if (width !== undefined && width % multiple !== 0) {
    throw new HttpError(422, `width must be a multiple of ${multiple} for this model family`);
  }
  if (height !== undefined && height % multiple !== 0) {
    throw new HttpError(422, `height must be a multiple of ${multiple} for this model family`);
  }
  return { width, height, multiple };
}

function resolveFamily(payload, kind) {
  const known = kind === 'video' ? VIDEO_FAMILIES : IMAGE_FAMILIES;
  const hint = optionalString(payload.family, 'family');
  if (hint) {
    if (!known[hint]) throw new HttpError(422, `Unknown ${kind} family: ${hint}`);
    return hint;
  }
  const model = typeof payload.model === 'string' ? payload.model.trim() : '';
  if (model && /^[A-Z][A-Z0-9_]+$/.test(model)) {
    const family = familyForModel(model);
    if (family && known[family]) return family;
  }
  return null;
}

function modelReference(payload) {
  const modelId = optionalString(payload.model_id, 'model_id');
  const model = optionalString(payload.model, 'model');
  const modelConfig = payload.model_config === undefined ? undefined : assertObject(payload.model_config, 'model_config');
  if (!modelId && !model && !(modelConfig && modelConfig.modelSrc)) {
    throw new HttpError(422, 'Provide model_id, model, or model_config.modelSrc');
  }
  return { modelId, model, modelConfig };
}

function hasValue(value) {
  return value !== undefined && value !== null && value !== '';
}

function validateVideo(payload) {
  rejectUnknown(payload, VIDEO_FIELDS, 'video');
  const prompt = requiredString(payload.prompt, 'prompt');
  const mode = enumValue(payload.mode, 'mode', ['txt2vid', 'img2vid'], 'txt2vid');
  const familyName = resolveFamily(payload, 'video');
  const family = familyName ? VIDEO_FAMILIES[familyName] : null;
  const warnings = [];
  const { modelId, model, modelConfig } = modelReference(payload);
  const initImage = optionalString(payload.init_image, 'init_image');
  if (mode === 'img2vid' && !initImage) {
    throw new HttpError(422, 'init_image is required for img2vid');
  }
  if (family && !family.modes.includes(mode)) {
    throw new HttpError(422, `${family.label} does not support mode ${mode}`);
  }
  if (mode === 'img2vid' && familyName && familyName.startsWith('wan2.1_t2v')) {
    throw new HttpError(422, 'Wan 2.1 T2V checkpoints cannot run img2vid; use WAN2_1_I2V_14B_Q4_K_M');
  }
  const dimensions = validateDimensions(payload.width, payload.height, family, 'video');
  const videoFrames = intValue(payload.video_frames, 'video_frames', { minimum: 1, maximum: config.limits.maxVideoFrames });
  const fps = intValue(payload.fps, 'fps', { minimum: 1, maximum: 120 });
  const steps = intValue(payload.steps, 'steps', { minimum: 1, maximum: config.limits.maxSteps });
  const seed = intValue(payload.seed, 'seed', { minimum: -1 });
  const cfgScale = numberValue(payload.cfg_scale, 'cfg_scale', { minimum: 0, maximum: 30 });
  const flowShift = numberValue(payload.flow_shift, 'flow_shift', { minimum: 0, maximum: 20 });
  const strength = numberValue(payload.strength, 'strength', { minimum: 0, maximum: 1 });
  const loraStrength = numberValue(payload.lora_strength, 'lora_strength', { minimum: -10, maximum: 10 });
  const stgScale = numberValue(payload.stg_scale, 'stg_scale');
  const stgBlock = intValue(payload.stg_block, 'stg_block', { minimum: 0 });
  const referenceAttention = numberValue(payload.reference_attention_strength, 'reference_attention_strength', { minimum: 0, maximum: 10 });
  const referenceDownscale = intValue(payload.reference_downscale_factor, 'reference_downscale_factor', { minimum: 1, maximum: 16 });
  const vaeTileSize = intValue(payload.vae_tile_size, 'vae_tile_size', { minimum: 1, maximum: 128 });
  const moeBoundary = numberValue(payload.moe_boundary, 'moe_boundary', { minimum: 0, maximum: 1 });
  const timeout = numberValue(payload.timeout, 'timeout', { minimum: 1 });
  const highNoiseFields = ['high_noise_steps', 'high_noise_sample_method', 'high_noise_scheduler', 'high_noise_cfg_scale', 'high_noise_flow_shift'];
  const hasHighNoise = highNoiseFields.some((name) => hasValue(payload[name])) || hasValue(moeBoundary);
  if (hasHighNoise && familyName && familyName !== 'wan2.2_a14b') {
    throw new HttpError(422, `${family.label} is a single-expert layout and rejects high_noise_* / moe_boundary`);
  }
  if (familyName === 'wan2.2_a14b') {
    if (!hasValue(payload.model_config && payload.model_config.highNoiseDiffusionModelSrc) && !hasValue(payload.highNoiseDiffusionModelSrc)) {
      warnings.push('Wan 2.2 A14B needs highNoiseDiffusionModelSrc to load the high-noise expert.');
    }
  }
  const referenceImages = payload.reference_images === undefined || payload.reference_images === null ? [] : payload.reference_images;
  if (!Array.isArray(referenceImages)) throw new HttpError(422, 'reference_images must be an array');
  if (referenceImages.length > config.limits.maxReferenceImages) {
    throw new HttpError(422, `reference_images supports at most ${config.limits.maxReferenceImages} images`);
  }
  for (const [index, item] of referenceImages.entries()) {
    if (typeof item !== 'string' || item.trim() === '') throw new HttpError(422, `reference_images[${index}] must be a path`);
  }
  let scheduler = optionalString(payload.scheduler, 'scheduler');
  let referenceDownscaleFactor = referenceDownscale;
  let resolvedFrames = videoFrames;
  if (referenceImages.length) {
    if (familyName && familyName !== 'ltx2') {
      throw new HttpError(422, 'reference_images conditioning is only supported by LTX-2');
    }
    if (!optionalString(payload.lora, 'lora')) {
      throw new HttpError(422, 'lora is required with reference_images (LTX-2 IC-LoRA)');
    }
    if (scheduler && scheduler !== 'ltx2') throw new HttpError(422, 'scheduler must be "ltx2" for reference conditioning');
    scheduler = 'ltx2';
    referenceDownscaleFactor = referenceDownscale === undefined ? 1 : referenceDownscale;
    if (referenceDownscaleFactor !== 1) throw new HttpError(422, 'reference_downscale_factor must be 1 for LTX-2');
    if (resolvedFrames === undefined) {
      resolvedFrames = 121;
      warnings.push('video_frames defaulted to 121 because LTX-2 reference conditioning requires at least 121 frames.');
    }
    if (resolvedFrames < 121) throw new HttpError(422, 'LTX-2 reference conditioning requires at least 121 video_frames');
  }
  if (familyName && family.constraints) {
    const rules = family.constraints;
    if (rules.frames && resolvedFrames !== undefined) {
      const frames = resolvedFrames;
      if (rules.frames === '4k+1' && (frames - 1) % 4 !== 0) throw new HttpError(422, 'video_frames must satisfy 4k+1 for this family');
      if (rules.frames === '8k+1' && ((frames - 1) % 8 !== 0 || frames > 257)) throw new HttpError(422, 'video_frames must satisfy 8k+1 with a maximum of 257 for LTX-2');
      if (rules.frames === '17k+5' && (frames - 5) % 17 !== 0) throw new HttpError(422, 'video_frames must satisfy 17k+5 for MiniMax-H3');
      if (rules.minFrames && frames < rules.minFrames) throw new HttpError(422, `video_frames must be at least ${rules.minFrames} for this family`);
      if (rules.maxFrames && frames > rules.maxFrames) throw new HttpError(422, `video_frames must be at most ${rules.maxFrames} for this family`);
      if (rules.referenceMinFrames && referenceImages.length && frames < rules.referenceMinFrames) throw new HttpError(422, `LTX-2 reference conditioning needs at least ${rules.referenceMinFrames} frames`);
    }
    if (rules.fixedFps && fps !== undefined && fps !== rules.fixedFps) throw new HttpError(422, `fps must be ${rules.fixedFps} for this family`);
    if (rules.rejectsStrength && strength !== undefined) throw new HttpError(422, 'strength is rejected by MiniMax-H3 keyframe conditioning');
    if (rules.supportsTemporalTiling === false && booleanValue(payload.temporal_tiling, 'temporal_tiling', false)) {
      warnings.push('temporal_tiling only affects LTX-2; it is ignored by this family.');
    }
  }
  const referenceImagesValue = referenceImages.map((item) => item.trim());
  const lora = optionalString(payload.lora, 'lora');
  const normalized = {
    mode,
    prompt,
    negative_prompt: optionalString(payload.negative_prompt, 'negative_prompt'),
    init_image: initImage,
    control_frames: payload.control_frames === undefined ? undefined : payload.control_frames,
    width: dimensions.width,
    height: dimensions.height,
    video_frames: resolvedFrames,
    fps,
    steps,
    cfg_scale: cfgScale,
    flow_shift: flowShift,
    seed,
    scheduler,
    strength,
    reference_images: referenceImagesValue.length ? referenceImagesValue : undefined,
    lora,
    lora_strength: loraStrength,
    stg_scale: stgScale,
    stg_block: stgBlock,
    reference_attention_strength: referenceAttention,
    reference_downscale_factor: referenceDownscaleFactor,
    temporal_tiling: payload.temporal_tiling === undefined ? undefined : booleanValue(payload.temporal_tiling, 'temporal_tiling', false),
    vae_tile_size: vaeTileSize,
    high_noise_steps: intValue(payload.high_noise_steps, 'high_noise_steps', { minimum: 1, maximum: config.limits.maxSteps }),
    high_noise_sample_method: optionalString(payload.high_noise_sample_method, 'high_noise_sample_method'),
    high_noise_scheduler: optionalString(payload.high_noise_scheduler, 'high_noise_scheduler'),
    high_noise_cfg_scale: numberValue(payload.high_noise_cfg_scale, 'high_noise_cfg_scale', { minimum: 0, maximum: 30 }),
    high_noise_flow_shift: numberValue(payload.high_noise_flow_shift, 'high_noise_flow_shift', { minimum: 0, maximum: 20 }),
    moe_boundary: moeBoundary,
    vae_tiling: payload.vae_tiling === undefined ? undefined : booleanValue(payload.vae_tiling, 'vae_tiling', true),
    output_format: enumValue(payload.output_format, 'output_format', ['both', 'mp4', 'avi'], 'both'),
    timeout,
    model_id: modelId,
    model,
    model_config: modelConfig,
  };
  if (payload.control_frames !== undefined) {
    if (!Array.isArray(payload.control_frames)) throw new HttpError(422, 'control_frames must be an array');
    if (payload.control_frames.length > config.limits.maxReferenceImages) throw new HttpError(422, 'too many control_frames');
    for (const [index, item] of payload.control_frames.entries()) {
      if (typeof item !== 'string' || item.trim() === '') throw new HttpError(422, `control_frames[${index}] must be a path`);
    }
    normalized.control_frames = payload.control_frames.map((item) => item.trim());
  }
  for (const key of Object.keys(normalized)) {
    if (normalized[key] === undefined) delete normalized[key];
  }
  return { params: normalized, family: familyName, warnings };
}

function validateImage(payload) {
  rejectUnknown(payload, IMAGE_FIELDS, 'image');
  const prompt = requiredString(payload.prompt, 'prompt');
  const familyName = resolveFamily(payload, 'image');
  const family = familyName ? IMAGE_FAMILIES[familyName] : null;
  const warnings = [];
  const { modelId, model, modelConfig } = modelReference(payload);
  const dimensions = validateDimensions(payload.width, payload.height, family, 'image');
  const steps = intValue(payload.steps, 'steps', { minimum: 1, maximum: config.limits.maxSteps });
  const guidance = numberValue(payload.guidance, 'guidance', { minimum: 0, maximum: 30 });
  const cfgScale = numberValue(payload.cfg_scale, 'cfg_scale', { minimum: 0, maximum: 30 });
  const seed = intValue(payload.seed, 'seed', { minimum: -1 });
  const batchCount = intValue(payload.batch_count, 'batch_count', { minimum: 1, maximum: config.limits.maxImageBatch });
  const strength = numberValue(payload.strength, 'strength', { minimum: 0, maximum: 1 });
  const loraStrength = numberValue(payload.lora_strength, 'lora_strength', { minimum: -10, maximum: 10 });
  const initImage = optionalString(payload.init_image, 'init_image');
  const initImages = payload.init_images === undefined || payload.init_images === null ? [] : payload.init_images;
  if (!Array.isArray(initImages)) throw new HttpError(422, 'init_images must be an array');
  if (initImages.length > config.limits.maxReferenceImages) throw new HttpError(422, 'too many init_images');
  for (const [index, item] of initImages.entries()) {
    if (typeof item !== 'string' || item.trim() === '') throw new HttpError(422, `init_images[${index}] must be a path`);
  }
  if (initImage && initImages.length) throw new HttpError(422, 'init_image and init_images are mutually exclusive');
  if (familyName === 'ideogram4' && !prompt.trim().startsWith('{')) {
    warnings.push('Ideogram 4 expects a JSON-serialized structured caption; a plain prompt may produce placeholder output.');
  }
  let upscale = payload.upscale;
  if (upscale !== undefined && typeof upscale !== 'boolean') {
    if (!upscale || typeof upscale !== 'object' || Array.isArray(upscale)) {
      throw new HttpError(422, 'upscale must be a boolean or {repeats:N}');
    }
    const repeats = intValue(upscale.repeats, 'upscale.repeats', { minimum: 1, maximum: config.limits.maxUpscaleRepeats });
    upscale = { repeats };
  }
  if (familyName === 'qwen_image_2_1' && upscale && (upscale === true || (upscale && upscale.repeats))) {
    throw new HttpError(422, 'Qwen-Image-2.1 produces RGBA and rejects post-generation upscaling');
  }
  if (initImage && familyName === 'flux2_klein') {
    if (modelConfig && modelConfig.prediction && modelConfig.prediction !== 'flux2_flow') {
      throw new HttpError(422, 'FLUX.2 img2img requires modelConfig.prediction="flux2_flow"');
    }
    warnings.push('FLUX.2 img2img requires the model to be loaded with prediction="flux2_flow".');
  }
  const samplingMethod = optionalString(payload.sampler, 'sampler') || optionalString(payload.sampling_method, 'sampling_method');
  const normalized = {
    prompt,
    negative_prompt: optionalString(payload.negative_prompt, 'negative_prompt'),
    width: dimensions.width,
    height: dimensions.height,
    steps,
    guidance,
    cfg_scale: cfgScale,
    seed,
    batch_count: batchCount,
    sampling_method: samplingMethod,
    scheduler: optionalString(payload.scheduler, 'scheduler'),
    init_image: initImage,
    init_images: initImages.length ? initImages.map((item) => item.trim()) : undefined,
    strength,
    lora: optionalString(payload.lora, 'lora'),
    lora_strength: loraStrength,
    upscale,
    output_format: enumValue(payload.output_format, 'output_format', ['png'], 'png'),
    timeout: numberValue(payload.timeout, 'timeout', { minimum: 1 }),
    model_id: modelId,
    model,
    model_config: modelConfig,
  };
  for (const key of Object.keys(normalized)) {
    if (normalized[key] === undefined) delete normalized[key];
  }
  return { params: normalized, family: familyName, warnings };
}

function validateUpscale(payload) {
  rejectUnknown(payload, UPSCALE_FIELDS, 'upscale');
  const imagePath = requiredString(payload.image_path, 'image_path');
  const repeats = intValue(payload.repeats, 'repeats', { minimum: 1, maximum: config.limits.maxUpscaleRepeats }) || 1;
  const tileSize = intValue(payload.tile_size, 'tile_size', { minimum: 16, maximum: 1024 });
  return {
    params: {
      image_path: imagePath,
      model_id: optionalString(payload.model_id, 'model_id'),
      model: optionalString(payload.model, 'model') || (payload.model_id ? undefined : 'REALESRGAN_X4PLUS'),
      repeats,
      tile_size: tileSize,
      output_format: 'png',
    },
    family: 'esrgan',
    warnings: [],
  };
}

function normalizeModelConfig(payload) {
  const nested = assertObject(payload.modelConfig, 'modelConfig');
  const merged = { ...nested, ...payload };
  delete merged.modelConfig;
  rejectUnknown(merged, LOAD_FIELDS, 'model load');
  const modelSrc = optionalString(merged.modelSrc, 'modelSrc');
  if (!modelSrc) throw new HttpError(422, 'modelSrc is required');
  const modelType = enumValue(merged.modelType, 'modelType', ['sdcpp-generation', 'diffusion'], 'sdcpp-generation');
  const device = enumValue(merged.device, 'device', ['gpu', 'cpu'], config.device);
  const threads = intValue(merged.threads, 'threads', { minimum: 1, maximum: 128 });
  const mode = enumValue(merged.mode, 'mode', ['video', 'upscale'], undefined);
  const familyHint = optionalString(merged.family, 'family');
  const family = familyHint || familyForModel(modelSrc) || null;
  const known = { ...VIDEO_FAMILIES, ...IMAGE_FAMILIES };
  if (family && !known[family]) throw new HttpError(422, `Unknown model family: ${family}`);
  const modelConfig = { device, mode };
  if (threads !== undefined) modelConfig.threads = threads;
  const sourceFields = [
    't5XxlModelSrc', 'vaeModelSrc', 'clipVisionModelSrc', 'llmModelSrc', 'audioVaeModelSrc',
    'embeddingsConnectorsModelSrc', 'projectionModelSrc', 'uncondModelSrc', 'highNoiseDiffusionModelSrc',
    'clipLModelSrc', 'clipGModelSrc',
  ];
  for (const name of sourceFields) {
    const value = optionalString(merged[name], name, 4096);
    if (value !== undefined) modelConfig[name] = value;
  }
  const booleans = ['diffusion_fa', 'offload_to_cpu', 'vae_tiling', 'stream_layers', 'flash_attn'];
  for (const name of booleans) {
    if (merged[name] !== undefined) modelConfig[name] = booleanValue(merged[name], name, false);
  }
  for (const name of ['params_backend', 'backend', 'prediction', 'lora_apply_mode']) {
    const value = optionalString(merged[name], name, 256);
    if (value !== undefined) modelConfig[name] = value;
  }
  if (hasValue(merged.max_vram)) {
    if (typeof merged.max_vram === 'number' && !Number.isFinite(merged.max_vram)) throw new HttpError(422, 'max_vram must be a number or string');
    modelConfig.max_vram = merged.max_vram;
  }
  if (merged.upscaler !== undefined && merged.upscaler !== null) {
    const upscaler = assertObject(merged.upscaler, 'upscaler');
    if (upscaler.type && upscaler.type !== 'esrgan') throw new HttpError(422, 'upscaler.type must be "esrgan"');
    if (!upscaler.model_src && !upscaler.modelSrc) throw new HttpError(422, 'upscaler.model_src is required');
    const tileSize = intValue(upscaler.tile_size, 'upscaler.tile_size', { minimum: 16, maximum: 1024 });
    modelConfig.upscaler = {
      type: 'esrgan',
      model_src: upscaler.model_src || upscaler.modelSrc,
      ...(tileSize !== undefined ? { tile_size: tileSize } : {}),
    };
  }
  for (const key of Object.keys(modelConfig)) {
    if (modelConfig[key] === undefined) delete modelConfig[key];
  }
  return {
    modelSrc,
    modelType,
    modelConfig,
    family,
    mock: merged.mock === undefined ? config.mock : booleanValue(merged.mock, 'mock', config.mock),
  };
}

module.exports = {
  validateVideo,
  validateImage,
  validateUpscale,
  normalizeModelConfig,
  assertObject,
  intValue,
  numberValue,
  booleanValue,
  optionalString,
};
