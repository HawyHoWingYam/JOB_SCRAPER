import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Plus, Zap, AlertTriangle, CalendarClock, X } from 'lucide-react';
import { API_BASE_URL } from '../../api/base';
import { fetchCapabilities } from '../../api/capabilities';
import ScheduleForm from './ScheduleForm';
import ScheduleList from './ScheduleList';
import ScheduleHistory from './ScheduleHistory';
import ScrapeProgressPanel from './ScrapeProgressPanel';
import { getCrawlModeOptionsForSource, resolveDefaultCrawlMode } from './crawlMode';
import { CRAWL_PHASE_OPTIONS, resolveDefaultCrawlPhase } from './crawlPhase';
import {
    formatListingBatchIdentity,
    formatListingBatchOptionLabel,
    formatScraperSourceLabel,
} from './listingBatchLabel';
import './Scheduler.css';

const API_URL = API_BASE_URL;
const API_BASE = `${API_URL}/api/v1`;
const CATEGORY_API_BASE = `${API_URL}/api`;
const DEFAULT_MANUAL_ACTION_HELPER_URL = 'http://127.0.0.1:47652';
const DIRECT_OVERRIDE_RUN_KEY = 'scheduler.directOverrideRun';
const DIRECT_OVERRIDE_RECOVERY_WINDOW_MS = 20_000;
const EMPTY_PROGRESS = {};
const SOURCE_OPTIONS = [
    { value: 'jobsdb', label: 'JobsDB' },
    { value: 'ctgoodjobs', label: 'CTgoodjobs' },
    { value: 'offertoday', label: 'OfferToday' },
];

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

