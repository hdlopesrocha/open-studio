'use strict';

const express = require('express');

const config = require('./config');
const catalog = require('./catalog');
const files = require('./files');
const jobs = require('./jobs');
const memory = require('./memory');
const mock = require('./mock');
const sdk = require('./sdk');
const { HttpError, JobCancelled } = require('./errors');
const { normalizeModelConfig, validateVideo, validateImage, validateUpscale } = require('./validation');

const app = express();
const startedAt = Date.now();

app.disable('x-powered-by');
app.use(express.json({ limit: '16mb' }));

function requestToken(req) {
  const header = req.get('x-internal-token') || '';
  return header === config.internalToken;
}

function requireToken(req, res, next) {
  if (!config.requireInternalToken || requestToken(req)) return next();
  return res.status(403).json({ detail: 'Invalid internal token' });
}

app.use('/api/qvac', requireToken);

app.get('/health', async (req, res) => {
  let ffmpegReady = false;
  try {
    ffmpegReady = await mock.ffmpegAvailable();
  } catch (error) {
    ffmpegReady = false;
  }
  res.json({
    service: 'qvac',
    status: config.mock ? 'mock' : 'ok',
    version: config.version,
    mode: config.mock ? 'mock' : 'sdk',
    mock: config.mock,
    device: config.device,
    ffmpeg: ffmpegReady,
    uptime_seconds: Math.round((Date.now() - startedAt) / 100) / 10,
  });
});

app.get('/', (req, res) => {
  res.json({
    name: 'Open Studio QVAC',
    service: 'qvac',
    version: config.version,
    docs: null,
    health: '/health',
    api: '/api/qvac',
  });
});

app.get('/api/qvac/catalog', async (req, res, next) => {
  try {
    const [sdkInfo, mem] = await Promise.all([sdk.sdkStatus(), memory.memoryStatus()]);
    res.json(catalog.buildCatalog({ sdkInfo, memory: mem }));
  } catch (error) {
    next(error);
  }
});

app.get('/api/qvac/status', async (req, res, next) => {
  try {
    const [sdkInfo, mem] = await Promise.all([sdk.sdkStatus(), memory.memoryStatus()]);
    res.json({
      service: 'qvac',
      version: config.version,
      mode: config.mock ? 'mock' : 'sdk',
      mock: config.mock,
      device: config.device,
      sdk: sdkInfo,
      sdk_declared_version: config.sdkPackageVersion,
      loaded_models: sdk.listLoaded(),
      active_jobs: jobs.activeJobs(),
      memory: mem,
      requirements: config.requirements,
      ffmpeg: {
        available: await mock.ffmpegAvailable(),
        version: await mock.ffmpegVersion(),
      },
      uptime_seconds: Math.round((Date.now() - startedAt) / 100) / 10,
    });
  } catch (error) {
    next(error);
  }
});

app.post('/api/qvac/models/load', async (req, res, next) => {
  try {
    const normalized = normalizeModelConfig(req.body || {});
    const entry = await sdk.loadModel(normalized, {
      report: async () => {},
    });
    res.json({ model: sdk.publicModel(entry) });
  } catch (error) {
    next(error);
  }
});

app.post('/api/qvac/models/unload', async (req, res, next) => {
  try {
    const modelId = req.body && (req.body.model_id || req.body.modelId);
    const clearStorage = Boolean(req.body && req.body.clear_storage);
    if (!modelId) {
      const items = await sdk.unloadAll();
      return res.json({ items, total: items.length, unloaded_all: true });
    }
    const item = await sdk.unloadModel(modelId, { clearStorage });
    return res.json({ model: item, unloaded: true });
  } catch (error) {
    return next(error);
  }
});

app.get('/api/qvac/models/loaded', (req, res) => {
  const items = sdk.listLoaded();
  res.json({ items, total: items.length });
});

