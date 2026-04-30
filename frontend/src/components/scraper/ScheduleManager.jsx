import React, { useState, useEffect, useCallback } from 'react';
import { Plus, Zap, AlertTriangle, CalendarClock } from 'lucide-react';
import ScheduleForm from './ScheduleForm';
import ScheduleList from './ScheduleList';
import ScheduleHistory from './ScheduleHistory';
import ScrapeProgressPanel from './ScrapeProgressPanel';
import './Scheduler.css';

const API_URL = import.meta.env.VITE_API_URL || '';
const API_BASE = `${API_URL}/api/v1`;
const CATEGORY_API_BASE = `${API_URL}/api`;
const SOURCE_OPTIONS = [
    { value: 'jobsdb', label: 'JobsDB' },
    { value: 'ctgoodjobs', label: 'CTgoodjobs' },
];

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
    const categoryIds = normalizeCategoryIdsForSource(sourceSite, form?.category_ids);
    const maxPages = Number.parseInt(`${form?.max_pages ?? ''}`, 10);

    if (categoryIds.length === 0) {
        return {
            error: '请至少选择一个分类 (Please select at least one category)',
        };
    }

    if (!Number.isInteger(maxPages) || maxPages < 1 || maxPages > 1000) {
        return {
            error: 'Max pages must be a whole number between 1 and 1000.',
        };
    }

    return {
        payload: {
            source_site: sourceSite,
            category_ids: categoryIds,
            max_pages: maxPages,
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
        category_ids: [],
        max_pages: 3
    });
    const [scrapeStatus, setScrapeStatus] = useState(null);
    const [showProgress, setShowProgress] = useState(false);

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
            if (!response.ok) throw new Error('获取分类列表失败');
            const data = await response.json();
            setCategories(data.categories || []);
        } catch (err) {
            console.error('Failed to fetch categories:', err);
        }
    }, []);

    const bootstrapProgressPanel = useCallback(async () => {
        try {
            const response = await fetch(`${API_BASE}/scrape/progress`);
            if (!response.ok) {
                throw new Error('获取抓取进度失败');
            }

            const data = await response.json();
            const hasRecentProgress = Object.keys(data.all || {}).length > 0;
            setShowProgress(Boolean(data.has_active || hasRecentProgress));
        } catch (err) {
            console.error('Failed to bootstrap scrape progress:', err);
        }
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
            const response = await fetch(`${API_BASE}/schedules/${id}/run`, {
                method: 'POST'
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
        setScrapeStatus('Initiating scraping sequence...');
        try {
            const response = await fetch(`${API_BASE}/schedules/run-now`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(request.payload)
            });
            if (!response.ok) {
                const errData = await response.json();
                throw new Error(formatApiErrorDetail(errData.detail));
            }
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

            {showProgress && (
                <ScrapeProgressPanel
                    isVisible={showProgress}
                    onClose={() => setShowProgress(false)}
                    onNavigateToAI={onNavigateToAI}
                />
            )}

            {showImmediateScrape && (
                <div className="immediate-form-panel glass-panel">
                    <h3>Direct Override Sequence</h3>
                    <p className="form-hint">Select sectors to scan immediately. Process runs asynchronously.</p>

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
                        <label>Max Depth (Pages)</label>
                        <input
                            type="number"
                            min="1"
                            max="1000"
                            className="premium-input w-24"
                            value={immediateForm.max_pages}
                            onChange={(e) => setImmediateForm(prev => ({
                                ...prev,
                                max_pages: parseInt(e.target.value) || 3
                            }))}
                        />
                    </div>

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
