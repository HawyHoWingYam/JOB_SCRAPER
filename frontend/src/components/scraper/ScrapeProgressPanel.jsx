import React, { useState, useEffect, useRef } from 'react';
import { API_BASE_URL } from '../../api/base';
import { formatCrawlModeLabel } from './crawlMode';

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
    onCloseManualActionWindows,
    onCaptureManualActionAnalysis,
    onAutoResolveManualAction
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
        return getProgressTimestamp(rightEntry[1]) - getProgressTimestamp(leftEntry[1]);
    });
    const visibleProgressEntries = progressEntries.slice(0, MAX_VISIBLE_TASKS);
    const hasProgress = visibleProgressEntries.length > 0;

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
                            Showing latest {visibleProgressEntries.length} of {progressEntries.length} tasks
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
                    visibleProgressEntries.map(([taskKey, data]) => (
                        <ProgressItem
                            key={taskKey}
                            taskKey={taskKey}
                            data={data}
                            onNavigateToAI={onNavigateToAI}
                            onResumeCrawlJob={onResumeCrawlJob}
                            onCancelCrawlJob={onCancelCrawlJob}
                            onOpenManualActionBrowser={onOpenManualActionBrowser}
                            onCloseManualActionWindows={onCloseManualActionWindows}
                            onCaptureManualActionAnalysis={onCaptureManualActionAnalysis}
                            onAutoResolveManualAction={onAutoResolveManualAction}
                        />
                    ))
                )}
            </div>
        </div>
    );
}