function jobParams(validated) {
  const params = { ...validated.params };
  if (validated.family) params.family = validated.family;
  return params;
}

app.post('/api/qvac/video', async (req, res, next) => {
  try {
    const validated = validateVideo(req.body || {});
    const job = await jobs.submitJob('video', jobParams(validated), req.body && req.body.title);
    res.json(job);
  } catch (error) {
    next(error);
  }
});

app.post('/api/qvac/image', async (req, res, next) => {
  try {
    const validated = validateImage(req.body || {});
    const job = await jobs.submitJob('image', jobParams(validated), req.body && req.body.title);
    res.json(job);
  } catch (error) {
    next(error);
  }
});

app.post('/api/qvac/upscale', async (req, res, next) => {
  try {
    const validated = validateUpscale(req.body || {});
    const job = await jobs.submitJob('upscale', jobParams(validated), req.body && req.body.title);
    res.json(job);
  } catch (error) {
    next(error);
  }
});

app.post('/internal/jobs/run', requireToken, async (req, res) => {
  const body = req.body || {};
  const action = body.action;
  const jobId = body.job_id;
  try {
    const result = await jobs.runJob({ job_id: jobId, action, params: body.params || {} });
    res.json({ result });
  } catch (error) {
    if (error instanceof JobCancelled) {
      return res.json({ cancelled: true, result: { message: 'Cancelled' } });
    }
    if (error instanceof HttpError) {
      return res.status(error.status).json({ detail: error.message, ...(error.details ? { details: error.details } : {}) });
    }
    console.error('[qvac] job failed', error);
    return res.status(500).json({ detail: error.message || String(error) });
  }
});

app.get('/internal/jobs/:jobId/cancel-state', requireToken, (req, res) => {
  try {
    res.json(jobs.cancelState(req.params.jobId));
  } catch (error) {
    if (error instanceof HttpError) return res.status(error.status).json({ detail: error.message });
    return res.status(500).json({ detail: error.message });
  }
});

app.post('/internal/jobs/:jobId/cancel', requireToken, async (req, res) => {
  try {
    await jobs.requestCancel(req.params.jobId);
    res.json({ ok: true, job_id: req.params.jobId });
  } catch (error) {
    if (error instanceof HttpError) return res.status(error.status).json({ detail: error.message });
    return res.status(500).json({ detail: error.message });
  }
});

app.get('/internal/qvac/active', requireToken, (req, res) => {
  res.json({ jobs: jobs.activeJobs(), total: jobs.activeJobs().length });
});

app.use((req, res) => {
  res.status(404).json({ detail: 'Not found' });
});

app.use((error, req, res, next) => {
  if (res.headersSent) return next(error);
  if (error instanceof HttpError) {
    return res.status(error.status).json({ detail: error.message, ...(error.details ? { details: error.details } : {}) });
  }
  if (error instanceof SyntaxError && error.status === 400) {
    return res.status(400).json({ detail: 'Invalid JSON body' });
  }
  console.error('[qvac] unhandled error', error);
  return res.status(500).json({ detail: error.message || 'Internal error' });
});

function start(port = config.port) {
  const server = app.listen(port, config.host, () => {
    console.log(`[qvac] listening on ${config.host}:${port} mode=${config.mock ? 'mock' : 'sdk'} device=${config.device}`);
  });
  // Video generation can take far longer than Node's default 5 minute request
  // timeout. The job hub enforces its own per-job timeout.
  server.requestTimeout = 0;
  server.timeout = 0;
  server.headersTimeout = 60_000;
  return server;
}

function shutdown(signal) {
  console.log(`[qvac] ${signal} received, unloading models`);
  sdk
    .unloadAll()
    .catch(() => {})
    .finally(() => process.exit(0));
}

if (require.main === module) {
  start();
  process.on('SIGTERM', () => shutdown('SIGTERM'));
  process.on('SIGINT', () => shutdown('SIGINT'));
}

module.exports = { app, start };
