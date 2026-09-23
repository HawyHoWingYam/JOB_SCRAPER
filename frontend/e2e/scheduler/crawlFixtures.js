export const listingTask = {
  crawl_job_id: "listing-task",
  status: "running",
  trigger_type: "manual",
  source_site: "jobsdb",
  crawl_mode: "headless",
  crawl_phase: "listing",
  phase: 1,
  job_ids_collected: 87,
  raw_job_ids_collected: 96,
  listings_staged: 87,
  detail_target_rows: 87,
  current_page: 2,
  total_pages: 10,
  updated_at: "2026-07-15T12:00:00Z",
};

export function normalizedTaskDetail({
  id = "listing-task",
  status = "running",
  phase = "listing",
  sourceSite = "jobsdb",
  operatorState,
  actions,
} = {}) {
  return {
    run: {
      crawl_job_id: id,
      source_site: sourceSite,
      crawl_phase: phase,
      crawl_mode: sourceSite === "ctgoodjobs" ? "headed" : "headless",
      trigger_kind: "one_off",
      status,
      queued_at: "2026-07-15T12:00:00Z",
      started_at: "2026-07-15T12:01:00Z",
      completed_at: null,
      updated_at: "2026-07-15T12:02:00Z",
      authority: {
        authority_kind: "dispatch_plan",
        dispatch_plan_id: "10000000-0000-0000-0000-000000000001",
        dispatch_plan_fingerprint: "a".repeat(64),
        plan_state: "consumed",
        automation_id: null,
        authored_scope: {
          source_site: sourceSite,
          mode: "all",
          classification_ids: [],
        },
        resolved_scope: {
          source_site: sourceSite,
          authored_scope: {
            source_site: sourceSite,
            mode: "all",
            classification_ids: [],
          },
          selected_classifications: [],
          query_targets: [],
          query_target_count: 0,
        },
        readiness: { status: "ready", reasons: [] },
      },
      listing_workload: phase === "listing" ? {
        query_target_count: 2,
        page_depth: 5,
        estimated_max_pages: 10,
        run_page_cap: 10,
        pages_requested: 2,
      } : null,
      detail_snapshot: phase === "detail" ? {
        backlog_scope: { kind: "global" },
        cutoff_at: "2026-07-15T12:00:00Z",
        target_count: 4,
        fetched_count: 3,
        saved_count: 2,
        failed_count: 1,
        unavailable_count: 1,
        manual_action_count: 0,
        remaining_count: 1,
        future_eligible_count: 7,
        detail_run_cap: 5000,
      } : null,
      recovery_attempt: null,
    },
    persisted_status: status,
    operator_state: operatorState ?? (status === "cancelling" ? "cancellation_pending" : null),
    queued_at: "2026-07-15T12:00:00Z",
    started_at: "2026-07-15T12:01:00Z",
    completed_at: null,
    updated_at: "2026-07-15T12:02:00Z",
    detail_pacing: phase === "detail" ? {
      interval_min_seconds: 1,
      interval_max_seconds: 3,
      burst_size: 20,
      burst_pause_seconds: 30,
    } : null,
    issue: null,
    manual_action_guidance: null,
    recovery_attempt: null,
    actions: actions ?? (status === "running" ? [
      { action: "cancel", enabled: true, reason_code: null },
    ] : []),
  };
}

export async function interceptCrawl(page) {
  const requests = [];
  let status = 'running';
  let failEvents = true;
  await page.route(url => url.pathname.startsWith('/api/crawl-jobs/'), async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    requests.push({ path, method: request.method() });
    let result;
    if (path === '/api/crawl-jobs/tasks') {
      result = { items: [{ ...listingTask, crawl_job_id: 'task-1', status }], total: 21, page: Number(url.searchParams.get('page')), page_size: 10, refreshed_at: '2026-09-23T08:00:00Z' };
    } else if (path.endsWith('/events')) {
      if (failEvents) { return route.fulfill({ status: 503, json: { detail: 'Events temporarily unavailable' } }); }
      result = { events: [{ id: 1, sequence_no: 7, event_type: 'crawl.started', payload: { message: 'Collection started' }, created_at: '2026-09-23T08:00:00Z' }], total: 1 };
    } else if (path.endsWith('/cancel')) {
      status = 'cancelling'; result = { status };
    } else if (path.endsWith('/quality')) result = { enabled: false, maximum_limit: 20, latest: null };
    else if (path.endsWith('/incident-triage')) result = { enabled: false, latest: null };
    else if (/\/tasks\/[^/]+$/.test(path)) {
      result = normalizedTaskDetail({ id: decodeURIComponent(path.split('/').at(-1)), status,
        actions: status === 'cancelled' ? [] : [{ action: 'cancel', enabled: status === 'running', reason_code: status === 'cancelling' ? 'CANCELLATION_PENDING' : null }],
      });
    } else return route.fulfill({ status: 404, json: { detail: `Unmocked crawl API: ${path}` } });
    return route.fulfill({ json: result });
  });
  return { requests, acknowledgeCancellation: () => { status = 'cancelled'; }, allowEvents: () => { failEvents = false; } };
}
