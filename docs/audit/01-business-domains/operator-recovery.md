# Business Domain: Operator and Recovery

## Current Responsibilities

Operator and recovery flows expose runtime health, recover interrupted runs, support manual crawl intervention, and provide scripts for backlog repair.

## Current Implementation Map

- Health API: `backend/app/api/health.py`
- Operator API: `backend/app/api/operator.py`
- Health summary service: `backend/app/services/operator_health_service.py`
- Progress API: `backend/app/api/progress.py`
- Recovery service: `backend/app/services/startup_recovery_service.py`
- Scripts: `backend/scripts/operator_health_report.py`, `recover_failed_crawl_auto_runs.py`, `prepare_headed_crawl_worker_host.py`
- Frontend: `frontend/src/components/operator/OperatorHealthPage.jsx`, `scraper/ScheduleManager.jsx`, `ScrapeProgressPanel.jsx`

## Data and Control Flow

`backend/app/services/operator_health_service.py` builds the shared operator summary used by both `GET /api/v1/operator/health` and the embedded `operator` block returned from root `GET /health`. The contract unifies scheduler status, queue and worker summaries, backlog counts, headed runtime state, freshness snapshots, and issue strings in one read-only payload for visibility and triage.

Startup recovery marks interrupted company runs, crawl jobs, and schedule executions. Manual-action crawls remain visible through progress payloads and can be resumed or cancelled, but remediation is still handled through existing workflow surfaces and scripts rather than the operator health page.

## Tests and Coverage

- `backend/tests/test_operator_health_api.py`
- `backend/tests/test_health_api.py`
- `backend/tests/test_progress_api.py`
- `backend/tests/test_startup_recovery_service.py`
- `backend/tests/test_operator_health_report.py`
- `backend/tests/test_recover_failed_crawl_auto_runs.py`
- `frontend/src/components/operator/OperatorHealthPage.test.jsx`
- `frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`

## Known Gaps or Risks

- Some recovery flows remain script-first rather than API/UI-first.
- The operator health page is intentionally read-only, so operators still pivot to schedule, crawl-job, or script flows for remediation.
- Manual headed browser intervention depends on local operator environment, not only application state.
- API startup reconciles crawl, company, and schedule state, but AI enrichment recovery is still a separate worker concern.
- Manual-action jobs remain resumable without a lease, timeout, acknowledgement, or stale-action alert policy.
- Cancellation is represented in durable state, but worker-side cooperative cancellation is incomplete.

## Optimization Backlog

- Move script-first recovery paths behind dry-run API/UI actions with structured preview, execute, and audit-event records.
- Model manual action lifecycle with assignee/acknowledgement, timeout, retry policy, and stale-action notifications.
- Add recovery audit events for startup reconciliation, manual resume/cancel, script execution, and automatic requeue decisions.

## Follow-up Audit Questions

- Should every recovery script have a corresponding dry-run API or UI action?
- Should the operator health contract be documented more explicitly for external tooling or automation consumers?
- Should manual action lifecycle include explicit assignee, timeout, and retry policy?
