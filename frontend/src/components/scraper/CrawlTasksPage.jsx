import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  RefreshCcw,
  RotateCcw,
  Square,
} from "lucide-react";
import { apiPath } from "../../api/base";
import { fetchCapabilities } from "../../api/capabilities";
import { apiFetchJson } from "../../api/client";
import { createMonitoringId, logError, logInfo } from "../../monitoring";
import { formatCrawlModeLabel } from "./crawlMode";
import { formatCrawlPhaseLabel } from "./crawlPhase";
import { formatScraperSourceLabel } from "./listingBatchLabel";
import { buildIpBlockGuidance } from "./ipBlockGuidance";
import { cancelCrawlJob, resumeCrawlJob } from "./crawlTaskActions";
import ManualActionRecoveryPanel from "./ManualActionRecoveryPanel";
import "./CrawlTasksPage.css";

const API_BASE = apiPath("");
const PAGE_SIZE = 10;
export const AUTO_REFRESH_MS = 60_000;
const DEFAULT_FILTERS = {
  status: "all",
  sourceSite: "all",
  crawlMode: "all",
  timeRange: "all",
};
const STATUS_OPTIONS = [
  { value: "all", label: "All statuses" },
  { value: "queued", label: "Queued" },
  { value: "dispatching", label: "Dispatching" },
  { value: "running", label: "Running" },
  { value: "manual_action_required", label: "Manual Action Required" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];
const SOURCE_OPTIONS = [
  { value: "all", label: "All sources" },
  { value: "jobsdb", label: "JobsDB" },
  { value: "ctgoodjobs", label: "CTgoodjobs" },
  { value: "offertoday", label: "OfferToday" },
];
const CRAWL_MODE_OPTIONS = [
  { value: "all", label: "All modes" },
  { value: "headless", label: "Headless" },
  { value: "headed", label: "Headed" },
];
const TIME_RANGE_OPTIONS = [
  { value: "all", label: "All time" },
  { value: "24h", label: "Last 24 hours" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
];

function buildTasksUrl(page, filters) {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(PAGE_SIZE),
    time_range: filters.timeRange,
  });

  if (filters.status !== "all") {
    params.set("status", filters.status);
  }

  if (filters.sourceSite !== "all") {
    params.set("source_site", filters.sourceSite);
  }

  if (filters.crawlMode !== "all") {
    params.set("crawl_mode", filters.crawlMode);
  }

  return `${API_BASE}/crawl-jobs/tasks?${params.toString()}`;
}
function formatTimestamp(value) {
  if (!value) {
    return "-";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return `${value}`;
  }

  return parsed.toLocaleString("en-US");
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
  const requestedPhase =
    `${task?.request_payload?.crawl_phase || task?.crawl_phase || ""}`
      .trim()
      .toLowerCase();
  if (requestedPhase) {
    return requestedPhase;
  }

  // Older snapshots expose only the numeric progress phase. Keep those
  // detail tasks in the detail layout without treating ingest/full as a new
  // supported crawl phase.
  const snapshotPhase = Number(task?.phase);
  if (snapshotPhase === 2) {
    return "detail";
  }
  if (snapshotPhase === 1) {
    return "listing";
  }

  return "";
}

function isCompletedListingTask(task) {
  return (
    task?.status === "completed" &&
    resolveRequestedCrawlPhase(task) === "listing" &&
    Boolean(task?.listing_completed)
  );
}

function buildListingMetricSummary(task) {
  const summary = [];
  const normalizedSourceSite = `${task?.source_site || ""}`
    .trim()
    .toLowerCase();
  const jobIdsCollected = Number(task?.job_ids_collected || 0);
  const rawJobIdsCollected = task?.raw_job_ids_collected;
  const detailTargetRows = Number(task?.detail_target_rows || 0);
  const listingsStaged = Number(task?.listings_staged || 0);
  const currentPage = Number(task?.current_page || 0);
  const totalPages = Number(task?.total_pages || 0);

  if (jobIdsCollected > 0) {
    summary.push(`IDs ${formatCount(jobIdsCollected)}`);
  }

  if (
    rawJobIdsCollected !== null &&
    rawJobIdsCollected !== undefined &&
    Number(rawJobIdsCollected) > 0
  ) {
    summary.push(`Raw IDs ${formatCount(rawJobIdsCollected)}`);
  }

  if (listingsStaged > 0) {
    summary.push(`Staged listings ${formatCount(listingsStaged)}`);
  }

  if (detailTargetRows > 0) {
    summary.push(`Detail queue ${formatCount(detailTargetRows)}`);
  }

  if (currentPage > 0 || totalPages > 0) {
    if (normalizedSourceSite === "offertoday") {
      const maximumBudget =
        totalPages > 0 ? ` / max ${formatCount(totalPages)}` : "";
      summary.push(
        `Query requests ${formatCount(currentPage)}${maximumBudget}`,
      );
    } else {
      summary.push(`Pages ${formatCountPair(currentPage, totalPages)}`);
    }
  }

  if (summary.length === 0) {
    summary.push("Metrics pending");
  }

  return summary;
}

