import React, { useState, useEffect, useRef } from 'react';
import { API_BASE_URL } from '../../api/base';
import { formatCrawlModeLabel } from './crawlMode';

const API_URL = API_BASE_URL;
const API_BASE = `${API_URL}/api/v1`;
const EMPTY_PROGRESS = {};

function ScrapeProgressPanel({
    isVisible,
    initialProgress = EMPTY_PROGRESS,
    recoveryStartedAt,
    recoveryWindowMs,
    onClose,
    onNavigateToAI
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

    const progressEntries = Object.entries(progress);
    const hasProgress = progressEntries.length > 0;

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
                <h3>Scraping Progress</h3>
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
                    progressEntries.map(([categoryId, data]) => (
                        <ProgressItem key={categoryId} data={data} onNavigateToAI={onNavigateToAI} />
                    ))
                )}
            </div>
        </div>
    );
}

function ProgressItem({ data, onNavigateToAI }) {
    const {
        status,
        category_name,
        crawl_mode,
        phase,
        // Phase 1
        job_ids_collected = 0,
        current_page,
        total_pages,
        // Phase 2
        jobs_scraped = 0,
        total_jobs = 0,
        current_job_title,
        // Phase 3
        jobs_classified = 0,
        classification_total = 0,
        // Phase 4
        jobs_saved = 0,
        save_total = 0,
        // Phase 5
        ai_run_id,
        ai_completed_items = 0,
        ai_failed_items = 0,
        ai_total_items,
        // Timing
        elapsed_seconds = 0,
        phase_rate = 0,
        error
    } = data;

    let percentage = 0;
    let statusText = '';
    let detailText = '';
    const aiProcessedItems = ai_completed_items + ai_failed_items;
    const aiTotalItems = ai_total_items || save_total || jobs_saved || total_jobs || jobs_scraped || aiProcessedItems;

    if (status === 'queued') {
        percentage = 0;
        statusText = 'Queued';
        detailText = 'Awaiting crawl worker dispatch';
    } else if (phase === 1) {
        percentage = total_pages ? (current_page / total_pages) * 25 : 0;
        statusText = 'Collecting IDs';
        detailText = `Page ${current_page || 0}/${total_pages || '?'} (${job_ids_collected} found)`;
    } else if (phase === 2) {
        percentage = 25 + (total_jobs ? (jobs_scraped / total_jobs) * 25 : 0);
        statusText = 'Scraping Details';
        detailText = `${jobs_scraped}/${total_jobs} jobs`;
        if (current_job_title) {
            detailText += ` - ${current_job_title}`;
        }
    } else if (phase === 3) {
        percentage = 50 + (classification_total ? (jobs_classified / classification_total) * 25 : 0);
        statusText = 'AI Classifying';
        detailText = `${jobs_classified}/${classification_total} jobs`;
        if (current_job_title) {
            detailText += ` - ${current_job_title}`;
        }
    } else if (phase === 4) {
        percentage = 75 + (save_total ? (jobs_saved / save_total) * 25 : 0);
        statusText = 'Saving to DB';
        detailText = `${jobs_saved}/${save_total} jobs`;
    } else if (phase === 5 || status === 'ai_running' || status === 'completed_with_ai_failures') {
        percentage = 75 + (aiTotalItems ? (aiProcessedItems / aiTotalItems) * 25 : 0);
        statusText = 'AI Enrichment';
        detailText = `${aiProcessedItems}/${aiTotalItems || '?'} items processed`;
        if (ai_failed_items > 0) {
            detailText += ` · ${ai_failed_items} failed`;
        }
    }

    if (status === 'completed' && (phase === 5 || ai_run_id)) {
        percentage = 100;
        statusText = 'Completed';
        detailText = ai_failed_items > 0
            ? `${ai_completed_items} succeeded · ${ai_failed_items} failed`
            : `${ai_completed_items || aiTotalItems || jobs_scraped} items enriched`;
    } else if (status === 'completed') {
        percentage = 100;
        statusText = 'Completed';
        detailText = `Scraped ${jobs_scraped} jobs`;
    } else if (status === 'completed_with_ai_failures') {
        percentage = 100;
        statusText = 'Completed With AI Failures';
        detailText = `${ai_completed_items} succeeded · ${ai_failed_items} failed`;
    } else if (status === 'ai_running') {
        statusText = 'AI Enrichment';
    } else if (status === 'failed') {
        statusText = 'Failed';
        detailText = error || 'Unknown error';
    } else if (status === 'cancelled') {
        statusText = 'Cancelled';
        detailText = error || 'Cancelled';
    }

    const formatTime = (seconds) => {
        if (seconds < 60) return `${seconds}s`;
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${mins}m ${secs}s`;
    };

    const statusClass =
        status === 'completed'
            ? 'success'
            : status === 'failed'
              ? 'error'
              : status === 'cancelled'
                ? 'warning'
              : status === 'completed_with_ai_failures'
                ? 'warning'
                : 'running';
    const headingLabel = crawl_mode
        ? `${category_name} · ${formatCrawlModeLabel(crawl_mode)}`
        : category_name;

    return (
        <div className={`progress-item ${statusClass}`}>
            <div className="progress-item-header">
                <span className="category-name">{headingLabel}</span>
                <span className={`status-badge status-${statusClass}`}>
                    {statusText}
                </span>
            </div>

            <div className="progress-bar-container">
                <div
                    className="progress-bar-fill"
                    style={{ width: `${Math.min(percentage, 100)}%` }}
                />
            </div>

            <div className="progress-details">
                <div className="progress-text">{detailText}</div>
                {status !== 'completed' && status !== 'failed' && status !== 'completed_with_ai_failures' && (
                    <div className="progress-stats">
                        <span>Time: {formatTime(elapsed_seconds)}</span>
                        <span>Rate: {phase_rate.toFixed(1)}/s</span>
                    </div>
                )}
            </div>

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
