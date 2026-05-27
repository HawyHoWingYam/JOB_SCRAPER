import React, { useState, useEffect, useRef } from 'react';
import { API_BASE_URL } from '../../api/base';
import { formatCrawlModeLabel } from './crawlMode';
import {
    formatListingBatchIdentity,
    formatScraperSourceLabel,
} from './listingBatchLabel';

const API_URL = API_BASE_URL;
const API_BASE = `${API_URL}/api/v1`;
const EMPTY_PROGRESS = {};
const MAX_VISIBLE_TASKS = 5;

function ScrapeProgressPanel({
    isVisible,
    initialProgress = EMPTY_PROGRESS,
    recoveryStartedAt,
    recoveryWindowMs,
    onClose,
    onNavigateToAI,
    onResumeCrawlJob,
    onCancelCrawlJob,
    onOpenManualActionBrowser,
    onGetManualActionReuseStatus,
    onCloseManualActionWindows
}) {
    const [progress, setProgress] = useState(initialProgress);
    const [isConnected, setIsConnected] = useState(false);
    const [error, setError] = useState(null);
    const eventSourceRef = useRef(null);
    const reconnectTimeoutRef = useRef(null);
    const recoveryTimeoutRef = useRef(null);
    const wasVisibleRef = useRef(false);
    const onCloseRef = useRef(onClose);

    onCloseRef.current = onClose;

    const clearReconnectTimeout = () => {
        if (reconnectTimeoutRef.current) {
            clearTimeout(reconnectTimeoutRef.current);
            reconnectTimeoutRef.current = null;
        }
    };

    const clearRecoveryTimeout = () => {
        if (recoveryTimeoutRef.current) {
            clearTimeout(recoveryTimeoutRef.current);
            recoveryTimeoutRef.current = null;
        }
    };

    const closeEventSource = () => {
        if (eventSourceRef.current) {
            eventSourceRef.current.close();
            eventSourceRef.current = null;
        }
    };

    useEffect(() => {
        const hasInitialProgress = Object.keys(initialProgress).length > 0;
        const hasCurrentProgress = Object.keys(progress).length > 0;

        if (!isVisible) {
            wasVisibleRef.current = false;
            setProgress(EMPTY_PROGRESS);
            setError(null);
            return;
        }

        if (!wasVisibleRef.current || (!hasCurrentProgress && hasInitialProgress)) {
            setProgress(initialProgress);
        }

        wasVisibleRef.current = true;
    }, [initialProgress, isVisible, progress]);

    useEffect(() => {
        if (!isVisible) {
            clearReconnectTimeout();
            closeEventSource();
            setIsConnected(false);
            return;
        }

        const connectSSE = () => {
            const eventSource = new EventSource(`${API_BASE}/scrape/progress/stream`);
            eventSourceRef.current = eventSource;
            const isCurrentStream = () => eventSourceRef.current === eventSource;

            eventSource.onopen = () => {
                if (!isCurrentStream()) {
                    return;
                }
                setIsConnected(true);
                setError(null);
            };

            eventSource.onmessage = (event) => {
                if (!isCurrentStream()) {
                    return;
                }
                try {
                    const data = JSON.parse(event.data);
                    if (data.closed) {
                        clearRecoveryTimeout();
                        eventSource.close();
                        eventSourceRef.current = null;
                        setIsConnected(false);
                        onCloseRef.current?.('closed');
                        return;
                    }
                    setProgress(data.all || {});
                } catch (e) {
                    console.error('Failed to parse SSE data:', e);
                }
            };

            eventSource.onerror = () => {
                if (!isCurrentStream()) {
                    return;
                }
                setError('Connection lost. Reconnecting...');
                setIsConnected(false);
                eventSource.close();
                eventSourceRef.current = null;
                reconnectTimeoutRef.current = setTimeout(() => {
                    reconnectTimeoutRef.current = null;
                    connectSSE();
                }, 3000);
            };
        };

        connectSSE();

        return () => {
            clearReconnectTimeout();
            closeEventSource();
        };
    }, [isVisible]);

    const progressEntries = Object.entries(progress).sort((leftEntry, rightEntry) => {
        return getProgressSortTimestamp(rightEntry[1]) - getProgressSortTimestamp(leftEntry[1]);
    });
    const progressSections = buildProgressSections(progressEntries);
    const visibleTaskCount = progressSections.reduce((count, section) => count + section.entries.length, 0);
    const hasProgress = visibleTaskCount > 0;

    useEffect(() => {
        clearRecoveryTimeout();

        if (!isVisible || !recoveryStartedAt || hasProgress) {
            return;
        }

        const recoveryWindow = Number(recoveryWindowMs);
        if (!Number.isFinite(recoveryWindow) || recoveryWindow <= 0) {
            return;
        }

        const recoveryDeadline = new Date(recoveryStartedAt).getTime() + recoveryWindow;

        if (Number.isNaN(recoveryDeadline)) {
            return;
        }

        const closeForRecoveryTimeout = () => {
            clearReconnectTimeout();
            closeEventSource();
            setIsConnected(false);
            onCloseRef.current?.('recovery_timeout');
        };

        const remainingMs = recoveryDeadline - Date.now();

        if (remainingMs <= 0) {
            closeForRecoveryTimeout();
            return;
        }

        recoveryTimeoutRef.current = setTimeout(() => {
            recoveryTimeoutRef.current = null;
            closeForRecoveryTimeout();
        }, remainingMs);

        return () => {
            clearRecoveryTimeout();
        };
    }, [hasProgress, isVisible, recoveryStartedAt, recoveryWindowMs]);

    if (!isVisible) return null;
    const isRecovering = Boolean(recoveryStartedAt) && !hasProgress;

    return (
        <div className="scrape-progress-panel">
            <div className="progress-panel-header">
                <div>
                    <h3>Scraping Progress</h3>
                    {hasProgress && (
                        <div className="progress-count-hint">
                            Showing {visibleTaskCount} of {progressEntries.length} operator-visible tasks
                        </div>
                    )}
                </div>
                <div className="connection-status">
                    <span className={`status-dot ${isConnected ? 'connected' : 'disconnected'}`} />
                    {isConnected ? 'Live' : 'Connecting...'}
                </div>
            </div>

            {error && <div className="progress-error">{error}</div>}

            <div className="progress-panel-body">
                {!hasProgress ? (
                    <div className="no-progress">
                        {isRecovering ? 'Reconnecting to active Direct Override...' : 'No active scraping tasks'}
                    </div>
                ) : (
                    progressSections.map((section) => (
                        <div key={section.key} className="progress-section">
                            <div className="progress-count-hint">{section.title}</div>
                            {section.entries.map(([taskKey, data]) => (
                                <ProgressItem
                                    key={taskKey}
                                    taskKey={taskKey}
                                    data={data}
                                    onNavigateToAI={onNavigateToAI}
                                    onResumeCrawlJob={onResumeCrawlJob}
                                    onCancelCrawlJob={onCancelCrawlJob}
                                    onOpenManualActionBrowser={onOpenManualActionBrowser}
                                    onGetManualActionReuseStatus={onGetManualActionReuseStatus}
                                    onCloseManualActionWindows={onCloseManualActionWindows}
                                />
                            ))}
                        </div>
                    ))
                )}
            </div>
        </div>
    );
}

