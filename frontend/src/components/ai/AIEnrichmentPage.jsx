import { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  Clock3,
  Copy,
  LoaderCircle,
  Orbit,
  RefreshCcw,
  Sparkles,
  Square,
} from 'lucide-react';
import { apiPath } from '../../api/base';
import { governanceHash } from '../jobIntelligence/governanceRoute';
import '../Dashboard.css';
import './AIEnrichmentPage.css';

const ACTIVE_RUN_STATUSES = new Set(['pending', 'running', 'stopping']);
const TERMINAL_RUN_STATUSES = new Set(['completed', 'completed_with_failures', 'completed_with_exclusions', 'failed', 'cancelled']);
const DEGRADED_PLACEHOLDER = 'Unavailable';
const REFRESH_REQUEST_TIMEOUT_MS = 8000;
const FILTER_PREVIEW_DEBOUNCE_MS = 350;
const FILTER_STORAGE_KEY = 'ai-enrichment-filtered-run:v2';
const LEGACY_FILTER_STORAGE_KEY = 'ai-enrichment-filtered-run:v1';
const DEFAULT_FILTER_STATE = {
  source_sites: [],
  source_classification_ids: [],
  source_subclassification_ids: [],
  posted_date_from: '',
  posted_date_to: '',
};

function normalizeRunStatus(value) {
  return String(value || '').toLowerCase();
}

function isActiveRun(run) {
  return ACTIVE_RUN_STATUSES.has(normalizeRunStatus(run?.status));
}

function isTerminalRun(run) {
  return TERMINAL_RUN_STATUSES.has(normalizeRunStatus(run?.status));
}

