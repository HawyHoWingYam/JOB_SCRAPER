import React, { useEffect, useRef, useState } from 'react';
import { Building2, MapPin, CalendarDays, BrainCircuit, ExternalLink, Activity } from 'lucide-react';
import SearchBar from './SearchBar';
import FilterPanel from './FilterPanel';
import PaginationControl from './PaginationControl';
import JobDetailModal from './JobDetailModal';
import { API_BASE_URL, apiPath } from '../api/base';
import { formatApiErrorDetail } from '../api/errors';
import { fetchCapabilities } from '../api/capabilities';
import { hashForJobsRoute, parseJobsRoute } from '../appRoute';
import {
    createEmptyJobBrowserLayer,
    createEmptyJobBrowserScope,
    appendLayerToScope,
    hasPendingLayerChanges,
    normalizeLayerForSubmit,
    removeLayerFromScope,
    replaceLayerInScope,
    replaceScopeWithLayer,
} from './jobBrowserScopeUtils';
import {
    clearJobBrowserSession,
    readJobBrowserSession,
    writeJobBrowserSession,
} from './jobBrowserSessionStorage';
import { summarizeJobBrowserLayer } from './jobBrowserLayerSummary';
import {
    countPendingQueryChanges,
    getDatePresetForQuery,
    getDatePresetRange,
    getDateValidationError,
} from './jobBrowserQueryUtils';
import './JobBrowser.css';

function hasQueryValue(value) {
    if (Array.isArray(value)) {
        return value.length > 0;
    }
    return value !== '' && value != null;
}

