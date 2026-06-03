# Pagination, Companies Run Orchestration, and Fallback Reduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add direct page-jump controls to Job Browser and Companies, refactor Companies run orchestration so the UI no longer gets stuck, and reduce governed taxonomy fallback assignments for high-signal jobs.

**Architecture:** Introduce a shared frontend pagination control, extract Companies enrichment-run state handling into a dedicated hook plus small backend consistency improvements, and extend `JobCategoryNormalizer` with deterministic specific-over-general promotion rules for governed slices. Keep dashboard contracts unchanged and drive confidence through focused TDD on both frontend and backend paths.

**Tech Stack:** React 19, Vite, Vitest, Testing Library, plain CSS, FastAPI, SQLAlchemy, pytest

---

## File Structure

### New files

- `frontend/src/components/PaginationControl.jsx`
  - Shared page navigation UI and draft page-jump behavior.
- `frontend/src/components/PaginationControl.test.jsx`
  - Isolated pagination behavior tests.
- `frontend/src/components/companies/useCompanyEnrichmentRun.js`
  - Companies run polling, visibility resume, terminal reconciliation, and derived view model.

### Modified files

- `frontend/src/components/Pagination.jsx`
  - Convert into a thin compatibility wrapper over `PaginationControl` so existing imports stay stable during the refactor.
- `frontend/src/components/JobBrowser.jsx`
  - Swap the page footer to the shared pagination control.
- `frontend/src/components/JobBrowser.test.jsx`
  - Add page-jump behavior coverage.
- `frontend/src/components/JobBrowser.css`
  - Add shared pagination input and button styling used by `PaginationControl`.
- `frontend/src/components/companies/CompaniesPage.jsx`
  - Replace inline run orchestration with the extracted hook and shared pagination control.
- `frontend/src/components/companies/CompaniesPage.test.jsx`
  - Add page-jump coverage and run-completion regression coverage.
- `frontend/src/components/companies/CompaniesPage.css`
  - Align the Companies page footer with the shared pagination control styling.
- `backend/app/services/company_enrichment_run_service.py`
  - Tighten run/item state update ordering and current-company identity consistency.
- `backend/app/api/companies.py`
  - Keep contract stable while ensuring `current_company_id` remains reliable for the frontend.
- `backend/tests/test_company_enrichment_run_service.py`
  - Add state-ordering and current-company-id coverage.
- `backend/app/services/job_category_normalizer.py`
  - Add specific-over-general promotion logic for high-signal governed cases.
- `backend/tests/test_job_category_normalizer.py`
  - Add regression tests for promoted specific subcategories and negative controls.

## Task 1: Build Shared Pagination Control

**Files:**
- Create: `frontend/src/components/PaginationControl.jsx`
- Create: `frontend/src/components/PaginationControl.test.jsx`
- Modify: `frontend/src/components/JobBrowser.css`
- Modify: `frontend/src/components/companies/CompaniesPage.css`

- [ ] **Step 1: Write the failing pagination component tests**

