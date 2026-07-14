import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Plus, Zap, AlertTriangle, CalendarClock, X } from 'lucide-react';
import { apiFetchJson } from '../../api/client';
import { API_BASE_URL, apiPath } from '../../api/base';
import { createMonitoringId, logError } from '../../monitoring';
import ScheduleForm from './ScheduleForm';
import ScheduleList from './ScheduleList';
import ScheduleHistory from './ScheduleHistory';
import ScrapeProgressPanel from './ScrapeProgressPanel';
import { getCrawlModeOptionsForSource, resolveDefaultCrawlMode } from './crawlMode';
import { CRAWL_PHASE_OPTIONS, resolveDefaultCrawlPhase } from './crawlPhase';
import { sourceRequiresExternalHeadedWorker } from './headedRuntime';
import { resolveDefaultMaxPages } from './maxPages';
import {
    formatListingBatchIdentity,
    formatListingBatchOptionLabel,
    formatScraperSourceLabel,
} from './listingBatchLabel';
import './Scheduler.css';

const API_BASE = apiPath('');
const CATEGORY_API_BASE = `${API_BASE_URL}/api`;
const DEFAULT_MANUAL_ACTION_HELPER_URL = 'http://127.0.0.1:47652';
const DIRECT_OVERRIDE_RUN_KEY = 'scheduler.directOverrideRun';
const DIRECT_OVERRIDE_RECOVERY_WINDOW_MS = 20_000;
const EMPTY_PROGRESS = {};
const EMPTY_SOURCE_CATALOG = {};

function readDirectOverrideRunMarker() {
    try {
        const rawValue = window.sessionStorage.getItem(DIRECT_OVERRIDE_RUN_KEY);
        if (!rawValue) {
            return null;
        }

        const parsed = JSON.parse(rawValue);
        if (!parsed || typeof parsed !== 'object') {
            return null;
        }

        if (typeof parsed.sourceSite !== 'string' || typeof parsed.startedAt !== 'string') {
            return null;
        }

        if (Number.isNaN(new Date(parsed.startedAt).getTime())) {
            return null;
        }

        return {
            crawlJobId: typeof parsed.crawlJobId === 'string' ? parsed.crawlJobId : null,
            sourceSite: parsed.sourceSite,
            startedAt: parsed.startedAt,
        };
    } catch {
        return null;
    }
}

function writeDirectOverrideRunMarker(marker) {
    window.sessionStorage.setItem(DIRECT_OVERRIDE_RUN_KEY, JSON.stringify(marker));
}

function clearDirectOverrideRunMarker() {
    window.sessionStorage.removeItem(DIRECT_OVERRIDE_RUN_KEY);
}

function isFreshDirectOverrideRunMarker(marker) {
    if (!marker) {
        return false;
    }

    const startedAtMs = new Date(marker.startedAt).getTime();
    if (Number.isNaN(startedAtMs)) {
        return false;
    }

    return Date.now() - startedAtMs <= DIRECT_OVERRIDE_RECOVERY_WINDOW_MS;
}

function attachRequestId(error, requestId, fallbackMessage = 'Request failed') {
    const resolvedError = error instanceof Error
        ? error
        : new Error(typeof error === 'string' && error ? error : fallbackMessage);

    if (typeof resolvedError.requestId !== 'string') {
        resolvedError.requestId = requestId;
    }

    return resolvedError;
}

async function apiFetchJsonWithMonitoring(url, {
    failureEvent,
    failureContext = null,
    fallbackMessage = 'Request failed',
    requestId = createMonitoringId('req'),
    ...options
} = {}) {
    try {
        return await apiFetchJson(url, {
            ...options,
            requestId,
        });
    } catch (err) {
        const detail = err instanceof Error && err.message
            ? err.message
            : fallbackMessage;

        logError(failureEvent, {
            ...(failureContext || {}),
            requestId,
            detail,
        });

        throw attachRequestId(err, requestId, fallbackMessage);
    }
}

function normalizeCategoryIdsForSource(sourceSite, categoryIds) {
    if (!Array.isArray(categoryIds)) {
        return [];
    }

    if (sourceSite === 'offertoday') {
        return categoryIds
            .map((value) => Number.parseInt(`${value}`, 10))
            .filter((value) => Number.isInteger(value));
    }

    if (sourceSite === 'ctgoodjobs') {
        return categoryIds.filter(
            (value) => typeof value === 'string' && value.startsWith('ctgoodjobs:')
        );
    }

    return categoryIds
        .map((value) => Number.parseInt(`${value}`, 10))
        .filter((value) => Number.isInteger(value));
}

function buildImmediateScrapePayload(form, sourceSite, sourceCatalog = EMPTY_SOURCE_CATALOG) {
    const crawlPhase = form?.crawl_phase || resolveDefaultCrawlPhase();
    const categoryIds = normalizeCategoryIdsForSource(sourceSite, form?.category_ids);
    const maxPages = Number.parseInt(`${form?.max_pages ?? ''}`, 10);
    const detailLimit = Number.parseInt(`${form?.detail_limit ?? ''}`, 10);
    const sourceListingCrawlJobId = `${form?.source_listing_crawl_job_id ?? ''}`.trim();

    if (crawlPhase === 'listing' && categoryIds.length === 0 && sourceSite !== 'offertoday') {
        return {
            error: 'Please select at least one category.',
        };
    }

    if (crawlPhase === 'listing' && (!Number.isInteger(maxPages) || maxPages < 1 || maxPages > 9999)) {
        return {
            error: 'Max pages must be a whole number between 1 and 1000.',
        };
    }

    if (crawlPhase === 'detail' && categoryIds.length === 0 && !sourceListingCrawlJobId) {
        return {
            error: 'Detail runs need categories or a source listing crawl job ID.',
        };
    }

    if (crawlPhase === 'detail' && (!Number.isInteger(detailLimit) || detailLimit < 1 || detailLimit > 5000)) {
        return {
            error: 'Detail batch size must be a whole number between 1 and 5000.',
        };
    }

    return {
        payload: {
            source_site: sourceSite,
            crawl_phase: crawlPhase,
            crawl_mode: form?.crawl_mode || resolveDefaultCrawlMode(sourceSite, sourceCatalog),
            category_ids: categoryIds,
            max_pages: Number.isInteger(maxPages) ? maxPages : resolveDefaultMaxPages(sourceSite, sourceCatalog),
            detail_limit: crawlPhase === 'detail' ? detailLimit : 100,
            // For listing/full phases: skip re-staging jobs already in the DB.
            // For detail phase: always process the backlog — failed/pending rows need retrying.
            skip_existing: crawlPhase !== 'detail',
            ...(sourceListingCrawlJobId ? { source_listing_crawl_job_id: sourceListingCrawlJobId } : {}),
        },
    };
}

function formatRuntimeTimestamp(value) {
    if (!value) {
        return 'Unknown';
    }

    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return `${value}`;
    }

    return parsed.toLocaleString('en-US');
}

