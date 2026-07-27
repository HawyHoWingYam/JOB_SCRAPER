import { apiPath } from './base';
import { apiFetchJson } from './client';

function getCurrent(path, options) {
  return apiFetchJson(apiPath(path), {
    retryTransient: true,
    ...options,
  });
}

export function fetchCurrentJobTaxonomyTree(options) {
  return getCurrent('/job-intelligence/job-taxonomy/tree', options);
}

export function fetchCurrentJobTaxonomyState(jobId, options) {
  return getCurrent(
    `/job-intelligence/jobs/${encodeURIComponent(jobId)}/job-taxonomy`,
    options,
  );
}

export function fetchCurrentCompanyIndustryTree(options) {
  return getCurrent('/job-intelligence/company-industries/tree', options);
}

export function fetchCurrentCompanyIndustryState(companyId, options) {
  return getCurrent(
    `/job-intelligence/companies/${encodeURIComponent(companyId)}/industries`,
    options,
  );
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
