'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const config = require('./config');
const files = require('./files');
const mock = require('./mock');
const { HttpError, JobCancelled } = require('./errors');
const { normalizeModelConfig } = require('./validation');
const { VIDEO_FAMILIES, IMAGE_FAMILIES, KNOWN_MODELS } = require('./catalog');

const LOADED = new Map();
let sdkPromise = null;
let sdkStatusCache = null;

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function getSdk() {
  if (config.mock) throw new HttpError(503, 'QVAC_MOCK=1: native SDK calls are disabled');
  if (!sdkPromise) {
    sdkPromise = import('@qvac/sdk').catch((error) => {
      sdkPromise = null;
      throw new HttpError(503, `QVAC SDK failed to load: ${error.message}. Set QVAC_MOCK=1 to use the demo renderer.`);
    });
  }
  return sdkPromise;
}

function sdkConstants(sdk) {
  return Object.keys(sdk)
    .filter((key) => /^[A-Z][A-Z0-9_]{2,}$/.test(key))
    .filter((key) => {
      const value = sdk[key];
      // Plugin constants are strings. Model constants are descriptor
      // objects such as SD_V2_1_1B_Q8_0, which the SDK expects to receive
      // directly as modelSrc during loadModel().
      return typeof value === 'string' || Boolean(value && typeof value === 'object' && value.src);
    })
    .sort();
}

function knownModelSizes(sdk) {
  const sizes = {};
  for (const model of KNOWN_MODELS) {
    const descriptor = sdk[model.name];
    const size = Number(descriptor && typeof descriptor === 'object' ? descriptor.expectedSize : 0);
    if (size > 0) sizes[model.name] = size;
  }
  return sizes;
}

async function sdkStatus(force = false) {
  if (config.mock) {
    return {
      available: false,
      mock: true,
      version: config.sdkPackageVersion,
      declared_version: config.sdkPackageVersion,
      constants: [],
      model_sizes: {},
      error: 'mock mode',
    };
  }
  if (sdkStatusCache && !force) return sdkStatusCache;
  try {
    const sdk = await getSdk();
    sdkStatusCache = {
      available: typeof sdk.loadModel === 'function',
      mock: false,
      version: (sdk.version || sdk.VERSION || null) || config.sdkPackageVersion,
      declared_version: config.sdkPackageVersion,
      constants: sdkConstants(sdk),
      model_sizes: knownModelSizes(sdk),
      error: typeof sdk.loadModel === 'function' ? null : 'loadModel export is missing',
    };
  } catch (error) {
    sdkStatusCache = {
      available: false,
      mock: false,
      version: config.sdkPackageVersion,
      declared_version: config.sdkPackageVersion,
      constants: [],
      model_sizes: {},
      error: error.message || String(error),
    };
  }
  return sdkStatusCache;
}

function knownConstant(name) {
  try {
    const catalog = require('./catalog');
    return catalog.KNOWN_MODELS.some((model) => model.name === name);
  } catch (error) {
    return false;
  }
}

async function resolveConstant(value, label = 'model source') {
  const text = String(value || '').trim();
  if (!text) throw new HttpError(422, `${label} is required`);
  if (files.isUrl(text) || path.isAbsolute(text)) return text;
  if (!files.isConstantName(text)) return files.modelSource(text, label);
  const status = await sdkStatus();
  if (status.available && status.constants.includes(text)) {
    const sdk = await getSdk();
    return sdk[text];
  }
  if (config.mock && knownConstant(text)) return `mock://${text}`;
  if (status.available) {
    throw new HttpError(422, `${label} constant ${text} is not exported by the installed @qvac/sdk. Pass a local path or URL instead.`);
  }
  if (knownConstant(text)) {
    throw new HttpError(503, `QVAC SDK is unavailable (${status.error || 'not installed'}); cannot resolve ${text}. Set QVAC_MOCK=1 for mock generation.`);
  }
  throw new HttpError(422, `Unknown ${label} constant: ${text}`);
}

function publicModel(entry) {
  return {
    model_id: entry.modelId,
    model: entry.modelName || null,
    family: entry.family || null,
    kind: entry.kind || null,
    mock: entry.mock,
    loaded_at: entry.loadedAt,
    config: entry.publicConfig || null,
  };
}

function listLoaded() {
  return [...LOADED.values()].map(publicModel);
}

function getLoaded(modelId) {
  const entry = LOADED.get(String(modelId || ''));
  if (!entry) throw new HttpError(404, `Model not loaded: ${modelId}`);
  return entry;
}

