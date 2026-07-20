export class BoardPayloadError extends Error {
  constructor(path, message) {
    super(`Invalid Task Control Board response at ${path}: ${message}`);
    this.name = 'BoardPayloadError';
    this.path = path;
  }
}

const object = (value, path) => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new BoardPayloadError(path, 'expected object');
  return value;
};
const array = (value, path) => {
  if (!Array.isArray(value)) throw new BoardPayloadError(path, 'expected array');
  return value;
};
const string = (value, path) => {
  if (typeof value !== 'string' || !value.trim()) throw new BoardPayloadError(path, 'expected non-empty string');
  return value;
};
const integer = (value, path) => {
  if (!Number.isInteger(value) || value < 0) throw new BoardPayloadError(path, 'expected non-negative integer');
  return value;
};

function decodeAction(value, path) {
  const row = object(value, path);
  return {
    action: string(row.action, `${path}.action`),
    enabled: Boolean(row.enabled),
    reasonCode: row.reason_code == null ? null : string(row.reason_code, `${path}.reason_code`),
  };
}

function decodeHealth(value, path) {
  const row = object(value, path);
  return {
    sourceSite: string(row.source_site, `${path}.source_site`),
    state: string(row.state, `${path}.state`),
    revisionId: row.revision_id == null ? null : string(row.revision_id, `${path}.revision_id`),
    sequence: row.sequence == null ? null : integer(row.sequence, `${path}.sequence`),
    fingerprint: row.fingerprint == null ? null : string(row.fingerprint, `${path}.fingerprint`),
    publishedAt: row.published_at || null,
  };
}

function decodeIssue(value, path) {
  if (value == null) return null;
  const row = object(value, path);
  return {
    issueClass: string(row.issue_class, `${path}.issue_class`),
    code: row.code || null,
    stage: row.stage || null,
    summary: string(row.summary, `${path}.summary`),
  };
}

function decodeRun(value, path) {
  const row = object(value, path);
  return {
    id: string(row.crawl_job_id, `${path}.crawl_job_id`),
    sourceSite: string(row.source_site, `${path}.source_site`),
    phase: string(row.crawl_phase, `${path}.crawl_phase`),
    mode: string(row.crawl_mode, `${path}.crawl_mode`),
    triggerKind: string(row.trigger_kind, `${path}.trigger_kind`),
    status: string(row.status, `${path}.status`),
    queuedAt: row.queued_at,
    startedAt: row.started_at || null,
    completedAt: row.completed_at || null,
    updatedAt: row.updated_at,
    authority: object(row.authority, `${path}.authority`),
    listingWorkload: row.listing_workload == null ? null : object(row.listing_workload, `${path}.listing_workload`),
    detailSnapshot: row.detail_snapshot == null ? null : object(row.detail_snapshot, `${path}.detail_snapshot`),
    recoveryAttempt: row.recovery_attempt == null ? null : object(row.recovery_attempt, `${path}.recovery_attempt`),
  };
}

function decodeAutomation(value, path) {
  const row = object(value, path);
  const schedule = object(row.schedule, `${path}.schedule`);
  return {
    id: string(row.automation_id, `${path}.automation_id`),
    revision: integer(row.revision, `${path}.revision`),
    lifecycleState: string(row.lifecycle_state, `${path}.lifecycle_state`),
    name: string(row.name, `${path}.name`),
    sourceSite: string(row.source_site, `${path}.source_site`),
    phase: string(row.crawl_phase, `${path}.crawl_phase`),
    mode: string(row.crawl_mode, `${path}.crawl_mode`),
    authoredScope: object(row.authored_scope, `${path}.authored_scope`),
    schedule: {
      cronExpression: string(schedule.cron_expression, `${path}.schedule.cron_expression`),
      timezone: string(schedule.timezone, `${path}.schedule.timezone`),
      humanSummary: string(schedule.human_summary, `${path}.schedule.human_summary`),
      nextRunAt: schedule.next_run_at || null,
    },
    latestOutcome: row.latest_outcome == null ? null : object(row.latest_outcome, `${path}.latest_outcome`),
    catalogHealth: decodeHealth(row.catalog_health, `${path}.catalog_health`),
    resolvedScopeSummary: row.resolved_scope_summary == null ? null : object(row.resolved_scope_summary, `${path}.resolved_scope_summary`),
    currentRun: row.current_run == null ? null : decodeRun(row.current_run, `${path}.current_run`),
    scopeReviewReason: row.scope_review_reason || null,
    actions: array(row.actions, `${path}.actions`).map((item, index) => decodeAction(item, `${path}.actions[${index}]`)),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    lastRunAt: row.last_run_at || null,
  };
}

