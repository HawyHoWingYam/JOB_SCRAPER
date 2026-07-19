import React from 'react';

function industryLabel(node) {
  return `${node.code} · ${node.labels?.en || 'Unknown Industry'}`;
}

export default function CompanyIndustryContextPanel({ tree, mappings = [] }) {
  return (
    <section className="governance-panel">
      <h2>Company Industry context</h2>
      <p>
        <strong>Active HSIC release:</strong>{' '}
        {tree?.revision?.release_key || 'Unknown'}
      </p>
      <h3>Taxonomy roots</h3>
      {tree?.nodes?.length ? (
        <ul className="governance-context-list">
          {tree.nodes.map((node) => (
            <li key={node.id}>{industryLabel(node)}</li>
          ))}
        </ul>
      ) : (
        <p className="governance-muted">No active taxonomy roots available.</p>
      )}
      <h3>Reviewed Source Industry mappings</h3>
      {mappings.length ? (
        <ul className="governance-context-list">
          {mappings.map((mapping) => (
            <li key={mapping.id}>
              <strong>{mapping.raw_value}</strong>
              <span>{mapping.source_site} · {mapping.status}</span>
              <code>{mapping.target_node_id}</code>
            </li>
          ))}
        </ul>
      ) : (
        <p className="governance-muted">No reviewed mappings available.</p>
      )}
    </section>
  );
}
