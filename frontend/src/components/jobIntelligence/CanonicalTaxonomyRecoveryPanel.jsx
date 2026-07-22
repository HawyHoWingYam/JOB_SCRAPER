import React, { useEffect, useMemo, useState } from 'react';
import {
  createCanonicalTaxonomyRecoveryRun,
  fetchCanonicalTaxonomyRecoveryRun,
  previewCanonicalTaxonomyRecovery,
  retryCanonicalTaxonomyRecoveryRun,
} from '../../api/jobIntelligence';
import { formatApiErrorDetail } from '../../api/errors';

const RECOVERY_REASONS = [
  'classifier_output_invalid',
  'classifier_provenance_missing',
];
const ACTIVE_STATUSES = new Set(['pending', 'running', 'stopping']);

function scopeReason(scope) {
  return scope.reason || scope.reasonCodes?.[0] || null;
}

function toProgress(run) {
  const total = Number(run?.total_items || 0);
  const settled = Number(run?.completed_items || 0)
    + Number(run?.failed_items || 0)
    + Number(run?.cancelled_items || 0)
    + Number(run?.excluded_items || 0);
  return total > 0 ? Math.min(100, Math.round((settled / total) * 100)) : 0;
}

export default function CanonicalTaxonomyRecoveryPanel({ scope = {}, onComplete }) {
  const [status, setStatus] = useState('idle');
  const [preview, setPreview] = useState(null);
  const [run, setRun] = useState(null);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState(null);
  const scopeKey = useMemo(() => JSON.stringify(scope), [scope]);
  const reason = scopeReason(scope);
  const eligible = !reason || RECOVERY_REASONS.includes(reason);

  useEffect(() => {
    setStatus('idle');
    setPreview(null);
    setRun(null);
    setConfirmed(false);
    setError(null);
  }, [scopeKey]);

  useEffect(() => {
    if (!run?.id || !ACTIVE_STATUSES.has(run.status)) return undefined;
    let cancelled = false;
    const poll = async () => {
      try {
        const next = await fetchCanonicalTaxonomyRecoveryRun(run.id);
        if (cancelled) return;
        setRun(next);
        if (!ACTIVE_STATUSES.has(next.status)) {
          setStatus('complete');
          onComplete?.(next);
        }
      } catch (pollError) {
        if (!cancelled) setError(pollError);
      }
    };
    const timer = window.setInterval(poll, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [run?.id, run?.status, onComplete]);

  if (!eligible) return null;

  const inspect = async () => {
    setStatus('previewing');
    setError(null);
    setConfirmed(false);
    try {
      const nextPreview = await previewCanonicalTaxonomyRecovery(scope);
      setPreview(nextPreview);
      setStatus('ready');
    } catch (previewError) {
      setError(previewError);
      setStatus('error');
    }
  };

  const start = async () => {
    if (!preview || !confirmed) return;
    setStatus('starting');
    setError(null);
    try {
      const nextRun = await createCanonicalTaxonomyRecoveryRun(scope, {
        expectedScopeFingerprint: preview.scope_fingerprint,
        taxonomyRevisionId: preview.taxonomy_revision.id,
        mappingRevisionId: preview.mapping_revision.id,
      });
      setRun(nextRun);
      setStatus(ACTIVE_STATUSES.has(nextRun.status) ? 'running' : 'complete');
    } catch (startError) {
      setError(startError);
      setStatus('error');
    }
  };

  const retry = async () => {
    if (!run?.id) return;
    setStatus('starting');
    setError(null);
    try {
      const nextRun = await retryCanonicalTaxonomyRecoveryRun(run.id);
      setRun(nextRun);
      setStatus('running');
    } catch (retryError) {
      setError(retryError);
      setStatus('error');
    }
  };

  return (
    <section className="governance-panel taxonomy-recovery-panel">
      <h2>Re-run Job Taxonomy only</h2>
      <p>
        This preview covers only <code>classifier_output_invalid</code> and{' '}
        <code>classifier_provenance_missing</code>. It does not rerun Skills,
        Summary, or Experience. If the classifier still cannot decide, the Job
        stays in Review; it is never bulk-marked as insufficient evidence.
      </p>
      {status === 'idle' && (
        <button type="button" onClick={inspect}>
          Preview AI taxonomy recovery
        </button>
      )}
      {status === 'previewing' && <p role="status">Preparing the bounded preview…</p>}
      {error && (
        <p className="provenance-repair-error" role="alert">
          {formatApiErrorDetail(error, 'Recovery request failed')}
        </p>
      )}

      {preview && (
        <div className="taxonomy-recovery-preview" aria-live="polite">
          <strong>Preview: {preview.selected_count} Jobs would be processed</strong>
          <dl>
            {RECOVERY_REASONS.map((code) => (
              <div key={code}>
                <dt>{code}</dt>
                <dd>{preview.counts_by_reason?.[code] || 0}</dd>
              </div>
            ))}
          </dl>
          <p className="governance-muted">
            Taxonomy revision {preview.taxonomy_revision?.id} · Mapping revision{' '}
            {preview.mapping_revision?.id}
          </p>
          {preview.sample?.length > 0 && (
            <ul className="taxonomy-recovery-sample">
              {preview.sample.map((item) => (
                <li key={item.job_id}>
                  <strong>{item.title || 'Job title unavailable'}</strong>{' '}
                  <span>{item.company_name || 'Company unavailable'}</span>
                </li>
              ))}
            </ul>
          )}
          {status === 'ready' && preview.selected_count > 0 && (
            <>
              <label className="provenance-confirmation">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(event) => setConfirmed(event.target.checked)}
                />
                <span>
                  I reviewed this bounded scope and approve re-running only Job
                  Taxonomy with these pinned revisions.
                </span>
              </label>
              <button type="button" disabled={!confirmed} onClick={start}>
                Confirm and queue {preview.selected_count} Jobs
              </button>
            </>
          )}
          {status === 'ready' && preview.selected_count === 0 && (
            <p className="governance-muted">No eligible classifier failures in this scope.</p>
          )}
        </div>
      )}

      {run && (
        <div className="taxonomy-recovery-progress" role="status" aria-live="polite">
          <strong>Recovery run {run.status}</strong>
          <progress max="100" value={toProgress(run)} />
          <span>
            {run.completed_items || 0} processed · {run.failed_items || 0} upstream failures ·{' '}
            {run.total_items || 0} total
          </span>
          {run.status === 'completed' && (
            <p>Unresolved classifier results remain in the Review queue for follow-up.</p>
          )}
          {!ACTIVE_STATUSES.has(run.status) && Number(run.failed_items || 0) > 0 && (
            <button type="button" onClick={retry}>
              Retry AI upstream failures only
            </button>
          )}
        </div>
      )}
    </section>
  );
}