function removeLoaded(modelId) {
  return LOADED.delete(String(modelId || ''));
}

function clearLoaded() {
  LOADED.clear();
}

function kindForFamily(family) {
  if (family && VIDEO_FAMILIES[family]) return 'video';
  if (family && IMAGE_FAMILIES[family]) {
    return IMAGE_FAMILIES[family].kind === 'upscale' ? 'upscale' : 'image';
  }
  return null;
}

async function resolveModelSources(normalized) {
  const resolved = { ...normalized.modelConfig };
  if (resolved.upscaler && resolved.upscaler.model_src) {
    resolved.upscaler = { ...resolved.upscaler, model_src: await resolveConstant(resolved.upscaler.model_src, 'upscaler.model_src') };
  }
  const sourceFields = [
    't5XxlModelSrc', 'vaeModelSrc', 'clipVisionModelSrc', 'llmModelSrc', 'audioVaeModelSrc',
    'embeddingsConnectorsModelSrc', 'projectionModelSrc', 'uncondModelSrc', 'highNoiseDiffusionModelSrc',
    'clipLModelSrc', 'clipGModelSrc',
  ];
  for (const name of sourceFields) {
    if (resolved[name]) resolved[name] = await resolveConstant(resolved[name], name);
  }
  const modelSrc = await resolveConstant(normalized.modelSrc, 'modelSrc');
  return { modelSrc, modelConfig: resolved };
}

async function loadModel(normalized, { report } = {}) {
  const family = normalized.family || null;
  const kind = kindForFamily(family);
  if (kind === 'video' && normalized.modelConfig && !normalized.modelConfig.mode) normalized.modelConfig.mode = 'video';
  if (kind === 'upscale' && normalized.modelConfig && !normalized.modelConfig.mode) normalized.modelConfig.mode = 'upscale';
  const useMock = normalized.mock || config.mock;
  const resolved = await resolveModelSources(normalized);
  if (useMock) {
    const modelId = `mock-${crypto.randomUUID()}`;
    const entry = {
      modelId,
      family,
      kind,
      modelName: normalized.modelSrc,
      mock: true,
      loadedAt: new Date().toISOString(),
      publicConfig: { modelType: normalized.modelType, modelConfig: normalized.modelConfig },
    };
    LOADED.set(modelId, entry);
    if (report) await report(50, 'Model (mock)', `Mock-loaded ${normalized.modelSrc}`);
    return entry;
  }
  const sdk = await getSdk();
  const { modelSrc, modelConfig } = resolved;
  if (report) await report(5, 'Loading model', `Loading ${normalized.modelSrc}`);
  const result = await sdk.loadModel({
    modelSrc,
    modelType: normalized.modelType,
    modelConfig,
    onProgress: (progress) => {
      if (report) {
        const percentage = Number(progress && progress.percentage);
        if (Number.isFinite(percentage)) {
          report(5 + percentage * 0.9, 'Downloading model', `${percentage.toFixed(0)}%`).catch(() => {});
        }
      }
    },
  });
  const modelId = typeof result === 'string' ? result : (result && (result.modelId || result.id)) || null;
  if (!modelId) throw new HttpError(500, 'QVAC loadModel did not return a model ID');
  const entry = {
    modelId,
    family,
    kind,
    modelName: normalized.modelSrc,
    mock: false,
    loadedAt: new Date().toISOString(),
    publicConfig: { modelType: normalized.modelType, modelConfig },
  };
  LOADED.set(modelId, entry);
  if (report) await report(100, 'Model loaded', `Loaded ${normalized.modelSrc}`);
  return entry;
}

async function unloadModel(modelId, { clearStorage = false } = {}) {
  const entry = getLoaded(modelId);
  if (!entry.mock) {
    const sdk = await getSdk();
    if (typeof sdk.unloadModel === 'function') {
      await sdk.unloadModel({ modelId: entry.modelId, clearStorage: Boolean(clearStorage) });
    }
  }
  LOADED.delete(entry.modelId);
  return publicModel(entry);
}

async function unloadAll() {
  const results = [];
  for (const entry of [...LOADED.values()]) {
    try {
      results.push(await unloadModel(entry.modelId));
    } catch (error) {
      // best effort shutdown
    }
  }
  return results;
}

async function cancelSdkRequest(requestId) {
  if (!requestId) return false;
  try {
    const sdk = await getSdk();
    if (typeof sdk.cancel === 'function') {
      await sdk.cancel(requestId);
      return true;
    }
  } catch (error) {
    return false;
  }
  return false;
}

