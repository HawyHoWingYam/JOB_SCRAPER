import React, { useEffect, useRef, useState } from 'react';

export default function GovernanceQueue({
  areaLabel,
  adapter,
  items,
  total,
  query,
  nextCursor,
  selectedId,
  focusTarget,
  onFocusTargetHandled,
  onFilter,
  onNextPage,
  onSelect,
}) {
  const [draftQuery, setDraftQuery] = useState(query || '');
  const searchInputRef = useRef(null);
  const itemButtonRefs = useRef([]);

  useEffect(() => {
    setDraftQuery(query || '');
  }, [query]);

  useEffect(() => {
    if (!focusTarget) return;
    const target = focusTarget === 'search'
      ? searchInputRef.current
      : itemButtonRefs.current[
          items.findIndex((item) => item.id === focusTarget)
        ];
    if (!target) return;
    target.focus();
    onFocusTargetHandled();
  }, [focusTarget, items, onFocusTargetHandled]);

  const handleItemKeyDown = (event, currentIndex) => {
    let nextIndex = null;
    if (event.key === 'ArrowDown') {
      nextIndex = Math.min(currentIndex + 1, items.length - 1);
    } else if (event.key === 'ArrowUp') {
      nextIndex = Math.max(currentIndex - 1, 0);
    } else if (event.key === 'Home') {
      nextIndex = 0;
    } else if (event.key === 'End') {
      nextIndex = items.length - 1;
    }
    if (nextIndex === null || nextIndex === currentIndex) return;
    event.preventDefault();
    itemButtonRefs.current[nextIndex]?.focus();
  };

  const applyFilter = (event) => {
    event.preventDefault();
    onFilter(draftQuery.trim());
  };

  return (
    <section className="governance-queue" aria-label={`${areaLabel} queue`}>
      <form className="governance-queue-filter" onSubmit={applyFilter}>
        <label className="governance-search-label">
          {adapter.queueSearchLabel}
          <input
            ref={searchInputRef}
            type="search"
            value={draftQuery}
            onChange={(event) => setDraftQuery(event.target.value)}
          />
        </label>
        <div className="governance-queue-filter-actions">
          <button type="submit">Apply queue filter</button>
          {(query || draftQuery) && (
            <button
              type="button"
              onClick={() => {
                setDraftQuery('');
                onFilter('');
              }}
            >
              Clear queue filter
            </button>
          )}
        </div>
      </form>
      <div className="governance-queue-count" aria-live="polite">
        Showing {items.length} of {total} matching items
      </div>
      {items.length === 0 && (
        <div className="governance-queue-empty" role="status">
          {query
            ? `No ${areaLabel} items match this filter.`
            : `No pending ${areaLabel} items.`}
        </div>
      )}
      <ul>
        {items.map((item, index) => (
          <li key={item.id}>
            <button
              ref={(node) => {
                itemButtonRefs.current[index] = node;
              }}
              type="button"
              className={item.id === selectedId ? 'selected' : ''}
              aria-pressed={item.id === selectedId}
              onClick={() => onSelect(item.id)}
              onKeyDown={(event) => handleItemKeyDown(event, index)}
            >
              <strong>{adapter.queueLabel(item)}</strong>
              <span>{adapter.queueMeta(item)}</span>
              <small>Version {item.version}</small>
            </button>
          </li>
        ))}
      </ul>
      {nextCursor && (
        <button
          type="button"
          className="governance-queue-next"
          onClick={onNextPage}
        >
          Next queue page
        </button>
      )}
    </section>
  );
}
