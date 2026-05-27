# Direct Override Form UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the direct-override form clearer and safer by separating listing/detail intent, surfacing inline readiness feedback before launch, and showing an operator-readable request summary tied to the effective payload.

**Architecture:** Keep the backend payload contract unchanged. Refactor the `ScheduleManager` direct-override surface around a mode-sensitive header, clearer numeric/scope controls, and a readiness summary block generated from the same normalized request logic already used before POST.

**Tech Stack:** React 19, Vitest, Testing Library, plain CSS, existing scheduler control-plane APIs

---

## File Map

- `frontend/src/components/scraper/ScheduleManager.jsx`
  - Main implementation target.
  - Extend direct-override helper builders and form rendering.
- `frontend/src/components/scraper/ScheduleManager.test.jsx`
  - TDD coverage for listing/detail summaries, inline readiness, and payload preservation.
- `frontend/src/components/scraper/Scheduler.css`
  - Styling support for the direct-override mode header and readiness summary.

### Task 1: Add inline launch-readiness feedback and explicit mode summaries

**Files:**
- Modify: `frontend/src/components/scraper/ScheduleManager.jsx`
- Test: `frontend/src/components/scraper/ScheduleManager.test.jsx`

- [ ] **Step 1: Write failing tests for mode-specific readiness copy**

Add these tests to `frontend/src/components/scraper/ScheduleManager.test.jsx`:

```jsx
  it('shows listing-mode readiness guidance before any sector is selected', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));

    expect(screen.getByText(/listing mode/i)).toBeInTheDocument();
    expect(screen.getByText(/select at least one sector to launch this listing crawl/i)).toBeInTheDocument();
    expect(screen.getByText(/launch blocked/i)).toBeInTheDocument();
  });

  it('shows detail-mode readiness guidance and explains the backlog scope when switched to detail mode', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
    fireEvent.change(screen.getByRole('combobox', { name: /crawl phase/i }), {
      target: { value: 'detail' },
    });

    expect(screen.getByText(/detail mode/i)).toBeInTheDocument();
    expect(screen.getByText(/recover eligible detail backlog/i)).toBeInTheDocument();
    expect(screen.getByText(/launch blocked/i)).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the focused scheduler test file and confirm the new expectations fail**

Run:

```bash
npm test -- ScheduleManager.test.jsx
```

Expected:

```text
FAIL
Unable to find text matching /listing mode/i
```

- [ ] **Step 3: Add helper builders for launch readiness and mode header copy**

Insert these helpers into `frontend/src/components/scraper/ScheduleManager.jsx` near the existing direct-override summary helpers:

```jsx
function buildImmediateRunReadiness(form, sourceSite) {
    const request = buildImmediateScrapePayload(form, sourceSite);
    const crawlPhase = form?.crawl_phase || resolveDefaultCrawlPhase();
    const selectedSectorCount = Array.isArray(form?.category_ids) ? form.category_ids.length : 0;
    const hasBatchFilter = Boolean(`${form?.source_listing_crawl_job_id ?? ''}`.trim());

    if (request.error) {
        return {
            isReady: false,
            statusLabel: 'Launch blocked',
            detail: request.error,
        };
    }

    return {
        isReady: true,
        statusLabel: 'Ready to launch',
        detail: crawlPhase === 'listing'
            ? `Listing crawl will scan ${selectedSectorCount} selected sector${selectedSectorCount === 1 ? '' : 's'}.`
            : hasBatchFilter
                ? 'Detail crawl will narrow recovery to the selected legacy listing batch.'
                : 'Detail crawl will recover eligible backlog from the selected sector scope.',
    };
}

function buildImmediateRunModeCopy(form) {
    const crawlPhase = form?.crawl_phase || resolveDefaultCrawlPhase();

    if (crawlPhase === 'detail') {
        return {
            eyebrow: 'Detail Mode',
            title: 'Recover eligible detail backlog',
            description: 'Use sectors and optional legacy batch narrowing to target pending detail work.',
        };
    }

    return {
        eyebrow: 'Listing Mode',
        title: 'Collect listing pages and job IDs',
        description: 'Select sectors and page depth before dispatching a new listing crawl.',
    };
}
```

- [ ] **Step 4: Render the new mode header and readiness block in the direct-override panel**

Update the direct-override form section in `frontend/src/components/scraper/ScheduleManager.jsx` to calculate and render:

```jsx
    const immediateRunSummary = buildImmediateRunSummary(immediateForm, currentSourceSite, categories);
    const immediateRunReadiness = buildImmediateRunReadiness(immediateForm, currentSourceSite);
    const immediateRunModeCopy = buildImmediateRunModeCopy(immediateForm);
```

Then replace the top summary area with:

```jsx
                    <div className="override-mode-panel">
                        <span className="scheduler-panel-kicker">{immediateRunModeCopy.eyebrow}</span>
                        <strong className="override-summary-title">{immediateRunModeCopy.title}</strong>
                        <p className="form-hint">{immediateRunModeCopy.description}</p>
                    </div>

                    <div className="override-summary-panel">
                        <span className="scheduler-panel-kicker">{immediateRunSummary.title}</span>
                        <strong className="override-summary-title">{immediateRunSummary.description}</strong>
                        <div className="override-summary-metrics">
                            {immediateRunSummary.metrics.map((metric) => (
                                <span key={metric} className="override-summary-chip">
                                    {metric}
                                </span>
                            ))}
                        </div>
                    </div>

                    <div className={`override-readiness-panel ${immediateRunReadiness.isReady ? 'ready' : 'blocked'}`}>
                        <span className="scheduler-panel-kicker">{immediateRunReadiness.statusLabel}</span>
                        <strong>{immediateRunReadiness.detail}</strong>
                    </div>