```jsx
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import PaginationControl from './PaginationControl';

describe('PaginationControl', () => {
  it('submits a clamped page number when Go is pressed', () => {
    const onPageChange = vi.fn();

    render(
      <PaginationControl
        page={2}
        totalPages={5}
        totalItems={120}
        summaryText="Page 2 of 5"
        isLoading={false}
        onPageChange={onPageChange}
      />,
    );

    fireEvent.change(screen.getByLabelText(/jump to page/i), {
      target: { value: '99' },
    });
    fireEvent.click(screen.getByRole('button', { name: /go/i }));

    expect(onPageChange).toHaveBeenCalledWith(5);
  });

  it('does not submit when the clamped page matches the current page', () => {
    const onPageChange = vi.fn();

    render(
      <PaginationControl
        page={5}
        totalPages={5}
        totalItems={120}
        summaryText="Page 5 of 5"
        isLoading={false}
        onPageChange={onPageChange}
      />,
    );

    fireEvent.change(screen.getByLabelText(/jump to page/i), {
      target: { value: '99' },
    });
    fireEvent.click(screen.getByRole('button', { name: /go/i }));

    expect(onPageChange).not.toHaveBeenCalled();
  });

  it('submits when enter is pressed inside the page input', () => {
    const onPageChange = vi.fn();

    render(
      <PaginationControl
        page={1}
        totalPages={5}
        totalItems={120}
        summaryText="Page 1 of 5"
        isLoading={false}
        onPageChange={onPageChange}
      />,
    );

    fireEvent.change(screen.getByLabelText(/jump to page/i), {
      target: { value: '3' },
    });
    fireEvent.keyDown(screen.getByLabelText(/jump to page/i), {
      key: 'Enter',
      code: 'Enter',
    });

    expect(onPageChange).toHaveBeenCalledWith(3);
  });

  it('disables the input and go button while loading', () => {
    render(
      <PaginationControl
        page={1}
        totalPages={5}
        totalItems={120}
        summaryText="Page 1 of 5"
        isLoading
        onPageChange={vi.fn()}
      />,
    );

    expect(screen.getByLabelText(/jump to page/i)).toBeDisabled();
    expect(screen.getByRole('button', { name: /go/i })).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run the pagination component tests to verify failure**

Run: `npm test -- --run src/components/PaginationControl.test.jsx`  
Workdir: `frontend`  
Expected: FAIL because `PaginationControl.jsx` does not exist yet.

- [ ] **Step 3: Write the minimal shared pagination component**

```jsx
import React, { useEffect, useState } from 'react';

function normalizeDraftPage(value) {
  const numeric = Number.parseInt(String(value || '').trim(), 10);
  if (!Number.isFinite(numeric)) {
    return null;
  }
  return numeric;
}

function PaginationControl({
  page,
  totalPages,
  totalItems,
  isLoading,
  onPageChange,
  summaryText,
  hideWhenSinglePage = true,
}) {
  const [draftPage, setDraftPage] = useState(String(page || 1));

  useEffect(() => {
    setDraftPage(String(page || 1));
  }, [page]);

  if (hideWhenSinglePage && totalPages <= 1) {
    return null;
  }

  const commitDraftPage = () => {
    const normalized = normalizeDraftPage(draftPage);
    if (normalized == null || totalPages <= 0) {
      return;
    }

    const clamped = Math.max(1, Math.min(normalized, totalPages));
    if (clamped === page) {
      setDraftPage(String(clamped));
      return;
    }

    setDraftPage(String(clamped));
    onPageChange(clamped);
  };

  return (
    <div className="pagination">
      <span className="pagination-info">
        {summaryText || `Page ${page} of ${totalPages} (${totalItems} items)`}
      </span>

      <div className="pagination-controls">
        <button
          type="button"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1 || isLoading}
        >
          Previous
        </button>

        <label className="pagination-jump">
          <span className="pagination-jump-label">Jump to page</span>
          <input
            aria-label="Jump to page"
            type="number"
            min="1"
            max={Math.max(totalPages, 1)}
            value={draftPage}
            onChange={(event) => setDraftPage(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                commitDraftPage();
              }
            }}
            disabled={isLoading}
          />
        </label>

        <button type="button" onClick={commitDraftPage} disabled={isLoading}>
          Go
        </button>

        <button
          type="button"
          onClick={() => onPageChange(page + 1)}
          disabled={page >= totalPages || isLoading}
        >
          Next
        </button>
      </div>
    </div>
  );
}

export default PaginationControl;
```

- [ ] **Step 4: Add minimal shared pagination styles**

```css
.pagination-jump {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
}

.pagination-jump-label {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
}

.pagination-jump input {
    width: 84px;
    min-height: 40px;
    padding: 0 var(--space-2);
}
```

- [ ] **Step 5: Run the pagination component tests to verify success**

Run: `npm test -- --run src/components/PaginationControl.test.jsx`  
Workdir: `frontend`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/PaginationControl.jsx frontend/src/components/PaginationControl.test.jsx frontend/src/components/JobBrowser.css frontend/src/components/companies/CompaniesPage.css
git commit -m "feat: add shared pagination control"
```

