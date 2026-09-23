import React, { useState } from 'react';
import { formatControlDateTime } from '../../features/taskControl/shared/controlTime';
import { buildControlRoute } from '../../features/taskControl/shared/controlRoute';
import ManualActionRecoveryPanel from './ManualActionRecoveryPanel';

function value(value) {
  return value == null || value === '' ? 'Not recorded' : String(value);
}

function ScopeDetails({ authority }) {
  const authored = authority.authored_scope;
  const resolved = authority.resolved_scope;
  return <dl className="crawl-tasks-detail-grid"><div><dt>Dispatch Plan</dt><dd>{authority.dispatch_plan_id}</dd></div><div><dt>Plan state</dt><dd>{authority.plan_state}</dd></div><div><dt>Plan fingerprint</dt><dd><code>{authority.dispatch_plan_fingerprint}</code></dd></div><div><dt>Automation</dt><dd>{authority.automation_id || 'One-off run'}</dd></div><div><dt>Authored Scope</dt><dd>{authored?.mode === 'all' ? 'All major categories' : `${authored?.classification_ids?.length || 0} selected major categories`}</dd></div><div><dt>Resolved Scope</dt><dd>{resolved ? `${resolved.selected_classifications?.length || 0} classifications · ${resolved.query_target_count} Query Targets` : 'Not recorded'}</dd></div><div><dt>Readiness</dt><dd>{authority.readiness?.status || 'Not recorded'}</dd></div></dl>;
}

function Workload({ run }) {
  if (run.phase === 'listing') {
    const listing = run.listingWorkload;
    return <section className="crawl-tasks-detail-block"><h3>Listing workload</h3><dl className="crawl-tasks-detail-grid"><div><dt>Query Targets</dt><dd>{listing.query_target_count}</dd></div><div><dt>Page Depth</dt><dd>{listing.page_depth}</dd></div><div><dt>Estimated maximum</dt><dd>{listing.estimated_max_pages} pages</dd></div><div><dt>Run Page Cap</dt><dd>{listing.run_page_cap}</dd></div><div><dt>Pages requested</dt><dd>{listing.pages_requested} / {listing.estimated_max_pages}</dd></div></dl></section>;
  }
  const detail = run.detailSnapshot;
  return <section className="crawl-tasks-detail-block"><h3>Finite detail snapshot</h3><dl className="crawl-tasks-detail-grid"><div><dt>Backlog scope</dt><dd>{detail.backlog_scope?.kind}</dd></div><div><dt>Cutoff</dt><dd>{detail.cutoff_at ? formatControlDateTime(detail.cutoff_at) : 'Not recorded'}</dd></div><div><dt>Targets</dt><dd>{detail.target_count}</dd></div><div><dt>Fetched / saved</dt><dd>{detail.fetched_count} / {detail.saved_count}</dd></div><div><dt>Failed / unavailable</dt><dd>{detail.failed_count} / {detail.unavailable_count}</dd></div><div><dt>Manual action</dt><dd>{detail.manual_action_count}</dd></div><div><dt>Remaining in snapshot</dt><dd>{detail.remaining_count}</dd></div><div><dt>Eligible for later run</dt><dd>{detail.future_eligible_count}</dd></div><div><dt>Complete-run cap</dt><dd>{detail.detail_run_cap}</dd></div></dl></section>;
}

function ListingRecovery({ recovery, run, onContinue }) {
  if (
    run?.status !== 'completed' ||
    run?.phase !== 'listing' ||
    !recovery?.listingPartial
  ) return null;
  const cappedCount = recovery.cappedQueryTargetCount;
  const targetCount = recovery.queryTargetCount;
  return <section className="crawl-tasks-detail-block crawl-tasks-listing-partial" role="status"><h3>Completed with partial listing</h3><p><strong>{cappedCount} of {targetCount} query targets</strong> reached the page-depth limit ({recovery.pageDepth} pages) before the source was exhausted.</p><p>{recovery.pagesRequested} pages were requested for this run. The run page cap is separate from the per-target page-depth limit.</p>{recovery.continuationSupported ? <button type="button" className="crawl-tasks-continue-button" onClick={onContinue}>Continue capped query targets</button> : <p className="crawl-tasks-detail-text">The capped target identities were not recorded for this historical run. Start a new scoped listing run to continue it.</p>}</section>;
}

