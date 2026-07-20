export function buildCrawlTaskRoute(taskId, view = null) {
  const params = new URLSearchParams();
  if (taskId) params.set('task', taskId);
  if (view) params.set('view', view);
  const query = params.toString();
  return query ? `#crawl-tasks?${query}` : '#crawl-tasks';
}

export function parseCrawlTaskRoute(hash = window.location.hash) {
  const raw = String(hash || '').replace(/^#/, '');
  const [path, query = ''] = raw.split('?', 2);
  if (path !== 'crawl-tasks') return { kind: 'invalid', taskId: null, view: null };
  const params = new URLSearchParams(query);
  const taskId = params.get('task')?.trim() || null;
  return {
    kind: 'tasks',
    taskId: taskId && taskId.length <= 255 ? taskId : null,
    view: params.get('view') === 'events' ? 'events' : null,
  };
}
