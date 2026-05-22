# Operator Perspective: Monitoring and Health

## Current Responsibilities

This perspective covers overall backend health plus the unified operator visibility surface for scheduler status, worker queues, backlog counts, headed runtime state, issue summaries, and freshness signals.

## Current Implementation Map

- Backend health: `backend/app/api/health.py`
- Dedicated operator route: `backend/app/api/operator.py`
- Shared summary service: `backend/app/services/operator_health_service.py`
- Progress: `backend/app/api/progress.py`
- CLI report: `backend/scripts/operator_health_report.py`
- Frontend views: `frontend/src/components/operator/OperatorHealthPage.jsx`, `scraper/ScheduleManager.jsx`, `ScrapeProgressPanel.jsx`

## Data and Control Flow

`backend/app/services/operator_health_service.py` builds the operator summary once. Root `GET /health` embeds that summary under `operator`, and `GET /api/v1/operator/health` exposes the same contract directly for the frontend operator page. The payload combines queue and worker summaries, scheduler state, headed runtime readiness, backlog counts, freshness snapshots, and issue strings for visibility and triage rather than remediation.

Progress endpoints still derive active/manual-action crawl state from durable crawl jobs and latest events.

## Tests and Coverage

- `backend/tests/test_operator_health_api.py`
- `backend/tests/test_health_api.py`
- `backend/tests/test_operator_health_report.py`
- `backend/tests/test_progress_api.py`
- `frontend/src/components/operator/OperatorHealthPage.test.jsx`
- `frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`

## Known Gaps or Risks

- The operator page is read-only, so it helps triage but does not execute recovery or remediation.
- `ScheduleManager` still uses embedded operator data from root `/health`, while the dedicated page uses `/api/v1/operator/health`.
- The contract covers scheduler, queues, backlog, headed runtime, and issues in one place, but it does not add remediation hints or operator actions.
- Crawl progress and manual-action workflow state still live in workflow panels rather than the operator page.

## Optimization Backlog

- Add thresholds and remediation hints per worker group instead of collapsing all lag/freshness checks into one status.
- Align the remaining root `/health` consumers with the dedicated operator endpoint or keep a documented reason for both surfaces.
- Add stale manual action, oldest pending outbox event, oldest dead letter, and pending detail backlog indicators.

## Follow-up Audit Questions

- Should each worker group have explicit status, lag threshold, and remediation guidance?
- Should health response include service profile availability for ML services?
- Should the operator page eventually surface linked drill-downs into schedules, crawl jobs, or dead letters without adding write actions?
