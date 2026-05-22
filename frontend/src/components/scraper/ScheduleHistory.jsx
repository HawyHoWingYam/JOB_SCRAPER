import React from 'react';

function formatDate(dateString) {
    if (!dateString) return '-';
    return new Date(dateString).toLocaleString('zh-CN');
}

function formatDuration(seconds) {
    if (!seconds) return '-';
    if (seconds < 60) return `${seconds} 秒`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins} 分 ${secs} 秒`;
}

function getStatusClass(status) {
    switch (status) {
        case 'completed': return 'status-success';
        case 'failed': return 'status-error';
        case 'running': return 'status-running';
        default: return 'status-pending';
    }
}

function getStatusText(status) {
    switch (status) {
        case 'completed': return '完成';
        case 'failed': return '失败';
        case 'running': return '运行中';
        default: return '等待中';
    }
}

function getDetailedStatus(exec) {
    if (!exec.phase1_completed && !exec.phase2_completed && !exec.phase3_completed && !exec.phase4_completed) {
        return '-';
    }
    const phases = [];
    if (exec.phase1_completed) phases.push('收集ID');
    if (exec.phase2_completed) phases.push('爬取详情');
    if (exec.phase3_completed) phases.push('AI分类');
    if (exec.phase4_completed) phases.push('保存数据');
    return phases.join(' → ');
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
                    <h3>执行历史 - {scheduleName}</h3>
                    <button className="btn-close" aria-label="Close history" onClick={onClose}>×</button>
                </div>

                <div className="schedule-history-body">
                    {executions.length === 0 ? (
                        <p className="no-history">暂无执行记录</p>
                    ) : (
                        <table className="history-table">
                            <thead>
                                <tr>
                                    <th>状态</th>
                                    <th>执行阶段</th>
                                    <th>开始时间</th>
                                    <th>完成时间</th>
                                    <th>耗时</th>
                                    <th>爬取数量</th>
                                    <th>错误信息</th>
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
                                        <td>{exec.jobs_scraped || 0}</td>
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
