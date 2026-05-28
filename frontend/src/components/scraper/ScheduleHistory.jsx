import React from 'react';
import { X } from 'lucide-react';

function formatDate(dateString) {
    if (!dateString) return '-';
    return new Date(dateString).toLocaleString('en-US');
}

function formatDuration(seconds) {
    if (seconds == null || Number.isNaN(Number(seconds))) return '-';
    if (Number(seconds) === 0) return '0s';
    if (seconds < 60) return `${seconds}s`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs}s`;
}

function formatExecutionVolume(exec) {
    const scraped = Number(exec.jobs_scraped || 0).toLocaleString();
    const saved = Number(exec.jobs_saved || 0).toLocaleString();
    return `${scraped} / ${saved}`;
}

function getStatusClass(status) {
    switch (status) {
        case 'completed': return 'status-success';
        case 'completed_with_ai_failures': return 'status-warning';
        case 'failed': return 'status-error';
        case 'running': return 'status-running';
        default: return 'status-pending';
    }
}

function getStatusText(status) {
    switch (status) {
        case 'completed': return 'Completed';
        case 'completed_with_ai_failures': return 'Completed With AI Failures';
        case 'failed': return 'Failed';
        case 'running': return 'Running';
        default: return 'Pending';
    }
}

function getDetailedStatus(exec) {
    if (
        !exec.phase1_completed
        && !exec.phase2_completed
        && !exec.phase3_completed
        && !exec.phase4_completed
        && !exec.phase5_completed
    ) {
        return '-';
    }
    const phases = [];
    if (exec.phase1_completed) phases.push('Collect IDs');
    if (exec.phase2_completed) phases.push('Fetch Details');
    if (exec.phase3_completed) phases.push('AI Classify');
    if (exec.phase4_completed) phases.push('Persist Data');
    if (exec.phase5_completed) phases.push('AI Enrich');
    return phases.join(' -> ');
}

function formatExecutionPipelineCounts(exec) {
    const metrics = [
        { label: 'IDs', value: Number(exec.ids_collected || 0).toLocaleString() },
        { label: 'Scraped', value: Number(exec.jobs_scraped || 0).toLocaleString() },
    ];

    if (Number(exec.jobs_classified || 0) > 0) {
        metrics.push({
            label: 'Classified',
            value: Number(exec.jobs_classified || 0).toLocaleString(),
        });
    }

    metrics.push({
        label: 'Ingested',
        value: Number(exec.jobs_saved || 0).toLocaleString(),
    });

    return metrics;
}

function renderExecutionMetric(metric) {
    return (
        <span className="snapshot-pill" key={metric.label}>
            <strong>{metric.label}</strong>
            <span>{metric.value}</span>
        </span>
    );
}

function renderSnapshotItem(label, value) {
    return (
        <span className="snapshot-pill" key={label}>
            <strong>{label}</strong>
            <span>{value}</span>
        </span>
    );
}

function renderRequestSnapshot(exec) {
    const snapshot = exec.request_payload_snapshot;
    if (!snapshot && !exec.crawl_job_id) {
        return null;
    }

    const categoryCount = Array.isArray(snapshot?.category_ids) ? snapshot.category_ids.length : 0;
    const items = [];

    if (snapshot?.source_site) {
        items.push(renderSnapshotItem('Source', snapshot.source_site));
    }
    if (snapshot?.crawl_phase) {
        items.push(renderSnapshotItem('Phase', snapshot.crawl_phase));
    }
    if (snapshot?.crawl_mode) {
        items.push(renderSnapshotItem('Mode', snapshot.crawl_mode));
    }
    items.push(renderSnapshotItem('Categories', `${categoryCount} selected`));
    if (snapshot?.source_listing_crawl_job_id) {
        items.push(renderSnapshotItem('Detail Batch', snapshot.source_listing_crawl_job_id));
    }
    if (snapshot?.detail_limit) {
        items.push(renderSnapshotItem('Detail Limit', `${snapshot.detail_limit}`));
    }
    if (exec.crawl_job_id) {
        items.push(renderSnapshotItem('Crawl Job', exec.crawl_job_id));
    }

    return (
        <div className="execution-request-snapshot">
            <div className="snapshot-title">Request Snapshot</div>
            <div className="snapshot-grid">{items}</div>
        </div>
    );
}

function ScheduleHistory({ executions, scheduleName, onClose }) {
    return (
        <div className="schedule-history-modal">
            <div className="schedule-history-content">
                <div className="schedule-history-header">
                    <h3>Execution History - {scheduleName}</h3>
                    <button className="btn-close" aria-label="Close history" onClick={onClose}>
                        <X size={18} />
                    </button>
                </div>

                <div className="schedule-history-body">
                    {executions.length === 0 ? (
                        <p className="no-history">No execution records yet.</p>
                    ) : (
                        <table className="history-table">
                            <thead>
                                <tr>
                                    <th>Status</th>
                                    <th>Execution Phase</th>
                                    <th>Started</th>
                                    <th>Completed</th>
                                    <th>Duration</th>
                                    <th>Execution Counts</th>
                                    <th>Error</th>
                                </tr>
                            </thead>
                            <tbody>
                                {executions.map(exec => (
                                    <tr key={exec.id}>
                                        <td>
                                            <span className={`status-badge ${getStatusClass(exec.status)}`}>
                                                {getStatusText(exec.status)}
                                            </span>
                                        </td>
                                        <td>
                                            <div className="execution-phases">
                                                {getDetailedStatus(exec)}
                                            </div>
                                            {renderRequestSnapshot(exec)}
                                        </td>
                                        <td>{formatDate(exec.started_at)}</td>
                                        <td>{formatDate(exec.completed_at)}</td>
                                        <td>{formatDuration(exec.duration_seconds)}</td>
                                        <td>
                                            <div className="snapshot-grid">
                                                {formatExecutionPipelineCounts(exec).map(renderExecutionMetric)}
                                            </div>
                                        </td>
                                        <td className="error-cell">
                                            {exec.error_message || '-'}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </div>
            </div>
        </div>
    );
}

export default ScheduleHistory;