function CrawlQualityAdvisory({ quality, pending, error, onPreview, onEvaluate }) {
  const [limit, setLimit] = useState(20);
  const preview = quality?.preview;
  const latest = quality?.latest;
  const maximum = Number(quality?.maximum_limit || 20);
  const boundedLimit = Math.max(1, Math.min(maximum, limit));
  return <section className="crawl-tasks-detail-block" aria-labelledby="crawl-quality-heading"><h3 id="crawl-quality-heading">Crawl content quality advisory</h3><p>Jev only reviews successful content. It does not retry, repair, resume, cancel, or change this Crawl Job.</p><label><span>Bounded listing limit</span><input aria-label="Crawl quality listing limit" type="number" min="1" max={maximum} value={boundedLimit} onChange={(event) => setLimit(Math.max(1, Math.min(maximum, Number(event.target.value) || 1)))} /></label><div className="board-actions"><button type="button" disabled={pending !== null} onClick={() => onPreview(boundedLimit)}>Preview candidates</button><button type="button" disabled={!quality?.enabled || pending !== null || preview?.selected_count === 0} onClick={() => onEvaluate(boundedLimit)}>Evaluate with Jev</button></div>{!quality?.enabled && <p className="crawl-tasks-detail-text">Crawl quality advisory is disabled in Settings.</p>}{preview && <p role="status">Free database preview: {preview.selected_count} selected / {preview.eligible_count} eligible · {preview.deterministic_excluded_count} deterministic exclusions · {preview.insufficient_excluded_count} insufficient. No Jev request was sent.</p>}{error && <p role="alert" className="crawl-tasks-banner crawl-tasks-banner-error">{error}</p>}{latest && <div><p><strong>Latest:</strong> {latest.status} · {latest.observations?.length || 0} observations</p>{(latest.observations || []).map((observation) => <article key={observation.id} className="crawl-tasks-detail-text"><strong>{observation.source_identity}</strong> · {observation.quality || observation.status}{observation.problem_kind && ` · ${observation.problem_kind}`}{observation.request_id && ` · receipt ${observation.request_id}`}{observation.cost_usd != null && ` · cost USD ${Number(observation.cost_usd).toFixed(5)}`}</article>)}</div>}</section>;
}

