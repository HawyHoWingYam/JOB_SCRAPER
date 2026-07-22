import React, { useEffect, useMemo, useState } from 'react';
import {
  applySourceCatalogProvenance,
  inspectSourceCatalogProvenance,
} from '../../api/jobIntelligence';
import { formatApiErrorDetail } from '../../api/errors';

const DEFAULT_LIMIT = 50;

function toApiScope(scope = {}) {
  return {
    source_sites: scope.sourceSites || [],
    source_classification_ids: scope.sourceClassificationIds || [],
    source_subclassification_ids: scope.sourceSubclassificationIds || [],
    posted_date_from: scope.postedDateFrom || null,
    posted_date_to: scope.postedDateTo || null,
  };
}

export default function ProvenanceRepairPanel({ scope = {}, item, onComplete }) {
  const [status, setStatus] = useState('idle');
  const [report, setReport] = useState(null);
  const [result, setResult] = useState(null);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState(null);
  const limit = Number(scope.pendingLimit) > 0 ? Number(scope.pendingLimit) : DEFAULT_LIMIT;
  const apiScope = useMemo(() => toApiScope(scope), [scope]);
  const reason = item?.reasons?.[0];
  const isProvenanceMissing = reason === 'source_catalog_provenance_missing';

  useEffect(() => {
    setStatus('idle');
    setReport(null);
    setResult(null);
    setConfirmed(false);
    setError(null);
  }, [item?.id]);

  if (!isProvenanceMissing && reason !== 'source_classification_paths_missing') {
    return null;
  }

  const inspect = async () => {
    setStatus('inspecting');
    setError(null);
    try {
      const payload = await inspectSourceCatalogProvenance(apiScope, limit);
      setReport(payload.report);
      setStatus('ready');
    } catch (inspectError) {
      setError(inspectError);
      setStatus('error');
    }
  };

  const apply = async () => {
    if (!report || !confirmed) return;
    setStatus('applying');
    setError(null);
    try {
      const payload = await applySourceCatalogProvenance(
        apiScope,
        {
          limit,
          revisionId: report.revision_id,
          expectedFingerprint: report.revision_fingerprint,
          repairableJobIds: report.repairable_job_ids,
        },
      );
      setResult(payload);
      setStatus('complete');
      onComplete?.(payload);
    } catch (applyError) {
      setError(applyError);
      setStatus('error');
    }
  };

  const blockers = report?.write_blockers || [];
  const canApply = Boolean(
    report
    && report.repairable_jobs > 0
    && blockers.length === 0
    && confirmed
    && status === 'ready',
  );

  return (
    <section className="governance-panel provenance-repair-panel">
      <h2>{isProvenanceMissing ? 'Restore the source evidence link' : 'Source data needs recollection'}</h2>
      {isProvenanceMissing ? (
        <>
          <p>
            This job has a source classification path, but it is not tied to a
            specific published Source Catalog version. AI cannot safely use that
            path until the version binding is checked.
          </p>
          <p className="governance-muted">
            Assigning a Canonical Job Subcategory does not repair this source
            evidence. The safe flow is inspect first, then confirm the bounded
            current batch.
          </p>
          {status === 'idle' && (
            <button type="button" onClick={inspect}>
              Check whether this batch can be repaired
            </button>
          )}
        </>
      ) : (
        <p>
          The source classification path itself is missing. This cannot be
          repaired by choosing a canonical category; source data must be
          recollected before AI Enrichment can run.
        </p>
      )}

      {status === 'inspecting' && <p role="status">Checking the current Source Catalog…</p>}
      {status === 'applying' && <p role="status">Applying the confirmed repair…</p>}
      {error && (
        <p className="provenance-repair-error" role="alert">
          {formatApiErrorDetail(error, 'Provenance request failed')}
        </p>
      )}

      {report && (
        <div className="provenance-repair-report" aria-live="polite">
          <strong>Current batch check</strong>
          <dl>
            <div><dt>Jobs checked</dt><dd>{report.jobs_inspected}</dd></div>
            <div><dt>Safe to repair</dt><dd>{report.repairable_jobs}</dd></div>
            <div><dt>Already bound</dt><dd>{report.already_bound_paths}</dd></div>
            <div><dt>Blocked paths</dt><dd>{report.missing_path_jobs + report.unknown_identity_jobs.length}</dd></div>
          </dl>
          {blockers.length > 0 && (
            <div className="provenance-repair-blockers">
              <strong>Repair is blocked until these checks pass:</strong>
              <ul>{blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul>
            </div>
          )}
          {status === 'ready' && blockers.length === 0 && report.repairable_jobs > 0 && (
            <label className="provenance-confirmation">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              <span>I reviewed the current Source Catalog version and approve this bounded repair.</span>
            </label>
          )}
          {status === 'ready' && isProvenanceMissing && (
            <button type="button" disabled={!canApply} onClick={apply}>
              Confirm provenance repair
            </button>
          )}
        </div>
      )}

      {result && (
        <div className="provenance-repair-result" role="status">
          <strong>Repair finished</strong>
          <p>
            Repaired {result.repair?.changed_jobs || 0} jobs. The refreshed
            preflight currently allows {result.selection?.effective_item_count || 0}
            {' '}to run and still excludes {result.selection?.excluded_item_count || 0}.
          </p>
          <a href="#ai">Return to AI Enrichment</a>
        </div>
      )}
    </section>
  );
}
