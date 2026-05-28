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

function formatCron(cronExpression) {
    return CRON_PRESETS[cronExpression] || cronExpression;
}

function formatDate(dateString) {
    if (!dateString) return '-';
    return new Date(dateString).toLocaleString('en-US', {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
    });
}

function parseTimestamp(value) {
    if (!value) {
        return null;
    }

    const parsed = Date.parse(value);
    return Number.isNaN(parsed) ? null : parsed;
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
                            <span className="value">{schedule.category_ids?.length || 0} selected</span>
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
                            <span className="value">{formatDate(schedule.last_run_at)}</span>
                        </div>
                    </div>

                    <div className="info-block">
                        <Play size={16} className="info-icon" />
                        <div className="info-content">
                            <span className="label">Next Run</span>
                            <span className="value">{formatDate(schedule.next_run_at)}</span>
                        </div>
                    </div>
                </div>
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