async function awaitCancelable(promise, ctx) {
  let finished = false;
  const wrapped = Promise.resolve(promise).then(
    (value) => {
      finished = true;
      return { value };
    },
    (error) => {
      finished = true;
      throw error;
    },
  );
  while (!finished) {
    const winner = await Promise.race([wrapped, delay(500).then(() => ({ tick: true }))]);
    if (winner && winner.tick) {
      await ctx.checkCancel();
    } else if (winner && Object.prototype.hasOwnProperty.call(winner, 'value')) {
      return winner.value;
    }
  }
  return wrapped;
}

function asBuffer(value) {
  if (Buffer.isBuffer(value)) return value;
  if (value instanceof Uint8Array) return Buffer.from(value);
  if (value instanceof ArrayBuffer) return Buffer.from(new Uint8Array(value));
  if (value && value.buffer instanceof ArrayBuffer) return Buffer.from(new Uint8Array(value.buffer));
  throw new HttpError(500, 'QVAC SDK returned an unsupported output buffer');
}

function normalizeBuffers(value) {
  const list = Array.isArray(value) ? value : [value];
  return list.filter((item) => item !== undefined && item !== null).map(asBuffer);
}

function serializeStats(value) {
  if (value === undefined || value === null) return null;
  try {
    return JSON.parse(
      JSON.stringify(value, (key, item) => {
        if (typeof item === 'bigint') return item.toString();
        if (item instanceof Uint8Array) return { type: 'bytes', length: item.length };
        return item;
      }),
    );
  } catch (error) {
    return { serialization_error: error.message };
  }
}

function modelForGeneration(params, kind) {
  let entry;
  if (params.model_id) {
    entry = getLoaded(params.model_id);
  } else {
    throw new HttpError(422, `model_id is required for ${kind} jobs unless the job loads a model inline`);
  }
  if (entry.kind && entry.kind !== kind) {
    throw new HttpError(422, `Model ${entry.modelId} is a ${entry.kind} model, not ${kind}`);
  }
  return entry;
}

async function ensureModel(params, ctx, kind) {
  if (params.model_id) return modelForGeneration(params, kind);
  const loadPayload = { ...(params.model_config || {}) };
  if (!loadPayload.modelSrc && params.model) loadPayload.modelSrc = params.model;
  if (params.family) loadPayload.family = params.family;
  if (!loadPayload.modelSrc) throw new HttpError(422, 'Provide model_id or a model/model_config.modelSrc');
  const requested = String(loadPayload.modelSrc);
  for (const entry of LOADED.values()) {
    if (entry.kind && entry.kind !== kind) continue;
    if (String(entry.modelName) === requested) return entry;
  }
  if (kind === 'image' && params.init_image) {
    const family = loadPayload.family || (params.model && require('./catalog').familyForModel(params.model));
    if (family === 'flux2_klein') loadPayload.prediction = loadPayload.prediction || 'flux2_flow';
  }
  const normalized = normalizeModelConfig(loadPayload);
  if (kind === 'upscale' && normalized.family !== 'esrgan' && !params.model_id) {
    normalized.family = 'esrgan';
  }
  return loadModel(normalized, {
    report: async (progress, stage, message) => {
      if (ctx.report) await ctx.report(progress, stage, message);
    },
  });
}

async function simulateProgress(ctx, { from = 5, to = 85, steps = 10, stage = 'Generating' } = {}) {
  for (let index = 0; index < steps; index += 1) {
    await delay(60);
    await ctx.checkCancel();
    const progress = from + ((to - from) * (index + 1)) / steps;
    if (ctx.report) await ctx.report(progress, stage, `Step ${index + 1}/${steps}`);
  }
}

