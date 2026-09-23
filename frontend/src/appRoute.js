export const VALID_APP_VIEWS = new Set([
  'dashboard',
  'jobs',
  'add-job',
  'companies',
  'ai',
  'classification',
  'offertoday-keywords',
  'settings',
  'scheduler',
  'crawl-tasks',
]);

const JOB_ROUTE_FILTER_KEYS = {
  skillIds: 'skill_ids',
};
const MAX_JOB_ROUTE_IDS = 20;
const STABLE_CODE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const DEFAULT_CLASSIFICATION_TARGET = 'skill';
const VALID_CLASSIFICATION_TARGETS = new Set([DEFAULT_CLASSIFICATION_TARGET]);

function normalizeStableCodes(values) {
  const normalized = [];
  for (const rawValue of values || []) {
    const value = String(rawValue || '').trim();
    if (!STABLE_CODE_PATTERN.test(value) || normalized.includes(value)) {
      continue;
    }
    normalized.push(value);
    if (normalized.length === MAX_JOB_ROUTE_IDS) break;
  }
  return normalized;
}

export function resolveAppView(hash = window.location.hash) {
  const normalized = String(hash || '')
    .replace(/^#/, '')
    .trim()
    .toLowerCase();
  const topLevelView = normalized.split(/[/?]/, 1)[0];
  return VALID_APP_VIEWS.has(topLevelView) ? topLevelView : 'dashboard';
}

export function hashForView(view) {
  return `#${VALID_APP_VIEWS.has(view) ? view : 'dashboard'}`;
}

export function parseJobsRoute(hash = window.location.hash) {
  const rawHash = String(hash || '').replace(/^#/, '');
  const [rawView, rawQuery = ''] = rawHash.split('?', 2);
  if (rawView.trim().toLowerCase() !== 'jobs') {
    return { skillIds: [] };
  }

  const searchParams = new URLSearchParams(rawQuery);
  return {
    skillIds: normalizeStableCodes(
      searchParams.getAll(JOB_ROUTE_FILTER_KEYS.skillIds),
    ),
  };
}

export function hashForJobsRoute({
  skillIds = [],
} = {}) {
  const searchParams = new URLSearchParams();
  for (const code of normalizeStableCodes(skillIds)) {
    searchParams.append(JOB_ROUTE_FILTER_KEYS.skillIds, code);
  }
  const query = searchParams.toString();
  return query ? `#jobs?${query}` : '#jobs';
}

export function parseClassificationRoute(hash = window.location.hash) {
  const rawHash = String(hash || '').replace(/^#/, '');
  const [rawView, rawQuery = ''] = rawHash.split('?', 2);
  if (rawView.trim().toLowerCase() !== 'classification') {
    return { target: DEFAULT_CLASSIFICATION_TARGET };
  }

  const target = new URLSearchParams(rawQuery).get('target');
  return {
    target: VALID_CLASSIFICATION_TARGETS.has(target)
      ? target
      : DEFAULT_CLASSIFICATION_TARGET,
  };
}

export function hashForClassificationRoute(target = DEFAULT_CLASSIFICATION_TARGET) {
  const normalizedTarget = VALID_CLASSIFICATION_TARGETS.has(target)
    ? target
    : DEFAULT_CLASSIFICATION_TARGET;
  return `#classification?target=${encodeURIComponent(normalizedTarget)}`;
}