function formatSourceLabel(sourceSite) {
    return formatScraperSourceLabel(sourceSite);
}

function formatDuration(seconds) {
    if (seconds == null || Number.isNaN(Number(seconds))) {
        return '-';
    }

    const wholeSeconds = Math.max(0, Math.round(Number(seconds)));
    if (wholeSeconds < 60) {
        return `${wholeSeconds}s`;
    }

    const mins = Math.floor(wholeSeconds / 60);
    const secs = wholeSeconds % 60;
    return `${mins}m ${secs}s`;
}

function formatTaskTimestamp(value) {
    if (!value) {
        return '-';
    }

    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return `${value}`;
    }

    return parsed.toLocaleString('en-US');
}

function formatCount(value) {
    return Number(value || 0).toLocaleString();
}

function formatCountPair(currentValue, totalValue) {
    const normalizedTotal = Number(totalValue);
    if (Number.isFinite(normalizedTotal) && normalizedTotal > 0) {
        return `${formatCount(currentValue)}/${formatCount(normalizedTotal)}`;
    }

    return `${formatCount(currentValue)}/?`;
}

function getProgressSortTimestamp(data) {
    const classification = classifyProgressEntry(data);
    const candidateValues = classification === 'live' || classification === 'attention'
        ? [data?.updated_at, data?.started_at, data?.queued_at]
        : [data?.completed_at, data?.started_at, data?.queued_at];

    for (const value of candidateValues) {
        const timestamp = Date.parse(value);
        if (!Number.isNaN(timestamp)) {
            return timestamp;
        }
    }

    return 0;
}

function formatMaybeCountPair(currentValue, totalValue) {
    const normalizedCurrent = Number(currentValue || 0);
    const normalizedTotal = Number(totalValue);

    if (
        Number.isFinite(normalizedTotal)
        && normalizedTotal > 0
        && normalizedTotal >= normalizedCurrent
    ) {
        return formatCountPair(normalizedCurrent, normalizedTotal);
    }

    return formatCount(normalizedCurrent);
}

function classifyProgressEntry(data) {
    if (data?.status === 'manual_action_required') {
        return 'attention';
    }

    if (
        data?.operator_state === 'completed_with_downstream_backlog'
        || data?.operator_state === 'stale_downstream_backlog'
    ) {
        return 'backlog';
    }

    if (['queued', 'dispatching', 'running', 'ai_running'].includes(data?.status)) {
        return 'live';
    }

    return 'terminal';
}

