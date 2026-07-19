import React from 'react';

function JsonEvidence({ value }) {
  if (value === null || value === undefined) return <span>Unknown</span>;
  if (typeof value !== 'object') return <span>{String(value)}</span>;
  return <pre>{JSON.stringify(value, null, 2)}</pre>;
}

export default function EvidencePanel({ area, item }) {
  return (
    <section className="governance-panel">
      <h2>Evidence</h2>
      {area === 'job-taxonomy' && (
        <>
          <p><strong>Job:</strong> {item.job_id}</p>
          <p><strong>Unassigned reasons:</strong> {(item.reasons || []).join(', ') || 'Unknown'}</p>
          <p><strong>Evidence hash:</strong> <code>{item.evidence_hash}</code></p>
          <JsonEvidence value={item.evidence_refs} />
        </>
      )}
      {area === 'skill-candidates' && (
        <>
          <p><strong>Candidate:</strong> {item.canonical_raw_name}</p>
          <p><strong>Raw variants:</strong> {(item.raw_variants || []).join(', ')}</p>
          <p><strong>Affected Jobs:</strong> {item.affected_job_count}</p>
          <p><strong>Occurrences:</strong> {item.occurrence_count}</p>
          <JsonEvidence value={item.evidence_summary} />
        </>
      )}
      {area === 'company-industries' && (
        <>
          <p><strong>Company:</strong> {item.company_id}</p>
          <p><strong>Source:</strong> {item.source_site || 'Unknown'}</p>
          <p><strong>Raw Industry evidence:</strong> {item.raw_value || 'Unknown'}</p>
          <p><strong>Review reason:</strong> {item.reason}</p>
          <JsonEvidence value={item.provenance} />
        </>
      )}
    </section>
  );
}