function buildDetailMetricSummary(task) {
  const summary = [];
  const detailTargetCount = Number(task?.detail_target_count ?? 0);
  const detailFetchedCount = Number(task?.detail_fetched_count ?? 0);
  const detailSavedCount = Number(task?.detail_saved_count ?? 0);
  const detailFailedCount = Number(task?.detail_failed_count ?? 0);
  const detailRemainingCount = Number(task?.detail_remaining_count ?? 0);
  const detailUnavailableCount = Number(task?.detail_unavailable_count ?? 0);
  const detailManualActionCount = Number(task?.detail_manual_action_count ?? 0);
  const isOfferToday =
    `${task?.source_site || ""}`.trim().toLowerCase() === "offertoday";
  const detailSegmentIndex = Number(task?.detail_segment_index || 0);
  const detailSegmentTargetRows = Number(task?.detail_segment_target_rows || 0);
  const detailBacklogRemaining = Number(task?.detail_backlog_remaining || 0);
  const detailBacklogFailed = Number(task?.detail_backlog_failed || 0);
  const detailBacklogManual = Number(
    task?.detail_backlog_manual_action_required || 0,
  );

  summary.push(`Detail targets ${formatCount(detailTargetCount)}`);
  summary.push(`Fetched ${formatCount(detailFetchedCount)}`);
  summary.push(`Saved ${formatCount(detailSavedCount)}`);
  summary.push(`Failed ${formatCount(detailFailedCount)}`);
  summary.push(`Remaining ${formatCount(detailRemainingCount)}`);
  if (detailUnavailableCount > 0) {
    summary.push(`Unavailable ${formatCount(detailUnavailableCount)}`);
  }
  if (detailManualActionCount > 0) {
    summary.push(`Manual action ${formatCount(detailManualActionCount)}`);
  }
  if (isOfferToday && (detailSegmentIndex > 0 || detailSegmentTargetRows > 0)) {
    const segmentLabel =
      detailSegmentIndex > 0
        ? `Segment ${formatCount(detailSegmentIndex)}`
        : "Segment";
    summary.push(
      `${segmentLabel} targets ${formatCount(detailSegmentTargetRows)}`,
    );
  }
  if (
    isOfferToday &&
    (task?.detail_continuation_state || detailBacklogRemaining > 0)
  ) {
    summary.push(`Backlog remaining ${formatCount(detailBacklogRemaining)}`);
  }
  if (isOfferToday && detailBacklogFailed > 0) {
    summary.push(`Backlog failed ${formatCount(detailBacklogFailed)}`);
  }
  if (isOfferToday && detailBacklogManual > 0) {
    summary.push(`Manual review ${formatCount(detailBacklogManual)}`);
  }

  return summary;
}

function buildMetricSummary(task) {
  return resolveRequestedCrawlPhase(task) === "detail"
    ? buildDetailMetricSummary(task)
    : buildListingMetricSummary(task);
}

function buildScopeHint(task) {
  const crawlPhase = resolveRequestedCrawlPhase(task);
  const detailScope =
    `${task?.detail_scope || task?.request_payload?.detail_scope || ""}`.trim();
  if (
    crawlPhase === "detail" &&
    `${task?.source_site || ""}`.trim().toLowerCase() === "offertoday"
  ) {
    if (detailScope === "global") {
      return `${formatCrawlPhaseLabel(crawlPhase)} · Global backlog`;
    }
    if (detailScope === "listing_batch") {
      return `${formatCrawlPhaseLabel(crawlPhase)} · Listing batch`;
    }
  }
  return formatCrawlPhaseLabel(crawlPhase);
}

function isIpBlockedTask(task) {
  return (
    task?.issue_class === "ip_blocked" ||
    task?.manual_action?.classification === "ip_blocked" ||
    task?.issue_code === "-1000035"
  );
}