async function generateVideo(params, ctx) {
  const warnings = [];
  const entry = await ensureModel(params, ctx, 'video');
  if (ctx.report) await ctx.report(3, 'Preparing', 'Resolving media inputs');
  let initImage;
  if (params.mode === 'img2vid') {
    const inputPath = files.inputFile(params.init_image, 'init_image');
    initImage = files.readBufferSync(inputPath);
  }
  const referenceImages = files.imageList(params.reference_images, 'reference_images').map((filePath) => files.readBufferSync(filePath));
  const controlFrames = files.imageList(params.control_frames, 'control_frames').map((filePath) => files.readBufferSync(filePath));
  let lora;
  if (params.lora) lora = files.loraSource(params.lora);
  const generation = {
    modelId: entry.modelId,
    mode: params.mode,
    prompt: params.prompt,
    negative_prompt: params.negative_prompt,
    init_image: initImage,
    control_frames: controlFrames.length ? controlFrames : undefined,
    width: params.width,
    height: params.height,
    video_frames: params.video_frames,
    fps: params.fps,
    steps: params.steps,
    cfg_scale: params.cfg_scale,
    flow_shift: params.flow_shift,
    seed: params.seed,
    scheduler: params.scheduler,
    strength: params.strength,
    reference_images: referenceImages.length ? referenceImages : undefined,
    lora,
    lora_strength: params.lora_strength,
    stg_scale: params.stg_scale,
    stg_block: params.stg_block,
    reference_attention_strength: params.reference_attention_strength,
    reference_downscale_factor: params.reference_downscale_factor,
    temporal_tiling: params.temporal_tiling,
    vae_tile_size: params.vae_tile_size,
    high_noise_steps: params.high_noise_steps,
    high_noise_sample_method: params.high_noise_sample_method,
    high_noise_scheduler: params.high_noise_scheduler,
    high_noise_cfg_scale: params.high_noise_cfg_scale,
    high_noise_flow_shift: params.high_noise_flow_shift,
    moe_boundary: params.moe_boundary,
    vae_tiling: params.vae_tiling,
  };
  for (const key of Object.keys(generation)) {
    if (generation[key] === undefined || generation[key] === null) delete generation[key];
  }

  const directory = await files.outputDir(ctx.jobId);
  const outputs = [];
  let stats = null;
  const useMock = config.mock || entry.mock;
  if (useMock) {
    await simulateProgress(ctx, { from: 5, to: 70, steps: 8, stage: 'Generating (mock)' });
    if (params.output_format !== 'mp4') warnings.push('Mock video generation writes a playable MP4; AVI buffers are only produced by the real QVAC SDK.');
    const fps = Number(params.fps) || 16;
    const frames = Number(params.video_frames) || 33;
    const duration = Math.min(3, Math.max(1, frames / fps));
    const outputPath = path.join(directory, 'mock_video_0.mp4');
    const result = await mock.createMockVideo({
      outputPath,
      width: params.width,
      height: params.height,
      fps,
      duration,
      prompt: params.prompt,
      check: ctx.checkCancel,
    });
    if (result.warning) warnings.push(result.warning);
    outputs.push(outputPath);
    stats = { mock: true, requested_frames: frames, requested_fps: fps };
    if (ctx.report) await ctx.report(92, 'Finalizing', 'Mock video rendered');
  } else {
    const sdk = await getSdk();
    const result = sdk.video(generation);
    if (result.requestId && ctx.onRequestId) await ctx.onRequestId(result.requestId);
    try {
      if (result.progressStream) {
        for await (const tick of result.progressStream) {
          await ctx.checkCancel();
          const total = Number(tick.totalSteps) || Number(params.steps) || 1;
          const step = Number(tick.step) || 0;
          if (ctx.report) await ctx.report(5 + Math.min(80, (step / Math.max(1, total)) * 80), 'Generating', `Step ${step}/${total}`);
        }
      }
      const buffers = normalizeBuffers(await awaitCancelable(result.outputs, ctx));
      stats = result.stats !== undefined ? serializeStats(await awaitCancelable(result.stats, ctx)) : null;
      for (let index = 0; index < buffers.length; index += 1) {
        await ctx.checkCancel();
        const aviPath = path.join(directory, `video_${index}.avi`);
        await files.saveBuffer(aviPath, buffers[index]);
        outputs.push(aviPath);
        if (params.output_format === 'both' || params.output_format === 'mp4') {
          const mp4Path = path.join(directory, `video_${index}.mp4`);
          const transcoded = await mock.transcodeToMp4(aviPath, mp4Path, {
            check: ctx.checkCancel,
            onProgress: (seconds) => {
              if (ctx.report && params.video_frames && params.fps) {
                const duration = Number(params.video_frames) / Number(params.fps);
                const progress = 85 + Math.min(12, (seconds / Math.max(0.01, duration)) * 12);
                ctx.report(progress, 'Transcoding', `${seconds.toFixed(1)}s`).catch(() => {});
              }
            },
          });
          if (transcoded.ok) outputs.push(mp4Path);
          if (transcoded.warning) warnings.push(transcoded.warning);
        }
      }
      if (!outputs.length) throw new HttpError(500, 'QVAC video generation returned no buffers');
    } catch (error) {
      if (error instanceof JobCancelled) {
        await cancelSdkRequest(result.requestId);
      }
      throw error;
    }
  }

  const descriptors = files.describeFiles(outputs);
  const primary = descriptors.find((item) => item.kind === 'video') || descriptors[0];
  return {
    message: useMock ? 'Mock video generated (QVAC_MOCK=1)' : `Generated ${descriptors.length} video output(s)`,
    files: descriptors,
    data: {
      operation: 'video',
      mock: useMock,
      model_id: entry.modelId,
      model: entry.modelName,
      family: entry.family,
      mode: params.mode,
      prompt: params.prompt,
      width: params.width,
      height: params.height,
      video_frames: params.video_frames,
      fps: params.fps,
      seed: params.seed,
      duration_seconds: params.video_frames && params.fps ? Math.round((Number(params.video_frames) / Number(params.fps)) * 1000) / 1000 : null,
      output_format: params.output_format,
      primary_file: primary ? primary.path : null,
      paths: descriptors.map((item) => item.path),
      stats,
      warnings,
    },
  };
}

