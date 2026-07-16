# Fix JobsDB reusable-browser recovery

## Goal

Restore the JobsDB manual-recovery path so a crawl paused by positive access
verification can attach from the Docker crawler to the operator's reusable
Windows browser, and make each recovery attempt visibly succeed or fail instead
of appearing to do nothing.

## Background and Confirmed Facts

- Live task `37cb2cc5-16bc-45d2-bd1c-4b79ba84f464` is a JobsDB headless detail
  crawl with 3,805 selected targets. Its first detail request received HTTP 403
  positive `ip_blocked` evidence and correctly entered resumable manual action.
- A Fresh Profile recovery attempt then reached `browser_profile_in_use`.
- Five later frontend `reuse_open_browser` attempts each returned HTTP 200 from
  the resume API and emitted `resume_requested -> requested -> started`, then
  returned to `manual_action_required` within roughly three seconds. Each backend
  attempt logged `manual_action_attach_attempt` followed by
  `manual_action_attach_failure`; none logged `manual_action_attach_success`.
- The frontend helper and browser indicators were connected when the operator
  retried, so helper health alone did not prove container-to-host CDP reachability.
- The backend container has `MANUAL_ACTION_CDP_HOST=host.docker.internal`, but
  `JobsDBBrowserDetailScraper._attach_to_live_browser()` ignores it and connects
  to `http://127.0.0.1:<debug_port>`
  (`backend/app/scraper/jobsdb_browser_detail_scraper.py:217-252`). Inside Docker,
  that address targets the container rather than the host browser.
- The CTGoodJobs adapter already resolves the configured CDP host before
  `connect_over_cdp`
  (`backend/app/scraper/ctgoodjobs_browser_page_scraper.py:294-317`), providing a
  repository-local reference for the correct topology.
- The frontend button does send `POST /crawl-jobs/{id}/resume` with
  `strategy=reuse_open_browser`; after the request it refreshes the task. A fast
  transition back to the same status makes the action appear inert, even though
  the new failure is recorded in events
  (`frontend/src/components/scraper/ManualActionRecoveryPanel.jsx:229-255,422-446`).

## Requirements

### R1. Fix JobsDB container-to-host CDP attachment

- Resolve the JobsDB CDP connection host from the same configured
  `manual_action_cdp_host` / helper-host fallback used by the other browser
  adapters; do not hard-code container localhost.
- Keep this as a minimal JobsDB adapter repair using the existing
  `resolve_manual_action_cdp_connect_host(...)` seam. Do not extract or rewrite
  the CTGoodJobs, JobsDB, and OfferToday attach flows in this urgent task.
- Preserve browser profile lookup, debug-port selection, CDP context reuse, and
  the existing resumable manual-action contract.
- Log the configured and resolved CDP host on attach attempt, success, and
  failure without exposing cookies, browser contents, or other session secrets.
- A failed attach must remain a bounded `reuse_open_browser_unavailable` manual
  action and must not consume any of the 3,805 detail targets.

### R2. Make recovery attempts observable in Crawl Tasks

- A click on Resume Task with Open Browser must immediately show that the request
  was accepted and that the task is being retried.
- If the task returns to manual action, show the new stage/reason and distinguish
  it from the prior attempt rather than silently returning to an apparently
  unchanged card.
- Keep the latest recovery-attempt result as a durable inline record in Task
  Details until the next operator action or a later task outcome supersedes it;
  do not rely on a transient toast or require View Events for basic diagnosis.
- Prevent or clearly discourage repeated clicks while the dispatched recovery
  attempt is still unresolved.
- Browser/helper connectivity must never trigger an automatic resume. Connected
  only means the recovery transport is available; the operator must explicitly
  confirm Resume after completing the JobsDB verification step.
- Preserve the shared recovery component and cross-source API contract; source-
  specific text may be used where it improves operator guidance.

### R3. Verify the real recovery path

- Add deterministic backend coverage proving that JobsDB uses the resolved
  container-to-host CDP endpoint and emits attach success/failure correctly.
- Add frontend coverage for accepted, pending, and returned-to-manual-action
  recovery feedback.
- Rebuild the affected Docker service(s), use the existing open JobsDB
  verification browser, and resume task `37cb2cc5-16bc-45d2-bd1c-4b79ba84f464`
  through the frontend.
- Verify `manual_action_attach_success`, detail processing beyond zero, preserved
  target scope, and honest final/manual state. Do not claim success from helper
  health or HTTP 200 on the resume endpoint alone.

## Acceptance Criteria

- [x] AC1: A deterministic test proves JobsDB connects to the resolved configured
  CDP host rather than `127.0.0.1` in a container-host recovery scenario.
- [x] AC2: Attach attempt/success/failure logs identify source, crawl job,
  strategy, configured host, resolved host, and debug port without secrets.
- [x] AC3: Frontend tests prove one click shows accepted/pending feedback and a
  subsequent manual-action outcome displays the new recovery reason.
- [x] AC4: Repeated user clicks cannot create an invisible resume loop while the
  previous attempt is unresolved.
- [x] AC5: Focused backend and frontend tests pass and the affected Docker
  services rebuild healthy.
- [x] AC6: Live task `37cb2cc5-16bc-45d2-bd1c-4b79ba84f464` records
  `manual_action_attach_success` and processes at least one detail target, or the
  remaining external blocker is reported with new positive evidence.
- [x] AC7: The task's original 3,805-target scope and prior event history remain
  intact through recovery.

## Out of Scope

- Redefining or implementing true routine headless behavior for JobsDB.
- CTGoodJobs headless viability research.
- Splitting Crawl Tasks into three source-specific pages or redesigning its full
  information architecture.
- Automated CAPTCHA solving, challenge evasion, or storing browser secrets.