function buildManualActionGuidance(task) {
  if (isIpBlockedTask(task)) {
    return buildIpBlockGuidance({
      sourceSite:
        task?.manual_action?.source_site ||
        task?.request_payload?.source_site ||
        task?.source_site,
      message: task?.manual_action?.message,
    }).message;
  }

  return null;
}

function buildIssueSummary(task) {
  const listingPartialSummary = (() => {
    if (!task?.listing_partial) {
      return null;
    }

    const cappedConditions = Number(task?.listing_capped_condition_count || 0);
    const totalConditions = Number(task?.listing_condition_count || 0);
    if (cappedConditions > 0 && totalConditions > 0) {
      return `Partial listing: ${formatCount(cappedConditions)} of ${formatCount(totalConditions)} query conditions reached the configured page cap.`;
    }
    if (cappedConditions > 0) {
      return `Partial listing: ${formatCount(cappedConditions)} query conditions reached the configured page cap.`;
    }
    return "Partial listing: one or more query conditions reached the configured page cap.";
  })();

  return (
    buildManualActionGuidance(task) ||
    task?.latest_issue_text ||
    task?.manual_action?.reason ||
    task?.error ||
    task?.status_reason ||
    listingPartialSummary ||
    null
  );
}

function formatStatusLabel(status) {
  return `${status || "unknown"}`.replace(/_/g, " ");
}

function buildStatusLabel(task) {
  if (isCompletedListingTask(task)) {
    return task?.listing_partial
      ? "Listing Complete (Partial)"
      : "Listing Complete";
  }

  return formatStatusLabel(task?.status);
}

