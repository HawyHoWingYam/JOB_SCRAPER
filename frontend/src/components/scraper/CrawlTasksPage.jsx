import React, {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  ChevronLeft,
  ChevronRight,
  RefreshCcw,
} from "lucide-react";
import { apiPath } from "../../api/base";
import { apiFetchJson } from "../../api/client";
import { createMonitoringId, logError, logInfo } from "../../monitoring";
import { formatCrawlModeLabel } from "./crawlMode";
import { formatCrawlPhaseLabel } from "./crawlPhase";
import { formatScraperSourceLabel } from "./listingBatchLabel";
import { cancelCrawlJob } from "./crawlTaskActions";
import {
  evaluateCrawlQuality,
  evaluateIncidentTriage,
  getCrawlQuality,
  getIncidentTriage,
  getCrawlTaskDetail,
  previewCrawlQuality,
  previewIncidentTriage,
  resumeManualTask,
} from "../../features/taskControl/board/boardApi";
import { buildCrawlTaskRoute, parseCrawlTaskRoute } from "../../features/taskControl/board/boardRoute";
import { buildControlRoute, newDraftId } from "../../features/taskControl/shared/controlRoute";
import { createWizardDraft, writeDraft } from "../../features/taskControl/wizard/wizardDraft";
import ConfirmActionDialog from "../../features/taskControl/shared/ConfirmActionDialog";
import CrawlTaskDetails from "./CrawlTaskDetails";
import CrawlTaskEvents from "./CrawlTaskEvents";
import "./CrawlTasksPage.css";

const API_BASE = apiPath("");
const PAGE_SIZE = 10;
export const AUTO_REFRESH_MS = 60_000;
export const CANCELLATION_REFRESH_MS = 1_000;
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
  { value: "cancelling", label: "Cancelling" },
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