function formatBacklogCount(value) {
    return Number(value || 0).toLocaleString();
}

function hasEligibleListingBatchDetailWork(batch) {
    if (`${batch?.status || ''}`.trim().toLowerCase() !== 'completed') {
        return false;
    }
    return [
        batch?.detail_pending,
        batch?.detail_failed,
        batch?.detail_manual_action_required,
    ].some((value) => Number(value || 0) > 0);
}

function findNewestEligibleListingBatch(batches) {
    return (batches || [])
        .filter(hasEligibleListingBatchDetailWork)
        .reduce((newest, batch) => {
            if (!newest) {
                return batch;
            }

            const batchTimestamp = Date.parse(
                batch?.queued_at || batch?.created_at || batch?.completed_at || ''
            );
            const newestTimestamp = Date.parse(
                newest?.queued_at || newest?.created_at || newest?.completed_at || ''
            );
            const normalizedBatchTimestamp = Number.isFinite(batchTimestamp) ? batchTimestamp : 0;
            const normalizedNewestTimestamp = Number.isFinite(newestTimestamp) ? newestTimestamp : 0;
            if (normalizedBatchTimestamp !== normalizedNewestTimestamp) {
                return normalizedBatchTimestamp > normalizedNewestTimestamp ? batch : newest;
            }

            return `${batch?.crawl_job_id || ''}`.localeCompare(
                `${newest?.crawl_job_id || ''}`
            ) > 0
                ? batch
                : newest;
        }, null);
}

function formatSourceLabel(sourceSite) {
    return formatScraperSourceLabel(sourceSite);
}

function buildManualActionHelperUnavailableMessage(actionLabel) {
    return `Manual-action helper is unavailable. Start the dedicated helper service and retry ${actionLabel}.`;
}

function buildHeadedWorkerUnavailableMessage(headedWorkerStatus) {
    const heartbeatStatus = `${headedWorkerStatus?.heartbeat_status || ''}`.trim().toLowerCase();
    const startCommand = headedWorkerStatus?.start_command || 'python backend\\scripts\\prepare_headed_crawl_worker_host.py';

    if (heartbeatStatus === 'stale') {
        return `Headed crawl worker is offline. Restart ${startCommand} before launching a headed run.`;
    }

    return `Headed crawl worker is offline. Start ${startCommand} before launching a headed run.`;
}

function buildSchedulerRuntimeBanner(scheduler) {
    if (!scheduler || scheduler.available !== false) {
        return null;
    }

    const owner = scheduler.worker_name || scheduler.owner || 'scheduler-worker';
    const manualRunAvailable = scheduler.manual_run_available !== false;

    if (scheduler.heartbeat_status === 'stale' && manualRunAvailable) {
        return {
            title: 'Scheduler automation paused',
            lines: [
                `Manual runs are still available while ${owner} recovers.`,
                scheduler.last_heartbeat_at
                    ? `Last heartbeat: ${formatRuntimeTimestamp(scheduler.last_heartbeat_at)}`
                    : 'Last heartbeat: unknown',
            ],
        };
    }

    if (scheduler.heartbeat_status === 'missing' && manualRunAvailable) {
        return {
            title: 'Scheduler worker not reporting',
            lines: [
                `Manual runs are still available, but ${owner} is offline for cron dispatch.`,
            ],
        };
    }

    return {
        title: 'Scheduler dispatch unavailable',
        lines: ['Scheduler dispatch is unavailable in the current runtime profile.'],
    };
}

function formatSectorSelectionLabel(selectedCount) {
    return `${selectedCount} sector${selectedCount === 1 ? '' : 's'} selected`;
}

function formatOfferTodayListingScopeLabel(selectedCount) {
    return selectedCount === 0 ? '全 IT 分類（預設）' : formatSectorSelectionLabel(selectedCount);
}

function buildSelectedSectorSummary(form, categories) {
    const selectedIds = new Set(
        Array.isArray(form?.category_ids)
            ? form.category_ids.map((categoryId) => `${categoryId}`)
            : []
    );
    const selectedNames = categories
        .filter((category) => selectedIds.has(`${category.id}`))
        .map((category) => category.name);

    if (selectedNames.length === 0) {
        return 'Sectors: none selected';
    }

    return `Sectors: ${selectedNames.join(', ')}`;
}

function formatImmediateListingDepthMetric(maxPages, sourceSite, selectedSectorCount) {
    if (!Number.isInteger(maxPages)) {
        return 'Page limit not set';
    }
    if (maxPages < 1 || maxPages > 9999) {
        return 'Page limit invalid';
    }
    if (sourceSite === 'offertoday' && selectedSectorCount === 0) {
        return `${maxPages} pages across 全 IT 分類（預設）`;
    }
    return `${maxPages} pages per sector`;
}

function formatImmediateDetailLimitMetric(detailLimit) {
    if (!Number.isInteger(detailLimit)) {
        return 'Detail limit not set';
    }
    if (detailLimit < 1 || detailLimit > 5000) {
        return 'Detail limit invalid';
    }
    return `Up to ${detailLimit} job details to crawl`;
}

function buildImmediateRunSummary(form, sourceSite, categories) {
    const crawlPhase = form?.crawl_phase || resolveDefaultCrawlPhase();
    const selectedSectorCount = Array.isArray(form?.category_ids) ? form.category_ids.length : 0;
    const summaryMetrics = [formatSourceLabel(sourceSite)];

    if (crawlPhase === 'detail') {
        const detailLimit = Number.parseInt(`${form?.detail_limit ?? ''}`, 10);
        const listingBatchId = `${form?.source_listing_crawl_job_id ?? ''}`.trim();

        summaryMetrics.push(
            formatImmediateDetailLimitMetric(detailLimit),
            'Eligible backlog: pending, failed, manual review',
            buildSelectedSectorSummary(form, categories)
        );

        if (listingBatchId) {
            summaryMetrics.push(
                `Listing batch scope: ${formatListingBatchIdentity({
                    sourceSite,
                    crawlJobId: listingBatchId,
                })}`
            );
        }

        return {
            title: 'Immediate Run for Backlog Recovery',
            description: 'This run will recover detail backlog from the selected source and sectors.',
            metrics: summaryMetrics,
            actionLabel: 'Start Job Detail Crawl',
        };
    }

    const maxPages = Number.parseInt(`${form?.max_pages ?? ''}`, 10);

    summaryMetrics.push(
        sourceSite === 'offertoday'
            ? formatOfferTodayListingScopeLabel(selectedSectorCount)
            : formatSectorSelectionLabel(selectedSectorCount),
        formatImmediateListingDepthMetric(maxPages, sourceSite, selectedSectorCount)
    );

    return {
        title: 'Immediate Run for Backlog Recovery',
        description: 'This run will start a job ID crawl.',
        metrics: summaryMetrics,
        actionLabel: 'Start Job ID Crawl',
    };
}

