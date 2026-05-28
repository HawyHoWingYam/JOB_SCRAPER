import React, { useEffect, useState } from 'react';
import { Building2, MapPin, CalendarDays, BrainCircuit, ExternalLink, Activity } from 'lucide-react';
import SearchBar from './SearchBar';
import FilterPanel from './FilterPanel';
import Pagination from './Pagination';
import JobDetailModal from './JobDetailModal';
import { API_BASE_URL } from '../api/base';
import { fetchCapabilities } from '../api/capabilities';
import {
    createEmptyJobBrowserLayer,
    createEmptyJobBrowserScope,
    appendLayerToScope,
    hasPendingLayerChanges,
    normalizeLayerForSubmit,
    removeLayerFromScope,
    replaceScopeWithLayer,
} from './jobBrowserScopeUtils';
import {
    countPendingQueryChanges,
    createEmptyJobBrowserQuery,
    getDatePresetForQuery,
    getDatePresetRange,
    getDateValidationError,
} from './jobBrowserQueryUtils';
import './JobBrowser.css';

const API_URL = API_BASE_URL;

function hasQueryValue(value) {
    if (Array.isArray(value)) {
        return value.length > 0;
    }
    return value !== '' && value != null;
}

function getJobTaxonomyPath(job) {
    return job?.job_taxonomy?.path || '';
}

function formatFilterDate(value) {
    if (!value) {
        return '';
    }

    return new Date(`${value}T00:00:00`).toLocaleDateString('en-GB', {
        day: 'numeric',
        month: 'short',
    });
}

function describePostingWindow(filters) {
    if (filters.posted_date_from && filters.posted_date_to) {
        return `Posting window ${formatFilterDate(filters.posted_date_from)} to ${formatFilterDate(filters.posted_date_to)}`;
    }

    if (filters.posted_date_from) {
        return `Posted since ${formatFilterDate(filters.posted_date_from)}`;
    }

    if (filters.posted_date_to) {
        return `Posted through ${formatFilterDate(filters.posted_date_to)}`;
    }

    return 'All posting windows';
}

function formatPostedDate(value) {
    if (!value) {
        return null;
    }

    return new Date(value).toLocaleDateString('en-GB', {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
    });
}

function isLayerEmpty(layer) {
    const normalized = normalizeLayerForSubmit(layer);
    const filters = normalized.structured_filters;
    return !normalized.text_expression && !Object.values(filters).some(hasQueryValue);
}

function downloadBlob(blob, filename) {
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
}

function formatApiErrorDetail(detail, fallback) {
    if (typeof detail === 'string' && detail.trim()) {
        return detail;
    }

    if (Array.isArray(detail) && detail.length > 0) {
        const formatted = detail
            .map((item) => {
                if (typeof item === 'string' && item.trim()) {
                    return item;
                }

                if (item && typeof item === 'object') {
                    const path = Array.isArray(item.loc)
                        ? item.loc.filter((segment) => segment !== 'body').join('.')
                        : '';
                    const message = typeof item.msg === 'string'
                        ? item.msg
                        : typeof item.message === 'string'
                            ? item.message
                            : '';

                    if (path && message) {
                        return `${path}: ${message}`;
                    }

                    if (message) {
                        return message;
                    }
                }

                return null;
            })
            .filter(Boolean)
            .join('; ');

        if (formatted) {
            return formatted;
        }
    }

    if (detail && typeof detail === 'object') {
        if (typeof detail.message === 'string' && detail.message.trim()) {
            return detail.message;
        }

        if (typeof detail.code === 'string' && detail.code.trim()) {
            return detail.code;
        }
    }

    return fallback;
}

function formatPendingChangesLabel(count) {
    if (!count) {
        return 'No refinements armed';
    }

    return `${count} pending change${count === 1 ? '' : 's'} armed`;
}

