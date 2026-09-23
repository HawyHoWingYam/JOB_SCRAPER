import { apiPath } from './base';
import { apiFetchJson } from './client';

function getCurrent(path, options) {
  return apiFetchJson(apiPath(path), {
    retryTransient: true,
    ...options,
  });
}

export function fetchCurrentSkillTree(options) {
  return getCurrent('/job-intelligence/skills/tree', options);
}

export function fetchCurrentJobSkills(jobId, options) {
  return getCurrent(
    `/job-intelligence/jobs/${encodeURIComponent(jobId)}/skills`,
    options,
  );
}
