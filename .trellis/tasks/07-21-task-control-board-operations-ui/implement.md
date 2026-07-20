# Task Control Board and Task Details implementation plan

## Ordered implementation

### 1. Close normalized projection gaps

- [ ] Search current Board/API consumers and choose in-place V2 versus explicit
  `version=2` compatibility; record the decision in contract tests.
- [ ] Add Source summary, Catalog health, attention item, action capability,
  schedule/latest-outcome, active-run, upcoming, and Board V2 contracts.
- [ ] Batch-build deterministic source summaries and selected-source sections;
  keep section membership/priority/order backend-owned.
- [ ] Add normalized single-task detail contract/endpoint using the same
  snapshot builder as list/Board.
- [ ] Add bounded manual-action guidance and action capabilities; exclude
  bodies/cookies/browser state/raw resume payload/unbounded IDs.
- [ ] Cover all-clear, legacy, not-found, action truth table, stable order, and
  no-N+1 behavior with focused backend tests.

Checkpoint: API can drive the complete Board/Task Details without payload
archaeology; no UI replacement yet.

### 2. Establish Board adapter and routes

- [ ] Reuse Wizard shared structured errors, decoders, route builders, timezone
  formatter, and confirmation dialog.
- [ ] Add Board API/decoder/reducer and `#scheduler?source=...` parsing.
- [ ] Add `#crawl-tasks?task=...` parsing/building and normalized single-task
  fetch.
- [ ] Add AbortController/request-version guards and prior-good refresh state.
- [ ] Test invalid/encoded IDs, back/forward, Source changes, late response
  suppression, and malformed API payloads.

### 3. Build Board shell and Source awareness

- [ ] Implement header actions linking to Wizard routes with selected Source.
- [ ] Implement Source tabs with text/count states and cross-source critical/
  manual-action banner.
- [ ] Implement Needs attention, Active runs, Upcoming, and single All clear.
- [ ] Preserve backend membership, priority, and order; do not classify raw
  statuses in React.
- [ ] Add Catalog health link to Governance and durable Task/Logs links.
- [ ] Cover loading, empty, prior-good error, manual action, worker unavailable,
  and catalog states.

### 4. Build active-run and cancellation UX

- [ ] Render listing workload and detail snapshot/future backlog with
  phase-correct labels.
- [ ] Render normalized issues/manual actions and server-declared actions.
- [ ] Confirm Cancel, call the existing cancellation helper, render
  `cancelling`, and disable repeat actions.
- [ ] Poll at one second with cleanup until terminal acknowledgement; never set
  `cancelled` optimistically.
- [ ] Test cancel rejected/API failure, unmount/route/Source cleanup, terminal
  no-cancel, and committed metrics.

### 5. Build Automation operations table

- [ ] Implement a real expandable table with schedule/timezone, scope, latest
  outcome, next run, lifecycle/Catalog health, and action menu.
- [ ] Render expanded resolved-scope/settings/current-run details from decoded
  projections.
- [ ] Add Edit/Run-now Wizard links, Pause/Resume, Archive, Logs, archived
  filter, scope-aware Restore, and permanent-delete impact.
- [ ] Carry expected revision, disable duplicate pending actions, and refetch on
  authoritative success/conflict.
- [ ] Test table semantics/disclosure, backend order, lifecycle copy, CAS
  conflict, fresh impact token, and history preservation.

Rollback point: new Board remains behind a temporary local switch; legacy
`#scheduler` stays usable.

### 6. Refactor Task Details to normalized authority

- [ ] Split Task Details into identity/status, Authority, Workload, Pacing,
  Issue/Manual Action, Recovery, Actions, and Audit link sections.
- [ ] Listing: target count/depth/estimate/run cap/pages requested.
- [ ] Detail: backlog scope/cutoff/target/outcomes/remaining/future/run cap and
  immutable pacing separately.
- [ ] Render Authored/Resolved Scope, Catalog/Automation/Plan revisions, plan
  state/fingerprint, readiness, and honest legacy fallback.
- [ ] Replace raw `manual_action` with normalized safe guidance.
- [ ] Remove ordinary raw `request_payload` rendering and prohibit new raw event
  parsing; keep a separate audit-events link.
- [ ] Support direct reload/back/forward for `?task=<id>` and not-found state.

### 7. Accessibility and visual pass

- [ ] Apply calmer dark Board/Task Details styling and safe narrow-desktop
  overflow.
- [ ] Verify tab, table, disclosure, dialog, live status, focus movement, and
  non-color meaning.
- [ ] Verify source-correct CTgoodjobs headed and OfferToday IP-block guidance.
- [ ] Add a source-search/contract test rejecting Board/Task Details reads of
  `request_payload` or raw event payloads.

### 8. Replace legacy composition

- [ ] Run Board/Wizard parity for source selection, forms/routes, runtime
  warnings, settings/history links, Automation actions, active progress,
  cancellation, and empty/error states.
- [ ] Make new Board the default `#scheduler` composition.
- [ ] Remove/retire duplicate legacy inline form/card/payload parsing only after
  parity.
- [ ] Remove the temporary switch before acceptance.
- [ ] Preserve reusable Crawl Task cancellation/manual-action/API code where it
  follows normalized contracts.

### 9. Verify and hand off to parent

Focused backend examples:

```bash
python3 -m pytest -q backend/tests/test_task_control_board_service.py
python3 -m pytest -q backend/tests/test_crawl_control_api.py -k task_control_board
python3 -m pytest -q backend/tests/test_crawl_task_snapshot_service.py
python3 -m ruff check backend/app/crawl_control/task_control_board_contracts.py backend/app/crawl_control/task_control_board_service.py backend/app/api/crawl_control.py backend/app/api/crawl_jobs.py backend/app/schemas/crawl_job.py
python3 -m compileall -q backend/app/crawl_control backend/app/api backend/app/schemas/crawl_job.py
```

Focused frontend examples:

```bash
cd frontend
npx vitest run src/features/taskControl/board
npx vitest run src/components/scraper/CrawlTasksPage.test.jsx
npm run build
```

- [ ] Board/Task deep links, lifecycle, cancellation, accessibility, raw-payload
  guard, and `git diff --check` pass.
- [ ] Legacy switch is gone; existing top-level bookmarks still work.
- [ ] Do not run the full backend suite. Hand the converged three-child tree to
  the parent for one complete frontend suite/lint/build.

## Rollback

- Switch `#scheduler` back to legacy composition without changing server state.
- Retain normalized APIs/decoders if visual rollback alone is needed.
- Never compensate UI failure by editing Catalog/Automation/plan/run rows or
  pretending cancellation is terminal.
