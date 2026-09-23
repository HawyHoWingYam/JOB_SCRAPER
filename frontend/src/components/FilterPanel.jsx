import React from 'react';
import { CalendarRange, FilterX } from 'lucide-react';
import {
    CheckboxFacetSelector,
    HierarchyFacetSelector,
} from './FilterSelectorCard';

const SOURCE_OPTIONS = [
    { value: '', label: 'All Sources' },
    { value: 'jobsdb', label: 'JobsDB' },
    { value: 'ctgoodjobs', label: 'CTGoodJobs' },
    { value: 'offertoday', label: 'OfferToday' },
];

function hasFilterValue(value) {
    return value !== '' && value != null;
}

function formatSourceLabel(value) {
    const match = SOURCE_OPTIONS.find((option) => option.value === value);
    return match?.label || value;
}

function sourceClassificationLabel(option) {
    return `${formatSourceLabel(option.source)} · ${option.path || option.label}`;
}

function normalizeEmploymentTypeOption(option) {
    if (typeof option === 'string') {
        return {
            key: `legacy:${option}`,
            id: `legacy:${option}`,
            label: option,
            value: `legacy:${option}`,
            legacyLabel: option,
        };
    }
    if (
        option
        && typeof option === 'object'
        && typeof option.code === 'string'
        && typeof option.label === 'string'
    ) {
        return {
            key: `code:${option.code}`,
            id: option.id || option.code,
            label: option.label,
            value: option.code,
            code: option.code,
            count: option.count,
        };
    }
    return null;
}

