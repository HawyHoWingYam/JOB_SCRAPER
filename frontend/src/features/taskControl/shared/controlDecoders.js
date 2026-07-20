export class ControlPayloadError extends Error {
  constructor(path, message) {
    super(`Invalid Crawl Control response at ${path}: ${message}`);
    this.name = 'ControlPayloadError';
    this.path = path;
  }
}

function object(value, path) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new ControlPayloadError(path, 'expected object');
  }
  return value;
}

function string(value, path) {
  if (typeof value !== 'string' || !value.trim()) {
    throw new ControlPayloadError(path, 'expected non-empty string');
  }
  return value;
}

function integer(value, path, { minimum = 0 } = {}) {
  if (!Number.isInteger(value) || value < minimum) {
    throw new ControlPayloadError(path, `expected integer >= ${minimum}`);
  }
  return value;
}

function list(value, path) {
  if (!Array.isArray(value)) throw new ControlPayloadError(path, 'expected array');
  return value;
}

function decodeReadiness(value, path) {
  const row = object(value, path);
  return {
    status: string(row.status, `${path}.status`),
    checkedAt: string(row.checked_at, `${path}.checked_at`),
    blockingErrors: list(row.blocking_errors || [], `${path}.blocking_errors`).map((item, index) => {
      const error = object(item, `${path}.blocking_errors[${index}]`);
      return {
        code: string(error.code, `${path}.blocking_errors[${index}].code`),
        message: string(error.message, `${path}.blocking_errors[${index}].message`),
        context: object(error.context || {}, `${path}.blocking_errors[${index}].context`),
      };
    }),
    capabilities: object(row.capabilities || {}, `${path}.capabilities`),
  };
}

export function decodeAutomation(value, path = '$') {
  const row = object(value, path);
  const snapshot = object(row.snapshot, `${path}.snapshot`);
  const configuration = object(snapshot.configuration, `${path}.snapshot.configuration`);
  const scope = object(configuration.scope, `${path}.snapshot.configuration.scope`);
  return {
    id: string(snapshot.automation_id, `${path}.snapshot.automation_id`),
    revision: integer(snapshot.revision, `${path}.snapshot.revision`, { minimum: 1 }),
    lifecycleState: string(snapshot.lifecycle_state, `${path}.snapshot.lifecycle_state`),
    configuration,
    sourceSite: string(scope.source_site, `${path}.snapshot.configuration.scope.source_site`),
    createdAt: string(row.created_at, `${path}.created_at`),
    updatedAt: string(row.updated_at, `${path}.updated_at`),
    nextRunAt: row.next_run_at == null ? null : string(row.next_run_at, `${path}.next_run_at`),
  };
}

export function decodeAutomationReview(value) {
  const row = object(value, '$');
  return {
    inputFingerprint: string(row.input_fingerprint, '$.input_fingerprint'),
    automationId: row.automation_id == null ? null : string(row.automation_id, '$.automation_id'),
    expectedRevision: row.expected_revision == null ? null : integer(row.expected_revision, '$.expected_revision', { minimum: 1 }),
    catalogRevisionId: string(row.catalog_revision_id, '$.catalog_revision_id'),
    authoredScope: object(row.authored_scope, '$.authored_scope'),
    resolvedScope: object(row.resolved_scope, '$.resolved_scope'),
    listingWorkload: row.listing_workload == null ? null : object(row.listing_workload, '$.listing_workload'),
    detailPreview: row.detail_preview == null ? null : object(row.detail_preview, '$.detail_preview'),
    scheduleSummary: object(row.schedule_summary, '$.schedule_summary'),
    readiness: decodeReadiness(row.readiness, '$.readiness'),
    warnings: list(row.warnings || [], '$.warnings'),
    before: row.before == null ? null : decodeAutomation(row.before, '$.before'),
  };
}

export function decodeDispatchPreparation(value) {
  const row = object(value, '$');
  const plan = object(row.plan, '$.plan');
  const content = object(plan.content, '$.plan.content');
  return {
    planId: string(plan.plan_id, '$.plan.plan_id'),
    state: string(plan.state, '$.plan.state'),
    planFingerprint: string(plan.plan_fingerprint, '$.plan.plan_fingerprint'),
    confirmationToken: row.confirmation_token == null ? null : string(row.confirmation_token, '$.confirmation_token'),
    expiresAt: string(plan.expires_at, '$.plan.expires_at'),
    detailTargetCount: integer(plan.detail_target_count, '$.plan.detail_target_count'),
    content,
    readiness: decodeReadiness(plan.readiness, '$.plan.readiness'),
    targets: list(plan.targets || [], '$.plan.targets'),
  };
}

export function decodeDispatchResult(value) {
  const row = object(value, '$');
  const plan = object(row.plan, '$.plan');
  const run = object(row.run, '$.run');
  return {
    planId: string(plan.plan_id, '$.plan.plan_id'),
    crawlJobId: string(run.crawl_job_id, '$.run.crawl_job_id'),
    status: string(run.status, '$.run.status'),
    run,
  };
}

export function decodeCrawlJob(value) {
  const row = object(value, '$');
  return {
    id: string(row.id || row.crawl_job_id, '$.id'),
    status: string(row.status, '$.status'),
    progress: object(row.progress || {}, '$.progress'),
  };
}
