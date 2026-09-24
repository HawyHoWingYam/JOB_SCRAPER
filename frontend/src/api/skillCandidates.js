import { apiPath } from './base';
import { apiFetchJson } from './client';

const ROOT = '/job-intelligence/skill-candidates';

export function fetchSkillCandidates({ readyOnly = true, limit = 100, offset = 0, signal } = {}) {
  const query = new URLSearchParams({
    ready_only: String(readyOnly),
    limit: String(limit),
    offset: String(offset),
  });
  return apiFetchJson(apiPath(`${ROOT}?${query}`), {
    retryTransient: true,
    signal,
  });
}

export function decideSkillCandidate(candidateId, payload) {
  return apiFetchJson(
    apiPath(`${ROOT}/${encodeURIComponent(candidateId)}/decision`),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  );
}

export function fetchSkillMaintenanceStatus({ signal } = {}) {
  return apiFetchJson(apiPath(`${ROOT}/maintenance/status`), {
    retryTransient: true,
    signal,
  });
}

export function approveSkillMaintenance(batchId) {
  return apiFetchJson(
    apiPath(`${ROOT}/maintenance/${encodeURIComponent(batchId)}/approve`),
    { method: 'POST' },
  );
}