export default function CrawlTaskDetails({ detail, loading, error, actionState, onAction, onOpenEvents, onContinueCappedListing, onRecoveryChanged, crawlQuality, crawlQualityPending, crawlQualityError, onCrawlQualityPreview, onCrawlQualityEvaluate }) {
  if (loading && !detail) return <div className="crawl-tasks-empty" role="status">Loading normalized Task Details…</div>;
  if (error && !detail) return <div className="crawl-tasks-banner crawl-tasks-banner-error" role="alert">{error}</div>;
  if (!detail) return <div className="crawl-tasks-empty">Select a task to inspect normalized details.</div>;
  const { run } = detail;
  const guidance = detail.manualActionGuidance;
  const showBrowserRecovery = Boolean(
    run.status === 'manual_action_required'
      && ['jobsdb', 'ctgoodjobs'].includes(run.sourceSite)
      && guidance
      && (guidance.resume_supported || guidance.reset_supported),
  );
  const recoveryTask = showBrowserRecovery ? {
    crawl_job_id: run.id,
    source_site: run.sourceSite,
    manual_action: {
      source_site: guidance.source_site,
      action_type: guidance.action_type,
      classification: guidance.classification,
      stage: guidance.stage,
      code: guidance.code,
      message: guidance.message,
      instructions: guidance.instructions,
      resume_supported: guidance.resume_supported,
      reuse_open_browser_supported: guidance.resume_strategies?.includes('reuse_open_browser') === true,
      reset_supported: guidance.reset_supported === true,
      reset_reason: guidance.reset_reason || null,
      profile_scope: guidance.profile_scope || null,
    },
  } : null;
  const statusLabel = run.status === 'completed' && run.phase === 'listing' && detail.listingRecovery?.listingPartial
    ? 'Completed with partial listing'
    : detail.operatorState === 'completed_with_downstream_backlog'
      ? 'Completed with downstream backlog'
      : detail.operatorState === 'stale_downstream_backlog'
        ? 'Terminal with downstream backlog'
        : run.status;
  const hasDownstreamBacklog = detail.operatorState === 'completed_with_downstream_backlog'
    || detail.operatorState === 'stale_downstream_backlog';
  const remainingCount = Number(run.detailSnapshot?.remaining_count || 0);
  return <><div className="crawl-tasks-detail-header"><div><h2>Task Details</h2><div className="crawl-task-id">{run.id}</div></div><button type="button" className="crawl-tasks-link-button" onClick={onOpenEvents}>Audit events</button></div>{error && <div className="crawl-tasks-banner crawl-tasks-banner-warning" role="alert">Refresh failed; prior Task Details remain visible. {error}</div>}{run.status === 'cancelling' && <div className="crawl-tasks-banner crawl-tasks-banner-warning">Cancellation requested. Waiting for backend <code>cancelled</code> acknowledgement.</div>}{actionState.error && <div className="crawl-tasks-banner crawl-tasks-banner-error">{actionState.error}</div>}{actionState.notice && <div className="crawl-tasks-banner crawl-tasks-banner-success">{actionState.notice}</div>}{hasDownstreamBacklog && <section className="crawl-tasks-listing-partial crawl-tasks-downstream-backlog" role="status" data-testid="crawl-task-downstream-backlog"><h3>{statusLabel}</h3><p>This execution segment is terminal, but <strong>{remainingCount.toLocaleString()} detail targets remain in the frozen snapshot</strong>. They are not failed and are separate from work eligible for a later run.</p><a href={buildControlRoute({ sourceSite: run.sourceSite })}>Open Scheduler for this source</a><p>A new run requires a fresh scope review; this task stays terminal.</p></section>}<dl className="crawl-tasks-detail-grid"><div><dt>Status</dt><dd>{statusLabel}</dd></div><div><dt>Source</dt><dd>{run.sourceSite}</dd></div><div><dt>Phase / mode</dt><dd>{run.phase} · {run.mode}</dd></div><div><dt>Trigger</dt><dd>{run.triggerKind}</dd></div><div><dt>Queued</dt><dd>{formatControlDateTime(detail.queuedAt)}</dd></div><div><dt>Started</dt><dd>{detail.startedAt ? formatControlDateTime(detail.startedAt) : 'Not started'}</dd></div><div><dt>Completed</dt><dd>{detail.completedAt ? formatControlDateTime(detail.completedAt) : 'Not completed'}</dd></div><div><dt>Updated</dt><dd>{formatControlDateTime(detail.updatedAt)}</dd></div></dl><Workload run={run} /><ListingRecovery recovery={detail.listingRecovery} run={run} onContinue={onContinueCappedListing} />{run.phase === 'detail' && <section className="crawl-tasks-detail-block"><h3>Immutable detail pacing</h3><p>{detail.detailPacing ? `${value(detail.detailPacing.interval_min_seconds)}–${value(detail.detailPacing.interval_max_seconds)} seconds · ${value(detail.detailPacing.burst_size)} attempts · ${value(detail.detailPacing.burst_pause_seconds)} seconds pause` : 'Not recorded'}</p></section>}{detail.issue && <section className="crawl-tasks-detail-block"><h3>Issue</h3><p><strong>{detail.issue.code || detail.issue.issueClass}</strong> · {detail.issue.summary}</p>{detail.issue.stage && <p>Stage: {detail.issue.stage}</p>}</section>}{showBrowserRecovery && <ManualActionRecoveryPanel task={recoveryTask} capability={null} onTaskChanged={onRecoveryChanged} recoveryAttempt={detail.recoveryAttempt ? {
    status: detail.recoveryAttempt.outcome,
    sequenceNo: detail.recoveryAttempt.request_event_sequence,
    requestedAt: detail.recoveryAttempt.requested_at,
    outcomeAt: detail.recoveryAttempt.outcome_at,
    strategy: detail.recoveryAttempt.strategy,
    stage: guidance.stage,
    classification: detail.recoveryAttempt.outcome_classification || detail.recoveryAttempt.trigger_classification,
    message: detail.recoveryAttempt.outcome_error,
  } : null} recoveryAttemptError={null} />}{guidance && !showBrowserRecovery && <section className="crawl-tasks-detail-block"><h3>Manual action guidance</h3><p>{guidance.message}</p>{guidance.instructions?.length > 0 && <ol>{guidance.instructions.map((instruction) => <li key={instruction}>{instruction}</li>)}</ol>}</section>}{detail.recoveryAttempt && !showBrowserRecovery && <section className="crawl-tasks-detail-block"><h3>Current recovery attempt</h3><p>{detail.recoveryAttempt.outcome} · {detail.recoveryAttempt.strategy || 'server-selected strategy'}</p></section>}<div className="crawl-tasks-danger-zone"><div><strong>Actions</strong><p>Available actions reflect the latest task state. Cancellation preserves saved work.</p></div><div className="board-actions">{detail.actions.filter((action) => ['cancel', ...(showBrowserRecovery ? [] : ['resume_manual_action'])].includes(action.action)).map((action) => <button key={action.action} type="button" disabled={!action.enabled || actionState.pending !== null} onClick={(event) => onAction(action.action, event.currentTarget)}>{action.action === 'cancel' ? (run.status === 'cancelling' ? 'Cancelling Crawl Job' : 'Cancel Crawl Job') : 'Resume manual action'}</button>)}</div></div><section className="crawl-tasks-detail-block"><h3>Immutable authority</h3><ScopeDetails authority={run.authority} /></section><CrawlQualityAdvisory quality={crawlQuality} pending={crawlQualityPending} error={crawlQualityError} onPreview={onCrawlQualityPreview} onEvaluate={onCrawlQualityEvaluate} /></>;
}