## Task 2: Integrate Shared Pagination into Job Browser

**Files:**
- Modify: `frontend/src/components/JobBrowser.jsx`
- Modify: `frontend/src/components/JobBrowser.test.jsx`
- Modify: `frontend/src/components/Pagination.jsx`

- [ ] **Step 1: Write the failing Job Browser page-jump regression test**

```jsx
it('jumps directly to a requested page from the shared pagination control', async () => {
  render(<JobBrowser />);

  await screen.findByText('Healthcare ERP Lead');

  fireEvent.change(screen.getByLabelText(/jump to page/i), {
    target: { value: '2' },
  });
  fireEvent.click(screen.getByRole('button', { name: /go/i }));

  await waitFor(() => {
    expect(getLatestSearchBody(globalThis.fetch).page).toBe(2);
  });
});
```

- [ ] **Step 2: Run the Job Browser test to verify failure**

Run: `npm test -- --run src/components/JobBrowser.test.jsx`  
Workdir: `frontend`  
Expected: FAIL because `JobBrowser` still renders the old pagination control.

- [ ] **Step 3: Replace the old Job Browser pagination usage**

```jsx
import PaginationControl from './PaginationControl';

// ...

<PaginationControl
  page={pagination.page}
  totalPages={pagination.totalPages}
  totalItems={pagination.total}
  isLoading={isLoading}
  onPageChange={handlePageChange}
  summaryText={`Page ${pagination.page} of ${Math.max(pagination.totalPages || 1, 1)} (${pagination.total} jobs)`}
  hideWhenSinglePage
/>
```

- [ ] **Step 4: Convert the old `Pagination.jsx` into a thin compatibility wrapper**

```jsx
import React from 'react';
import PaginationControl from './PaginationControl';

function Pagination({ page, totalPages, total, onPageChange, isLoading }) {
  return (
    <PaginationControl
      page={page}
      totalPages={totalPages}
      totalItems={total}
      isLoading={isLoading}
      onPageChange={onPageChange}
      summaryText={`Page ${page} of ${totalPages} (${total} jobs)`}
      hideWhenSinglePage
    />
  );
}

export default Pagination;
```

- [ ] **Step 5: Run the Job Browser tests to verify success**

Run: `npm test -- --run src/components/JobBrowser.test.jsx src/components/PaginationControl.test.jsx`  
Workdir: `frontend`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/JobBrowser.jsx frontend/src/components/JobBrowser.test.jsx frontend/src/components/Pagination.jsx
git commit -m "feat: add direct page jump to job browser"
```

## Task 3: Integrate Shared Pagination into Companies

**Files:**
- Modify: `frontend/src/components/companies/CompaniesPage.jsx`
- Modify: `frontend/src/components/companies/CompaniesPage.test.jsx`

- [ ] **Step 1: Write the failing Companies page-jump regression test**

```jsx
it('jumps directly to a requested companies page', async () => {
  const user = userEvent.setup();
  render(<CompaniesPage />);

  await screen.findByText('Acme Health');

  await user.clear(screen.getByLabelText(/jump to page/i));
  await user.type(screen.getByLabelText(/jump to page/i), '2');
  await user.click(screen.getByRole('button', { name: /go/i }));

  await waitFor(() => {
    expect(companyRequests.at(-1)).toBe('status=pending&q=&page=2&page_size=25');
  });
});
```

- [ ] **Step 2: Run the Companies test to verify failure**

Run: `npm test -- --run src/components/companies/CompaniesPage.test.jsx`  
Workdir: `frontend`  
Expected: FAIL because the Companies page still renders the local previous/next footer only.

- [ ] **Step 3: Replace the Companies pagination footer with the shared control**

```jsx
import PaginationControl from '../PaginationControl';

// ...

<PaginationControl
  page={page}
  totalPages={Math.max(totalPages, 1)}
  totalItems={companies.length}
  isLoading={isLoading}
  onPageChange={setPage}
  summaryText={`Page ${page} of ${Math.max(totalPages, 1)}`}
  hideWhenSinglePage