function JobBrowser() {
    const [jobs, setJobs] = useState([]);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(null);
    const [searchError, setSearchError] = useState('');
    const [exportError, setExportError] = useState('');
    const [isExporting, setIsExporting] = useState(false);
    const [draftLayer, setDraftLayer] = useState(createEmptyJobBrowserLayer);
    const [activeScope, setActiveScope] = useState(createEmptyJobBrowserScope);
    const [layerSummaries, setLayerSummaries] = useState([]);
    const [filterOptions, setFilterOptions] = useState({
        employment_types: [],
        industries: [],
        job_subcategories: [],
    });
    const [pagination, setPagination] = useState({
        page: 1,
        pageSize: 24,
        total: 0,
        totalPages: 0
    });
    const [selectedJobId, setSelectedJobId] = useState(null);
    const [retrievalMode, setRetrievalMode] = useState('lexical');
    const [capabilities, setCapabilities] = useState(null);
    const [capabilitiesLoading, setCapabilitiesLoading] = useState(true);

    const hasPendingChanges = hasPendingLayerChanges(createEmptyJobBrowserLayer(), draftLayer);
    const pendingChangeCount = countPendingQueryChanges(createEmptyJobBrowserQuery(), {
        search_query: draftLayer.text_expression,
        ...draftLayer.structured_filters,
    });
    const draftDatePreset = getDatePresetForQuery(draftLayer.structured_filters);
    const dateValidationError = getDateValidationError(draftLayer.structured_filters);
    const semanticAvailable = capabilities?.search?.semantic?.available !== false;
    const hybridAvailable = capabilities?.search?.hybrid?.available !== false;

    const fetchJobs = async ({
        scope,
        page,
        pageSize,
        commitScope = false,
        clearDraft = false,
    }) => {
        setIsLoading(true);
        setError(null);
        setExportError('');

        try {
            const response = await fetch(`${API_URL}/api/v1/jobs/search`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    scope,
                    retrieval_mode: retrievalMode,
                    page,
                    page_size: pageSize,
                }),
            });

            if (!response.ok) {
                const payload = await response.json().catch(() => null);
                if (response.status === 422 && payload?.detail?.code === 'invalid_search_expression') {
                    setSearchError(payload.detail.message || 'Search expression is invalid.');
                    return false;
                }

                throw new Error(formatApiErrorDetail(payload?.detail, 'Failed to fetch jobs'));
            }

            const data = await response.json();
            setJobs(data.jobs);
            setPagination((prev) => ({
                ...prev,
                page,
                pageSize,
                total: data.total,
                totalPages: data.total_pages
            }));
            setLayerSummaries(data.layer_summaries || []);

            if (commitScope) {
                setActiveScope(data.applied_scope || scope);
                if (clearDraft) {
                    setDraftLayer(createEmptyJobBrowserLayer());
                }
            }

            setSearchError('');
            return true;
        } catch (err) {
            setError(err.message);
            return false;
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        const fetchFilterOptions = async () => {
            try {
                const [baseResponse, subcategoriesResponse] = await Promise.all([
                    fetch(`${API_URL}/api/v1/jobs/filters`),
                    fetch(`${API_URL}/api/v1/filters/job-subcategories`),
                ]);

                if (baseResponse.ok && subcategoriesResponse.ok) {
                    const [data, jobSubcategories] = await Promise.all([
                        baseResponse.json(),
                        subcategoriesResponse.json(),
                    ]);
                    setFilterOptions({
                        ...data,
                        job_subcategories: jobSubcategories,
                    });
                }
            } catch (err) {
                console.error('Failed to fetch filter options:', err);
            }
        };

        fetchFilterOptions();
        fetchJobs({
            scope: createEmptyJobBrowserScope(),
            page: 1,
            pageSize: pagination.pageSize,
        });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
        let cancelled = false;

        fetchCapabilities()
            .then((payload) => {
                if (!cancelled) {
                    setCapabilities(payload);
                    setCapabilitiesLoading(false);
                }
            })
            .catch(() => {
                if (!cancelled) {
                    setCapabilities(null);
                    setCapabilitiesLoading(false);
                }
            });

        return () => {
            cancelled = true;
        };
    }, []);

    useEffect(() => {
        if ((retrievalMode === 'semantic' && !semanticAvailable) || (retrievalMode === 'hybrid' && !hybridAvailable)) {
            setRetrievalMode('lexical');
        }
    }, [hybridAvailable, retrievalMode, semanticAvailable]);

    const handleSearchChange = (query) => {
        setDraftLayer((prev) => ({
            ...prev,
            text_expression: query,
        }));
    };

    const handleFilterChange = (newFilters) => {
        setDraftLayer((prev) => ({
            ...prev,
            structured_filters: newFilters,
        }));
    };

    const handleResetDraft = () => {
        setDraftLayer(createEmptyJobBrowserLayer());
        setSearchError('');
    };

    const handleDatePresetChange = (preset) => {
        if (preset === 'custom') {
            return;
        }

        setDraftLayer((prev) => ({
            ...prev,
            structured_filters: {
                ...prev.structured_filters,
                ...getDatePresetRange(preset),
            },
        }));
    };

    const handleSearchAllJobs = async () => {
        if (dateValidationError) {
            return;
        }

        const scope = isLayerEmpty(draftLayer)
            ? createEmptyJobBrowserScope()
            : replaceScopeWithLayer(createEmptyJobBrowserScope(), {
                ...draftLayer,
                client_id: 'root',
            });

        await fetchJobs({
            scope,
            page: 1,
            pageSize: pagination.pageSize,
            commitScope: true,
            clearDraft: true,
        });
    };

    const handleSearchWithinResults = async () => {
        if (dateValidationError || isLayerEmpty(draftLayer)) {
            return;
        }

        const scope = appendLayerToScope(activeScope, {
            ...draftLayer,
            client_id: `refine-${activeScope.layers.length}`,
        });

        await fetchJobs({
            scope,
            page: 1,
            pageSize: pagination.pageSize,
            commitScope: true,
            clearDraft: true,
        });
    };

    const handleSubmit = () => {
        if (activeScope.layers.length > 0) {
            handleSearchWithinResults();
            return;
        }
        handleSearchAllJobs();
    };

    const handlePageChange = async (newPage) => {
        await fetchJobs({
            scope: activeScope,
            page: newPage,
            pageSize: pagination.pageSize,
        });
    };

    const handleRemoveLayer = async (clientId) => {
        const nextScope = removeLayerFromScope(activeScope, clientId);
        await fetchJobs({
            scope: nextScope,
            page: 1,
            pageSize: pagination.pageSize,
            commitScope: true,
        });
    };

    const handleExport = async () => {
        setIsExporting(true);
        setExportError('');

        try {
            const response = await fetch(`${API_URL}/api/v1/jobs/search/export`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    scope: activeScope,
                    retrieval_mode: retrievalMode,
                }),
            });

            if (!response.ok) {
                const payload = await response.json().catch(() => null);
                throw new Error(formatApiErrorDetail(payload?.detail, 'Export failed for the current scope'));
            }

            const blob = await response.blob();
            downloadBlob(blob, 'job-search-export.csv');
        } catch (err) {
            setExportError(err.message);
        } finally {
            setIsExporting(false);
        }
    };

    return (
        <div className="job-browser-view">
            <div className="browser-controls">
                <section className="query-console glass-panel">
                    <div className="query-console-top">
                        <div className="query-console-copy">
                            <p className="console-eyebrow">Query Console</p>
                            <h2>Data Explorer</h2>
                            <p className="subtitle">Captured listings, active filters, retrieval mode, and export state.</p>
                        </div>

                        <div className="query-console-status">
                            <span className="console-pill console-pill-primary">
                                {describePostingWindow(draftLayer.structured_filters)}
                            </span>
                            <span className="console-pill">
                                {activeScope.layers.length > 0 ? 'Layered scope active' : 'Open query scope'}
                            </span>
                            <span className="console-pill">
                                {retrievalMode === 'lexical'
                                    ? 'Lexical retrieval'
                                    : retrievalMode === 'hybrid'
                                        ? 'Hybrid retrieval'
                                        : 'Semantic retrieval'}
                            </span>
                            <span className="console-pill console-pill-muted">
                                {hasPendingChanges
                                    ? formatPendingChangesLabel(pendingChangeCount)
                                    : activeScope.layers.length === 0
                                        ? 'No refinements armed'
                                        : `${activeScope.layers.length} applied layers`}
                            </span>
                        </div>
                    </div>

                    <div className="query-console-main">
                        <SearchBar
                            value={draftLayer.text_expression}
                            onChange={handleSearchChange}
                            onSubmit={handleSubmit}
                            isLoading={isLoading}
                            placeholder="Query titles, companies, or deep scan descriptions..."
                        />

                        <div className="query-mode-row">
                            <label className="filter-label" htmlFor="job-browser-retrieval-mode">
                                Retrieval mode
                            </label>
                            <select
                                id="job-browser-retrieval-mode"
                                className="premium-select highlight-select query-mode-select"
                                value={retrievalMode}
                                onChange={(event) => setRetrievalMode(event.target.value)}
                                disabled={isLoading}
                            >
                                <option value="lexical">Lexical</option>
                                <option value="hybrid" disabled={!hybridAvailable}>Hybrid</option>
                                <option value="semantic" disabled={!semanticAvailable}>Semantic</option>
                            </select>
                            <p className="query-mode-note">
                                Current retrieval profile for the submitted search scope.
                            </p>
                        </div>

                        <div className="query-action-row">
                            <button
                                type="button"
                                className="apply-filters-btn"
                                onClick={handleSearchAllJobs}
                                disabled={isLoading || Boolean(dateValidationError)}
                            >
                                Search all jobs
                            </button>
                            {activeScope.layers.length > 0 && (
                                <button
                                    type="button"
                                    className="apply-filters-btn secondary"
                                    onClick={handleSearchWithinResults}
                                    disabled={isLoading || Boolean(dateValidationError) || isLayerEmpty(draftLayer)}
                                >
                                    Search within results
                                </button>
                            )}
                        </div>

                        {searchError && (
                            <p className="filter-validation-message query-validation-message">{searchError}</p>
                        )}

                        <div className="query-console-results">
                            <div>
                                <span className="query-console-results-label">Matched jobs</span>
                                <strong>{pagination.total.toLocaleString()}</strong>
                            </div>
                            <div>
                                <span className="query-console-results-label">Page</span>
                                <strong>{pagination.page} / {Math.max(pagination.totalPages || 1, 1)}</strong>
                            </div>
                        </div>

                        <div className="query-action-row query-export-row">
                            <button
                                type="button"
                                className="apply-filters-btn secondary"
                                onClick={handleExport}
                                disabled={isExporting || pagination.total === 0}
                            >
                                {isExporting ? 'Exporting...' : `Export ${pagination.total} results`}
                            </button>
                        </div>

                        {hasPendingChanges && (
                            <p className="query-export-note">Export uses current results, not pending edits.</p>
                        )}
                        {exportError && (
                            <p className="filter-validation-message query-validation-message">{exportError}</p>
                        )}
                    </div>
                </section>

                <FilterPanel
                    filters={draftLayer.structured_filters}
                    onFilterChange={handleFilterChange}
                    onReset={handleResetDraft}
                    onDatePresetChange={handleDatePresetChange}
                    filterOptions={filterOptions}
                    isLoading={isLoading}
                    datePreset={draftDatePreset}
                    validationError={dateValidationError}
                    pendingChangeCount={pendingChangeCount}
                />
            </div>

            <div className="job-results-area">
                {activeScope.layers.length > 0 && (
                    <div className="scope-trail glass-panel" aria-label="Active scope trail">
                        {layerSummaries.map((summary) => (
                            <div key={summary.client_id} className="scope-trail-item">
                                <span>{summary.label}</span>
                                <button
                                    type="button"
                                    className="scope-remove-btn"
                                    onClick={() => handleRemoveLayer(summary.client_id)}
                                >
                                    Remove layer
                                </button>
                            </div>
                        ))}
                    </div>
                )}

                {error && <div className="error-message glass-panel">System Error: {error}</div>}

                {isLoading ? (
                    <div className="loading-state">
                        <Activity className="spinner" size={32} />
                        <p>Querying Databanks...</p>
                    </div>
                ) : jobs.length === 0 ? (
                    <div className="no-results glass-panel">
                        <BrainCircuit size={48} className="empty-icon" />
                        <h3>No Jobs Found</h3>
                        <p>Adjust your parameters to broaden the search.</p>
                    </div>
                ) : (
                    <>
                        <div className="results-summary-bar glass-panel">
                            <div>
                                <span className="results-summary-label">Live slice</span>
                                <strong>{jobs.length} jobs on this page</strong>
                            </div>
                            <div>
                                <span className="results-summary-label">Scope</span>
                                <strong>{activeScope.layers.length > 0 ? `${activeScope.layers.length} applied layers` : 'All jobs'}</strong>
                            </div>
                        </div>

                        <div className="job-grid">
                            {jobs.map((job) => (
                                <div
                                    key={job.id}
                                    className="job-card glass-panel"
                                    onClick={() => setSelectedJobId(job.id)}
                                >
                                    <div className="job-card-header">
                                        <h3 className="job-title">{job.title}</h3>
                                        <button type="button" className="view-btn">
                                            <ExternalLink size={16} />
                                        </button>
                                    </div>

                                    <div className="job-meta-grid">
                                        <div className="meta-item">
                                            <Building2 size={16} className="meta-icon" />
                                            <span>{job.company_name}</span>
                                        </div>
                                        <div className="meta-item">
                                            <MapPin size={16} className="meta-icon" />
                                            <span>{job.location}</span>
                                        </div>
                                        {job.posted_date && (
                                            <div className="meta-item meta-item-date">
                                                <CalendarDays size={16} className="meta-icon" />
                                                <span>Posted {formatPostedDate(job.posted_date)}</span>
                                            </div>
                                        )}
                                    </div>

                                    <div className="job-tags-area">
                                        {job.employment_type && <span className="tag type-tag">{job.employment_type}</span>}
                                        {getJobTaxonomyPath(job) && (
                                            <span className="tag ai-tag">
                                                <BrainCircuit size={12} />
                                                {getJobTaxonomyPath(job)}
                                            </span>
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>

                        <Pagination
                            page={pagination.page}
                            totalPages={pagination.totalPages}
                            total={pagination.total}
                            onPageChange={handlePageChange}
                            isLoading={isLoading}
                        />
                    </>
                )}
            </div>

            {selectedJobId && (
                <JobDetailModal
                    jobId={selectedJobId}
                    apiUrl={API_URL}
                    capabilities={capabilities}
                    capabilitiesLoading={capabilitiesLoading}
                    onClose={() => setSelectedJobId(null)}
                />
            )}
        </div>
    );
}

export default JobBrowser;
