import { GOVERNANCE_AREAS } from '../../api/jobIntelligence';

const DEFAULT_AREA = GOVERNANCE_AREAS[0].key;
const AREA_KEYS = new Set(GOVERNANCE_AREAS.map((area) => area.key));

function readPositiveInteger(value) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

function readArray(params, key) {
  return params.getAll(key).map((value) => value.trim()).filter(Boolean);
}

function scopeFromParams(params) {
  const sourceSites = readArray(params, 'source_site');
  const sourceClassificationIds = readArray(params, 'source_classification_id');
  const sourceSubclassificationIds = readArray(params, 'source_subclassification_id');
  const jobIds = readArray(params, 'job_id');
  const source = {
    ...(sourceSites.length ? { sourceSites } : {}),
    ...(sourceClassificationIds.length ? { sourceClassificationIds } : {}),
    ...(sourceSubclassificationIds.length ? { sourceSubclassificationIds } : {}),
    ...(params.get('posted_date_from') ? { postedDateFrom: params.get('posted_date_from') } : {}),
    ...(params.get('posted_date_to') ? { postedDateTo: params.get('posted_date_to') } : {}),
    ...(readPositiveInteger(params.get('pending_limit'))
      ? { pendingLimit: readPositiveInteger(params.get('pending_limit')) }
      : {}),
    ...(params.get('reason') ? { reason: params.get('reason') } : {}),
    ...(jobIds.length ? { jobIds } : {}),
  };
  return Object.keys(source).length > 0 ? source : null;
}

function appendArray(params, key, values) {
  for (const value of values || []) {
    if (value !== null && value !== undefined && String(value).trim()) {
      params.append(key, String(value));
    }
  }
}

function appendScope(params, filters = {}) {
  appendArray(params, 'source_site', filters.sourceSites || filters.source_sites);
  appendArray(
    params,
    'source_classification_id',
    filters.sourceClassificationIds || filters.source_classification_ids,
  );
  appendArray(
    params,
    'source_subclassification_id',
    filters.sourceSubclassificationIds || filters.source_subclassification_ids,
  );
  appendArray(params, 'job_id', filters.jobIds || filters.job_ids);
  if (filters.postedDateFrom || filters.posted_date_from) {
    params.set('posted_date_from', filters.postedDateFrom || filters.posted_date_from);
  }
  if (filters.postedDateTo || filters.posted_date_to) {
    params.set('posted_date_to', filters.postedDateTo || filters.posted_date_to);
  }
  if (filters.pendingLimit || filters.pending_limit) {
    params.set('pending_limit', String(filters.pendingLimit || filters.pending_limit));
  }
  if (filters.reason) params.set('reason', filters.reason);
}

export function parseGovernanceHash(hash = window.location.hash) {
  const raw = String(hash || '').replace(/^#/, '');
  const [path, query = ''] = raw.split('?');
  const segments = path.split('/').filter(Boolean);
  const isGovernanceRoute = segments.length === 2 && segments[0] === 'job-intelligence';
  if (!isGovernanceRoute) {
    return { area: DEFAULT_AREA, itemId: null };
  }
  const area = AREA_KEYS.has(segments[1]) ? segments[1] : DEFAULT_AREA;
  const params = new URLSearchParams(query);
  const queueQuery = params.get('q');
  const cursor = params.get('cursor');
  const page = readPositiveInteger(params.get('page'));
  const scope = scopeFromParams(params);
  return {
    area,
    itemId: params.get('item'),
    ...(queueQuery ? { query: queueQuery } : {}),
    ...(cursor ? { cursor } : {}),
    ...(page ? { page } : {}),
    ...(scope ? { scope } : {}),
  };
}

export function governanceHash(area, itemId = null, filters = {}) {
  const safeArea = AREA_KEYS.has(area) ? area : DEFAULT_AREA;
  const params = new URLSearchParams();
  if (itemId) params.set('item', itemId);
  if (filters.query) params.set('q', filters.query);
  if (filters.cursor) params.set('cursor', filters.cursor);
  appendScope(params, filters);
  if (filters.page && Number(filters.page) > 1) {
    params.set('page', String(Math.floor(Number(filters.page))));
  }
  const query = params.toString();
  return `#job-intelligence/${safeArea}${query ? `?${query}` : ''}`;
}

export function navigateGovernance(area, itemId = null, filters = {}) {
  const nextHash = governanceHash(area, itemId, filters);
  if (window.location.hash === nextHash) {
    window.dispatchEvent(new HashChangeEvent('hashchange'));
    return;
  }
  window.location.hash = nextHash;
}
