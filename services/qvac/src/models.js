'use strict';

const fs = require('fs');
const path = require('path');

const config = require('./config');
const sdk = require('./sdk');
const { VIDEO_FAMILIES, IMAGE_FAMILIES } = require('./catalog');
const { HttpError } = require('./errors');

const STATE_DIR = path.join(config.stateRoot, 'qvac');
const MANIFEST_PATH = path.join(STATE_DIR, 'installed-models.json');
let manifest = null;
let installQueue = Promise.resolve();

function emptyManifest() {
  return { version: 1, models: {}, families: {}, updated_at: null };
}

function readManifest() {
  if (manifest) return manifest;
  try {
    const parsed = JSON.parse(fs.readFileSync(MANIFEST_PATH, 'utf8'));
    manifest = {
      version: 1,
      models: parsed && typeof parsed.models === 'object' ? parsed.models : {},
      families: parsed && typeof parsed.families === 'object' ? parsed.families : {},
      updated_at: parsed && parsed.updated_at ? String(parsed.updated_at) : null,
    };
  } catch (error) {
    manifest = emptyManifest();
  }
  return manifest;
}

function writeManifest() {
  const data = readManifest();
  data.updated_at = new Date().toISOString();
  fs.mkdirSync(STATE_DIR, { recursive: true });
  const temporary = `${MANIFEST_PATH}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(data, null, 2)}\n`, 'utf8');
  fs.renameSync(temporary, MANIFEST_PATH);
}

function installedNames() {
  return new Set(Object.keys(readManifest().models || {}));
}

function familyDefinition(family) {
  return VIDEO_FAMILIES[family] || IMAGE_FAMILIES[family] || null;
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

function familyInfo(family, { loaded = [] } = {}) {
  const definition = familyDefinition(family);
  if (!definition) throw new HttpError(404, `Unknown QVAC model family: ${family}`);
  const models = requiredModels(definition);
  const completed = installedNames();
  for (const item of loaded) {
    const name = String(item && (item.modelName || item.model || '') || '');
    if (name) completed.add(name);
  }
  const missing = models.filter((name) => !completed.has(name));
  return {
    family,
    label: definition.label || family,
    kind: definition.kind || 'video',
    modes: definition.modes || [],
    models,
    installed: models.length > 0 && missing.length === 0,
    missing,
  };
}

async function resolveModelAssets(family) {
  const definition = familyDefinition(family);
  const info = familyInfo(family);
  if (hasPlaceholders(definition)) {
    throw new HttpError(422, `QVAC does not expose the required model files for ${family}`);
  }
  if (!info.models.length) {
    throw new HttpError(422, `No downloadable assets are declared for ${family}`);
  }
  if (config.mock) {
    throw new HttpError(503, 'QVAC mock mode does not download model weights. Set QVAC_MOCK=0 to install models.');
  }
  const sdkInfo = await sdk.sdkStatus(true);
  if (!sdkInfo.available) {
    throw new HttpError(503, `QVAC SDK is unavailable: ${sdkInfo.error || 'not installed'}`);
  }
  const loadedSdk = await sdk.getSdk();
  const assets = [];
  const missing = [];
  for (const name of info.models) {
    const descriptor = loadedSdk[name];
    if (!descriptor || (typeof descriptor !== 'object' && typeof descriptor !== 'string')) {
      missing.push(name);
      continue;
    }
    assets.push({
      name,
      descriptor,
      expectedSize: Number(descriptor.expectedSize) || 0,
    });
  }
  if (missing.length) {
    throw new HttpError(
      422,
      `This QVAC build is missing required model constants: ${missing.join(', ')}`,
    );
  }
  return { info, assets };
}

async function downloadFamily(family) {
  const { info, assets } = await resolveModelAssets(family);
  const loadedSdk = await sdk.getSdk();
  const totalBytes = assets.reduce((sum, item) => sum + (item.expectedSize || 0), 0);
  const done = [];
  for (const asset of assets) {
    try {
      await loadedSdk.downloadAsset({ assetSrc: asset.descriptor });
      done.push(asset);
    } catch (error) {
      throw new HttpError(
        502,
        `Could not download ${asset.name}: ${error && error.message ? error.message : String(error)}`,
      );
    }
  }
  const now = new Date().toISOString();
  const data = readManifest();
  for (const asset of assets) {
    data.models[asset.name] = {
      installed_at: now,
      family,
      size_bytes: asset.expectedSize || null,
    };
  }
  data.families[family] = {
    installed_at: now,
    models: assets.map((asset) => asset.name),
    size_bytes: totalBytes || null,
  };
  writeManifest();
  return {
    family,
    label: info.label,
    kind: info.kind,
    modes: info.modes,
    models: assets.map((asset) => asset.name),
    installed: true,
    size_bytes: totalBytes || null,
    downloaded: done.map((asset) => asset.name),
  };
}

function installFamily(family) {
  const key = String(family || '').trim();
  if (!key) return Promise.reject(new HttpError(422, 'family is required'));
  if (!familyDefinition(key)) return Promise.reject(new HttpError(404, `Unknown QVAC model family: ${key}`));
  const run = installQueue.then(() => downloadFamily(key));
  installQueue = run.catch(() => {});
  return run;
}

module.exports = {
  MANIFEST_PATH,
  familyDefinition,
  requiredModels,
  familyInfo,
  installedNames,
  readManifest,
  installFamily,
};