/>
```

- [ ] **Step 4: Run the Companies pagination tests to verify success**

Run: `npm test -- --run src/components/companies/CompaniesPage.test.jsx src/components/PaginationControl.test.jsx`  
Workdir: `frontend`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/companies/CompaniesPage.jsx frontend/src/components/companies/CompaniesPage.test.jsx
git commit -m "feat: add direct page jump to companies"
```

## Task 4: Lock in the Companies stuck-run regression before refactoring

**Files:**
- Modify: `frontend/src/components/companies/CompaniesPage.test.jsx`

- [ ] **Step 1: Write a failing regression test for terminal run convergence**

```jsx
it('clears stale generating state after a run reaches a terminal status', async () => {
  const user = userEvent.setup();
  currentRunResponses = [
    {
      id: 'run-current',
      status: 'running',
      total_items: 1,
      pending_items: 0,
      completed_items: 0,
      failed_items: 0,
      current_company_id: 'company-1',
      current_company_name: 'Acme Health',
      error_message: null,
      started_at: '2026-04-19T10:00:00Z',
      completed_at: null,
      created_at: '2026-04-19T10:00:00Z',
    },
  ];
  runResponsesById['run-current'] = [
    {
      id: 'run-current',
      status: 'completed',
      total_items: 1,
      pending_items: 0,
      completed_items: 1,
      failed_items: 0,
      current_company_id: null,
      current_company_name: null,
      error_message: null,
      started_at: '2026-04-19T10:00:00Z',
      completed_at: '2026-04-19T10:01:00Z',
      created_at: '2026-04-19T10:00:00Z',
    },
  ];
  companyPages['status=pending&q=&page=1&page_size=25'] = buildCompaniesPayload(
    [
      {
        id: 'company-1',
        company_id: 'company-1',
        name: 'Acme Health',
        industry: 'Healthcare',
        location: 'Hong Kong',
        ai_description: 'Acme Health AI summary',
      },
    ],
    1,
    1,
  );

  render(<CompaniesPage />);

  expect(await screen.findByText(/current company: acme health/i)).toBeInTheDocument();

  await waitFor(() => {
    expect(screen.queryByText(/current company: acme health/i)).not.toBeInTheDocument();
  });
  expect(screen.getByText(/finished generating descriptions for 1 companies\. 1 succeeded, 0 failed\./i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the Companies regression test to verify failure**

Run: `npm test -- --run src/components/companies/CompaniesPage.test.jsx`  
Workdir: `frontend`  
Expected: FAIL because the current page logic can remain stuck on stale active-run UI.

- [ ] **Step 3: Commit the red test checkpoint**

```bash
git add frontend/src/components/companies/CompaniesPage.test.jsx
git commit -m "test: cover stuck companies run convergence"
```

## Task 5: Extract Companies run orchestration into a hook

**Files:**
- Create: `frontend/src/components/companies/useCompanyEnrichmentRun.js`
- Modify: `frontend/src/components/companies/CompaniesPage.jsx`
- Modify: `frontend/src/components/companies/CompaniesPage.test.jsx`

- [ ] **Step 1: Create the hook with the current run orchestration behavior**

```jsx
import { useEffect, useMemo, useRef, useState } from 'react';

const RUN_POLL_INTERVAL_MS = 2000;

