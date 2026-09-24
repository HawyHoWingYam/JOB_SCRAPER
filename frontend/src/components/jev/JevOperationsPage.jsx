import React, { useCallback, useEffect, useRef, useState } from 'react';
import { apiFetchJson } from '../../api/client';
import ConfirmActionDialog from '../../features/taskControl/shared/ConfirmActionDialog';
import { readJobBrowserSession } from '../jobBrowserSessionStorage';
import './JevOperationsPage.css';

const OPERATIONS = [
  ['skills', 'Skills correction'],
  ['duplicate', 'Possible same vacancy'],
  ['related_jobs', 'Related Jobs'],
];
const OPERATION_LABELS = Object.fromEntries(OPERATIONS);
const ACTIVE_STATUSES = new Set(['pending', 'running', 'stopping']);
const AUTO_REFRESH_INTERVAL_MS = 60_000;
const INITIAL_LOAD_STATE = { loading: true, refreshing: false, loaded: false, error: '' };

async function requestJson(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  return apiFetchJson(`/api${path}`, { ...options, retryTransient: method === 'GET' });
}

function postJson(path, body, extra = {}) {
  return requestJson(path, {
    ...extra,
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(extra.headers || {}) },
    body: JSON.stringify(body),
  });
}

function longRunningPostJson(path, body, extra = {}) {
  return postJson(path, body, {
    // Manually started work can spend time validating a preview or waiting on
    // the provider. A competing browser deadline can hide a committed receipt.
    timeoutMs: null,
    ...extra,
  });
}

function randomKey(prefix) {
  return globalThis.crypto?.randomUUID?.() || `${prefix}-${Date.now()}`;
}

function statusLabel(value) {
  return String(value || 'unknown').replaceAll('_', ' ');
}

function statusTone(value) {
  if (['completed', 'succeeded'].includes(value)) return 'success';
  if (['failed', 'completed_with_failures'].includes(value)) return 'danger';
  if (['running', 'stopping'].includes(value)) return 'active';
  if (['pending', 'cancelled', 'stopped'].includes(value)) return 'warning';
  return 'neutral';
}

function historyErrorMessage(error, resource) {
  if (error?.status === 404 && resource === 'batch history') {
    return 'Jev Operations is not available in the running backend. Update or restart the backend, then retry.';
  }
  if (error?.status >= 500 && resource === 'batch history') {
    return 'The backend could not load Jev batch history. Check that the current sandbox schema is deployed, then retry.';
  }
  if (error?.code === 'REQUEST_TIMEOUT') {
    return `Loading ${resource} timed out. Check the backend connection, then retry.`;
  }
  return `Could not load ${resource}: ${error?.message || 'Unknown error'}`;
}

function actionErrorMessage(error, actionName) {
  if (error?.code === 'REQUEST_TIMEOUT') {
    if (actionName?.includes('preview')) {
      return 'The local preview took too long. No Jev provider request was sent; narrow the Job scope and retry.';
    }
    return 'The backend did not respond before the request timeout. Check history before retrying because the action may already have been recorded.';
  }
  if (error?.name === 'AbortError') {
    return 'The request was cancelled before it completed. Retry the action when the connection is stable.';
  }
  return error?.message || 'The operation failed.';
}

function ProgressBar({ completed, total, label }) {
  const safeTotal = Math.max(Number(total) || 0, 0);
  const safeCompleted = Math.min(Math.max(Number(completed) || 0, 0), safeTotal);
  const percent = safeTotal ? Math.round((safeCompleted / safeTotal) * 100) : 0;
  return (
    <div className="jev-progress" role="progressbar" aria-label={label} aria-valuemin="0" aria-valuemax={safeTotal} aria-valuenow={safeCompleted}>
      <div className="jev-progress-copy"><span>{safeCompleted} of {safeTotal} finished</span><strong>{percent}%</strong></div>
      <div className="jev-progress-track" aria-hidden="true"><span style={{ width: `${percent}%` }} /></div>
    </div>
  );
}

