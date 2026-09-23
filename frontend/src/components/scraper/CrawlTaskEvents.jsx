import React, { useEffect, useState } from 'react';
import { apiPath } from '../../api/base';
import { apiFetchJson } from '../../api/client';
import { formatControlDateTime } from '../../features/taskControl/shared/controlTime';

export default function CrawlTaskEvents({ taskId, onBack }) {
  const [snapshot, setSnapshot] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    apiFetchJson(apiPath(`/crawl-jobs/${encodeURIComponent(taskId)}/events?limit=100`), { signal: controller.signal })
      .then((result) => { if (!controller.signal.aborted) setSnapshot(result); })
      .catch((failure) => { if (!controller.signal.aborted) setError(failure.message || 'Unable to load audit events.'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [taskId, revision]);

  return <section aria-label="Task audit events">
    <div className="crawl-tasks-detail-header">
      <div><h2>Audit events</h2><p className="crawl-task-id">{taskId}</p></div>
      <button type="button" onClick={onBack}>Back to task details</button>
    </div>
    <p>Recorded activity for this task. Task Details contains the authoritative progress and available actions.</p>
    <button type="button" disabled={loading} onClick={() => setRevision((value) => value + 1)}>{loading ? 'Loading events…' : error ? 'Retry events' : 'Refresh events'}</button>
    {error && <p role="alert">{snapshot ? 'Refresh failed; previously loaded events remain visible. ' : ''}{error}</p>}
    {snapshot && <>
      <p role="status">Showing {snapshot.events.length} of {snapshot.total} recorded events (latest 100).</p>
      {snapshot.events.length === 0 ? <p>No audit events have been recorded for this task.</p> : <ol className="crawl-task-events">
        {snapshot.events.map((event) => <li key={event.id}>
          <strong>{event.event_type.replaceAll('_', ' ')}</strong>
          <p>#{event.sequence_no} · {formatControlDateTime(event.created_at)}{event.emitted_by ? ` · ${event.emitted_by}` : ''}</p>
          <details><summary>Event details</summary><pre>{JSON.stringify(event.payload, null, 2)}</pre></details>
        </li>)}
      </ol>}
    </>}
  </section>;
}
