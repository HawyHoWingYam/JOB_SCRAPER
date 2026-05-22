# Operator Perspective: Recovery and Manual Intervention

## Current Responsibilities

This perspective covers resuming blocked crawls, cancelling manual-action jobs, recovering failed auto-runs, and reconnecting progress after UI reloads.

## Current Implementation Map

- Frontend: `frontend/src/components/scraper/ScrapeProgressPanel.jsx`, `ScheduleManager.jsx`
- Backend API: `backend/app/api/crawl_jobs.py`
- Recovery service: `backend/app/services/startup_recovery_service.py`
- Recovery script: `backend/scripts/recover_failed_crawl_auto_runs.py`

## Data and Control Flow

Manual action progress includes instructions and copyable values. Resume/cancel actions post to crawl job endpoints. The UI stores a short-lived session marker after direct override so progress can reconnect after a launch race or reload.

## Tests and Coverage

- `frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`
- `frontend/src/components/scraper/ScheduleManager.test.jsx`
- `backend/tests/test_crawl_jobs_api.py`
- `backend/tests/test_recover_failed_crawl_auto_runs.py`
- `backend/tests/test_startup_recovery_service.py`

## Known Gaps or Risks

- Manual intervention still requires operators to use external browser windows.
- Progress recovery window is short and session-local.
- Failed auto-run recovery is currently script-based rather than guided in UI.
- Manual-action jobs have no explicit lease, acknowledgement, timeout, stale policy, or operator assignment.
- Cancellation is visible through API state, but worker-side cooperative cancellation remains a risk for active crawls.

## Optimization Backlog

- Add manual-action leases with acknowledge, assignee, timeout, retry, and stale escalation fields.
- Provide UI dry-run previews for recovery scripts before execution and persist the resulting recovery audit events.
- Use durable crawl job IDs and crawl event history for progress recovery across browser reloads and sessions.
- Add cooperative cancellation checks and tests for headed/manual-action crawls so cancel prevents further ingest/progress side effects.

## Follow-up Audit Questions

- Should recovery actions show a before/after preview?
- Should manual action jobs be assignable or acknowledgeable?
- Should progress recovery use durable job IDs instead of only short session markers?
