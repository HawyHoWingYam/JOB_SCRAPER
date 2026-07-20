export const VALID_APP_VIEWS = new Set([
  'dashboard',
  'jobs',
  'add-job',
  'companies',
  'job-intelligence',
  'source-catalogs',
  'ai',
  'settings',
  'scheduler',
  'crawl-tasks',
]);

export function resolveAppView(hash = window.location.hash) {
  const normalized = String(hash || '')
    .replace(/^#/, '')
    .trim()
    .toLowerCase();
  const topLevelView = normalized.split(/[/?]/, 1)[0];
  return VALID_APP_VIEWS.has(topLevelView) ? topLevelView : 'dashboard';
}

export function hashForView(view) {
  if (view === 'job-intelligence') {
    return '#job-intelligence/job-taxonomy';
  }
  return `#${VALID_APP_VIEWS.has(view) ? view : 'dashboard'}`;
}
