# Live Progress and Manual Recovery UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the scheduler progress panel so operators can triage run state quickly, see one best next action when intervention is needed, and access diagnostics without the default card turning into a wall of text.

**Architecture:** Keep the existing backend payload contract intact and refactor the frontend rendering model in `ScrapeProgressPanel` around three layers: a primary status strip, a conditional decision panel, and a diagnostics drawer. Encode one primary display state per progress item, collapse routine diagnostics by default, and only promote rich recovery actions when the item is blocked, failed, or degraded.

**Tech Stack:** React 19, Vitest, Testing Library, plain CSS, existing scheduler/progress panel integration

---

## File Map

- `frontend/src/components/scraper/ScrapeProgressPanel.jsx`
  - Main implementation target.
  - Add display-state resolution helpers, diagnostics drawer behavior, and the new card hierarchy.
- `frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`
  - Regression and behavior tests for state priority, drawer defaults, and recovery action emphasis.
- `frontend/src/components/scraper/Scheduler.css`
  - Styling support for the new status strip, decision panel, chips, and diagnostics drawer.

### Task 1: Add a display-state model and drawer behavior to the progress panel

**Files:**
- Modify: `frontend/src/components/scraper/ScrapeProgressPanel.jsx`
- Test: `frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`

- [ ] **Step 1: Write a failing test for state priority and default diagnostics expansion**

Add these tests to `frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`:

```jsx
  it('prioritizes manual action items into the attention section and auto-expands their diagnostics', async () => {
    render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-manual': {
            crawl_job_id: 'crawl-job-manual',
            status: 'manual_action_required',
            source_site: 'ctgoodjobs',
            category_name: 'Information Technology',
            crawl_mode: 'headed',
            updated_at: '2026-05-27T11:00:00.000Z',
            manual_action: {
              stage: 'category_page',
              blocked_url: 'https://jobs.ctgoodjobs.hk/jobs',
              browser_profile_path: 'C:\\profiles\\ctgoodjobs-headed',
              browser_channel: 'msedge',
              instructions: ['Complete the verification challenge.'],
            },
          },
        },
      });
    });

    expect(await screen.findByText(/needs attention/i)).toBeInTheDocument();
    expect(screen.getByText(/manual action required/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /diagnostics/i })).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText(/stage: category_page/i)).toBeInTheDocument();
  });

  it('keeps routine running items collapsed by default and surfaces a warning chip for unstable proxy runs', async () => {
    render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-proxy': {
            crawl_job_id: 'crawl-job-proxy',
            status: 'running',
            source_site: 'ctgoodjobs',
            category_name: 'Information Technology',
            crawl_mode: 'headless',
            phase: 2,
            jobs_scraped: 5,
            detail_target_rows: 24,
            proxy_enabled: true,
            proxy_provider: 'static',
            proxy_requests_total: 8,
            proxy_requests_success: 6,
            proxy_requests_challenge: 1,
            proxy_requests_network_fail: 1,
            proxy_quarantined_total: 1,
          },
        },
      });
    });

    expect(await screen.findByText(/proxy unstable/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /diagnostics/i })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText(/proxy requests: 8/i)).not.toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the focused progress-panel test file and confirm the new expectations fail**

Run:

```bash
npm test -- ScrapeProgressPanel.test.jsx
```

Expected:

```text
FAIL
Unable to find a button with the name /diagnostics/i
```

- [ ] **Step 3: Add display-state and diagnostics-default helpers to `ScrapeProgressPanel.jsx`**

Insert these helpers near the existing section-building utilities in `frontend/src/components/scraper/ScrapeProgressPanel.jsx`:

```jsx
function resolveDisplayState(data) {
    if (data?.status === 'manual_action_required') {
        return 'manual_action_required';
    }

    if (data?.status === 'failed') {
        return 'failed';
    }

    const proxyWarningsPresent = [
        data?.proxy_requests_challenge,
        data?.proxy_requests_network_fail,
        data?.proxy_requests_http_fail,
        data?.proxy_quarantined_total,
    ].some((value) => Number(value || 0) > 0);

    if (data?.status === 'running' && proxyWarningsPresent) {
        return 'running_with_warning';
    }

    if (data?.status === 'running' || data?.status === 'ai_running' || data?.status === 'dispatching') {
        return 'running';
    }

    if (data?.status === 'queued') {
        return 'queued';
    }

    if (data?.status === 'completed' || data?.status === 'completed_with_ai_failures') {
        return 'completed';
    }

    if (data?.status === 'cancelled') {
        return 'cancelled';
    }

    return data?.status || 'running';
}

