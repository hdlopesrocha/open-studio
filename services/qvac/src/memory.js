'use strict';

const fs = require('fs');
const os = require('os');
const { execFile } = require('child_process');
const { promisify } = require('util');

const execFileAsync = promisify(execFile);
const config = require('./config');

function readMemInfo() {
  try {
    const text = fs.readFileSync('/proc/meminfo', 'utf8');
    const values = {};
    for (const line of text.splitlines ? text.splitlines() : text.split('\n')) {
      const match = /^(\w+):\s+(\d+)\s+kB/.exec(line);
      if (match) values[match[1]] = Number(match[2]) * 1024;
    }
    if (values.MemTotal) {
      return {
        total: values.MemTotal,
        free: (values.MemAvailable || values.MemFree || 0),
        source: 'proc',
      };
    }
  } catch (error) {
    // fall through to os APIs
  }
  return { total: os.totalmem(), free: os.freemem(), source: 'os' };
}

async function nvidiaSmi() {
  try {
    const { stdout } = await execFileAsync(
      'nvidia-smi',
      ['--query-gpu=index,name,memory.total,memory.free,driver_version', '--format=csv,noheader,nounits'],
      { timeout: 5000 },
    );
    const devices = stdout
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const [index, name, total, free, driver] = line.split(',').map((part) => part.trim());
        return {
          index: Number(index),
          name,
          totalMemory: Number(total) * 1024 * 1024,
          freeMemory: Number(free) * 1024 * 1024,
          driverVersion: driver || null,
        };
      });
    return { available: devices.length > 0, devices, backend: 'nvidia-smi', error: null };
  } catch (error) {
    return {
      available: false,
      devices: [],
      backend: 'nvidia-smi',
      error: error.code === 'ENOENT' ? 'nvidia-smi not found' : String(error.message || error),
    };
  }
}

function vulkanPresence() {
  const devices = [];
  for (const candidate of ['/dev/dri/renderD128', '/dev/dri/card0']) {
    try {
      if (fs.existsSync(candidate)) devices.push(candidate);
    } catch (error) {
      // ignore
    }
  }
  const libraryCandidates = [
    '/usr/lib/x86_64-linux-gnu/libvulkan.so.1',
    '/usr/lib/aarch64-linux-gnu/libvulkan.so.1',
    '/usr/lib/libvulkan.so.1',
  ];
  const libraries = libraryCandidates.filter((candidate) => {
    try {
      return fs.existsSync(candidate);
    } catch (error) {
      return false;
    }
  });
  return { devices, libraries, available: devices.length > 0 || libraries.length > 0 };
}

function mb(bytes) {
  return Math.round((Number(bytes) / (1024 * 1024)) * 10) / 10;
}

async function memoryStatus({ includeGpu = true } = {}) {
  const system = readMemInfo();
  const gpu = includeGpu ? await nvidiaSmi() : { available: false, devices: [], backend: 'skipped', error: null };
  const vulkan = vulkanPresence();
  const unsupported = process.platform === 'darwin';
  const gpuTotal = gpu.devices.reduce((sum, device) => sum + device.totalMemory, 0);
  const gpuFree = gpu.devices.reduce((sum, device) => sum + device.freeMemory, 0);
  const requiredVideoMemory = config.requirements.videoMemoryGb * 1024 * 1024 * 1024;
  const requiredUnifiedMemory = config.requirements.unifiedMemoryGb * 1024 * 1024 * 1024;
  const availableForRequirement = config.device === 'gpu' ? gpuTotal : system.total;
  const requirement = config.device === 'gpu' ? requiredVideoMemory : unsupported ? requiredUnifiedMemory : system.total;
  const meets = config.device === 'gpu' ? gpuTotal >= requiredVideoMemory : system.total >= requiredUnifiedMemory;
  return {
    device: config.device,
    platform: process.platform,
    arch: process.arch,
    system: {
      total: system.total,
      free: system.free,
      totalGb: Math.round((system.total / 1024 ** 3) * 10) / 10,
      freeGb: Math.round((system.free / 1024 ** 3) * 10) / 10,
      source: system.source,
    },
    gpu: {
      available: gpu.available,
      backend: gpu.backend,
      error: gpu.error,
      devices: gpu.devices.map((device) => ({
        ...device,
        totalGb: Math.round((device.totalMemory / 1024 ** 3) * 10) / 10,
        freeGb: Math.round((device.freeMemory / 1024 ** 3) * 10) / 10,
      })),
      totalMemory: gpuTotal,
      freeMemory: gpuFree,
    },
    vulkan,
    requirements: {
      ...config.requirements,
      requiredBytes: config.device === 'gpu' ? requiredVideoMemory : requiredUnifiedMemory,
      availableBytes: availableForRequirement,
      meets: meets,
      targetBytes: requirement,
    },
    memoryMb: {
      systemTotal: mb(system.total),
      systemFree: mb(system.free),
      gpuTotal: mb(gpuTotal),
      gpuFree: mb(gpuFree),
    },
  };
}

module.exports = { memoryStatus, nvidiaSmi, readMemInfo, vulkanPresence };