function formatApiErrorDetail(detail, fallback = 'Start failed') {
    if (typeof detail === 'string' && detail.trim()) {
        return detail;
    }

    if (Array.isArray(detail) && detail.length > 0) {
        return detail
            .map((item) => {
                if (typeof item === 'string') {
                    return item;
                }

                if (item && typeof item === 'object') {
                    const path = Array.isArray(item.loc) ? item.loc.slice(1).join('.') : '';
                    const message = typeof item.msg === 'string' ? item.msg : '';
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
            .join('; ') || fallback;
    }

    return fallback;
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

function buildImmediateScrapePayload(form, sourceSite) {
    const crawlPhase = form?.crawl_phase || resolveDefaultCrawlPhase();
    const categoryIds = normalizeCategoryIdsForSource(sourceSite, form?.category_ids);
    const maxPages = Number.parseInt(`${form?.max_pages ?? ''}`, 10);
    const detailLimit = Number.parseInt(`${form?.detail_limit ?? ''}`, 10);
    const sourceListingCrawlJobId = `${form?.source_listing_crawl_job_id ?? ''}`.trim();

    if (crawlPhase === 'listing' && categoryIds.length === 0) {
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
            crawl_mode: form?.crawl_mode || resolveDefaultCrawlMode(sourceSite),
            category_ids: categoryIds,
            max_pages: Number.isInteger(maxPages) ? maxPages : 3,
            detail_limit: crawlPhase === 'detail' ? detailLimit : 100,
            skip_existing: true,
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

function formatImmediateListingDepthMetric(maxPages) {
    if (!Number.isInteger(maxPages)) {
        return 'Page limit not set';
    }
    if (maxPages < 1 || maxPages > 9999) {
        return 'Page limit invalid';
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
                `Legacy batch filter: ${formatListingBatchIdentity({
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
        formatSectorSelectionLabel(selectedSectorCount),
        formatImmediateListingDepthMetric(maxPages)
    );

    return {
        title: 'Immediate Run for Backlog Recovery',
        description: 'This run will start a job ID crawl.',
        metrics: summaryMetrics,
        actionLabel: 'Start Job ID Crawl',
    };
}

function buildImmediateRunReadiness(form, sourceSite, headedWorkerStatus = null) {
    const request = buildImmediateScrapePayload(form, sourceSite);
    const crawlPhase = form?.crawl_phase || resolveDefaultCrawlPhase();
    const crawlMode = form?.crawl_mode || resolveDefaultCrawlMode(sourceSite);
    const selectedSectorCount = Array.isArray(form?.category_ids) ? form.category_ids.length : 0;
    const hasBatchFilter = Boolean(`${form?.source_listing_crawl_job_id ?? ''}`.trim());

    // OfferToday runs headed mode inside the same Docker container — no host-side worker needed
    if (crawlMode === 'headed' && headedWorkerStatus?.available === false) {
        if (sourceSite !== 'offertoday') {
            return {
                isReady: false,
                statusLabel: 'Headed worker offline',
                detail: buildHeadedWorkerUnavailableMessage(headedWorkerStatus),
            };
        }
    }

    if (request.error) {
        let detail = request.error;

        if (crawlPhase === 'listing' && selectedSectorCount === 0) {
            detail = 'Select at least one sector to launch this listing crawl.';
        } else if (crawlPhase === 'detail' && selectedSectorCount === 0 && !hasBatchFilter) {
            detail = 'Select sectors or a legacy listing batch before launching this detail recovery run.';
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
            ? `Listing crawl will scan ${selectedSectorCount} selected sector${selectedSectorCount === 1 ? '' : 's'}.`
            : hasBatchFilter
                ? 'Detail crawl will narrow recovery to the selected legacy listing batch.'
                : 'Detail crawl will recover eligible backlog from the selected sector scope.',
    };
}

function buildImmediateRunModeCopy(form) {
    const crawlPhase = form?.crawl_phase || resolveDefaultCrawlPhase();

    if (crawlPhase === 'detail') {
        return {
            eyebrow: 'Detail Mode',
            title: 'Recover eligible detail backlog',
            description: 'Use sectors and optional legacy batch narrowing to target pending detail work.',
        };
    }

    return {
        eyebrow: 'Listing Mode',
        title: 'Collect listing pages and job IDs',
        description: 'Select sectors and page depth before dispatching a new listing crawl.',
    };
}

function ScheduleManager({ onNavigateToAI }) {
    // State
    const [schedules, setSchedules] = useState([]);
    const [categories, setCategories] = useState([]);
    const [capabilities, setCapabilities] = useState(null);
    const [listingBatches, setListingBatches] = useState([]);
    const [currentSourceSite, setCurrentSourceSite] = useState('jobsdb');
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(null);
    const [showForm, setShowForm] = useState(false);
    const [historyData, setHistoryData] = useState(null);
    const [createFormHasSourceSelections, setCreateFormHasSourceSelections] = useState(false);
    const [showImmediateScrape, setShowImmediateScrape] = useState(false);
    const [immediateForm, setImmediateForm] = useState({
        crawl_phase: resolveDefaultCrawlPhase(),
        crawl_mode: resolveDefaultCrawlMode('jobsdb'),
        category_ids: [],
        max_pages: 3,
        detail_limit: 100,
        source_listing_crawl_job_id: '',
    });
    const [scrapeStatus, setScrapeStatus] = useState(null);
    const [progressRecoveryNotice, setProgressRecoveryNotice] = useState(null);
    const [showProgress, setShowProgress] = useState(false);
    const [progressPanelState, setProgressPanelState] = useState({
        initialProgress: EMPTY_PROGRESS,
        recoveryStartedAt: null,
    });
    const directOverrideRecoveryRef = useRef(null);
    const scheduleHistoryCacheRef = useRef(new Map());
    const categoryCacheRef = useRef(new Map());
    const listingBatchesCacheRef = useRef(new Map());

    // Fetch schedules
    const fetchSchedules = useCallback(async () => {
        try {
            const response = await fetch(`${API_BASE}/schedules`);
            if (!response.ok) throw new Error('Failed to load schedules');
            const data = await response.json();
            setSchedules(data.schedules || []);
        } catch (err) {
            setError(err.message);
        }
    }, []);

    // Fetch categories
    const fetchCategories = useCallback(async (sourceSite) => {
        try {
            const cachedCategories = categoryCacheRef.current.get(sourceSite);
            if (cachedCategories) {
                setCategories(cachedCategories);
                return;
            }

            const response = await fetch(
                `${CATEGORY_API_BASE}/categories?source_site=${encodeURIComponent(sourceSite)}`
            );
            if (!response.ok) {
                let detail = '';
                try {
                    const payload = await response.json();
                    detail = typeof payload?.detail === 'string' ? payload.detail : '';
                } catch {
                    detail = '';
                }
                throw new Error(detail || 'Failed to load categories');
            }
            if (!response.ok) throw new Error('Failed to load categories');
            const data = await response.json();
            const nextCategories = data.categories || [];
            categoryCacheRef.current.set(sourceSite, nextCategories);
            setCategories(nextCategories);
        } catch (err) {
            console.error('Failed to fetch categories:', err);
            setCategories([]);
            setError(err.message);
        }
    }, []);

    const fetchRuntimeCapabilities = useCallback(async () => {
        try {
            setCapabilities(await fetchCapabilities());
        } catch (err) {
            console.error('Failed to fetch runtime capabilities:', err);
            setCapabilities(null);
        }
    }, []);

    const fetchListingBatches = useCallback(async (sourceSite) => {
        try {
            const cachedListingBatches = listingBatchesCacheRef.current.get(sourceSite);
            if (cachedListingBatches) {
                setListingBatches(cachedListingBatches);
                return;
            }

            setListingBatches([]);
            const response = await fetch(
                `${API_BASE}/crawl-jobs/listing-batches?source_site=${encodeURIComponent(sourceSite)}&limit=20`
            );
            if (!response.ok) {
                throw new Error('Failed to load listing batches');
            }
            const data = await response.json();
            const nextBatches = Array.isArray(data.batches) ? data.batches : [];
            listingBatchesCacheRef.current.set(sourceSite, nextBatches);
            setListingBatches(nextBatches);
        } catch (err) {
            console.error('Failed to fetch listing batches:', err);
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
            const response = await fetch(`${API_BASE}/scrape/progress`);
            if (!response.ok) {
                throw new Error('Failed to load crawl progress');
            }

            const data = await response.json();
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
            console.error('Failed to bootstrap scrape progress:', err);

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
        const response = await fetch(`${API_BASE}/crawl-jobs/${crawlJobId}/resume`, {
            method: 'POST',
            headers: requestBody ? { 'Content-Type': 'application/json' } : undefined,
            body: requestBody,
        });

        if (!response.ok) {
            let detail = 'Failed to resume crawl job';

            try {
                const payload = await response.json();
                detail = formatApiErrorDetail(payload.detail, detail);
            } catch {
                // Fall back to the default message when no JSON error is available.
            }

            setError(detail);
            throw new Error(detail);
        }

        setError(null);
        return response.json();
    }, []);

    const handleCancelCrawlJob = useCallback(async (crawlJobId) => {
        const response = await fetch(`${API_BASE}/crawl-jobs/${crawlJobId}/cancel`, {
            method: 'POST',
        });

        if (!response.ok) {
            let detail = 'Failed to cancel crawl job';

            try {
                const payload = await response.json();
                detail = formatApiErrorDetail(payload.detail, detail);
            } catch {
                // Fall back to the default message when no JSON error is available.
            }

            setError(detail);
            throw new Error(detail);
        }

        setError(null);
        return response.json();
    }, []);

    const getManualActionHelperUrl = useCallback(() => {
        return capabilities?.manual_actions?.helper_url || DEFAULT_MANUAL_ACTION_HELPER_URL;
    }, [capabilities]);

    const postManualActionHelper = useCallback(async ({ path, actionLabel, fallbackDetail, crawlJobId }) => {
        let response;

        try {
            response = await fetch(`${getManualActionHelperUrl()}${path}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ crawl_job_id: crawlJobId }),
            });
        } catch (requestError) {
            const detail = buildManualActionHelperUnavailableMessage(actionLabel);
            setError(detail);
            throw new Error(detail);
        }

        if (!response.ok) {
            let detail = fallbackDetail;

            try {
                const payload = await response.json();
                detail = formatApiErrorDetail(payload.detail, detail);
            } catch {
                // Fall back to the default message when no JSON error is available.
            }

            setError(detail);
            throw new Error(detail);
        }

        setError(null);
        return response.json();
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
        try {
            return await postManualActionHelper({
                path: '/manual-actions/open-browser',
                actionLabel: 'opening the verification browser',
                fallbackDetail: 'Failed to open verification browser',
                crawlJobId,
            });
        } catch {
            return null;
        }
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
            const response = await fetch(`${API_BASE}/schedules`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.detail || 'Failed to create schedule');
            }
            const createdSchedule = await response.json();
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
            const response = await fetch(`${API_BASE}/schedules/${id}/toggle`, {
                method: 'POST'
            });
            if (!response.ok) throw new Error('Failed to toggle schedule');
            const updatedSchedule = await response.json();
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
            const response = await fetch(`${API_BASE}/schedules/${id}`, {
                method: 'DELETE'
            });
            if (!response.ok) throw new Error('Failed to delete schedule');
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
            const response = await fetch(`${API_BASE}/schedules/${id}/run`, {
                method: 'POST'
            });
            if (!response.ok) {
                let detail = 'Failed to run schedule';
                try {
                    const payload = await response.json();
                    detail = formatApiErrorDetail(payload.detail, detail);
                } catch {
                    // Fall back to the default message when no JSON error is available.
                }
                throw new Error(detail);
            }
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

            const response = await fetch(`${API_BASE}/schedules/${id}/history`);
            if (!response.ok) throw new Error('Failed to load execution history');
            const data = await response.json();
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
        const request = buildImmediateScrapePayload(immediateForm, currentSourceSite);
        if (request.error) {
            setError(request.error);
            return;
        }
        setIsLoading(true);
        setError(null);
        setProgressRecoveryNotice(null);
        setScrapeStatus('Queueing crawl job...');
        try {
            const response = await fetch(`${API_BASE}/crawl-jobs`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(request.payload)
            });
            if (!response.ok) {
                const errData = await response.json();
                throw new Error(formatApiErrorDetail(errData.detail));
            }
            const payload = await response.json();
            const runMarker = {
                crawlJobId: payload.id || response.headers.get('X-Crawl-Job-Id') || null,
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

        if (nextSourceSite === currentSourceSite) {
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
        setImmediateForm((prev) => ({
            ...prev,
            crawl_phase: resolveDefaultCrawlPhase(),
            crawl_mode: resolveDefaultCrawlMode(nextSourceSite),
            category_ids: [],
            source_listing_crawl_job_id: '',
        }));
    };

    const filteredSchedules = schedules.filter(
        (schedule) => (schedule.source_site || 'jobsdb') === currentSourceSite
    );
    const selectedListingBatch = listingBatches.find(
        (batch) => batch.crawl_job_id === immediateForm.source_listing_crawl_job_id
    ) || null;
    const immediateCrawlModeOptions = getCrawlModeOptionsForSource(currentSourceSite);
    const immediateRunSummary = buildImmediateRunSummary(immediateForm, currentSourceSite, categories);
    const immediateRunReadiness = buildImmediateRunReadiness(
        immediateForm,
        currentSourceSite,
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
                        onClick={() => setShowImmediateScrape(!showImmediateScrape)}
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
                    className="premium-select"
                    value={currentSourceSite}
                    onChange={handleSourceSiteChange}
                >
                    {SOURCE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                            {option.label}
                        </option>
                    ))}
                </select>
            </div>

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
                    onClose={handleProgressClose}
                    onNavigateToAI={onNavigateToAI}
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
                            className="premium-select"
                            value={immediateForm.crawl_phase}
                            onChange={(e) => setImmediateForm(prev => ({
                                ...prev,
                                crawl_phase: e.target.value,
                                source_listing_crawl_job_id: e.target.value === 'detail'
                                    ? prev.source_listing_crawl_job_id
                                    : '',
                            }))}
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
                            className="premium-select"
                            value={immediateForm.crawl_mode}
                            onChange={(e) => setImmediateForm(prev => ({
                                ...prev,
                                crawl_mode: e.target.value,
                            }))}
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
                    </div>

                    <div className="cyber-form-group">
                        <label>{immediateForm.crawl_phase === 'detail' ? 'Detail Crawl Target' : 'Max Depth (Pages)'}</label>
                        <input
                            type="number"
                            min="1"
                            max={immediateForm.crawl_phase === 'detail' ? '5000' : '9999'}
                            className="premium-input w-24"
                            value={immediateForm.crawl_phase === 'detail' ? immediateForm.detail_limit : immediateForm.max_pages}
                            onChange={(e) => setImmediateForm(prev => ({
                                ...prev,
                                ...(immediateForm.crawl_phase === 'detail'
                                    ? { detail_limit: e.target.value }
                                    : { max_pages: e.target.value })
                            }))}
                        />
                        <p className="form-hint">
                            {immediateForm.crawl_phase === 'detail'
                                ? 'Set the maximum number of eligible detail rows to recover in this run.'
                                : 'Set how many listing pages to scan per selected sector.'}
                        </p>
                    </div>

                    {immediateForm.crawl_phase === 'detail' && (
                        <div className="cyber-form-group">
                            <label htmlFor="source-listing-crawl-job-id">Legacy Listing Batch Filter</label>
                            <select
                                id="source-listing-crawl-job-id"
                                className="premium-select"
                                value={immediateForm.source_listing_crawl_job_id}
                                onChange={(e) => setImmediateForm(prev => ({
                                    ...prev,
                                    source_listing_crawl_job_id: e.target.value,
                                }))}
                            >
                                <option value="">No legacy batch filter</option>
                                {listingBatches.map((batch) => (
                                    <option key={batch.crawl_job_id} value={batch.crawl_job_id}>
                                        {formatListingBatchOptionLabel(batch, formatRuntimeTimestamp)}
                                    </option>
                                ))}
                            </select>
                            <p className="form-hint backlog-guidance-muted">
                                Optional narrowing control. Leave blank to recover eligible backlog across the selected sectors.
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