async function generateImage(params, ctx) {
  const warnings = [];
  const entry = await ensureModel(params, ctx, 'image');
  let initImage;
  if (params.init_image) initImage = files.readBufferSync(files.inputFile(params.init_image, 'init_image'));
  const initImages = files.imageList(params.init_images, 'init_images').map((filePath) => files.readBufferSync(filePath));
  let lora;
  if (params.lora) lora = files.loraSource(params.lora);
  const generation = {
    modelId: entry.modelId,
    prompt: params.prompt,
    negative_prompt: params.negative_prompt,
    width: params.width,
    height: params.height,
    steps: params.steps,
    guidance: params.guidance,
    cfg_scale: params.cfg_scale,
    seed: params.seed,
    batch_count: params.batch_count,
    sampling_method: params.sampling_method,
    scheduler: params.scheduler,
    init_image: initImage,
    init_images: initImages.length ? initImages : undefined,
    strength: params.strength,
    lora,
    lora_strength: params.lora_strength,
    upscale: params.upscale,
  };
  for (const key of Object.keys(generation)) {
    if (generation[key] === undefined || generation[key] === null) delete generation[key];
  }

  const directory = await files.outputDir(ctx.jobId);
  const outputs = [];
  let stats = null;
  const useMock = config.mock || entry.mock;
  if (useMock) {
    await simulateProgress(ctx, { from: 5, to: 60, steps: 6, stage: 'Generating image (mock)' });
    const count = Math.max(1, Math.min(config.limits.maxImageBatch, Number(params.batch_count) || 1));
    for (let index = 0; index < count; index += 1) {
      const outputPath = path.join(directory, `mock_image_${index}.png`);
      const result = await mock.createMockImage({
        outputPath,
        width: params.width,
        height: params.height,
        check: ctx.checkCancel,
      });
      if (result.warning) warnings.push(result.warning);
      outputs.push(outputPath);
    }
    if (params.upscale && params.upscale !== false) {
      for (let index = 0; index < outputs.length; index += 1) {
        const upscaled = path.join(directory, `mock_upscaled_${index}.png`);
        const result = await mock.mockUpscale({
          inputPath: outputs[index],
          outputPath: upscaled,
          repeats: typeof params.upscale === 'object' ? params.upscale.repeats || 1 : 1,
          check: ctx.checkCancel,
        });
        if (result.warning) warnings.push(result.warning);
        outputs[index] = upscaled;
      }
    }
    stats = { mock: true };
    if (ctx.report) await ctx.report(92, 'Finalizing', 'Mock images rendered');
  } else {
    const sdk = await getSdk();
    const result = sdk.diffusion(generation);
    if (result.requestId && ctx.onRequestId) await ctx.onRequestId(result.requestId);
    try {
      if (result.progressStream) {
        for await (const tick of result.progressStream) {
          await ctx.checkCancel();
          const total = Number(tick.totalSteps) || Number(params.steps) || 1;
          const step = Number(tick.step) || 0;
          if (ctx.report) await ctx.report(5 + Math.min(85, (step / Math.max(1, total)) * 85), 'Generating', `Step ${step}/${total}`);
        }
      }
      const buffers = normalizeBuffers(await awaitCancelable(result.outputs, ctx));
      stats = result.stats !== undefined ? serializeStats(await awaitCancelable(result.stats, ctx)) : null;
      for (let index = 0; index < buffers.length; index += 1) {
        await ctx.checkCancel();
        const outputPath = path.join(directory, `image_${index}.png`);
        await files.saveBuffer(outputPath, buffers[index]);
        outputs.push(outputPath);
      }
      if (!outputs.length) throw new HttpError(500, 'QVAC image generation returned no buffers');
    } catch (error) {
      if (error instanceof JobCancelled) await cancelSdkRequest(result.requestId);
      throw error;
    }
  }

  const descriptors = files.describeFiles(outputs);
  return {
    message: useMock ? 'Mock image generated (QVAC_MOCK=1)' : `Generated ${descriptors.length} image(s)`,
    files: descriptors,
    data: {
      operation: 'image',
      mock: useMock,
      model_id: entry.modelId,
      model: entry.modelName,
      family: entry.family,
      prompt: params.prompt,
      width: params.width,
      height: params.height,
      batch_count: params.batch_count,
      seed: params.seed,
      upscale: params.upscale || false,
      paths: descriptors.map((item) => item.path),
      stats,
      warnings,
    },
  };
}

