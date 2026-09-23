import React, { useMemo, useState } from 'react';

export default function SourceScopeTree({
  sourceSite,
  classifications,
  scope,
  onChange,
}) {
  const [search, setSearch] = useState('');
  const selectedIds = new Set(scope?.classification_ids || []);
  const singleSelect = sourceSite === 'offertoday';
  const rows = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (classifications || []).filter((item) => (
      item.active
      && item.id.startsWith(`${sourceSite}:`)
      && (!query || item.label.toLowerCase().includes(query))
    ));
  }, [classifications, search, sourceSite]);

  const setSelected = (id, checked) => {
    if (singleSelect) {
      onChange({
        mode: 'selected',
        classification_ids: checked ? [id] : [],
      });
      return;
    }
    const next = new Set(selectedIds);
    if (checked) next.add(id);
    else next.delete(id);
    onChange({
      mode: 'selected',
      classification_ids: [...next],
    });
  };

  return (
    <div className="scope-tree">
      <div className="control-choice-row">
        {!singleSelect && <button
          type="button"
          aria-pressed={scope?.mode === 'all'}
          onClick={() => onChange({ mode: 'all', classification_ids: [] })}
        >
          All major categories
        </button>}
        <button
          type="button"
          aria-pressed={scope?.mode === 'selected'}
          onClick={() => onChange({
            mode: 'selected',
            classification_ids: [...selectedIds],
          })}
        >
          {singleSelect ? 'Choose one major category' : 'Selected major categories'}
        </button>
      </div>
      {scope?.mode === 'selected' && (
        <>
          {singleSelect && <p>OfferToday automatically includes the current child categories and the enabled keyword pack for this major category.</p>}
          <label className="control-field">
            Search categories
            <input value={search} onChange={(event) => setSearch(event.target.value)} />
          </label>
          <div className="scope-tree-list">
            {rows.map((item) => (
              <label key={item.id} className="scope-node">
                <input
                  type={singleSelect ? 'radio' : 'checkbox'}
                  name={singleSelect ? 'offertoday-classification' : undefined}
                  checked={selectedIds.has(item.id)}
                  onChange={(event) => setSelected(item.id, event.target.checked)}
                />
                <span>{item.label}</span>
              </label>
            ))}
          </div>
          {!rows.length && <p className="control-empty">No active major categories match.</p>}
        </>
      )}
    </div>
  );
}
