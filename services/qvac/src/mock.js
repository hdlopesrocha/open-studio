'use strict';

const fs = require('fs');
const fsp = require('fs/promises');
const path = require('path');
const { spawn, execFile } = require('child_process');
const { promisify } = require('util');

const config = require('./config');
const { JobCancelled } = require('./errors');

const execFileAsync = promisify(execFile);
const TINY_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
);

let availableCache = null;

async function ffmpegAvailable() {
  if (availableCache !== null) return availableCache;
  try {
    await execFileAsync(config.ffmpeg, ['-version'], { timeout: 5000 });
    availableCache = true;
  } catch (error) {
    availableCache = false;
  }
  return availableCache;
}

async function ffmpegVersion() {
  try {
    const { stdout } = await execFileAsync(config.ffmpeg, ['-version'], { timeout: 5000 });
    return stdout.split('\n')[0] || null;
  } catch (error) {
    return null;
  }
}

function killProcess(child) {
  if (!child || child.exitCode !== null) return;
  try {
    process.kill(-child.pid, 'SIGTERM');
  } catch (error) {
    try {
      child.kill('SIGTERM');
    } catch (inner) {
      // already gone
    }
  }
}

async function runFfmpeg(args, options = {}) {
  const { check, onProgress, timeout = 3600 } = options;
  const available = await ffmpegAvailable();
  if (!available) return { ok: false, error: 'ffmpeg is not installed' };
  return new Promise((resolve, reject) => {
    const child = spawn(config.ffmpeg, ['-hide_banner', '-y', '-nostats', '-progress', 'pipe:1', ...args], {
      stdio: ['ignore', 'pipe', 'pipe'],
      detached: true,
    });
    let stdout = '';
    let stderr = '';
    let settled = false;
    const started = Date.now();
    const timer = setInterval(async () => {
      if (settled) return;
      if (timeout && Date.now() - started > timeout * 1000) {
        killProcess(child);
        settled = true;
        clearInterval(timer);
        reject(new Error(`ffmpeg exceeded the ${timeout}s timeout`));
        return;
      }
      if (check) {
        try {
          await check();
        } catch (error) {
          killProcess(child);
          settled = true;
          clearInterval(timer);
          reject(error instanceof JobCancelled ? error : new JobCancelled(error.message));
        }
      }
    }, 400);
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString('utf8');
      if (onProgress && stdout.length > 0) {
        const lines = stdout.split('\n');
        stdout = lines.pop() || '';
        for (const line of lines) {
          const [key, value] = line.split('=');
          if (key === 'out_time_us' && onProgress) {
            const seconds = Number(value) / 1e6;
            if (Number.isFinite(seconds)) onProgress(seconds);
          }
        }
      }
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString('utf8');
      if (stderr.length > 20000) stderr = stderr.slice(-10000);
    });
    child.on('error', (error) => {
      if (settled) return;
      settled = true;
      clearInterval(timer);
      reject(error);
    });
    child.on('close', (code, signal) => {
      if (settled) return;
      settled = true;
      clearInterval(timer);
      if (code === 0) resolve({ ok: true, stderr });
      else reject(new Error(stderr.split('\n').slice(-12).join('\n') || `ffmpeg exited with ${code || signal}`));
    });
  });
}

