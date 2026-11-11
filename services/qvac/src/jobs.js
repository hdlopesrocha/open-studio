'use strict';

const config = require('./config');
const sdk = require('./sdk');
const { HttpError, JobCancelled } = require('./errors');
const { validateVideo, validateImage, validateUpscale } = require('./validation');

const JOB_ID_RE = /^[A-Za-z0-9_-]{1,80}$/;
const STATES = new Map();

function headers() {
  return {
    'Content-Type': 'application/json',
    'X-Internal-Token': config.internalToken,
    'X-Service': 'qvac',
  };
}

async function postJson(url, payload, timeoutMs = 10000) {
  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(timeoutMs),
    });
    return response;
  } catch (error) {
    return null;
  }
}

function normalizeJobId(value) {
  const text = String(value || '').trim();
  if (!JOB_ID_RE.test(text)) throw new HttpError(422, 'job_id may only contain letters, numbers, underscore and dash');
  return text;
}

function state(jobId) {
  let entry = STATES.get(jobId);
  if (!entry) {
    entry = {
      jobId,
      cancelRequested: false,
      sdkRequestId: null,
      startedAt: null,
      lastPoll: 0,
      action: null,
      stage: 'Queued',
      completed: false,
    };
    STATES.set(jobId, entry);
  }
  return entry;
}

async function report(jobId, progress, stage, message, warnings) {
  const payload = {};
  if (progress !== undefined && progress !== null) payload.progress = Math.max(0, Math.min(100, Number(progress)));
  if (stage) payload.stage = String(stage);
  if (message) payload.message = String(message);
  if (warnings && warnings.length) payload.warnings = warnings.map((item) => String(item).slice(0, 1000));
  if (!Object.keys(payload).length) return;
  await postJson(`${config.jobhubUrl}/internal/jobs/${jobId}/progress`, payload, 8000);
}

async function remoteCancelState(jobId) {
  try {
    const response = await fetch(`${config.jobhubUrl}/internal/jobs/${jobId}/cancel-state`, {
      headers: headers(),
      signal: AbortSignal.timeout(5000),
    });
    if (response.status === 200) {
      const data = await response.json();
      return Boolean(data.cancel_requested);
    }
  } catch (error) {
    // The job hub may be unavailable while this worker is finishing.
  }
  return false;
}

function contextFor(jobId) {
  const entry = state(jobId);
  async function checkCancelled() {
    if (entry.cancelRequested) throw new JobCancelled();
    const now = Date.now();
    if (now - entry.lastPoll > 1500) {
      entry.lastPoll = now;
      const remote = await remoteCancelState(jobId);
      if (remote) {
        entry.cancelRequested = true;
        if (entry.sdkRequestId) await sdk.cancelSdkRequest(entry.sdkRequestId);
        throw new JobCancelled();
      }
    }
  }
  return {
    jobId,
    state: entry,
    report: (progress, stage, message) => {
      if (stage) entry.stage = stage;
      return report(jobId, progress, stage, message);
    },
    checkCancel: checkCancelled,
    onRequestId: async (requestId) => {
      entry.sdkRequestId = requestId;
      if (entry.cancelRequested) await sdk.cancelSdkRequest(requestId);
    },
  };
}

async function submitJob(action, params, title) {
  const payload = {
    component: 'qvac',
    action,
    title: title || `QVAC · ${action}`,
    params,
  };
  let response;
  try {
    response = await fetch(`${config.jobhubUrl}/api/jobs`, {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(15000),
    });
  } catch (error) {
    throw new HttpError(502, `Job hub unreachable: ${error.message}`);
  }
  if (!response.ok) {
    const text = (await response.text()).slice(0, 1000);
    throw new HttpError(502, `Job hub rejected the job: ${text}`);
  }
  return response.json();
}

function uniqueWarnings(...groups) {
  const seen = new Set();
  const result = [];
  for (const group of groups) {
    for (const warning of group || []) {
      if (!warning || seen.has(warning)) continue;
      seen.add(warning);
      result.push(warning);
    }
  }
  return result;
}

async function runJob({ job_id: rawJobId, action, params: rawParams }) {
  const jobId = normalizeJobId(rawJobId);
  const entry = state(jobId);
  entry.startedAt = new Date().toISOString();
  entry.action = action;
  entry.completed = false;
  const params = rawParams && typeof rawParams === 'object' && !Array.isArray(rawParams) ? rawParams : {};
  try {
    await report(jobId, 1, 'Starting', `Starting QVAC ${action}`);

    let validated;
    if (action === 'video') validated = validateVideo(params);
    else if (action === 'image') validated = validateImage(params);
    else if (action === 'upscale') validated = validateUpscale(params);
    else throw new HttpError(422, `Unknown QVAC action: ${action}`);

    const ctx = contextFor(jobId);
    let result;
    if (action === 'video') result = await sdk.generateVideo(validated.params, ctx);
    else if (action === 'image') result = await sdk.generateImage(validated.params, ctx);
    else result = await sdk.generateUpscale(validated.params, ctx);

    const warnings = uniqueWarnings(validated.warnings, result.data && result.data.warnings);
    if (warnings.length) {
      result.data = result.data || {};
      result.data.warnings = warnings;
      await report(jobId, undefined, 'Warnings', undefined, warnings);
    }
    entry.completed = true;
    entry.stage = 'Complete';
    await report(jobId, 100, 'Complete', result.message || 'Completed');
    setTimeout(() => STATES.delete(jobId), 5 * 60 * 1000).unref?.();
    return result;
  } catch (error) {
    entry.completed = true;
    entry.stage = error instanceof JobCancelled ? 'Cancelled' : 'Failed';
    setTimeout(() => STATES.delete(jobId), 5 * 60 * 1000).unref?.();
    throw error;
  }
}

async function requestCancel(jobIdValue) {
  const jobId = normalizeJobId(jobIdValue);
  const entry = state(jobId);
  entry.cancelRequested = true;
  await report(jobId, undefined, 'Cancelling', 'Cancellation requested');
  if (entry.sdkRequestId) await sdk.cancelSdkRequest(entry.sdkRequestId);
  return true;
}

function cancelState(jobIdValue) {
  const jobId = normalizeJobId(jobIdValue);
  const entry = STATES.get(jobId);
  return { job_id: jobId, cancel_requested: Boolean(entry && entry.cancelRequested) };
}

function activeJobs() {
  return [...STATES.values()]
    .filter((entry) => !entry.completed)
    .map((entry) => ({
      job_id: entry.jobId,
      action: entry.action,
      stage: entry.stage,
      started_at: entry.startedAt,
      cancel_requested: entry.cancelRequested,
    }));
}

module.exports = {
  report,
  submitJob,
  runJob,
  requestCancel,
  cancelState,
  contextFor,
  activeJobs,
  normalizeJobId,
};
