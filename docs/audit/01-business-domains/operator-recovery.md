# Business Domain: Operator and Recovery

## Current Responsibilities

Operator and recovery flows expose runtime health, recover interrupted runs, support manual crawl intervention, and provide scripts for backlog repair.

## Current Implementation Map

- Health API: `backend/app/api/health.py`
- Progress API: `backend/app/api/progress.py`
- Recovery service: `backend/app/services/startup_recovery_service.py`
- Scripts: `backend/scripts/operator_health_report.py`, `recover_failed_crawl_auto_runs.py`, `prepare_headed_crawl_worker_host.py`
- Frontend: `frontend/src/components/scraper/ScrapeProgressPanel.jsx`, `ScheduleManager.jsx`

## Data and Control Flow

Health aggregates Redis stream lag, worker groups, database freshness, pending detail rows, and AI backlog. Startup recovery marks interrupted company runs, crawl jobs, and schedule executions. Manual action crawls remain visible through progress payloads and can be resumed or cancelled.

## Tests and Coverage

- `backend/tests/test_health_api.py`
- `backend/tests/test_progress_api.py`
- `backend/tests/test_startup_recovery_service.py`
- `backend/tests/test_operator_health_report.py`
- `backend/tests/test_recover_failed_crawl_auto_runs.py`
- `frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`

## Known Gaps or Risks

- Some recovery flows remain script-first rather than API/UI-first.
- Health output is broad, but frontend only surfaces a small subset.
- Manual headed browser intervention depends on local operator environment, not only application state.
- API startup reconciles crawl, company, and schedule state, but AI enrichment recovery is still a separate worker concern.
- Manual-action jobs remain resumable without a lease, timeout, acknowledgement, or stale-action alert policy.
- Cancellation is represented in durable state, but worker-side cooperative cancellation is incomplete.

## Optimization Backlog

- Add an operator health surface that includes crawl streams, headed worker state, scheduler ownership, outbox failures, dead letters, ML sidecars, and host browser readiness.
- Move script-first recovery paths behind dry-run API/UI actions with structured preview, execute, and audit-event records.
- Model manual action lifecycle with assignee/acknowledgement, timeout, retry policy, and stale-action notifications.
- Add recovery audit events for startup reconciliation, manual resume/cancel, script execution, and automatic requeue decisions.

## Follow-up Audit Questions

- Should every recovery script have a corresponding dry-run API or UI action?
- Should operator health be versioned and documented as a public operator contract?
- Should manual action lifecycle include explicit assignee, timeout, and retry policy?