function formatSourceLabel(sourceSite) {
    if (sourceSite === 'ctgoodjobs') {
        return 'CTgoodjobs';
    }

    if (sourceSite === 'jobsdb') {
        return 'JobsDB';
    }

    return sourceSite;
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

function getProgressTimestamp(data) {
    const candidateValues = [
        data?.updated_at,
        data?.completed_at,
        data?.started_at,
        data?.queued_at,
    ];

    for (const value of candidateValues) {
        const timestamp = Date.parse(value);
        if (!Number.isNaN(timestamp)) {
            return timestamp;
        }
    }

    return 0;
}

function formatPhaseLabel(phase, status) {
    if (status === 'manual_action_required') {
        return 'Manual Review';
    }

    if (phase === 1) {
        return 'Listing IDs';
    }

    if (phase === 2) {
        return 'Job Details';
    }

    if (phase === 3) {
        return 'AI Classification';
    }

    if (phase === 4) {
        return 'Database Save';
    }

    if (phase === 5 || status === 'ai_running' || status === 'completed_with_ai_failures') {
        return 'AI Enrichment';
    }

    return 'Queued';
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

function ProgressItem({
    taskKey,
    data,
    onNavigateToAI,
    onResumeCrawlJob,
    onCancelCrawlJob,
    onOpenManualActionBrowser,
    onCloseManualActionWindows,
    onCaptureManualActionAnalysis,
    onAutoResolveManualAction
}) {
    const [manualActionAnalysis, setManualActionAnalysis] = useState(null);
    const [localManualActionResolution, setLocalManualActionResolution] = useState(null);
    const [manualActionAnalysisError, setManualActionAnalysisError] = useState(null);
    const [isManualActionAnalysisLoading, setIsManualActionAnalysisLoading] = useState(false);
    const [isApplyingSuggestedFix, setIsApplyingSuggestedFix] = useState(false);
    const {
        crawl_job_id,
        status,
        operator_state,
        source_site,
        category_name,
        crawl_mode,
        phase,
        manual_action,
        manual_action_resolution,
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
        detail_pending = 0,
        detail_running = 0,
        detail_manual_action_required = 0,
        // Phase 5
        ai_run_id,
        ai_completed_items = 0,
        ai_failed_items = 0,
        ai_total_items,
        // Timing
        elapsed_seconds = 0,
        error
    } = data;
    const taskId = crawl_job_id || taskKey;
    const elapsedLabel = formatDuration(elapsed_seconds);
    const effectiveManualActionResolution = localManualActionResolution || manual_action_resolution || null;
    const effectiveDetailTotal = detail_job_total || total_jobs;
    const effectiveDetailIndex = detail_job_index || jobs_scraped;
    const aiProcessedItems = ai_completed_items + ai_failed_items;
    const aiTotalItems = ai_total_items || save_total || jobs_saved || total_jobs || jobs_scraped || aiProcessedItems;
    const hasDownstreamBacklog = operator_state === 'completed_with_downstream_backlog'
        || operator_state === 'stale_downstream_backlog';
    const contextChips = buildContextChips({
        sourceSite: manual_action?.source_site || source_site,
        categoryName: category_name,
        crawlMode: crawl_mode,
    });

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

    if (status === 'manual_action_required' && manual_action) {
        const instructions = Array.isArray(manual_action.instructions)
            ? manual_action.instructions.filter(Boolean)
            : [];
        const metricLines = [];

        if (phase === 1) {
            metricLines.push(`Pages: ${formatCountPair(current_page || 0, total_pages)}`);
            metricLines.push(`IDs found: ${formatCount(job_ids_collected)}`);
        } else if (phase === 2) {
            metricLines.push(`Details completed: ${formatCountPair(jobs_scraped, effectiveDetailTotal)}`);
            if (detail_job_index || effectiveDetailTotal) {
                metricLines.push(`Current target: ${formatCountPair(effectiveDetailIndex, effectiveDetailTotal)}`);
            }
            if (save_total > 0) {
                metricLines.push(`Saved: ${formatCountPair(jobs_saved, save_total)}`);
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

        const handleResume = async () => {
            if (!crawl_job_id) {
                return;
            }

            try {
                await onResumeCrawlJob?.(crawl_job_id);
            } catch (resumeError) {
                console.error('Failed to resume crawl job:', resumeError);
            }
        };

        const handleOpenVerificationBrowser = async () => {
            if (!crawl_job_id && !manual_action.blocked_url) {
                return;
            }

            try {
                if (onOpenManualActionBrowser && crawl_job_id) {
                    await onOpenManualActionBrowser(crawl_job_id);
                    return;
                }
            } catch (browserError) {
                console.error('Failed to open manual action browser:', browserError);
            }

            if (manual_action.blocked_url) {
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

        const handleCaptureAndAnalyze = async () => {
            if (!crawl_job_id || !onCaptureManualActionAnalysis) {
                return;
            }

            setIsManualActionAnalysisLoading(true);
            setManualActionAnalysisError(null);

            try {
                const analysis = await onCaptureManualActionAnalysis(crawl_job_id, manual_action);
                setManualActionAnalysis(analysis || null);
                setLocalManualActionResolution(null);
            } catch (analysisError) {
                console.error('Failed to capture and analyze manual action:', analysisError);
                setManualActionAnalysisError(
                    analysisError instanceof Error
                        ? analysisError.message
                        : 'Failed to capture and analyze verification'
                );
            } finally {
                setIsManualActionAnalysisLoading(false);
            }
        };

        const applySuggestedFix = async (analysis) => {
            if (!crawl_job_id || !analysis?.auto_apply_supported) {
                return;
            }

            if (analysis.suggested_action === 'close_profile_windows') {
                await onCloseManualActionWindows?.(crawl_job_id);
            }

            if (analysis.auto_resume_after_action) {
                await onResumeCrawlJob?.(crawl_job_id);
            }
        };

        const handleApplySuggestedFix = async () => {
            if (!manualActionAnalysis?.auto_apply_supported) {
                return;
            }

            setIsApplyingSuggestedFix(true);
            setManualActionAnalysisError(null);

            try {
                await applySuggestedFix(manualActionAnalysis);
            } catch (applyError) {
                console.error('Failed to apply suggested manual action fix:', applyError);
                setManualActionAnalysisError(
                    applyError instanceof Error
                        ? applyError.message
                        : 'Failed to apply suggested fix'
                );
            } finally {
                setIsApplyingSuggestedFix(false);
            }
        };

        const handleAutoResolve = async () => {
            if (!crawl_job_id) {
                return;
            }

            setIsManualActionAnalysisLoading(true);
            setIsApplyingSuggestedFix(true);
            setManualActionAnalysisError(null);

            try {
                if (onAutoResolveManualAction) {
                    const resolution = await onAutoResolveManualAction(crawl_job_id);
                    if (resolution?.analysis) {
                        setManualActionAnalysis(resolution.analysis);
                    }
                    setLocalManualActionResolution(resolution || null);
                    return;
                }

                if (!onCaptureManualActionAnalysis) {
                    return;
                }

                const analysis = await onCaptureManualActionAnalysis(crawl_job_id, manual_action);
                setManualActionAnalysis(analysis || null);
                setLocalManualActionResolution(null);
                if (analysis?.auto_apply_supported) {
                    await applySuggestedFix(analysis);
                }
            } catch (resolveError) {
                console.error('Failed to auto resolve manual action:', resolveError);
                setManualActionAnalysisError(
                    resolveError instanceof Error
                        ? resolveError.message
                        : 'Failed to auto resolve manual action'
                );
            } finally {
                setIsManualActionAnalysisLoading(false);
                setIsApplyingSuggestedFix(false);
            }
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
                {renderMetricLines(metricLines)}

                <div className="progress-details">
                    <div className="progress-text">Stage: {manual_action.stage || '-'}</div>
                    <div className="progress-text">{manual_action.blocked_url || '-'}</div>
                    <div className="progress-text">
                        Browser Profile Path: {manual_action.browser_profile_path || '-'}
                    </div>
                    <div className="progress-text">
                        Browser Channel: {manual_action.browser_channel || '-'}
                    </div>
                    {current_job_title && (
                        <div className="progress-text">Current title: {current_job_title}</div>
                    )}
                    <div className="progress-stats">
                        <span>Elapsed: {elapsedLabel}</span>
                    </div>
                    {instructions.length > 0 && (
                        <ul className="progress-manual-action-list">
                            {instructions.map((instruction, index) => (
                                <li key={`${index}-${instruction}`}>{instruction}</li>
                            ))}
                        </ul>
                    )}
                    {manualActionAnalysis && (
                        <div className="progress-manual-analysis">
                            <div className="progress-text">
                                Challenge Type: {manualActionAnalysis.challenge_type || 'unknown'}
                            </div>
                            {manualActionAnalysis.summary && (
                                <div className="progress-text">{manualActionAnalysis.summary}</div>
                            )}
                            {Array.isArray(manualActionAnalysis.recommended_actions)
                                && manualActionAnalysis.recommended_actions.length > 0 && (
                                <ul className="progress-manual-action-list">
                                    {manualActionAnalysis.recommended_actions.map((instruction, index) => (
                                        <li key={`${taskId}-analysis-${index}`}>{instruction}</li>
                                    ))}
                                </ul>
                            )}
                        </div>
                    )}
                    {effectiveManualActionResolution && (
                        <div className="progress-manual-analysis">
                            {effectiveManualActionResolution.resolution_status && (
                                <div className="progress-text">
                                    Resolution Status: {effectiveManualActionResolution.resolution_status}
                                </div>
                            )}
                            {Array.isArray(effectiveManualActionResolution.applied_actions)
                                && effectiveManualActionResolution.applied_actions.length > 0 && (
                                <div className="progress-text">
                                    Applied Actions: {effectiveManualActionResolution.applied_actions.join(', ')}
                                </div>
                            )}
                        </div>
                    )}
                    {manualActionAnalysisError && (
                        <div className="progress-error">{manualActionAnalysisError}</div>
                    )}
                </div>

                <div className="progress-actions">
                    {manual_action.blocked_url && (
                        <button
                            type="button"
                            className="progress-link-button"
                            onClick={handleOpenVerificationBrowser}
                        >
                            Open Verification Browser
                        </button>
                    )}
                    {manual_action.browser_profile_path && (
                        <button
                            type="button"
                            className="progress-link-button"
                            onClick={handleCloseProfileWindows}
                        >
                            Close Profile Windows
                        </button>
                    )}
                    {onCaptureManualActionAnalysis && crawl_job_id && (
                        <button
                            type="button"
                            className="progress-link-button"
                            onClick={handleCaptureAndAnalyze}
                            disabled={isManualActionAnalysisLoading}
                        >
                            {isManualActionAnalysisLoading ? 'Analyzing...' : 'Capture and Analyze'}
                        </button>
                    )}
                    {(onCaptureManualActionAnalysis || onAutoResolveManualAction) && crawl_job_id && (
                        <button
                            type="button"
                            className="progress-link-button"
                            onClick={handleAutoResolve}
                            disabled={isManualActionAnalysisLoading || isApplyingSuggestedFix}
                        >
                            {isManualActionAnalysisLoading || isApplyingSuggestedFix ? 'Auto Resolving...' : 'Auto Resolve'}
                        </button>
                    )}
                    {manualActionAnalysis?.auto_apply_supported && (
                        <button
                            type="button"
                            className="progress-link-button"
                            onClick={handleApplySuggestedFix}
                            disabled={isApplyingSuggestedFix}
                        >
                            {isApplyingSuggestedFix ? 'Applying...' : 'Apply Suggested Fix'}
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
                    <button
                        type="button"
                        className="progress-link-button"
                        onClick={handleResume}
                    >
                        Resume
                    </button>
                    <button
                        type="button"
                        className="progress-link-button"
                        onClick={handleCancel}
                    >
                        Cancel
                    </button>
                </div>
            </div>
        );
    }

    let statusText = '';
    let statusClass = 'running';
    const metricLines = [];
    const detailLines = [];

    if (status === 'queued') {
        statusText = 'Queued';
        detailLines.push('Awaiting crawl worker dispatch');
    } else if (phase === 1) {
        statusText = 'Collecting IDs';
        metricLines.push(`Pages: ${formatCountPair(current_page || 0, total_pages)}`);
        metricLines.push(`IDs found: ${formatCount(job_ids_collected)}`);
        if (jobs_skipped_existing > 0) {
            metricLines.push(`Existing skipped: ${formatCount(jobs_skipped_existing)}`);
        }
    } else if (phase === 2) {
        statusText = 'Scraping Details';
        metricLines.push(`Details completed: ${formatCountPair(jobs_scraped, effectiveDetailTotal)}`);
        if (detail_job_index || effectiveDetailTotal) {
            metricLines.push(`Current target: ${formatCountPair(effectiveDetailIndex, effectiveDetailTotal)}`);
        }
        if (save_total > 0) {
            metricLines.push(`Saved: ${formatCountPair(jobs_saved, save_total)}`);
        }
        if (jobs_skipped_existing > 0) {
            metricLines.push(`Existing skipped: ${formatCount(jobs_skipped_existing)}`);
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
        metricLines.push(`Saved: ${formatCountPair(jobs_saved, save_total)}`);
    } else if (phase === 5 || status === 'ai_running' || status === 'completed_with_ai_failures') {
        statusText = 'AI Enrichment';
        metricLines.push(`Items processed: ${formatCountPair(aiProcessedItems, aiTotalItems)}`);
        if (ai_failed_items > 0) {
            metricLines.push(`Failures: ${formatCount(ai_failed_items)}`);
        }
    }

    if (hasDownstreamBacklog) {
        statusText = 'Downstream Backlog';
        statusClass = 'warning';
        const ingestTotal = save_total || jobs_scraped || listings_staged || total_jobs;
        metricLines.length = 0;
        metricLines.push(`Ingested: ${formatCountPair(jobs_saved, ingestTotal)}`);
        if (detail_pending > 0) {
            metricLines.push(`Pending details: ${formatCount(detail_pending)}`);
        }
        if (detail_running > 0) {
            metricLines.push(`Running details: ${formatCount(detail_running)}`);
        }
        if (detail_manual_action_required > 0) {
            metricLines.push(`Manual review: ${formatCount(detail_manual_action_required)}`);
        }
    } else if (status === 'completed' && (phase === 5 || ai_run_id)) {
        statusText = 'Completed';
        statusClass = 'success';
        metricLines.length = 0;
        if (ai_failed_items > 0) {
            metricLines.push(`Succeeded: ${formatCount(ai_completed_items)}`);
            metricLines.push(`Failed: ${formatCount(ai_failed_items)}`);
        } else {
            metricLines.push(`Items enriched: ${formatCount(ai_completed_items || aiTotalItems || jobs_scraped)}`);
        }
    } else if (status === 'completed') {
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

    return (
        <div className={`progress-item ${statusClass}`}>
            {renderHeader(statusText, statusClass)}
            {renderMetricLines(metricLines)}

            <div className="progress-details">
                {detailLines.map((line) => (
                    <div key={`${taskId}-${line}`} className="progress-text">{line}</div>
                ))}
                <div className="progress-stats">
                    <span>Elapsed: {elapsedLabel}</span>
                </div>
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