function shouldExpandDiagnosticsByDefault(displayState) {
    return displayState === 'manual_action_required' || displayState === 'failed';
}

function buildStatusSignals({ displayState, proxyEnabled, proxyWarningsPresent }) {
    const chips = [];

    if (displayState === 'manual_action_required') {
        chips.push('Intervention required');
    }

    if (displayState === 'failed') {
        chips.push('Failure');
    }

    if (displayState === 'running_with_warning' && proxyEnabled && proxyWarningsPresent) {
        chips.push('Proxy unstable');
    }

    return chips;
}
```

- [ ] **Step 4: Refactor `ProgressItem` to use the display-state model and a diagnostics drawer toggle**

Update the start of `ProgressItem` in `frontend/src/components/scraper/ScrapeProgressPanel.jsx` to include the new state model:

```jsx
function ProgressItem({
    taskKey,
    data,
    onNavigateToAI,
    onResumeCrawlJob,
    onCancelCrawlJob,
    onOpenManualActionBrowser,
    onGetManualActionReuseStatus,
    onCloseManualActionWindows
}) {
    const [liveSessionMetadata, setLiveSessionMetadata] = useState(null);
    const [reuseStatusError, setReuseStatusError] = useState(null);
    const [showReuseRecoveryPrompt, setShowReuseRecoveryPrompt] = useState(false);
    const [showFreshResumeWarning, setShowFreshResumeWarning] = useState(false);
    const [isReuseChecking, setIsReuseChecking] = useState(false);
    const [isResumeSubmitting, setIsResumeSubmitting] = useState(null);
    const displayState = resolveDisplayState(data);
    const proxyWarningsPresent = [
        data?.proxy_requests_challenge,
        data?.proxy_requests_network_fail,
        data?.proxy_requests_http_fail,
        data?.proxy_quarantined_total,
    ].some((value) => Number(value || 0) > 0);
    const [isDiagnosticsOpen, setIsDiagnosticsOpen] = useState(
        shouldExpandDiagnosticsByDefault(displayState)
    );
```

Then extend the existing reset effect to resync drawer defaults on run/state changes:

```jsx
    useEffect(() => {
        setLiveSessionMetadata(null);
        setReuseStatusError(null);
        setShowReuseRecoveryPrompt(false);
        setShowFreshResumeWarning(false);
        setIsReuseChecking(false);
        setIsResumeSubmitting(null);
        setIsDiagnosticsOpen(shouldExpandDiagnosticsByDefault(displayState));
    }, [crawl_job_id, manual_action?.stage, status, displayState]);
```

- [ ] **Step 5: Re-run the focused progress-panel test file and confirm the new state-model expectations pass**

Run:

```bash
npm test -- ScrapeProgressPanel.test.jsx
```

Expected:

```text
PASS
```

### Task 2: Rebuild the card into status strip, decision panel, and diagnostics drawer

**Files:**
- Modify: `frontend/src/components/scraper/ScrapeProgressPanel.jsx`
- Modify: `frontend/src/components/scraper/Scheduler.css`
- Test: `frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`

- [ ] **Step 1: Add a failing test that enforces one recovery-focused primary action surface**

Add this test to `frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`:

```jsx
  it('renders a recovery decision panel for manual-action jobs with a primary resume action and collapsible diagnostics', async () => {
    render(<ScrapeProgressPanel isVisible onClose={vi.fn()} />);

    const stream = latestEventSource();
    act(() => {
      stream.emitOpen();
      stream.emitMessage({
        all: {
          'crawl-job-456': {
            crawl_job_id: 'crawl-job-456',
            status: 'manual_action_required',
            source_site: 'ctgoodjobs',
            category_name: 'Information Technology',
            crawl_mode: 'headed',
            manual_action: {
              stage: 'browser_profile_in_use',
              blocked_url: 'https://jobs.ctgoodjobs.hk/jobs',
              browser_profile_path: 'C:\\profiles\\ctgoodjobs-headed',
              browser_channel: 'msedge',
              instructions: [
                'Close all Edge windows that use the listed automation profile.',
                'Return to the app and click Resume.',
              ],
            },
          },
        },
      });
    });

    expect(await screen.findByText(/next step/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /resume using open browser/i })).toHaveClass('progress-primary-action');
    expect(screen.getByRole('button', { name: /close profile windows/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /diagnostics/i })).toHaveAttribute('aria-expanded', 'true');
  });
