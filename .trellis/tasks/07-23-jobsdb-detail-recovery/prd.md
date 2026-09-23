# Fix JobsDB headless detail recovery and profile lock handling

## Goal

Make JobsDB detail crawls reliable in both normal headless execution and explicit manual recovery, so a containerized worker never sends the operator toward a browser they cannot see and a blocked task can resume without losing completed targets.

## User value

An operator can run a JobsDB detail task headlessly, handle an IP/WAF/login challenge through an intentional verification-browser button when needed, and recover stale browser state from the frontend without recreating the crawl.

## Confirmed background

- Task `bdc9e95d-080b-4933-bdd6-ed5b4caea694` is a JobsDB detail task with `crawl_mode=headless`, `status=manual_action_required`, `target_count=3907`, and `fetched_count=0`.
- `backend/app/scraper/jobsdb_browser_detail_scraper.py:192-208` currently hard-codes `headless=False` for persistent launch, even when task metadata is headless.
- `backend/app/scraper/jobsdb_browser_detail_scraper.py:373-388` turns profile launch failure into “Close all Edge windows…” guidance, which is not actionable when the profile is inside `/app/.host_browser_profiles/chromium` in a container.
- `backend/app/services/crawl_job_dispatch_service.py:635-690` already models `fresh_profile` and `reuse_open_browser` resume strategies, with fresh profile as the default.
- `frontend/src/components/scraper/ManualActionRecoveryPanel.jsx:297-567` already contains explicit helper, open-browser, reuse, and fresh-profile controls; `frontend/src/components/scraper/CrawlTaskDetails.jsx:46` still exposes only a generic Resume action.

## Requirements

- R1. Normal JobsDB detail execution must honor the reviewed `crawl_mode`: fresh headless runs launch headless; fresh headed runs launch visible.
- R2. The existing Playwright detail parser and persistence flow must remain the MVP implementation; replacing it with HTTP/API extraction is out of scope.
- R3. `fresh_profile` resumes use isolated task/run-owned profiles; `reuse_open_browser` is explicit and may attach to a separate headed verification browser for a manual recovery attempt, including for a headless task.
- R4. Recovery preserves the existing task checkpoint and retries only the statuses permitted by the classification; it never silently creates a second crawl.
- R5. Profile locks are cleaned only after liveness checks prove no matching process and no reachable live-browser registry session. Unknown liveness fails closed.
- R6. The frontend exposes explicit recovery controls and status rather than one ambiguous Resume action, including Reset when safe.
- R7. Existing tasks are handled through legacy payload normalization where their scope/checkpoint is trustworthy; no database migration is required.
- R8. Scope is JobsDB detail plus shared recovery primitives only; CTGoodJobs and OfferToday behavior changes are out of scope.

## Child task map and dependency

- `07-23-jobsdb-detail-headless`: implement and test R1/R2. Its launch-mode contract must be stable before the profile child finalizes recovery wiring.
- `07-23-jobsdb-profile-recovery`: implement and test R3-R7, depending on the headless child’s mode contract but independently verifiable with mocked launch, profile, and UI flows.

## Acceptance criteria

- [ ] A fresh JobsDB detail task reviewed as headless launches without a visible desktop browser; a fresh headed task retains visible-browser behavior.
- [ ] A headless task that raises a supported manual challenge can expose an explicit verification-browser flow; opting into it uses `reuse_open_browser` only for that recovery attempt.
- [ ] A stale profile cannot leave the task with only the old “close all Edge windows” instruction; the UI presents safe Reset/Resume choices or a concrete fail-closed diagnostic.
- [ ] Resume and Reset retain completed-target progress and do not duplicate the task’s scope.
- [ ] Existing detail parsing, persistence, and recovery status transitions remain covered by automated tests.

## Out of scope

- Replacing Playwright with JobsDB API/HTTP detail extraction.
- Changing listing scope, aggregate caps, page-depth policy, or target selection.
- Automatically changing a task’s reviewed crawl mode for ordinary execution.
- Broad behavior changes for non-JobsDB sources.
