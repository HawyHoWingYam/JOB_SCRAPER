import React from 'react';
import { Clock, Play, History, Trash2, Calendar, FileText, CheckCircle2, XCircle } from 'lucide-react';
import { formatCrawlModeLabel } from './crawlMode';
import { formatCrawlPhaseLabel } from './crawlPhase';

// 频率预设映射
const CRON_PRESETS = {
    '0 2 * * *': '每天凌晨 2 点',
    '0 */6 * * *': '每 6 小时',
    '0 */12 * * *': '每 12 小时',
    '0 9 * * 1': '每周一早上 9 点'
};

function formatSourceLabel(sourceSite) {
    return sourceSite === 'ctgoodjobs' ? 'CTgoodjobs' : 'JobsDB';
}

function formatCron(cronExpression) {
    return CRON_PRESETS[cronExpression] || cronExpression;
}

function formatDate(dateString) {
    if (!dateString) return '-';
    return new Date(dateString).toLocaleString('zh-CN', {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
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
                    <Play size={16} /> Execute
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

    if (schedules.length === 0) {
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
            <h3 className="section-title">Active Automations</h3>
            <div className="schedule-grid">
                {schedules.map(schedule => (
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