function governanceScope(filters = {}, pendingLimit, detail = {}) {
  const sourceId = detail.source_classification_id;
  const sourceSite = sourceId?.includes(':') ? sourceId.split(':', 1)[0] : null;
  const stableReason = /^[a-z0-9_]+$/.test(String(detail.reason || ''))
    ? detail.reason
    : null;
  return {
    ...filters,
    ...(sourceSite && !filters.source_sites?.length
      ? { source_sites: [sourceSite] }
      : {}),
    ...(stableReason ? { reason: stableReason } : {}),
    ...(detail.job_ids?.length ? { jobIds: detail.job_ids } : {}),
    ...(pendingLimit ? { pendingLimit } : {}),
  };
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

function formatPendingGateProgress(pendingGateProgress, { compact = false } = {}) {
  const emittedItems = Number(pendingGateProgress?.emitted_items);
  const settledItems = Number(pendingGateProgress?.settled_items);
  const hasEmittedItems = Number.isFinite(emittedItems) && emittedItems > 0;
  const hasSettledItems = Number.isFinite(settledItems) && settledItems >= 0;

  if (hasEmittedItems && hasSettledItems) {
    return compact
      ? `Ingest settled ${settledItems.toLocaleString()}/${emittedItems.toLocaleString()}`
      : `Ingest settled ${settledItems.toLocaleString()} of ${emittedItems.toLocaleString()} emitted items.`;
  }

  if (hasSettledItems && settledItems > 0) {
    return compact
      ? `Ingest settled ${settledItems.toLocaleString()}`
      : `Ingest settled ${settledItems.toLocaleString()} items so far.`;
  }

  return 'Ingest settle progress unavailable';
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
  const activeRun = (sortedRuns || []).find((run) => isActiveRun(run));
  const terminalRuns = (sortedRuns || []).filter((run) => isTerminalRun(run));
  if (activeRun) {
    return {
      hasActive: true,
      slots: [activeRun, terminalRuns[0] || null],
    };
  }

  return {
    hasActive: false,
    slots: [terminalRuns[0] || null, terminalRuns[1] || null],
  };
}

function getRunStatusTone(status) {
  const normalized = normalizeRunStatus(status);
  if (ACTIVE_RUN_STATUSES.has(normalized)) {
    return 'active';
  }
  if (normalized === 'completed') {
    return 'success';
  }
  if (normalized === 'completed_with_failures') {
    return 'warning';
  }
  if (normalized === 'completed_with_exclusions') {
    return 'warning';
  }
  if (normalized === 'failed') {
    return 'danger';
  }
  return 'muted';
}

function loadPersistedFilters() {
  try {
    const current = window.localStorage.getItem(FILTER_STORAGE_KEY);
    const legacy = current ? null : window.localStorage.getItem(LEGACY_FILTER_STORAGE_KEY);
    const parsed = JSON.parse(current || legacy || 'null');
    const filters = parsed?.filters;
    const limit = Number(parsed?.limit);
    if (!filters || !Number.isInteger(limit) || limit < 1 || limit > 5000) {
      return { filters: DEFAULT_FILTER_STATE, limit: '50' };
    }
    const persistedFilters = {
      filters: {
        ...DEFAULT_FILTER_STATE,
        ...Object.fromEntries(
          Object.keys(DEFAULT_FILTER_STATE).map((key) => [
            key,
            Array.isArray(DEFAULT_FILTER_STATE[key])
              ? (Array.isArray(filters[key])
                ? filters[key].filter((item) => typeof item === 'string')
                : [])
              : (typeof filters[key] === 'string' ? filters[key] : ''),
          ]),
        ),
      },
      limit: String(limit),
    };
    if (legacy) {
      // v1 stored unqualified display names. Keep only fields whose identity is
      // still unambiguous and let the operator reselect source-qualified paths.
      persistedFilters.filters.source_classification_ids = [];
      persistedFilters.filters.source_subclassification_ids = [];
      persistedFilters.migratedLegacyStorage = true;
    }
    return persistedFilters;
  } catch {
    return { filters: DEFAULT_FILTER_STATE, limit: '50' };
  }
}

function hasOrdinaryFilters(filters) {
  return Boolean(
    filters.source_sites.length
    || filters.source_classification_ids.length
    || filters.source_subclassification_ids.length
    || filters.posted_date_from
    || filters.posted_date_to,
  );
}

function SearchableMultiSelect({ label, options, values, onChange }) {
  const [search, setSearch] = useState('');
  const normalizedOptions = options.map((option) => (
    typeof option === 'string'
      ? { value: option, label: option }
      : option
  ));
  const visibleOptions = normalizedOptions.filter((option) => (
    option.label.toLowerCase().includes(search.toLowerCase())
  ));

  return (
    <fieldset className="ai-multi-select">
      <legend>{label}</legend>
      <input
        aria-label={`Search ${label}`}
        type="search"
        placeholder={`Search ${label.toLowerCase()}`}
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      <div className="ai-multi-options">
        {visibleOptions.length === 0 && <span className="ai-empty-option">No options</span>}
        {visibleOptions.map((option) => (
          <label key={option.value}>
            <input
              type="checkbox"
              checked={values.includes(option.value)}
              onChange={() => onChange(
                values.includes(option.value)
                  ? values.filter((value) => value !== option.value)
                  : [...values, option.value],
              )}
            />
            <span>{option.label}</span>
          </label>
        ))}
      </div>
      {values.length > 0 && <small>{values.length} selected</small>}
    </fieldset>
  );
}

function describeActiveRunFocus({
  status,
  inProgressItems,
  latestStartedJobTitle,
  startedMs,
  pendingGateReason,
  pendingGateProgress,
}) {
  const normalizedStatus = normalizeRunStatus(status);

  if (normalizedStatus === 'stopping') {
    return {
      label: 'Stop status',
      value: 'Stopping after in-flight jobs',
      detail: 'No new jobs will start.',
    };
  }

  if (inProgressItems > 0) {
    return {
      label: 'Jobs in progress',
      value: `${inProgressItems} jobs in progress`,
      detail: `Latest title: ${latestStartedJobTitle}`,
    };
  }

  if (normalizedStatus === 'pending') {
    if (pendingGateReason === 'waiting_for_ingest_settle') {
      return {
        label: 'Queue status',
        value: 'Waiting for ingest settle',
        detail: formatPendingGateProgress(pendingGateProgress),
      };
    }

    if (pendingGateReason === 'waiting_for_crawl_completion') {
      return {
        label: 'Queue status',
        value: 'Waiting for crawl completion',
        detail: 'This run will queue after the linked crawl reaches a terminal state.',
      };
    }

    if (pendingGateReason === 'waiting_for_ai_runtime') {
      return {
        label: 'Queue status',
        value: 'Waiting for AI runtime',
        detail: 'The jobs AI profile must become ready before execution can start.',
      };
    }

    return {
      label: 'Queue status',
      value: 'Queued for execution',
      detail: startedMs === null
        ? 'Latest title will appear after the first item starts.'
        : `Latest title: ${latestStartedJobTitle}`,
    };
  }

  return {
    label: 'Jobs in progress',
    value: 'Waiting for next item to start',
    detail: `Latest title: ${latestStartedJobTitle}`,
  };
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

export default function AIEnrichmentPage() {
  const persistedFilters = useRef(loadPersistedFilters()).current;
  const [overview, setOverview] = useState(null);
  const [hasLoadedOverview, setHasLoadedOverview] = useState(false);
  const [runs, setRuns] = useState([]);
  const [hasLoadedRuns, setHasLoadedRuns] = useState(false);
  const [pendingLimit, setPendingLimit] = useState(persistedFilters.limit);
  const [filters, setFilters] = useState(persistedFilters.filters);
  const [filterHierarchy, setFilterHierarchy] = useState([]);
  const [filterOptionsError, setFilterOptionsError] = useState(null);
  const [allPendingAcknowledged, setAllPendingAcknowledged] = useState(false);
  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [refreshError, setRefreshError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [actionMessage, setActionMessage] = useState(null);
  const [isPageVisible, setIsPageVisible] = useState(() => {
    if (typeof document === 'undefined') {
      return true;
    }

    return !document.hidden;
  });
  const hasConsoleData = hasLoadedOverview || hasLoadedRuns;
  const hasConsoleDataRef = useRef(false);
  const refreshInFlightRef = useRef(null);
  const refreshQueuedRef = useRef(false);
  const mountedRef = useRef(true);
  const wasPageVisibleRef = useRef(typeof document === 'undefined' ? true : !document.hidden);
  const previewControllerRef = useRef(null);
  const skipNextPersistRef = useRef(false);
  const sortedRuns = sortRunsNewestFirst(runs);
  const overviewPendingJobs = Number(overview?.pending_jobs || 0);
  const overviewAiEligibleJobs = Number(overview?.ai_eligible_jobs || 0);
  const overviewFailedJobs = Number(overview?.failed_jobs ?? overview?.failed_items ?? 0);
  const visibleActiveRunsCount = sortedRuns.filter((run) => isActiveRun(run)).length;
  const overviewActiveRunsCount = Number(overview?.active_runs ?? overview?.running_runs ?? 0);
  const isBootstrapPolling = hasConsoleData && (!hasLoadedOverview || !hasLoadedRuns);
  const shouldPollRuns = isBootstrapPolling || overviewActiveRunsCount > 0 || (!hasLoadedOverview && visibleActiveRunsCount > 0);
  const pendingJobsDisplay = hasLoadedOverview ? overviewPendingJobs : DEGRADED_PLACEHOLDER;
  const eligibleJobsDisplay = hasLoadedOverview ? overviewAiEligibleJobs : DEGRADED_PLACEHOLDER;
  const failedJobsDisplay = hasLoadedOverview ? overviewFailedJobs : DEGRADED_PLACEHOLDER;
  const activeRunsDisplay = hasLoadedOverview ? overviewActiveRunsCount : DEGRADED_PLACEHOLDER;
  const pendingEligibleDisplay = hasLoadedOverview
    ? `${overviewPendingJobs.toLocaleString()} / ${overviewAiEligibleJobs.toLocaleString()}`
    : `${pendingJobsDisplay} / ${eligibleJobsDisplay}`;
  const { hasActive: monitorHasActive, slots: monitorSlots } = resolveMonitorSlots(sortedRuns);
  const activeRun = monitorSlots.find((run) => isActiveRun(run)) || null;
  const ordinaryFiltersSelected = hasOrdinaryFilters(filters);
  const normalizedLimit = Math.min(5000, Math.max(1, Number(pendingLimit) || 1));
  const canPreview = ordinaryFiltersSelected || allPendingAcknowledged;
  const canLaunch = !submitting
    && !activeRun
    && !previewLoading
    && !previewError
    && Number(preview?.effective_item_count || 0) > 0;
  const sourceOptions = filterHierarchy.map((source) => source.source_site);
  const selectedSources = filters.source_sites.length > 0
    ? filterHierarchy.filter((source) => filters.source_sites.includes(source.source_site))
    : filterHierarchy;
  const classificationOptions = selectedSources.flatMap((source) => (
    (source.classifications || [])
      .filter((item) => item.id && item.name)
      .map((item) => ({
        value: item.id,
        label: `${source.source_site} · ${item.name} (${item.id})`,
      }))
  )).sort((left, right) => left.label.localeCompare(right.label));
  const subclassificationOptions = selectedSources.flatMap((source) => (
    (source.classifications || [])
      .filter((item) => filters.source_classification_ids.length === 0
        || filters.source_classification_ids.includes(item.id))
      .flatMap((item) => (item.subclassification_options || []).map((option) => ({
        value: option.id,
        label: `${source.source_site} · ${option.breadcrumb || option.name} (${option.id})`,
      })))
  )).sort((left, right) => left.label.localeCompare(right.label));

  useEffect(() => {
    hasConsoleDataRef.current = hasConsoleData;
  }, [hasConsoleData]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (skipNextPersistRef.current) {
      skipNextPersistRef.current = false;
      return;
    }
    try {
      window.localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify({
        filters,
        limit: normalizedLimit,
      }));
      if (persistedFilters.migratedLegacyStorage) {
        window.localStorage.removeItem(LEGACY_FILTER_STORAGE_KEY);
      }
    } catch {
      // Storage is a convenience; private mode or quota errors must not block operations.
    }
  }, [filters, normalizedLimit, persistedFilters.migratedLegacyStorage]);

  useEffect(() => {
    let cancelled = false;
    fetch(apiPath('/ai/pending/filter-options'))
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Filter options request failed with ${response.status}`);
        }
        return response.json();
      })
      .then((payload) => {
        if (!cancelled) {
          setFilterHierarchy(Array.isArray(payload.sources) ? payload.sources : []);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setFilterOptionsError(error.message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    previewControllerRef.current?.abort();
    if (!canPreview) {
      setPreview(null);
      setPreviewLoading(false);
      setPreviewError(null);
      return undefined;
    }

    const controller = new AbortController();
    previewControllerRef.current = controller;
    setPreviewLoading(true);
    setPreviewError(null);
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(apiPath('/ai/pending/preview'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: controller.signal,
          body: JSON.stringify({
            filters: {
              ...filters,
              posted_date_from: filters.posted_date_from || null,
              posted_date_to: filters.posted_date_to || null,
            },
            limit: normalizedLimit,
            all_pending_acknowledged: allPendingAcknowledged,
          }),
        });
        if (!response.ok) {
          throw new Error(`Preview request failed with ${response.status}`);
        }
        const payload = await response.json();
        if (!controller.signal.aborted) {
          setPreview(payload);
          setPreviewLoading(false);
        }
      } catch (error) {
        if (error.name !== 'AbortError' && !controller.signal.aborted) {
          setPreviewError(error.message);
          setPreviewLoading(false);
        }
      }
    }, FILTER_PREVIEW_DEBOUNCE_MS);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [allPendingAcknowledged, canPreview, filters, normalizedLimit]);

  useEffect(() => {
    if (typeof document === 'undefined') {
      return undefined;
    }

    const handleVisibilityChange = () => {
      setIsPageVisible(!document.hidden);
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, []);

  const fetchAIConsole = useCallback(async ({ queueAfterInFlight = false } = {}) => {
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

        const overviewTask = withRequestTimeout(
          fetch(apiPath('/ai/overview')).then(async (response) => {
            if (!response.ok) {
              throw new Error(`Overview request failed with ${response.status}`);
            }
            return response.json();
          }),
          'Overview',
        );

        const runsTask = withRequestTimeout(
          fetch(apiPath('/ai/runs?monitor=true')).then(async (response) => {
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
  }, []);

  useEffect(() => {
    fetchAIConsole();
  }, [fetchAIConsole]);

  useEffect(() => {
    const wasPageVisible = wasPageVisibleRef.current;
    wasPageVisibleRef.current = isPageVisible;

    if (!isPageVisible || wasPageVisible || loading || !hasConsoleData || !shouldPollRuns) {
      return;
    }

    fetchAIConsole({ queueAfterInFlight: true });
  }, [fetchAIConsole, hasConsoleData, isPageVisible, loading, shouldPollRuns]);

  useEffect(() => {
    if (loading || !hasConsoleData || !shouldPollRuns || !isPageVisible) {
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
  }, [fetchAIConsole, hasConsoleData, isPageVisible, loading, shouldPollRuns]);

  async function runPendingEnrichment() {
    if (!ordinaryFiltersSelected && !allPendingAcknowledged) {
      setActionError('Select at least one filter or acknowledge all pending jobs.');
      return;
    }
    if (!ordinaryFiltersSelected && !window.confirm('Run the oldest pending jobs across every source and classification?')) {
      return;
    }

    try {
      setSubmitting(true);
      setActionError(null);
      setActionMessage(null);
      setPendingLimit(String(normalizedLimit));

      const response = await fetch(apiPath('/ai/runs'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          mode: 'pending',
          limit: normalizedLimit,
          filters: {
            ...filters,
            posted_date_from: filters.posted_date_from || null,
            posted_date_to: filters.posted_date_to || null,
          },
          all_pending_acknowledged: allPendingAcknowledged,
        }),
      });

      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        if (response.status === 409 && payload?.detail?.code === 'active_run_exists') {
          throw new Error(`Another run is active: ${payload.detail.run_id}`);
        }
        throw new Error(`Run request failed with ${response.status}`);
      }

      setAllPendingAcknowledged(false);
      const payload = await response.json();
      const excludedCount = Number(payload?.excluded_items || preview?.excluded_item_count || 0);
      const selectedCount = Number(payload?.total_items || preview?.selected_item_count || normalizedLimit);
      const effectiveCount = Number(
        preview?.effective_item_count ?? Math.max(selectedCount - excludedCount, 0),
      );
      setActionMessage(
        excludedCount > 0
          ? `Filtered run submitted for ${effectiveCount.toLocaleString()} jobs; ${excludedCount.toLocaleString()} excluded by taxonomy.`
          : `Filtered run submitted for ${effectiveCount.toLocaleString()} jobs.`,
      );
      fetchAIConsole({ queueAfterInFlight: true });
    } catch (err) {
      setActionError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function retryFailedItems(run) {
    if (!run) {
      return;
    }

    try {
      setSubmitting(true);
      setActionError(null);
      setActionMessage(null);

      const response = await fetch(apiPath('/ai/runs/' + run.id + '/retry-failed'), {
        method: 'POST',
      });

      if (!response.ok) {
        throw new Error(`Retry request failed with ${response.status}`);
      }

      setActionMessage(`Retry run created from ${run.id}.`);
      fetchAIConsole({ queueAfterInFlight: true });
    } catch (err) {
      setActionError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function stopRun(run) {
    if (!window.confirm('Stop this run? Jobs already in flight may still finish and be saved.')) {
      return;
    }
    try {
      setSubmitting(true);
      setActionError(null);
      const response = await fetch(apiPath(`/ai/runs/${run.id}/stop`), { method: 'POST' });
      if (!response.ok) {
        throw new Error(`Stop request failed with ${response.status}`);
      }
      setActionMessage(`Stop requested for ${run.id}.`);
      fetchAIConsole({ queueAfterInFlight: true });
    } catch (error) {
      setActionError(error.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function copyRunId(runId) {
    try {
      await window.navigator.clipboard?.writeText?.(runId);
      setActionMessage(`Copied run UUID ${runId}.`);
    } catch {
      setActionError('Unable to copy the run UUID.');
    }
  }

  function resetFilters() {
    skipNextPersistRef.current = true;
    setFilters(DEFAULT_FILTER_STATE);
    setPendingLimit('50');
    setAllPendingAcknowledged(false);
    setPreview(null);
    try {
      window.localStorage.removeItem(FILTER_STORAGE_KEY);
      window.localStorage.removeItem(LEGACY_FILTER_STORAGE_KEY);
    } catch {
      // Ignore unavailable storage; in-memory controls are already reset.
    }
  }

  function updateSources(sourceSites) {
    const relevantSources = sourceSites.length > 0
      ? filterHierarchy.filter((source) => sourceSites.includes(source.source_site))
      : filterHierarchy;
    const allowedClassifications = new Set(
      relevantSources.flatMap((source) => (
        (source.classifications || []).map((item) => item.id).filter(Boolean)
      )),
    );
    const allowedSubclassifications = new Set(
      relevantSources.flatMap((source) => (source.classifications || []).flatMap(
        (item) => (item.subclassification_options || []).map((option) => option.id),
      )),
    );
    setFilters((current) => ({
      ...current,
      source_sites: sourceSites,
      source_classification_ids: current.source_classification_ids.filter((value) => allowedClassifications.has(value)),
      source_subclassification_ids: current.source_subclassification_ids.filter((value) => allowedSubclassifications.has(value)),
    }));
  }

  function updateClassifications(classifications) {
    const allowedSubclassifications = new Set(
      selectedSources.flatMap((source) => (source.classifications || [])
        .filter((item) => classifications.length === 0 || classifications.includes(item.id))
        .flatMap((item) => (
          (item.subclassification_options || []).map((option) => option.id)
        ))),
    );
    setFilters((current) => ({
      ...current,
      source_classification_ids: classifications,
      source_subclassification_ids: current.source_subclassification_ids.filter((value) => allowedSubclassifications.has(value)),
    }));
  }

  return (
    <section className="dashboard-container">
      <header className="dashboard-header">
        <div>
          <h2>AI Enrichment</h2>
          <p className="subtitle">
            Monitor enrichment runs and launch an oldest-first filtered batch.
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
          <div className="ai-metric-strip glass-panel" aria-label="AI enrichment summary">
            <div><BrainCircuit size={18} /><span>Pending / eligible</span><strong>{pendingEligibleDisplay}</strong></div>
            <div><Orbit size={18} /><span>Active runs</span><strong>{activeRunsDisplay}</strong></div>
            <div><AlertTriangle size={18} /><span>Failed jobs</span><strong>{failedJobsDisplay}</strong></div>
          </div>

          <div className="ai-console-grid">
            <section className="chart-wrapper glass-panel ai-console-panel ai-filter-panel">
              <div className="ai-console-header">
                <div>
                  <h3>Filtered Run</h3>
                  <p className="ai-console-copy">
                    Select a slice of the pending queue. Jobs launch oldest first.
                  </p>
                </div>
              </div>

              <div className="ai-filter-grid">
                <SearchableMultiSelect
                  label="Sources"
                  options={sourceOptions}
                  values={filters.source_sites}
                  onChange={updateSources}
                />
                <SearchableMultiSelect
                  label="Source Classifications"
                  options={classificationOptions}
                  values={filters.source_classification_ids}
                  onChange={updateClassifications}
                />
                <SearchableMultiSelect
                  label="Source Subclassifications"
                  options={subclassificationOptions}
                  values={filters.source_subclassification_ids}
                  onChange={(value) => setFilters((current) => ({ ...current, source_subclassification_ids: value }))}
                />
              </div>

              {persistedFilters.migratedLegacyStorage && (
                <div className="ai-status-banner ai-status-warning" role="status">
                  Saved name-based Source Classification filters were cleared because
                  duplicate labels cannot be migrated safely. Reselect source-qualified paths.
                </div>
              )}
              {filterOptionsError && <div className="ai-status-banner ai-status-error">{filterOptionsError}</div>}

              <div className="ai-date-limit-grid">
                <label className="ai-input-group" htmlFor="posted-date-from">
                  <span>Posted from</span>
                  <input id="posted-date-from" type="date" value={filters.posted_date_from} onChange={(event) => setFilters((current) => ({ ...current, posted_date_from: event.target.value }))} />
                </label>
                <label className="ai-input-group" htmlFor="posted-date-to">
                  <span>Posted to</span>
                  <input id="posted-date-to" type="date" value={filters.posted_date_to} onChange={(event) => setFilters((current) => ({ ...current, posted_date_to: event.target.value }))} />
                </label>
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
              </div>

              {!ordinaryFiltersSelected && (
                <label className="ai-all-pending-check">
                  <input type="checkbox" checked={allPendingAcknowledged} onChange={(event) => setAllPendingAcknowledged(event.target.checked)} />
                  <span>I understand this will select from all pending AI-eligible jobs.</span>
                </label>
              )}

              <div className="ai-preview-summary" aria-live="polite">
                {previewLoading
                  ? 'Calculating preview…'
                  : previewError
                    ? previewError
                    : preview
                      ? `${Number(preview.matching_pending_count || 0).toLocaleString()} match · ${Number(preview.effective_item_count || 0).toLocaleString()} will run${Number(preview.excluded_item_count || 0) > 0 ? ` · ${Number(preview.excluded_item_count).toLocaleString()} excluded` : ''}`
                      : 'Choose filters to preview the run.'}
              </div>

              {Number(preview?.excluded_item_count || 0) > 0 && (
                <div className="ai-exclusion-panel" data-testid="pending-exclusion-details">
                  <strong>{Number(preview.excluded_item_count).toLocaleString()} jobs will be excluded before execution.</strong>
                  <ul>
                    {(preview.excluded_items || []).map((detail) => (
                      <li key={`${detail.source_classification_id || 'missing'}-${detail.reason}`}>
                        <span>
                          {detail.source_classification_name || 'Unnamed source category'}
                          {detail.source_classification_id ? ` (${detail.source_classification_id})` : ''}
                          {' · '}{Number(detail.count || 0).toLocaleString()} jobs
                        </span>
                        <small>{detail.reason || 'Unsupported source taxonomy'}</small>
                      </li>
                    ))}
                  </ul>
                  {(preview.excluded_items || []).map((detail) => (
                    <a
                      key={`review-${detail.reason}-${detail.source_classification_id || 'unknown'}`}
                      className="ai-governance-link"
                      href={governanceHash('job-taxonomy', null, governanceScope(filters, normalizedLimit, detail))}
                    >
                      Review {Number(detail.count || 0).toLocaleString()} excluded jobs
                    </a>
                  ))}
                </div>
              )}

              <div className="ai-actions-row">
                <button type="button" className="ai-primary-button" disabled={!canLaunch} onClick={runPendingEnrichment}>
                  <Sparkles size={16} />
                  <span>Run {Number(preview?.effective_item_count || 0).toLocaleString()} filtered jobs</span>
                </button>
                <button type="button" className="ai-secondary-button" disabled={submitting} onClick={resetFilters}>
                  <RefreshCcw size={16} />
                  <span>Reset</span>
                </button>
              </div>

              {actionMessage && <div className="ai-status-banner ai-status-success">{actionMessage}</div>}
              {actionError && <div className="ai-status-banner ai-status-error">{actionError}</div>}
            </section>

            <section className="chart-wrapper glass-panel ai-console-panel ai-monitor-panel">
              <div className="ai-console-header">
                <div>
                  <h3>Run Monitor</h3>
                  <p className="ai-console-copy">
                    Active plus latest terminal, or the latest two terminal runs.
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

                  const processedItems = Number(run.completed_items || 0)
                    + Number(run.failed_items || 0)
                    + Number(run.cancelled_items || 0)
                    + Number(run.excluded_items || 0);
                  const totalItems = Number(run.total_items || 0);
                  const remainingItems = Number.isFinite(Number(run.pending_items))
                    ? Number(run.pending_items)
                    : Math.max(0, totalItems - processedItems);
                  const normalizedStatus = normalizeRunStatus(run.status);
                  const statusTone = getRunStatusTone(normalizedStatus);
                  const active = isActiveRun(run);
                  const excludedItems = Number(run.excluded_items || 0);
                  const excludedDetails = Array.isArray(run.excluded_details) ? run.excluded_details : [];
                  const inProgressItems = Number.isFinite(Number(run.in_progress_items))
                    ? Number(run.in_progress_items)
                    : (active ? Math.max(0, totalItems - remainingItems - processedItems) : 0);
                  const latestStartedJobTitle = run.latest_started_job_title || run.current_job_title || 'Latest title unavailable yet';
                  const progressValue = totalItems ? Math.round((processedItems / totalItems) * 100) : 0;

                  const startedMs = parseDateMs(run.started_at);
                  const completedMs = parseDateMs(run.completed_at);
                  const completedIso = formatTimestampIso(run.completed_at);
                  const createdIso = formatTimestampIso(run.created_at);
                  const durationSeconds =
                    startedMs !== null && completedMs !== null ? Math.max(0, (completedMs - startedMs) / 1000) : null;
                  const activeRunFocus = describeActiveRunFocus({
                    status: run.status,
                    inProgressItems,
                    latestStartedJobTitle,
                    startedMs,
                    pendingGateReason: run.pending_gate_reason,
                    pendingGateProgress: run.pending_gate_progress,
                  });
                  const isQueuedPendingRun = normalizedStatus === 'pending' && startedMs === null;

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
                          <div className="ai-run-id-row">
                            <span className="ai-run-id">{run.id}</span>
                            <button type="button" className="ai-icon-button" aria-label={`Copy run UUID ${run.id}`} onClick={() => copyRunId(run.id)}>
                              <Copy size={14} />
                            </button>
                          </div>
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
                        <span><Square size={14} /> Cancelled {Number(run.cancelled_items || 0)}</span>
                        <span>Excluded {excludedItems}</span>
                        <span>Remaining {remainingItems}</span>
                      </div>

                      {active && (
                        <div className="ai-run-focus">
                          <span className="ai-run-focus-label">{activeRunFocus.label}</span>
                          <strong className="ai-run-focus-value">{activeRunFocus.value}</strong>
                          <span className="ai-run-focus-detail">{activeRunFocus.detail}</span>
                        </div>
                      )}

                      {active ? (
                        <div className="ai-run-summary ai-run-summary-live">
                          <div className="ai-run-summary-title">
                            {isQueuedPendingRun ? 'Queued summary' : 'Live summary'}
                          </div>
                          <div className="ai-run-summary-body">
                            <span>{isQueuedPendingRun
                              ? run.pending_gate_reason === 'waiting_for_ingest_settle'
                                ? formatPendingGateProgress(run.pending_gate_progress, { compact: true })
                                : `Queued at ${createdIso || '-'}`
                              : `Elapsed ${startedMs === null ? '-' : formatDurationShort((Date.now() - startedMs) / 1000)}`
                            }</span>
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
                      ) : normalizedStatus === 'completed_with_exclusions' ? (
                        <div className="ai-run-summary ai-run-summary-terminal">
                          <div className="ai-run-summary-title">Completed with exclusions</div>
                          <div className="ai-run-summary-body ai-run-summary-stack">
                            <span>Succeeded {Number(run.completed_items || 0)}</span>
                            <span>Excluded {excludedItems}</span>
                            <span>Completed at {completedIso || '-'}</span>
                            <span>
                              Duration {durationSeconds === null ? '-' : formatDurationShort(durationSeconds)}
                            </span>
                          </div>
                        </div>
                      ) : normalizedStatus === 'cancelled' ? (
                        <div className="ai-run-summary ai-run-summary-terminal">
                          <div className="ai-run-summary-title">Cancelled summary</div>
                          <div className="ai-run-summary-body ai-run-summary-stack">
                            <span>Succeeded {Number(run.completed_items || 0)}</span>
                            <span>Failed {Number(run.failed_items || 0)}</span>
                            <span>Cancelled {Number(run.cancelled_items || 0)}</span>
                          </div>
                        </div>
                      ) : (
                        <div className="ai-run-summary ai-run-summary-terminal">
                          <div className="ai-run-summary-title">Failure summary</div>
                          <div className="ai-run-summary-body ai-run-summary-stack">
                            <span>Failure count {Number(run.failed_items || 0)}</span>
                            {excludedItems > 0 && <span>Excluded {excludedItems}</span>}
                            {run.last_failed_job_title && (
                              <span>Last failed {run.last_failed_job_title}</span>
                            )}
                            {run.error_message && (
                              <span>{run.error_message}</span>
                            )}
                          </div>
                        </div>
                      )}

                      {excludedDetails.length > 0 && (
                        <div className="ai-run-summary ai-exclusion-panel" data-testid="run-exclusion-details">
                          <div className="ai-run-summary-title">Excluded by taxonomy</div>
                          <ul>
                            {excludedDetails.map((detail, detailIndex) => (
                              <li key={`${detail.source_classification_id || 'missing'}-${detail.reason || 'reason'}-${detailIndex}`}>
                                <span>
                                  {detail.source_classification_name || 'Unnamed source category'}
                                  {detail.source_classification_id ? ` (${detail.source_classification_id})` : ''}
                                  {' · '}{Number(detail.count || 0).toLocaleString()} jobs
                                </span>
                                <small>{detail.reason || 'Unsupported source taxonomy'}</small>
                              </li>
                            ))}
                          </ul>
                          {excludedDetails.map((detail) => (
                            <a
                              key={`run-review-${detail.reason || 'reason'}-${detail.source_classification_id || 'unknown'}`}
                              className="ai-governance-link"
                              href={governanceHash('job-taxonomy', null, governanceScope({}, run.pending_limit, detail))}
                            >
                              Review {Number(detail.count || 0).toLocaleString()} excluded jobs
                            </a>
                          ))}
                        </div>
                      )}

                      <div className="ai-run-actions">
                        {active && normalizeRunStatus(run.status) !== 'stopping' && (
                          <button type="button" className="ai-secondary-button" disabled={submitting} onClick={() => stopRun(run)}>
                            <Square size={14} /> Stop
                          </button>
                        )}
                        {normalizeRunStatus(run.status) === 'stopping' && (
                          <button type="button" className="ai-secondary-button" disabled>
                            <LoaderCircle className="spinner" size={14} /> Stopping
                          </button>
                        )}
                        {isRetryableTerminalRun(run) && (
                          <button type="button" className="ai-secondary-button" disabled={submitting || Boolean(activeRun)} onClick={() => retryFailedItems(run)}>
                            <RefreshCcw size={14} /> Retry failed jobs ({Number(run.failed_items || 0)})
                          </button>
                        )}
                      </div>
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