export function decodeBoard(value) {
  const row = object(value, '$');
  if (row.version !== 2) throw new BoardPayloadError('$.version', 'expected 2');
  return {
    selectedSource: string(row.selected_source, '$.selected_source'),
    sourceSummaries: array(row.source_summaries, '$.source_summaries').map((item, index) => {
      const summary = object(item, `$.source_summaries[${index}]`);
      return {
        sourceSite: string(summary.source_site, `$.source_summaries[${index}].source_site`),
        state: string(summary.state, `$.source_summaries[${index}].state`),
        attentionCount: integer(summary.attention_count, `$.source_summaries[${index}].attention_count`),
        activeRunCount: integer(summary.active_run_count, `$.source_summaries[${index}].active_run_count`),
        upcomingCount: integer(summary.upcoming_count, `$.source_summaries[${index}].upcoming_count`),
        catalogHealth: decodeHealth(summary.catalog_health, `$.source_summaries[${index}].catalog_health`),
      };
    }),
    needsAttention: array(row.needs_attention, '$.needs_attention').map((item, index) => {
      const attention = object(item, `$.needs_attention[${index}]`);
      return {
        id: string(attention.item_id, `$.needs_attention[${index}].item_id`),
        kind: string(attention.kind, `$.needs_attention[${index}].kind`),
        priority: integer(attention.priority, `$.needs_attention[${index}].priority`),
        sourceSite: string(attention.source_site, `$.needs_attention[${index}].source_site`),
        code: string(attention.code, `$.needs_attention[${index}].code`),
        title: string(attention.title, `$.needs_attention[${index}].title`),
        summary: string(attention.summary, `$.needs_attention[${index}].summary`),
        entityKind: string(attention.entity_kind, `$.needs_attention[${index}].entity_kind`),
        entityId: string(attention.entity_id, `$.needs_attention[${index}].entity_id`),
        primaryAction: decodeAction(attention.primary_action, `$.needs_attention[${index}].primary_action`),
        secondaryActions: array(attention.secondary_actions, `$.needs_attention[${index}].secondary_actions`).map((action, actionIndex) => decodeAction(action, `$.needs_attention[${index}].secondary_actions[${actionIndex}]`)),
      };
    }),
    activeRuns: array(row.active_runs, '$.active_runs').map((item, index) => {
      const active = object(item, `$.active_runs[${index}]`);
      return {
        run: decodeRun(active.run, `$.active_runs[${index}].run`),
        issue: decodeIssue(active.issue, `$.active_runs[${index}].issue`),
        manualActionGuidance: active.manual_action_guidance || null,
        actions: array(active.actions, `$.active_runs[${index}].actions`).map((action, actionIndex) => decodeAction(action, `$.active_runs[${index}].actions[${actionIndex}]`)),
      };
    }),
    upcoming: array(row.upcoming, '$.upcoming').map((item, index) => decodeAutomation(item, `$.upcoming[${index}]`)),
    archivedAutomations: array(row.archived_automations, '$.archived_automations').map((item, index) => decodeAutomation(item, `$.archived_automations[${index}]`)),
    allClear: Boolean(row.all_clear),
    refreshedAt: row.refreshed_at,
  };
}

export function decodeDeleteReview(value) {
  const row = object(value, '$');
  return {
    reviewToken: string(row.review_token, '$.review_token'),
    expiresAt: row.expires_at,
    impact: object(row.impact, '$.impact'),
  };
}

export function decodeTaskDetail(value) {
  const row = object(value, '$');
  return {
    run: decodeRun(row.run, '$.run'),
    persistedStatus: string(row.persisted_status, '$.persisted_status'),
    operatorState: row.operator_state || null,
    queuedAt: row.queued_at,
    startedAt: row.started_at || null,
    completedAt: row.completed_at || null,
    updatedAt: row.updated_at,
    detailPacing: row.detail_pacing == null ? null : object(row.detail_pacing, '$.detail_pacing'),
    issue: decodeIssue(row.issue, '$.issue'),
    manualActionGuidance: row.manual_action_guidance || null,
    recoveryAttempt: row.recovery_attempt || null,
    actions: array(row.actions, '$.actions').map((item, index) => decodeAction(item, `$.actions[${index}]`)),
  };
}