function IncidentTriageAdvisory({ value, pending, error, onPreview, onEvaluate }) {
  const [eventLimit, setEventLimit] = useState(200);
  const maximum = Number(value?.maximum_event_limit || 200);
  const boundedLimit = Math.max(1, Math.min(maximum, eventLimit));
  const preview = value?.preview;
  const latest = value?.latest;
  return (
    <section className="glass-panel crawl-tasks-detail-block" aria-label="Jev repeated incident triage">
      <h2>Repeated incident triage</h2>
      <p>
        Jev prioritizes secret-safe clusters only. It cannot change severity,
        retry, resume, cancel, dismiss, or write Crawl Job events.
      </p>
      <label>
        <span>Recent incident event limit</span>
        <input
          aria-label="Jev incident event limit"
          type="number"
          min="1"
          max={maximum}
          value={boundedLimit}
          onChange={(event) => setEventLimit(Math.max(1, Math.min(maximum, Number(event.target.value) || 1)))}
        />
      </label>
      <div className="board-actions">
        <button type="button" disabled={pending !== null} onClick={() => onPreview(boundedLimit)}>
          Preview incident clusters
        </button>
        <button
          type="button"
          disabled={!value?.enabled || pending !== null || !preview?.selected_cluster_count}
          onClick={() => onEvaluate(preview.id)}
        >
          Evaluate clusters with Jev
        </button>
      </div>
      {!value?.enabled && <p>Incident triage is disabled in Settings.</p>}
      {preview && (
        <p role="status">
          Free database preview: {preview.selected_cluster_count} clusters selected
          from {preview.total_event_count} events. No Jev request was sent.
        </p>
      )}
      {error && <p role="alert" className="crawl-tasks-banner crawl-tasks-banner-error">{error}</p>}
      {latest && (
        <div data-testid="jev-incident-triage-receipt">
          <p>
            <strong>Latest:</strong> {latest.status}
            {latest.request_id && ` · receipt ${latest.request_id}`}
            {latest.provider && ` · ${latest.provider}`}
            {latest.cost_usd != null && ` · cost USD ${Number(latest.cost_usd).toFixed(5)}`}
            {latest.error_code && ` · ${latest.error_code}`}
          </p>
          {latest.status !== 'completed' && (
            <p data-testid="jev-incident-triage-fallback">
              Fallback: deterministic clusters remain visible without Jev prioritization.
            </p>
          )}
          {(latest.clusters || []).map((cluster) => (
            <article key={cluster.id} className="crawl-tasks-detail-text">
              <strong>{cluster.source_site} · {cluster.issue_class}</strong>
              {' · '}{cluster.event_count} events
              {cluster.disposition && ` · ${cluster.disposition}`}
              <br />{cluster.normalized_symptom}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

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
    `${task?.crawl_phase || ""}`
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
  const workload = task?.listing_workload || {};
  const currentPage = Number(
    workload.pages_requested ?? task?.current_page ?? 0,
  );
  const totalPages = Number(
    workload.estimated_max_pages ?? task?.total_pages ?? 0,
  );
  const runPageCap = Number(workload.run_page_cap || 0);

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
      const maximumBudget = totalPages > 0 ? `/${formatCount(totalPages)}` : "/?";
      summary.push(`Pages requested ${formatCount(currentPage)}${maximumBudget}`);
      if (runPageCap > 0 && runPageCap !== totalPages) {
        summary.push(`Run page cap ${formatCount(runPageCap)}`);
      }
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
    `${task?.detail_scope || ""}`.trim();
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

function buildIssueSummary(task) {
  const listingPartialSummary = (() => {
    if (!isCompletedListingTask(task) || !task?.listing_partial) {
      return null;
    }

    const cappedConditions = Number(task?.listing_capped_condition_count || 0);
    const totalConditions = Number(
      task?.listing_condition_count || task?.listing_workload?.query_target_count || 0,
    );
    if (cappedConditions > 0 && totalConditions > 0) {
      return `${formatCount(cappedConditions)} of ${formatCount(totalConditions)} query targets reached the page-depth limit.`;
    }
    if (cappedConditions > 0) {
      return `${formatCount(cappedConditions)} query targets reached the page-depth limit.`;
    }
    return "Some query targets reached the page-depth limit before listing was exhausted.";
  })();

  return (
    listingPartialSummary ||
    task?.latest_issue_text ||
    task?.error ||
    task?.status_reason ||
    null
  );
}

function formatStatusLabel(status) {
  return `${status || "unknown"}`.replace(/_/g, " ");
}

function buildStatusLabel(task) {
  if (task?.operator_state === "completed_with_downstream_backlog") {
    return "Completed with downstream backlog";
  }
  if (task?.operator_state === "stale_downstream_backlog") {
    return "Terminal with downstream backlog";
  }
  if (isCompletedListingTask(task)) {
    return task?.listing_partial
      ? "Completed with partial listing"
      : "Completed";
  }

  return formatStatusLabel(task?.status);
}

function buildStatusClassName(task) {
  if (
    task?.operator_state === "completed_with_downstream_backlog" ||
    task?.operator_state === "stale_downstream_backlog"
  ) {
    return "status-backlog";
  }
  return isCompletedListingTask(task) && task.listing_partial
    ? "status-partial"
    : `status-${task.status || "unknown"}`;
}

function createCappedListingDraft(detail) {
  const run = detail?.run;
  const recovery = detail?.listingRecovery || run?.listingRecovery;
  const classificationIds = Array.isArray(recovery?.cappedClassificationIds)
    ? recovery.cappedClassificationIds.filter(Boolean)
    : [];
  if (!run || !recovery?.continuationSupported || classificationIds.length === 0) {
    return null;
  }

  const sourceSite = run.sourceSite;
  const sourcePrefix = `${String(sourceSite || '').trim().toLowerCase()}:`;
  if (
    !String(sourceSite || '').trim() ||
    classificationIds.some(
      (classificationId) =>
        !String(classificationId).toLowerCase().startsWith(sourcePrefix),
    )
  ) {
    return null;
  }
  const draftId = newDraftId();
  const pageDepth = Math.max(
    1,
    Number(recovery.pageDepth || run.listingWorkload?.page_depth || 1),
  );
  const targetCount = Math.max(
    classificationIds.length,
    Number(recovery.cappedQueryTargetCount || classificationIds.length),
  );
  const systemCap = 1000;
  const runPageCap = Math.min(Math.max(targetCount * pageDepth, 1), systemCap);
  const draft = createWizardDraft(
    {
      flow: "one_off",
      mode: "create",
      automationId: null,
      sourceSite,
    },
    sourceSite,
  );
  draft.step = "review";
  draft.intent = "listing";
  draft.scope = {
    mode: "selected",
    classification_ids: classificationIds,
  };
  draft.execution = {
    page_depth: pageDepth,
    run_page_cap: runPageCap,
    crawl_mode: run.mode,
  };
  let storage = null;
  try {
    storage = window.sessionStorage;
  } catch {
    storage = null;
  }
  writeDraft(storage, draftId, draft);
  const route = buildControlRoute({
    flow: "one_off",
    mode: "create",
    automationId: null,
    sourceSite,
    draftId,
    step: "review",
  });
  window.location.hash = route;
  return draftId;
}

function isCancellingTask(task) {
  return task?.status === "cancelling";
}

function extractErrorMessage(error, fallbackMessage) {
  if (error instanceof Error && error.message) {
    return error.message;
  }

  return fallbackMessage;
}

export default function CrawlTasksPage() {
  const initialRoute = typeof window === "undefined" ? { taskId: null } : parseCrawlTaskRoute(window.location.hash);
  const [filters, setFilters] = useState(initialRoute.filters || DEFAULT_FILTERS);
  const [page, setPage] = useState(initialRoute.page || 1);
  const [detailView, setDetailView] = useState(initialRoute.view);
  const [tasks, setTasks] = useState([]);
  const [pagination, setPagination] = useState({
    total: 0,
    page: 1,
    pageSize: PAGE_SIZE,
  });
  const [selectedTaskId, setSelectedTaskId] = useState(initialRoute.taskId);
  const [selectedTaskDetail, setSelectedTaskDetail] = useState(null);
  const [selectedTaskDetailError, setSelectedTaskDetailError] = useState(null);
  const [selectedTaskDetailLoading, setSelectedTaskDetailLoading] = useState(false);
  const [crawlQuality, setCrawlQuality] = useState(null);
  const [crawlQualityPending, setCrawlQualityPending] = useState(null);
  const [crawlQualityError, setCrawlQualityError] = useState('');
  const [incidentTriage, setIncidentTriage] = useState(null);
  const [incidentTriagePending, setIncidentTriagePending] = useState(null);
  const [incidentTriageError, setIncidentTriageError] = useState('');
  const [refreshedAt, setRefreshedAt] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [actionState, setActionState] = useState({
    pending: null,
    error: null,
    notice: null,
  });
  const [cancelDialogOpen, setCancelDialogOpen] = useState(false);
  const latestLoadRef = useRef(0);
  const latestDetailRef = useRef(0);
  const dialogTriggerRef = useRef(null);
  const pageCount = Math.max(
    1,
    Math.ceil((pagination.total || 0) / (pagination.pageSize || PAGE_SIZE)),
  );
  const hasCancellingTask = tasks.some(isCancellingTask);

  useEffect(() => {
    const controller = new AbortController();
    getIncidentTriage({ signal: controller.signal })
      .then((result) => setIncidentTriage(result))
      .catch((triageError) => {
        if (!controller.signal.aborted) {
          setIncidentTriageError(extractErrorMessage(triageError, 'Incident triage is unavailable'));
        }
      });
    return () => controller.abort();
  }, []);

  const loadSelectedTaskDetail = useCallback(async ({ signal } = {}) => {
    if (!selectedTaskId) {
      latestDetailRef.current += 1;
      setSelectedTaskDetail(null);
      setSelectedTaskDetailError(null);
      setCrawlQuality(null);
      return;
    }
    const requestVersion = ++latestDetailRef.current;
    const isCurrent = () => !signal?.aborted && requestVersion === latestDetailRef.current;
    setSelectedTaskDetail((current) => current?.run.id === selectedTaskId ? current : null);
    setSelectedTaskDetailLoading(true);
    try {
      const value = await getCrawlTaskDetail(selectedTaskId, { signal });
      if (isCurrent()) {
        setSelectedTaskDetail(value);
        setSelectedTaskDetailError(null);
      }
      try {
        const quality = await getCrawlQuality(selectedTaskId, { signal });
        if (isCurrent()) {
          setCrawlQuality(quality);
          setCrawlQualityError('');
        }
      } catch (qualityError) {
        if (isCurrent()) {
          setCrawlQuality(null);
          setCrawlQualityError(extractErrorMessage(qualityError, 'Crawl quality is unavailable'));
        }
      }
    } catch (detailError) {
      if (isCurrent()) setSelectedTaskDetailError(extractErrorMessage(detailError, "Failed to load normalized Task Details"));
    } finally {
      if (isCurrent()) setSelectedTaskDetailLoading(false);
    }
  }, [selectedTaskId]);

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
          if (currentId) {
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

    const intervalId = window.setInterval(
      () => {
        void loadTasks({ reason: "poll" });
      },
      hasCancellingTask ? CANCELLATION_REFRESH_MS : AUTO_REFRESH_MS,
    );

    return () => {
      window.clearInterval(intervalId);
    };
  }, [hasCancellingTask, loadTasks]);

  useEffect(() => {
    const controller = new AbortController();
    void loadSelectedTaskDetail({ signal: controller.signal });
    const intervalId = selectedTaskId ? window.setInterval(() => {
      void loadSelectedTaskDetail({ signal: controller.signal });
    }, selectedTaskDetail?.run.status === "cancelling" ? CANCELLATION_REFRESH_MS : AUTO_REFRESH_MS) : null;
    return () => {
      controller.abort();
      if (intervalId) window.clearInterval(intervalId);
    };
  }, [loadSelectedTaskDetail, selectedTaskDetail?.run.status, selectedTaskId]);

  useEffect(() => {
    const onHashChange = () => {
      const next = parseCrawlTaskRoute(window.location.hash);
      if (next.kind === "tasks") {
        setSelectedTaskId(next.taskId);
        setDetailView(next.view);
        setFilters((current) => JSON.stringify(current) === JSON.stringify(next.filters) ? current : next.filters);
        setPage(next.page);
        setActionState({ pending: null, error: null, notice: null });
      }
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const navigateTasks = useCallback((taskId, view, nextFilters = filters, nextPage = page) => {
    if (taskId !== selectedTaskId) {
      latestDetailRef.current += 1;
      setSelectedTaskDetail(null);
      setSelectedTaskDetailError(null);
      setCrawlQuality(null);
      setCrawlQualityError('');
    }
    setSelectedTaskId(taskId);
    setDetailView(view);
    setFilters(nextFilters);
    setPage(nextPage);
    window.location.hash = buildCrawlTaskRoute(taskId, view, { filters: nextFilters, page: nextPage });
    setActionState({ pending: null, error: null, notice: null });
  }, [filters, page, selectedTaskId]);

  const handleFilterChange = (field) => (event) => {
    navigateTasks(selectedTaskId, detailView, { ...filters, [field]: event.target.value }, 1);
  };

  const handleSelectTask = (crawlJobId) => navigateTasks(crawlJobId, null);

  const handleContinueCappedListing = useCallback(() => {
    createCappedListingDraft(selectedTaskDetail);
  }, [selectedTaskDetail]);

  const handleRecoveryChanged = useCallback(
    async () => {
      await Promise.all([
        loadTasks({ reason: "recovery" }),
        loadSelectedTaskDetail(),
      ]);
    },
    [loadSelectedTaskDetail, loadTasks],
  );

  const runTaskAction = useCallback(
    async (actionKey, actionLabel, action) => {
      if (!selectedTaskId) {
        return;
      }

      setActionState({ pending: actionKey, error: null, notice: null });

      try {
        await action();
        setActionState({
          pending: null,
          error: null,
          notice: `${actionLabel} requested for ${selectedTaskId}.`,
        });
        await loadTasks({ reason: actionKey });
        await loadSelectedTaskDetail();
        return true;
      } catch (actionError) {
        const detail = extractErrorMessage(
          actionError,
          `Failed to ${actionLabel.toLowerCase()}`,
        );
        setActionState({ pending: null, error: detail, notice: null });
        logError("crawl_tasks.action_failed", {
          action: actionKey,
          crawlJobId: selectedTaskId,
          detail,
        });
        return false;
      }
    },
    [loadSelectedTaskDetail, loadTasks, selectedTaskId],
  );

  const handleOpenEvents = () => navigateTasks(selectedTaskId, 'events');

  const handleNormalizedAction = useCallback((action, trigger) => {
    if (!selectedTaskId) return;
    if (action === "cancel") {
      dialogTriggerRef.current = trigger;
      setCancelDialogOpen(true);
    } else if (action === "resume_manual_action") {
      void runTaskAction("resume", "Resume manual action", () => resumeManualTask(selectedTaskId));
    }
  }, [runTaskAction, selectedTaskId]);

  const confirmCancellation = useCallback(async () => {
    const succeeded = await runTaskAction(
      "cancel",
      "Cancel crawl job",
      () => cancelCrawlJob(selectedTaskId),
    );
    if (succeeded) setCancelDialogOpen(false);
  }, [runTaskAction, selectedTaskId]);

  const handleCrawlQualityPreview = useCallback(async (limit) => {
    if (!selectedTaskId) return;
    setCrawlQualityPending('preview');
    setCrawlQualityError('');
    try {
      const preview = await previewCrawlQuality(selectedTaskId, limit);
      setCrawlQuality((current) => ({ ...(current || {}), preview }));
    } catch (qualityError) {
      setCrawlQualityError(extractErrorMessage(qualityError, 'Preview failed'));
    } finally {
      setCrawlQualityPending(null);
    }
  }, [selectedTaskId]);

  const handleCrawlQualityEvaluate = useCallback(async (limit) => {
    if (!selectedTaskId) return;
    setCrawlQualityPending('evaluate');
    setCrawlQualityError('');
    try {
      const latest = await evaluateCrawlQuality(selectedTaskId, limit);
      setCrawlQuality((current) => ({ ...(current || {}), latest }));
    } catch (qualityError) {
      setCrawlQualityError(extractErrorMessage(qualityError, 'Jev quality evaluation failed'));
    } finally {
      setCrawlQualityPending(null);
    }
  }, [selectedTaskId]);

  const handleIncidentTriagePreview = useCallback(async (eventLimit) => {
    setIncidentTriagePending('preview');
    setIncidentTriageError('');
    try {
      const preview = await previewIncidentTriage(eventLimit);
      setIncidentTriage((current) => ({ ...(current || {}), preview }));
    } catch (triageError) {
      setIncidentTriageError(extractErrorMessage(triageError, 'Incident preview failed'));
    } finally {
      setIncidentTriagePending(null);
    }
  }, []);

  const handleIncidentTriageEvaluate = useCallback(async (evaluationId) => {
    setIncidentTriagePending('evaluate');
    setIncidentTriageError('');
    try {
      const latest = await evaluateIncidentTriage(evaluationId);
      setIncidentTriage((current) => ({ ...(current || {}), latest }));
    } catch (triageError) {
      setIncidentTriageError(extractErrorMessage(triageError, 'Jev incident triage failed'));
    } finally {
      setIncidentTriagePending(null);
    }
  }, []);

  return (
    <section className="crawl-tasks-page">
      <header className="crawl-tasks-header">
        <div>
          <h1>Crawl Tasks</h1>
          <p className="form-hint">
            Track collection runs, inspect their progress, and resolve issues.
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
          onClick={() => { void loadTasks({ reason: "manual_refresh" }); void loadSelectedTaskDetail(); }}
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
          {tasks.length > 0 ? "Refresh failed; previously loaded tasks remain visible. " : ""}{error}
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
              {isLoading ? "Refreshing task list" : hasCancellingTask ? "Cancellation refresh every 1 sec" : "Auto refresh every 1 min"}
            </div>
          </div>

          {tasks.length === 0 ? (
            <div className="crawl-tasks-empty">
              {isLoading
                ? "Loading crawl tasks..."
                : error ? "Task list unavailable. Use Refresh to try again." : "No tasks match these filters."}
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
                        className={`crawl-task-status ${buildStatusClassName(task)}`}
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
              onClick={() => navigateTasks(selectedTaskId, detailView, filters, Math.max(1, page - 1))}
              disabled={page <= 1 || isLoading}
            >
              <ChevronLeft size={16} aria-hidden="true" />
              <span>Previous Page</span>
            </button>

            <button
              type="button"
              onClick={() =>
                navigateTasks(selectedTaskId, detailView, filters, Math.min(pageCount, page + 1))
              }
              disabled={page >= pageCount || isLoading}
            >
              <span>Next Page</span>
              <ChevronRight size={16} aria-hidden="true" />
            </button>
          </div>
        </section>

        <aside className="glass-panel crawl-tasks-detail">
          {selectedTaskId && !isLoading && !tasks.some((task) => task.crawl_job_id === selectedTaskId) && <p className="crawl-tasks-banner crawl-tasks-banner-warning">This task is outside the current list page or filters. Its details are loaded directly.</p>}
          {selectedTaskId && detailView === 'events' ? (
            <CrawlTaskEvents key={selectedTaskId} taskId={selectedTaskId} onBack={() => navigateTasks(selectedTaskId, null)} />
          ) : selectedTaskId ? (
            <CrawlTaskDetails
              detail={selectedTaskDetail?.run.id === selectedTaskId ? selectedTaskDetail : null}
              loading={selectedTaskDetailLoading}
              error={selectedTaskDetailError}
              actionState={actionState}
              onAction={handleNormalizedAction}
              onOpenEvents={handleOpenEvents}
              onContinueCappedListing={handleContinueCappedListing}
              onRecoveryChanged={handleRecoveryChanged}
              crawlQuality={crawlQuality}
              crawlQualityPending={crawlQualityPending}
              crawlQualityError={crawlQualityError}
              onCrawlQualityPreview={handleCrawlQualityPreview}
              onCrawlQualityEvaluate={handleCrawlQualityEvaluate}
            />
          ) : (
            <div className="crawl-tasks-empty">
              Select a task to inspect details and actions.
            </div>
          )}
        </aside>
      </div>
      <IncidentTriageAdvisory
        value={incidentTriage}
        pending={incidentTriagePending}
        error={incidentTriageError}
        onPreview={handleIncidentTriagePreview}
        onEvaluate={handleIncidentTriageEvaluate}
      />

      {cancelDialogOpen && (
        <ConfirmActionDialog
          title="Cancel this crawl?"
          summary="Committed work remains visible. Unfinished detail work returns to backend-owned later backlog after cancelled acknowledgement."
          confirmLabel="Request cancellation"
          pending={actionState.pending === "cancel"}
          error={actionState.error ? { message: actionState.error } : null}
          restoreFocusRef={dialogTriggerRef}
          onCancel={() => setCancelDialogOpen(false)}
          onConfirm={confirmCancellation}
        />
      )}
    </section>
  );
}