function buildProgressSections(progressEntries) {
    const groupedEntries = {
        attention: [],
        live: [],
        backlog: [],
        terminal: [],
    };

    progressEntries.forEach((entry) => {
        groupedEntries[classifyProgressEntry(entry[1])].push(entry);
    });

    const linkedBacklogBatchIds = new Set(
        [...groupedEntries.attention, ...groupedEntries.live]
            .map(([, data]) => `${data?.request_payload?.source_listing_crawl_job_id || ''}`.trim())
            .filter(Boolean)
    );
    if (linkedBacklogBatchIds.size > 0) {
        groupedEntries.backlog = groupedEntries.backlog.filter(
            ([taskKey]) => !linkedBacklogBatchIds.has(`${taskKey}`)
        );
    }

    const visibleKeys = new Set();
    const prioritizedEntries = [];
    ['attention', 'live', 'backlog', 'terminal'].forEach((groupKey) => {
        groupedEntries[groupKey].forEach((entry) => {
            if (prioritizedEntries.length >= MAX_VISIBLE_TASKS) {
                return;
            }
            prioritizedEntries.push(entry);
            visibleKeys.add(entry[0]);
        });
    });

    return [
        { key: 'attention', title: 'Needs Attention', entries: groupedEntries.attention.filter(([key]) => visibleKeys.has(key)) },
        { key: 'live', title: 'Running or Queued', entries: groupedEntries.live.filter(([key]) => visibleKeys.has(key)) },
        { key: 'backlog', title: 'Backlog Follow-up', entries: groupedEntries.backlog.filter(([key]) => visibleKeys.has(key)) },
        { key: 'terminal', title: 'Recent Terminal', entries: groupedEntries.terminal.filter(([key]) => visibleKeys.has(key)) },
    ].filter((section) => section.entries.length > 0);
}

function resolveDisplayState(data) {
    if (data?.status === 'manual_action_required') {
        return 'manual_action_required';
    }

    if (data?.status === 'failed') {
        return 'failed';
    }

    const proxyWarningsPresent = [
        data?.proxy_requests_challenge,
        data?.proxy_requests_network_fail,
        data?.proxy_requests_http_fail,
        data?.proxy_quarantined_total,
    ].some((value) => Number(value || 0) > 0);

    if (data?.status === 'running' && proxyWarningsPresent) {
        return 'running_with_warning';
    }

    if (data?.status === 'running' || data?.status === 'ai_running' || data?.status === 'dispatching') {
        return 'running';
    }

    if (data?.status === 'queued') {
        return 'queued';
    }

    if (data?.status === 'completed' || data?.status === 'completed_with_ai_failures') {
        return 'completed';
    }

    if (data?.status === 'cancelled') {
        return 'cancelled';
    }

    return data?.status || 'running';
}

function shouldExpandDiagnosticsByDefault(displayState) {
    return displayState === 'manual_action_required' || displayState === 'failed';
}

function buildStatusSignals({
    displayState,
    proxyEnabled,
    proxyWarningsPresent,
}) {
    const chips = [];

    if (displayState === 'manual_action_required') {
        chips.push('Intervention required');
    }

    if (displayState === 'failed') {
        chips.push('Failure');
    }

    if (displayState === 'running_with_warning' && proxyEnabled && proxyWarningsPresent) {
        chips.push('Proxy unstable');
    }

    return chips;
}

function buildContextChips({
    sourceSite,
    categoryName,
    crawlMode,
}) {
    const values = [];

    if (sourceSite) {
        values.push(formatSourceLabel(sourceSite));
    }

    if (categoryName) {
        values.push(categoryName);
    }

    if (crawlMode) {
        values.push(formatCrawlModeLabel(crawlMode));
    }

    return values;
}

function resolveMetricScope(data) {
    if (data?.metric_scope) {
        return data.metric_scope;
    }

    if (data?.status === 'manual_action_required') {
        return 'manual_action';
    }

    const backlogCountsVisible = [
        data?.listings_staged,
        data?.detail_pending,
        data?.detail_running,
        data?.detail_completed,
        data?.detail_failed,
        data?.detail_manual_action_required,
    ].some((value) => Number(value || 0) > 0);

    if (
        backlogCountsVisible
        && (
            data?.operator_state === 'completed_with_downstream_backlog'
            || data?.operator_state === 'stale_downstream_backlog'
        )
    ) {
        return 'backlog_pool';
    }

    if (data?.phase === 1) {
        return 'listing_run';
    }
    if (data?.phase === 2) {
        return 'detail_run';
    }
    if (data?.phase === 4) {
        return 'ingest_run';
    }
    if (data?.phase === 5 || data?.status === 'ai_running' || data?.ai_run_id) {
        return 'ai_run';
    }

    return 'crawl_job';
}

function buildDetailRunMetricLines({
    detailSelectedRows,
    detailSkippedExistingRows,
    detailTargetRows,
    jobsScraped,
    detailRunFailed,
    detailRunManualActionRequired,
}) {
    const lines = [];
    const runnableRows = detailTargetRows || Math.max(detailSelectedRows - detailSkippedExistingRows, 0);

    if (detailSelectedRows > 0) {
        lines.push(`Rows checked: ${formatCount(detailSelectedRows)}`);
    }
    if (detailSkippedExistingRows > 0) {
        lines.push(`Skipped existing: ${formatCount(detailSkippedExistingRows)}`);
    }

    lines.push(
        `Detail crawled: ${runnableRows > 0
            ? formatCountPair(jobsScraped, runnableRows)
            : formatCount(jobsScraped)
        }`
    );

    if (detailRunFailed > 0) {
        lines.push(`Failed rows: ${formatCount(detailRunFailed)}`);
    }
    if (detailRunManualActionRequired > 0) {
        lines.push(`Manual review: ${formatCount(detailRunManualActionRequired)}`);
    }

    return lines;
}

