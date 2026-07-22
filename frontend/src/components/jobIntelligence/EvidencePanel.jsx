import React from 'react';

function JsonEvidence({ value }) {
  if (value === null || value === undefined) return <span>Unknown</span>;
  if (typeof value !== 'object') return <span>{String(value)}</span>;
  return <pre>{JSON.stringify(value, null, 2)}</pre>;
}

export default function EvidencePanel({ area, item }) {
  const sourceEvidenceReason = (item?.reasons || []).find((reason) => (
    reason === 'source_catalog_provenance_missing'
    || reason === 'source_classification_paths_missing'
  ));
  return (
    <section className="governance-panel">
      <h2>Evidence</h2>
      {area === 'job-taxonomy' && (
        <>
          <p><strong>Job:</strong> {item.job_title || 'Job details unavailable'}</p>
          <p><strong>Company:</strong> {item.company_name || 'Company unavailable'}</p>
          <p><strong>Why it is paused:</strong> {sourceEvidenceReason
            ? 'The source classification evidence is not yet safe to use for AI Enrichment.'
            : ((item.reasons || []).join(', ') || 'The item has not been assigned yet.')}</p>
          {sourceEvidenceReason && (
            <p className="governance-muted">
              The source path is evidence only until its governed catalog/version
              provenance is verified. The repair action appears below.
            </p>
          )}
          <details className="technical-evidence">
            <summary>View technical evidence</summary>
            <p><strong>Job UUID:</strong> <code>{item.job_id}</code></p>
            <p><strong>Unassigned reasons:</strong> {(item.reasons || []).join(', ') || 'Unknown'}</p>
            <p><strong>Evidence hash:</strong> <code>{item.evidence_hash}</code></p>
            <JsonEvidence value={item.evidence_refs} />
          </details>
        </>
      )}
      {area === 'skill-candidates' && (
        <>
          <p><strong>Candidate:</strong> {item.canonical_raw_name}</p>
          <p><strong>Raw variants:</strong> {(item.raw_variants || []).join(', ')}</p>
          <p><strong>Affected Jobs:</strong> {item.affected_job_count}</p>
          <p><strong>Occurrences:</strong> {item.occurrence_count}</p>
          <details className="technical-evidence">
            <summary>View technical evidence</summary>
            <JsonEvidence value={item.evidence_summary} />
          </details>
        </>
      )}
      {area === 'company-industries' && (
        <>
          <p><strong>Company:</strong> {item.company_id}</p>
          <p><strong>Source:</strong> {item.source_site || 'Unknown'}</p>
          <p><strong>Raw Industry evidence:</strong> {item.raw_value || 'Unknown'}</p>
          <p><strong>Review reason:</strong> {item.reason}</p>
          <details className="technical-evidence">
            <summary>View technical evidence</summary>
            <JsonEvidence value={item.provenance} />
          </details>
        </>
      )}
    </section>
  );
}
