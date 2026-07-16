# Implementation Plan: JobsDB reusable-browser recovery

## 1. Backend regression test first

- Add focused coverage for `JobsDBBrowserDetailScraper` using fake Playwright,
  browser, context, page, and registry/session dependencies.
- Assert a configured `host.docker.internal` value is resolved and passed to
  `connect_over_cdp` with the registered debug port; the test must fail against
  the current hard-coded `127.0.0.1` behavior.
- Assert attempt/success log records contain `crawl_job_id`, strategy, source,
  configured CDP host, resolved connection host, and debug port.
- Cover attach exception and context-missing paths without changing the existing
  `reuse_open_browser_unavailable` manual-action interface.

Likely files:

- `backend/tests/test_jobsdb_browser_detail_scraper.py` (new focused test file)
- `backend/app/scraper/jobsdb_browser_detail_scraper.py`

## 2. Minimal JobsDB host-resolution repair

- Import and use `resolve_manual_action_cdp_connect_host`.
- Select `settings.manual_action_cdp_host` with helper-host fallback.
- Replace `127.0.0.1` in the CDP URL with the resolved host.
- Add bounded configured/resolved host fields to attach attempt, success, and
  failure log context.
- Do not change routine browser launch mode, profile selection, manual-action
  normalization, target selection, or the CTGoodJobs/OfferToday adapters.

## 3. Frontend event client and projection tests

- Add a bounded crawl-job events fetch helper using the existing JSON client.
- Add a pure projection helper for the latest `crawl.resume_requested` and its
  subsequent `crawl.manual_action_required` outcome.
- Unit-test no-attempt, accepted/in-progress, returned-to-manual-action, and
  multiple-attempt ordering by `sequence_no`.

Likely files:

- `frontend/src/api/crawlTaskActions.js`
- `frontend/src/components/scraper/recoveryAttemptUtils.js` (if extraction keeps
  the panel interface smaller)
- focused tests beside the helper or in `CrawlTasksPage.test.jsx`

## 4. Persistent Task Details feedback

- Load bounded events for the selected task without blocking the main task list.
- Refresh selected-task events after Resume and with normal selected-task
  refreshes.
- Pass the derived latest attempt into the manual recovery panel or a small
  Task Details status view.
- Render accepted/pending and returned-to-manual-action results with timestamp,
  strategy, new stage/classification, and a stable accessible test id.
- Keep both resume buttons disabled during the active POST/refresh operation.
- Preserve explicit operator confirmation; never POST from browser/helper polling.

Likely files:

- `frontend/src/components/scraper/CrawlTasksPage.jsx`
- `frontend/src/components/scraper/ManualActionRecoveryPanel.jsx`
- `frontend/src/components/scraper/CrawlTasksPage.test.jsx`

## 5. Focused verification

Run from repository root unless noted:

```powershell
python -m pytest backend/tests/test_jobsdb_browser_detail_scraper.py -q
python -m pytest backend/tests/test_cross_source_ip_recovery.py -q
python -m pytest backend/tests/test_cross_source_crawl_logging.py -q
python -m ruff check backend/app/scraper/jobsdb_browser_detail_scraper.py backend/tests/test_jobsdb_browser_detail_scraper.py
python -m compileall -q backend/app/scraper/jobsdb_browser_detail_scraper.py backend/tests/test_jobsdb_browser_detail_scraper.py
Set-Location frontend
npm test -- --run src/components/scraper/CrawlTasksPage.test.jsx
npm run build
Set-Location ..
git diff --check
```

If the projection helper has its own test file, include it in the focused Vitest
command.

## 6. Docker and live frontend verification

- Snapshot the task's current status, event count, target count, and selected
  source-listing crawl ID before restart.
- Rebuild/restart only affected services:

```powershell
docker compose up -d --build backend-api frontend-ui
docker compose ps
```

- Confirm `MANUAL_ACTION_CDP_HOST=host.docker.internal` remains present in the
  backend container.
- Confirm helper and verification browser show connected in Crawl Tasks.
- Confirm JobsDB access manually in the open browser.
- Click Resume Task with Open Browser once.
- Verify the frontend shows an accepted attempt, then the actual new outcome.
- Verify backend logs include `manual_action_attach_success` with the configured
  and resolved host fields.
- Verify task `37cb2cc5-16bc-45d2-bd1c-4b79ba84f464` preserves its 3,805-target
  scope and processes at least one detail target.
- If JobsDB returns another positive block/challenge, leave the task paused and
  capture the bounded stage/classification evidence; do not loop Resume.

## Risk and rollback points

- The highest-risk point is live CDP reachability after container restart; test
  host resolution independently before consuming a resume attempt.
- Frontend event fetching must be bounded and selected-task-only to avoid adding
  one events request per row.
- Event projection must order by `sequence_no`, not client clock timestamps.
- Do not include unrelated dirty worktree files in this task's changes.
- No database migration or destructive task-state reset is permitted.

## Verification evidence (2026-07-16)

- GitHub issue: `HawyHoWingYam/JOB_SCRAPER#9`.
- Backend focused verification: 2 JobsDB adapter tests plus 40 cross-source
  recovery/logging tests passed; Ruff and `compileall` passed.
- Frontend verification: 14 focused tests passed; targeted ESLint, Prettier,
  and the Vite production build passed.
- The live frontend issued exactly one explicit `reuse_open_browser` resume for
  task `37cb2cc5-16bc-45d2-bd1c-4b79ba84f464`. Backend logs recorded
  `manual_action_attach_success`; the task preserved its 3,805-target scope and
  advanced from zero to 212 completed details with zero crawl failures.
- Both Docker images rebuilt. `frontend-ui` and `backend-api` were recreated and
  became healthy. The user explicitly allowed the productive JobsDB child to be
  terminated for the backend recreation; the task transitioned honestly to
  `failed` rather than remaining stale `running`, while retaining its metrics
  and event history.
- The final AC4 review added a regression proving both Resume actions remain
  disabled while the latest event-derived recovery attempt is unresolved.