function HistoryState({ state, empty, children, onRetry }) {
  if (!state.loaded && state.loading) return <div className="jev-state-card" role="status">Loading {state.label}…</div>;
  if (!state.loaded && state.error) {
    return <div className="jev-state-card jev-state-error" role="alert"><span>{state.error}</span><button type="button" onClick={onRetry}>Retry loading</button></div>;
  }
  return (
    <>
      {state.error && <div className="jev-state-card jev-state-warning" role="alert"><span>{state.error} Showing the last successful update.</span><button type="button" onClick={onRetry}>Retry refresh</button></div>}
      {state.refreshing && <p className="jev-refreshing" role="status">Refreshing {state.label}…</p>}
      {children || <div className="jev-empty-state">{empty}</div>}
    </>
  );
}

function ToolResult({ title, value }) {
  if (!value) return null;
  const status = value.status || value.outcome || value.decision || 'ready';
  return (
    <div className="jev-tool-result" role="status">
      <div className="jev-row-between"><span>{title}</span><span className={`jev-status jev-status-${statusTone(status)}`}>{statusLabel(status)}</span></div>
      <details><summary>View response details</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>
    </div>
  );
}

function BatchCard({ batch, onAction, busy, pending }) {
  const finished = (batch.completed_items || 0) + (batch.failed_items || 0) + (batch.skipped_items || 0);
  const ownPending = (action) => pending === `batch-${batch.id}-${action}`;
  return (
    <article className="glass-panel jev-batch-card" aria-label={`Jev batch ${batch.id}`}>
      <div className="jev-row-between">
        <div className="jev-card-identity"><span className={`jev-status jev-status-${statusTone(batch.status)}`}>{statusLabel(batch.status)}</span><code>{batch.id}</code></div>
        <span className="jev-card-date">{batch.created_at ? new Date(batch.created_at).toLocaleString() : null}</span>
      </div>
      <div className="jev-chip-row" aria-label="Selected operations">
        {(batch.operations || []).map((operation) => <span className="jev-chip" key={operation}>{OPERATION_LABELS[operation] || operation}</span>)}
        {batch.force_reevaluation && <span className="jev-chip jev-chip-warning">Force correction enabled</span>}
      </div>
      <ProgressBar completed={finished} total={batch.total_items} label={`Progress for Jev batch ${batch.id}`} />
      {batch.total_execution_batches > 0 && <p className="jev-muted">Execution batch <strong>{batch.current_execution_batch || batch.total_execution_batches}</strong> / {batch.total_execution_batches} · {batch.execution_batch_size} Jobs per execution batch · continues automatically</p>}
      <div className="jev-metric-grid"><span><strong>{batch.pending_items || 0}</strong> Pending</span><span><strong>{batch.running_items || 0}</strong> Running</span><span><strong>{batch.failed_items || 0}</strong> Failed</span><span><strong>{batch.skipped_items || 0}</strong> Skipped</span></div>
      <div className="jev-actions">
        {ACTIVE_STATUSES.has(batch.status) && <button className="jev-danger-button" type="button" disabled={busy} onClick={() => onAction(batch.id, 'stop')}>{ownPending('stop') ? 'Stopping…' : 'Stop'}</button>}
        {batch.status === 'stopped' && <button type="button" disabled={busy} onClick={() => onAction(batch.id, 'resume')}>{ownPending('resume') ? 'Resuming…' : 'Resume manually'}</button>}
        {batch.failed_items > 0 && !ACTIVE_STATUSES.has(batch.status) && <button type="button" disabled={busy} onClick={() => onAction(batch.id, 'retry-failed')}>{ownPending('retry-failed') ? 'Retrying…' : `Retry failed items (${batch.failed_items})`}</button>}
      </div>
      {batch.item_details_included && <details>
        <summary>Per-operation items ({(batch.items || []).length})</summary>
        {(batch.items || []).length ? <ul className="jev-item-list">{batch.items.map((item) => <li key={item.id}><div className="jev-row-between"><strong>{OPERATION_LABELS[item.operation] || item.operation}</strong><span className={`jev-status jev-status-${statusTone(item.status)}`}>{statusLabel(item.status)}</span></div><code>{item.job_id}</code>{item.error_message && <p className="jev-item-error">{item.error_message}</p>}</li>)}</ul> : <p className="jev-muted">No item details were returned.</p>}
      </details>}
    </article>
  );
}

