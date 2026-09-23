export async function interceptAI(page) {
  const requests = [];
  const failed = { id: 'older-failed', source_type: 'manual_pending', status: 'completed_with_failures', total_items: 4, completed_items: 2, failed_items: 2, pending_items: 0, created_at: '2026-09-20T08:00:00Z' };
  const waiting = { id: 'waiting-crawl', source_type: 'post_scrape', status: 'waiting', total_items: 2, pending_items: 2, failed_items: 0, created_at: '2026-09-21T08:00:00Z', trigger_crawl_job_id: 'task-1', pending_gate_reason: 'waiting_for_crawl_completion', pending_gate_crawl_job_status: 'running' };
  let runs = [waiting, failed];
  await page.route(url => url.pathname.startsWith('/api/ai/'), async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const body = request.postDataJSON();
    requests.push({ path, method: request.method(), body });
    const active = runs.find(run => ['pending', 'running', 'stopping'].includes(run.status));
    let result;
    if (path.endsWith('/overview')) result = { pending_jobs: 120, ai_eligible_jobs: 150, active_runs: active ? 1 : 0, failed_jobs: 2 };
    else if (path.endsWith('/filter-options')) result = { sources: [{ source_site: 'jobsdb', classifications: [] }, { source_site: 'manual', classifications: [] }] };
    else if (path.endsWith('/preview')) result = { matching_pending_count: 120, selected_item_count: body.limit, effective_item_count: Math.max(body.limit - 2, 0), excluded_item_count: 2, excluded_items: [{ source_classification_id: 'jobsdb:1', count: 2, reason: 'Missing source evidence' }] };
    else if (path === '/api/ai/runs' && request.method() === 'POST') {
      result = { id: 'created-ai', source_type: 'manual_pending', status: 'running', total_items: 4, pending_items: 3, completed_items: 0, failed_items: 0, excluded_items: 1, created_at: '2026-09-23T08:00:00Z' };
      runs = [result, ...runs];
    } else if (path.endsWith('/retry-failed')) {
      result = { ...failed, id: 'retry-ai', status: 'pending', total_items: 2, pending_items: 2, completed_items: 0, failed_items: 0, created_at: '2026-09-23T09:00:00Z' };
      runs = [result, ...runs];
    } else if (path.endsWith('/stop')) {
      const run = runs.find(item => item.id === path.split('/')[4]);
      result = { ...run, status: 'cancelled', pending_items: 0, cancelled_items: run.pending_items };
      runs = runs.map(item => item.id === result.id ? result : item);
    } else if (path.endsWith('/items')) result = { items: url.searchParams.get('status') === 'failed' && path.includes('older-failed') ? [{ id: 'failed-item', job_id: 'job-7', status: 'failed', error_message: 'Provider timed out', attempt_count: 2 }] : [] };
    else if (path === '/api/ai/runs') result = { runs: url.searchParams.has('monitor') ? (active ? [active, failed] : [failed]) : runs };
    else if (path.startsWith('/api/ai/runs/')) result = runs.find(item => item.id === path.split('/').at(-1));
    if (!result) return route.fulfill({ status: 404, json: { detail: 'Run not found' } });
    return route.fulfill({ json: result });
  });
  return requests;
}
