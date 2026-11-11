'use strict';

const path = require('path');
const fs = require('fs');

const pkg = require('../package.json');

function env(name, fallback = '') {
  const value = process.env[name];
  return value === undefined || value === '' ? fallback : value;
}

function envBool(name, fallback = false) {
  const value = process.env[name];
  if (value === undefined || value === '') return fallback;
  return ['1', 'true', 'yes', 'on', 'y'].includes(String(value).trim().toLowerCase());
}

function envInt(name, fallback) {
  const parsed = Number.parseInt(process.env[name] || '', 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

const DATA_ROOT = path.resolve(env('DATA_ROOT', '/data'));
const FILES_ROOT = path.resolve(env('FILES_ROOT', path.join(DATA_ROOT, 'files')));
const MODELS_ROOT = path.resolve(env('MODELS_ROOT', path.join(DATA_ROOT, 'models')));
const STATE_ROOT = path.resolve(env('STATE_ROOT', path.join(DATA_ROOT, 'state')));
const CACHE_ROOT = path.resolve(env('CACHE_ROOT', path.join(DATA_ROOT, 'cache')));

const device = String(env('QVAC_DEVICE', 'gpu')).toLowerCase();
const QVAC_DEVICE = ['gpu', 'cpu'].includes(device) ? device : 'gpu';
const QVAC_MOCK = envBool('QVAC_MOCK', false);
const MAX_VRAM = env('QVAC_MAX_VRAM', '');
const FFMPEG = env('FFMPEG', 'ffmpeg');

const config = {
  service: 'qvac',
  version: pkg.version,
  port: envInt('PORT', 8000),
  host: env('HOST', '0.0.0.0'),
  filesRoot: FILES_ROOT,
  modelsRoot: MODELS_ROOT,
  dataRoot: DATA_ROOT,
  stateRoot: STATE_ROOT,
  cacheRoot: CACHE_ROOT,
  jobhubUrl: env('JOBHUB_URL', 'http://jobhub:8000').replace(/\/+$/, ''),
  filesServiceUrl: env('FILES_SERVICE_URL', 'http://files:8000').replace(/\/+$/, ''),
  internalToken: env('INTERNAL_TOKEN', 'change-me-internal'),
  requireInternalToken: envBool('REQUIRE_INTERNAL_TOKEN', true),
  device: QVAC_DEVICE,
  mock: QVAC_MOCK,
  maxVram: MAX_VRAM,
  ffmpeg: FFMPEG,
  sdkPackageVersion: (pkg.dependencies && pkg.dependencies['@qvac/sdk']) || 'unknown',
  requirements: {
    videoMemoryGb: 16,
    unifiedMemoryGb: 20,
    note: 'QVAC video generation requires at least 16 GB of VRAM or 20 GB of unified memory.',
  },
  limits: {
    maxWidth: 4096,
    maxHeight: 4096,
    maxVideoFrames: 257,
    maxImageBatch: 8,
    maxSteps: 200,
    maxReferenceImages: 8,
    maxUpscaleRepeats: 4,
    maxLoraPathLength: 4096,
  },
};

for (const directory of [config.filesRoot, config.modelsRoot, config.stateRoot, config.cacheRoot, path.join(config.filesRoot, 'qvac')]) {
  try {
    fs.mkdirSync(directory, { recursive: true });
  } catch (error) {
    // The service can still start and report the failure through /health.
    console.error(`[qvac] could not create ${directory}: ${error.message}`);
  }
}

module.exports = config;