function GenericRunCard({ run, onAction, busy, pending }) {
  const finished = (run.completed_items || 0) + (run.failed_items || 0) + (run.cancelled_items || 0);
  const ownPending = (action) => pending === `run-${run.id}-${action}`;
  return (
    <article className="glass-panel jev-batch-card" aria-label={`Jev run ${run.id}`}>
      <div className="jev-row-between"><div className="jev-card-identity"><strong>{statusLabel(run.purpose)}</strong><code>{run.id}</code></div><span className={`jev-status jev-status-${statusTone(run.status)}`}>{statusLabel(run.status)}</span></div>
      <ProgressBar completed={finished} total={run.total_items} label={`Progress for Jev run ${run.id}`} />
      <div className="jev-actions">
        {['pending', 'running'].includes(run.status) && <button type="button" disabled={busy} onClick={() => onAction(run.id, 'execute-next')}>{ownPending('execute-next') ? 'Executing…' : 'Execute next'}</button>}
        {['pending', 'running'].includes(run.status) && <button className="jev-danger-button" type="button" disabled={busy} onClick={() => onAction(run.id, 'stop')}>{ownPending('stop') ? 'Stopping…' : 'Stop'}</button>}
        {run.status === 'cancelled' && <button type="button" disabled={busy} onClick={() => onAction(run.id, 'resume')}>{ownPending('resume') ? 'Resuming…' : 'Resume manually'}</button>}
        {run.status === 'completed_with_failures' && <button type="button" disabled={busy} onClick={() => onAction(run.id, 'retry-failed')}>{ownPending('retry-failed') ? 'Retrying…' : `Retry failed (${run.failed_items || 0})`}</button>}
      </div>
    </article>
  );
}