```

- [ ] **Step 2: Run the focused test file and confirm the recovery-panel test fails before the JSX refactor**

Run:

```bash
npm test -- ScrapeProgressPanel.test.jsx
```

Expected:

```text
FAIL
Unable to find an element with the text /next step/i
```

- [ ] **Step 3: Replace the existing manual-action layout with status-strip, decision-panel, and diagnostics sections**

Refactor the `status === 'manual_action_required'` branch in `frontend/src/components/scraper/ScrapeProgressPanel.jsx` so the returned JSX follows this structure:

```jsx
        const statusSignals = buildStatusSignals({
            displayState,
            proxyEnabled: proxy_enabled,
            proxyWarningsPresent,
        });

        return (
            <div className="progress-item warning">
                {renderHeader('Manual Action Required', 'warning')}

                <div className="progress-status-strip">
                    <div className="progress-status-summary">
                        <span className="progress-status-title">Next step</span>
                        <span className="progress-status-subtitle">
                            Resume this run after resolving the browser/profile blocker.
                        </span>
                    </div>
                    <div className="progress-status-signal-row">
                        {statusSignals.map((signal) => (
                            <span key={`${taskId}-${signal}`} className="progress-status-chip">
                                {signal}
                            </span>
                        ))}
                    </div>
                </div>

                {renderMetricLines(metricLines)}

                <div className="progress-decision-panel">
                    <button
                        type="button"
                        className="progress-link-button progress-primary-action"
                        onClick={handleResumeUsingOpenBrowser}
                        disabled={isReuseChecking || isResumeSubmitting === 'reuse_open_browser'}
                    >
                        {isReuseChecking || isResumeSubmitting === 'reuse_open_browser'
                            ? 'Attaching...'
                            : 'Resume Using Open Browser'}
                    </button>
                    <div className="progress-secondary-actions">
                        <button
                            type="button"
                            className="progress-link-button"
                            onClick={handleResumeFresh}
                            disabled={isResumeSubmitting === 'fresh_profile'}
                        >
                            Resume Fresh
                        </button>
                        <button
                            type="button"
                            className="progress-link-button"
                            onClick={handleCloseProfileWindows}
                        >
                            Close Profile Windows
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

                <button
                    type="button"
                    className="progress-diagnostics-toggle"
                    aria-expanded={isDiagnosticsOpen ? 'true' : 'false'}
                    onClick={() => setIsDiagnosticsOpen((current) => !current)}
                >
                    Diagnostics
                </button>

                {isDiagnosticsOpen && (
                    <div className="progress-diagnostics-drawer">
                        <div className="progress-diagnostics-section">
                            <strong>Run timing</strong>
                            {renderTimingBlock()}
                        </div>
                        <div className="progress-diagnostics-section">
                            <strong>Technical diagnostics</strong>
                            <div className="progress-text">Stage: {manual_action.stage || '-'}</div>
                            <div className="progress-text">{manual_action.blocked_url || '-'}</div>
                            <div className="progress-text">
                                Browser Profile Path: {manual_action.browser_profile_path || '-'}
                            </div>
                            <div className="progress-text">
                                Browser Channel: {manual_action.browser_channel || '-'}
                            </div>
                        </div>
                    </div>
                )}
            </div>
        );
