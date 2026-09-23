const filterFields = {
  status: ['status', ['queued', 'dispatching', 'running', 'cancelling', 'manual_action_required', 'completed', 'failed', 'cancelled']],
  sourceSite: ['source', ['jobsdb', 'ctgoodjobs', 'offertoday']],
  crawlMode: ['mode', ['headless', 'headed']],
  timeRange: ['range', ['24h', '7d', '30d']],
};

export function buildCrawlTaskRoute(taskId, view = null, { filters = {}, page = 1 } = {}) {
  const params = new URLSearchParams();
  if (taskId) params.set('task', taskId);
  if (view) params.set('view', view);
  for (const [field, [key, allowed]] of Object.entries(filterFields)) {
    if (allowed.includes(filters[field])) params.set(key, filters[field]);
  }
  if (Number.isSafeInteger(page) && page > 1) params.set('page', String(page));
  const query = params.toString();
  return query ? `#crawl-tasks?${query}` : '#crawl-tasks';
}

export function parseCrawlTaskRoute(hash = window.location.hash) {
  const raw = String(hash || '').replace(/^#/, '');
  const [path, query = ''] = raw.split('?', 2);
  if (path !== 'crawl-tasks') return { kind: 'invalid', taskId: null, view: null };
  const params = new URLSearchParams(query);
  const taskId = params.get('task')?.trim() || null;
  const page = Number(params.get('page'));
  return {
    filters: Object.fromEntries(Object.entries(filterFields).map(([field, [key, allowed]]) => [field, allowed.includes(params.get(key)) ? params.get(key) : 'all'])),
    page: Number.isSafeInteger(page) && page > 0 ? page : 1,
    kind: 'tasks',
    taskId: taskId && taskId.length <= 255 ? taskId : null,
    view: params.get('view') === 'events' ? 'events' : null,
  };
}