function FilterPanel({
    filters,
    onFilterChange,
    onReset,
    onDatePresetChange,
    filterOptions,
    isLoading,
    isFacetsLoading = false,
    facetsError = '',
    onRetryFacets,
    datePreset,
    validationError,
    pendingChangeCount,
}) {
    const facetControlsDisabled = isLoading || isFacetsLoading || Boolean(facetsError);
    const handleChange = (field, value) => {
        onFilterChange({
            ...filters,
            [field]: value,
        });
    };
    const employmentTypeOptions = (filterOptions.employment_types || [])
        .map(normalizeEmploymentTypeOption)
        .filter(Boolean);
    const sourceOptions = filterOptions.sources?.length
        ? [SOURCE_OPTIONS[0], ...filterOptions.sources.map((option) => ({
            value: option.id,
            label: `${option.label} (${option.count} jobs)`,
            count: option.count,
        }))]
        : SOURCE_OPTIONS;
    const sourceClassificationOptions = (
        filterOptions.source_classifications || []
    ).map((option) => ({
        ...option,
        displayLabel: sourceClassificationLabel(option),
    }));

    const handleEmploymentTypeChange = (selectedValues) => {
        const selectedOptions = employmentTypeOptions.filter((option) =>
            selectedValues.includes(option.id),
        );
        onFilterChange({
            ...filters,
            employment_type_codes: selectedOptions
                .map((option) => option.code)
                .filter(Boolean),
            employment_type:
                selectedOptions.find((option) => option.legacyLabel)
                    ?.legacyLabel || '',
        });
    };

    const activeFilters = [
        filters.source_site && `Source: ${formatSourceLabel(filters.source_site)}`,
        filters.source_classification_ids?.length > 0 &&
            `Source Classification Paths: ${filters.source_classification_ids
                .map((id) => {
                    const option = filterOptions.source_classifications?.find(
                        (item) => item.id === id,
                    );
                    return option ? sourceClassificationLabel(option) : id;
                })
                .join(', ')}`,
        filters.employment_type_codes?.length > 0 &&
            `Employment Type: ${filters.employment_type_codes
                .map((code) =>
                    employmentTypeOptions.find((option) => option.code === code)
                        ?.label || code,
                )
                .join(', ')}`,
        filters.employment_type && `Employment Type: ${filters.employment_type}`,
        filters.posted_date_from && `Date from: ${filters.posted_date_from}`,
        filters.posted_date_to && `Date to: ${filters.posted_date_to}`,
        hasFilterValue(filters.experience_years_from) && `Experience from: ${filters.experience_years_from} years`,
        hasFilterValue(filters.experience_years_to) && `Experience to: ${filters.experience_years_to} years`,
    ].filter(Boolean);

    const datePresetOptions = [
        { id: 'any_time', label: 'Any time' },
        { id: 'today', label: 'Today' },
        { id: 'last_7_days', label: 'Last 7 days' },
        { id: 'last_30_days', label: 'Last 30 days' },
        { id: 'this_month', label: 'This month' },
        { id: 'custom', label: 'Custom' },
    ];

    return (
        <div className="filter-workspace">
            <section className="filter-deck glass-panel">
                <div className="filter-deck-header">
                    <div>
                        <p className="filter-card-title">Search Lenses</p>
                        <h3>Filters</h3>
                        <p className="filter-card-hint">
                            Active source, date, and experience constraints.
                        </p>
                    </div>
                    <div className="filter-deck-actions">
                        <button
                            type="button"
                            className="clear-filters-btn"
                            onClick={onReset}
                            disabled={isLoading}
                            title="Clear Filters"
                        >
                            <FilterX size={16} />
                            <span>Reset</span>
                        </button>
                    </div>
                </div>

                {isFacetsLoading && (
                    <p
                        className="filter-facet-state"
                        role="status"
                        aria-label="Refreshing filter counts"
                    >
                        Refreshing filter counts…
                    </p>
                )}
                {facetsError && (
                    <div className="filter-facet-state error" role="alert">
                        <span>{facetsError}</span>
                        <button type="button" onClick={onRetryFacets}>
                            Retry filter counts
                        </button>
                    </div>
                )}

                <div className="filter-chip-row" aria-label="Active filters">
                    {activeFilters.length === 0 ? (
                        <span className="filter-chip filter-chip-empty">No structured filters applied</span>
                    ) : (
                        activeFilters.map((filter) => (
                            <span key={filter} className="filter-chip">
                                {filter}
                            </span>
                        ))
                    )}
                    {pendingChangeCount > 0 && (
                        <span className="filter-chip filter-chip-pending">
                            {pendingChangeCount} pending change{pendingChangeCount === 1 ? '' : 's'}
                        </span>
                    )}
                </div>

                <div className="filter-grid">
                    <label className="filter-field">
                        <span className="filter-label">Source</span>
                        <select
                            className="premium-select"
                            value={filters.source_site || ''}
                            onChange={(e) => handleChange('source_site', e.target.value)}
                            disabled={facetControlsDisabled}
                        >
                            {sourceOptions.map((option) => (
                                <option
                                    key={option.value || 'all'}
                                    value={option.value}
                                    disabled={option.count === 0 && filters.source_site !== option.value}
                                >
                                    {option.label}
                                </option>
                            ))}
                        </select>
                    </label>

                    <HierarchyFacetSelector
                        title="Source Classification Paths"
                        options={sourceClassificationOptions}
                        selectedIds={filters.source_classification_ids || []}
                        onChange={(ids) => handleChange('source_classification_ids', ids)}
                        disabled={facetControlsDisabled}
                        groupBySource
                    />

                    <CheckboxFacetSelector
                        title="Employment Type"
                        options={employmentTypeOptions}
                        selectedIds={[
                            ...(filters.employment_type_codes || []),
                            ...(filters.employment_type
                                ? [`legacy:${filters.employment_type}`]
                                : []),
                        ]}
                        onChange={handleEmploymentTypeChange}
                        disabled={facetControlsDisabled}
                    />

                    <label className="filter-field">
                        <span className="filter-label">Date From</span>
                        <input
                            className="premium-input"
                            type="date"
                            value={filters.posted_date_from || ''}
                            onChange={(e) => handleChange('posted_date_from', e.target.value)}
                            disabled={isLoading}
                        />
                    </label>

                    <label className="filter-field">
                        <span className="filter-label">Date To</span>
                        <input
                            className="premium-input"
                            type="date"
                            value={filters.posted_date_to || ''}
                            onChange={(e) => handleChange('posted_date_to', e.target.value)}
                            disabled={isLoading}
                        />
                    </label>

                    <label className="filter-field">
                        <span className="filter-label">Experience From</span>
                        <input
                            className="premium-input"
                            type="number"
                            inputMode="numeric"
                            min="0"
                            step="1"
                            value={filters.experience_years_from ?? ''}
                            onChange={(e) => handleChange('experience_years_from', e.target.value)}
                            disabled={isLoading}
                        />
                    </label>

                    <label className="filter-field">
                        <span className="filter-label">Experience To</span>
                        <input
                            className="premium-input"
                            type="number"
                            inputMode="numeric"
                            min="0"
                            step="1"
                            value={filters.experience_years_to ?? ''}
                            onChange={(e) => handleChange('experience_years_to', e.target.value)}
                            disabled={isLoading}
                        />
                    </label>

                    <div className="filter-field filter-field-wide">
                        <span className="filter-label">Experience Matching</span>
                        <div className="filter-date-note">
                            <span>Unspecified experience is counted as 0-1 years.</span>
                        </div>
                    </div>

                    <div className="filter-field filter-field-wide">
                        <span className="filter-label">Posting Window</span>
                        <div className="filter-preset-row" role="group" aria-label="Posting window presets">
                            {datePresetOptions.map((preset) => (
                                <button
                                    key={preset.id}
                                    type="button"
                                    className={`filter-preset-btn${datePreset === preset.id ? ' is-active' : ''}`}
                                    onClick={() => onDatePresetChange(preset.id)}
                                    aria-pressed={datePreset === preset.id}
                                >
                                    {preset.label}
                                </button>
                            ))}
                        </div>
                        <div className="filter-date-note">
                            <CalendarRange size={16} />
                            <span>Based on the job post date.</span>
                        </div>
                        {validationError && (
                            <p className="filter-validation-message">{validationError}</p>
                        )}
                    </div>
                </div>
            </section>
        </div>
    );
}

export default FilterPanel;
