import React, { useMemo, useState } from 'react';

function pathLabel(node) {
  return node.nativePath?.join(' / ') || node.nativeLabel;
}

export default function SourceScopeTree({ sourceSite, catalog, scope, onChange }) {
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState(() => new Set());
  const nodes = useMemo(() => catalog?.nodes || [], [catalog?.nodes]);
  const byParent = useMemo(() => {
    const result = new Map();
    nodes.forEach((node) => {
      const key = node.parentNodeKey || '__root__';
      result.set(key, [...(result.get(key) || []), node]);
    });
    return result;
  }, [nodes]);
  const rules = scope?.rules || [];

  const setRule = (node, kind) => {
    const key = `${kind}:${node.classificationId}`;
    const current = new Map(rules.map((rule) => [`${rule.kind}:${rule.classification_id}`, rule]));
    if (current.has(key)) current.delete(key);
    else current.set(key, { kind, classification_id: node.classificationId, path: pathLabel(node) });
    onChange({ mode: 'rules', rules: [...current.values()] });
  };

  const renderNode = (node) => {
    const children = byParent.get(node.nodeKey) || [];
    const isExpanded = expanded.has(node.nodeKey);
    const exactSelected = rules.some((rule) => rule.kind === 'exact' && rule.classification_id === node.classificationId);
    const subtreeSelected = rules.some((rule) => rule.kind === 'subtree' && rule.classification_id === node.classificationId);
    const canonical = node.sourceMetadata?.clean_match || node.sourceMetadata?.canonical_clean_match;
    return (
      <li key={node.nodeKey}>
        <div className="scope-node">
          {children.length > 0 ? (
            <button type="button" className="scope-expand" aria-expanded={isExpanded} onClick={() => setExpanded((current) => { const next = new Set(current); if (next.has(node.nodeKey)) next.delete(node.nodeKey); else next.add(node.nodeKey); return next; })}>
              {isExpanded ? 'Collapse' : 'Expand'}
            </button>
          ) : <span className="scope-leaf" aria-hidden="true">Leaf</span>}
          <div className="scope-node-label"><strong>{node.nativeLabel}</strong><small>{pathLabel(node)}</small>{canonical && <small>Canonical: {canonical}</small>}{node.aliasOfNodeKey && <small>Alias of {node.aliasOfNodeKey} · informational only</small>}</div>
          {node.classificationId && node.selectable && !node.aliasOfNodeKey && (
            <div className="scope-node-actions">
              {node.supportsExact && <button type="button" aria-pressed={exactSelected} onClick={() => setRule(node, 'exact')}>This classification only</button>}
              {node.supportsSubtree && <button type="button" aria-pressed={subtreeSelected} onClick={() => setRule(node, 'subtree')}>Entire category tree</button>}
            </div>
          )}
        </div>
        {children.length > 0 && isExpanded && <ul>{children.map(renderNode)}</ul>}
      </li>
    );
  };

  const normalizedSearch = search.trim().toLowerCase();
  const matches = normalizedSearch
    ? nodes.filter((node) => `${node.nativeLabel} ${pathLabel(node)} ${node.sourceMetadata?.clean_match || ''}`.toLowerCase().includes(normalizedSearch))
    : null;

  return (
    <div className="source-scope-tree">
      <div className="scope-mode-actions">
        {catalog?.capabilities?.supportsAllScope && <button type="button" aria-pressed={scope?.mode === 'all'} onClick={() => onChange({ mode: 'all', rules: [] })}>All source classifications</button>}
        {sourceSite === 'offertoday' && <button type="button" onClick={() => {
          const recommendation = nodes.find((node) => node.classificationId === 'offertoday:118000');
          if (recommendation) setRule(recommendation, 'subtree');
        }}>Recommend: All IT categories (offertoday:118000 subtree)</button>}
      </div>
      <label className="control-field">Search source-native classifications<input type="search" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
      {rules.length > 0 && <div className="scope-rule-chips" aria-label="Selected scope rules">{rules.map((rule) => <button key={`${rule.kind}:${rule.classification_id}`} type="button" onClick={() => onChange({ mode: 'rules', rules: rules.filter((item) => item !== rule) })}>{rule.kind === 'exact' ? 'Exact' : 'Subtree'} · {rule.path || rule.classification_id} ×</button>)}</div>}
      {matches ? (
        <ul className="scope-search-results">{matches.map((node) => renderNode(node))}</ul>
      ) : (
        <ul className="scope-hierarchy">{(byParent.get('__root__') || []).map(renderNode)}</ul>
      )}
      {!nodes.length && <p role="status" className="control-empty">No active Source Catalog nodes are available.</p>}
    </div>
  );
}
