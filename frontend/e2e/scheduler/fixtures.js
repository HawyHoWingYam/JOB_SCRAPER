export const scope = { source_site: 'jobsdb', mode: 'all', classification_ids: [] };
const now = '2026-09-23T08:00:00Z';
const action = (name, enabled = true) => ({ action: name, enabled, reason_code: enabled ? null : 'AUTOMATION_NOT_PAUSED' });
export const configuration = {
  name: 'Morning listings', description: '', cron_expression: '0 4 * * *', timezone: 'Asia/Hong_Kong', scope,
  listing_settings: { page_depth: 2, run_page_cap: 20, crawl_mode: 'headless' }, detail_settings: null,
};
export const automation = { snapshot: { automation_id: 'automation-1', lifecycle_state: 'paused', configuration }, created_at: now, updated_at: now, next_run_at: null };
const run = {
  crawl_job_id: 'task-1', source_site: 'jobsdb', crawl_phase: 'listing', crawl_mode: 'headless', trigger_kind: 'manual', status: 'running',
  queued_at: now, updated_at: now, authority: {},
  listing_workload: { query_target_count: 3, pages_requested: 2, run_page_cap: 20, page_depth: 2 },
};
export const board = {
  selected_source: 'jobsdb', source_summaries: ['jobsdb', 'ctgoodjobs', 'offertoday'].map(source_site => ({ source_site, state: source_site === 'jobsdb' ? 'running' : 'all_clear', attention_count: 0, active_run_count: source_site === 'jobsdb' ? 1 : 0, upcoming_count: source_site === 'jobsdb' ? 1 : 0 })),
  needs_attention: [], active_runs: [{ run, issue: null, actions: [action('view_task'), action('view_logs'), action('cancel')] }],
  upcoming: [{ automation_id: 'automation-1', lifecycle_state: 'active', name: 'Morning listings', source_site: 'jobsdb', crawl_phase: 'listing', crawl_mode: 'headless', authored_scope: scope,
    schedule: { cron_expression: '0 4 * * *', timezone: 'Asia/Hong_Kong', human_summary: 'Daily at 04:00 · Asia/Hong_Kong', next_run_at: '2026-09-24T20:00:00Z' },
    latest_outcome: { status: 'completed' }, resolved_scope_summary: { query_target_count: 3 }, actions: [action('edit'), action('run_now'), action('pause'), action('resume', false), action('archive')], created_at: now, updated_at: now }],
  archived_automations: [], all_clear: false, refreshed_at: now,
};
const readiness = { status: 'ready', checked_at: now, blocking_errors: [], capabilities: {} };
export async function interceptScheduler(page) {
  const requests = [];
  let saved = structuredClone(automation);
  let planCount = 0;
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    const body = req.postDataJSON();
    requests.push({ path, method: req.method(), body });
    let response;
    if (path === '/api/task-control-board') {
      const source = new URL(req.url()).searchParams.get('source_site');
      response = source === 'jobsdb' ? board : { ...board, selected_source: source, active_runs: [], upcoming: [], all_clear: true };
    }
    else if (path.startsWith('/api/source-classifications/')) {
      const source = path.split('/').at(-1);
      response = { source_site: source, classifications: [{ id: `${source}:1`, label: 'Information Technology', native_id: '1', active: true }] };
    } else if (path === '/api/automations/reviews') {
      const config = body.configuration;
      response = { input_fingerprint: JSON.stringify(config), authored_scope: config.scope, resolved_scope: { query_target_count: 3 },
        listing_workload: config.listing_settings ? { query_target_count: 3, ...config.listing_settings, estimated_max_pages: 3 * config.listing_settings.page_depth, system_run_page_cap: 5000 } : null,
        detail_preview: null, schedule_summary: { human_summary: 'Daily at 04:00 · Asia/Hong_Kong', next_run_at: '2026-09-24T20:00:00Z', timezone: config.timezone }, readiness, warnings: [] };
    } else if (path === '/api/automations' || path === '/api/automations/automation-1') {
      if (req.method() !== 'GET') saved = { ...saved, snapshot: { ...saved.snapshot, configuration: body.configuration, lifecycle_state: body.initial_state || saved.snapshot.lifecycle_state } };
      response = saved;
    } else if (path === '/api/dispatch-plans') {
      planCount += 1;
      response = { confirmation_token: `token-${planCount}`, plan: { plan_id: `plan-${planCount}`, state: 'prepared', plan_fingerprint: `fingerprint-${planCount}`, expires_at: '2099-01-01T00:00:00Z', detail_target_count: 0, readiness,
        content: { source_site: 'jobsdb', resolved_scope: { query_target_count: 3 }, listing_settings: body.listing_settings || configuration.listing_settings }, targets: [] } };
    } else if (/\/dispatch-plans\/[^/]+\/dispatch$/.test(path)) response = { plan: { plan_id: path.split('/')[3] }, run: { crawl_job_id: 'created-task', status: 'queued' } };
    else return route.fulfill({ status: 404, json: { detail: `Unmocked API: ${path}` } });
    await route.fulfill({ json: response });
  });
  return requests;
}
