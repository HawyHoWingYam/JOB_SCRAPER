import React, { useCallback, useEffect, useState } from 'react';
import { readJobBrowserSession } from '../jobBrowserSessionStorage';
import './JevOperationsPage.css';

const OPERATIONS = [
  ['skills', 'Skills correction'],
  ['duplicate', 'Possible same vacancy'],
  ['related_jobs', 'Related Jobs'],
];

async function requestJson(path, options = {}) {
  const response = await fetch(`/api${path}`, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof payload.detail === 'string'
      ? payload.detail
      : Array.isArray(payload.detail)
        ? payload.detail.map((item) => `${(item.loc || []).join('.')}: ${item.msg}`).join('; ')
        : payload.detail?.message || payload.detail?.code;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return payload;
}

function postJson(path, body, extra = {}) {
  return requestJson(path, {
    ...extra,
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(extra.headers || {}) },
    body: JSON.stringify(body),
  });
}

function randomKey(prefix) {
  return globalThis.crypto?.randomUUID?.() || `${prefix}-${Date.now()}`;
}

function BatchCard({ batch, onAction }) {
  return (
    <article className="glass-panel jev-batch-card" aria-label={`Jev batch ${batch.id}`}>
      <div className="jev-row jev-row-between">
        <div>
          <strong>{batch.status}</strong>
          <p className="jev-muted">{batch.id}</p>
        </div>
        <span>{batch.completed_items}/{batch.total_items} completed</span>
      </div>
      <div className="jev-progress-grid">
        <span>Pending {batch.pending_items}</span>
        <span>Running {batch.running_items}</span>
        <span>Failed {batch.failed_items}</span>
        <span>Skipped {batch.skipped_items}</span>
      </div>
      <div className="jev-actions">
        {['pending', 'running', 'stopping'].includes(batch.status) && (
          <button type="button" onClick={() => onAction(batch.id, 'stop')}>Stop</button>
        )}
        {batch.status === 'stopped' && (
          <button type="button" onClick={() => onAction(batch.id, 'resume')}>Resume manually</button>
        )}
        {batch.failed_items > 0 && !['pending', 'running', 'stopping'].includes(batch.status) && (
          <button type="button" onClick={() => onAction(batch.id, 'retry-failed')}>Retry failed items</button>
        )}
      </div>
      <details>
        <summary>Per-operation items</summary>
        <ul className="jev-item-list">
          {(batch.items || []).map((item) => (
            <li key={item.id}>
              <strong>{item.operation}</strong> · {item.job_id} · {item.status}
              {item.error_message ? ` · ${item.error_message}` : ''}
            </li>
          ))}
        </ul>
      </details>
    </article>
  );
}

function GenericRunCard({ run, onAction }) {
  return (
    <article className="glass-panel jev-batch-card" aria-label={`Jev run ${run.id}`}>
      <div className="jev-row jev-row-between"><div><strong>{run.purpose}</strong><p className="jev-muted">{run.id}</p></div><span>{run.status} · {run.completed_items}/{run.total_items}</span></div>
      <div className="jev-actions">
        {['pending', 'running'].includes(run.status) && <button type="button" onClick={() => onAction(run.id, 'execute-next')}>Execute next</button>}
        {['pending', 'running'].includes(run.status) && <button type="button" onClick={() => onAction(run.id, 'stop')}>Stop</button>}
        {run.status === 'cancelled' && <button type="button" onClick={() => onAction(run.id, 'resume')}>Resume manually</button>}
        {run.status === 'completed_with_failures' && <button type="button" onClick={() => onAction(run.id, 'retry-failed')}>Retry failed</button>}
      </div>
    </article>
  );
}

