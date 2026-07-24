function positiveInteger(value, label) {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1) throw new Error(`${label} must be a positive integer`);
  return parsed;
}

export function wizardDraftFingerprint(draft) {
  return JSON.stringify({
    source_site: draft.source_site,
    intent: draft.intent,
    scope: draft.scope,
    execution: draft.execution,
    schedule: draft.schedule,
    automation_id: draft.automation_id,
    expected_revision: draft.expected_revision,
  });
}

export function buildAuthoredScope(draft, published) {
  const catalogSource = published?.catalog?.sourceSite;
  const revision = published?.revision;
  if (!revision || catalogSource !== draft.source_site || revision.sourceSite !== draft.source_site) {
    throw new Error('Route, draft, Catalog, and command Source must agree');
  }
  if (draft.scope?.mode === 'all') {
    if (!published.catalog.capabilities.supportsAllScope) throw new Error('This Source does not support explicit all scope');
    return { version: 1, source_site: draft.source_site, reviewed_catalog_revision_id: revision.id, mode: 'all', rules: [] };
  }
  const rules = (draft.scope?.rules || []).filter((rule) => rule.classification_id?.startsWith(`${draft.source_site}:`) && ['exact', 'subtree'].includes(rule.kind));
  if (!rules.length) throw new Error('Choose explicit all scope or at least one Exact/Subtree rule');
  const deduped = [...new Map(rules.map((rule) => [`${rule.kind}:${rule.classification_id}`, rule])).values()];
  return { version: 1, source_site: draft.source_site, reviewed_catalog_revision_id: revision.id, mode: 'rules', rules: deduped.map(({ kind, classification_id }) => ({ kind, classification_id })) };
}

function listingSettings(draft) {
  return {
    version: 1,
    crawl_mode: draft.execution.crawl_mode || 'headless',
    page_depth: positiveInteger(draft.execution.page_depth, 'Page Depth'),
    run_page_cap: positiveInteger(draft.execution.run_page_cap, 'Run Page Cap'),
  };
}

function detailSettings(draft, scope) {
  const kind = draft.execution.backlog_kind;
  let backlogScope;
  if (kind === 'source_backlog') backlogScope = { kind: 'source_backlog' };
  else if (kind === 'listing_batch') {
    if (!draft.execution.source_listing_crawl_job_id) throw new Error('Choose an explicit listing batch');
    backlogScope = { kind: 'listing_batch', source_listing_crawl_job_id: draft.execution.source_listing_crawl_job_id };
  } else if (kind === 'crawl_scope') backlogScope = { kind: 'crawl_scope', scope };
  else throw new Error('Choose a detail backlog population');
  if (kind !== 'crawl_scope' && scope.mode !== 'all') throw new Error('Source backlog and listing batch require explicit all-source context');
  const limit = draft.execution.limit_kind === 'entire_snapshot'
    ? { kind: 'entire_snapshot' }
    : { kind: 'stop_after', detail_run_cap: positiveInteger(draft.execution.detail_run_cap, 'Detail Run Cap') };
  return {
    version: 1,
    crawl_mode: draft.execution.crawl_mode || 'headless',
    backlog_scope: backlogScope,
    limit,
    backlog_snapshot: null,
  };
}

export function buildAutomationConfiguration(draft, published) {
  if (!draft.intent) throw new Error('Choose Discover listings or Enrich job details');
  const scope = buildAuthoredScope(draft, published);
  const name = String(draft.schedule.name || '').trim();
  if (!name) throw new Error('Automation name is required');
  return {
    version: 1,
    name,
    description: String(draft.schedule.description || '').trim() || null,
    cron_expression: String(draft.schedule.cron_expression || '').trim(),
    timezone: String(draft.schedule.timezone || '').trim(),
    scope,
    listing_settings: draft.intent === 'listing' ? listingSettings(draft) : null,
    detail_settings: draft.intent === 'detail' ? detailSettings(draft, scope) : null,
  };
}

export function buildAutomationReviewRequest(draft, published) {
  return {
    configuration: buildAutomationConfiguration(draft, published),
    ...(draft.mode === 'edit' ? { automation_id: draft.automation_id, expected_revision: draft.expected_revision } : {}),
  };
}

export function buildAutomationMutation(draft, published, review) {
  const configuration = buildAutomationConfiguration(draft, published);
  return draft.mode === 'edit'
    ? { expected_revision: draft.expected_revision, configuration, review_fingerprint: review.inputFingerprint }
    : { configuration, review_fingerprint: review.inputFingerprint, initial_state: draft.schedule.initial_state || 'paused' };
}

export function buildOneOffRun(draft, published) {
  const scope = buildAuthoredScope(draft, published);
  return {
    version: 1,
    kind: 'one_off',
    scope,
    listing_settings: draft.intent === 'listing' ? listingSettings(draft) : null,
    detail_settings: draft.intent === 'detail' ? detailSettings(draft, scope) : null,
  };
}

export function draftFromAutomation(route, automation) {
  const config = automation.configuration;
  const listing = config.listing_settings;
  const detail = config.detail_settings;
  const scope = config.scope;
  return {
    version: 1,
    updated_at: new Date().toISOString(),
    flow: route.flow,
    mode: route.mode,
    automation_id: automation.id,
    expected_revision: automation.revision,
    source_site: automation.sourceSite,
    step: route.flow === 'run_now' ? 'review' : 'intent',
    run_choice: route.flow === 'run_now' ? 'saved' : null,
    intent: listing ? 'listing' : 'detail',
    scope: { mode: scope.mode, rules: scope.rules || [] },
    execution: listing ? {
      page_depth: listing.page_depth,
      run_page_cap: listing.run_page_cap,
      crawl_mode: listing.crawl_mode,
    } : {
      backlog_kind: detail.backlog_scope.kind,
      source_listing_crawl_job_id: detail.backlog_scope.source_listing_crawl_job_id || '',
      limit_kind: detail.limit.kind,
      detail_run_cap: detail.limit.detail_run_cap || 100,
      crawl_mode: detail.crawl_mode,
    },
    schedule: {
      name: config.name,
      description: config.description || '',
      cron_expression: config.cron_expression,
      timezone: config.timezone,
      initial_state: automation.lifecycleState === 'active' ? 'active' : 'paused',
    },
  };
}

export function pairedDetailDraft(draft) {
  return {
    ...draft,
    mode: 'create',
    automation_id: null,
    expected_revision: null,
    step: 'intent',
    intent: 'detail',
    execution: {
      backlog_kind: 'crawl_scope',
      limit_kind: 'stop_after',
      detail_run_cap: 100,
      crawl_mode: draft.execution.crawl_mode || 'headless',
    },
    schedule: { ...draft.schedule, name: `${draft.schedule.name} details`, initial_state: 'paused' },
  };
}
