import React, { useEffect, useState } from 'react';
import { formatCompanyIndustryNode } from './companies/companyIndustryDisplay';

function nodeLabel(node) {
  return formatCompanyIndustryNode(node);
}

export default function LazyCompanyIndustryFilter({
  tree,
  selectedIds,
  onChange,
  loadChildren,
  onNodesSeen,
  disabled,
}) {
  const [visibleNodes, setVisibleNodes] = useState(tree?.nodes || []);
  const [trail, setTrail] = useState([]);
  const [loadingNodeId, setLoadingNodeId] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setVisibleNodes(tree?.nodes || []);
    setTrail([]);
    setError(null);
  }, [tree]);

  const toggleNode = (nodeId, checked) => {
    const next = checked
      ? [...selectedIds, nodeId]
      : selectedIds.filter((id) => id !== nodeId);
    onChange([...new Set(next)]);
  };

  const browseChildren = async (node) => {
    if (!loadChildren) return;
    setLoadingNodeId(node.id);
    setError(null);
    try {
      const childTree = await loadChildren(node.id);
      const children = childTree?.nodes || [];
      if (!children.length) {
        setError(new Error('No child Company Industries are available.'));
        return;
      }
      onNodesSeen?.(children);
      setTrail((current) => [
        ...current,
        { node, nodes: visibleNodes },
      ]);
      setVisibleNodes(children);
    } catch (loadError) {
      setError(loadError);
    } finally {
      setLoadingNodeId(null);
    }
  };

  const browseParent = () => {
    const parent = trail[trail.length - 1];
    if (!parent) return;
    setVisibleNodes(parent.nodes);
    setTrail((current) => current.slice(0, -1));
    setError(null);
  };

  return (
    <fieldset className="filter-field company-industry-filter">
      <legend className="filter-label">Company Industry</legend>
      <p className="filter-hierarchy-note">
        Selecting a node includes governed assignments to its descendants.
      </p>
      {trail.length > 0 && (
        <div className="filter-hierarchy-trail" aria-label="Company Industry path">
          {trail.map(({ node }) => (
            <span key={node.id}>{nodeLabel(node)}</span>
          ))}
        </div>
      )}
      <ul className="filter-hierarchy-list">
        {visibleNodes.map((node) => (
          <li key={node.id}>
            <label>
              <input
                type="checkbox"
                checked={selectedIds.includes(node.id)}
                onChange={(event) => toggleNode(node.id, event.target.checked)}
                disabled={disabled}
              />
              <span>{nodeLabel(node)}</span>
            </label>
            {node.level !== 'subclass' && loadChildren && (
              <button
                type="button"
                aria-label={`Browse children of ${nodeLabel(node)}`}
                onClick={() => browseChildren(node)}
                disabled={disabled || loadingNodeId === node.id}
              >
                {loadingNodeId === node.id ? 'Loading…' : 'Browse'}
              </button>
            )}
          </li>
        ))}
      </ul>
      {trail.length > 0 && (
        <button
          type="button"
          className="filter-hierarchy-back"
          onClick={browseParent}
          disabled={disabled}
        >
          Back to parent Company Industries
        </button>
      )}
      {error && <p className="filter-validation-message" role="alert">{error.message}</p>}
    </fieldset>
  );
}