function buildImmediateRunReadiness(
    form,
    sourceSite,
    sourceCatalog = EMPTY_SOURCE_CATALOG,
    headedWorkerStatus = null,
) {
    const request = buildImmediateScrapePayload(form, sourceSite, sourceCatalog);
    const crawlPhase = form?.crawl_phase || resolveDefaultCrawlPhase();
    const crawlMode = form?.crawl_mode || resolveDefaultCrawlMode(sourceSite, sourceCatalog);
    const selectedSectorCount = Array.isArray(form?.category_ids) ? form.category_ids.length : 0;
    const hasBatchFilter = Boolean(`${form?.source_listing_crawl_job_id ?? ''}`.trim());

    // Only runtimes that explicitly depend on an external headed worker should block launch here.
    if (
        crawlMode === 'headed'
        && sourceRequiresExternalHeadedWorker(sourceSite, sourceCatalog)
        && headedWorkerStatus?.available === false
    ) {
        return {
            isReady: false,
            statusLabel: 'Headed worker offline',
            detail: buildHeadedWorkerUnavailableMessage(headedWorkerStatus),
        };
    }

    if (request.error) {
        let detail = request.error;

        if (crawlPhase === 'listing' && selectedSectorCount === 0 && sourceSite !== 'offertoday') {
            detail = 'Select at least one sector to launch this listing crawl.';
        } else if (crawlPhase === 'detail' && selectedSectorCount === 0 && !hasBatchFilter) {
            detail = 'Select sectors or a listing batch before launching this detail recovery run.';
        }

        return {
            isReady: false,
            statusLabel: 'Launch blocked',
            detail,
        };
    }

    return {
        isReady: true,
        statusLabel: 'Ready to launch',
        detail: crawlPhase === 'listing'
            ? (sourceSite === 'offertoday' && selectedSectorCount === 0
                ? 'Listing crawl will use 全 IT 分類（預設）.'
                : `Listing crawl will scan ${selectedSectorCount} selected sector${selectedSectorCount === 1 ? '' : 's'}.`)
            : hasBatchFilter
                ? 'Detail crawl will use only the selected listing batch, including keyword and hybrid rows.'
                : 'Detail crawl will use global category backlog across matching listing batches.',
    };
}

function buildImmediateRunModeCopy(form) {
    const crawlPhase = form?.crawl_phase || resolveDefaultCrawlPhase();

    if (crawlPhase === 'detail') {
        return {
            eyebrow: 'Detail Mode',
            title: 'Recover eligible detail backlog',
            description: 'Use a listing batch for complete batch recovery, or explicitly choose category backlog.',
        };
    }

    return {
        eyebrow: 'Listing Mode',
        title: 'Collect listing pages and job IDs',
        description: 'Select sectors and page depth before dispatching a new listing crawl.',
    };
}

