import { apiPath } from './base';
import { apiFetchJson } from './client';

export const GOVERNANCE_AREAS = [
  {
    key: 'job-taxonomy',
    summaryKey: 'job_taxonomy',
    label: 'Job Taxonomy Review',
  },
  {
    key: 'skill-candidates',
    summaryKey: 'skill_candidates',
    label: 'Skill Candidates',
  },
  {
    key: 'company-industries',
    summaryKey: 'company_industries',
    label: 'Company Industries',
  },
];

function appendValues(params, key, values) {
  for (const value of values || []) {
    if (value !== null && value !== undefined && String(value).trim()) {
      params.append(key, String(value));
    }
  }
}

function queryPath(path, buildParams) {
  const params = new URLSearchParams();
  buildParams?.(params);
  const query = params.toString();
  return apiPath(query ? `${path}?${query}` : path);
}

function getJson(path, options) {
  return apiFetchJson(path, options);
}

function postJson(path, body, options = {}) {
  return apiFetchJson(path, {
    ...options,
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    body: JSON.stringify(body),
  });
}

function decisionKey(prefix, subjectId) {
  const randomId = globalThis.crypto?.randomUUID?.();
  return `${prefix}:${subjectId}:${randomId || `${Date.now()}-${Math.random()}`}`;
}

function commonDecisionBody(values, prefix, subjectId) {
  return {
    action: values.action,
    expected_version: values.expectedVersion,
    idempotency_key:
      values.idempotencyKey || decisionKey(prefix, subjectId),
    confirmed: true,
    ...(values.note ? { note: values.note } : {}),
    ...(values.correlationId
      ? { correlation_id: values.correlationId }
      : {}),
  };
}

export function fetchGovernanceSummary(options) {
  return getJson(apiPath('/job-intelligence/governance/summary'), options);
}

export function fetchCanonicalRevision(options) {
  return getJson(
    apiPath('/job-intelligence/canonical-job-taxonomy/revision'),
    options,
  );
}

export function fetchCanonicalTree(options) {
  return getJson(
    apiPath('/job-intelligence/canonical-job-taxonomy/tree'),
    options,
  );
}

export function fetchCanonicalReviewItems(filters = {}, options) {
  const path = queryPath(
    '/job-intelligence/governance/job-taxonomy/review-items',
    (params) => {
      appendValues(params, 'status', filters.status);
      appendValues(params, 'reason', filters.reason);
      if (filters.jobId) params.set('job_id', filters.jobId);
      if (filters.cursor) params.set('cursor', filters.cursor);
      if (filters.limit) params.set('limit', String(filters.limit));
    },
  );
  return getJson(path, options);
}

export function fetchCanonicalReviewItem(reviewItemId, options) {
  return getJson(
    apiPath(
      `/job-intelligence/governance/job-taxonomy/review-items/${encodeURIComponent(reviewItemId)}`,
    ),
    options,
  );
}

export function decideCanonicalReviewItem(reviewItemId, values, options) {
  const body = {
    ...commonDecisionBody(values, 'job-taxonomy', reviewItemId),
    ...(values.targetId ? { target_id: values.targetId } : {}),
  };
  return postJson(
    apiPath(
      `/job-intelligence/governance/job-taxonomy/review-items/${encodeURIComponent(reviewItemId)}/decision`,
    ),
    body,
    options,
  );
}

export function fetchCanonicalAudit(filters = {}, options) {
  return getJson(
    queryPath(
      '/job-intelligence/governance/job-taxonomy/audit-events',
      (params) => {
        if (filters.subjectId) params.set('subject_id', filters.subjectId);
        if (filters.cursor) params.set('cursor', filters.cursor);
        if (filters.limit) params.set('limit', String(filters.limit));
      },
    ),
    options,
  );
}

export function fetchSkillRevision(options) {
  return getJson(apiPath('/job-intelligence/skills/revision'), options);
}

export function fetchSkillTree(options) {
  return getJson(apiPath('/job-intelligence/skills/tree'), options);
}

export function searchGovernedSkills(filters = {}, options) {
  return getJson(
    queryPath('/job-intelligence/skills/search', (params) => {
      if (filters.query) params.set('q', filters.query);
      if (filters.categoryCode) {
        params.set('category_code', filters.categoryCode);
      }
      if (filters.technologyCode) {
        params.set('technology_code', filters.technologyCode);
      }
      if (filters.limit) params.set('limit', String(filters.limit));
    }),
    options,
  );
}

export function fetchSkillCandidates(filters = {}, options) {
  return getJson(
    queryPath('/job-intelligence/governance/skills/candidates', (params) => {
      appendValues(params, 'status', filters.status);
      if (filters.search) params.set('search', filters.search);
      if (filters.cursor) params.set('cursor', filters.cursor);
      if (filters.limit) params.set('limit', String(filters.limit));
    }),
    options,
  );
}

