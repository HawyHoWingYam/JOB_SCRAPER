import { useCallback, useEffect, useRef, useState } from 'react';

const RUN_POLL_INTERVAL_MS = 2000;

function hasCompanyAIDescription(company) {
  return Boolean(company?.ai_description?.trim());
}

export function isActiveRun(run) {
  return Boolean(run && ['pending', 'running'].includes(String(run.status || '').toLowerCase()));
}

export function isTerminalRun(run) {
  return Boolean(run && ['completed', 'completed_with_failures', 'failed'].includes(String(run.status || '').toLowerCase()));
}

export function isQueuedRun(run) {
  return Boolean(run && String(run.status || '').toLowerCase() === 'pending');
}

export function getRunProgress(run) {
  if (!run) {
    return { processed: 0, total: 0 };
  }

  const processed = Number(run.completed_items || 0) + Number(run.failed_items || 0);
  return {
    processed,
    total: Number(run.total_items || 0),
  };
}

function getProgressValue(progress) {
  if (!progress.total) {
    return 0;
  }

  const roundedValue = Math.round((progress.processed / progress.total) * 100);
  if (progress.processed > 0) {
    return Math.min(Math.max(roundedValue, 1), 100);
  }

  return roundedValue;
}

function reconcileRunItemsByCompanyId(run, runItemsByCompanyId) {
  if (!run) {
    return {};
  }

  const nextRunItemsByCompanyId = {};

  for (const [companyId, item] of Object.entries(runItemsByCompanyId || {})) {
    const itemStatus = String(item?.status || '').toLowerCase();
    if (isTerminalRun(run) && ['pending', 'running'].includes(itemStatus)) {
      continue;
    }

    nextRunItemsByCompanyId[companyId] = item;
  }

  return nextRunItemsByCompanyId;
}

export function getCompanyStatus(company, run, runItem) {
  const itemStatus = String(runItem?.status || '').toLowerCase();

  if (itemStatus === 'failed' && !hasCompanyAIDescription(company)) {
    return 'failed';
  }

  if (isTerminalRun(run)) {
    return hasCompanyAIDescription(company) ? 'ready' : 'pending';
  }

  if (itemStatus === 'pending' && !hasCompanyAIDescription(company)) {
    return 'queued';
  }
  if (itemStatus === 'running' && !hasCompanyAIDescription(company)) {
    return 'generating';
  }

  const currentCompanyId = `${run?.current_company_id || ''}`.trim();
  const companyId = `${company?.id || ''}`.trim();
  const matchesCurrentCompany = currentCompanyId
    ? currentCompanyId === companyId
    : run?.current_company_name === company.name;

  if (isActiveRun(run) && matchesCurrentCompany && !hasCompanyAIDescription(company)) {
    return 'generating';
  }

  return hasCompanyAIDescription(company) ? 'ready' : 'pending';
}

export function formatRunCompletionMessage(run) {
  const summary = `Finished generating descriptions for ${run.total_items} companies. ${run.completed_items} succeeded, ${run.failed_items} failed.`;
  if (run.error_message) {
    return `${summary} ${run.error_message}`;
  }
  return summary;
}

export function getRunStatusLabel(status) {
  const normalizedStatus = String(status || '').toLowerCase();

  if (normalizedStatus === 'completed') return 'Completed';
  if (normalizedStatus === 'completed_with_failures') return 'Completed With Failures';
  if (normalizedStatus === 'failed') return 'Failed';
  if (normalizedStatus === 'running') return 'Running';
  if (normalizedStatus === 'pending') return 'Pending';
  return 'Unknown';
}

export function getCompanyStatusLabel(status) {
  if (status === 'queued') return 'Queued';
  if (status === 'generating') return 'Generating';
  if (status === 'failed') return 'Failed';
  if (status === 'ready') return 'AI Ready';
  return 'Awaiting AI';
}

export function getCompanyDescriptionText(company, status, runItem) {
  if (status === 'queued') {
    return 'Queued for AI description generation.';
  }

  if (status === 'generating') {
    return 'Generating company description...';
  }

  if (status === 'failed') {
    return runItem?.error_message || company.ai_description || 'Description generation failed for this company.';
  }

  return company.ai_description || 'No AI description yet. Generate one for this company.';
}

function buildRunItemsByCompanyId(items) {
  const nextRunItemsByCompanyId = {};

  for (const item of items || []) {
    const companyId = `${item.company_id || ''}`.trim();
    if (!companyId) {
      continue;
    }

    nextRunItemsByCompanyId[companyId] = item;
  }

  return nextRunItemsByCompanyId;
}