function getCanonicalTaxonomyLabel(job) {
    if (job?.canonical_taxonomy_availability?.available === false) {
        return 'Canonical Job Taxonomy: Unavailable';
    }

    const canonicalState = job?.canonical_taxonomy;
    if (canonicalState?.state === 'unassigned') {
        return 'Canonical Job Taxonomy: Unassigned';
    }

    const breadcrumb = canonicalState?.assignment?.breadcrumb;
    if (canonicalState?.state === 'assigned' && breadcrumb) {
        const labels = [
            breadcrumb.domain?.label,
            breadcrumb.category?.label,
            breadcrumb.subcategory?.label,
        ].filter(Boolean);
        if (labels.length === 3) {
            return `Canonical Job Taxonomy: ${labels.join(' / ')}`;
        }
    }

    return 'Canonical Job Taxonomy: Unknown';
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

function formatPendingChangesLabel(count) {
    if (!count) {
        return 'No refinements armed';
    }

    return `${count} pending change${count === 1 ? '' : 's'} armed`;
}

function createScopeFromRouteHash(routeHash) {
    const route = parseJobsRoute(routeHash);
    if (
        route.canonicalSubcategoryIds.length === 0
        && route.skillIds.length === 0
    ) {
        return createEmptyJobBrowserScope();
    }

    const layer = createEmptyJobBrowserLayer('root');
    layer.structured_filters = {
        ...layer.structured_filters,
        canonical_subcategory_ids: route.canonicalSubcategoryIds,
        skill_ids: route.skillIds,
    };
    return replaceScopeWithLayer(createEmptyJobBrowserScope(), layer);
}

function routeFiltersFromScope(scope) {
    if (!scope?.layers?.length) {
        return { canonicalSubcategoryIds: [], skillIds: [] };
    }
    if (scope.layers.length !== 1) return null;

    const layer = normalizeLayerForSubmit(scope.layers[0]);
    if (layer.text_expression) return null;

    const supportedKeys = new Set(['canonical_subcategory_ids', 'skill_ids']);
    const hasUnsupportedFilter = Object.entries(layer.structured_filters).some(
        ([key, value]) => !supportedKeys.has(key) && hasQueryValue(value),
    );
    if (hasUnsupportedFilter) return null;

    return {
        canonicalSubcategoryIds:
            layer.structured_filters.canonical_subcategory_ids || [],
        skillIds: layer.structured_filters.skill_ids || [],
    };
}

function getJobBrowserSessionStorage() {
    if (typeof window === 'undefined') return null;
    try {
        return window.sessionStorage;
    } catch {
        return null;
    }
}

function JobBrowser({
    routeHash = typeof window === 'undefined' ? '#jobs' : window.location.hash,
}) {
    const searchRequestSequenceRef = useRef(0);
    const searchAbortControllerRef = useRef(null);
    const lastWrittenRouteHashRef = useRef(null);
    const [jobs, setJobs] = useState([]);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(null);
    const [searchError, setSearchError] = useState('');
    const [exportError, setExportError] = useState('');
    const [isExporting, setIsExporting] = useState(false);
    const [draftLayer, setDraftLayer] = useState(createEmptyJobBrowserLayer);
    const [activeScope, setActiveScope] = useState(createEmptyJobBrowserScope);
    const [editingLayerId, setEditingLayerId] = useState(null);
    const [filterOptions, setFilterOptions] = useState({
        sources: [],
        employment_types: [],
        source_classifications: [],
        canonical_job_taxonomy: [],
        company_industries: [],
        canonical_taxonomy: { domains: [] },
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

    const draftBaselineLayer = editingLayerId
        ? activeScope.layers.find((layer) => layer.client_id === editingLayerId)
            || createEmptyJobBrowserLayer()
        : createEmptyJobBrowserLayer();
    const hasPendingChanges = hasPendingLayerChanges(draftBaselineLayer, draftLayer);
    const pendingChangeCount = countPendingQueryChanges({
        search_query: draftBaselineLayer.text_expression,
        ...draftBaselineLayer.structured_filters,
    }, {
        search_query: draftLayer.text_expression,
        ...draftLayer.structured_filters,
    });
    const draftDatePreset = getDatePresetForQuery(draftLayer.structured_filters);
    const dateValidationError = getDateValidationError(draftLayer.structured_filters);
    const semanticAvailable = capabilities?.search?.semantic?.available !== false;
    const hybridAvailable = capabilities?.search?.hybrid?.available !== false;

    const syncRouteToScope = (scope) => {
        if (typeof window === 'undefined') return;
        const routeFilters = routeFiltersFromScope(scope);
        const nextHash = routeFilters ? hashForJobsRoute(routeFilters) : '#jobs';
        if (window.location.hash === nextHash) return;
        lastWrittenRouteHashRef.current = nextHash;
        window.location.hash = nextHash;
    };

    const fetchJobs = async ({
        scope,
        page,
        pageSize,
        commitScope = false,
        clearDraft = false,
        includeFacets = true,
    }) => {
        const requestSequence = searchRequestSequenceRef.current + 1;
        searchRequestSequenceRef.current = requestSequence;
        searchAbortControllerRef.current?.abort();
        const controller = new AbortController();
        searchAbortControllerRef.current = controller;
        const isLatestRequest = () => (
            searchRequestSequenceRef.current === requestSequence
            && !controller.signal.aborted
        );

        setIsLoading(true);
        setError(null);
        setExportError('');

        try {
            const response = await fetch(apiPath('/jobs/search'), {
                method: 'POST',
                signal: controller.signal,
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    scope,
                    retrieval_mode: retrievalMode,
                    page,
                    page_size: pageSize,
                    include_facets: includeFacets,
                }),
            });

            if (!isLatestRequest()) {
                return false;
            }

            if (!response.ok) {
                const payload = await response.json().catch(() => null);
                if (!isLatestRequest()) {
                    return false;
                }
                if (response.status === 422 && payload?.detail?.code === 'invalid_search_expression') {
                    setSearchError(payload.detail.message || 'Search expression is invalid.');
                    return false;
                }

                throw new Error(formatApiErrorDetail(payload?.detail, 'Failed to fetch jobs'));
            }

            const data = await response.json();
            if (!isLatestRequest()) {
                return false;
            }
            setJobs(data.jobs);
            setPagination((prev) => ({
                ...prev,
                page,
                pageSize,
                total: data.total,
                totalPages: data.total_pages
            }));
            if (data.facets) {
                setFilterOptions(data.facets);
            }

            if (commitScope) {
                const committedScope = data.applied_scope || scope;
                setActiveScope(committedScope);
                writeJobBrowserSession(
                    getJobBrowserSessionStorage(),
                    committedScope,
                );
                if (clearDraft) {
                    setDraftLayer(createEmptyJobBrowserLayer());
                }
            }

            setSearchError('');
            return true;
        } catch (err) {
            if (!isLatestRequest() || err?.name === 'AbortError') {
                return false;
            }
            setError(err.message);
            return false;
        } finally {
            if (searchRequestSequenceRef.current === requestSequence) {
                if (searchAbortControllerRef.current === controller) {
                    searchAbortControllerRef.current = null;
                }
                setIsLoading(false);
            }
        }
    };

    useEffect(() => {
        return () => {
            searchRequestSequenceRef.current += 1;
            searchAbortControllerRef.current?.abort();
            searchAbortControllerRef.current = null;
        };
    }, []);

    useEffect(() => {
        const normalizedRouteHash = String(routeHash || '#jobs');
        if (lastWrittenRouteHashRef.current === normalizedRouteHash) {
            lastWrittenRouteHashRef.current = null;
            return;
        }

        const routeScope = createScopeFromRouteHash(normalizedRouteHash);
        const scope = routeScope.layers.length > 0
            ? routeScope
            : readJobBrowserSession(getJobBrowserSessionStorage())
                || createEmptyJobBrowserScope();
        setSelectedJobId(null);
        setEditingLayerId(null);
        setDraftLayer(createEmptyJobBrowserLayer());
        fetchJobs({
            scope,
            page: 1,
            pageSize: pagination.pageSize,
            commitScope: true,
            clearDraft: true,
        });
        // fetchJobs intentionally follows the route boundary, not render identity.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [routeHash]);

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

    const handleDiscardDraft = () => {
        setDraftLayer(createEmptyJobBrowserLayer());
        setEditingLayerId(null);
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

        const succeeded = await fetchJobs({
            scope,
            page: 1,
            pageSize: pagination.pageSize,
            commitScope: true,
            clearDraft: true,
        });
        if (succeeded) syncRouteToScope(scope);
    };

    const handleSearchWithinResults = async () => {
        if (dateValidationError || isLayerEmpty(draftLayer)) {
            return;
        }

        let refinementIndex = activeScope.layers.length;
        while (activeScope.layers.some(
            (layer) => layer.client_id === `refine-${refinementIndex}`,
        )) {
            refinementIndex += 1;
        }
        const scope = appendLayerToScope(activeScope, {
            ...draftLayer,
            client_id: `refine-${refinementIndex}`,
        });

        const succeeded = await fetchJobs({
            scope,
            page: 1,
            pageSize: pagination.pageSize,
            commitScope: true,
            clearDraft: true,
        });
        if (succeeded) syncRouteToScope(scope);
    };

    const handleSubmit = () => {
        if (editingLayerId) {
            handleSaveLayer();
            return;
        }
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
            includeFacets: false,
        });
    };

    const handleEditLayer = (clientId) => {
        const layer = activeScope.layers.find(
            (candidate) => candidate.client_id === clientId,
        );
        if (!layer) return;
        setDraftLayer(normalizeLayerForSubmit(layer));
        setEditingLayerId(clientId);
        setSearchError('');
    };

    const handleSaveLayer = async () => {
        if (!editingLayerId || dateValidationError || isLayerEmpty(draftLayer)) {
            return;
        }
        const nextScope = replaceLayerInScope(
            activeScope,
            editingLayerId,
            draftLayer,
        );
        const succeeded = await fetchJobs({
            scope: nextScope,
            page: 1,
            pageSize: pagination.pageSize,
            commitScope: true,
            clearDraft: true,
        });
        if (succeeded) {
            setEditingLayerId(null);
            syncRouteToScope(nextScope);
        }
    };

    const handleRemoveLayer = async (clientId) => {
        const nextScope = removeLayerFromScope(activeScope, clientId);
        const succeeded = await fetchJobs({
            scope: nextScope,
            page: 1,
            pageSize: pagination.pageSize,
            commitScope: true,
        });
        if (succeeded) {
            if (editingLayerId === clientId) {
                setEditingLayerId(null);
                setDraftLayer(createEmptyJobBrowserLayer());
            }
            syncRouteToScope(nextScope);
        }
    };

    const handleClearAllLayers = async () => {
        const nextScope = createEmptyJobBrowserScope();
        const succeeded = await fetchJobs({
            scope: nextScope,
            page: 1,
            pageSize: pagination.pageSize,
            commitScope: true,
            clearDraft: true,
        });
        if (succeeded) {
            setEditingLayerId(null);
            clearJobBrowserSession(getJobBrowserSessionStorage());
            syncRouteToScope(nextScope);
        }
    };

    const handleExport = async () => {
        setIsExporting(true);
        setExportError('');

        try {
            const response = await fetch(apiPath('/jobs/search/export'), {
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
                            {editingLayerId ? (
                                <button
                                    type="button"
                                    className="apply-filters-btn"
                                    onClick={handleSaveLayer}
                                    disabled={isLoading || Boolean(dateValidationError) || isLayerEmpty(draftLayer)}
                                >
                                    Save layer
                                </button>
                            ) : (
                                <button
                                    type="button"
                                    className="apply-filters-btn"
                                    onClick={handleSearchAllJobs}
                                    disabled={isLoading || Boolean(dateValidationError)}
                                >
                                    Search all jobs
                                </button>
                            )}
                            {!editingLayerId && activeScope.layers.length > 0 && (
                                <button
                                    type="button"
                                    className="apply-filters-btn secondary"
                                    onClick={handleSearchWithinResults}
                                    disabled={isLoading || Boolean(dateValidationError) || isLayerEmpty(draftLayer)}
                                >
                                    Refine current results
                                </button>
                            )}
                            {(editingLayerId || hasPendingChanges) && (
                                <button
                                    type="button"
                                    className="apply-filters-btn secondary"
                                    onClick={handleDiscardDraft}
                                    disabled={isLoading}
                                >
                                    Discard changes
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
                        {activeScope.layers.map((layer, index) => (
                            <div key={layer.client_id} className="scope-trail-item">
                                <div>
                                    <strong>Layer {index + 1}</strong>
                                    <ul>
                                        {summarizeJobBrowserLayer(layer, filterOptions).map(
                                            (summary) => <li key={summary}>{summary}</li>,
                                        )}
                                    </ul>
                                </div>
                                <button
                                    type="button"
                                    className="scope-remove-btn"
                                    onClick={() => handleEditLayer(layer.client_id)}
                                    disabled={isLoading}
                                >
                                    Edit layer
                                </button>
                                <button
                                    type="button"
                                    className="scope-remove-btn"
                                    onClick={() => handleRemoveLayer(layer.client_id)}
                                    disabled={isLoading}
                                >
                                    Remove layer
                                </button>
                            </div>
                        ))}
                        <button
                            type="button"
                            className="scope-remove-btn"
                            onClick={handleClearAllLayers}
                            disabled={isLoading}
                        >
                            Clear all layers
                        </button>
                    </div>
                )}

                {error ? (
                    <div className="error-message glass-panel" role="alert">
                        System Error: {error}
                    </div>
                ) : isLoading ? (
                    <div className="loading-state" role="status" aria-live="polite">
                        <Activity className="spinner" size={32} aria-hidden="true" />
                        <p>Querying jobs…</p>
                    </div>
                ) : jobs.length === 0 ? (
                    <div className="no-results glass-panel" role="status" aria-live="polite">
                        <BrainCircuit size={48} className="empty-icon" aria-hidden="true" />
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
                                <article
                                    key={job.id}
                                    className="job-card glass-panel"
                                    aria-label={`${job.title} at ${job.company_name}`}
                                >
                                    <div className="job-card-header">
                                        <h3 className="job-title">{job.title}</h3>
                                        <button
                                            type="button"
                                            className="view-btn"
                                            aria-label={`View ${job.title} at ${job.company_name}`}
                                            onClick={() => setSelectedJobId(job.id)}
                                        >
                                            <ExternalLink size={16} aria-hidden="true" />
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
                                        {job.employment_types?.length > 0 ? (
                                            job.employment_types.map((employmentType) => (
                                                <span key={employmentType.code} className="tag type-tag">
                                                    {employmentType.label}
                                                </span>
                                            ))
                                        ) : (
                                            <span className="tag type-tag">Employment Type: Unknown</span>
                                        )}
                                        <span className="tag ai-tag">
                                            <BrainCircuit size={12} aria-hidden="true" />
                                            {getCanonicalTaxonomyLabel(job)}
                                        </span>
                                    </div>
                                </article>
                            ))}
                        </div>

                        <PaginationControl
                            page={pagination.page}
                            totalPages={pagination.totalPages}
                            totalItems={pagination.total}
                            isLoading={isLoading}
                            onPageChange={handlePageChange}
                            summaryText={`Page ${pagination.page} of ${Math.max(pagination.totalPages || 1, 1)} (${pagination.total} jobs)`}
                            hideWhenSinglePage
                        />
                    </>
                )}
            </div>

            {selectedJobId && (
                <JobDetailModal
                    jobId={selectedJobId}
                    apiUrl={API_BASE_URL}
                    capabilities={capabilities}
                    capabilitiesLoading={capabilitiesLoading}
                    onClose={() => setSelectedJobId(null)}
                />
            )}
        </div>
    );
}

export default JobBrowser;