export default function JevOperationsPage() {
  const [activeView, setActiveView] = useState('batches');
  const [selection, setSelection] = useState({ source_sites: [], keyword: '', job_ids: '', posted_date_from: '', posted_date_to: '', processing_status: 'all', include_all_matching: false, max_jobs: 100, execution_batch_size: 500, start_execution_batch: 1, operations: ['skills'], force_reevaluation: false });
  const [batches, setBatches] = useState([]);
  const [runs, setRuns] = useState([]);
  const [batchLoad, setBatchLoad] = useState(INITIAL_LOAD_STATE);
  const [runLoad, setRunLoad] = useState(INITIAL_LOAD_STATE);
  const [pending, setPending] = useState('');
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  const [startDialogOpen, setStartDialogOpen] = useState(false);
  const startButtonRef = useRef(null);
  const startIdempotencyKeyRef = useRef(null);
  const batchRefreshInFlightRef = useRef(false);
  const runRefreshInFlightRef = useRef(false);
  const [toolState, setToolState] = useState({ incidentLimit: 200, crawlJobId: '', crawlLimit: 20 });
  const [toolResult, setToolResult] = useState({});

  const payload = useCallback(() => ({
    source_sites: selection.source_sites,
    keyword: selection.keyword.trim() || null,
    job_ids: selection.job_ids.split(/[\s,]+/).map((value) => value.trim()).filter(Boolean),
    posted_date_from: selection.posted_date_from || null,
    posted_date_to: selection.posted_date_to || null,
    processing_status: selection.processing_status,
    job_offset: 0,
    max_jobs: selection.include_all_matching ? null : Number(selection.max_jobs),
    execution_batch_size: Number(selection.execution_batch_size),
    start_execution_batch: Number(selection.start_execution_batch),
    operations: selection.operations,
    force_reevaluation: selection.force_reevaluation,
  }), [selection]);

  const changeSelection = (changes) => {
    setSelection((current) => ({ ...current, ...changes }));
    startIdempotencyKeyRef.current = null;
  };

  const refreshBatches = useCallback(async ({ background = false, silent = false } = {}) => {
    if (batchRefreshInFlightRef.current) return false;
    batchRefreshInFlightRef.current = true;
    if (!silent) setBatchLoad((current) => ({ ...current, loading: !background || !current.loaded, refreshing: background && current.loaded, error: '' }));
    try {
      const data = await requestJson('/jev/operations/batches');
      setBatches(data.batches || []);
      setBatchLoad({ loading: false, refreshing: false, loaded: true, error: '' });
      return true;
    } catch (error) {
      setBatchLoad((current) => ({ ...current, loading: false, refreshing: false, error: historyErrorMessage(error, 'batch history') }));
      return false;
    } finally {
      batchRefreshInFlightRef.current = false;
    }
  }, []);

  const refreshRuns = useCallback(async ({ background = false, silent = false } = {}) => {
    if (runRefreshInFlightRef.current) return false;
    runRefreshInFlightRef.current = true;
    if (!silent) setRunLoad((current) => ({ ...current, loading: !background || !current.loaded, refreshing: background && current.loaded, error: '' }));
    try {
      const data = await requestJson('/jev/runs');
      setRuns(data.runs || []);
      setRunLoad({ loading: false, refreshing: false, loaded: true, error: '' });
      return true;
    } catch (error) {
      setRunLoad((current) => ({ ...current, loading: false, refreshing: false, error: historyErrorMessage(error, 'run history') }));
      return false;
    } finally {
      runRefreshInFlightRef.current = false;
    }
  }, []);

  useEffect(() => { void refreshBatches(); void refreshRuns(); }, [refreshBatches, refreshRuns]);
  useEffect(() => {
    const hasActiveBatch = batches.some((batch) => ACTIVE_STATUSES.has(batch.status));
    const hasActiveRun = runs.some((jevRun) => ACTIVE_STATUSES.has(jevRun.status));
    if (!hasActiveBatch && !hasActiveRun) return undefined;
    const timer = setInterval(() => {
      if (document.visibilityState === 'hidden') return;
      if (hasActiveBatch) void refreshBatches({ background: true, silent: true });
      if (hasActiveRun) void refreshRuns({ background: true, silent: true });
    }, AUTO_REFRESH_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [batches, refreshBatches, refreshRuns, runs]);

  const run = async (name, action, successMessage = '') => {
    if (pending) return null;
    setPending(name); setActionError(''); setNotice('');
    try {
      const value = await action();
      setToolResult((current) => ({ ...current, [name]: value }));
      if (successMessage) setNotice(successMessage);
      return value;
    } catch (error) {
      setActionError(actionErrorMessage(error, name));
      return null;
    } finally { setPending(''); }
  };

  const startBatch = async () => {
    const value = await run('batch-start', async () => {
      startIdempotencyKeyRef.current ||= randomKey('jev-batch');
      const created = await longRunningPostJson('/jev/operations/batches', payload(), { headers: { 'Idempotency-Key': startIdempotencyKeyRef.current } });
      startIdempotencyKeyRef.current = null;
      await refreshBatches({ background: true });
      return created;
    }, 'Jev Job batch started manually.');
    if (value) setStartDialogOpen(false);
  };
  const batchAction = (batchId, action) => run(`batch-${batchId}-${action}`, async () => { const value = await postJson(`/jev/operations/batches/${batchId}/${action}`, {}); await refreshBatches({ background: true }); return value; }, `Batch ${statusLabel(action)} requested manually.`);
  const genericRunAction = (runId, action) => run(`run-${runId}-${action}`, async () => { const value = await (action === 'execute-next' ? longRunningPostJson : postJson)(`/jev/runs/${runId}/${action}`, {}); await refreshRuns({ background: true }); return value; }, `Run ${statusLabel(action)} requested manually.`);
  const toggleOperation = (operation) => changeSelection({ operations: selection.operations.includes(operation) ? selection.operations.filter((value) => value !== operation) : [...selection.operations, operation] });
  const runMaintenance = () => run('maintenance', () => postJson('/job-intelligence/skill-candidates/maintenance/run-now', {}), 'Skill maintenance started manually.');
  const previewSearchRerank = () => run('search-rerank-preview', async () => { const scope = readJobBrowserSession(globalThis.sessionStorage); if (!scope) throw new Error('Apply a Job Browser search first; no saved scope is available.'); return postJson('/jobs/search/rerank/preview', { scope, retrieval_mode: 'lexical' }); }, 'Search preview ready. No Jev provider request was sent.');
  const evaluateSearchRerank = () => run('search-rerank-evaluate', () => longRunningPostJson(`/jobs/search/rerank/evaluations/${toolResult['search-rerank-preview'].id}`, {}), 'Search relevance evaluation started manually.');
  const previewIncident = () => run('incident-preview', () => postJson('/crawl-jobs/incident-triage/preview', { event_limit: Number(toolState.incidentLimit) }), 'Incident preview ready. No Jev provider request was sent.');
  const evaluateIncident = () => run('incident-evaluate', () => longRunningPostJson(`/crawl-jobs/incident-triage/evaluations/${toolResult['incident-preview'].id}`, {}), 'Incident evaluation started manually.');
  const previewCrawlQuality = () => run('crawl-preview', () => postJson(`/crawl-jobs/tasks/${toolState.crawlJobId}/quality/preview`, { limit: Number(toolState.crawlLimit) }), 'Crawl quality preview ready. No Jev provider request was sent.');
  const evaluateCrawlQuality = () => run('crawl-evaluate', () => longRunningPostJson(`/crawl-jobs/tasks/${toolState.crawlJobId}/quality/evaluations`, { limit: Number(toolState.crawlLimit) }), 'Crawl quality evaluation started manually.');
  const runSmoke = () => run('smoke', async () => {
    const created = await postJson('/jev/runs', { purpose: 'configuration_smoke_test', rubric_version: 'jev-smoke-v1', items: [{ subject_id: 'operations-console-smoke-test', evidence_refs: [], payload: { state: { purpose: 'Confirm the configured Jev connection.' }, questions: { ready: { type: 'choice', instructions: 'Is this request readable?', criteria: { yes: 'Readable', no: 'Not readable' } } } } }] });
    const value = await longRunningPostJson(`/jev/runs/${created.id}/execute-next`, {}); await refreshRuns({ background: true }); return value;
  }, 'One paid Jev smoke request was started manually.');

  const busy = Boolean(pending);
  const invalidPostedDateWindow = Boolean(selection.posted_date_from && selection.posted_date_to && selection.posted_date_from > selection.posted_date_to);
  const executionBatchSize = Number(selection.execution_batch_size);
  const startExecutionBatch = Number(selection.start_execution_batch);
  const maximumMatchingJobs = Number(selection.max_jobs);
  const invalidExecutionPlan = executionBatchSize < 1 || startExecutionBatch < 1 || (!selection.include_all_matching && (maximumMatchingJobs < 1 || (startExecutionBatch - 1) * executionBatchSize >= maximumMatchingJobs));
  const activeCount = batches.filter((batch) => ACTIVE_STATUSES.has(batch.status)).length + runs.filter((jevRun) => ACTIVE_STATUSES.has(jevRun.status)).length;
  const failedCount = batches.reduce((count, batch) => count + (batch.failed_items || 0), 0) + runs.reduce((count, runItem) => count + (runItem.failed_items || 0), 0);
  const postedDateSummary = selection.posted_date_from || selection.posted_date_to ? ` Posted date: ${selection.posted_date_from || 'any'} through ${selection.posted_date_to || 'any'}, inclusive.` : '';
  const boundedRemainingJobs = Math.max(maximumMatchingJobs - ((startExecutionBatch - 1) * executionBatchSize), 0);
  const boundedExecutionBatches = Math.ceil(boundedRemainingJobs / Math.max(executionBatchSize || 1, 1));
  const finalExecutionBatch = startExecutionBatch + Math.max(boundedExecutionBatches - 1, 0);
  const executionRange = selection.include_all_matching ? `execution batch ${startExecutionBatch} and continues until every matching Job is processed` : `execution batches ${startExecutionBatch} through ${finalExecutionBatch}`;
  const scopeLimitSummary = selection.include_all_matching ? 'All matching Jobs define the scope.' : `The first up to ${selection.max_jobs} matching Jobs define the scope.`;
  const batchWindowSummary = ` ${scopeLimitSummary} The exact matching Job IDs will be frozen when you confirm. This plan starts at ${executionRange}, with up to ${selection.execution_batch_size} Jobs per batch.`;
  const startSummary = `${selection.operations.map((operation) => OPERATION_LABELS[operation]).join(', ')} will run inside one durable Jev batch.${postedDateSummary}${batchWindowSummary} Eligibility is checked item by item after the batch is recorded. ${selection.force_reevaluation ? 'Force correction is enabled, so successful unchanged results may be evaluated and corrected.' : 'Previously successful unchanged work will remain untouched.'}`;

  return (
    <div className="jev-page">
      <header className="jev-page-header">
        <div><p className="eyebrow">Manual provider boundary</p><h1>Jev Operations</h1><p className="jev-lead">Build a durable Job batch, confirm it once, and let its execution batches continue automatically.</p></div>
        <div className="jev-header-actions"><span className="jev-manual-badge">Manual start only</span><a href="#settings">Credentials and model settings</a><button type="button" disabled={batchLoad.loading || runLoad.loading || batchLoad.refreshing || runLoad.refreshing} onClick={() => { void refreshBatches({ background: true }); void refreshRuns({ background: true }); }}>{batchLoad.refreshing || runLoad.refreshing ? 'Refreshing…' : 'Refresh history'}</button></div>
      </header>
      <div className="jev-overview" aria-label="Jev operations overview"><div><strong>{activeCount}</strong><span>Active manual runs</span></div><div><strong>{batches.length}</strong><span>Job batches loaded</span></div><div><strong>{runs.length}</strong><span>General runs loaded</span></div><div><strong>{failedCount}</strong><span>Failed items visible</span></div></div>
      {actionError && <div className="jev-banner jev-banner-error" role="alert"><strong>Action failed</strong><span>{actionError}</span></div>}
      {notice && <div className="jev-banner jev-banner-success" role="status">{notice}</div>}

      <nav className="jev-workspace-tabs" role="tablist" aria-label="Jev Operations workspaces">
        <button id="jev-batches-tab" type="button" role="tab" aria-selected={activeView === 'batches'} aria-controls="jev-batches-panel" onClick={() => setActiveView('batches')}><span>Job operations</span><small>Build and monitor batches</small></button>
        <button id="jev-tools-tab" type="button" role="tab" aria-selected={activeView === 'tools'} aria-controls="jev-tools-panel" onClick={() => setActiveView('tools')}><span>Advisory tools</span><small>Preview and evaluate</small></button>
        <button id="jev-history-tab" type="button" role="tab" aria-selected={activeView === 'history'} aria-controls="jev-history-panel" onClick={() => setActiveView('history')}><span>Run history</span><small>{runs.length} provider runs</small></button>
      </nav>

      <div id="jev-batches-panel" role="tabpanel" aria-labelledby="jev-batches-tab" hidden={activeView !== 'batches'} className="jev-workspace-panel">
        <section className="glass-panel jev-section jev-batch-builder" aria-labelledby="job-batch-heading">
          <div className="jev-section-heading"><div><p className="jev-step">Build a batch</p><h2 id="job-batch-heading">Choose scope and operations</h2></div><p>The exact scope is frozen only after you confirm. No separate Preview is required.</p></div>
          <div className="jev-builder-layout">
            <div className="jev-builder-block"><div className="jev-builder-label"><span>1</span><div><strong>Job scope</strong><small>Filter the retained corpus or paste exact UUIDs.</small></div></div><div className="jev-form-grid">
              <label>Sources (comma separated)<input value={selection.source_sites.join(', ')} onChange={(event) => changeSelection({ source_sites: event.target.value.split(',').map((value) => value.trim()).filter(Boolean) })} placeholder="jobsdb, ctgoodjobs" /></label>
              <label>Keyword<input value={selection.keyword} onChange={(event) => changeSelection({ keyword: event.target.value })} placeholder="Optional title or text" /></label>
              <label>Posted from<input type="date" value={selection.posted_date_from} max={selection.posted_date_to || undefined} onChange={(event) => changeSelection({ posted_date_from: event.target.value })} /></label>
              <label>Posted to<input type="date" value={selection.posted_date_to} min={selection.posted_date_from || undefined} onChange={(event) => changeSelection({ posted_date_to: event.target.value })} /></label>
              <label>Processing status<select value={selection.processing_status} onChange={(event) => changeSelection({ processing_status: event.target.value })}><option value="all">All selected Jobs</option><option value="eligible">At least one eligible</option><option value="successful">Successful unchanged</option><option value="failed">Previously failed</option></select></label>
              <label>Jobs per execution batch<input type="number" min="1" value={selection.execution_batch_size} onChange={(event) => changeSelection({ execution_batch_size: event.target.value })} /></label>
              <label>Start from execution batch<input type="number" min="1" value={selection.start_execution_batch} onChange={(event) => changeSelection({ start_execution_batch: event.target.value })} /></label>
              <fieldset className="jev-wide-field jev-scope-size"><legend>Matching Job count</legend><div className="jev-scope-options">
                <div className={`jev-scope-option ${selection.include_all_matching ? '' : 'is-selected'}`}><label className="jev-scope-option-heading"><input type="radio" name="jev-scope-size" checked={!selection.include_all_matching} onChange={() => changeSelection({ include_all_matching: false })} /><span><strong>Limit matching Jobs</strong><small>Freeze only the first matching Jobs in the stable scope order.</small></span></label><label className="jev-scope-limit">Maximum matching Jobs<input type="number" min="1" disabled={selection.include_all_matching} value={selection.max_jobs} onChange={(event) => changeSelection({ max_jobs: event.target.value })} /></label></div>
                <div className={`jev-scope-option ${selection.include_all_matching ? 'is-selected' : ''}`}><label className="jev-scope-option-heading"><input type="radio" name="jev-scope-size" checked={selection.include_all_matching} onChange={() => changeSelection({ include_all_matching: true })} /><span><strong>Include all matching Jobs</strong><small>No application count limit. The confirmed plan continues execution batch by execution batch until the frozen scope is complete.</small></span></label><div className="jev-scope-all-note"><strong>Complete matching scope</strong><span>Batch size controls progress only; it does not cap the total.</span></div></div>
              </div></fieldset>
              <label className="jev-wide-field">Explicit Job UUIDs<textarea value={selection.job_ids} onChange={(event) => changeSelection({ job_ids: event.target.value })} placeholder="One UUID per line or comma separated" /></label>
            </div></div>
            <div className="jev-builder-block"><div className="jev-builder-label"><span>2</span><div><strong>Provider work</strong><small>Select all three to process each included Job sequentially inside one durable batch.</small></div></div>
              <fieldset className="jev-operation-picker"><legend className="jev-sr-only">Operations</legend>{OPERATIONS.map(([value, label]) => <label key={value}><input type="checkbox" checked={selection.operations.includes(value)} onChange={() => toggleOperation(value)} /><span><strong>{label}</strong><small>{value === 'skills' ? 'Correct the AI enrichment baseline.' : value === 'duplicate' ? 'Associate suspected duplicate vacancies without merging Jobs.' : 'Refresh related-job recommendations.'}</small></span></label>)}</fieldset>
              <label className="jev-force"><input type="checkbox" checked={selection.force_reevaluation} onChange={(event) => changeSelection({ force_reevaluation: event.target.checked })} /><span><strong>Force correction</strong><small>Reevaluate successful unchanged results. Requires explicit confirmation.</small></span></label>
            </div>
          </div>
          <div className="jev-batch-footer"><div><strong>3 · Confirm and start</strong><small>{invalidPostedDateWindow ? 'Posted from must be on or before Posted to.' : invalidExecutionPlan ? 'The starting execution batch must fall inside the matching Job scope.' : 'The confirmation dialog is the final manual boundary before provider work.'}</small></div><div className="jev-actions"><button ref={startButtonRef} type="button" onClick={() => { setActionError(''); startIdempotencyKeyRef.current ||= randomKey('jev-batch'); setStartDialogOpen(true); }} disabled={busy || invalidPostedDateWindow || invalidExecutionPlan || selection.operations.length === 0}>Start Jev batch…</button></div></div>
        </section>

        <section className="jev-section jev-history-section" aria-labelledby="batch-history-heading">
          <div className="jev-section-heading"><div><p className="jev-step">Batch monitor</p><h2 id="batch-history-heading">Job batch history</h2></div><p>Stop, resume, and retry remain explicit manual actions.</p></div>
          <HistoryState state={{ ...batchLoad, label: 'Jev Job batches' }} empty="No Jev Job batches yet. Configure a scope above, then start one manually." onRetry={() => void refreshBatches()}>{batches.length ? <div className="jev-history-list">{batches.map((batch) => <BatchCard key={batch.id} batch={batch} onAction={batchAction} busy={busy} pending={pending} />)}</div> : null}</HistoryState>
        </section>
      </div>

      <section id="jev-tools-panel" role="tabpanel" hidden={activeView !== 'tools'} className="glass-panel jev-section jev-workspace-panel" aria-labelledby="jev-tools-tab">
        <div className="jev-section-heading"><div><p className="jev-step">Explicit manual actions</p><h2 id="other-tools-heading">Advisory tools</h2></div><p>Preview first where available. Only Evaluate or Run sends work to Jev.</p></div>
        <div className="jev-tool-grid">
          <article><div className="jev-tool-heading"><span>Direct run</span><h3>Skill taxonomy maintenance</h3></div><p>Review accumulated Skill candidates. New Skills and hierarchy changes return to Classification for approval.</p><div className="jev-tool-actions"><button type="button" onClick={runMaintenance} disabled={busy}>{pending === 'maintenance' ? 'Starting…' : 'Run maintenance now'}</button></div><ToolResult title="Latest maintenance response" value={toolResult.maintenance} /></article>
          <article><div className="jev-tool-heading"><span>Preview → Evaluate</span><h3>Search relevance advisory</h3></div><p>Uses the latest successfully applied Job Browser scope and its frozen lexical candidates.</p><div className="jev-tool-actions"><button type="button" onClick={previewSearchRerank} disabled={busy}>Preview saved search</button><button type="button" onClick={evaluateSearchRerank} disabled={busy || !toolResult['search-rerank-preview']?.selected_count}>Evaluate preview with Jev</button></div><ToolResult title="Search preview" value={toolResult['search-rerank-preview']} /><ToolResult title="Latest evaluation" value={toolResult['search-rerank-evaluate']} /></article>
          <article><div className="jev-tool-heading"><span>Preview → Evaluate</span><h3>Repeated incident triage</h3></div><p>Clusters secret-safe operational symptoms before any provider request.</p><label>Event limit<input type="number" min="1" max="1000" value={toolState.incidentLimit} onChange={(event) => setToolState({ ...toolState, incidentLimit: event.target.value })} /></label><div className="jev-tool-actions"><button type="button" onClick={previewIncident} disabled={busy}>Preview incidents</button><button type="button" onClick={evaluateIncident} disabled={busy || !toolResult['incident-preview']?.selected_cluster_count}>Evaluate clusters with Jev</button></div><ToolResult title="Incident preview" value={toolResult['incident-preview']} /><ToolResult title="Latest evaluation" value={toolResult['incident-evaluate']} /></article>
          <article><div className="jev-tool-heading"><span>Preview → Evaluate</span><h3>Crawl content quality</h3></div><p>Reviews bounded content evidence; it never dispatches or repairs a crawl.</p><label>Crawl Job UUID<input value={toolState.crawlJobId} onChange={(event) => setToolState({ ...toolState, crawlJobId: event.target.value })} /></label><label>Listing limit<input type="number" min="1" max="100" value={toolState.crawlLimit} onChange={(event) => setToolState({ ...toolState, crawlLimit: event.target.value })} /></label><div className="jev-tool-actions"><button type="button" onClick={previewCrawlQuality} disabled={busy || !toolState.crawlJobId}>Preview listings</button><button type="button" onClick={evaluateCrawlQuality} disabled={busy || !toolResult['crawl-preview']?.selected_count}>Evaluate listings with Jev</button></div><ToolResult title="Crawl preview" value={toolResult['crawl-preview']} /><ToolResult title="Latest evaluation" value={toolResult['crawl-evaluate']} /></article>
          <article className="jev-tool-warning"><div className="jev-tool-heading"><span>Paid diagnostic</span><h3>Configuration smoke</h3></div><p>Creates one recorded run and sends one provider request. For draft-only testing, use Settings.</p><div className="jev-tool-actions"><button type="button" onClick={runSmoke} disabled={busy}>{pending === 'smoke' ? 'Running…' : 'Run one Jev smoke request'}</button></div><ToolResult title="Latest smoke response" value={toolResult.smoke} /></article>
        </div>
      </section>

      <section id="jev-history-panel" role="tabpanel" hidden={activeView !== 'history'} className="jev-section jev-workspace-panel" aria-labelledby="jev-history-tab">
        <div className="jev-section-heading"><div><p className="jev-step">Receipts and controls</p><h2 id="generic-history-heading">Provider run history</h2></div><p>Generic, smoke, and evaluation runs. Opening this view never creates work.</p></div>
        <HistoryState state={{ ...runLoad, label: 'Jev runs' }} empty="No Jev runs yet. Opening this page never creates one." onRetry={() => void refreshRuns()}>{runs.length ? <div className="jev-history-list">{runs.map((jevRun) => <GenericRunCard key={jevRun.id} run={jevRun} onAction={genericRunAction} busy={busy} pending={pending} />)}</div> : null}</HistoryState>
      </section>

      {startDialogOpen && <ConfirmActionDialog title={selection.force_reevaluation ? 'Start this correction batch?' : 'Start this Jev batch?'} summary={startSummary} confirmLabel={selection.force_reevaluation ? 'Confirm force correction and start' : 'Confirm and start'} pendingLabel="Freezing scope…" pending={pending === 'batch-start'} error={actionError ? new Error(actionError) : null} restoreFocusRef={startButtonRef} onCancel={() => { if (!busy) setStartDialogOpen(false); }} onConfirm={startBatch} />}
    </div>
  );
}
