import React from 'react';
import { Clock, Play, History, Trash2, Calendar, FileText, CheckCircle2, XCircle } from 'lucide-react';
import { formatCrawlModeLabel } from './crawlMode';
import { formatCrawlPhaseLabel } from './crawlPhase';

const CRON_PRESETS = {
    '0 2 * * *': 'Daily at 02:00',
    '0 */6 * * *': 'Every 6 hours',
    '0 */12 * * *': 'Every 12 hours',
    '0 9 * * 1': 'Mondays at 09:00'
};

function formatSourceLabel(sourceSite) {
    return sourceSite === 'ctgoodjobs' ? 'CTgoodjobs' : 'JobsDB';
}

function formatExecutionStatus(status) {
    switch (status) {
        case 'completed':
            return 'Completed';
        case 'completed_with_ai_failures':
            return 'Completed With AI Failures';
        case 'failed':
            return 'Failed';
        case 'running':
            return 'Running';
        case 'pending':
            return 'Pending';
        default:
            return null;
    }
}

function formatLatestExecutionVolume(schedule) {
    const scraped = Number(schedule.latest_execution_jobs_scraped || 0).toLocaleString();
    const ingested = Number(schedule.latest_execution_jobs_saved || 0).toLocaleString();
    return `${scraped} scraped / ${ingested} ingested`;
}

function buildCategorySummary(schedule, categories = []) {
    const categoryIds = Array.isArray(schedule.category_ids) ? schedule.category_ids.map((id) => `${id}`) : [];
    if (categoryIds.length === 0) {
        return 'No sectors selected';
    }

    const categoryLookup = new Map(
        categories.map((category) => [`${category.id}`, category.name])
    );
    const names = categoryIds.map((id) => categoryLookup.get(id)).filter(Boolean);
    if (names.length === 0) {
        return `${categoryIds.length} selected`;
    }

    if (names.length <= 2) {
        return names.join(', ');
    }

    return `${names.slice(0, 2).join(', ')}, +${names.length - 2} more`;
}

function formatCron(cronExpression) {
    return CRON_PRESETS[cronExpression] || cronExpression;
}

function formatDate(dateString) {
    if (!dateString) return '-';
    return new Date(dateString).toLocaleString('en-US', {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
    });
}

function formatLastRunValue(dateString) {
    return dateString ? formatDate(dateString) : 'Never';
}

function formatNextRunValue(schedule) {
    if (schedule.next_run_at) {
        return formatDate(schedule.next_run_at);
    }

    return schedule.is_active ? 'Pending scheduler' : 'Paused';
}

function parseTimestamp(value) {
    if (!value) {
        return null;
    }

    const parsed = Date.parse(value);
    return Number.isNaN(parsed) ? null : parsed;
}

function formatRelativeTimeHint(value, { future = false } = {}) {
    const timestamp = parseTimestamp(value);
    if (timestamp === null) {
        return null;
    }

    const deltaMs = timestamp - Date.now();
    const absMs = Math.abs(deltaMs);

    if (future) {
        if (deltaMs <= 0) {
            return 'Overdue';
        }
        if (absMs < 60_000) {
            return 'Due soon';
        }
    } else if (absMs < 60_000) {
        return 'Just now';
    }

    const minutes = Math.round(absMs / 60_000);
    if (minutes < 60) {
        return future ? `In ${minutes}m` : `${minutes}m ago`;
    }

    const hours = Math.round(absMs / 3_600_000);
    if (hours < 24) {
        return future ? `In ${hours}h` : `${hours}h ago`;
    }

    const days = Math.round(absMs / 86_400_000);
    return future ? `In ${days}d` : `${days}d ago`;
}

function sortSchedulesForDisplay(schedules) {
    return [...schedules].sort((left, right) => {
        const leftActiveRank = left.is_active ? 0 : 1;
        const rightActiveRank = right.is_active ? 0 : 1;
        if (leftActiveRank !== rightActiveRank) {
            return leftActiveRank - rightActiveRank;
        }

        if (leftActiveRank === 0) {
            const leftNextRun = parseTimestamp(left.next_run_at);
            const rightNextRun = parseTimestamp(right.next_run_at);

            if (leftNextRun !== null || rightNextRun !== null) {
                if (leftNextRun === null) return 1;
                if (rightNextRun === null) return -1;
                if (leftNextRun !== rightNextRun) {
                    return leftNextRun - rightNextRun;
                }
            }
        } else {
            const leftLastRun = parseTimestamp(left.last_run_at);
            const rightLastRun = parseTimestamp(right.last_run_at);

            if (leftLastRun !== null || rightLastRun !== null) {
                if (leftLastRun === null) return 1;
                if (rightLastRun === null) return -1;
                if (leftLastRun !== rightLastRun) {
                    return rightLastRun - leftLastRun;
                }
            }
        }

        const leftName = `${left.name || ''}`.trim();
        const rightName = `${right.name || ''}`.trim();
        const nameComparison = leftName.localeCompare(rightName, 'en', { sensitivity: 'base' });
        if (nameComparison !== 0) {
            return nameComparison;
        }

        return `${left.id || ''}`.localeCompare(`${right.id || ''}`, 'en', { sensitivity: 'base' });
    });
}