export function fetchSkillCandidate(candidateId, options) {
  return getJson(
    apiPath(
      `/job-intelligence/governance/skills/candidates/${encodeURIComponent(candidateId)}`,
    ),
    options,
  );
}

export function fetchSkillRecommendations(candidateId, filters = {}, options) {
  return getJson(
    queryPath(
      `/job-intelligence/governance/skills/candidates/${encodeURIComponent(candidateId)}/recommendations`,
      (params) => {
        if (filters.limit) params.set('limit', String(filters.limit));
      },
    ),
    options,
  );
}

export function decideSkillCandidate(candidateId, values, options) {
  const body = {
    ...commonDecisionBody(values, 'skill-candidate', candidateId),
    ...(values.targetSkillId
      ? { target_skill_id: values.targetSkillId }
      : {}),
    ...(values.createTarget ? { create_target: values.createTarget } : {}),
    ...(values.genericTag ? { generic_tag: values.genericTag } : {}),
    ...(values.rejectionReason
      ? { rejection_reason: values.rejectionReason }
      : {}),
  };
  return postJson(
    apiPath(
      `/job-intelligence/governance/skills/candidates/${encodeURIComponent(candidateId)}/decision`,
    ),
    body,
    options,
  );
}

export function fetchSkillAudit(filters = {}, options) {
  return getJson(
    queryPath('/job-intelligence/governance/skills/audit-events', (params) => {
      if (filters.subjectId) params.set('subject_id', filters.subjectId);
      if (filters.cursor) params.set('cursor', filters.cursor);
      if (filters.limit) params.set('limit', String(filters.limit));
    }),
    options,
  );
}

export function fetchCompanyIndustryRevision(options) {
  return getJson(apiPath('/job-intelligence/company-industries/revision'), options);
}

export function fetchCompanyIndustryTree(filters = {}, options) {
  return getJson(
    queryPath('/job-intelligence/company-industries/tree', (params) => {
      if (filters.parentId) params.set('parent_id', filters.parentId);
    }),
    options,
  );
}

export function fetchCompanyIndustryState(companyId, options) {
  return getJson(
    apiPath(
      `/job-intelligence/companies/${encodeURIComponent(companyId)}/industries`,
    ),
    options,
  );
}

export function fetchCompanyIndustryReviewItems(filters = {}, options) {
  return getJson(
    queryPath(
      '/job-intelligence/governance/company-industries/review-items',
      (params) => {
        appendValues(params, 'status', filters.status);
        appendValues(params, 'source_site', filters.sourceSite);
        appendValues(params, 'reason', filters.reason);
        if (filters.companyId) params.set('company_id', filters.companyId);
        if (filters.rawValue) params.set('raw_value', filters.rawValue);
        if (filters.cursor) params.set('cursor', filters.cursor);
        if (filters.limit) params.set('limit', String(filters.limit));
      },
    ),
    options,
  );
}

export function fetchCompanyIndustryReviewItem(reviewItemId, options) {
  return getJson(
    apiPath(
      `/job-intelligence/governance/company-industries/review-items/${encodeURIComponent(reviewItemId)}`,
    ),
    options,
  );
}

export function decideCompanyIndustryReviewItem(reviewItemId, values, options) {
  const body = {
    ...commonDecisionBody(values, 'company-industry', reviewItemId),
    ...(values.targetId ? { target_id: values.targetId } : {}),
  };
  return postJson(
    apiPath(
      `/job-intelligence/governance/company-industries/review-items/${encodeURIComponent(reviewItemId)}/decision`,
    ),
    body,
    options,
  );
}

export function fetchCompanyIndustryMappings(filters = {}, options) {
  return getJson(
    queryPath('/job-intelligence/governance/company-industries/mappings', (params) => {
      appendValues(params, 'source_site', filters.sourceSite);
      appendValues(params, 'status', filters.status);
    }),
    options,
  );
}

export function fetchCompanyIndustryAudit(filters = {}, options) {
  return getJson(
    queryPath(
      '/job-intelligence/governance/company-industries/audit-events',
      (params) => {
        if (filters.subjectId) params.set('subject_id', filters.subjectId);
        if (filters.cursor) params.set('cursor', filters.cursor);
        if (filters.limit) params.set('limit', String(filters.limit));
      },
    ),
    options,
  );
}

export function isStaleGovernanceError(error) {
  return (
    error?.status === 409 &&
    error?.code === 'GOVERNANCE_DECISION_STALE_VERSION'
  );
}
