import { useId, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, X } from 'lucide-react';
import {
  isHierarchyOptionCovered,
  toggleHierarchySelection,
} from './filterFacetUtils';


function optionJobLabel(option) {
  if (typeof option.count !== 'number') return option.label;
  return `${option.label} (${option.count} jobs)`;
}


export function FilterSelectorCard({
  title,
  selectedOptions = [],
  onRemove,
  disabled = false,
  children,
}) {
  const contentId = useId();
  const [isOpen, setIsOpen] = useState(false);

  return (
    <section className="filter-selector-card filter-field-wide">
      <button
        type="button"
        className="filter-selector-trigger"
        aria-expanded={isOpen}
        aria-controls={contentId}
        aria-label={`${title}, ${selectedOptions.length} selected`}
        onClick={() => setIsOpen((current) => !current)}
        disabled={disabled}
      >
        <span>
          <strong>{title}</strong>
          <small>{selectedOptions.length > 0
            ? `${selectedOptions.length} selected`
            : 'Any'}</small>
        </span>
        <ChevronDown size={18} aria-hidden="true" />
      </button>

      {selectedOptions.length > 0 && (
        <div className="filter-selector-summary" aria-label={`${title} selections`}>
          {selectedOptions.map((option) => (
            <button
              type="button"
              className="filter-selector-chip"
              key={option.id}
              onClick={() => onRemove(option.id)}
              aria-label={`Remove ${option.label} from ${title}`}
              disabled={disabled}
            >
              <span>{option.label}</span>
              <X size={14} aria-hidden="true" />
            </button>
          ))}
        </div>
      )}

      <div id={contentId} className="filter-selector-content" hidden={!isOpen}>
        {children}
      </div>
    </section>
  );
}


export function CheckboxFacetSelector({
  title,
  options = [],
  selectedIds = [],
  onChange,
  disabled = false,
}) {
  const [search, setSearch] = useState('');
  const selected = new Set(selectedIds);
  const normalizedSearch = search.trim().toLocaleLowerCase();
  const visibleOptions = useMemo(
    () => options.filter((option) => (
      !normalizedSearch
      || option.label.toLocaleLowerCase().includes(normalizedSearch)
    )),
    [normalizedSearch, options],
  );
  const selectedOptions = selectedIds.map(
    (id) => options.find((option) => option.id === id) || { id, label: id },
  );

  const toggle = (option, checked) => {
    const next = checked
      ? [...selectedIds, option.id]
      : selectedIds.filter((id) => id !== option.id);
    onChange(Array.from(new Set(next)));
  };

  return (
    <FilterSelectorCard
      title={title}
      selectedOptions={selectedOptions}
      onRemove={(id) => onChange(selectedIds.filter((selectedId) => selectedId !== id))}
      disabled={disabled}
    >
      <label className="filter-selector-search">
        <span className="sr-only">Search {title}</span>
        <input
          className="premium-input"
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={`Search ${title}`}
          disabled={disabled}
        />
      </label>
      <ul className="filter-selector-options">
        {visibleOptions.map((option) => {
          const isSelected = selected.has(option.id);
          const unavailable = option.count === 0 && !isSelected;
          return (
            <li key={option.id}>
              <label>
                <input
                  type="checkbox"
                  checked={isSelected}
                  disabled={disabled || unavailable}
                  onChange={(event) => toggle(option, event.target.checked)}
                />
                <span>{optionJobLabel(option)}</span>
              </label>
            </li>
          );
        })}
      </ul>
    </FilterSelectorCard>
  );
}


export function HierarchyFacetSelector({
  title,
  options = [],
  selectedIds = [],
  onChange,
  disabled = false,
  groupBySource = false,
}) {
  const [search, setSearch] = useState('');
  const [expandedIds, setExpandedIds] = useState(new Set());
  const selected = new Set(selectedIds);
  const optionById = new Map(options.map((option) => [option.id, option]));
  const childrenByParent = new Map();
  for (const option of options) {
    const parentId = option.parent_id && optionById.has(option.parent_id)
      ? option.parent_id
      : null;
    const children = childrenByParent.get(parentId) || [];
    children.push(option);
    childrenByParent.set(parentId, children);
  }
  const normalizedSearch = search.trim().toLocaleLowerCase();
  const matchesSearch = (option) => [
    option.label,
    option.path,
    option.displayLabel,
  ].some((value) => value?.toLocaleLowerCase().includes(normalizedSearch));
  const visibleRoots = normalizedSearch
    ? options.filter(matchesSearch)
    : childrenByParent.get(null) || [];
  const selectedOptions = selectedIds.map(
    (id) => optionById.get(id) || { id, label: id },
  );

  const toggleExpanded = (id) => {
    setExpandedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const renderOption = (option, depth = 0) => {
    const children = normalizedSearch ? [] : childrenByParent.get(option.id) || [];
    const isSelected = selected.has(option.id);
    const covered = isHierarchyOptionCovered(options, selectedIds, option.id);
    const unavailable = option.count === 0 && !isSelected;
    const label = option.displayLabel || option.path || option.label;
    return (
      <li key={option.id}>
        <div className="filter-tree-option" style={{ '--filter-tree-depth': depth }}>
          {children.length > 0 ? (
            <button
              type="button"
              className="filter-tree-expand"
              aria-label={`${expandedIds.has(option.id) ? 'Hide' : 'Show'} children of ${label}`}
              aria-expanded={expandedIds.has(option.id)}
              onClick={() => toggleExpanded(option.id)}
              disabled={disabled}
            >
              {expandedIds.has(option.id)
                ? <ChevronDown size={16} aria-hidden="true" />
                : <ChevronRight size={16} aria-hidden="true" />}
            </button>
          ) : <span className="filter-tree-spacer" />}
          <label>
            <input
              type="checkbox"
              checked={isSelected}
              disabled={disabled || covered || unavailable}
              onChange={(event) => onChange(toggleHierarchySelection(
                options,
                selectedIds,
                option.id,
                event.target.checked,
              ))}
            />
            <span>{optionJobLabel({ ...option, label })}</span>
          </label>
        </div>
        {children.length > 0 && expandedIds.has(option.id) && (
          <ul>{children.map((child) => renderOption(child, depth + 1))}</ul>
        )}
      </li>
    );
  };

  const groupedRoots = groupBySource
    ? Array.from(visibleRoots.reduce((groups, option) => {
      const source = option.source || 'Other';
      const group = groups.get(source) || [];
      group.push(option);
      groups.set(source, group);
      return groups;
    }, new Map()).entries())
    : [[null, visibleRoots]];

  return (
    <FilterSelectorCard
      title={title}
      selectedOptions={selectedOptions.map((option) => ({
        ...option,
        label: option.displayLabel || option.path || option.label,
      }))}
      onRemove={(id) => onChange(selectedIds.filter((selectedId) => selectedId !== id))}
      disabled={disabled}
    >
      <label className="filter-selector-search">
        <span className="sr-only">Search {title}</span>
        <input
          className="premium-input"
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={`Search ${title}`}
          disabled={disabled}
        />
      </label>
      <div className="filter-tree-groups">
        {groupedRoots.map(([source, roots]) => (
          <section key={source || 'all'}>
            {source && <h4>{source}</h4>}
            <ul className="filter-selector-options filter-tree-options">
              {roots.map((option) => renderOption(option))}
            </ul>
          </section>
        ))}
      </div>
    </FilterSelectorCard>
  );
}
