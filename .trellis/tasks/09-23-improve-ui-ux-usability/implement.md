# UI/UX Usability Implementation Plan

Status: implementation approved and activated; code, automated checks, and evidence collection completed; commit review pending. Existing live deployment mismatch recorded in verification.md.

## Sequence and Dependencies

One coordinated task, implemented directly by the main session. Complete slices in order; each retains current capabilities.

1. [x] Load trellis-before-dev and the relevant frontend specs. Read the exact code before editing. Inspect git status and establish source/runtime parity for screenshots. Record existing frontend check failures separately.
2. [x] Capture representative baseline pages at 1366×768 and 1440×900. Inspect remaining R6 pages and their loading/empty/error interactions. Trace collection Task actions and existing run links. Record a page-to-requirement checklist in task notes.
3. [x] Implement R1/R2 shared styling and expanded navigation. Validate every destination, focus, layout overflow, and Settings access. This slice precedes page layout tuning.
4. [x] Implement R3 Job Browser grid and explicit-apply feedback without changing state ownership or search contracts. Preserve Jev access and all layered actions. Validate populated results in the first viewport, pending edits, failed apply, facet recovery, and applied-scope export.
5. [x] Implement R4 collection labels, descriptions, state clarity, and run handoff. Keep Scheduler/history separate. Verify action targets before deduplication and verify cancellation acknowledgement.
6. [x] Implement R5 AI queue/run feedback and presentation. Exercise empty eligible queue, API failure, active/completed/partial failure, retry, and cooperative stop with mocks.
7. [x] Implement R6 consistency improvements across remaining pages using observed findings. Preserve all form validation, review, settings, and detail capabilities. Record any page requiring no local change after shared improvements.
8. [x] Run trellis-check, frontend checks, relevant backend contract tests, and browser regression at both target sizes. Capture before/after evidence and complete AC1–AC10. Add tests only for meaningful behavior changes and regression risks, not cosmetic implementation details.
9. [ ] Present final results and limitations; follow the repository finish workflow after verification. Do not treat passing unit tests alone as visual acceptance.

## Specs to Load for Relevant Slices

- `.trellis/spec/frontend/index.md` plus shared component, state, and quality guidance.
- `.trellis/spec/backend/job-browser-search.md` and `.trellis/spec/backend/jev-system-one.md` for search/Jev behavior.
- `.trellis/spec/frontend/task-control-board-ui.md`, `task-control-wizard-ui.md`, and `crawl-task-pacing-snapshot-ui.md` for collection.
- `.trellis/spec/frontend/ai-enrichment-console.md` for AI processing.
- The frontend index's linked settings, governance, dashboard, and Job Intelligence contracts for R6 pages.

## Commands

Run from `frontend/`:

```sh
npm run lint
npm run build
npm test
```

For backend/API contracts touched by the frontend work, run from the repository root:

```sh
python3 -m pytest -q backend/tests
```

During individual slices use focused Vitest files, then the full suite once integrated:

```sh
npx vitest run src/components/JobBrowser.test.jsx src/components/FilterPanel.test.jsx src/components/jobBrowserScopeUtils.test.js src/components/jobBrowserSessionStorage.test.js src/appRoute.test.js
npx vitest run src/features/taskControl/board/TaskControlBoardPage.test.jsx src/features/taskControl/wizard/TaskControlWizard.test.jsx src/components/scraper/CrawlTasksPage.test.jsx src/components/ai/AIEnrichmentPage.test.jsx
```

Use relevant existing tests for Dashboard, Add Job, Companies, Classification, Settings, and detail views when those components change. Run existing `npm run e2e` after changes; it is Jev-specific and starts a backend through `e2e/start-jev-backend.sh`, so do not treat it as a general usability suite. Add focused browser coverage for changed navigation and workflows where the existing suite does not reach them. Prefer browser inspection with mocked network responses for mutations and failure cases. No standalone type-check script exists in package.json.

## Browser Acceptance

At both target viewports, verify: direct navigation and deep links; no accidental page overflow; readable and keyboard-accessible controls; first Job row visible; explicit filter application and stable prior results on failure; loading versus empty versus error separation; exact-run links; truthful stop/cancel states; copyable identifiers; readable timezone-aware timestamps. Check all named pages, and record which cases use fixtures versus live read-only data.

## Risk and Rollback

Shared CSS has the broadest regression risk; scoped overrides and representative screenshots must be checked before later slices. Job Browser DOM reorganization must not remount or reset draft/applied state. Collection action labels must not alter action selection or permissions. AI presentation must not change queue eligibility or replay real runs. Retain changes in separable logical slices; roll back a faulty presentation slice without database operations. Reopen design if a fix requires backend changes or different business semantics.
