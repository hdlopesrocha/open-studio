'use strict';

const fs = require('fs');
const fsp = require('fs/promises');
const path = require('path');

const config = require('./config');
const { HttpError } = require('./errors');

const IMAGE_EXTENSIONS = new Set(['.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff', '.avif']);
const VIDEO_EXTENSIONS = new Set(['.mp4', '.mkv', '.mov', '.webm', '.avi', '.m4v', '.mpeg', '.mpg']);
const AUDIO_EXTENSIONS = new Set(['.wav', '.mp3', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.aiff', '.aif']);
const SUBTITLE_EXTENSIONS = new Set(['.srt', '.vtt', '.ass', '.ssa']);
const MODEL_EXTENSIONS = new Set(['.gguf', '.safetensors', '.pth', '.bin', '.onnx', '.pt']);
const JOB_ID_RE = /^[A-Za-z0-9_-]{1,80}$/;

function isInside(root, target) {
  const relative = path.relative(root, target);
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

function safeResolve(value, options = {}) {
  const {
    label = 'path',
    allowAbsolute = false,
    root = config.filesRoot,
    mustExist = false,
    mustBeFile = false,
    mustBeDirectory = false,
  } = options;
  if (typeof value !== 'string' || value.trim() === '') {
    throw new HttpError(422, `${label} is required`);
  }
  const text = value.trim();
  if (text.includes('\0')) {
    throw new HttpError(422, `${label} cannot contain null bytes`);
  }
  let target;
  if (path.isAbsolute(text)) {
    if (!allowAbsolute && !isInside(root, path.resolve(text))) {
      throw new HttpError(422, `${label} must be relative to ${root}`);
    }
    target = path.resolve(text);
  } else {
    target = path.resolve(root, text);
    if (!isInside(root, target)) {
      throw new HttpError(422, `${label} escapes ${root}`);
    }
  }
  if (mustExist && !fs.existsSync(target)) {
    throw new HttpError(404, `${label} not found: ${text}`);
  }
  if (mustExist && mustBeFile && !fs.statSync(target).isFile()) {
    throw new HttpError(422, `${label} must be a file: ${text}`);
  }
  if (mustExist && mustBeDirectory && !fs.statSync(target).isDirectory()) {
    throw new HttpError(422, `${label} must be a directory: ${text}`);
  }
  return target;
}

function inputFile(value, label, options = {}) {
  return safeResolve(value, { ...options, label, mustExist: true, mustBeFile: true });
}

function optionalInput(value, label, options = {}) {
  if (value === undefined || value === null || value === '') return null;
  return inputFile(value, label, options);
}

function isUrl(value) {
  return typeof value === 'string' && /^https?:\/\//i.test(value.trim());
}

function isConstantName(value) {
  return typeof value === 'string' && /^[A-Z][A-Z0-9_]{2,}$/.test(value.trim());
}

function modelSource(value, label = 'modelSrc') {
  if (typeof value !== 'string' || value.trim() === '') {
    throw new HttpError(422, `${label} is required`);
  }
  const text = value.trim();
  if (isUrl(text) || isConstantName(text)) return text;
  if (path.isAbsolute(text)) {
    if (!fs.existsSync(text)) throw new HttpError(404, `${label} not found: ${text}`);
    return text;
  }
  const underModels = path.resolve(config.modelsRoot, text);
  if (!isInside(config.modelsRoot, underModels)) {
    throw new HttpError(422, `${label} escapes the models root`);
  }
  if (fs.existsSync(underModels)) return underModels;
  const underFiles = path.resolve(config.filesRoot, text);
  if (isInside(config.filesRoot, underFiles) && fs.existsSync(underFiles)) return underFiles;
  throw new HttpError(404, `${label} not found under the models root: ${text}`);
}

function loraSource(value) {
  if (typeof value !== 'string' || value.trim() === '') {
    throw new HttpError(422, 'lora must be an absolute worker path or a model-relative path');
  }
  const text = value.trim();
  if (text.length > config.limits.maxLoraPathLength) {
    throw new HttpError(422, 'lora path is too long');
  }
  if (path.isAbsolute(text)) {
    if (!fs.existsSync(text)) throw new HttpError(404, `lora not found: ${text}`);
    return text;
  }
  return modelSource(text, 'lora');
}

function jobId(value) {
  const text = String(value || '').trim();
  if (!JOB_ID_RE.test(text)) {
    throw new HttpError(422, 'job_id may only contain letters, numbers, underscore and dash');
  }
  return text;
}

async function outputDir(jobIdValue) {
  const id = jobId(jobIdValue);
  const directory = path.join(config.filesRoot, 'qvac', id);
  await fsp.mkdir(directory, { recursive: true });
  return directory;
}

function relativePath(filePath) {
  const resolved = path.resolve(filePath);
  if (!isInside(config.filesRoot, resolved)) {
    throw new HttpError(500, `File is outside the shared files root: ${filePath}`);
  }
  return path.relative(config.filesRoot, resolved).split(path.sep).join('/');
}

function kindFor(filePath) {
  const extension = path.extname(filePath).toLowerCase();
  if (IMAGE_EXTENSIONS.has(extension)) return 'image';
  if (VIDEO_EXTENSIONS.has(extension)) return 'video';
  if (AUDIO_EXTENSIONS.has(extension)) return 'audio';
  if (SUBTITLE_EXTENSIONS.has(extension)) return 'subtitle';
  if (MODEL_EXTENSIONS.has(extension)) return 'model';
  if (extension === '.json') return 'document';
  return 'other';
}

function mimeFor(filePath) {
  const extension = path.extname(filePath).toLowerCase();
  const map = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
    '.bmp': 'image/bmp',
    '.gif': 'image/gif',
    '.mp4': 'video/mp4',
    '.m4v': 'video/mp4',
    '.mkv': 'video/x-matroska',
    '.mov': 'video/quicktime',
    '.webm': 'video/webm',
    '.avi': 'video/x-msvideo',
    '.wav': 'audio/wav',
    '.mp3': 'audio/mpeg',
    '.flac': 'audio/flac',
    '.m4a': 'audio/mp4',
    '.ogg': 'audio/ogg',
    '.opus': 'audio/opus',
    '.srt': 'application/x-subrip',
    '.vtt': 'text/vtt',
    '.ass': 'text/x-ssa',
    '.json': 'application/json',
    '.gguf': 'application/octet-stream',
    '.safetensors': 'application/octet-stream',
  };
  return map[extension] || 'application/octet-stream';
}

function fileDescriptor(filePath) {
  const stat = fs.statSync(filePath);
  return {
    path: relativePath(filePath),
    name: path.basename(filePath),
    kind: kindFor(filePath),
    mime: mimeFor(filePath),
    size: stat.size,
    modified: stat.mtime.toISOString(),
  };
}

function describeFiles(filePaths) {
  const seen = new Set();
  const items = [];
  for (const filePath of filePaths) {
    if (!filePath || !fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) continue;
    const descriptor = fileDescriptor(filePath);
    if (seen.has(descriptor.path)) continue;
    seen.add(descriptor.path);
    items.push(descriptor);
  }
  return items;
}

async function saveBuffer(filePath, buffer) {
  await fsp.mkdir(path.dirname(filePath), { recursive: true });
  await fsp.writeFile(filePath, Buffer.from(buffer));
  return filePath;
}

async function readBuffer(filePath) {
  return new Uint8Array(await fsp.readFile(filePath));
}

function readBufferSync(filePath) {
  return new Uint8Array(fs.readFileSync(filePath));
}

function imageList(value, label) {
  if (value === undefined || value === null || value === '') return [];
  if (!Array.isArray(value)) throw new HttpError(422, `${label} must be an array of paths`);
  if (value.length > config.limits.maxReferenceImages) {
    throw new HttpError(422, `${label} supports at most ${config.limits.maxReferenceImages} images`);
  }
  return value.map((item, index) => inputFile(item, `${label}[${index}]`));
}

module.exports = {
  IMAGE_EXTENSIONS,
  VIDEO_EXTENSIONS,
  AUDIO_EXTENSIONS,
  MODEL_EXTENSIONS,
  JOB_ID_RE,
  isInside,
  safeResolve,
  inputFile,
  optionalInput,
  isUrl,
  isConstantName,
  modelSource,
  loraSource,
  jobId,
  outputDir,
  relativePath,
  kindFor,
  mimeFor,
  fileDescriptor,
  describeFiles,
  saveBuffer,
  readBuffer,
  readBufferSync,
  imageList,
};
