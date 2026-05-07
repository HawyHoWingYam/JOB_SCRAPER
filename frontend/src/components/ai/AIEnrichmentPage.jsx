import { useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  Clock3,
  LoaderCircle,
  Orbit,
  RefreshCcw,
  Sparkles,
} from 'lucide-react';
import { API_BASE_URL } from '../../api/base';
import '../Dashboard.css';
import './AIEnrichmentPage.css';

const API_URL = API_BASE_URL;
const ACTIVE_RUN_STATUSES = new Set(['pending', 'running']);
const TERMINAL_RUN_STATUSES = new Set(['completed', 'completed_with_failures', 'failed']);
const DEGRADED_PLACEHOLDER = 'Unavailable';
const REFRESH_REQUEST_TIMEOUT_MS = 8000;

function normalizeRunStatus(value) {
  return String(value || '').toLowerCase();
}

function isActiveRun(run) {
  return ACTIVE_RUN_STATUSES.has(normalizeRunStatus(run?.status));
}

function isTerminalRun(run) {
  return TERMINAL_RUN_STATUSES.has(normalizeRunStatus(run?.status));
}

function parseDateMs(value) {
  if (!value) {
    return null;
  }

  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function formatDurationShort(totalSeconds) {
  const safeSeconds = Math.max(0, Math.round(Number(totalSeconds) || 0));
  const minutes = Math.floor(safeSeconds / 60);
  const seconds = safeSeconds % 60;

  if (minutes <= 0) {
    return `${seconds}s`;
  }

  return `${minutes}m ${seconds}s`;
}

function formatTimestampIso(value) {
  const parsed = parseDateMs(value);
  if (parsed === null) {
    return null;
  }

  return new Date(parsed).toISOString();
}

function sortRunsNewestFirst(runList) {
  const annotated = (runList || []).map((run, index) => ({
    run,
    index,
    createdMs: parseDateMs(run?.created_at),
  }));

  annotated.sort((a, b) => {
    if (a.createdMs !== null && b.createdMs !== null && a.createdMs !== b.createdMs) {
      return b.createdMs - a.createdMs;
    }

    if (a.createdMs !== null && b.createdMs === null) {
      return -1;
    }

    if (a.createdMs === null && b.createdMs !== null) {
      return 1;
    }

    const aId = String(a.run?.id || '');
    const bId = String(b.run?.id || '');
    if (aId !== bId) {
      return bId.localeCompare(aId);
    }

    return a.index - b.index;
  });

  return annotated.map(({ run }) => run);
}

function resolveMonitorSlots(sortedRuns) {
  const newestActiveIndex = (sortedRuns || []).findIndex((run) => isActiveRun(run));
  if (newestActiveIndex !== -1) {
    return {
      hasActive: true,
      slots: [sortedRuns[newestActiveIndex], sortedRuns[newestActiveIndex + 1] || null],
    };
  }

  const terminalRuns = (sortedRuns || []).filter((run) => isTerminalRun(run));
  return {
    hasActive: false,
    slots: [terminalRuns[0] || null, terminalRuns[1] || null],
  };
}

function getRunStatusTone(status) {
  const normalized = normalizeRunStatus(status);
  if (normalized === 'pending' || normalized === 'running') {
    return 'active';
  }
  if (normalized === 'completed') {
    return 'success';
  }
  if (normalized === 'completed_with_failures') {
    return 'warning';
  }
  if (normalized === 'failed') {
    return 'danger';
  }
  return 'muted';
}

function isRetryableTerminalRun(run) {
  if (!run || !isTerminalRun(run)) {
    return false;
  }

  const normalizedStatus = normalizeRunStatus(run?.status);
  if (normalizedStatus === 'completed_with_failures' || normalizedStatus === 'failed') {
    return true;
  }

  return Number(run?.failed_items || 0) > 0;
}

function withRequestTimeout(promise, label) {
  let timeoutId;

  const timeoutPromise = new Promise((_, reject) => {
    timeoutId = setTimeout(() => {
      reject(new Error(`${label} request timed out after ${REFRESH_REQUEST_TIMEOUT_MS}ms`));
    }, REFRESH_REQUEST_TIMEOUT_MS);
  });

  return Promise.race([promise, timeoutPromise]).finally(() => {
    clearTimeout(timeoutId);
  });
}

function formatDisplayValue(value) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value.toLocaleString();
  }

  return String(value);
}

