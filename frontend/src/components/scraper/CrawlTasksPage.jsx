import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  MonitorPlay,
  RefreshCcw,
  RotateCcw,
  Square,
  Unplug,
} from 'lucide-react';
import { apiPath } from '../../api/base';
import { apiFetchJson } from '../../api/client';
import { createMonitoringId, logError, logInfo } from '../../monitoring';
import { formatCrawlModeLabel } from './crawlMode';
import { formatCrawlPhaseLabel } from './crawlPhase';
import { formatScraperSourceLabel } from './listingBatchLabel';
import {
  cancelCrawlJob,
  closeManualActionWindows,
  getManualActionReuseStatus,
  openManualActionBrowser,
  resumeCrawlJob,
} from './crawlTaskActions';
import './CrawlTasksPage.css';

const API_BASE = apiPath('');
const PAGE_SIZE = 10;
const AUTO_REFRESH_MS = 10000;
const DEFAULT_FILTERS = {
  status: 'all',
  sourceSite: 'all',
  crawlMode: 'all',
  timeRange: 'all',
};
const STATUS_OPTIONS = [
  { value: 'all', label: 'All statuses' },
  { value: 'queued', label: 'Queued' },
  { value: 'dispatching', label: 'Dispatching' },
  { value: 'running', label: 'Running' },
  { value: 'manual_action_required', label: 'Manual Action Required' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'cancelled', label: 'Cancelled' },
];
const SOURCE_OPTIONS = [
  { value: 'all', label: 'All sources' },
  { value: 'jobsdb', label: 'JobsDB' },
  { value: 'ctgoodjobs', label: 'CTgoodjobs' },
  { value: 'offertoday', label: 'OfferToday' },
];
const CRAWL_MODE_OPTIONS = [
  { value: 'all', label: 'All modes' },
  { value: 'headless', label: 'Headless' },
  { value: 'headed', label: 'Headed' },
];
const TIME_RANGE_OPTIONS = [
  { value: 'all', label: 'All time' },
  { value: '24h', label: 'Last 24 hours' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
];

function buildTasksUrl(page, filters) {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(PAGE_SIZE),
    time_range: filters.timeRange,
  });

  if (filters.status !== 'all') {
    params.set('status', filters.status);
  }

  if (filters.sourceSite !== 'all') {
    params.set('source_site', filters.sourceSite);
  }

  if (filters.crawlMode !== 'all') {
    params.set('crawl_mode', filters.crawlMode);
  }

  return `${API_BASE}/crawl-jobs/tasks?${params.toString()}`;
}

function formatTimestamp(value) {
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
  const normalizedTotal = Number(totalValue || 0);
  if (Number.isFinite(normalizedTotal) && normalizedTotal > 0) {
    return `${formatCount(currentValue)}/${formatCount(normalizedTotal)}`;
  }

  return `${formatCount(currentValue)}/?`;
}

function resolveRequestedCrawlPhase(task) {
  return `${task?.request_payload?.crawl_phase || task?.crawl_phase || ''}`.trim().toLowerCase();
}

function isCompletedListingTask(task) {
  return task?.status === 'completed'
    && resolveRequestedCrawlPhase(task) === 'listing'
    && Boolean(task?.listing_completed);
}

function buildMetricSummary(task) {
  const summary = [];
  const normalizedSourceSite = `${task?.source_site || ''}`.trim().toLowerCase();
  const jobIdsCollected = Number(task?.job_ids_collected || 0);
  const detailTargetRows = Number(task?.detail_target_rows || 0);
  const jobsSaved = Number(task?.jobs_saved || 0);
  const listingsStaged = Number(task?.listings_staged || 0);
  const currentPage = Number(task?.current_page || 0);
  const totalPages = Number(task?.total_pages || 0);
  const failedItems = Number(task?.detail_run_failed || task?.ingest_items_failed || 0);
  const listingPageLabel = normalizedSourceSite === 'offertoday' ? 'Query tasks' : 'Pages';
  const completedListingTask = isCompletedListingTask(task);

  if (jobIdsCollected > 0) {
    summary.push(`IDs ${formatCount(jobIdsCollected)}`);
  }

  if (detailTargetRows > 0) {
    summary.push(`${completedListingTask ? 'Ready for detail' : 'Queue'} ${formatCount(detailTargetRows)}`);
  }

  if (listingsStaged > 0) {
    summary.push(`Staged ${formatCount(listingsStaged)}`);
  }

  if (currentPage > 0 || totalPages > 0) {
    summary.push(`${listingPageLabel} ${formatCountPair(currentPage, totalPages)}`);
  }

  if (jobsSaved > 0) {
    summary.push(`Saved ${formatCount(jobsSaved)}`);
  }

  if (failedItems > 0) {
    summary.push(`Failed ${formatCount(failedItems)}`);
  }

  if (summary.length === 0) {
    summary.push('Metrics pending');
  }

  return summary;
}

