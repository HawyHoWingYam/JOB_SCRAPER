import React, { useEffect, useRef, useState } from 'react';
import { Sparkles } from 'lucide-react';
import CompanyDetailModal from './CompanyDetailModal';
import CompanySummaryCard from './CompanySummaryCard';
import { API_BASE_URL } from '../../api/base';
import './CompaniesPage.css';

const API_URL = API_BASE_URL;
const PAGE_SIZE = 25;
const RUN_POLL_INTERVAL_MS = 2000;

function hasCompanyAIDescription(company) {
  return Boolean(company?.ai_description?.trim());
}

function isActiveRun(run) {
  return Boolean(run && ['pending', 'running'].includes(String(run.status || '').toLowerCase()));
}

function isTerminalRun(run) {
  return Boolean(run && ['completed', 'completed_with_failures', 'failed'].includes(String(run.status || '').toLowerCase()));
}

function getRunProgress(run) {
  if (!run) {
    return { processed: 0, total: 0 };
  }

  const processed = Number(run.completed_items || 0) + Number(run.failed_items || 0);
  return {
    processed,
    total: Number(run.total_items || 0),
  };
}

function getCompanyStatus(company, run) {
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

function formatRunCompletionMessage(run) {
  const summary = `Finished generating descriptions for ${run.total_items} companies. ${run.completed_items} succeeded, ${run.failed_items} failed.`;
  if (run.error_message) {
    return `${summary} ${run.error_message}`;
  }
  return summary;
}

function getCompanyStatusLabel(status) {
  if (status === 'generating') return 'Generating';
  if (status === 'failed') return 'Failed';
  if (status === 'ready') return 'AI Ready';
  return 'Awaiting AI';
}

function getCompanyDescriptionText(company, status) {
  if (status === 'generating') {
    return 'Generating company description...';
  }

  if (status === 'failed') {
    return company.ai_description || 'Description generation failed for this company.';
  }

  return company.ai_description || 'No AI description yet. Generate one for this company.';
}

function CompaniesPage() {
  const [companies, setCompanies] = useState([]);
  const [searchInput, setSearchInput] = useState('');
  const [appliedQuery, setAppliedQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('pending');
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [refreshError, setRefreshError] = useState(null);
  const [actionMessage, setActionMessage] = useState(null);
  const [currentRun, setCurrentRun] = useState(null);
  const [isCreatingRun, setIsCreatingRun] = useState(false);
  const [selectedCompanyId, setSelectedCompanyId] = useState(null);
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

  const selectedCompany = companies.find((company) => company.id === selectedCompanyId) || null;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    currentRunIdRef.current = currentRun?.id || null;
  }, [currentRun]);

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

  const fetchRunById = async (runId) => {
    const response = await fetch(`${API_URL}/api/v1/companies/enrichment-runs/${runId}`);
    if (!response.ok) {
      throw new Error('Failed to refresh company enrichment run');
    }
    return response.json();
  };

  const refreshCurrentRun = async ({ runId = null, queueAfterInFlight = false } = {}) => {
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

      setCurrentRun(payload);
      setRefreshError(null);

      if (isTerminalRun(payload)) {
        setActionMessage(formatRunCompletionMessage(payload));
        await loadCompanies({
          query: appliedQuery,
          status: statusFilter,
          pageNumber: page,
          preserveMessage: true,
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
  };

  const loadCompanies = async ({
    query = appliedQuery,
    status = statusFilter,
    pageNumber = page,
    preserveMessage = true,
  } = {}) => {
    setIsLoading(true);
    setError(null);
    if (!preserveMessage) {
      setActionMessage(null);
    }

    try {
      const params = new URLSearchParams();
      params.append('status', status);
      params.append('page', String(pageNumber));
      params.append('page_size', String(PAGE_SIZE));
      if (query) {
        params.append('q', query);
      }

      const response = await fetch(`${API_URL}/api/v1/companies?${params.toString()}`);
      if (!response.ok) {
        throw new Error('Failed to load companies');
      }

      const payload = await response.json();
      if (!mountedRef.current) {
        return;
      }
      setCompanies(payload.items || []);
      setTotalPages(Number(payload.total_pages || 0));
      setError(null);
    } catch (err) {
      if (!mountedRef.current) {
        return;
      }
      setCompanies([]);
      setTotalPages(0);
      setError(err.message);
    } finally {
      if (mountedRef.current) {
        setIsLoading(false);
      }
    }
  };

  const loadCurrentRun = async () => {
    try {
      const response = await fetch(`${API_URL}/api/v1/companies/enrichment-runs/current`);
      if (!response.ok) {
        throw new Error('Failed to load company enrichment run');
      }

      const payload = await response.json();
      if (!mountedRef.current) {
        return;
      }
      setCurrentRun(payload);
      setError(null);
    } catch (err) {
      if (mountedRef.current) {
        setError(err.message);
      }
    }
  };

  useEffect(() => {
    loadCompanies();
  }, [appliedQuery, statusFilter, page]);

  useEffect(() => {
    loadCurrentRun();
  }, []);

  useEffect(() => {
    if (selectedCompanyId && !selectedCompany && !isLoading) {
      setSelectedCompanyId(null);
    }
  }, [isLoading, selectedCompany, selectedCompanyId]);

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
      } catch (err) {
        if (!cancelled) {
          setRefreshError(`Refresh failed: ${err.message}`);
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
  }, [appliedQuery, currentRun, isPageVisible, page, statusFilter]);

  useEffect(() => {
    const wasPageVisible = wasPageVisibleRef.current;
    wasPageVisibleRef.current = isPageVisible;

    if (!isPageVisible || wasPageVisible || !isActiveRun(currentRun)) {
      return;
    }

    let cancelled = false;

    const refreshNow = async () => {
      try {
        const payload = await refreshCurrentRun({
          runId: currentRun.id,
          queueAfterInFlight: true,
        });
        if (cancelled || !mountedRef.current) {
          return;
        }
      } catch (err) {
        if (!cancelled && mountedRef.current) {
          setRefreshError(`Refresh failed: ${err.message}`);
        }
      }
    };

    refreshNow();

    return () => {
      cancelled = true;
    };
  }, [appliedQuery, currentRun, isPageVisible, page, statusFilter]);

  const handleSearchSubmit = async (event) => {
    event.preventDefault();
    setPage(1);
    setAppliedQuery(searchInput.trim());
  };

  const handleStatusChange = async (event) => {
    setPage(1);
    setStatusFilter(event.target.value);
  };

  const handleCreateRun = async () => {
    setIsCreatingRun(true);
    setError(null);
    setRefreshError(null);
    setActionMessage(null);

    try {
      const response = await fetch(`${API_URL}/api/v1/companies/enrichment-runs`, {
        method: 'POST',
      });
      if (!response.ok) {
        throw new Error('Failed to start company enrichment run');
      }

      const payload = await response.json();
      if (payload?.status === 'empty' && payload?.run === null) {
        setCurrentRun(null);
        setActionMessage('All companies already have AI descriptions.');
        return;
      }

      const runPayload = payload.run || payload;
      setCurrentRun(runPayload);
      setActionMessage('Global backlog run started.');
      if (isActiveRun(runPayload)) {
        try {
          const refreshedRun = await refreshCurrentRun({ runId: runPayload.id });
          if (!mountedRef.current) {
            return;
          }
        } catch (_err) {
          // The polling loop will retry shortly; keep the optimistic run state.
        }
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setIsCreatingRun(false);
    }
  };

  const progress = getRunProgress(currentRun);
  const progressValue = progress.total ? Math.round((progress.processed / progress.total) * 100) : 0;
  const remainingCount = currentRun
    ? Math.max(Number(currentRun.pending_items || 0), 0)
    : 0;
  const pageReadyCount = companies.filter((company) => hasCompanyAIDescription(company)).length;
  const selectedCompanyStatus = selectedCompany ? getCompanyStatus(selectedCompany, currentRun) : null;
  const selectedCompanyDescription = selectedCompany && selectedCompanyStatus
    ? getCompanyDescriptionText(selectedCompany, selectedCompanyStatus)
    : null;
  const hasActiveRun = isActiveRun(currentRun);
  const batchButtonLabel = hasActiveRun
    ? 'Generation in progress'
    : isCreatingRun
      ? 'Starting generation...'
      : 'Generate All Pending Descriptions';

  return (
    <div className="companies-page">
      <section className="companies-hero glass-panel">
        <div className="companies-hero-copy">
          <p className="companies-eyebrow">Company Intelligence</p>
          <h2>Companies</h2>
          <p className="companies-subtitle">
            Company rows, AI description coverage, and the global generation queue.
          </p>

          <div className="companies-hero-stats">
            <div>
              <span>Visible results</span>
              <strong>{companies.length}</strong>
            </div>
            <div>
              <span>Descriptions ready</span>
              <strong>{pageReadyCount}</strong>
            </div>
          </div>

          {currentRun && (
            <div className="companies-progress">
              <div className="companies-progress-header">
                <span>Global backlog run</span>
                <strong>{progressValue}%</strong>
              </div>
              <p className="companies-progress-summary">
                {`Generating descriptions: ${progress.processed} / ${progress.total}`}
              </p>
              <div
                className="companies-progress-track"
                role="progressbar"
                aria-label="Company description progress"
                aria-valuemin="0"
                aria-valuemax="100"
                aria-valuenow={progressValue}
              >
                <div
                  className={`companies-progress-fill ${hasActiveRun ? 'live' : ''}`}
                  style={{ width: `${progressValue}%` }}
                />
              </div>
              <div className="companies-progress-meta">
                <span>{`Success: ${currentRun.completed_items}`}</span>
                <span>{`Failed: ${currentRun.failed_items}`}</span>
                <span>{`Remaining: ${remainingCount}`}</span>
              </div>
              {currentRun.current_company_name && (
                <p className="companies-progress-current">
                  {`Current company: ${currentRun.current_company_name}`}
                </p>
              )}
            </div>
          )}
        </div>

        <div className="companies-hero-actions">
          <form className="companies-search" onSubmit={handleSearchSubmit}>
            <label htmlFor="company-search" className="companies-search-label">
              Search companies
            </label>
            <div className="companies-filter-row">
              <input
                id="company-search"
                aria-label="Search companies"
                className="companies-search-input"
                type="text"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="Search company names..."
                disabled={isLoading || hasActiveRun || isCreatingRun}
              />
              <div className="companies-status-filter">
                <label htmlFor="company-status-filter">Status</label>
                <select
                  id="company-status-filter"
                  aria-label="Status"
                  value={statusFilter}
                  onChange={handleStatusChange}
                  disabled={isLoading || hasActiveRun || isCreatingRun}
                >
                  <option value="pending">Pending</option>
                  <option value="ready">Ready</option>
                  <option value="all">All</option>
                </select>
              </div>
              <button className="companies-search-button" type="submit" disabled={isLoading || hasActiveRun || isCreatingRun}>
                Search
              </button>
            </div>
          </form>

          <div className="companies-batch-group">
            <p className="companies-batch-hint">
              Targets all companies without AI descriptions.
            </p>
            <button
              type="button"
              className="companies-batch-button"
              onClick={handleCreateRun}
              disabled={isLoading || isCreatingRun || hasActiveRun}
            >
              <Sparkles size={16} />
              <span>{batchButtonLabel}</span>
            </button>
          </div>
        </div>
      </section>

      {error && <div className="companies-error glass-panel">{error}</div>}
      {refreshError && <div className="companies-error glass-panel">{refreshError}</div>}
      {actionMessage && <div className="companies-status glass-panel">{actionMessage}</div>}

      {isLoading ? (
        <div className="companies-empty glass-panel">
          <p>Loading companies...</p>
        </div>
      ) : companies.length === 0 ? (
        <div className="companies-empty glass-panel">
          <p>No companies matched the current query.</p>
        </div>
      ) : (
        <>
          <div className="companies-grid">
            {companies.map((company) => {
              const companyStatus = getCompanyStatus(company, currentRun);

              return (
                <CompanySummaryCard
                  key={company.id}
                  company={company}
                  status={companyStatus}
                  statusLabel={getCompanyStatusLabel(companyStatus)}
                  onClick={() => setSelectedCompanyId(company.id)}
                />
              );
            })}
          </div>

          <div className="companies-pagination glass-panel">
            <button
              type="button"
              className="companies-pagination-button"
              onClick={() => setPage((currentPage) => Math.max(currentPage - 1, 1))}
              disabled={page <= 1 || isLoading}
              aria-label="Previous page"
            >
              Previous
            </button>
            <p>{`Page ${page} of ${Math.max(totalPages, 1)}`}</p>
            <button
              type="button"
              className="companies-pagination-button"
              onClick={() => setPage((currentPage) => Math.min(currentPage + 1, Math.max(totalPages, 1)))}
              disabled={page >= Math.max(totalPages, 1) || isLoading}
              aria-label="Next page"
            >
              Next
            </button>
          </div>
        </>
      )}

      {selectedCompany && selectedCompanyStatus && selectedCompanyDescription && (
        <CompanyDetailModal
          company={selectedCompany}
          statusLabel={getCompanyStatusLabel(selectedCompanyStatus)}
          statusClassName={selectedCompanyStatus}
          descriptionText={selectedCompanyDescription}
          onClose={() => setSelectedCompanyId(null)}
        />
      )}
    </div>
  );
}

export default CompaniesPage;