function SummaryCard({ label, value, icon, tone = 'default' }) {
  const IconComponent = icon;

  return (
    <article className={`stat-card glass-panel ai-tone-${tone}`}>
      <div className={`stat-icon-wrapper ${tone}-glow`}>
        <IconComponent size={24} className="stat-icon" />
      </div>
      <div className="stat-info">
        <div className="stat-value">{formatDisplayValue(value)}</div>
        <div className="stat-label">{label}</div>
      </div>
    </article>
  );
}

export default function AIEnrichmentPage() {
  const [overview, setOverview] = useState(null);
  const [hasLoadedOverview, setHasLoadedOverview] = useState(false);
  const [runs, setRuns] = useState([]);
  const [hasLoadedRuns, setHasLoadedRuns] = useState(false);
  const [pendingLimit, setPendingLimit] = useState('50');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [refreshError, setRefreshError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [actionMessage, setActionMessage] = useState(null);
  const hasConsoleData = hasLoadedOverview || hasLoadedRuns;
  const hasConsoleDataRef = useRef(false);
  const refreshInFlightRef = useRef(null);
  const refreshQueuedRef = useRef(false);
  const mountedRef = useRef(true);
  const sortedRuns = sortRunsNewestFirst(runs);
  const overviewPendingJobs = Number(overview?.pending_jobs || 0);
  const overviewFailedJobs = Number(overview?.failed_jobs ?? overview?.failed_items ?? 0);
  const visibleActiveRunsCount = sortedRuns.filter((run) => isActiveRun(run)).length;
  const overviewActiveRunsCount = Number(overview?.active_runs || 0);
  const isBootstrapPolling = hasConsoleData && (!hasLoadedOverview || !hasLoadedRuns);
  const shouldPollRuns = isBootstrapPolling || overviewActiveRunsCount > 0 || (!hasLoadedOverview && visibleActiveRunsCount > 0);
  const pendingJobsDisplay = hasLoadedOverview ? overviewPendingJobs : DEGRADED_PLACEHOLDER;
  const failedJobsDisplay = hasLoadedOverview ? overviewFailedJobs : DEGRADED_PLACEHOLDER;
  const activeRunsDisplay = hasLoadedOverview ? overviewActiveRunsCount : DEGRADED_PLACEHOLDER;
  const lastCompletedDisplay = hasLoadedOverview
    ? overview?.last_completed_run?.id || 'No completed run yet'
    : DEGRADED_PLACEHOLDER;
  const backlogWindowDisplay = hasLoadedOverview ? `${overviewPendingJobs.toLocaleString()} jobs` : DEGRADED_PLACEHOLDER;
  const failureCountDisplay = hasLoadedOverview ? `${overviewFailedJobs.toLocaleString()} jobs` : DEGRADED_PLACEHOLDER;
  const activeRunsRibbonDisplay = hasLoadedOverview ? `${overviewActiveRunsCount.toLocaleString()} runs` : DEGRADED_PLACEHOLDER;
  const { hasActive: monitorHasActive, slots: monitorSlots } = resolveMonitorSlots(sortedRuns);
  const retryTargetRun = monitorSlots.find((run) => isRetryableTerminalRun(run)) || null;

  useEffect(() => {
    hasConsoleDataRef.current = hasConsoleData;
  }, [hasConsoleData]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  async function fetchAIConsole({ queueAfterInFlight = false } = {}) {
    if (refreshInFlightRef.current) {
      if (queueAfterInFlight) {
        refreshQueuedRef.current = true;
      }
      return refreshInFlightRef.current;
    }

    const refreshPromise = (async () => {
      try {
        if (!hasConsoleDataRef.current) {
          setLoadError(null);
        }
        setRefreshError(null);

        const overviewTask = withRequestTimeout(
          fetch(`${API_URL}/api/v1/ai/overview`).then(async (response) => {
            if (!response.ok) {
              throw new Error(`Overview request failed with ${response.status}`);
            }
            return response.json();
          }),
          'Overview',
        );

        const runsTask = withRequestTimeout(
          fetch(`${API_URL}/api/v1/ai/runs?monitor=true`).then(async (response) => {
            if (!response.ok) {
              throw new Error(`Runs request failed with ${response.status}`);
            }
            return response.json();
          }),
          'Runs',
        );

        overviewTask.then(
          (payload) => {
            if (!mountedRef.current) {
              return;
            }

            setOverview(payload);
            setHasLoadedOverview(true);
            setLoadError(null);
            setLoading(false);
          },
          () => {},
        );

        runsTask.then(
          (payload) => {
            if (!mountedRef.current) {
              return;
            }

            setRuns(payload.runs || []);
            setHasLoadedRuns(true);
            setLoadError(null);
            setLoading(false);
          },
          () => {},
        );

        const [overviewResult, runsResult] = await Promise.allSettled([overviewTask, runsTask]);

        if (!mountedRef.current) {
          return;
        }

        const errors = [];
        let receivedAnyPayload = false;

        if (overviewResult.status === 'fulfilled') {
          receivedAnyPayload = true;
        } else {
          errors.push(overviewResult.reason?.message || String(overviewResult.reason));
        }

        if (runsResult.status === 'fulfilled') {
          receivedAnyPayload = true;
        } else {
          errors.push(runsResult.reason?.message || String(runsResult.reason));
        }

        if (errors.length === 0) {
          setLoadError(null);
          setRefreshError(null);
          return;
        }

        const combinedError = errors.length === 1 ? errors[0] : errors.join(' | ');

        if (!hasConsoleDataRef.current && !receivedAnyPayload) {
          setLoadError(combinedError);
          return;
        }

        setLoadError(null);
        setRefreshError(`Refresh failed: ${combinedError}`);
      } catch (err) {
        if (!mountedRef.current) {
          return;
        }

        if (!hasConsoleDataRef.current) {
          setLoadError(err.message);
        } else {
          setRefreshError(`Refresh failed: ${err.message}`);
        }
      } finally {
        if (mountedRef.current) {
          setLoading(false);
        }
      }
    })();

    refreshInFlightRef.current = refreshPromise.finally(() => {
      refreshInFlightRef.current = null;
      if (refreshQueuedRef.current && mountedRef.current) {
        refreshQueuedRef.current = false;
        fetchAIConsole();
      }
    });

    return refreshInFlightRef.current;
  }

  useEffect(() => {
    fetchAIConsole();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (loading || !hasConsoleData || !shouldPollRuns) {
      return undefined;
    }

    let cancelled = false;

    async function pollLoop() {
      while (!cancelled) {
        await new Promise((resolve) => {
          setTimeout(resolve, 2000);
        });
        if (cancelled) {
          return;
        }
        await fetchAIConsole();
      }
    }

    pollLoop();

    return () => {
      cancelled = true;
    };
  }, [hasConsoleData, loading, shouldPollRuns]);

  async function runPendingEnrichment() {
    try {
      setSubmitting(true);
      setActionError(null);
      setActionMessage(null);
      const normalizedLimit = Math.max(1, Number(pendingLimit) || 1);
      setPendingLimit(String(normalizedLimit));

      const response = await fetch(`${API_URL}/api/v1/ai/runs`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          mode: 'pending',
          limit: normalizedLimit,
        }),
      });

      if (!response.ok) {
        throw new Error(`Run request failed with ${response.status}`);
      }

      setActionMessage('Pending enrichment run submitted.');
      fetchAIConsole({ queueAfterInFlight: true });
    } catch (err) {
      setActionError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function retryFailedItems() {
    if (!retryTargetRun) {
      return;
    }

    try {
      setSubmitting(true);
      setActionError(null);
      setActionMessage(null);

      const response = await fetch(`${API_URL}/api/v1/ai/runs/${retryTargetRun.id}/retry-failed`, {
        method: 'POST',
      });

      if (!response.ok) {
        throw new Error(`Retry request failed with ${response.status}`);
      }

      setActionMessage(`Retry run created from ${retryTargetRun.id}.`);
      fetchAIConsole({ queueAfterInFlight: true });
    } catch (err) {
      setActionError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="dashboard-container">
      <header className="dashboard-header">
        <div>
          <h2>AI Enrichment</h2>
          <p className="subtitle">
            Auto-chain runs after scrape persistence, and keep this console for queue control, backlog sweeps, and quick retry launches.
          </p>
        </div>
      </header>

      {loading && (
        <div className="loading-state">
          <LoaderCircle className="spinner" size={32} />
          <p>Loading enrichment queue...</p>
        </div>
      )}

      {!loading && !hasConsoleData && loadError && (
        <div className="error-message glass-panel">
          <AlertTriangle size={18} />
          <span>Failed to load AI operations data: {loadError}</span>
        </div>
      )}

      {!loading && hasConsoleData && (
        <>
          {refreshError && <div className="ai-status-banner ai-status-error">{refreshError}</div>}
          <div className="stats-grid">
            <SummaryCard
              label="Pending Jobs"
              value={pendingJobsDisplay}
              icon={BrainCircuit}
              tone="purple"
            />
            <SummaryCard
              label="Active Runs"
              value={activeRunsDisplay}
              icon={Orbit}
              tone="blue"
            />
            <SummaryCard
              label="Failed Jobs"
              value={failedJobsDisplay}
              icon={AlertTriangle}
              tone="green"
            />
          </div>

          <div className="ai-console-grid">
            <section className="chart-wrapper glass-panel ai-console-panel">
              <div className="ai-console-header">
                <div>
                  <h3>Queue Overview</h3>
                  <p className="ai-console-copy">
                    Scrapes auto-chain into AI by default. Use manual actions here for backlog sweeps and recovery.
                  </p>
                </div>
                <div className="ai-last-run">
                  <span className="ai-last-run-label">Last Completed</span>
                  <strong>{lastCompletedDisplay}</strong>
                </div>
              </div>

              <div className="ai-actions-row">
                <label className="ai-input-group" htmlFor="pending-limit">
                  <span>Pending Limit</span>
                  <input
                    id="pending-limit"
                    type="number"
                    min="1"
                    step="1"
                    value={pendingLimit}
                    onChange={(event) => setPendingLimit(event.target.value)}
                  />
                </label>

                <button type="button" className="ai-primary-button" disabled={submitting} onClick={runPendingEnrichment}>
                  <Sparkles size={16} />
                  <span>Run Pending</span>
                </button>

                <button
                  type="button"
                  className="ai-secondary-button"
                  disabled={submitting || !retryTargetRun}
                  onClick={retryFailedItems}
                >
                  <RefreshCcw size={16} />
                  <span>Retry Failed</span>
                </button>
              </div>

              {retryTargetRun && (
                <div className="ai-retry-target">
                  <span className="ai-ribbon-label">Retry Target</span>
                  <strong>{retryTargetRun.id}</strong>
                  <p>
                    Latest failed run queued for operator retry. The detailed workbench is removed to keep this console focused on orchestration.
                  </p>
                </div>
              )}

              <div className="ai-queue-ribbon">
                <div>
                  <span className="ai-ribbon-label">Backlog Window</span>
                  <strong>{backlogWindowDisplay}</strong>
                </div>
                <div>
                  <span className="ai-ribbon-label">Failure Count</span>
                  <strong>{failureCountDisplay}</strong>
                </div>
                <div>
                  <span className="ai-ribbon-label">Active Runs</span>
                  <strong>{activeRunsRibbonDisplay}</strong>
                </div>
              </div>

              {actionMessage && <div className="ai-status-banner ai-status-success">{actionMessage}</div>}
              {actionError && <div className="ai-status-banner ai-status-error">{actionError}</div>}
            </section>

            <section className="chart-wrapper glass-panel ai-console-panel">
              <div className="ai-console-header">
                <div>
                  <h3>Run Monitor</h3>
                  <p className="ai-console-copy">
                    Persisted runs show the true orchestration state instead of transient in-memory tasks.
                  </p>
                </div>
              </div>

              <div className="ai-run-list ai-run-monitor">
                {monitorSlots.map((run, index) => {
                  const slotTitle = monitorHasActive
                    ? index === 0
                      ? 'Current Run'
                      : 'Previous Run'
                    : index === 0
                      ? 'Latest Run'
                      : 'Previous Run';

                  if (!run) {
                    return (
                      <article
                        key={slotTitle}
                        data-testid="run-monitor-card"
                        className="ai-run-card ai-monitor-card ai-run-card-empty"
                        aria-label={`${slotTitle} empty state`}
                      >
                        <div className="ai-run-topline">
                          <div className="ai-run-slot-title">{slotTitle}</div>
                          <div className="ai-run-status-badge ai-run-status-muted">empty</div>
                        </div>
                        <p className="ai-empty-state">No persisted run available yet.</p>
                      </article>
                    );
                  }

                  const processedItems = Number(run.completed_items || 0) + Number(run.failed_items || 0);
                  const totalItems = Number(run.total_items || 0);
                  const remainingItems = Number.isFinite(Number(run.pending_items))
                    ? Number(run.pending_items)
                    : Math.max(0, totalItems - processedItems);
                  const normalizedStatus = normalizeRunStatus(run.status);
                  const statusTone = getRunStatusTone(normalizedStatus);
                  const active = isActiveRun(run);
                  const inProgressItems = Number.isFinite(Number(run.in_progress_items))
                    ? Number(run.in_progress_items)
                    : (active ? Math.max(0, totalItems - remainingItems - processedItems) : 0);
                  const latestStartedJobTitle = run.latest_started_job_title || run.current_job_title || 'Waiting for persisted title';
                  const progressValue = totalItems ? Math.round((processedItems / totalItems) * 100) : 0;

                  const startedMs = parseDateMs(run.started_at);
                  const completedMs = parseDateMs(run.completed_at);
                  const completedIso = formatTimestampIso(run.completed_at);
                  const durationSeconds =
                    startedMs !== null && completedMs !== null ? Math.max(0, (completedMs - startedMs) / 1000) : null;

                  return (
                    <article
                      key={run.id}
                      data-testid="run-monitor-card"
                      className={`ai-run-card ai-monitor-card ai-run-card-${statusTone}`}
                      aria-label={`${slotTitle} ${run.id}`}
                    >
                      <div className="ai-run-topline">
                        <div>
                          <div className="ai-run-slot-title">{slotTitle}</div>
                          <div className="ai-run-id">{run.id}</div>
                          <div className="ai-run-source">{run.source_type}</div>
                        </div>
                        <div className={`ai-run-status-badge ai-run-status-${statusTone}`}>{normalizedStatus}</div>
                      </div>

                      <div
                        className="ai-run-progress-track"
                        role="progressbar"
                        aria-label={`${slotTitle} progress`}
                        aria-valuenow={progressValue}
                        aria-valuemin={0}
                        aria-valuemax={100}
                      >
                        <div
                          className={`ai-run-progress-fill ${active ? 'ai-run-progress-live' : ''}`}
                          style={{ width: `${progressValue}%` }}
                        />
                      </div>

                      <div className="ai-run-metrics">
                        <span><Clock3 size={14} /> Processed {processedItems}</span>
                        <span><CheckCircle2 size={14} /> Succeeded {run.completed_items}</span>
                        <span><AlertTriangle size={14} /> Failed {run.failed_items}</span>
                      </div>

                      {active && (
                        <div className="ai-run-focus">
                          <span className="ai-run-focus-label">Jobs in progress</span>
                          <strong className="ai-run-focus-value">
                            {inProgressItems > 0 ? `${inProgressItems} jobs in progress` : 'Waiting for workers to claim jobs'}
                          </strong>
                          <span className="ai-run-focus-detail">Latest title: {latestStartedJobTitle}</span>
                        </div>
                      )}

                      {active ? (
                        <div className="ai-run-summary ai-run-summary-live">
                          <div className="ai-run-summary-title">Live summary</div>
                          <div className="ai-run-summary-body">
                            <span>
                              Elapsed{' '}
                              {startedMs === null ? '-' : formatDurationShort((Date.now() - startedMs) / 1000)}
                            </span>
                            <span>Remaining {remainingItems}</span>
                          </div>
                        </div>
                      ) : normalizedStatus === 'completed' ? (
                        <div className="ai-run-summary ai-run-summary-terminal">
                          <div className="ai-run-summary-title">Completed summary</div>
                          <div className="ai-run-summary-body ai-run-summary-stack">
                            <span>Completed at {completedIso || '-'}</span>
                            <span>
                              Duration {durationSeconds === null ? '-' : formatDurationShort(durationSeconds)}
                            </span>
                          </div>
                        </div>
                      ) : (
                        <div className="ai-run-summary ai-run-summary-terminal">
                          <div className="ai-run-summary-title">Failure summary</div>
                          <div className="ai-run-summary-body ai-run-summary-stack">
                            <span>Failure count {Number(run.failed_items || 0)}</span>
                            {run.last_failed_job_title && (
                              <span>Last failed {run.last_failed_job_title}</span>
                            )}
                            {run.error_message && (
                              <span>{run.error_message}</span>
                            )}
                            <span>Retry available via queue controls.</span>
                          </div>
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
            </section>
          </div>
        </>
      )}
    </section>
  );
}
