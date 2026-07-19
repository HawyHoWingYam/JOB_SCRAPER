import React, { useEffect, useState } from 'react';
import { formatApiErrorDetail } from '../../api/errors';

export default function GovernedTargetPicker({
  options = [],
  value,
  onChange,
  loadChildren,
  browseLabel = 'Show child targets',
  disabled,
}) {
  const [visibleOptions, setVisibleOptions] = useState(options);
  const [trail, setTrail] = useState([]);
  const [loading, setLoading] = useState(false);
  const [browseError, setBrowseError] = useState(null);
  const selected = visibleOptions.find((option) => option.value === value);

  useEffect(() => {
    setVisibleOptions(options);
    setTrail([]);
    setBrowseError(null);
  }, [options]);

  const browseChildren = async () => {
    if (!selected || !loadChildren) return;
    setLoading(true);
    setBrowseError(null);
    try {
      const children = await loadChildren(selected.value);
      if (!children.length) {
        setBrowseError(new Error('No child Industries are available for this target.'));
        return;
      }
      setTrail((current) => [
        ...current,
        {
          label: selected.label,
          options: visibleOptions,
          selectedId: selected.value,
        },
      ]);
      setVisibleOptions(children);
      onChange(children[0]?.value || '');
    } catch (error) {
      setBrowseError(error);
    } finally {
      setLoading(false);
    }
  };

  const browseParent = () => {
    const parent = trail[trail.length - 1];
    if (!parent) return;
    setTrail((current) => current.slice(0, -1));
    setVisibleOptions(parent.options);
    onChange(parent.selectedId);
    setBrowseError(null);
  };

  return (
    <div className="decision-target-picker">
      {trail.length > 0 && (
        <ol aria-label="Selected target path" className="decision-target-trail">
          {trail.map((item) => (
            <li key={item.selectedId}>{item.label}</li>
          ))}
        </ol>
      )}
      <label>
        Governed target
        <select
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled || loading}
        >
          <option value="">Select a governed target</option>
          {visibleOptions.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      </label>
      {loadChildren && (
        <div className="decision-target-navigation">
          {trail.length > 0 && (
            <button type="button" onClick={browseParent} disabled={disabled || loading}>
              Back to parent Industries
            </button>
          )}
          {selected?.hasChildren !== false && (
            <button
              type="button"
              onClick={browseChildren}
              disabled={disabled || loading || !selected}
            >
              {loading ? 'Loading child Industries…' : browseLabel}
            </button>
          )}
        </div>
      )}
      {browseError && (
        <p className="decision-error" role="alert">
          {formatApiErrorDetail(browseError, 'Child targets could not be loaded.')}
        </p>
      )}
    </div>
  );
}
