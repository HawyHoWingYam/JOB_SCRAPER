import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Sparkles } from 'lucide-react';
import PaginationControl from '../PaginationControl';
import CompanyDetailModal from './CompanyDetailModal';
import CompanySummaryCard from './CompanySummaryCard';
import useCompanyEnrichmentRun, { getRunStatusLabel } from './useCompanyEnrichmentRun';
import { API_BASE_URL } from '../../api/base';
import './CompaniesPage.css';

const API_URL = API_BASE_URL;
const PAGE_SIZE = 25;

function hasCompanyAIDescription(company) {
  return Boolean(company?.ai_description?.trim());
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
  const [selectedCompanyId, setSelectedCompanyId] = useState(null);
  const mountedRef = useRef(true);

  const loadCompanies = useCallback(async ({
    query = appliedQuery,
    status = statusFilter,
    pageNumber = page,
  } = {}) => {
    setIsLoading(true);
    setError(null);

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

      const nextTotalPages = Number(payload.total_pages || 0);
      const resolvedPage = nextTotalPages > 0 ? nextTotalPages : 1;

      if (pageNumber > resolvedPage) {
        setTotalPages(nextTotalPages);
        setPage(resolvedPage);
        return;
      }

      setCompanies(payload.items || []);
      setTotalPages(nextTotalPages);
      setError(null);
    } catch (loadError) {
      if (!mountedRef.current) {
        return;
      }

      setCompanies([]);
      setTotalPages(0);
      setError(loadError.message);
    } finally {
      if (mountedRef.current) {
        setIsLoading(false);
      }
    }
  }, [appliedQuery, page, statusFilter]);

  const {
    currentRun,
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
  } = useCompanyEnrichmentRun({
    apiUrl: API_URL,
    appliedQuery,
    statusFilter,
    page,
    loadCompanies,
  });

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    loadCompanies();
  }, [loadCompanies]);

  const selectedCompany = companies.find((company) => company.id === selectedCompanyId) || null;

  useEffect(() => {
    if (selectedCompanyId && !selectedCompany && !isLoading) {
      setSelectedCompanyId(null);
    }
  }, [isLoading, selectedCompany, selectedCompanyId]);

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
    const didStartRun = await createRun();
    if (didStartRun) {
      setError(null);
    }
  };

  const pageReadyCount = companies.filter((company) => hasCompanyAIDescription(company)).length;
  const selectedCompanyState = selectedCompany ? getCompanyRunState(selectedCompany) : null;

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
              <span>Descriptions ready on page</span>
              <strong>{pageReadyCount}</strong>
            </div>
          </div>

          {currentRun && hasActiveRun && (
            <div className="companies-progress">
              <div className="companies-progress-header">
                <span>Global backlog run</span>
                <strong>{hasQueuedRun ? 'Queued' : `${progressValue}%`}</strong>
              </div>
              <p className="companies-progress-summary">
                {hasQueuedRun
                  ? 'Queued for execution'
                  : `Generating descriptions: ${progress.processed} / ${progress.total}`}
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
              {!hasQueuedRun && (
                <div className="companies-progress-meta">
                  <span>{`Success: ${currentRun.completed_items}`}</span>
                  <span>{`Failed: ${currentRun.failed_items}`}</span>
                  <span>{`Remaining: ${remainingCount}`}</span>
                </div>
              )}
              {currentRun.current_company_name && (
                <p className="companies-progress-current">
                  {`Current company: ${currentRun.current_company_name}`}
                </p>
              )}
            </div>
          )}
          {currentRun && hasTerminalRun && !actionMessage && (
            <div className="companies-progress">
              <div className="companies-progress-header">
                <span>Latest run</span>
                <strong>{getRunStatusLabel(currentRun.status)}</strong>
              </div>
              <p className="companies-progress-summary">
                {terminalMessage}
              </p>
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
                  <option value="pending">Needs AI</option>
                  <option value="ready">AI Ready</option>
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
              const companyRunState = getCompanyRunState(company);

              return (
                <CompanySummaryCard
                  key={company.id}
                  company={company}
                  status={companyRunState.status}
                  statusLabel={companyRunState.statusLabel}
                  onClick={() => setSelectedCompanyId(company.id)}
                />
              );
            })}
          </div>

          <PaginationControl
            page={page}
            totalPages={Math.max(totalPages, 1)}
            totalItems={companies.length}
            isLoading={isLoading}
            onPageChange={setPage}
            summaryText={`Page ${page} of ${Math.max(totalPages, 1)}`}
            hideWhenSinglePage
          />
        </>
      )}

      {selectedCompany && selectedCompanyState && (
        <CompanyDetailModal
          company={selectedCompany}
          statusLabel={selectedCompanyState.statusLabel}
          statusClassName={selectedCompanyState.status}
          descriptionText={selectedCompanyState.descriptionText}
          onClose={() => setSelectedCompanyId(null)}
        />
      )}
    </div>
  );
}

export default CompaniesPage;
