# Backlog UI UX Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing frontend controls for detail backlog and AI enrichment backlog explicit, safe, and verifiable from the UI.

**Architecture:** Keep the current Scheduler and AI Enrichment pages. Add small explanatory status panels and clearer submitted messages without adding new API routes or changing database models.

**Tech Stack:** React 19, Vite, Vitest, Testing Library, plain CSS.

---

### Task 1: Scheduler Detail Backlog Guidance

**Files:**
- Modify: `frontend/src/components/scraper/ScheduleManager.jsx`
- Modify: `frontend/src/components/scraper/Scheduler.css`
- Test: `frontend/src/components/scraper/ScheduleManager.test.jsx`

- [ ] **Step 1: Write the failing test**

Add a test that opens Direct Override, switches to `Job Detail Crawl`, verifies copy that explains the detail backlog, selects a listing batch, and asserts visible `74 pending`, `96 staged`, and `22 completed`.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix frontend test -- --run src/components/scraper/ScheduleManager.test.jsx -t "shows detail backlog guidance"`

Expected: FAIL because the backlog guidance copy and selected batch summary are not rendered yet.

- [ ] **Step 3: Write minimal implementation**

Add a selected-batch lookup and a small detail backlog panel below the listing batch dropdown. Show batch counts when a batch is selected and generic guidance when no batch is selected.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix frontend test -- --run src/components/scraper/ScheduleManager.test.jsx -t "shows detail backlog guidance"`

Expected: PASS.

### Task 2: AI Enrichment Backlog Guidance

**Files:**
- Modify: `frontend/src/components/ai/AIEnrichmentPage.jsx`
- Modify: `frontend/src/components/ai/AIEnrichmentPage.css`
- Test: `frontend/src/components/ai/AIEnrichmentPage.test.jsx`

- [ ] **Step 1: Write the failing test**

Add a test that loads the AI Enrichment page, verifies copy that explains pending AI jobs, changes `Pending Limit` to `3`, clicks `Run Pending`, and asserts the submitted message mentions processing up to `3` pending jobs.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix frontend test -- --run src/components/ai/AIEnrichmentPage.test.jsx -t "explains the AI backlog run"`

Expected: FAIL because the clearer guidance and submitted message are not rendered yet.

- [ ] **Step 3: Write minimal implementation**

Add backlog guidance near the Run Pending controls. Change the success message to include the normalized submitted limit.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix frontend test -- --run src/components/ai/AIEnrichmentPage.test.jsx -t "explains the AI backlog run"`

Expected: PASS.

### Task 3: Frontend Runtime Validation And Docs

**Files:**
- Modify: `docs/testing/frontend-driven-system-validation-2026-05-26.md`

- [ ] **Step 1: Run focused frontend tests**

Run: `npm --prefix frontend test -- --run src/components/scraper/ScheduleManager.test.jsx src/components/ai/AIEnrichmentPage.test.jsx`

Expected: PASS.

- [ ] **Step 2: Run frontend build**

Run: `npm --prefix frontend run build`

Expected: PASS.

- [ ] **Step 3: Validate through frontend**

Use the local frontend at `http://127.0.0.1:5173`:
- Scheduler: run `jobsdb` headed detail with `detail_limit=1` from an existing listing batch.
- AI Enrichment: run pending AI enrichment with `Pending Limit=1`.
- Job Browser: open a newly processed job detail modal and confirm description and AI fields when available.

- [ ] **Step 4: Update testing documentation**

Append the frontend-visible evidence, DB evidence, and commands to `docs/testing/frontend-driven-system-validation-2026-05-26.md`.
