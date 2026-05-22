# Operator Perspective: Monitoring and Health

## Current Responsibilities

This perspective covers overall backend health, worker queue state, Redis lag, database freshness, pending detail rows, and AI backlog.

## Current Implementation Map

- Backend health: `backend/app/api/health.py`
- Progress: `backend/app/api/progress.py`
- CLI report: `backend/scripts/operator_health_report.py`
- Frontend partial display: `frontend/src/components/scraper/ScheduleManager.jsx`, `ScrapeProgressPanel.jsx`

## Data and Control Flow

The health endpoint builds an operator summary from Redis consumer groups and database counts. Progress endpoints derive active/backlog snapshots from durable crawl jobs and latest events.

## Tests and Coverage

- `backend/tests/test_health_api.py`
- `backend/tests/test_operator_health_report.py`
- `backend/tests/test_progress_api.py`
- `frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`

## Known Gaps or Risks

- Health data is richer than what the UI currently shows.
- Redis group lag and database freshness are combined into one operator status.
- The frontend health call currently uses `/health`, outside the Vite `/api` proxy.
- Health does not fully cover scheduler ownership, headed host/browser state, ML sidecar readiness, outbox failures, or dead-letter remediation.
- Crawl progress and headed/manual-action state are visible in workflow panels but not unified into one monitoring surface.

## Optimization Backlog

- Build a dedicated operator health page with worker groups, Redis lag, database freshness, headed browser status, ML sidecars, scheduler state, outbox, and dead letters.
- Add thresholds and remediation hints per worker group instead of collapsing all lag/freshness checks into one status.
- Move health access under a stable API namespace or add a frontend adapter for `/health` so dev/prod routing is consistent.
- Add stale manual action, oldest pending outbox event, oldest dead letter, and pending detail backlog indicators.

## Follow-up Audit Questions

- Should operator health have a dedicated frontend page?
- Should each worker group have explicit status, lag threshold, and remediation guidance?
- Should health response include service profile availability for ML services?