function buildScopeHint(task) {
  const crawlPhase = resolveRequestedCrawlPhase(task);
  return formatCrawlPhaseLabel(crawlPhase);
}

function buildIssueSummary(task) {
  return (
    task?.latest_issue_text ||
    task?.manual_action?.reason ||
    task?.error ||
    task?.status_reason ||
    null
  );
}

function formatStatusLabel(status) {
  return `${status || 'unknown'}`.replace(/_/g, ' ');
}

function buildStatusLabel(task) {
  if (isCompletedListingTask(task)) {
    return 'Listing Complete';
  }

  return formatStatusLabel(task?.status);
}

function isManualActionTask(task) {
  return task?.status === 'manual_action_required' || Boolean(task?.manual_action);
}

function extractErrorMessage(error, fallbackMessage) {
  if (error instanceof Error && error.message) {
    return error.message;
  }

  return fallbackMessage;
}

export default function CrawlTasksPage() {
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [page, setPage] = useState(1);
  const [tasks, setTasks] = useState([]);
  const [pagination, setPagination] = useState({ total: 0, page: 1, pageSize: PAGE_SIZE });
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const [refreshedAt, setRefreshedAt] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [actionState, setActionState] = useState({ pending: null, error: null, notice: null });
  const latestLoadRef = useRef(0);

  const selectedTask = useMemo(() => {
    return tasks.find((task) => task.crawl_job_id === selectedTaskId) || null;
  }, [selectedTaskId, tasks]);
  const pageCount = Math.max(1, Math.ceil((pagination.total || 0) / (pagination.pageSize || PAGE_SIZE)));

  const loadTasks = useCallback(async ({ reason = 'refresh' } = {}) => {
    const requestId = createMonitoringId('req');
    const requestVersion = latestLoadRef.current + 1;
    const url = buildTasksUrl(page, filters);

    latestLoadRef.current = requestVersion;
    setIsLoading(true);
    setError(null);
    logInfo('crawl_tasks.load_started', {
      reason,
      requestId,
      url,
    });

    try {
      const data = await apiFetchJson(url, { requestId });
      if (latestLoadRef.current !== requestVersion) {
        return;
      }

      const nextItems = Array.isArray(data?.items) ? data.items : [];
      setTasks(nextItems);
      setPagination({
        total: Number(data?.total || 0),
        page: Number(data?.page || page),
        pageSize: Number(data?.page_size || PAGE_SIZE),
      });
      setRefreshedAt(data?.refreshed_at || null);
      setSelectedTaskId((currentId) => {
        if (nextItems.some((task) => task.crawl_job_id === currentId)) {
          return currentId;
        }

        return nextItems[0]?.crawl_job_id || null;
      });
      logInfo('crawl_tasks.load_succeeded', {
        reason,
        requestId,
        itemCount: nextItems.length,
        total: Number(data?.total || 0),
      });
    } catch (loadError) {
      if (latestLoadRef.current !== requestVersion) {
        return;
      }

      const detail = extractErrorMessage(loadError, 'Failed to load crawl tasks');
      setError(detail);
      logError('crawl_tasks.load_failed', {
        reason,
        requestId,
        detail,
      });
    } finally {
      if (latestLoadRef.current === requestVersion) {
        setIsLoading(false);
      }
    }
  }, [filters, page]);

  useEffect(() => {
    void loadTasks({ reason: 'initial' });

    const intervalId = window.setInterval(() => {
      void loadTasks({ reason: 'poll' });
    }, AUTO_REFRESH_MS);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [loadTasks]);

  const handleFilterChange = useCallback((field) => (event) => {
    const value = event.target.value;
    setFilters((current) => ({
      ...current,
      [field]: value,
    }));
    setPage(1);
    setActionState({ pending: null, error: null, notice: null });
  }, []);

  const handleSelectTask = useCallback((crawlJobId) => {
    setSelectedTaskId(crawlJobId);
    setActionState({ pending: null, error: null, notice: null });
  }, []);

  const runTaskAction = useCallback(async (actionKey, actionLabel, action) => {
    if (!selectedTask?.crawl_job_id) {
      return;
    }

    setActionState({ pending: actionKey, error: null, notice: null });

    try {
      await action();
      setActionState({
        pending: null,
        error: null,
        notice: `${actionLabel} requested for ${selectedTask.crawl_job_id}.`,
      });
      await loadTasks({ reason: actionKey });
    } catch (actionError) {
      const detail = extractErrorMessage(actionError, `Failed to ${actionLabel.toLowerCase()}`);
      setActionState({ pending: null, error: detail, notice: null });
      logError('crawl_tasks.action_failed', {
        action: actionKey,
        crawlJobId: selectedTask.crawl_job_id,
        detail,
      });
    }
  }, [loadTasks, selectedTask]);

  const handleOpenEvents = useCallback(() => {
    if (!selectedTask?.crawl_job_id || typeof window === 'undefined') {
      return;
    }

    window.open(
      apiPath(`/crawl-jobs/${selectedTask.crawl_job_id}/events`),
      '_blank',
      'noopener,noreferrer'
    );
  }, [selectedTask]);

  return (
    <section className="crawl-tasks-page">
      <header className="crawl-tasks-header">
        <div>
          <h1>Crawl Tasks</h1>
          <p className="form-hint">
            Durable crawl job history with filters, paging, and operator actions.
          </p>
          <div className="crawl-tasks-refreshed">
            {refreshedAt
              ? `Last refreshed ${formatTimestamp(refreshedAt)}`
              : 'Waiting for the first task snapshot'}
          </div>
        </div>

        <button
          type="button"
          className="crawl-tasks-refresh"
          onClick={() => void loadTasks({ reason: 'manual_refresh' })}
          disabled={isLoading}
        >
          <RefreshCcw size={16} aria-hidden="true" />
          <span>{isLoading ? 'Refreshing...' : 'Refresh'}</span>
        </button>
      </header>

      <div className="crawl-tasks-filters" role="group" aria-label="Crawl task filters">
        <label className="crawl-tasks-filter">
          <span className="filter-label">Status</span>
          <select
            aria-label="Status"
            data-testid="crawl-tasks-filter-status"
            className="premium-select"
            value={filters.status}
            onChange={handleFilterChange('status')}
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="crawl-tasks-filter">
          <span className="filter-label">Source Site</span>
          <select
            aria-label="Source Site"
            data-testid="crawl-tasks-filter-source"
            className="premium-select"
            value={filters.sourceSite}
            onChange={handleFilterChange('sourceSite')}
          >
            {SOURCE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="crawl-tasks-filter">
          <span className="filter-label">Crawl Mode</span>
          <select
            aria-label="Crawl Mode"
            data-testid="crawl-tasks-filter-mode"
            className="premium-select"
            value={filters.crawlMode}
            onChange={handleFilterChange('crawlMode')}
          >
            {CRAWL_MODE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="crawl-tasks-filter">
          <span className="filter-label">Time Range</span>
          <select
            aria-label="Time Range"
            data-testid="crawl-tasks-filter-time-range"
            className="premium-select"
            value={filters.timeRange}
            onChange={handleFilterChange('timeRange')}
          >
            {TIME_RANGE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && <div className="crawl-tasks-banner crawl-tasks-banner-error">{error}</div>}

      <div className="crawl-tasks-layout">
        <section className="glass-panel crawl-tasks-results">
          <div className="crawl-tasks-results-header">
            <div>
              <div className="crawl-tasks-total">
                {pagination.total.toLocaleString()} tasks
              </div>
              <div className="crawl-tasks-page-copy">Page {pagination.page} of {pageCount}</div>
            </div>
            <div className="crawl-tasks-page-copy">
              {isLoading ? 'Refreshing task list' : 'Auto refresh every 10s'}
            </div>
          </div>

          {tasks.length === 0 ? (
            <div className="crawl-tasks-empty">
              {isLoading ? 'Loading crawl tasks...' : 'No crawl tasks loaded yet.'}
            </div>
          ) : (
            <div className="crawl-tasks-list" role="list" aria-label="Crawl task results">
              {tasks.map((task) => {
                const issueSummary = buildIssueSummary(task);
                const metricSummary = buildMetricSummary(task);
                const isSelected = task.crawl_job_id === selectedTaskId;

                return (
                  <button
                    key={task.crawl_job_id}
                    type="button"
                    role="listitem"
                    data-testid={`crawl-task-row-${task.crawl_job_id}`}
                    className={`crawl-task-row ${isSelected ? 'selected' : ''}`}
                    aria-pressed={isSelected}
                    onClick={() => handleSelectTask(task.crawl_job_id)}
                  >
                    <div className="crawl-task-row-topline">
                      <span className={`crawl-task-status status-${task.status || 'unknown'}`}>
                        {buildStatusLabel(task)}
                      </span>
                      <span className="crawl-task-id">{task.crawl_job_id}</span>
                    </div>

                    <div className="crawl-task-row-meta">
                      <span>{formatScraperSourceLabel(task.source_site)}</span>
                      <span>{formatCrawlModeLabel(task.crawl_mode)}</span>
                      <span>{buildScopeHint(task)}</span>
                      <span>Updated {formatTimestamp(task.updated_at)}</span>
                    </div>

                    <div className="crawl-task-row-metrics">
                      {metricSummary.map((chip) => (
                        <span key={chip} className="crawl-task-chip">
                          {chip}
                        </span>
                      ))}
                    </div>

                    {issueSummary && <div className="crawl-task-issue">{issueSummary}</div>}
                  </button>
                );
              })}
            </div>
          )}

          <div className="crawl-tasks-pagination">
            <button
              type="button"
              onClick={() => setPage((current) => Math.max(1, current - 1))}
              disabled={page <= 1 || isLoading}
            >
              <ChevronLeft size={16} aria-hidden="true" />
              <span>Previous Page</span>
            </button>

            <button
              type="button"
              onClick={() => setPage((current) => Math.min(pageCount, current + 1))}
              disabled={page >= pageCount || isLoading}
            >
              <span>Next Page</span>
              <ChevronRight size={16} aria-hidden="true" />
            </button>
          </div>
        </section>

        <aside className="glass-panel crawl-tasks-detail">
          {selectedTask ? (
            <>
              <div className="crawl-tasks-detail-header">
                <div>
                  <h2>Task Details</h2>
                  <div className="crawl-task-id">{selectedTask.crawl_job_id}</div>
                </div>
                <button type="button" className="crawl-tasks-link-button" onClick={handleOpenEvents}>
                  <ExternalLink size={16} aria-hidden="true" />
                  <span>View Events</span>
                </button>
              </div>

              <div className="crawl-tasks-detail-actions">
                {isManualActionTask(selectedTask) ? (
                  <>
                    <button
                      type="button"
                      data-testid="crawl-task-resume-open-browser"
                      disabled={actionState.pending !== null}
                      onClick={() =>
                        void runTaskAction(
                          'resume_open_browser',
                          'Resume using open browser',
                          () => resumeCrawlJob(selectedTask.crawl_job_id, 'reuse_open_browser')
                        )
                      }
                    >
                      <RotateCcw size={16} aria-hidden="true" />
                      <span>Resume using Open Browser</span>
                    </button>

                    <button
                      type="button"
                      data-testid="crawl-task-resume-fresh"
                      disabled={actionState.pending !== null}
                      onClick={() =>
                        void runTaskAction('resume_fresh', 'Resume fresh', () =>
                          resumeCrawlJob(selectedTask.crawl_job_id, 'fresh_profile')
                        )
                      }
                    >
                      <RotateCcw size={16} aria-hidden="true" />
                      <span>Resume Fresh</span>
                    </button>

                    <button
                      type="button"
                      data-testid="crawl-task-open-browser"
                      disabled={actionState.pending !== null}
                      onClick={() =>
                        void runTaskAction('open_browser', 'Open browser', () =>
                          openManualActionBrowser(selectedTask.crawl_job_id)
                        )
                      }
                    >
                      <MonitorPlay size={16} aria-hidden="true" />
                      <span>Open Browser</span>
                    </button>

                    <button
                      type="button"
                      data-testid="crawl-task-check-reuse-status"
                      disabled={actionState.pending !== null}
                      onClick={() =>
                        void runTaskAction('reuse_status', 'Check reuse status', () =>
                          getManualActionReuseStatus(selectedTask.crawl_job_id)
                        )
                      }
                    >
                      <RefreshCcw size={16} aria-hidden="true" />
                      <span>Check Reuse Status</span>
                    </button>

                    <button
                      type="button"
                      data-testid="crawl-task-close-profile-windows"
                      disabled={actionState.pending !== null}
                      onClick={() =>
                        void runTaskAction('close_windows', 'Close profile windows', () =>
                          closeManualActionWindows(selectedTask.crawl_job_id)
                        )
                      }
                    >
                      <Unplug size={16} aria-hidden="true" />
                      <span>Close Profile Windows</span>
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    data-testid="crawl-task-resume"
                    disabled={actionState.pending !== null}
                    onClick={() =>
                      void runTaskAction('resume', 'Resume task', () =>
                        resumeCrawlJob(selectedTask.crawl_job_id)
                      )
                    }
                  >
                    <RotateCcw size={16} aria-hidden="true" />
                    <span>Resume Task</span>
                  </button>
                )}

                <button
                  type="button"
                  data-testid="crawl-task-cancel"
                  disabled={actionState.pending !== null}
                  onClick={() =>
                    void runTaskAction('cancel', 'Cancel crawl job', () =>
                      cancelCrawlJob(selectedTask.crawl_job_id)
                    )
                  }
                >
                  <Square size={16} aria-hidden="true" />
                  <span>Cancel Crawl Job</span>
                </button>
              </div>

              {actionState.error && (
                <div className="crawl-tasks-banner crawl-tasks-banner-error">{actionState.error}</div>
              )}
              {actionState.notice && (
                <div className="crawl-tasks-banner crawl-tasks-banner-success">{actionState.notice}</div>
              )}

              <dl className="crawl-tasks-detail-grid">
                <div>
                  <dt>Status</dt>
                  <dd>{buildStatusLabel(selectedTask)}</dd>
                </div>
                <div>
                  <dt>Source</dt>
                  <dd>{formatScraperSourceLabel(selectedTask.source_site)}</dd>
                </div>
                <div>
                  <dt>Crawl Mode</dt>
                  <dd>{formatCrawlModeLabel(selectedTask.crawl_mode)}</dd>
                </div>
                <div>
                  <dt>Scope</dt>
                  <dd>{buildScopeHint(selectedTask)}</dd>
                </div>
                <div>
                  <dt>Queued</dt>
                  <dd>{formatTimestamp(selectedTask.queued_at)}</dd>
                </div>
                <div>
                  <dt>Started</dt>
                  <dd>{formatTimestamp(selectedTask.started_at)}</dd>
                </div>
                <div>
                  <dt>Updated</dt>
                  <dd>{formatTimestamp(selectedTask.updated_at)}</dd>
                </div>
                <div>
                  <dt>Metrics</dt>
                  <dd>{buildMetricSummary(selectedTask).join(' | ')}</dd>
                </div>
              </dl>

              <div className="crawl-tasks-detail-block">
                <div className="crawl-tasks-detail-label">Issue Class</div>
                <div className="crawl-tasks-detail-text" data-testid="crawl-task-issue-class">
                  {selectedTask.issue_class || 'none'}
                </div>
              </div>

              <div className="crawl-tasks-detail-block">
                <div className="crawl-tasks-detail-label">Issue Code</div>
                <div className="crawl-tasks-detail-text" data-testid="crawl-task-issue-code">
                  {selectedTask.issue_code || 'none'}
                </div>
              </div>

              <div className="crawl-tasks-detail-block">
                <div className="crawl-tasks-detail-label">Issue Stage</div>
                <div className="crawl-tasks-detail-text" data-testid="crawl-task-issue-stage">
                  {selectedTask.issue_stage || 'none'}
                </div>
              </div>

              {buildIssueSummary(selectedTask) && (
                <div className="crawl-tasks-detail-block">
                  <div className="crawl-tasks-detail-label">Latest issue</div>
                  <div className="crawl-tasks-detail-text" data-testid="crawl-task-latest-issue-text">
                    {buildIssueSummary(selectedTask)}
                  </div>
                </div>
              )}

              {selectedTask.manual_action && (
                <div className="crawl-tasks-detail-block">
                  <div className="crawl-tasks-detail-label">Manual action payload</div>
                  <pre className="crawl-tasks-json">
                    {JSON.stringify(selectedTask.manual_action, null, 2)}
                  </pre>
                </div>
              )}

              {selectedTask.request_payload && (
                <div className="crawl-tasks-detail-block">
                  <div className="crawl-tasks-detail-label">Request payload</div>
                  <pre className="crawl-tasks-json">
                    {JSON.stringify(selectedTask.request_payload, null, 2)}
                  </pre>
                </div>
              )}
            </>
          ) : (
            <div className="crawl-tasks-empty">
              Select a task to inspect details and actions.
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}