export default function JevOperationsPage() {
  const [selection, setSelection] = useState({
    source_sites: [], keyword: '', job_ids: '', processing_status: 'all',
    max_jobs: 100, operations: ['skills'], force_reevaluation: false,
  });
  const [preview, setPreview] = useState(null);
  const [batches, setBatches] = useState([]);
  const [runs, setRuns] = useState([]);
  const [pending, setPending] = useState('');
  const [error, setError] = useState('');
  const [toolState, setToolState] = useState({ incidentLimit: 200, crawlJobId: '', crawlLimit: 20 });
  const [toolResult, setToolResult] = useState({});

  const payload = useCallback(() => ({
    source_sites: selection.source_sites,
    keyword: selection.keyword.trim() || null,
    job_ids: selection.job_ids.split(/[\s,]+/).map((value) => value.trim()).filter(Boolean),
    processing_status: selection.processing_status,
    max_jobs: Number(selection.max_jobs),
    operations: selection.operations,
    force_reevaluation: selection.force_reevaluation,
  }), [selection]);

  const refreshBatches = useCallback(async () => {
    const data = await requestJson('/jev/operations/batches');
    setBatches(data.batches || []);
  }, []);

  const refreshRuns = useCallback(async () => {
    const data = await requestJson('/jev/runs');
    setRuns(data.runs || []);
  }, []);

  useEffect(() => {
    Promise.all([refreshBatches(), refreshRuns()]).catch((err) => setError(err.message));
  }, [refreshBatches, refreshRuns]);

  useEffect(() => {
    const activeBatch = batches.some((batch) => ['pending', 'running', 'stopping'].includes(batch.status));
    const activeRun = runs.some((jevRun) => ['pending', 'running', 'stopping'].includes(jevRun.status));
    if (!activeBatch && !activeRun) return undefined;
    const timer = setInterval(() => Promise.all([refreshBatches(), refreshRuns()]).catch(() => {}), 1000);
    return () => clearInterval(timer);
  }, [batches, refreshBatches, refreshRuns, runs]);

  const run = async (name, action) => {
    setPending(name);
    setError('');
    try {
      const value = await action();
      setToolResult((current) => ({ ...current, [name]: value }));
      return value;
    } catch (err) {
      setError(err.message);
      return null;
    } finally {
      setPending('');
    }
  };

  const previewBatch = () => run('batch-preview', async () => {
    const value = await postJson('/jev/operations/preview', payload());
    setPreview(value);
    return value;
  });

  const startBatch = () => run('batch-start', async () => {
    const value = await postJson('/jev/operations/batches', {
      ...payload(), preview_fingerprint: preview.preview_fingerprint,
    }, { headers: { 'Idempotency-Key': randomKey('jev-batch') } });
    setPreview(null);
    await refreshBatches();
    return value;
  });

  const batchAction = (batchId, action) => run(`batch-${action}`, async () => {
    const value = await postJson(`/jev/operations/batches/${batchId}/${action}`, {});
    await refreshBatches();
    return value;
  });

  const genericRunAction = (runId, action) => run(`run-${action}`, async () => {
    const value = await postJson(`/jev/runs/${runId}/${action}`, {});
    await refreshRuns();
    return value;
  });

  const toggleOperation = (operation) => setSelection((current) => ({
    ...current,
    operations: current.operations.includes(operation)
      ? current.operations.filter((value) => value !== operation)
      : [...current.operations, operation],
  }));

  const runMaintenance = () => run('maintenance', () => (
    postJson('/job-intelligence/skill-candidates/maintenance/run-now', {})
  ));

  const previewSearchRerank = () => run('search-rerank-preview', async () => {
    const scope = readJobBrowserSession(globalThis.sessionStorage);
    if (!scope) throw new Error('Apply a Job Browser search first; no saved scope is available.');
    return postJson('/jobs/search/rerank/preview', { scope, retrieval_mode: 'lexical' });
  });

  const evaluateSearchRerank = () => run('search-rerank-evaluate', () => (
    postJson(`/jobs/search/rerank/evaluations/${toolResult['search-rerank-preview'].id}`, {})
  ));

  const previewIncident = () => run('incident-preview', () => (
    postJson('/crawl-jobs/incident-triage/preview', { event_limit: Number(toolState.incidentLimit) })
  ));

  const evaluateIncident = () => run('incident-evaluate', () => (
    postJson(`/crawl-jobs/incident-triage/evaluations/${toolResult['incident-preview'].id}`, {})
  ));

  const previewCrawlQuality = () => run('crawl-preview', () => (
    postJson(`/crawl-jobs/tasks/${toolState.crawlJobId}/quality/preview`, { limit: Number(toolState.crawlLimit) })
  ));

  const evaluateCrawlQuality = () => run('crawl-evaluate', () => (
    postJson(`/crawl-jobs/tasks/${toolState.crawlJobId}/quality/evaluations`, { limit: Number(toolState.crawlLimit) })
  ));

  const runSmoke = () => run('smoke', async () => {
    const created = await postJson('/jev/runs', {
      purpose: 'configuration_smoke_test', rubric_version: 'jev-smoke-v1',
      items: [{
        subject_id: 'operations-console-smoke-test', evidence_refs: [],
        payload: {
          state: { purpose: 'Confirm the configured Jev connection.' },
          questions: { ready: { type: 'choice', instructions: 'Is this request readable?', criteria: { yes: 'Readable', no: 'Not readable' } } },
        },
      }],
    });
    const value = await postJson(`/jev/runs/${created.id}/execute-next`, {});
    await refreshRuns();
    return value;
  });

  return (
    <div className="jev-page">
      <header className="jev-page-header">
        <div><p className="eyebrow">Manual provider boundary</p><h1>Jev Operations</h1></div>
        <a href="#settings">Credentials and model settings</a>
      </header>
      <p className="jev-lead">Nothing on this page starts until you use an explicit Start or Evaluate action. Preview is database-only.</p>
      {error && <div className="error-message" role="alert">{error}</div>}

      <section className="glass-panel jev-section" aria-labelledby="job-batch-heading">
        <h2 id="job-batch-heading">One Job batch, selected operations</h2>
        <div className="jev-form-grid">
          <label>Sources (comma separated)<input value={selection.source_sites.join(', ')} onChange={(event) => setSelection({ ...selection, source_sites: event.target.value.split(',').map((v) => v.trim()).filter(Boolean) })} /></label>
          <label>Keyword<input value={selection.keyword} onChange={(event) => setSelection({ ...selection, keyword: event.target.value })} /></label>
          <label>Explicit Job UUIDs<textarea value={selection.job_ids} onChange={(event) => setSelection({ ...selection, job_ids: event.target.value })} /></label>
          <label>Processing status<select value={selection.processing_status} onChange={(event) => setSelection({ ...selection, processing_status: event.target.value })}><option value="all">All selected Jobs</option><option value="eligible">At least one eligible</option><option value="successful">Successful unchanged</option><option value="failed">Previously failed</option></select></label>
          <label>Maximum Jobs<input type="number" min="1" max="5000" value={selection.max_jobs} onChange={(event) => setSelection({ ...selection, max_jobs: event.target.value })} /></label>
        </div>
        <fieldset className="jev-operation-picker"><legend>Operations</legend>{OPERATIONS.map(([value, label]) => <label key={value}><input type="checkbox" checked={selection.operations.includes(value)} onChange={() => toggleOperation(value)} />{label}</label>)}</fieldset>
        <label className="jev-force"><input type="checkbox" checked={selection.force_reevaluation} onChange={(event) => setSelection({ ...selection, force_reevaluation: event.target.checked })} />Force reevaluation of successful unchanged work</label>
        <div className="jev-actions"><button type="button" onClick={previewBatch} disabled={Boolean(pending) || selection.operations.length === 0}>Preview batch</button><button type="button" onClick={startBatch} disabled={Boolean(pending) || !preview}>Start selected operations</button></div>
        {preview && <div className="jev-preview" role="status"><strong>{preview.selected_job_count} Jobs selected</strong><span>Monetary limits: Jev API Console</span>{Object.entries(preview.operations).map(([name, value]) => <span key={name}>{name}: {value.eligible} eligible / {value.skipped} skipped</span>)}</div>}
      </section>

      <section className="jev-section" aria-labelledby="batch-history-heading"><h2 id="batch-history-heading">Job batch history</h2>{batches.length ? batches.map((batch) => <BatchCard key={batch.id} batch={batch} onAction={batchAction} />) : <p>No Jev Job batches yet.</p>}</section>

      <section className="glass-panel jev-section" aria-labelledby="other-tools-heading">
        <h2 id="other-tools-heading">Other manual Jev tools</h2>
        <div className="jev-tool-grid">
          <article><h3>Skill taxonomy maintenance</h3><p>Check accumulated Skill candidates and dispatch one bounded maintenance run.</p><button type="button" onClick={runMaintenance} disabled={Boolean(pending)}>Run maintenance now</button>{toolResult.maintenance && <pre>{JSON.stringify(toolResult.maintenance, null, 2)}</pre>}</article>
          <article><h3>Search relevance advisory</h3><p>Uses the latest successfully applied Job Browser scope and lexical membership.</p><button type="button" onClick={previewSearchRerank} disabled={Boolean(pending)}>Preview saved search</button><button type="button" onClick={evaluateSearchRerank} disabled={Boolean(pending) || !toolResult['search-rerank-preview']?.selected_count}>Evaluate preview with Jev</button>{toolResult['search-rerank-evaluate'] && <pre>{JSON.stringify(toolResult['search-rerank-evaluate'], null, 2)}</pre>}</article>
          <article><h3>Repeated incident triage</h3><label>Event limit<input type="number" min="1" max="1000" value={toolState.incidentLimit} onChange={(event) => setToolState({ ...toolState, incidentLimit: event.target.value })} /></label><button type="button" onClick={previewIncident} disabled={Boolean(pending)}>Preview incidents</button><button type="button" onClick={evaluateIncident} disabled={Boolean(pending) || !toolResult['incident-preview']?.selected_cluster_count}>Evaluate clusters with Jev</button>{toolResult['incident-evaluate'] && <pre>{JSON.stringify(toolResult['incident-evaluate'], null, 2)}</pre>}</article>
          <article><h3>Crawl content quality</h3><label>Crawl Job UUID<input value={toolState.crawlJobId} onChange={(event) => setToolState({ ...toolState, crawlJobId: event.target.value })} /></label><label>Listing limit<input type="number" min="1" max="100" value={toolState.crawlLimit} onChange={(event) => setToolState({ ...toolState, crawlLimit: event.target.value })} /></label><button type="button" onClick={previewCrawlQuality} disabled={Boolean(pending) || !toolState.crawlJobId}>Preview listings</button><button type="button" onClick={evaluateCrawlQuality} disabled={Boolean(pending) || !toolResult['crawl-preview']?.selected_count}>Evaluate listings with Jev</button>{toolResult['crawl-evaluate'] && <pre>{JSON.stringify(toolResult['crawl-evaluate'], null, 2)}</pre>}</article>
          <article><h3>Configuration smoke</h3><p>This is a paid, single-item connectivity check.</p><button type="button" onClick={runSmoke} disabled={Boolean(pending)}>Run one Jev smoke request</button>{toolResult.smoke && <pre>{JSON.stringify(toolResult.smoke, null, 2)}</pre>}</article>
        </div>
      </section>
      <section className="jev-section" aria-labelledby="generic-history-heading"><h2 id="generic-history-heading">All Jev run history</h2>{runs.length ? runs.map((jevRun) => <GenericRunCard key={jevRun.id} run={jevRun} onAction={genericRunAction} />) : <p>No Jev runs yet.</p>}</section>
    </div>
  );
}