function isManualActionTask(task) {
  return (
    task?.status === "manual_action_required" || Boolean(task?.manual_action)
  );
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
  const [pagination, setPagination] = useState({
    total: 0,
    page: 1,
    pageSize: PAGE_SIZE,
  });
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const [refreshedAt, setRefreshedAt] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [actionState, setActionState] = useState({
    pending: null,
    error: null,
    notice: null,
  });
  const [manualActionCapability, setManualActionCapability] = useState(null);
  const latestLoadRef = useRef(0);

  const selectedTask = useMemo(() => {
    return tasks.find((task) => task.crawl_job_id === selectedTaskId) || null;
  }, [selectedTaskId, tasks]);
  const pageCount = Math.max(
    1,
    Math.ceil((pagination.total || 0) / (pagination.pageSize || PAGE_SIZE)),
  );
  const manualActionGuidance = buildManualActionGuidance(selectedTask);

  const loadTasks = useCallback(
    async ({ reason = "refresh" } = {}) => {
      const requestId = createMonitoringId("req");
      const requestVersion = latestLoadRef.current + 1;
      const url = buildTasksUrl(page, filters);

      latestLoadRef.current = requestVersion;
      setIsLoading(true);
      setError(null);
      logInfo("crawl_tasks.load_started", {
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
        logInfo("crawl_tasks.load_succeeded", {
          reason,
          requestId,
          itemCount: nextItems.length,
          total: Number(data?.total || 0),
        });
      } catch (loadError) {
        if (latestLoadRef.current !== requestVersion) {
          return;
        }

        const detail = extractErrorMessage(
          loadError,
          "Failed to load crawl tasks",
        );
        setError(detail);
        logError("crawl_tasks.load_failed", {
          reason,
          requestId,
          detail,
        });
      } finally {
        if (latestLoadRef.current === requestVersion) {
          setIsLoading(false);
        }
      }
    },
    [filters, page],
  );

  useEffect(() => {
    void loadTasks({ reason: "initial" });

    const intervalId = window.setInterval(() => {
      void loadTasks({ reason: "poll" });
    }, AUTO_REFRESH_MS);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [loadTasks]);

  useEffect(() => {
    let cancelled = false;
    void fetchCapabilities()
      .then((payload) => {
        if (!cancelled) {
          setManualActionCapability(payload?.manual_actions || null);
        }
      })
      .catch((capabilityError) => {
        if (!cancelled) {
          logError("crawl_tasks.manual_action_capabilities_failed", {
            detail: extractErrorMessage(
              capabilityError,
              "Failed to load manual-action helper capability",
            ),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleFilterChange = useCallback(
    (field) => (event) => {
      const value = event.target.value;
      setFilters((current) => ({
        ...current,
        [field]: value,
      }));
      setPage(1);
      setActionState({ pending: null, error: null, notice: null });
    },
    [],
  );

  const handleSelectTask = useCallback((crawlJobId) => {
    setSelectedTaskId(crawlJobId);
    setActionState({ pending: null, error: null, notice: null });
  }, []);

  const runTaskAction = useCallback(
    async (actionKey, actionLabel, action) => {
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
        const detail = extractErrorMessage(
          actionError,
          `Failed to ${actionLabel.toLowerCase()}`,
        );
        setActionState({ pending: null, error: detail, notice: null });
        logError("crawl_tasks.action_failed", {
          action: actionKey,
          crawlJobId: selectedTask.crawl_job_id,
          detail,
        });
      }
    },
    [loadTasks, selectedTask],
  );

  const handleOpenEvents = useCallback(() => {
    if (!selectedTask?.crawl_job_id || typeof window === "undefined") {
      return;
    }

    window.open(
      apiPath(`/crawl-jobs/${selectedTask.crawl_job_id}/events`),
      "_blank",
      "noopener,noreferrer",
    );
  }, [selectedTask]);

  const handleTaskChanged = useCallback(
    async (reason) => {
      await loadTasks({ reason });
    },
    [loadTasks],
  );

  const handleCancelTask = useCallback(() => {
    if (!selectedTask?.crawl_job_id) {
      return;
    }
    const confirmed = window.confirm(
      `Cancel crawl job ${selectedTask.crawl_job_id}? This stops any remaining work for this task.`,
    );
    if (!confirmed) {
      return;
    }
    void runTaskAction("cancel", "Cancel crawl job", () =>
      cancelCrawlJob(selectedTask.crawl_job_id),
    );
  }, [runTaskAction, selectedTask]);

  return (
    <section className="crawl-tasks-page">
      <header className="crawl-tasks-header">
        <div>
          <h1>Crawl Tasks</h1>
          <p className="form-hint">
            Durable crawl job history with filters, paging, and operator
            actions.
          </p>
          <div className="crawl-tasks-refreshed">
            {refreshedAt
              ? `Last refreshed ${formatTimestamp(refreshedAt)}`
              : "Waiting for the first task snapshot"}
          </div>
        </div>

        <button
          type="button"
          className="crawl-tasks-refresh"
          onClick={() => void loadTasks({ reason: "manual_refresh" })}
          disabled={isLoading}
        >
          <RefreshCcw size={16} aria-hidden="true" />
          <span>{isLoading ? "Refreshing..." : "Refresh"}</span>
        </button>
      </header>

      <div
        className="crawl-tasks-filters"
        role="group"
        aria-label="Crawl task filters"
      >
        <label className="crawl-tasks-filter">
          <span className="filter-label">Status</span>
          <select
            aria-label="Status"
            data-testid="crawl-tasks-filter-status"
            className="premium-select"
            value={filters.status}
            onChange={handleFilterChange("status")}
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
            onChange={handleFilterChange("sourceSite")}
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
            onChange={handleFilterChange("crawlMode")}
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
            onChange={handleFilterChange("timeRange")}
          >
            {TIME_RANGE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && (
        <div className="crawl-tasks-banner crawl-tasks-banner-error">
          {error}
        </div>
      )}

      <div className="crawl-tasks-layout">
        <section className="glass-panel crawl-tasks-results">
          <div className="crawl-tasks-results-header">
            <div>
              <div className="crawl-tasks-total">
                {pagination.total.toLocaleString()} tasks
              </div>
              <div className="crawl-tasks-page-copy">
                Page {pagination.page} of {pageCount}
              </div>
            </div>
            <div className="crawl-tasks-page-copy">
              {isLoading ? "Refreshing task list" : "Auto refresh every 1 min"}
            </div>
          </div>

          {tasks.length === 0 ? (
            <div className="crawl-tasks-empty">
              {isLoading
                ? "Loading crawl tasks..."
                : "No crawl tasks loaded yet."}
            </div>
          ) : (
            <div
              className="crawl-tasks-list"
              role="list"
              aria-label="Crawl task results"
            >
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
                    className={`crawl-task-row ${isSelected ? "selected" : ""}`}
                    aria-pressed={isSelected}
                    onClick={() => handleSelectTask(task.crawl_job_id)}
                  >
                    <div className="crawl-task-row-topline">
                      <span
                        className={`crawl-task-status status-${task.status || "unknown"}`}
                      >
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

                    {issueSummary && (
                      <div className="crawl-task-issue">{issueSummary}</div>
                    )}
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
              onClick={() =>
                setPage((current) => Math.min(pageCount, current + 1))
              }
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
                  <div className="crawl-task-id">
                    {selectedTask.crawl_job_id}
                  </div>
                </div>
                <button
                  type="button"
                  className="crawl-tasks-link-button"
                  onClick={handleOpenEvents}
                >
                  <ExternalLink size={16} aria-hidden="true" />
                  <span>View Events</span>
                </button>
              </div>

              {manualActionGuidance && (
                <div
                  className="crawl-tasks-banner crawl-tasks-banner-warning"
                  data-testid="crawl-task-ip-block-guidance"
                >
                  {manualActionGuidance}
                </div>
              )}

              {isManualActionTask(selectedTask) ? (
                <ManualActionRecoveryPanel
                  key={selectedTask.crawl_job_id}
                  task={selectedTask}
                  capability={manualActionCapability}
                  onTaskChanged={handleTaskChanged}
                />
              ) : (
                <div className="crawl-tasks-detail-actions">
                  <button
                    type="button"
                    data-testid="crawl-task-resume"
                    disabled={actionState.pending !== null}
                    onClick={() =>
                      void runTaskAction("resume", "Resume task", () =>
                        resumeCrawlJob(selectedTask.crawl_job_id),
                      )
                    }
                  >
                    <RotateCcw size={16} aria-hidden="true" />
                    <span>Resume Task</span>
                  </button>
                </div>
              )}

              {actionState.error && (
                <div className="crawl-tasks-banner crawl-tasks-banner-error">
                  {actionState.error}
                </div>
              )}
              {actionState.notice && (
                <div className="crawl-tasks-banner crawl-tasks-banner-success">
                  {actionState.notice}
                </div>
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
                  <dd data-testid="crawl-task-detail-metrics">
                    {buildMetricSummary(selectedTask).join(" | ")}
                  </dd>
                </div>
              </dl>

              <div className="crawl-tasks-detail-block">
                <div className="crawl-tasks-detail-label">Issue Class</div>
                <div
                  className="crawl-tasks-detail-text"
                  data-testid="crawl-task-issue-class"
                >
                  {selectedTask.issue_class || "none"}
                </div>
              </div>

              <div className="crawl-tasks-detail-block">
                <div className="crawl-tasks-detail-label">Issue Code</div>
                <div
                  className="crawl-tasks-detail-text"
                  data-testid="crawl-task-issue-code"
                >
                  {selectedTask.issue_code || "none"}
                </div>
              </div>

              <div className="crawl-tasks-detail-block">
                <div className="crawl-tasks-detail-label">Issue Stage</div>
                <div
                  className="crawl-tasks-detail-text"
                  data-testid="crawl-task-issue-stage"
                >
                  {selectedTask.issue_stage || "none"}
                </div>
              </div>

              {buildIssueSummary(selectedTask) && (
                <div className="crawl-tasks-detail-block">
                  <div className="crawl-tasks-detail-label">Latest issue</div>
                  <div
                    className="crawl-tasks-detail-text"
                    data-testid="crawl-task-latest-issue-text"
                  >
                    {buildIssueSummary(selectedTask)}
                  </div>
                </div>
              )}

              {selectedTask.manual_action && (
                <div className="crawl-tasks-detail-block">
                  <div className="crawl-tasks-detail-label">
                    Manual action payload
                  </div>
                  <pre className="crawl-tasks-json">
                    {JSON.stringify(selectedTask.manual_action, null, 2)}
                  </pre>
                </div>
              )}

              {selectedTask.request_payload && (
                <div className="crawl-tasks-detail-block">
                  <div className="crawl-tasks-detail-label">
                    Request payload
                  </div>
                  <pre className="crawl-tasks-json">
                    {JSON.stringify(selectedTask.request_payload, null, 2)}
                  </pre>
                </div>
              )}

              <div className="crawl-tasks-danger-zone">
                <div>
                  <strong>Danger zone</strong>
                  <p>Cancel this crawl only when it should not be resumed.</p>
                </div>
                <button
                  type="button"
                  data-testid="crawl-task-cancel"
                  disabled={actionState.pending !== null}
                  onClick={handleCancelTask}
                >
                  <Square size={16} aria-hidden="true" />
                  <span>Cancel Crawl Job</span>
                </button>
              </div>
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