```

- [ ] **Step 4: Bring the routine-card branch onto the same status-strip and diagnostics-toggle pattern**

Refactor the non-manual-action return block in `frontend/src/components/scraper/ScrapeProgressPanel.jsx` so routine cards expose the summary first and keep details behind the drawer:

```jsx
    const statusSignals = buildStatusSignals({
        displayState,
        proxyEnabled: proxy_enabled,
        proxyWarningsPresent,
    });

    return (
        <div className={`progress-item ${statusClass}`}>
            {renderHeader(statusText, statusClass)}

            <div className="progress-status-strip">
                <div className="progress-status-summary">
                    <span className="progress-status-title">{statusText}</span>
                    <span className="progress-status-subtitle">
                        Last updated: {formatTaskTimestamp(data?.updated_at || completed_at || started_at || queued_at)}
                    </span>
                </div>
                <div className="progress-status-signal-row">
                    {statusSignals.map((signal) => (
                        <span key={`${taskId}-${signal}`} className="progress-status-chip">
                            {signal}
                        </span>
                    ))}
                </div>
            </div>

            {renderMetricLines(metricLines)}

            {(detailLines.length > 0 || ai_run_id) && (
                <>
                    <button
                        type="button"
                        className="progress-diagnostics-toggle"
                        aria-expanded={isDiagnosticsOpen ? 'true' : 'false'}
                        onClick={() => setIsDiagnosticsOpen((current) => !current)}
                    >
                        Diagnostics
                    </button>

                    {isDiagnosticsOpen && (
                        <div className="progress-diagnostics-drawer">
                            <div className="progress-diagnostics-section">
                                <strong>Run timing</strong>
                                {renderTimingBlock()}
                            </div>
                            <div className="progress-diagnostics-section">
                                <strong>Technical diagnostics</strong>
                                {detailLines.map((line) => (
                                    <div key={`${taskId}-${line}`} className="progress-text">{line}</div>
                                ))}
                            </div>
                        </div>
                    )}
                </>
            )}

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
```

- [ ] **Step 5: Add the CSS needed for the three-layer card hierarchy**

Append these rules to `frontend/src/components/scraper/Scheduler.css`:

```css
.progress-status-strip {
    display: flex;
    justify-content: space-between;
    gap: var(--space-3);
    align-items: flex-start;
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: rgba(255, 255, 255, 0.03);
}

.progress-status-summary {
    display: grid;
    gap: var(--space-1);
}

.progress-status-title {
    color: var(--color-text-primary);
    font-size: var(--text-sm);
    font-weight: 800;
}

.progress-status-subtitle {
    color: var(--color-text-secondary);
    font-size: var(--text-xs);
}

.progress-status-signal-row {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: var(--space-2);
}

.progress-status-chip {
    display: inline-flex;
    align-items: center;
    min-height: 24px;
    padding: 2px 10px;
    border: 1px solid rgba(216, 166, 87, 0.28);
    border-radius: var(--radius-full);
    background: rgba(216, 166, 87, 0.12);
    color: var(--color-accent-hover);
    font-size: var(--text-xs);
    font-weight: 700;
}

.progress-decision-panel,
.progress-diagnostics-drawer {
    display: grid;
    gap: var(--space-3);
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: rgba(255, 255, 255, 0.03);
}

.progress-secondary-actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
}

.progress-primary-action {
    border-color: rgba(79, 191, 139, 0.28);
    background: rgba(79, 191, 139, 0.12);
    color: var(--color-success-hover);
}

.progress-diagnostics-toggle {
    align-self: flex-start;
}

.progress-diagnostics-section {
    display: grid;
    gap: var(--space-2);
}
```

- [ ] **Step 6: Re-run the focused progress-panel test file and confirm the card-hierarchy tests pass**

Run:

```bash
npm test -- ScrapeProgressPanel.test.jsx
```

Expected:

```text
PASS
```

### Task 3: Verify integration and rendered behavior

**Files:**
- Test: `frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`
- Test: `frontend/src/components/scraper/ScheduleManager.test.jsx`

- [ ] **Step 1: Run the progress-panel and scheduler tests together**

Run:

```bash
npm test -- ScrapeProgressPanel.test.jsx ScheduleManager.test.jsx
```

Expected:

```text
PASS
No regressions in scheduler-panel integration
```

- [ ] **Step 2: Run the full frontend test suite**

Run:

```bash
npm test
```

Expected:

```text
All frontend test files pass
```

- [ ] **Step 3: Run the frontend production build**

Run:

```bash
npm run build
```

Expected:

```text
vite build completes successfully
```

- [ ] **Step 4: Produce one rendered evidence check for the updated hierarchy**

Run one browser-oriented verification after the implementation is in place, such as:

```bash
# Start the existing frontend app in the normal local workflow, then capture the scheduler surface.
# The exact command should match the repo's current frontend startup path.
```

Expected:

```text
A rendered scheduler/progress view shows:
- compact status strip
- visible primary action for manual-action runs
- diagnostics hidden by default for routine runs
- diagnostics expanded by default for failed/manual-action runs
```

- [ ] **Step 5: Record the exact commands and results in the implementation handoff**

Document:

- targeted component test command and result
- scheduler integration test command and result
- full frontend suite command and result
- build command and result
- rendered/snapshot verification result