```

- [ ] **Step 5: Re-run the focused scheduler test file and confirm the readiness-copy tests pass**

Run:

```bash
npm test -- ScheduleManager.test.jsx
```

Expected:

```text
PASS
```

### Task 2: Make request consequences clearer in the form controls

**Files:**
- Modify: `frontend/src/components/scraper/ScheduleManager.jsx`
- Modify: `frontend/src/components/scraper/Scheduler.css`
- Test: `frontend/src/components/scraper/ScheduleManager.test.jsx`

- [ ] **Step 1: Add failing tests for clearer numeric and batch-narrowing semantics**

Add these tests to `frontend/src/components/scraper/ScheduleManager.test.jsx`:

```jsx
  it('shows listing-specific numeric helper copy in listing mode and detail-specific helper copy in detail mode', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));

    expect(screen.getByText(/set how many listing pages to scan per selected sector/i)).toBeInTheDocument();

    fireEvent.change(screen.getByRole('combobox', { name: /crawl phase/i }), {
      target: { value: 'detail' },
    });

    expect(screen.getByText(/set the maximum number of eligible detail rows to recover/i)).toBeInTheDocument();
  });

  it('shows a readable launch summary for detail mode when a legacy batch filter is selected', async () => {
    render(<ScheduleManager onNavigateToAI={vi.fn()} />);

    await screen.findByText('Task Control Board');
    fireEvent.click(screen.getByRole('button', { name: /direct override/i }));
    fireEvent.change(screen.getByRole('combobox', { name: /crawl phase/i }), {
      target: { value: 'detail' },
    });

    const batchSelect = await screen.findByRole('combobox', { name: /legacy listing batch filter/i });
    fireEvent.change(batchSelect, { target: { value: 'listing-batch-123' } });

    expect(screen.getByText(/legacy batch filter: jobsdb batch listing-batch-123/i)).toBeInTheDocument();
    expect(screen.getByText(/detail crawl will narrow recovery to the selected legacy listing batch/i)).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the focused scheduler test file and confirm the new helper-copy expectations fail**

Run:

```bash
npm test -- ScheduleManager.test.jsx
```

Expected:

```text
FAIL
Unable to find text matching /set how many listing pages to scan per selected sector/i
```

- [ ] **Step 3: Add mode-specific helper copy directly under the numeric control and legacy batch filter**

Update the numeric-control section in `frontend/src/components/scraper/ScheduleManager.jsx` to include helper copy:

```jsx
                    <div className="cyber-form-group">
                        <label>{immediateForm.crawl_phase === 'detail' ? 'Detail Crawl Target' : 'Max Depth (Pages)'}</label>
                        <input
                            type="number"
                            className="premium-input"
                            min="1"
                            max={immediateForm.crawl_phase === 'detail' ? '5000' : '1000'}
                            value={immediateForm.crawl_phase === 'detail' ? immediateForm.detail_limit : immediateForm.max_pages}
                            onChange={(e) => setImmediateForm(prev => ({
                                ...prev,
                                ...(immediateForm.crawl_phase === 'detail'
                                    ? { detail_limit: parseInt(e.target.value) || 100 }
                                    : { max_pages: parseInt(e.target.value) || 3 })
                            }))}
                        />
                        <p className="form-hint">
                            {immediateForm.crawl_phase === 'detail'
                                ? 'Set the maximum number of eligible detail rows to recover in this run.'
                                : 'Set how many listing pages to scan per selected sector.'}
                        </p>
                    </div>
```

Then add clarifying copy above or below the legacy batch filter block:

```jsx
                            <p className="form-hint backlog-guidance-muted">
                                Optional narrowing control. Leave blank to recover eligible backlog across the selected sectors.
                            </p>
```

- [ ] **Step 4: Re-run the focused scheduler test file and confirm the helper-copy and batch-summary tests pass**

Run:

```bash
npm test -- ScheduleManager.test.jsx
```

Expected:

```text
PASS
```

- [ ] **Step 5: Add styling for the new mode and readiness panels**

Append these rules to `frontend/src/components/scraper/Scheduler.css`:

```css
.override-mode-panel,
.override-readiness-panel {
    display: grid;
    gap: var(--space-2);
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: rgba(255, 255, 255, 0.03);
}

.override-readiness-panel.ready {
    border-color: rgba(79, 191, 139, 0.28);
    background: rgba(79, 191, 139, 0.08);
}

.override-readiness-panel.blocked {
    border-color: rgba(233, 185, 73, 0.28);
    background: rgba(233, 185, 73, 0.08);
}
```

### Task 3: Preserve payload behavior and verify the full frontend

**Files:**
- Test: `frontend/src/components/scraper/ScheduleManager.test.jsx`
- Test: `frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`
- Test: `frontend/src/App.test.jsx`

- [ ] **Step 1: Run focused scheduler and progress tests together**

Run:

```bash
npm test -- ScheduleManager.test.jsx ScrapeProgressPanel.test.jsx
```

Expected:

```text
PASS
```

- [ ] **Step 2: Run the full frontend test suite**

Run:

```bash
npm test
```

Expected:

```text
All frontend tests pass
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

- [ ] **Step 4: Capture the verification summary in the implementation handoff**

Document:

- focused scheduler tests
- focused progress panel regression tests
- full frontend suite
- production build