export function useCompanyEnrichmentRun({
  apiUrl,
  appliedQuery,
  statusFilter,
  page,
  loadCompanies,
}) {
  const [currentRun, setCurrentRun] = useState(null);
  const [runItemsByCompanyId, setRunItemsByCompanyId] = useState({});
  const [refreshError, setRefreshError] = useState(null);
  const [actionMessage, setActionMessage] = useState(null);
  const [isCreatingRun, setIsCreatingRun] = useState(false);
  const [isPageVisible, setIsPageVisible] = useState(() => (
    typeof document === 'undefined' ? true : !document.hidden
  ));

  const mountedRef = useRef(true);
  const currentRunIdRef = useRef(null);
  const runRefreshInFlightRef = useRef(null);
  const runRefreshQueuedRef = useRef(false);
  const wasPageVisibleRef = useRef(typeof document === 'undefined' ? true : !document.hidden);

  const isActiveRun = (run) => Boolean(run && ['pending', 'running'].includes(String(run.status || '').toLowerCase()));
  const isQueuedRun = (run) => Boolean(run && String(run.status || '').toLowerCase() === 'pending');
  const isTerminalRun = (run) => Boolean(run && ['completed', 'completed_with_failures', 'failed'].includes(String(run.status || '').toLowerCase()));

  const formatRunCompletionMessage = (run) => {
    const summary = `Finished generating descriptions for ${run.total_items} companies. ${run.completed_items} succeeded, ${run.failed_items} failed.`;
    return run.error_message ? `${summary} ${run.error_message}` : summary;
  };

  const fetchRunById = async (runId) => {
    const response = await fetch(`${apiUrl}/api/v1/companies/enrichment-runs/${runId}`);
    if (!response.ok) {
      throw new Error('Failed to refresh company enrichment run');
    }
    return response.json();
  };

  const loadRunItems = async (runId) => {
    const response = await fetch(`${apiUrl}/api/v1/companies/enrichment-runs/${runId}/items`);
    if (!response.ok) {
      throw new Error('Failed to load company enrichment run items');
    }

    const payload = await response.json();
    const next = {};
    for (const item of payload.items || []) {
      const companyId = `${item.company_id || ''}`.trim();
      if (companyId) {
        next[companyId] = item;
      }
    }
    return next;
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
      const items = payload ? await loadRunItems(targetRunId).catch(() => ({})) : {};

      if (!mountedRef.current) {
        return payload;
      }

      setCurrentRun(payload);
      setRunItemsByCompanyId(items);
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
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, []);

  useEffect(() => {
    let cancelled = false;

    const loadCurrentRun = async () => {
      try {
        const response = await fetch(`${apiUrl}/api/v1/companies/enrichment-runs/current`);
        if (!response.ok) {
          throw new Error('Failed to load company enrichment run');
        }
        const payload = await response.json();
        if (!cancelled && mountedRef.current) {
          setCurrentRun(payload);
          if (payload?.id) {
            const items = await loadRunItems(payload.id).catch(() => ({}));
            if (!cancelled && mountedRef.current) {
              setRunItemsByCompanyId(items);
            }
          }
        }
      } catch (err) {
        if (!cancelled && mountedRef.current) {
          setRefreshError(err.message);
        }
      }
    };

    loadCurrentRun();
    return () => {
      cancelled = true;
    };
  }, [apiUrl]);

  useEffect(() => {
    if (!isActiveRun(currentRun) || !isPageVisible) {
      return undefined;
    }

    let cancelled = false;
    let timeoutId;

    const poll = async () => {
      let shouldContinue = true;
      try {
        const payload = await refreshCurrentRun({ runId: currentRun.id });
        if (cancelled || !payload) {
          return;
        }
        if (isTerminalRun(payload)) {
          shouldContinue = false;
        }
      } catch (err) {
        if (!cancelled) {
          setRefreshError(`Refresh failed: ${err.message}`);
        }
      } finally {
        if (!cancelled && shouldContinue) {
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
  }, [currentRun, isPageVisible, appliedQuery, statusFilter, page]);

  useEffect(() => {
    const wasVisible = wasPageVisibleRef.current;
    wasPageVisibleRef.current = isPageVisible;

    if (!isPageVisible || wasVisible || !isActiveRun(currentRun)) {
      return;
    }

    refreshCurrentRun({ runId: currentRun.id, queueAfterInFlight: true }).catch((err) => {
      if (mountedRef.current) {
        setRefreshError(`Refresh failed: ${err.message}`);
      }
    });
  }, [currentRun, isPageVisible, appliedQuery, statusFilter, page]);

  const derived = useMemo(() => {
    const progress = currentRun
      ? {
          processed: Number(currentRun.completed_items || 0) + Number(currentRun.failed_items || 0),
          total: Number(currentRun.total_items || 0),
        }
      : { processed: 0, total: 0 };
    return {
      hasActiveRun: isActiveRun(currentRun),
      hasQueuedRun: isQueuedRun(currentRun),
      progress,
      progressValue: progress.total ? Math.round((progress.processed / progress.total) * 100) : 0,
      remainingCount: currentRun ? Math.max(Number(currentRun.pending_items || 0), 0) : 0,
      batchButtonLabel: isActiveRun(currentRun)
        ? (isQueuedRun(currentRun) ? 'Generation queued' : 'Generation in progress')
        : isCreatingRun
          ? 'Starting generation...'
          : 'Generate Missing Descriptions',
      terminalMessage: currentRun && isTerminalRun(currentRun) ? formatRunCompletionMessage(currentRun) : null,
    };
  }, [currentRun, isCreatingRun]);

  return {
    currentRun,
    runItemsByCompanyId,
    refreshError,
    actionMessage,
    setActionMessage,
    isCreatingRun,
    setIsCreatingRun,
    refreshCurrentRun,
    setCurrentRun,
    ...derived,
  };
}
```

- [ ] **Step 2: Refactor `CompaniesPage.jsx` to consume the hook**

```jsx
const {
  currentRun,
  runItemsByCompanyId,
  refreshError,
  actionMessage,
  setActionMessage,
  isCreatingRun,
  setIsCreatingRun,
  refreshCurrentRun,
  setCurrentRun,
  hasActiveRun,
  hasQueuedRun,
  progress,
  progressValue,
  remainingCount,
  batchButtonLabel,
  terminalMessage,
} = useCompanyEnrichmentRun({
  apiUrl: API_URL,
  appliedQuery,
  statusFilter,
  page,
  loadCompanies,
});
```

- [ ] **Step 3: Re-run the Companies regression tests until green**

Run: `npm test -- --run src/components/companies/CompaniesPage.test.jsx src/components/PaginationControl.test.jsx`  
Workdir: `frontend`  
Expected: PASS, including the new terminal-convergence regression.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/companies/useCompanyEnrichmentRun.js frontend/src/components/companies/CompaniesPage.jsx frontend/src/components/companies/CompaniesPage.test.jsx
git commit -m "refactor: extract companies run orchestration"
```

## Task 6: Tighten backend company-run state consistency

**Files:**
- Modify: `backend/tests/test_company_enrichment_run_service.py`
- Modify: `backend/app/services/company_enrichment_run_service.py`
- Modify: `backend/app/api/companies.py`

- [ ] **Step 1: Write the failing backend run-state test**

```python
async def test_execute_run_clears_current_company_identity_and_updates_counters(db_session, company_factory):
    service = CompanyEnrichmentRunService(db_session)
    company = company_factory(name="Acme Health", ai_description=None)
    run = service.create_pending_run(force_company_ids=[company.id])
    db_session.commit()

    class StubEnrichmentService:
        async def enrich_company_description(self, company, db, force=False):
            company.ai_description = "AI summary"
            return {"company_id": str(company.id), "ai_description": company.ai_description}

    completed_run = await service.execute_run(run.id, enrichment_service=StubEnrichmentService())

    assert completed_run.status == "completed"
    assert completed_run.current_company_name is None
    assert completed_run.pending_items == 0
    assert completed_run.completed_items == 1
    assert completed_run.failed_items == 0
```

- [ ] **Step 2: Run the backend run-service test to verify failure**

Run: `python -m pytest backend/tests/test_company_enrichment_run_service.py -q`  
Workdir: repository root  
Expected: FAIL because the new terminal-state invariants are not yet covered or guaranteed.

- [ ] **Step 3: Adjust run execution ordering and current-company identity behavior**

```python
for item in items:
    company = companies_by_id.get(item.company_id)
    if company is None:
        raise NoResultFound(f"Company not found for enrichment run item {item.id}")

    item.status = "running"
    item.started_at = item.started_at or utc_now()
    run.current_company_name = company.name
    self.db.flush()

    try:
        await service.enrich_company_description(company, self.db)
        item.status = "completed"
        item.error_message = None
        item.completed_at = utc_now()
        completed_items += 1
    except Exception as exc:
        item.status = "failed"
        item.error_message = str(exc)
        item.completed_at = utc_now()
        failed_items += 1
        if first_error_message is None:
          first_error_message = str(exc)
    finally:
        run.pending_items = max(run.total_items - completed_items - failed_items, 0)
        run.completed_items = completed_items
        run.failed_items = failed_items
        self.db.flush()

run.current_company_name = None
run.completed_at = utc_now()
```

- [ ] **Step 4: Re-run backend run-service tests**

Run: `python -m pytest backend/tests/test_company_enrichment_run_service.py -q`  
Workdir: repository root  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/company_enrichment_run_service.py backend/app/api/companies.py backend/tests/test_company_enrichment_run_service.py
git commit -m "fix: stabilize company enrichment run state transitions"
```

## Task 7: Add fallback-promotion regression tests

**Files:**
- Modify: `backend/tests/test_job_category_normalizer.py`

- [ ] **Step 1: Write failing fallback-promotion tests**

```python
def test_resolve_taxonomy_decision_promotes_general_fallback_to_backend_when_api_signals_are_strong():
    db, normalizer = _build_normalizer()

    subcategory_id = normalizer.resolve_taxonomy_decision(
        classification={
            "taxonomy_decision": {
                "domain": "Information & Communication Technology",
                "category": "General",
                "subcategory": "General",
                "resolution": "fallback_default_path",
            },
            "final_taxonomy_decision": {
                "domain": "Information & Communication Technology",
                "category": "General",
                "subcategory": "General",
                "resolution": "fallback_default_path",
            },
        },
        source_classification_id="6281",
        source_classification_name="Information & Communication Technology",
        source_subclassification_name="Engineering - Software",
        job_title="Backend Engineer",
        job_description="Build REST APIs, backend services, and microservices for enterprise platforms.",
        extracted_skills=["Java", "Spring Boot", "RESTful API", "Microservices"],
    )

    resolved = db.query(JobSubcategory).filter(JobSubcategory.id == subcategory_id).one()
    assert resolved.name == "Backend Development"
    db.close()


def test_resolve_taxonomy_decision_keeps_general_fallback_when_backend_signals_are_weak():
    db, normalizer = _build_normalizer()

    subcategory_id = normalizer.resolve_taxonomy_decision(
        classification={
            "taxonomy_decision": {
                "domain": "Information & Communication Technology",
                "category": "General",
                "subcategory": "General",
                "resolution": "fallback_default_path",
            },
            "final_taxonomy_decision": {
                "domain": "Information & Communication Technology",
                "category": "General",
                "subcategory": "General",
                "resolution": "fallback_default_path",
            },
        },
        source_classification_id="6281",
        source_classification_name="Information & Communication Technology",
        source_subclassification_name="Engineering - Software",
        job_title="Software Engineer",
        job_description="Work with internal teams on software projects.",
        extracted_skills=["Communication", "Documentation"],
    )

    resolved = db.query(JobSubcategory).filter(JobSubcategory.id == subcategory_id).one()
    assert resolved.name == "General"
    db.close()
```

- [ ] **Step 2: Run the normalizer tests to verify failure**

Run: `python -m pytest backend/tests/test_job_category_normalizer.py -q`  
Workdir: repository root  
Expected: FAIL because `General / General` is still accepted for these high-signal cases.

- [ ] **Step 3: Commit the red test checkpoint**

```bash
git add backend/tests/test_job_category_normalizer.py
git commit -m "test: cover fallback promotion for taxonomy normalization"
```

## Task 8: Implement governed fallback promotion in the normalizer

**Files:**
- Modify: `backend/app/services/job_category_normalizer.py`
- Modify: `backend/tests/test_job_category_normalizer.py`

- [ ] **Step 1: Add a specific-over-general promotion helper**

```python
def _promote_specific_subcategory_over_general_fallback(
    self,
    resolved_path: tuple[str, str, str, bool],
    source_slice: SourceBoundTaxonomySlice,
    *,
    source_subclassification_name: Optional[str],
    job_title: Optional[str],
    job_description: str,
    extracted_skills: Optional[list[dict | str]],
    governance_override: bool,
) -> tuple[str, str, str, bool]:
    if governance_override:
        return resolved_path
    if resolved_path[1] != "General" or resolved_path[2] != "General":
        return resolved_path
    if source_subclassification_name != "Engineering - Software":
        return resolved_path
    if "Software Development" not in source_slice.allowed_categories:
        return resolved_path
    if "Backend Development" not in source_slice.allowed_subcategories:
        return resolved_path

    normalized_title = str(job_title or "").lower()
    normalized_text = " ".join(str(value or "").strip().lower() for value in (job_title, job_description))
    normalized_skill_names = {
        self._normalize_skill_signal_name(skill)
        for skill in (extracted_skills or [])
    }
    signal_hits = {
        signal
        for signal in (
            "backend",
            "api",
            "apis",
            "restful api",
            "microservices",
            "backend service",
            "backend services",
        )
        if signal in normalized_title or signal in normalized_text or signal in normalized_skill_names
    }

    if len(signal_hits) < 3:
        return resolved_path

    return (
        resolved_path[0],
        "Software Development",
        "Backend Development",
        resolved_path[3],
    )
```

- [ ] **Step 2: Call the new helper from `resolve_taxonomy_decision()`**

```python
domain_name, category_name, subcategory_name, allow_create = (
    self._promote_specific_subcategory_over_general_fallback(
        (domain_name, category_name, subcategory_name, allow_create),
        source_slice,
        source_subclassification_name=source_subclassification_name,
        job_title=job_title,
        job_description=job_description,
        extracted_skills=extracted_skills,
        governance_override=bool(classification.get("governance_override")),
    )
)
```

- [ ] **Step 3: Re-run the normalizer tests**

Run: `python -m pytest backend/tests/test_job_category_normalizer.py -q`  
Workdir: repository root  
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/job_category_normalizer.py backend/tests/test_job_category_normalizer.py
git commit -m "feat: promote specific taxonomy paths over generic fallback"
```

## Task 9: Final targeted verification

**Files:**
- Modify: none

- [ ] **Step 1: Run focused frontend verification**

Run: `npm test -- --run src/components/PaginationControl.test.jsx src/components/JobBrowser.test.jsx src/components/companies/CompaniesPage.test.jsx`  
Workdir: `frontend`  
Expected: PASS

- [ ] **Step 2: Run focused backend verification**

Run: `python -m pytest backend/tests/test_company_enrichment_run_service.py backend/tests/test_job_category_normalizer.py -q`  
Workdir: repository root  
Expected: PASS

- [ ] **Step 3: Review git diff before handoff**

Run: `git diff --stat -- frontend/src/components/PaginationControl.jsx frontend/src/components/PaginationControl.test.jsx frontend/src/components/Pagination.jsx frontend/src/components/JobBrowser.jsx frontend/src/components/JobBrowser.test.jsx frontend/src/components/JobBrowser.css frontend/src/components/companies/CompaniesPage.jsx frontend/src/components/companies/CompaniesPage.test.jsx frontend/src/components/companies/CompaniesPage.css frontend/src/components/companies/useCompanyEnrichmentRun.js backend/app/services/company_enrichment_run_service.py backend/app/api/companies.py backend/app/services/job_category_normalizer.py backend/tests/test_company_enrichment_run_service.py backend/tests/test_job_category_normalizer.py`  
Expected: the diff summary is empty after the final cleanup commit, which confirms all planned changes are committed.

- [ ] **Step 4: Commit any final cleanup**

```bash
git add frontend/src/components backend/app/services backend/app/api backend/tests
git commit -m "chore: finalize pagination companies and fallback work"
```