export default function useCompanyEnrichmentRun({
  apiUrl,
  appliedQuery,
  statusFilter,
  page,
  loadCompanies,
}) {
  const [refreshError, setRefreshError] = useState(null);
  const [actionMessage, setActionMessage] = useState(null);
  const [currentRun, setCurrentRun] = useState(null);
  const [runItemsByCompanyId, setRunItemsByCompanyId] = useState({});
  const [isCreatingRun, setIsCreatingRun] = useState(false);
  const [isPageVisible, setIsPageVisible] = useState(() => {
    if (typeof document === 'undefined') {
      return true;
    }

    return !document.hidden;
  });
  const mountedRef = useRef(true);
  const wasPageVisibleRef = useRef(typeof document === 'undefined' ? true : !document.hidden);
  const currentRunIdRef = useRef(null);
  const runRefreshInFlightRef = useRef(null);
  const runRefreshQueuedRef = useRef(false);
  const latestLoadCompaniesRef = useRef({
    appliedQuery,
    statusFilter,
    page,
    loadCompanies,
  });

  const updateCurrentRun = useCallback((run) => {
    currentRunIdRef.current = run?.id || null;
    setCurrentRun(run);
  }, []);

  const loadRunItems = useCallback(async (runId) => {
    const response = await fetch(`${apiUrl}/api/v1/companies/enrichment-runs/${runId}/items`);
    if (!response.ok) {
      throw new Error('Failed to load company enrichment run items');
    }

    const payload = await response.json();
    return buildRunItemsByCompanyId(payload.items);
  }, [apiUrl]);

  const fetchRunById = useCallback(async (runId) => {
    const response = await fetch(`${apiUrl}/api/v1/companies/enrichment-runs/${runId}`);
    if (!response.ok) {
      throw new Error('Failed to refresh company enrichment run');
    }
    return response.json();
  }, [apiUrl]);

  const refreshCurrentRun = useCallback(async ({ runId = null, queueAfterInFlight = false } = {}) => {
    const targetRunId = runId || currentRunIdRef.current;
    if (!targetRunId) {
      return null;
    }

    if (runRefreshInFlightRef.current) {
      if (queueAfterInFlight) {
        runRefreshQueuedRef.current = true;
      }
      return runRefreshInFlightRef.current;
    }

    const refreshPromise = (async () => {
      const payload = await fetchRunById(targetRunId);
      if (!mountedRef.current) {
        return payload;
      }

      updateCurrentRun(payload);
      setRunItemsByCompanyId((previousRunItemsByCompanyId) => reconcileRunItemsByCompanyId(payload, previousRunItemsByCompanyId));
      setRefreshError(null);

      if (isTerminalRun(payload)) {
        const { appliedQuery: query, statusFilter: status, page: pageNumber, loadCompanies: reloadCompanies } = latestLoadCompaniesRef.current;
        setActionMessage(formatRunCompletionMessage(payload));
        await reloadCompanies({
          query,
          status,
          pageNumber,
        });
      }

      return payload;
    })();

    runRefreshInFlightRef.current = refreshPromise.finally(() => {
      runRefreshInFlightRef.current = null;
      if (runRefreshQueuedRef.current && mountedRef.current) {
        runRefreshQueuedRef.current = false;
        refreshCurrentRun({ runId: currentRunIdRef.current });
      }
    });

    return runRefreshInFlightRef.current;
  }, [fetchRunById, updateCurrentRun]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    latestLoadCompaniesRef.current = {
      appliedQuery,
      statusFilter,
      page,
      loadCompanies,
    };
  }, [appliedQuery, loadCompanies, page, statusFilter]);

  useEffect(() => {
    if (!currentRun?.id) {
      setRunItemsByCompanyId({});
      return undefined;
    }

    let cancelled = false;
    const run = currentRun;

    const refreshRunItems = async () => {
      try {
        const nextRunItemsByCompanyId = await loadRunItems(run.id);
        if (!cancelled && mountedRef.current) {
          setRunItemsByCompanyId(reconcileRunItemsByCompanyId(run, nextRunItemsByCompanyId));
        }
      } catch {
        if (!cancelled && mountedRef.current) {
          setRunItemsByCompanyId({});
        }
      }
    };

    refreshRunItems();

    return () => {
      cancelled = true;
    };
  }, [currentRun, loadRunItems]);

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

  useEffect(() => {
    const loadCurrentRun = async () => {
      try {
        const response = await fetch(`${apiUrl}/api/v1/companies/enrichment-runs/current`);
        if (!response.ok) {
          throw new Error('Failed to load company enrichment run');
        }

        const payload = await response.json();
        if (!mountedRef.current) {
          return;
        }

        updateCurrentRun(payload);
        setRefreshError(null);
      } catch (error) {
        if (mountedRef.current) {
          setRefreshError(error.message);
        }
      }
    };

    loadCurrentRun();
  }, [apiUrl, updateCurrentRun]);

  useEffect(() => {
    if (!isActiveRun(currentRun) || !isPageVisible) {
      return undefined;
    }

    let cancelled = false;
    let timeoutId;

    const poll = async () => {
      let shouldContinuePolling = true;

      try {
        const payload = await refreshCurrentRun({ runId: currentRun.id });
        if (cancelled) {
          return;
        }

        if (isTerminalRun(payload)) {
          shouldContinuePolling = false;
          return;
        }
      } catch (error) {
        if (!cancelled) {
          setRefreshError(`Refresh failed: ${error.message}`);
        }
      } finally {
        if (!cancelled && shouldContinuePolling) {
          timeoutId = window.setTimeout(poll, RUN_POLL_INTERVAL_MS);
        }
      }
    };

    timeoutId = window.setTimeout(poll, RUN_POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      if (timeoutId) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [currentRun, isPageVisible, refreshCurrentRun]);

  useEffect(() => {
    const wasPageVisible = wasPageVisibleRef.current;
    wasPageVisibleRef.current = isPageVisible;

    if (!isPageVisible || wasPageVisible || !isActiveRun(currentRun)) {
      return undefined;
    }

    let cancelled = false;

    const refreshNow = async () => {
      try {
        await refreshCurrentRun({
          runId: currentRun.id,
          queueAfterInFlight: true,
        });
      } catch (error) {
        if (!cancelled && mountedRef.current) {
          setRefreshError(`Refresh failed: ${error.message}`);
        }
      }
    };

    refreshNow();

    return () => {
      cancelled = true;
    };
  }, [currentRun, isPageVisible, refreshCurrentRun]);

  const createRun = async () => {
    setIsCreatingRun(true);
    setRefreshError(null);
    setActionMessage(null);

    try {
      const response = await fetch(`${apiUrl}/api/v1/companies/enrichment-runs`, {
        method: 'POST',
      });
      if (!response.ok) {
        throw new Error('Failed to start company enrichment run');
      }

      const payload = await response.json();
      if (payload?.status === 'empty' && payload?.run === null) {
        updateCurrentRun(null);
        setActionMessage('All companies already have AI descriptions.');
        return true;
      }

      const runPayload = payload.run || payload;
      updateCurrentRun(runPayload);
      setActionMessage('Global backlog run started.');

      if (isActiveRun(runPayload)) {
        try {
          await refreshCurrentRun({ runId: runPayload.id });
        } catch {
          // The polling loop will retry shortly; keep the optimistic run state.
        }
      }

      return true;
    } catch (error) {
      setRefreshError(error.message);
      return false;
    } finally {
      setIsCreatingRun(false);
    }
  };

  const getCompanyRunState = (company) => {
    const runItem = runItemsByCompanyId[company.id] || null;
    const status = getCompanyStatus(company, currentRun, runItem);

    return {
      runItem,
      status,
      statusLabel: getCompanyStatusLabel(status),
      descriptionText: getCompanyDescriptionText(company, status, runItem),
    };
  };

  const progress = getRunProgress(currentRun);
  const progressValue = getProgressValue(progress);
  const remainingCount = currentRun
    ? Math.max(Number(currentRun.pending_items || 0), 0)
    : 0;
  const hasActiveRun = isActiveRun(currentRun);
  const hasQueuedRun = isQueuedRun(currentRun);
  const hasTerminalRun = isTerminalRun(currentRun);
  const batchButtonLabel = hasActiveRun
    ? (hasQueuedRun ? 'Generation queued' : 'Generation in progress')
    : isCreatingRun
      ? 'Starting generation...'
      : 'Generate Missing Descriptions';
  const terminalMessage = hasTerminalRun ? formatRunCompletionMessage(currentRun) : null;

  return {
    currentRun,
    runItemsByCompanyId,
    refreshError,
    actionMessage,
    isCreatingRun,
    hasActiveRun,
    hasQueuedRun,
    hasTerminalRun,
    progress,
    progressValue,
    remainingCount,
    batchButtonLabel,
    terminalMessage,
    createRun,
    getCompanyRunState,
  };
}