function ProgressItem({
    taskKey,
    data,
    onNavigateToAI,
    onResumeCrawlJob,
    onCancelCrawlJob,
    onOpenManualActionBrowser,
    onGetManualActionReuseStatus,
    onCloseManualActionWindows
}) {
    const [liveSessionMetadata, setLiveSessionMetadata] = useState(null);
    const [reuseStatusError, setReuseStatusError] = useState(null);
    const [showReuseRecoveryPrompt, setShowReuseRecoveryPrompt] = useState(false);
    const [showFreshResumeWarning, setShowFreshResumeWarning] = useState(false);
    const [isReuseChecking, setIsReuseChecking] = useState(false);
    const [isResumeSubmitting, setIsResumeSubmitting] = useState(null);
    const displayState = resolveDisplayState(data);
    const [isDiagnosticsOpen, setIsDiagnosticsOpen] = useState(
        shouldExpandDiagnosticsByDefault(displayState)
    );
    const {
        crawl_job_id,
        status,
        operator_state,
        source_site,
        category_name,
        crawl_mode,
        phase,
        manual_action,
        request_payload = {},
        // Phase 1
        job_ids_collected = 0,
        current_page,
        total_pages,
        // Phase 2
        jobs_scraped = 0,
        total_jobs = 0,
        current_job_title,
        detail_job_index,
        detail_job_total,
        // Phase 3
        jobs_classified = 0,
        classification_total = 0,
        // Phase 4
        jobs_saved = 0,
        save_total = 0,
        listings_staged = 0,
        jobs_skipped_existing = 0,
        detail_selected_rows = 0,
        detail_skipped_existing_rows = 0,
        detail_target_rows = 0,
        detail_run_failed = 0,
        detail_run_manual_action_required = 0,
        detail_pending = 0,
        detail_running = 0,
        detail_completed = 0,
        detail_failed = 0,
        detail_manual_action_required = 0,
        proxy_enabled,
        proxy_provider,
        proxy_requests_total = 0,
        proxy_requests_success = 0,
        proxy_requests_challenge = 0,
        proxy_requests_network_fail = 0,
        proxy_requests_http_fail = 0,
        proxy_quarantined_total = 0,
        // Phase 5
        ai_run_id,
        ai_completed_items = 0,
        ai_failed_items = 0,
        ai_total_items,
        // Timing
        queued_at,
        started_at,
        completed_at,
        elapsed_seconds = 0,
        error
    } = data;
    const taskId = crawl_job_id || taskKey;
    const elapsedLabel = formatDuration(elapsed_seconds);
    const effectiveDetailTotal = detail_job_total || total_jobs;
    const effectiveDetailIndex = detail_job_index || jobs_scraped;
    const aiProcessedItems = ai_completed_items + ai_failed_items;
    const aiTotalItems = ai_total_items || save_total || jobs_saved || total_jobs || jobs_scraped || aiProcessedItems;
    const sourceListingBatchId = `${request_payload?.source_listing_crawl_job_id || ''}`.trim();
    const listingBatchLabel = sourceListingBatchId
        ? formatListingBatchIdentity({
            sourceSite: source_site,
            crawlJobId: sourceListingBatchId,
        })
        : null;
    const hasDownstreamBacklog = operator_state === 'completed_with_downstream_backlog'
        || operator_state === 'stale_downstream_backlog';
    const metricScope = resolveMetricScope(data);
    const contextChips = buildContextChips({
        sourceSite: manual_action?.source_site || source_site,
        categoryName: category_name,
        crawlMode: crawl_mode,
    });
    const proxyWarningsPresent = [
        proxy_requests_challenge,
        proxy_requests_network_fail,
        proxy_requests_http_fail,
        proxy_quarantined_total,
    ].some((value) => Number(value || 0) > 0);
    const statusSignals = buildStatusSignals({
        displayState,
        proxyEnabled: proxy_enabled,
        proxyWarningsPresent,
    });

    useEffect(() => {
        setLiveSessionMetadata(null);
        setReuseStatusError(null);
        setShowReuseRecoveryPrompt(false);
        setShowFreshResumeWarning(false);
        setIsReuseChecking(false);
        setIsResumeSubmitting(null);
        setIsDiagnosticsOpen(shouldExpandDiagnosticsByDefault(displayState));
    }, [crawl_job_id, manual_action?.stage, status, displayState]);

    const renderHeader = (statusText, statusClass) => (
        <div className="progress-item-header">
            <div className="progress-heading-group">
                <span className="progress-task-id">{`Task ${taskId}`}</span>
                <div className="progress-context-row">
                    {contextChips.map((value) => (
                        <span key={`${taskId}-${value}`} className="progress-context-pill">
                            {value}
                        </span>
                    ))}
                </div>
            </div>
            <span className={`status-badge status-${statusClass}`}>
                {statusText}
            </span>
        </div>
    );

    const renderMetricLines = (lines) => (
        lines.length > 0 ? (
            <div className="progress-metric-grid">
                {lines.map((line) => (
                    <div key={`${taskId}-${line}`} className="progress-metric-card">
                        {line}
                    </div>
                ))}
            </div>
        ) : null
    );

    const renderTimingBlock = () => (
        <div className="progress-time-grid">
            <div className="progress-text">Queued: {formatTaskTimestamp(queued_at)}</div>
            <div className="progress-text">Started: {formatTaskTimestamp(started_at)}</div>
            <div className="progress-text">Ended: {formatTaskTimestamp(completed_at)}</div>
        </div>
    );

    if (status === 'manual_action_required' && manual_action) {
        const instructions = Array.isArray(manual_action.instructions)
            ? manual_action.instructions.filter(Boolean)
            : [];
        const isProxyUnavailable = manual_action.stage === 'proxy_unavailable';
        const metricLines = [];

        if (phase === 1) {
            metricLines.push(`Pages: ${formatCountPair(current_page || 0, total_pages)}`);
            metricLines.push(`IDs found: ${formatCount(job_ids_collected)}`);
        } else if (phase === 2) {
            metricLines.push(
                ...buildDetailRunMetricLines({
                    detailSelectedRows: detail_selected_rows,
                    detailSkippedExistingRows: detail_skipped_existing_rows,
                    detailTargetRows: detail_target_rows || effectiveDetailTotal,
                    jobsScraped: jobs_scraped,
                    detailRunFailed: detail_run_failed,
                    detailRunManualActionRequired: detail_run_manual_action_required || 1,
                })
            );
            if (detail_job_index || effectiveDetailTotal) {
                metricLines.push(`Current target: ${formatCountPair(effectiveDetailIndex, effectiveDetailTotal)}`);
            }
        } else if (phase === 5 || ai_run_id) {
            metricLines.push(`Items processed: ${formatCountPair(aiProcessedItems, aiTotalItems)}`);
        }

        const handleCopyValue = (value) => {
            if (!value) {
                return;
            }

            window.navigator.clipboard?.writeText?.(value);
        };

        const buildInlineErrorMessage = (value, fallback) => {
            if (typeof value === 'string' && value.trim()) {
                return value;
            }

            if (value instanceof Error && value.message) {
                return value.message;
            }

            return fallback;
        };

        const extractLiveSessionMetadata = (payload) => {
            if (!payload || typeof payload !== 'object') {
                return null;
            }

            if (payload.live_session && typeof payload.live_session === 'object') {
                return payload.live_session;
            }

            const hasSessionFields = [
                'session_id',
                'browser_channel',
                'attached_at',
                'last_seen_at',
                'debugger_url',
                'ws_endpoint',
            ].some((key) => payload[key] != null);

            return hasSessionFields ? payload : null;
        };

        const submitResume = async (strategy, fallbackMessage) => {
            if (!crawl_job_id) {
                return;
            }

            try {
                setIsResumeSubmitting(strategy);
                await onResumeCrawlJob?.(crawl_job_id, strategy);
                setReuseStatusError(null);
                setShowReuseRecoveryPrompt(false);
                setShowFreshResumeWarning(false);
            } catch (resumeError) {
                const detail = buildInlineErrorMessage(resumeError, fallbackMessage);
                console.error('Failed to resume crawl job:', resumeError);
                setReuseStatusError(detail);
            } finally {
                setIsResumeSubmitting(null);
            }
        };

        const handleOpenVerificationBrowser = async () => {
            if (!crawl_job_id && !manual_action.blocked_url) {
                return;
            }

            if (onOpenManualActionBrowser && crawl_job_id) {
                const openResult = await onOpenManualActionBrowser(crawl_job_id);
                const metadata = extractLiveSessionMetadata(openResult);
                if (metadata) {
                    setLiveSessionMetadata(metadata);
                }
                return;
            }

            if (manual_action.blocked_url && !onOpenManualActionBrowser) {
                window.open(manual_action.blocked_url, '_blank', 'noopener,noreferrer');
            }
        };

        const handleCloseProfileWindows = async () => {
            if (!crawl_job_id) {
                return;
            }

            try {
                await onCloseManualActionWindows?.(crawl_job_id);
            } catch (closeError) {
                console.error('Failed to close manual action profile windows:', closeError);
            }
        };

        const handleResumeUsingOpenBrowser = async () => {
            if (!crawl_job_id || !onGetManualActionReuseStatus) {
                await submitResume('reuse_open_browser', 'Failed to resume using the open browser');
                return;
            }

            setIsReuseChecking(true);
            setShowFreshResumeWarning(false);
            setLiveSessionMetadata(null);
            setReuseStatusError(null);
            setShowReuseRecoveryPrompt(false);

            try {
                const reuseStatus = await onGetManualActionReuseStatus(crawl_job_id);
                const metadata = extractLiveSessionMetadata(reuseStatus);

                if (metadata) {
                    setLiveSessionMetadata(metadata);
                }

                const reuseSupported = reuseStatus?.reuse_open_browser_supported !== false;
                if (reuseSupported && reuseStatus?.available) {
                    await submitResume('reuse_open_browser', 'Failed to resume using the open browser');
                    return;
                }

                setReuseStatusError(
                    buildInlineErrorMessage(
                        reuseStatus?.reason || reuseStatus?.detail,
                        'Open-browser reuse is unavailable right now. Retry attach or resume with a fresh profile.'
                    )
                );
                setShowReuseRecoveryPrompt(true);
            } catch (reuseError) {
                console.error('Failed to check manual action reuse status:', reuseError);
                setReuseStatusError(
                    buildInlineErrorMessage(reuseError, 'Failed to check open-browser reuse status')
                );
                setShowReuseRecoveryPrompt(true);
            } finally {
                setIsReuseChecking(false);
            }
        };

        const handleResumeFresh = () => {
            setLiveSessionMetadata(null);
            setReuseStatusError(null);
            setShowFreshResumeWarning(true);
            setShowReuseRecoveryPrompt(false);
        };

        const handleConfirmResumeFresh = async () => {
            await submitResume('fresh_profile', 'Failed to resume with a fresh browser profile');
        };

        const handleCancel = async () => {
            if (!crawl_job_id) {
                return;
            }

            try {
                await onCancelCrawlJob?.(crawl_job_id);
            } catch (cancelError) {
                console.error('Failed to cancel crawl job:', cancelError);
            }
        };

        return (
            <div className="progress-item warning">
                {renderHeader('Manual Action Required', 'warning')}
                <div className="progress-status-strip">
                    <div className="progress-status-summary">
                        <span className="progress-status-title">Next step</span>
                        <span className="progress-status-subtitle">
                            Resume this run after resolving the browser or profile blocker.
                        </span>
                    </div>
                    <div className="progress-status-signal-row">
                        {statusSignals.map((signal) => (
                            <span key={`${taskId}-${signal}`} className="progress-status-chip">
                                {signal}
                            </span>
                        ))}
                    </div>
                </div>
                {renderMetricLines(metricLines)}

                <div className="progress-decision-panel">
                    <button
                        type="button"
                        className="progress-link-button progress-primary-action"
                        onClick={isProxyUnavailable ? handleResumeFresh : handleResumeUsingOpenBrowser}
                        disabled={
                            isProxyUnavailable
                                ? isResumeSubmitting === 'fresh_profile'
                                : isReuseChecking || isResumeSubmitting === 'reuse_open_browser'
                        }
                    >
                        {isProxyUnavailable
                            ? (isResumeSubmitting === 'fresh_profile' ? 'Resuming Fresh...' : 'Resume Fresh')
                            : (isReuseChecking || isResumeSubmitting === 'reuse_open_browser'
                                ? 'Attaching...'
                                : 'Resume Using Open Browser')}
                    </button>
                    <div className="progress-secondary-actions">
                        {!isProxyUnavailable && (
                            <button
                                type="button"
                                className="progress-link-button"
                                onClick={handleResumeFresh}
                                disabled={isResumeSubmitting === 'fresh_profile'}
                            >
                                Resume Fresh
                            </button>
                        )}
                        {!isProxyUnavailable && manual_action.browser_profile_path && (
                            <button
                                type="button"
                                className="progress-link-button"
                                onClick={handleCloseProfileWindows}
                            >
                                Close Profile Windows
                            </button>
                        )}
                        <button
                            type="button"
                            className="progress-link-button"
                            onClick={handleCancel}
                        >
                            Cancel
                        </button>
                    </div>
                </div>

                <button
                    type="button"
                    className="progress-diagnostics-toggle"
                    aria-expanded={isDiagnosticsOpen ? 'true' : 'false'}
                    onClick={() => setIsDiagnosticsOpen((current) => !current)}
                >
                    Diagnostics
                </button>

                {isDiagnosticsOpen && (
                    <div className="progress-diagnostics-drawer">
                        <div className="progress-diagnostics-section">
                            <strong>Run timing</strong>
                            {renderTimingBlock()}
                            <div className="progress-stats">
                                <span>Elapsed: {elapsedLabel}</span>
                            </div>
                        </div>
                        <div className="progress-diagnostics-section">
                            <strong>Technical diagnostics</strong>
                            <div className="progress-text">Stage: {manual_action.stage || '-'}</div>
                            <div className="progress-text">{manual_action.blocked_url || '-'}</div>
                            <div className="progress-text">
                                Browser Profile Path: {manual_action.browser_profile_path || '-'}
                            </div>
                            <div className="progress-text">
                                Browser Channel: {manual_action.browser_channel || '-'}
                            </div>
                            {listingBatchLabel && (
                                <div className="progress-text">Listing batch: {listingBatchLabel}</div>
                            )}
                            {current_job_title && (
                                <div className="progress-text">Current title: {current_job_title}</div>
                            )}
                            {instructions.length > 0 && (
                                <ul className="progress-manual-action-list">
                                    {instructions.map((instruction, index) => (
                                        <li key={`${index}-${instruction}`}>{instruction}</li>
                                    ))}
                                </ul>
                            )}
                            {liveSessionMetadata && (
                                <div className="progress-manual-analysis">
                                    {liveSessionMetadata.browser_channel && (
                                        <div className="progress-text">
                                            Live Session Browser: {liveSessionMetadata.browser_channel}
                                        </div>
                                    )}
                                    {liveSessionMetadata.session_id && (
                                        <div className="progress-text">
                                            Live Session ID: {liveSessionMetadata.session_id}
                                        </div>
                                    )}
                                    {liveSessionMetadata.attached_at && (
                                        <div className="progress-text">
                                            Attached At: {liveSessionMetadata.attached_at}
                                        </div>
                                    )}
                                    {liveSessionMetadata.last_seen_at && (
                                        <div className="progress-text">
                                            Last Seen: {liveSessionMetadata.last_seen_at}
                                        </div>
                                    )}
                                </div>
                            )}
                            {showFreshResumeWarning && (
                                <div className="progress-manual-analysis">
                                    <div className="progress-text">
                                        Close any profile windows first before starting a fresh browser session.
                                    </div>
                                    <div className="progress-text">
                                        The app will not close them for you on this path.
                                    </div>
                                </div>
                            )}
                            {reuseStatusError && (
                                <div className="progress-error">{reuseStatusError}</div>
                            )}
                            <div className="progress-secondary-actions">
                                {!isProxyUnavailable && manual_action.blocked_url && (
                                    <button
                                        type="button"
                                        className="progress-link-button"
                                        onClick={handleOpenVerificationBrowser}
                                    >
                                        Open Verification Browser
                                    </button>
                                )}
                                <button
                                    type="button"
                                    className="progress-link-button"
                                    onClick={() => handleCopyValue(manual_action.blocked_url)}
                                >
                                    Copy URL
                                </button>
                                <button
                                    type="button"
                                    className="progress-link-button"
                                    onClick={() => handleCopyValue(manual_action.browser_profile_path)}
                                >
                                    Copy Profile Path
                                </button>
                                {!isProxyUnavailable && showReuseRecoveryPrompt && (
                                    <button
                                        type="button"
                                        className="progress-link-button"
                                        onClick={handleResumeUsingOpenBrowser}
                                        disabled={isReuseChecking || isResumeSubmitting === 'reuse_open_browser'}
                                    >
                                        Retry Attach
                                    </button>
                                )}
                                {showFreshResumeWarning && (
                                    <button
                                        type="button"
                                        className="progress-link-button"
                                        onClick={handleConfirmResumeFresh}
                                        disabled={isResumeSubmitting === 'fresh_profile'}
                                    >
                                        {isResumeSubmitting === 'fresh_profile' ? 'Resuming Fresh...' : 'Resume Fresh Now'}
                                    </button>
                                )}
                            </div>
                        </div>
                    </div>
                )}
            </div>
        );
    }

    let statusText = '';
    let statusClass = 'running';
    const metricLines = [];
    const detailLines = [];
    const isBacklogPoolScope = metricScope === 'backlog_pool';
    const isDetailRunScope = metricScope === 'detail_run';
    const detailTargetTotal = detail_target_rows || effectiveDetailTotal;

    if (status === 'queued') {
        statusText = 'Queued';
        detailLines.push('Awaiting crawl worker dispatch');
    } else if (isBacklogPoolScope) {
        statusText = 'Downstream Backlog';
        statusClass = 'warning';
        if (listings_staged > 0) {
            metricLines.push(`Staged listings: ${formatCount(listings_staged)}`);
        }
        if (detail_pending > 0) {
            metricLines.push(`Pending details: ${formatCount(detail_pending)}`);
        }
        if (detail_running > 0) {
            metricLines.push(`Running details: ${formatCount(detail_running)}`);
        }
        if (detail_completed > 0) {
            metricLines.push(`Completed details: ${formatCount(detail_completed)}`);
        }
        if (detail_failed > 0) {
            metricLines.push(`Failed details: ${formatCount(detail_failed)}`);
        }
        if (detail_manual_action_required > 0) {
            metricLines.push(`Manual review: ${formatCount(detail_manual_action_required)}`);
        }
    } else if (phase === 1) {
        statusText = 'Collecting IDs';
        metricLines.push(`Pages: ${formatCountPair(current_page || 0, total_pages)}`);
        metricLines.push(`IDs found: ${formatCount(job_ids_collected)}`);
        if (jobs_skipped_existing > 0) {
            metricLines.push(`Existing skipped: ${formatCount(jobs_skipped_existing)}`);
        }
    } else if (phase === 2 || isDetailRunScope) {
        statusText = 'Scraping Details';
        metricLines.push(
            ...buildDetailRunMetricLines({
                detailSelectedRows: detail_selected_rows,
                detailSkippedExistingRows: detail_skipped_existing_rows || jobs_skipped_existing,
                detailTargetRows: detailTargetTotal,
                jobsScraped: jobs_scraped,
                detailRunFailed: detail_run_failed,
                detailRunManualActionRequired: detail_run_manual_action_required,
            })
        );
        if (detail_job_index || effectiveDetailTotal) {
            metricLines.push(`Current target: ${formatCountPair(effectiveDetailIndex, effectiveDetailTotal)}`);
        }
        if (current_job_title) {
            detailLines.push(`Current title: ${current_job_title}`);
        }
    } else if (phase === 3) {
        statusText = 'AI Classifying';
        metricLines.push(`Jobs classified: ${formatCountPair(jobs_classified, classification_total)}`);
        if (current_job_title) {
            detailLines.push(`Current title: ${current_job_title}`);
        }
    } else if (phase === 4) {
        statusText = 'Saving to DB';
        metricLines.push(`Ingested: ${formatMaybeCountPair(jobs_saved, save_total)}`);
    } else if (phase === 5 || status === 'ai_running' || status === 'completed_with_ai_failures') {
        statusText = 'AI Enrichment';
        metricLines.push(`Items processed: ${formatCountPair(aiProcessedItems, aiTotalItems)}`);
        if (ai_failed_items > 0) {
            metricLines.push(`Failures: ${formatCount(ai_failed_items)}`);
        }
    }

    if (status === 'completed' && (phase === 5 || ai_run_id)) {
        statusText = 'Completed';
        statusClass = 'success';
        metricLines.length = 0;
        if (ai_failed_items > 0) {
            metricLines.push(`Succeeded: ${formatCount(ai_completed_items)}`);
            metricLines.push(`Failed: ${formatCount(ai_failed_items)}`);
        } else {
            metricLines.push(`Items enriched: ${formatCount(ai_completed_items || aiTotalItems || jobs_scraped)}`);
        }
    } else if (status === 'completed' && isDetailRunScope) {
        statusText = 'Completed';
        statusClass = 'success';
    } else if (status === 'completed' && !isBacklogPoolScope && !isDetailRunScope) {
        statusText = 'Completed';
        statusClass = 'success';
        metricLines.length = 0;
        metricLines.push(`Jobs scraped: ${formatCount(jobs_scraped)}`);
    } else if (status === 'completed_with_ai_failures') {
        statusText = 'Completed With AI Failures';
        statusClass = 'warning';
        metricLines.length = 0;
        metricLines.push(`Succeeded: ${formatCount(ai_completed_items)}`);
        metricLines.push(`Failed: ${formatCount(ai_failed_items)}`);
    } else if (status === 'ai_running') {
        statusText = 'AI Enrichment';
    } else if (status === 'failed') {
        statusText = 'Failed';
        statusClass = 'error';
        detailLines.push(error || 'Unknown error');
    } else if (status === 'cancelled') {
        statusText = 'Cancelled';
        statusClass = 'warning';
        detailLines.push(error || 'Cancelled');
    }

    if (listingBatchLabel) {
        detailLines.push(`Listing batch: ${listingBatchLabel}`);
    }

    if (typeof proxy_enabled === 'boolean') {
        detailLines.push(`Proxy: ${proxy_enabled ? (proxy_provider || 'enabled') : 'off'}`);
        if (proxy_enabled) {
            detailLines.push(`Proxy requests: ${formatCount(proxy_requests_total)}`);
            if (proxy_requests_success > 0) {
                detailLines.push(`Proxy success: ${formatCount(proxy_requests_success)}`);
            }
            if (proxy_requests_challenge > 0) {
                detailLines.push(`Proxy challenges: ${formatCount(proxy_requests_challenge)}`);
            }
            if (proxy_requests_network_fail > 0) {
                detailLines.push(`Proxy network fail: ${formatCount(proxy_requests_network_fail)}`);
            }
            if (proxy_requests_http_fail > 0) {
                detailLines.push(`Proxy HTTP fail: ${formatCount(proxy_requests_http_fail)}`);
            }
            if (proxy_quarantined_total > 0) {
                detailLines.push(`Proxy quarantined: ${formatCount(proxy_quarantined_total)}`);
            }
        }
    }

    return (
        <div className={`progress-item ${statusClass}`}>
            {renderHeader(statusText, statusClass)}
            <div className="progress-status-strip">
                <div className="progress-status-summary">
                    <span className="progress-status-title">{statusText}</span>
                    <span className="progress-status-subtitle">
                        Last updated: {formatTaskTimestamp(data?.updated_at || completed_at || started_at || queued_at)}
                    </span>
                </div>
                {statusSignals.length > 0 && (
                    <div className="progress-status-signal-row">
                        {statusSignals.map((signal) => (
                            <span key={`${taskId}-${signal}`} className="progress-status-chip">
                                {signal}
                            </span>
                        ))}
                    </div>
                )}
            </div>
            {renderMetricLines(metricLines)}

            <button
                type="button"
                className="progress-diagnostics-toggle"
                aria-expanded={isDiagnosticsOpen ? 'true' : 'false'}
                onClick={() => setIsDiagnosticsOpen((current) => !current)}
            >
                Diagnostics
            </button>

            {isDiagnosticsOpen && (
                <div className="progress-diagnostics-drawer">
                    <div className="progress-diagnostics-section">
                        <strong>Run timing</strong>
                        {renderTimingBlock()}
                        <div className="progress-stats">
                            <span>Elapsed: {elapsedLabel}</span>
                        </div>
                    </div>
                    <div className="progress-diagnostics-section">
                        <strong>Technical diagnostics</strong>
                        {detailLines.map((line) => (
                            <div key={`${taskId}-${line}`} className="progress-text">{line}</div>
                        ))}
                    </div>
                </div>
            )}

            {ai_run_id && (
                <div className="progress-actions">
                    <button
                        type="button"
                        className="progress-link-button"
                        onClick={() => onNavigateToAI?.(ai_run_id)}
                    >
                        View AI Run
                    </button>
                    <span className="progress-run-id">{ai_run_id}</span>
                </div>
            )}
        </div>
    );
}

export default ScrapeProgressPanel;