function placeholder(filePath, text) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${text}\n`, 'utf8');
  return filePath;
}

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value));
}

async function createMockVideo({ outputPath, width, height, fps, duration, prompt, check }) {
  const safeWidth = clamp(Number(width) || 480, 64, 1920);
  const safeHeight = clamp(Number(height) || 832, 64, 1920);
  const safeFps = clamp(Number(fps) || 16, 1, 60);
  const safeDuration = clamp(Number(duration) || 2, 0.5, 5);
  const available = await ffmpegAvailable();
  if (!available) {
    placeholder(outputPath.replace(/\.mp4$/i, '.mock.txt'), `MOCK QVAC VIDEO: ${prompt || 'no prompt'}`);
    placeholder(outputPath, 'MOCK QVAC VIDEO PLACEHOLDER (ffmpeg is not installed)');
    return { usedFfmpeg: false, warning: 'ffmpeg not found; wrote a text placeholder instead of a playable MP4.' };
  }
  const size = `${Math.round(safeWidth / 2) * 2}x${Math.round(safeHeight / 2) * 2}`;
  try {
    await runFfmpeg(
      [
        '-f', 'lavfi', '-i', `testsrc2=size=${size}:rate=${safeFps}`,
        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
        '-t', String(safeDuration),
        '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '96k', '-shortest',
        outputPath,
      ],
      { check, timeout: 120 },
    );
    return { usedFfmpeg: true, warning: null };
  } catch (error) {
    if (error instanceof JobCancelled) throw error;
    placeholder(outputPath.replace(/\.mp4$/i, '.mock.txt'), `MOCK QVAC VIDEO: ${prompt || 'no prompt'}\n${error.message}`);
    placeholder(outputPath, 'MOCK QVAC VIDEO PLACEHOLDER (ffmpeg failed)');
    return { usedFfmpeg: false, warning: `ffmpeg mock render failed: ${error.message}` };
  }
}

async function createMockImage({ outputPath, width, height, check }) {
  const safeWidth = clamp(Number(width) || 512, 32, 2048);
  const safeHeight = clamp(Number(height) || 512, 32, 2048);
  const available = await ffmpegAvailable();
  if (!available) {
    await fsp.mkdir(path.dirname(outputPath), { recursive: true });
    await fsp.writeFile(outputPath, TINY_PNG);
    return { usedFfmpeg: false, warning: 'ffmpeg not found; wrote a 1x1 PNG placeholder.' };
  }
  try {
    await runFfmpeg(
      [
        '-f', 'lavfi', '-i', `color=c=0x3355aa:s=${Math.round(safeWidth / 2) * 2}x${Math.round(safeHeight / 2) * 2}`,
        '-frames:v', '1', '-update', '1', outputPath,
      ],
      { check, timeout: 60 },
    );
    return { usedFfmpeg: true, warning: null };
  } catch (error) {
    if (error instanceof JobCancelled) throw error;
    await fsp.mkdir(path.dirname(outputPath), { recursive: true });
    await fsp.writeFile(outputPath, TINY_PNG);
    return { usedFfmpeg: false, warning: `ffmpeg mock image render failed: ${error.message}` };
  }
}

async function mockUpscale({ inputPath, outputPath, repeats = 1, check }) {
  const available = await ffmpegAvailable();
  if (!available) {
    await fsp.copyFile(inputPath, outputPath);
    return { usedFfmpeg: false, warning: 'ffmpeg not found; copied the input image instead.' };
  }
  const factor = Math.pow(2, Math.max(1, Math.min(4, Number(repeats) || 1)));
  try {
    await runFfmpeg(
      ['-i', inputPath, '-vf', `scale=iw*${factor}:ih*${factor}:flags=lanczos`, '-frames:v', '1', '-update', '1', outputPath],
      { check, timeout: 300 },
    );
    return { usedFfmpeg: true, warning: null };
  } catch (error) {
    if (error instanceof JobCancelled) throw error;
    await fsp.copyFile(inputPath, outputPath);
    return { usedFfmpeg: false, warning: `ffmpeg mock upscale failed: ${error.message}` };
  }
}

async function transcodeToMp4(inputPath, outputPath, { check, onProgress } = {}) {
  const available = await ffmpegAvailable();
  if (!available) return { ok: false, warning: 'ffmpeg not found; keeping the AVI output only.' };
  try {
    await runFfmpeg(
      [
        '-i', inputPath,
        '-c:v', 'libx264', '-preset', 'medium', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart',
        outputPath,
      ],
      { check, onProgress, timeout: 3600 },
    );
    return { ok: true, warning: null };
  } catch (error) {
    if (error instanceof JobCancelled) throw error;
    return { ok: false, warning: `MP4 transcode failed: ${error.message}` };
  }
}

module.exports = {
  ffmpegAvailable,
  ffmpegVersion,
  runFfmpeg,
  createMockVideo,
  createMockImage,
  mockUpscale,
  transcodeToMp4,
  TINY_PNG,
};