function ScheduleManager({ onNavigateToAI, onNavigateToCrawlTasks }) {
    // State
    const [schedules, setSchedules] = useState([]);
    const [categories, setCategories] = useState([]);
    const [capabilities, setCapabilities] = useState(null);
    const sourceCatalog = capabilities?.sources ?? EMPTY_SOURCE_CATALOG;
    const [listingBatches, setListingBatches] = useState([]);
    const [currentSourceSite, setCurrentSourceSite] = useState('jobsdb');
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(null);
    const [showForm, setShowForm] = useState(false);
    const [historyData, setHistoryData] = useState(null);
    const [createFormHasSourceSelections, setCreateFormHasSourceSelections] = useState(false);
    const [showImmediateScrape, setShowImmediateScrape] = useState(false);
    const [immediateForm, setImmediateForm] = useState(() => ({
        crawl_phase: resolveDefaultCrawlPhase(),
        crawl_mode: '',
        category_ids: [],
        max_pages: resolveDefaultMaxPages('jobsdb', sourceCatalog),
        detail_limit: 100,
        source_listing_crawl_job_id: '',
    }));
    const [scrapeStatus, setScrapeStatus] = useState(null);
    const [progressRecoveryNotice, setProgressRecoveryNotice] = useState(null);
    const [showProgress, setShowProgress] = useState(false);
    const [progressPanelState, setProgressPanelState] = useState({
        initialProgress: EMPTY_PROGRESS,
        recoveryStartedAt: null,
    });
    const directOverrideRecoveryRef = useRef(null);
    const immediateDirtyFieldsRef = useRef({
        crawlMode: false,
        maxPages: false,
        listingBatch: false,
    });
    const scheduleHistoryCacheRef = useRef(new Map());
    const categoryCacheRef = useRef(new Map());
    const listingBatchesCacheRef = useRef(new Map());

    const syncImmediateFormWithSourceDefaults = useCallback(() => {
        const crawlModeOptions = getCrawlModeOptionsForSource(currentSourceSite, sourceCatalog);
        const nextDefaultCrawlMode = resolveDefaultCrawlMode(currentSourceSite, sourceCatalog);
        const nextDefaultMaxPages = resolveDefaultMaxPages(currentSourceSite, sourceCatalog);

        setImmediateForm((prev) => {
            const currentMaxPages = Number.parseInt(`${prev.max_pages ?? ''}`, 10);
            const isCurrentCrawlModeValid = crawlModeOptions.some((option) => option.value === prev.crawl_mode);
            const isCurrentMaxPagesValid = Number.isInteger(currentMaxPages) && currentMaxPages > 0;
            const shouldAdoptDefaultCrawlMode =
                !prev.crawl_mode
                || !immediateDirtyFieldsRef.current.crawlMode
                || !isCurrentCrawlModeValid;
            const shouldAdoptDefaultMaxPages =
                !immediateDirtyFieldsRef.current.maxPages
                || !isCurrentMaxPagesValid;

            if (shouldAdoptDefaultCrawlMode) {
                immediateDirtyFieldsRef.current.crawlMode = false;
            }

            if (shouldAdoptDefaultMaxPages) {
                immediateDirtyFieldsRef.current.maxPages = false;
            }

            const nextCrawlMode = shouldAdoptDefaultCrawlMode ? nextDefaultCrawlMode : prev.crawl_mode;
            const nextMaxPages = shouldAdoptDefaultMaxPages ? nextDefaultMaxPages : prev.max_pages;

            if (nextCrawlMode === prev.crawl_mode && nextMaxPages === prev.max_pages) {
                return prev;
            }

            return {
                ...prev,
                crawl_mode: nextCrawlMode,
                max_pages: nextMaxPages,
            };
        });
    }, [currentSourceSite, sourceCatalog]);

    useEffect(() => {
        syncImmediateFormWithSourceDefaults();
    }, [syncImmediateFormWithSourceDefaults]);

    const handleImmediateScrapeToggle = () => {
        if (!showImmediateScrape) {
            syncImmediateFormWithSourceDefaults();
        }

        setShowImmediateScrape((prev) => !prev);
    };

    // Fetch schedules
    const fetchSchedules = useCallback(async () => {
        try {
            const data = await apiFetchJsonWithMonitoring(`${API_BASE}/schedules`, {
                failureEvent: 'schedule_manager.schedules_bootstrap_failed',
                fallbackMessage: 'Failed to load schedules',
            });
            setSchedules(data.schedules || []);
        } catch (err) {
            setError(err.message);
        }
    }, []);

    // Fetch categories
    const fetchCategories = useCallback(async (sourceSite) => {
        const requestId = createMonitoringId('req');
        try {
            const cachedCategories = categoryCacheRef.current.get(sourceSite);
            if (cachedCategories) {
                setCategories(cachedCategories);
                return;
            }

            const data = await apiFetchJson(
                `${CATEGORY_API_BASE}/categories?source_site=${encodeURIComponent(sourceSite)}`,
                { requestId }
            );
            const nextCategories = data.categories || [];
            categoryCacheRef.current.set(sourceSite, nextCategories);
            setCategories(nextCategories);
        } catch (err) {
            logError('schedule_manager.categories_failed', {
                sourceSite,
                requestId,
                detail: err instanceof Error ? err.message : err,
            });
            setCategories([]);
            setError(err.message);
        }
    }, []);

    const fetchRuntimeCapabilities = useCallback(async () => {
        const requestId = createMonitoringId('req');
        try {
            setCapabilities(
                await apiFetchJson(apiPath('/capabilities'), {
                    requestId,
                    timeoutMs: 8000,
                })
            );
        } catch (err) {
            logError('schedule_manager.runtime_capabilities_failed', {
                requestId,
                detail: err instanceof Error ? err.message : err,
            });
            setCapabilities(null);
        }
    }, []);

    const fetchListingBatches = useCallback(async (sourceSite) => {
        const requestId = createMonitoringId('req');
        try {
            const cachedListingBatches = listingBatchesCacheRef.current.get(sourceSite);
            if (cachedListingBatches) {
                setListingBatches(cachedListingBatches);
                return;
            }

            setListingBatches([]);
            const data = await apiFetchJson(
                `${API_BASE}/crawl-jobs/listing-batches?source_site=${encodeURIComponent(sourceSite)}&limit=20`,
                { requestId }
            );
            const nextBatches = Array.isArray(data.batches) ? data.batches : [];
            listingBatchesCacheRef.current.set(sourceSite, nextBatches);
            setListingBatches(nextBatches);
        } catch (err) {
            logError('schedule_manager.listing_batches_failed', {
                sourceSite,
                requestId,
                detail: err instanceof Error ? err.message : err,
            });
            setListingBatches([]);
        }
    }, []);

    const getFreshDirectOverrideRecoveryMarker = useCallback(() => {
        if (isFreshDirectOverrideRunMarker(directOverrideRecoveryRef.current)) {
            return directOverrideRecoveryRef.current;
        }

        const storedMarker = readDirectOverrideRunMarker();
        if (isFreshDirectOverrideRunMarker(storedMarker)) {
            return storedMarker;
        }

        return null;
    }, []);

    const bootstrapProgressPanel = useCallback(async () => {
        const requestId = createMonitoringId('req');
        const applyRecoveryFallback = () => {
            const recoveryMarker = getFreshDirectOverrideRecoveryMarker();

            if (recoveryMarker) {
                directOverrideRecoveryRef.current = recoveryMarker;
                setProgressPanelState({
                    initialProgress: EMPTY_PROGRESS,
                    recoveryStartedAt: recoveryMarker.startedAt,
                });
                setShowProgress(true);
                return true;
            }

            directOverrideRecoveryRef.current = null;
            clearDirectOverrideRunMarker();
            setProgressPanelState({
                initialProgress: EMPTY_PROGRESS,
                recoveryStartedAt: null,
            });
            setShowProgress(false);
            return false;
        };

        try {
            const data = await apiFetchJson(`${API_BASE}/scrape/progress`, { requestId });
            const initialProgress = data.all || {};
            const hasRecentProgress = Object.keys(initialProgress).length > 0;

            setProgressPanelState({
                initialProgress,
                recoveryStartedAt: null,
            });

            if (data.has_active || hasRecentProgress) {
                setShowProgress(true);
                return;
            }

            applyRecoveryFallback();
        } catch (err) {
            logError('schedule_manager.progress_bootstrap_failed', {
                requestId,
                detail: err instanceof Error ? err.message : err,
            });
            applyRecoveryFallback();
        }
    }, [getFreshDirectOverrideRecoveryMarker]);

    const handleProgressClose = useCallback((reason) => {
        directOverrideRecoveryRef.current = null;
        clearDirectOverrideRunMarker();
        setProgressPanelState({
            initialProgress: EMPTY_PROGRESS,
            recoveryStartedAt: null,
        });
        setShowProgress(false);
        if (reason === 'recovery_timeout') {
            setProgressRecoveryNotice({
                title: 'Direct Override recovery timed out after reconnecting.',
                detail: 'The run was likely interrupted by a restart or connection loss. Re-run the scrape if you still need it.',
            });
        }
    }, []);

    const handleResumeCrawlJob = useCallback(async (crawlJobId, strategy) => {
        const requestBody = strategy ? JSON.stringify({ strategy }) : null;
        const requestId = createMonitoringId('req');

        try {
            const data = await apiFetchJson(`${API_BASE}/crawl-jobs/${crawlJobId}/resume`, {
                method: 'POST',
                headers: requestBody ? { 'Content-Type': 'application/json' } : undefined,
                body: requestBody,
                requestId,
            });
            setError(null);
            return data;
        } catch (err) {
            const detail = err instanceof Error ? err.message : 'Failed to resume crawl job';
            setError(detail);
            throw attachRequestId(err, requestId, detail);
        }
    }, []);

    const handleCancelCrawlJob = useCallback(async (crawlJobId) => {
        const requestId = createMonitoringId('req');

        try {
            const data = await apiFetchJson(`${API_BASE}/crawl-jobs/${crawlJobId}/cancel`, {
                method: 'POST',
                requestId,
            });
            setError(null);
            return data;
        } catch (err) {
            const detail = err instanceof Error ? err.message : 'Failed to cancel crawl job';
            setError(detail);
            throw attachRequestId(err, requestId, detail);
        }
    }, []);

    const getManualActionHelperUrl = useCallback(() => {
        return capabilities?.manual_actions?.helper_url || DEFAULT_MANUAL_ACTION_HELPER_URL;
    }, [capabilities]);

    const postManualActionHelper = useCallback(async ({ path, actionLabel, fallbackDetail, crawlJobId }) => {
        const requestId = createMonitoringId('req');
        try {
            const data = await apiFetchJson(`${getManualActionHelperUrl()}${path}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ crawl_job_id: crawlJobId }),
                requestId,
            });
            setError(null);
            return data;
        } catch (requestError) {
            const isTransportFailure = requestError instanceof Error
                && (requestError.name === 'TypeError' || requestError.name === 'AbortError');
            const detail = isTransportFailure
                ? buildManualActionHelperUnavailableMessage(actionLabel)
                : requestError instanceof Error && requestError.message
                    ? requestError.message
                    : fallbackDetail;
            setError(detail);
            throw attachRequestId(new Error(detail), requestId, detail);
        }
    }, [getManualActionHelperUrl]);

    const handleGetManualActionReuseStatus = useCallback(async (crawlJobId) => {
        return postManualActionHelper({
            path: '/manual-actions/reuse-status',
            actionLabel: 'the attach status check',
            fallbackDetail: 'Failed to check open-browser reuse status',
            crawlJobId,
        });
    }, [postManualActionHelper]);

    const handleOpenManualActionBrowser = useCallback(async (crawlJobId) => {
        return postManualActionHelper({
            path: '/manual-actions/open-browser',
            actionLabel: 'opening the verification browser',
            fallbackDetail: 'Failed to open verification browser',
            crawlJobId,
        });
    }, [postManualActionHelper]);

    const handleCloseManualActionWindows = useCallback(async (crawlJobId) => {
        return postManualActionHelper({
            path: '/manual-actions/close-profile-windows',
            actionLabel: 'closing the verification profile windows',
            fallbackDetail: 'Failed to close profile windows',
            crawlJobId,
        });
    }, [postManualActionHelper]);

    // Initial load for shared runtime data.
    useEffect(() => {
        fetchSchedules();
        fetchRuntimeCapabilities();
        bootstrapProgressPanel();
    }, [
        bootstrapProgressPanel,
        fetchRuntimeCapabilities,
        fetchSchedules,
    ]);

    // Source-specific catalog data refreshes when the operator changes source.
    useEffect(() => {
        fetchCategories(currentSourceSite);
    }, [currentSourceSite, fetchCategories]);

    useEffect(() => {
        if (!showImmediateScrape || immediateForm.crawl_phase !== 'detail') {
            return;
        }

        fetchListingBatches(currentSourceSite);
    }, [currentSourceSite, fetchListingBatches, immediateForm.crawl_phase, showImmediateScrape]);

    useEffect(() => {
        if (
            !showImmediateScrape
            || immediateForm.crawl_phase !== 'detail'
            || currentSourceSite !== 'offertoday'
            || immediateDirtyFieldsRef.current.listingBatch
            || immediateForm.source_listing_crawl_job_id
        ) {
            return;
        }

        const defaultBatch = findNewestEligibleListingBatch(listingBatches);
        if (!defaultBatch?.crawl_job_id) {
            return;
        }

        setImmediateForm((prev) => (
            prev.source_listing_crawl_job_id
                ? prev
                : { ...prev, source_listing_crawl_job_id: defaultBatch.crawl_job_id }
        ));
    }, [
        currentSourceSite,
        immediateForm.crawl_phase,
        immediateForm.source_listing_crawl_job_id,
        listingBatches,
        showImmediateScrape,
    ]);

    const schedulerStatus = capabilities?.scheduler || null;
    const headedWorkerStatus = capabilities?.crawl_workers?.headed || null;
    const schedulerAutomationAvailable = schedulerStatus?.available !== false;
    const schedulerManualRunAvailable = schedulerStatus?.manual_run_available !== false;
    const scheduleAutomationDisabled = isLoading || !schedulerAutomationAvailable;
    const manualRunDisabled = isLoading || !schedulerManualRunAvailable;
    const schedulerRuntimeOwner = schedulerStatus?.worker_name || schedulerStatus?.owner || 'scheduler-worker';
    const schedulerBanner = buildSchedulerRuntimeBanner(schedulerStatus);

    // Create schedule
    const handleCreate = async (formData) => {
        if (!schedulerAutomationAvailable) {
            setError('Scheduler dispatch is unavailable in the current runtime profile.');
            return;
        }
        setIsLoading(true);
        setError(null);
        const payload = {
            ...formData,
            source_site: currentSourceSite,
            category_ids: normalizeCategoryIdsForSource(currentSourceSite, formData.category_ids),
        };
        try {
            const createdSchedule = await apiFetchJsonWithMonitoring(`${API_BASE}/schedules`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
                failureEvent: 'schedule_manager.schedule_create_failed',
                failureContext: {
                    sourceSite: currentSourceSite,
                    scheduleName: payload.name,
                },
                fallbackMessage: 'Failed to create schedule',
            });
            setSchedules((prev) => [createdSchedule, ...prev]);
            setShowForm(false);
            setCreateFormHasSourceSelections(false);
        } catch (err) {
            setError(err.message);
        } finally {
            setIsLoading(false);
        }
    };

    // Toggle schedule
    const handleToggle = async (id) => {
        if (!schedulerAutomationAvailable) {
            setError('Scheduler dispatch is unavailable in the current runtime profile.');
            return;
        }
        setIsLoading(true);
        try {
            const updatedSchedule = await apiFetchJsonWithMonitoring(`${API_BASE}/schedules/${id}/toggle`, {
                method: 'POST',
                failureEvent: 'schedule_manager.schedule_toggle_failed',
                failureContext: {
                    scheduleId: id,
                },
                fallbackMessage: 'Failed to toggle schedule',
            });
            setSchedules((prev) =>
                prev.map((schedule) =>
                    schedule.id === id
                        ? {
                            ...schedule,
                            is_active: updatedSchedule.is_active,
                            next_run_at: updatedSchedule.next_run_at,
                        }
                        : schedule
                )
            );
        } catch (err) {
            setError(err.message);
        } finally {
            setIsLoading(false);
        }
    };

    // Delete schedule
    const handleDelete = async (id) => {
        if (!window.confirm('Delete this schedule?')) return;
        setIsLoading(true);
        try {
            await apiFetchJsonWithMonitoring(`${API_BASE}/schedules/${id}`, {
                method: 'DELETE',
                failureEvent: 'schedule_manager.schedule_delete_failed',
                failureContext: {
                    scheduleId: id,
                },
                fallbackMessage: 'Failed to delete schedule',
            });
            scheduleHistoryCacheRef.current.delete(id);
            setSchedules((prev) => prev.filter((schedule) => schedule.id !== id));
        } catch (err) {
            setError(err.message);
        } finally {
            setIsLoading(false);
        }
    };

    // Run now
    const handleRun = async (id) => {
        if (!schedulerManualRunAvailable) {
            setError('Scheduler dispatch is unavailable in the current runtime profile.');
            return;
        }
        setIsLoading(true);
        try {
            await apiFetchJsonWithMonitoring(`${API_BASE}/schedules/${id}/run`, {
                method: 'POST',
                failureEvent: 'schedule_manager.schedule_run_failed',
                failureContext: {
                    scheduleId: id,
                },
                fallbackMessage: 'Failed to run schedule',
            });
            scheduleHistoryCacheRef.current.delete(id);
        } catch (err) {
            setError(err.message);
        } finally {
            setIsLoading(false);
        }
    };

    // View history
    const handleViewHistory = async (id) => {
        try {
            const cachedHistory = scheduleHistoryCacheRef.current.get(id);
            if (cachedHistory) {
                setHistoryData(cachedHistory);
                return;
            }

            const data = await apiFetchJsonWithMonitoring(`${API_BASE}/schedules/${id}/history`, {
                failureEvent: 'schedule_manager.schedule_history_failed',
                failureContext: {
                    scheduleId: id,
                },
                fallbackMessage: 'Failed to load execution history',
            });
            const schedule = schedules.find(s => s.id === id);
            const historyPayload = {
                executions: data.executions || [],
                scheduleName: schedule?.name || 'Unknown schedule'
            };
            scheduleHistoryCacheRef.current.set(id, historyPayload);
            setHistoryData(historyPayload);
        } catch (err) {
            setError(err.message);
        }
    };

    // Immediate scrape
    const handleImmediateScrape = async () => {
        if (!schedulerManualRunAvailable) {
            setError('Scheduler dispatch is unavailable in the current runtime profile.');
            return;
        }
        const request = buildImmediateScrapePayload(immediateForm, currentSourceSite, sourceCatalog);
        if (request.error) {
            setError(request.error);
            return;
        }
        setIsLoading(true);
        setError(null);
        setProgressRecoveryNotice(null);
        setScrapeStatus('Queueing crawl job...');
        try {
            const payload = await apiFetchJsonWithMonitoring(`${API_BASE}/crawl-jobs`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(request.payload),
                failureEvent: 'schedule_manager.direct_override_create_failed',
                failureContext: {
                    sourceSite: currentSourceSite,
                    crawlPhase: request.payload.crawl_phase,
                },
                fallbackMessage: 'Start failed',
            });
            const runMarker = {
                crawlJobId: payload.id || null,
                sourceSite: currentSourceSite,
                startedAt: new Date(Date.now()).toISOString(),
            };
            if (request.payload.crawl_phase === 'listing') {
                listingBatchesCacheRef.current.delete(currentSourceSite);
            }
            directOverrideRecoveryRef.current = runMarker;
            try {
                writeDirectOverrideRunMarker(runMarker);
            } catch {
                // Keep recovery state in memory for this mount when storage is unavailable.
            }
            setProgressPanelState({
                initialProgress: EMPTY_PROGRESS,
                recoveryStartedAt: runMarker.startedAt,
            });
            setShowProgress(true);
            setShowImmediateScrape(false);
            setScrapeStatus(null);
        } catch (err) {
            setError(err.message);
            setScrapeStatus(null);
        } finally {
            setIsLoading(false);
        }
    };

    const toggleImmediateCategory = (categoryId) => {
        setImmediateForm(prev => ({
            ...prev,
            category_ids: prev.category_ids.includes(categoryId)
                ? prev.category_ids.filter(id => id !== categoryId)
                : [...prev.category_ids, categoryId]
        }));
    };

    const handleSourceSiteChange = (event) => {
        const nextSourceSite = event.target.value;

        if (!nextSourceSite || nextSourceSite === currentSourceSite) {
            return;
        }

        if (
            (createFormHasSourceSelections || immediateForm.category_ids.length > 0)
            && !window.confirm('Switching data source will clear the current category selections. Continue?')
        ) {
            return;
        }

        setCurrentSourceSite(nextSourceSite);
        setCreateFormHasSourceSelections(false);
        immediateDirtyFieldsRef.current.listingBatch = false;
        setImmediateForm((prev) => ({
            ...prev,
            crawl_phase: resolveDefaultCrawlPhase(),
            category_ids: [],
            source_listing_crawl_job_id: '',
        }));
    };

    const filteredSchedules = schedules.filter(
        (schedule) => (schedule.source_site || 'jobsdb') === currentSourceSite
    );
    const hasRuntimeSourceCatalog = Object.keys(sourceCatalog).length > 0;
    const sourceMetadataUnavailable = capabilities !== null && !hasRuntimeSourceCatalog;
    const sourceOptions = hasRuntimeSourceCatalog
        ? Object.entries(sourceCatalog).map(([value, sourceMetadata]) => ({
            value,
            label: sourceMetadata?.label || formatSourceLabel(value),
        }))
        : [{ value: currentSourceSite, label: formatSourceLabel(currentSourceSite) }];
    const selectedListingBatch = listingBatches.find(
        (batch) => batch.crawl_job_id === immediateForm.source_listing_crawl_job_id
    ) || null;
    const immediateCrawlModeOptions = getCrawlModeOptionsForSource(currentSourceSite, sourceCatalog);
    const immediateRunSummary = buildImmediateRunSummary(immediateForm, currentSourceSite, categories);
    const immediateRunReadiness = buildImmediateRunReadiness(
        immediateForm,
        currentSourceSite,
        sourceCatalog,
        headedWorkerStatus,
    );
    const immediateRunModeCopy = buildImmediateRunModeCopy(immediateForm);

    return (
        <div className="scheduler-container">
            <header className="scheduler-header">
                <div>
                    <h2><CalendarClock className="title-icon" /> Task Control Board</h2>
                    <p className="subtitle">Automations, direct runs, and crawl progress.</p>
                </div>
                <div className="header-actions">
                    <button
                        className="cyber-btn primary-glow"
                        onClick={() => setShowForm(!showForm)}
                        disabled={!schedulerAutomationAvailable && !showForm}
                    >
                        {showForm ? 'Close Form' : <><Plus size={18} /> New Automation</>}
                    </button>
                    <button
                        className="cyber-btn run-btn"
                        data-testid="direct-override-toggle"
                        onClick={handleImmediateScrapeToggle}
                        disabled={manualRunDisabled}
                    >
                        {showImmediateScrape ? 'Cancel' : <><Zap size={18} /> Direct Override</>}
                    </button>
                </div>
            </header>

            <div className="source-control-panel glass-panel">
                <label htmlFor="scheduler-source-site">Data Source</label>
                <select
                    id="scheduler-source-site"
                    data-testid="scheduler-source-site"
                    className="premium-select"
                    value={currentSourceSite}
                    onChange={handleSourceSiteChange}
                    disabled={sourceMetadataUnavailable}
                >
                    {sourceOptions.map((option) => (
                        <option key={option.value} value={option.value}>
                            {option.label}
                        </option>
                    ))}
                </select>
            </div>

            {sourceMetadataUnavailable && (
                <div className="operator-health-banner glass-panel">
                    <AlertTriangle size={20} />
                    <div>
                        <strong>Source metadata is unavailable for this runtime.</strong>
                        <div className="operator-health-issues">
                            <span>Source switching is temporarily disabled until runtime capabilities expose `sources` metadata.</span>
                        </div>
                    </div>
                </div>
            )}

            <div className="scheduler-launchpad">
                <div className="scheduler-workstream-card glass-panel">
                    <span className="scheduler-panel-kicker">Scheduled Automation</span>
                    <p>
                        Keep repeatable source scans on a cron so nightly and recurring workloads stay hands-free.
                    </p>
                </div>
                <div className="scheduler-workstream-card glass-panel">
                    <span className="scheduler-panel-kicker">Immediate Run for Backlog Recovery</span>
                    <p>
                        Launch an on-demand listing or detail crawl when you need to recover backlog or step through manual verification.
                    </p>
                </div>
            </div>

            {schedulerStatus && (
                <div className="scheduler-runtime-panel glass-panel">
                    <strong>Scheduler owner: {schedulerRuntimeOwner}</strong>
                    <div className="operator-health-issues">
                        <span>Heartbeat: {schedulerStatus.heartbeat_status || 'fresh'}</span>
                        {schedulerStatus.last_heartbeat_at && (
                            <span>Last heartbeat: {formatRuntimeTimestamp(schedulerStatus.last_heartbeat_at)}</span>
                        )}
                        {schedulerStatus.last_reconcile_at && (
                            <span>Last reconcile: {formatRuntimeTimestamp(schedulerStatus.last_reconcile_at)}</span>
                        )}
                    </div>
                </div>
            )}
            {schedulerBanner && (
                <div className="operator-health-banner glass-panel">
                    <AlertTriangle size={20} />
                    <div>
                        <strong>{schedulerBanner.title}</strong>
                        <div className="operator-health-issues">
                            {schedulerBanner.lines.map((line) => (
                                <span key={line}>{line}</span>
                            ))}
                        </div>
                    </div>
                </div>
            )}

            {error && (
                <div className="error-banner glass-panel">
                    <AlertTriangle size={20} />
                    <span>{error}</span>
                    <button
                        type="button"
                        onClick={() => setError(null)}
                        className="close-error"
                        aria-label="Dismiss error"
                    >
                        <X size={16} />
                    </button>
                </div>
            )}

            {scrapeStatus && (
                <div className="status-banner glass-panel">
                    <Zap size={20} className="spinner" />
                    <span>{scrapeStatus}</span>
                </div>
            )}

            {progressRecoveryNotice && (
                <div className="error-banner glass-panel">
                    <AlertTriangle size={20} />
                    <span>
                        <strong>{progressRecoveryNotice.title}</strong>{' '}
                        {progressRecoveryNotice.detail}
                    </span>
                    <button
                        type="button"
                        onClick={() => setProgressRecoveryNotice(null)}
                        className="close-error"
                        aria-label="Dismiss recovery notice"
                    >
                        <X size={16} />
                    </button>
                </div>
            )}

            {showProgress && (
                <ScrapeProgressPanel
                    isVisible={showProgress}
                    initialProgress={progressPanelState.initialProgress}
                    recoveryStartedAt={progressPanelState.recoveryStartedAt}
                    recoveryWindowMs={DIRECT_OVERRIDE_RECOVERY_WINDOW_MS}
                    headedWorkerStatus={headedWorkerStatus}
                    sourceCatalog={sourceCatalog}
                    onClose={handleProgressClose}
                    onNavigateToAI={onNavigateToAI}
                    onOpenCrawlTasks={onNavigateToCrawlTasks}
                    onResumeCrawlJob={handleResumeCrawlJob}
                    onCancelCrawlJob={handleCancelCrawlJob}
                    onOpenManualActionBrowser={handleOpenManualActionBrowser}
                    onGetManualActionReuseStatus={handleGetManualActionReuseStatus}
                    onCloseManualActionWindows={handleCloseManualActionWindows}
                />
            )}

            {showImmediateScrape && (
                <div className="immediate-form-panel glass-panel">
                    <h3>Direct Override Sequence</h3>
                    <p className="form-hint">Direct crawl job configuration.</p>

                    <div className="override-mode-panel">
                        <span className="scheduler-panel-kicker">{immediateRunModeCopy.eyebrow}</span>
                        <strong className="override-summary-title">{immediateRunModeCopy.title}</strong>
                        <p className="form-hint">{immediateRunModeCopy.description}</p>
                    </div>

                    <div className="override-summary-panel">
                        <span className="scheduler-panel-kicker">{immediateRunSummary.title}</span>
                        <strong className="override-summary-title">{immediateRunSummary.description}</strong>
                        <div className="override-summary-metrics">
                            {immediateRunSummary.metrics.map((metric) => (
                                <span key={metric} className="override-summary-chip">
                                    {metric}
                                </span>
                            ))}
                        </div>
                    </div>

                    <div className={`override-readiness-panel ${immediateRunReadiness.isReady ? 'ready' : 'blocked'}`}>
                        <span className="scheduler-panel-kicker">{immediateRunReadiness.statusLabel}</span>
                        <strong>{immediateRunReadiness.detail}</strong>
                    </div>

                    <div className="cyber-form-group">
                        <label htmlFor="immediate-crawl-phase">Crawl Phase</label>
                        <select
                            id="immediate-crawl-phase"
                            data-testid="direct-override-phase"
                            className="premium-select"
                            value={immediateForm.crawl_phase}
                            onChange={(e) => {
                                const nextPhase = e.target.value;
                                immediateDirtyFieldsRef.current.listingBatch = false;
                                setImmediateForm(prev => ({
                                    ...prev,
                                    crawl_phase: nextPhase,
                                    source_listing_crawl_job_id: nextPhase === 'detail'
                                        ? prev.source_listing_crawl_job_id
                                        : '',
                                }));
                            }}
                        >
                            {CRAWL_PHASE_OPTIONS.map((option) => (
                                <option key={option.value} value={option.value}>
                                    {option.label}
                                </option>
                            ))}
                        </select>
                    </div>

                    <div className="cyber-form-group">
                        <label htmlFor="immediate-crawl-mode">Crawl Mode</label>
                        <select
                            id="immediate-crawl-mode"
                            data-testid="direct-override-mode"
                            className="premium-select"
                            value={immediateForm.crawl_mode}
                            onChange={(e) => {
                                immediateDirtyFieldsRef.current.crawlMode = true;
                                setImmediateForm(prev => ({
                                    ...prev,
                                    crawl_mode: e.target.value,
                                }));
                            }}
                        >
                            {immediateCrawlModeOptions.map((option) => (
                                <option key={option.value} value={option.value}>
                                    {option.label}
                                </option>
                            ))}
                        </select>
                    </div>

                    <div className="cyber-form-group">
                        <label>Target Sectors</label>
                        <div className="category-checkbox-grid">
                            {categories.map(cat => (
                                <label key={cat.id} className="cyber-checkbox-label">
                                    <input
                                        type="checkbox"
                                        checked={immediateForm.category_ids.includes(cat.id)}
                                        onChange={() => toggleImmediateCategory(cat.id)}
                                    />
                                    <span className="checkbox-text">{cat.name}</span>
                                </label>
                            ))}
                        </div>
                        {currentSourceSite === 'offertoday' && immediateForm.crawl_phase === 'listing' && (
                            <p className="form-hint">
                                Leave sectors blank to use 全 IT 分類（預設）.
                            </p>
                        )}
                    </div>

                    <div className="cyber-form-group">
                        <label>{immediateForm.crawl_phase === 'detail' ? 'Detail Crawl Target' : 'Max Depth (Pages)'}</label>
                        <input
                            type="number"
                            data-testid="direct-override-limit"
                            min="1"
                            max={immediateForm.crawl_phase === 'detail' ? '5000' : '9999'}
                            className="premium-input w-24"
                            value={immediateForm.crawl_phase === 'detail' ? immediateForm.detail_limit : immediateForm.max_pages}
                            onChange={(e) => {
                                if (immediateForm.crawl_phase !== 'detail') {
                                    immediateDirtyFieldsRef.current.maxPages = true;
                                }

                                setImmediateForm(prev => ({
                                    ...prev,
                                    ...(immediateForm.crawl_phase === 'detail'
                                        ? { detail_limit: e.target.value }
                                        : { max_pages: e.target.value })
                                }));
                            }}
                        />
                        <p className="form-hint">
                            {immediateForm.crawl_phase === 'detail'
                                ? 'Set the maximum number of eligible detail rows to recover in this run.'
                                : (currentSourceSite === 'offertoday' && immediateForm.category_ids.length === 0
                                    ? 'Set how many listing pages to scan across the default IT scope.'
                                    : 'Set how many listing pages to scan per selected sector.')}
                        </p>
                    </div>

                    {immediateForm.crawl_phase === 'detail' && (
                        <div className="cyber-form-group">
                            <label htmlFor="source-listing-crawl-job-id">Listing Batch Scope</label>
                            <select
                                id="source-listing-crawl-job-id"
                                data-testid="direct-override-listing-batch"
                                className="premium-select"
                                value={immediateForm.source_listing_crawl_job_id}
                                onChange={(e) => {
                                    immediateDirtyFieldsRef.current.listingBatch = true;
                                    setImmediateForm(prev => ({
                                        ...prev,
                                        source_listing_crawl_job_id: e.target.value,
                                    }));
                                }}
                            >
                                <option value="">Global category backlog (advanced)</option>
                                {listingBatches.map((batch) => (
                                    <option key={batch.crawl_job_id} value={batch.crawl_job_id}>
                                        {formatListingBatchOptionLabel(batch, formatRuntimeTimestamp)}
                                    </option>
                                ))}
                            </select>
                            <p className="form-hint backlog-guidance-muted">
                                {currentSourceSite === 'offertoday'
                                    ? 'OfferToday defaults to the newest batch with detail work. Choose global backlog explicitly only for category-wide recovery.'
                                    : 'Choose a listing batch to narrow recovery, or leave it blank for category backlog.'}
                            </p>
                            <div className="backlog-guidance-panel">
                                <div>
                                    <span className="backlog-guidance-label">Category-scoped backlog recovery</span>
                                    <p>
                                        Recover pending, failed, and manual-review detail backlog for the selected source and sectors. The target counts actual detail pages after existing jobs are filtered out.
                                    </p>
                                </div>
                                {selectedListingBatch ? (
                                    <div>
                                        <div className="backlog-guidance-label">
                                            {formatListingBatchIdentity({
                                                sourceSite: selectedListingBatch.source_site,
                                                crawlJobId: selectedListingBatch.crawl_job_id,
                                            })}
                                        </div>
                                        <div className="backlog-metric-grid" aria-label="Selected listing batch backlog">
                                            <div>
                                                <strong>{formatBacklogCount(selectedListingBatch.listings_staged)} staged</strong>
                                                <span>listings found</span>
                                            </div>
                                            <div>
                                                <strong>{formatBacklogCount(selectedListingBatch.detail_pending)} pending</strong>
                                                <span>details left</span>
                                            </div>
                                            {Number(selectedListingBatch.detail_running || 0) > 0 && (
                                                <div>
                                                    <strong>{formatBacklogCount(selectedListingBatch.detail_running)} running</strong>
                                                    <span>details in flight</span>
                                                </div>
                                            )}
                                            <div>
                                                <strong>{formatBacklogCount(selectedListingBatch.detail_completed)} completed</strong>
                                                <span>details completed</span>
                                            </div>
                                            {Number(selectedListingBatch.detail_failed || 0) > 0 && (
                                                <div>
                                                    <strong>{formatBacklogCount(selectedListingBatch.detail_failed)} failed</strong>
                                                    <span>details failed</span>
                                                </div>
                                            )}
                                            {Number(selectedListingBatch.detail_manual_action_required || 0) > 0 && (
                                                <div>
                                                    <strong>{formatBacklogCount(selectedListingBatch.detail_manual_action_required)} manual review</strong>
                                                    <span>details blocked</span>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                ) : (
                                    <p className="backlog-guidance-muted">
                                        Leave this empty for the default backlog pool. Use it only for targeted recovery or resume flows tied to one historical listing batch.
                                    </p>
                                )}
                            </div>
                        </div>
                    )}

                    <div className="form-actions mt-6">
                        <button
                            className="cyber-btn run-btn w-full"
                            data-testid="direct-override-start"
                            onClick={handleImmediateScrape}
                            disabled={isLoading || !immediateRunReadiness.isReady}
                        >
                            <Zap size={18} /> {isLoading ? 'Initializing...' : immediateRunSummary.actionLabel}
                        </button>
                    </div>
                </div>
            )}

            {showForm && (
                <div className="form-wrapper glass-panel mt-6">
                    <ScheduleForm
                        categories={categories}
                        sourceSite={currentSourceSite}
                        sourceCatalog={sourceCatalog}
                        onSubmit={handleCreate}
                        onCancel={() => setShowForm(false)}
                        onSourceScopedDirtyChange={setCreateFormHasSourceSelections}
                        isLoading={isLoading}
                    />
                </div>
            )}

            <ScheduleList
                schedules={filteredSchedules}
                categories={categories}
                currentSourceSite={currentSourceSite}
                onToggle={handleToggle}
                onDelete={handleDelete}
                onRun={handleRun}
                onViewHistory={handleViewHistory}
                isLoading={isLoading}
                scheduleAutomationDisabled={scheduleAutomationDisabled}
                manualRunDisabled={manualRunDisabled}
            />
            {historyData && (
                <ScheduleHistory
                    executions={historyData.executions}
                    scheduleName={historyData.scheduleName}
                    onClose={() => setHistoryData(null)}
                />
            )}
        </div>
    );
}

export default ScheduleManager;
