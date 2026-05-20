import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Plus, Zap, AlertTriangle, CalendarClock } from 'lucide-react';
import { API_BASE_URL } from '../../api/base';
import ScheduleForm from './ScheduleForm';
import ScheduleList from './ScheduleList';
import ScheduleHistory from './ScheduleHistory';
import ScrapeProgressPanel from './ScrapeProgressPanel';
import { CRAWL_MODE_OPTIONS, resolveDefaultCrawlMode } from './crawlMode';
import { CRAWL_PHASE_OPTIONS, resolveDefaultCrawlPhase } from './crawlPhase';
import './Scheduler.css';

const API_URL = API_BASE_URL;
const API_BASE = `${API_URL}/api/v1`;
const CATEGORY_API_BASE = `${API_URL}/api`;
const DIRECT_OVERRIDE_RUN_KEY = 'scheduler.directOverrideRun';
const DIRECT_OVERRIDE_RECOVERY_WINDOW_MS = 20_000;
const EMPTY_PROGRESS = {};
const SOURCE_OPTIONS = [
    { value: 'jobsdb', label: 'JobsDB' },
    { value: 'ctgoodjobs', label: 'CTgoodjobs' },
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

function formatApiErrorDetail(detail, fallback = '启动失败') {
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
            error: '请至少选择一个分类 (Please select at least one category)',
        };
    }

    if (crawlPhase === 'listing' && (!Number.isInteger(maxPages) || maxPages < 1 || maxPages > 1000)) {
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
            max_pages: maxPages,
            detail_limit: crawlPhase === 'detail' ? detailLimit : 100,
            ...(sourceListingCrawlJobId ? { source_listing_crawl_job_id: sourceListingCrawlJobId } : {}),
        },
    };
}