function ScheduleCard({
    schedule,
    categories,
    onToggle,
    onDelete,
    onRun,
    onViewHistory,
    isLoading,
    scheduleAutomationDisabled,
    manualRunDisabled,
}) {
    const isActive = schedule.is_active;
    const sourceLabel = formatSourceLabel(schedule.source_site || 'jobsdb');
    const crawlPhaseLabel = formatCrawlPhaseLabel(schedule.crawl_phase);
    const crawlModeLabel = formatCrawlModeLabel(schedule.crawl_mode);
    const categorySummary = buildCategorySummary(schedule, categories);
    const stateLabel = isActive ? 'Active' : 'Paused';
    const lastRunHint = formatRelativeTimeHint(schedule.last_run_at);
    const nextRunHint = formatRelativeTimeHint(schedule.next_run_at, { future: true });
    const latestExecutionStatus = formatExecutionStatus(schedule.latest_execution_status);

    return (
        <div className={`schedule-card glass-panel ${isActive ? 'active-glow' : ''}`}>
            <div className="schedule-card-header">
                <div className="schedule-title-area">
                    {isActive ? (
                        <CheckCircle2 size={20} className="status-icon active" />
                    ) : (
                        <XCircle size={20} className="status-icon inactive" />
                    )}
                    <h4>{schedule.name}</h4>
                    <span className="schedule-source-badge">{sourceLabel}</span>
                    <span className={`schedule-state-badge ${isActive ? 'schedule-state-active' : 'schedule-state-paused'}`}>
                        {stateLabel}
                    </span>
                </div>
                <label className="cyber-switch">
                    <input
                        type="checkbox"
                        checked={isActive}
                        onChange={() => onToggle(schedule.id)}
                        disabled={scheduleAutomationDisabled}
                    />
                    <span className="cyber-slider"></span>
                </label>
            </div>

            <div className="schedule-card-body">
                <div className="schedule-info-grid">
                    <div className="info-block">
                        <Clock size={16} className="info-icon" />
                        <div className="info-content">
                            <span className="label">Frequency</span>
                            <span className="value highlight">{formatCron(schedule.cron_expression)}</span>
                        </div>
                    </div>

                    <div className="info-block">
                        <FileText size={16} className="info-icon" />
                        <div className="info-content">
                            <span className="label">Categories</span>
                            <span className="value">{categorySummary}</span>
                        </div>
                    </div>

                    <div className="info-block">
                        <Play size={16} className="info-icon" />
                        <div className="info-content">
                            <span className="label">Phase</span>
                            <span className="value">{crawlPhaseLabel}</span>
                        </div>
                    </div>

                    <div className="info-block">
                        <Play size={16} className="info-icon" />
                        <div className="info-content">
                            <span className="label">Mode</span>
                            <span className="value">{crawlModeLabel}</span>
                        </div>
                    </div>

                    <div className="info-block">
                        <Calendar size={16} className="info-icon" />
                        <div className="info-content">
                            <span className="label">Last Run</span>
                            <span className="value">{formatLastRunValue(schedule.last_run_at)}</span>
                            {lastRunHint && <span className="subvalue">{lastRunHint}</span>}
                        </div>
                    </div>

                    <div className="info-block">
                        <Play size={16} className="info-icon" />
                        <div className="info-content">
                            <span className="label">Next Run</span>
                            <span className="value">{formatNextRunValue(schedule)}</span>
                            {nextRunHint && <span className="subvalue">{nextRunHint}</span>}
                        </div>
                    </div>
                </div>

                {latestExecutionStatus && (
                    <div className="schedule-execution-summary">
                        <span className="label">Last outcome</span>
                        <strong>{latestExecutionStatus}</strong>
                        <span>{formatLatestExecutionVolume(schedule)}</span>
                    </div>
                )}
            </div>

            <div className="schedule-card-actions">
                <button
                    className="cyber-btn run-btn"
                    onClick={() => onRun(schedule.id)}
                    disabled={manualRunDisabled}
                    title="Force Run Now"
                >
                    <Play size={16} /> Run Now
                </button>
                <button
                    className="cyber-btn history-btn"
                    onClick={() => onViewHistory(schedule.id)}
                    title="View Logs"
                >
                    <History size={16} /> Logs
                </button>
                <button
                    className="cyber-btn danger-btn"
                    onClick={() => onDelete(schedule.id)}
                    disabled={isLoading}
                    title="Delete Job"
                >
                    <Trash2 size={16} />
                </button>
            </div>
        </div>
    );
}

function ScheduleList({
    schedules,
    categories = [],
    currentSourceSite,
    onToggle,
    onDelete,
    onRun,
    onViewHistory,
    isLoading,
    scheduleAutomationDisabled = isLoading,
    manualRunDisabled = isLoading,
}) {
    const sourceLabel = formatSourceLabel(currentSourceSite);
    const sortedSchedules = sortSchedulesForDisplay(schedules);

    if (sortedSchedules.length === 0) {
        return (
            <div className="schedule-list-empty glass-panel">
                <Clock size={48} className="empty-icon" />
                <h3>No {sourceLabel} automated tasks</h3>
                <p>Create a {sourceLabel} schedule to automate crawler ops.</p>
            </div>
        );
    }

    return (
        <div className="schedule-list-container">
            <h3 className="section-title">Scheduled Automation</h3>
            <div className="schedule-grid">
                {sortedSchedules.map(schedule => (
                    <ScheduleCard
                        key={schedule.id}
                        schedule={schedule}
                        categories={categories}
                        onToggle={onToggle}
                        onDelete={onDelete}
                        onRun={onRun}
                        onViewHistory={onViewHistory}
                        isLoading={isLoading}
                        scheduleAutomationDisabled={scheduleAutomationDisabled}
                        manualRunDisabled={manualRunDisabled}
                    />
                ))}
            </div>
        </div>
    );
}

export default ScheduleList;
