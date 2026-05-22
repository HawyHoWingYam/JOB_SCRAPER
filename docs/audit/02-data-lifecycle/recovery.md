# Data Lifecycle: Recovery

## Current Responsibilities

Recovery handles interrupted operations, failed crawl auto-runs, manual action resume/cancel, stale detail rows, and operator-visible backlog.

## Current Implementation Map

- Startup recovery: `backend/app/services/startup_recovery_service.py`
- Crawl recovery API: `backend/app/api/crawl_jobs.py`
- Progress snapshots: `backend/app/api/progress.py`
- Scripts: `backend/scripts/recover_failed_crawl_auto_runs.py`, `operator_health_report.py`
- Frontend progress UI: `frontend/src/components/scraper/ScrapeProgressPanel.jsx`

## Data and Control Flow

On API startup, interrupted crawl jobs, company runs, and schedule executions are reconciled. Manual action crawl jobs can be resumed or cancelled through API actions. Progress includes backlog snapshots so completed crawls with downstream pending work remain visible.

## Tests and Coverage

- `backend/tests/test_startup_recovery_service.py`
- `backend/tests/test_recover_failed_crawl_auto_runs.py`
- `backend/tests/test_crawl_jobs_api.py`
- `backend/tests/test_progress_api.py`
- `frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`

## Known Gaps or Risks

- Recovery state is spread across crawl jobs, crawl events, listing rows, schedule executions, and scripts.
- Frontend recovery marker logic relies on session storage and a short reconnect window.
- Some recovery paths can requeue work, but the operator cannot review all candidates from the UI.
- `recover_failed_crawl_auto_runs.py` supports dry-run behavior, but recovery previews are not yet a shared UI/API pattern.
- Recovery of crawl, enrichment, and manual action paths uses different persistence and event surfaces.

## Optimization Backlog

- Persist recovery audit events for startup recovery, manual resume/cancel, script dry-runs, script execution, and automatic requeue actions.
- Add UI/API dry-run previews for failed auto-run recovery and stale detail backlog recovery before execution.
- Create a backlog queue view for pending detail rows, dead letters, AI/enrichment backlog, and outbox failures.
- Use durable crawl job IDs for progress reconnection instead of relying only on short-lived session markers.

## Follow-up Audit Questions

- Should recovery actions be tracked as explicit audit events?
- Should failed auto-run recovery require a dry-run preview by default?
- Should stale downstream backlog have a dedicated queue view?
