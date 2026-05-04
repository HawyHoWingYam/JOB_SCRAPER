import React from 'react';
import { CalendarRange, FilterX } from 'lucide-react';

function hasFilterValue(value) {
    return value !== '' && value != null;
}

function selectedSubcategoryLabel(filters, filterOptions) {
    const selectedId = filters.subcategory_ids?.[0];
    if (!selectedId) {
        return '';
    }

    const match = filterOptions.job_subcategories?.find((subcategory) => subcategory.id === selectedId);
    return match?.name || selectedId;
}

function FilterPanel({
    filters,
    onFilterChange,
    onReset,
    onDatePresetChange,
    filterOptions,
    isLoading,
    datePreset,
    validationError,
    pendingChangeCount,
}) {
    const handleChange = (field, value) => {
        onFilterChange({
            ...filters,
            [field]: value,
        });
    };

    const activeFilters = [
        filters.employment_type && `Job type: ${filters.employment_type}`,
        filters.subcategory_ids?.length > 0 && `Job taxonomy: ${selectedSubcategoryLabel(filters, filterOptions)}`,
        filters.industry && `Industry: ${filters.industry}`,
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
                        <h3>Refine without losing the signal</h3>
                        <p className="filter-card-hint">
                            Focus by hiring taxonomy and limit the results to the post-date window you care about.
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

                <div className="filter-chip-row" aria-label="Active filters">
                    {activeFilters.length === 0 ? (
                        <span className="filter-chip filter-chip-empty">All jobs currently in scope</span>
                    ) : (
                        activeFilters.map((filter) => (
                            <span key={filter} className="filter-chip">
                                {filter}
                            </span>
                        ))
                    )}
                    {pendingChangeCount > 0 && (
                        <span className="filter-chip filter-chip-pending">
                            {pendingChangeCount} pending changes
                        </span>
                    )}
                </div>

                <div className="filter-grid">
                    <label className="filter-field">
                        <span className="filter-label">Job Type</span>
                        <select
                            className="premium-select"
                            value={filters.employment_type || ''}
                            onChange={(e) => handleChange('employment_type', e.target.value)}
                            disabled={isLoading}
                        >
                            <option value="">All Job Types</option>
                            {filterOptions.employment_types.map((type) => (
                                <option key={type} value={type}>{type}</option>
                            ))}
                        </select>
                    </label>

                    <label className="filter-field">
                        <span className="filter-label">Job Taxonomy</span>
                        <select
                            className="premium-select highlight-select"
                            value={filters.subcategory_ids?.[0] || ''}
                            onChange={(e) => handleChange('subcategory_ids', e.target.value ? [e.target.value] : [])}
                            disabled={isLoading}
                        >
                            <option value="">All Taxonomy Paths</option>
                            {filterOptions.job_subcategories?.map((subcategory) => (
                                <option key={subcategory.id} value={subcategory.id}>{subcategory.name}</option>
                            ))}
                        </select>
                    </label>

                    <label className="filter-field">
                        <span className="filter-label">Industry</span>
                        <select
                            className="premium-select"
                            value={filters.industry || ''}
                            onChange={(e) => handleChange('industry', e.target.value)}
                            disabled={isLoading}
                        >
                            <option value="">All Industries</option>
                            {filterOptions.industries?.map((ind) => (
                                <option key={ind} value={ind}>{ind}</option>
                            ))}
                        </select>
                    </label>

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
                            <span>Unspecified experience is treated as 0-1 years for filtering.</span>
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
                            <span>Uses the job post date, so you can isolate fresh listings or backfill specific periods.</span>
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
