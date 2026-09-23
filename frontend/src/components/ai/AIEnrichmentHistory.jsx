import { buildSettingsRoute } from '../settings/settingsRoute';
import { useEffect, useRef, useState } from 'react';
import { apiPath } from '../../api/base';
import { apiFetchJson } from '../../api/client';
import { buildCrawlTaskRoute } from '../../features/taskControl/board/boardRoute';
import { formatControlDateTime } from '../../features/taskControl/shared/controlTime';

function selectedEnrichmentRun(hash = window.location.hash) {
  const [path, query] = hash.replace(/^#/, '').split('?', 2);
  const id = path === 'ai' ? new URLSearchParams(query).get('run') : null;
  return id && id.length <= 255 ? id : null;
}

export default function AIEnrichmentHistory({ revision, busy, hasActiveRun, onRetry, onResume, onStop }) {
  const [selectedId, setSelectedId] = useState(() => selectedEnrichmentRun());
  const [history, setHistory] = useState(null);
  const [historyError, setHistoryError] = useState('');
  const [historyLoading, setHistoryLoading] = useState(true);
  const [reload, setReload] = useState(0);
  const [run, setRun] = useState(null);
  const [runError, setRunError] = useState('');
  const [items, setItems] = useState(null);
  const [itemsError, setItemsError] = useState('');
  const [status, setStatus] = useState('failed');
  const [page, setPage] = useState(1);
  const [detailLoading, setDetailLoading] = useState(false);
  const headingRef = useRef(null);

  useEffect(() => {
    const change = () => { setSelectedId(selectedEnrichmentRun()); setPage(1); };
    window.addEventListener('hashchange', change);
    return () => window.removeEventListener('hashchange', change);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setHistoryLoading(true);
    apiFetchJson(apiPath('/ai/runs?limit=20'), { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) { setHistory(result.runs || []); setHistoryError(''); } })
      .catch(error => { if (!controller.signal.aborted) setHistoryError(error.message); })
      .finally(() => { if (!controller.signal.aborted) setHistoryLoading(false); });
    return () => controller.abort();
  }, [reload, revision]);

  useEffect(() => {
    if (!selectedId) return undefined;
    const controller = new AbortController();
    setRun(current => current?.id === selectedId ? current : null);
    setRunError('');
    apiFetchJson(apiPath(`/ai/runs/${encodeURIComponent(selectedId)}`), { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setRun(result); })
      .catch(error => { if (!controller.signal.aborted) setRunError(error.message); });
    return () => controller.abort();
  }, [selectedId, reload, revision]);

  useEffect(() => {
    if (!selectedId) return undefined;
    const controller = new AbortController();
    setItems(null);
    setItemsError('');
    setDetailLoading(true);
    const query = status === 'all' ? '' : `?status=${status}`;
    apiFetchJson(apiPath(`/ai/runs/${encodeURIComponent(selectedId)}/items${query}`), { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setItems(result.items || []); })
      .catch(error => { if (!controller.signal.aborted) setItemsError(error.message); })
      .finally(() => { if (!controller.signal.aborted) setDetailLoading(false); });
    return () => controller.abort();
  }, [selectedId, status, reload, revision]);

  useEffect(() => {
    if (selectedId) headingRef.current?.focus();
  }, [selectedId]);

  const selectedRun = run?.id === selectedId ? run : null;
  const selectedIsLive = ['waiting', 'pending', 'running', 'stopping'].includes(selectedRun?.status);
  useEffect(() => {
    if (!selectedIsLive) return undefined;
    const interval = window.setInterval(() => {
      if (!document.hidden) setReload(value => value + 1);
    }, 5000);
    return () => window.clearInterval(interval);
  }, [selectedIsLive]);
  const retryable = selectedRun && ['failed', 'completed_with_failures'].includes(selectedRun.status) && Number(selectedRun.failed_items) > 0;
  const resumable = selectedRun?.status === 'cancelled' && selectedRun.source_type === 'jev_skill_backfill' && Number(selectedRun.cancelled_items) > 0;
  const stoppable = selectedRun && ['waiting', 'pending', 'running'].includes(selectedRun.status);
  return <section className="glass-panel ai-history" aria-label="Run history and inspection">
    <div className="ai-console-header"><div><h3>Run history</h3><p>Latest 20 persisted runs, including waiting work. Open a run to inspect its outcomes.</p></div><button type="button" disabled={historyLoading} onClick={() => setReload(value => value + 1)}>{historyLoading ? 'Refreshing history…' : 'Refresh history'}</button></div>
    {historyError && <p role="alert">{history ? 'Refresh failed; previous history remains visible. ' : ''}{historyError}</p>}
    {history?.length === 0 && <p>No persisted runs yet.</p>}
    <ul className="ai-history-list">{history?.map(item => <li key={item.id}>
      <a href={`#ai?run=${encodeURIComponent(item.id)}`} aria-current={item.id === selectedId ? 'true' : undefined}>{item.id}</a>
      <span>{String(item.status).replaceAll('_', ' ')} · {formatControlDateTime(item.created_at)}</span>
      <span>{Number(item.failed_items || 0)} failed · {Number(item.excluded_items || 0)} excluded</span>
    </li>)}</ul>
    {selectedId && <section className="ai-run-inspection" aria-label={`Inspect run ${selectedId}`}>
      <div className="ai-console-header"><h3 ref={headingRef} tabIndex={-1}>Run details: {selectedId}</h3><a href="#ai">Close run details</a></div>
      {runError && <p role="alert">{selectedRun ? 'Refresh failed; previous run details remain visible. ' : ''}{runError}</p>}
      {!selectedRun && !runError && <p role="status">Loading run details…</p>}
      {selectedRun && <>
        <p><strong>{selectedRun.status.replaceAll('_', ' ')}</strong> · {selectedRun.total_items} selected · {Number(selectedRun.completed_items || 0)} succeeded · {Number(selectedRun.failed_items || 0)} failed · {Number(selectedRun.cancelled_items || 0)} cancelled · {Number(selectedRun.excluded_items || 0)} excluded</p>
        {selectedRun.status === 'waiting' && <p>This run is waiting for an execution slot. Its jobs are already reserved.</p>}
        {selectedRun.pending_gate_reason && <p>{selectedRun.pending_gate_reason.replaceAll('_', ' ')}</p>}
        {selectedRun.trigger_crawl_job_id && <p><a href={buildCrawlTaskRoute(selectedRun.trigger_crawl_job_id)}>Open linked crawl task</a>{selectedRun.pending_gate_crawl_job_status ? ` · ${selectedRun.pending_gate_crawl_job_status.replaceAll('_', ' ')}` : ''}</p>}
        {selectedRun.pending_gate_reason === 'waiting_for_ai_runtime' && <a href={buildSettingsRoute({ profile: 'jobs', returnToAI: true, returnRun: selectedId })}>Configure and test AI runtime in Settings</a>}
        <div className="ai-run-actions">
          {retryable && <button type="button" disabled={busy || hasActiveRun} onClick={() => onRetry(selectedRun)}>Retry this run’s failed jobs ({selectedRun.failed_items})</button>}
          {resumable && <button type="button" disabled={busy || hasActiveRun} onClick={() => onResume(selectedRun)}>Resume this backfill’s cancelled jobs ({selectedRun.cancelled_items})</button>}
          {stoppable && <button type="button" disabled={busy} onClick={() => onStop(selectedRun)}>Stop this run</button>}
          {selectedRun.status === 'stopping' && <p role="status">Stop requested; in-flight jobs may still finish.</p>}
        </div>
        {(retryable || resumable) && hasActiveRun && <p>Wait for the active run to finish before starting another run.</p>}
      </>}
      <label className="ai-history-filter">Item outcome <select value={status} onChange={event => { setStatus(event.target.value); setPage(1); }}>
        {['failed', 'excluded', 'cancelled', 'completed', 'pending', 'running', 'all'].map(value => <option key={value} value={value}>{value === 'all' ? 'All outcomes' : value}</option>)}
      </select></label>
      {detailLoading && <p role="status">Loading run items…</p>}
      {itemsError && <p role="alert">{itemsError}</p>}
      {(runError || itemsError) && <button type="button" onClick={() => setReload(value => value + 1)}>Retry run details</button>}
      {items && <>
        <p>{items.length} {status === 'all' ? '' : status} items. Excluded jobs were not attempted and cannot be retried as failures.</p>
        {items.length === 0 ? <p>No items match this outcome.</p> : <ol className="ai-history-items">{items.slice((page - 1) * 50, page * 50).map(item => <li key={item.id}>
          <strong>Job {item.job_id}</strong><span>{item.status} · {item.attempt_count} attempts</span>
          {(item.error_message || item.error_code) && <p>{item.error_message || item.error_code}</p>}
        </li>)}</ol>}
        {items.length > 50 && <div className="ai-run-actions"><button disabled={page === 1} onClick={() => setPage(value => value - 1)}>Previous items</button><span>Page {page} of {Math.ceil(items.length / 50)}</span><button disabled={page * 50 >= items.length} onClick={() => setPage(value => value + 1)}>Next items</button></div>}
      </>}
    </section>}
  </section>;
}