function ScheduleManager({ onNavigateToAI }) {
    // State
    const [schedules, setSchedules] = useState([]);
    const [categories, setCategories] = useState([]);
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

    // Fetch schedules
    const fetchSchedules = useCallback(async () => {
        try {
            const response = await fetch(`${API_BASE}/schedules`);
            if (!response.ok) throw new Error('获取任务列表失败');
            const data = await response.json();
            setSchedules(data.schedules || []);
        } catch (err) {
            setError(err.message);
        }
    }, []);

    // Fetch categories
    const fetchCategories = useCallback(async (sourceSite) => {
        try {
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
            if (!response.ok) throw new Error('获取分类列表失败');
            const data = await response.json();
            setCategories(data.categories || []);
        } catch (err) {
            console.error('Failed to fetch categories:', err);
            setCategories([]);
            setError(err.message);
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
                throw new Error('获取抓取进度失败');
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

    const handleResumeCrawlJob = useCallback(async (crawlJobId) => {
        const response = await fetch(`${API_BASE}/crawl-jobs/${crawlJobId}/resume`, {
            method: 'POST',
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

    // Initial load
    useEffect(() => {
        fetchSchedules();
        fetchCategories(currentSourceSite);
        bootstrapProgressPanel();
    }, [bootstrapProgressPanel, currentSourceSite, fetchCategories, fetchSchedules]);

    // Create schedule
    const handleCreate = async (formData) => {
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
                throw new Error(errData.detail || '创建失败');
            }
            await fetchSchedules();
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
        setIsLoading(true);
        try {
            const response = await fetch(`${API_BASE}/schedules/${id}/toggle`, {
                method: 'POST'
            });
            if (!response.ok) throw new Error('切换状态失败');
            await fetchSchedules();
        } catch (err) {
            setError(err.message);
        } finally {
            setIsLoading(false);
        }
    };

    // Delete schedule
    const handleDelete = async (id) => {
        if (!window.confirm('确定要删除此定时任务吗？')) return;
        setIsLoading(true);
        try {
            const response = await fetch(`${API_BASE}/schedules/${id}`, {
                method: 'DELETE'
            });
            if (!response.ok) throw new Error('删除失败');
            await fetchSchedules();
        } catch (err) {
            setError(err.message);
        } finally {
            setIsLoading(false);
        }
    };

    // Run now
    const handleRun = async (id) => {
        setIsLoading(true);
        try {
            const response = await fetch(`${API_BASE}/crawl-jobs`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ schedule_id: id })
            });
            if (!response.ok) throw new Error('执行失败');
            await fetchSchedules();
        } catch (err) {
            setError(err.message);
        } finally {
            setIsLoading(false);
        }
    };

    // View history
    const handleViewHistory = async (id) => {
        try {
            const response = await fetch(`${API_BASE}/schedules/${id}/history`);
            if (!response.ok) throw new Error('获取历史失败');
            const data = await response.json();
            const schedule = schedules.find(s => s.id === id);
            setHistoryData({
                executions: data.executions || [],
                scheduleName: schedule?.name || '未知任务'
            });
        } catch (err) {
            setError(err.message);
        }
    };

    // Immediate scrape
    const handleImmediateScrape = async () => {
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
        }));
    };

    const filteredSchedules = schedules.filter(
        (schedule) => (schedule.source_site || 'jobsdb') === currentSourceSite
    );

    return (
        <div className="scheduler-container">
            <header className="scheduler-header">
                <div>
                    <h2><CalendarClock className="title-icon" /> Task Control Board</h2>
                    <p className="subtitle">Manage automated and direct scraping vectors</p>
                </div>
                <div className="header-actions">
                    <button
                        className="cyber-btn primary-glow"
                        onClick={() => setShowForm(!showForm)}
                    >
                        {showForm ? 'Close Form' : <><Plus size={18} /> New Automation</>}
                    </button>
                    <button
                        className="cyber-btn run-btn"
                        onClick={() => setShowImmediateScrape(!showImmediateScrape)}
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

            {error && (
                <div className="error-banner glass-panel">
                    <AlertTriangle size={20} />
                    <span>{error}</span>
                    <button onClick={() => setError(null)} className="close-error">×</button>
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
                        onClick={() => setProgressRecoveryNotice(null)}
                        className="close-error"
                    >
                        ×
                    </button>
                </div>
            )}

            {showProgress && (
                <ScrapeProgressPanel
                    isVisible={showProgress}
                    initialProgress={progressPanelState.initialProgress}
                    recoveryStartedAt={progressPanelState.recoveryStartedAt}
                    recoveryWindowMs={DIRECT_OVERRIDE_RECOVERY_WINDOW_MS}
                    onClose={handleProgressClose}
                    onNavigateToAI={onNavigateToAI}
                    onResumeCrawlJob={handleResumeCrawlJob}
                    onCancelCrawlJob={handleCancelCrawlJob}
                />
            )}

            {showImmediateScrape && (
                <div className="immediate-form-panel glass-panel">
                    <h3>Direct Override Sequence</h3>
                    <p className="form-hint">Select sectors to scan immediately. Process runs asynchronously.</p>

                    <div className="cyber-form-group">
                        <label htmlFor="immediate-crawl-phase">Crawl Phase</label>
                        <select
                            id="immediate-crawl-phase"
                            className="premium-select"
                            value={immediateForm.crawl_phase}
                            onChange={(e) => setImmediateForm(prev => ({
                                ...prev,
                                crawl_phase: e.target.value,
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
                            {CRAWL_MODE_OPTIONS.map((option) => (
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
                        <label>{immediateForm.crawl_phase === 'detail' ? 'Detail Batch Size' : 'Max Depth (Pages)'}</label>
                        <input
                            type="number"
                            min="1"
                            max={immediateForm.crawl_phase === 'detail' ? '5000' : '1000'}
                            className="premium-input w-24"
                            value={immediateForm.crawl_phase === 'detail' ? immediateForm.detail_limit : immediateForm.max_pages}
                            onChange={(e) => setImmediateForm(prev => ({
                                ...prev,
                                ...(immediateForm.crawl_phase === 'detail'
                                    ? { detail_limit: parseInt(e.target.value) || 100 }
                                    : { max_pages: parseInt(e.target.value) || 3 })
                            }))}
                        />
                    </div>

                    {immediateForm.crawl_phase === 'detail' && (
                        <div className="cyber-form-group">
                            <label htmlFor="source-listing-crawl-job-id">Source Listing Crawl Job ID</label>
                            <input
                                id="source-listing-crawl-job-id"
                                type="text"
                                className="premium-input"
                                value={immediateForm.source_listing_crawl_job_id}
                                onChange={(e) => setImmediateForm(prev => ({
                                    ...prev,
                                    source_listing_crawl_job_id: e.target.value,
                                }))}
                                placeholder="Optional specific listing batch"
                            />
                        </div>
                    )}

                    <div className="form-actions mt-6">
                        <button
                            className="cyber-btn run-btn w-full"
                            onClick={handleImmediateScrape}
                            disabled={isLoading}
                        >
                            <Zap size={18} /> {isLoading ? 'Initializing...' : 'Engage Scanner'}
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
                currentSourceSite={currentSourceSite}
                onToggle={handleToggle}
                onDelete={handleDelete}
                onRun={handleRun}
                onViewHistory={handleViewHistory}
                isLoading={isLoading}
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