async function generateUpscale(params, ctx) {
  const warnings = [];
  const inputPath = files.inputFile(params.image_path, 'image_path');
  let entry;
  if (params.model_id) {
    entry = getLoaded(params.model_id);
  } else {
    const normalized = normalizeModelConfig({
      modelSrc: params.model || 'REALESRGAN_X4PLUS',
      modelType: 'sdcpp-generation',
      family: 'esrgan',
      mode: 'upscale',
      upscaler: { type: 'esrgan', model_src: params.model || 'REALESRGAN_X4PLUS', tile_size: params.tile_size || 128 },
    });
    entry = await loadModel(normalized, { report: async (progress, stage, message) => ctx.report && ctx.report(progress, stage, message) });
  }
  const directory = await files.outputDir(ctx.jobId);
  const outputs = [];
  const useMock = config.mock || entry.mock;
  if (useMock) {
    await simulateProgress(ctx, { from: 5, to: 80, steps: 5, stage: 'Upscaling (mock)' });
    const outputPath = path.join(directory, 'mock_upscaled_0.png');
    const result = await mock.mockUpscale({ inputPath, outputPath, repeats: params.repeats, check: ctx.checkCancel });
    if (result.warning) warnings.push(result.warning);
    outputs.push(outputPath);
  } else {
    const sdk = await getSdk();
    const result = sdk.upscale({ modelId: entry.modelId, image: files.readBufferSync(inputPath), repeats: params.repeats });
    if (result.requestId && ctx.onRequestId) await ctx.onRequestId(result.requestId);
    try {
      if (result.progressStream) {
        for await (const tick of result.progressStream) {
          await ctx.checkCancel();
          const total = Number(tick.totalSteps) || 1;
          const step = Number(tick.step) || 0;
          if (ctx.report) await ctx.report(5 + Math.min(85, (step / total) * 85), 'Upscaling', `Step ${step}/${total}`);
        }
      }
      const buffers = normalizeBuffers(await awaitCancelable(result.outputs, ctx));
      for (let index = 0; index < buffers.length; index += 1) {
        await ctx.checkCancel();
        const outputPath = path.join(directory, `upscaled_${index}.png`);
        await files.saveBuffer(outputPath, buffers[index]);
        outputs.push(outputPath);
      }
      if (!outputs.length) throw new HttpError(500, 'QVAC upscale returned no buffers');
    } catch (error) {
      if (error instanceof JobCancelled) await cancelSdkRequest(result.requestId);
      throw error;
    }
  }
  const descriptors = files.describeFiles(outputs);
  return {
    message: useMock ? 'Mock upscale complete (QVAC_MOCK=1)' : `Upscaled image ${params.repeats}x`,
    files: descriptors,
    data: {
      operation: 'upscale',
      mock: useMock,
      model_id: entry.modelId,
      repeats: params.repeats,
      input: files.fileDescriptor(inputPath),
      paths: descriptors.map((item) => item.path),
      warnings,
    },
  };
}

module.exports = {
  getSdk,
  sdkStatus,
  sdkConstants,
  resolveConstant,
  loadModel,
  unloadModel,
  unloadAll,
  listLoaded,
  getLoaded,
  removeLoaded,
  clearLoaded,
  cancelSdkRequest,
  generateVideo,
  generateImage,
  generateUpscale,
  publicModel,
};
