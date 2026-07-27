import { apiPath } from './base';
import { apiFetchJson } from './client';

const ROOT = '/job-intelligence/classification-batches';

function request(path, options = {}) {
  return apiFetchJson(apiPath(`${ROOT}${path}`), {
    retryTransient: true,
    ...options,
  });
}

export function previewClassificationBatch(domain, payload, options) {
  return request(`/${encodeURIComponent(domain)}/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    ...options,
  });
}

export function startClassificationBatch(domain, payload, options) {
  return request(`/${encodeURIComponent(domain)}/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    ...options,
  });
}

export function fetchClassificationRuns(domain, options) {
  const query = domain ? `?domain=${encodeURIComponent(domain)}` : '';
  return request(`/runs${query}`, options);
}

export function stopClassificationRun(runId, options) {
  return request(`/runs/${encodeURIComponent(runId)}/stop`, {
    method: 'POST',
    ...options,
  });
}

export function retryClassificationRun(runId, options) {
  return request(`/runs/${encodeURIComponent(runId)}/retry-failed`, {
    method: 'POST',
    ...options,
  });
}
