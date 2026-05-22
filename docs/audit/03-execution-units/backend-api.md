# Execution Unit: Backend API

## Current Responsibilities

The backend API owns the public HTTP boundary, CORS, startup recovery for API-owned work, schedule CRUD, manual schedule execution, direct override dispatch, the root health surface, the dedicated operator health surface, and proxying to internal retrieval and recommendation services.

## Current Implementation Map

- Entrypoint and lifespan: `backend/app/main.py`
- Route composition: `backend/app/api/__init__.py`
- Core routes: `backend/app/api/health.py`, `operator.py`, `crawl_jobs.py`, `schedules.py`, `progress.py`
- Self-prefixed routes: `backend/app/api/ai.py`, `settings.py`, `stats.py`
- Compatibility routes: `backend/app/api/category_routes.py`
- Scheduler runtime status reader: `backend/app/services/scheduler_runtime.py`
- Operator health summary: `backend/app/services/operator_health_service.py`
- Crawl dispatch: `backend/app/services/crawl_job_dispatch_service.py`
- Startup recovery: `backend/app/services/startup_recovery_service.py`
- Internal service clients: `backend/app/services/retrieval_client.py`, `recommendation_client.py`
- Docker services: `backend-api`, `scheduler-worker` in `docker-compose.yml`
- Runtime helper: `backend/app/server_runtime.py`

## Data and Control Flow

The API lifespan runs `StartupRecoveryService.recover_interrupted_operations` with `recover_ai_runs=False` and recovery enabled for company enrichment runs, crawl jobs, and schedule executions. AI enrichment recovery remains enrichment-worker owned.

`backend-api` no longer starts APScheduler during lifespan. Scheduler ownership is delegated to `scheduler-worker`, and the API only reads worker heartbeat state through `scheduler_runtime_heartbeats` for `/health`, `/api/v1/operator/health`, and `/api/v1/capabilities`.

`GET /api/v1/operator/health` returns the shared operator contract from `backend/app/services/operator_health_service.py`. Root `GET /health` calls the same service and embeds the result under `operator`, adding only top-level backend service status and LLM degradation checks. The shared contract includes scheduler status, queue summaries, backlog counts, headed runtime readiness, freshness snapshots, worker summaries, and issue strings.

Manual per-schedule execute (`POST /api/v1/schedules/{id}/run`) and direct override (`POST /api/v1/schedules/run-now`, plus crawl-job APIs) stay API-owned. They dispatch durable crawl jobs through `CrawlJobDispatchService` even when scheduler-worker is stale or missing. Schedule list/detail responses expose the worker-reconciled `next_run_at` stored on `scrape_schedules`.

## Tests and Coverage

- `backend/tests/test_api_runtime.py`
- `backend/tests/test_operator_health_api.py`
- `backend/tests/test_health_api.py`
- `backend/tests/test_scheduler_dispatcher.py`
- `backend/tests/test_capabilities_api.py`
- `backend/tests/test_validate_audit_docs.py`
- `backend/tests/test_startup_recovery_service.py`
- API-specific tests across `backend/tests/test_*_api.py`

## Known Gaps or Risks

- Schedule CRUD succeeds while scheduler-worker is stale, but cron behavior will not reflect those changes until the worker heartbeats again and reconciles.
- Exposed `next_run_at` values are authoritative only as of the latest successful scheduler-worker reconcile.
- Route namespace conventions remain mixed across root health, compatibility categories, `/api/v1` routers, and self-prefixed routers.
- Internal retrieval and recommendation sidecar availability is still discovered from configuration metadata rather than end-to-end active checks.
- Startup recovery failures are logged and startup continues; readiness does not hard-fail on recovery issues.
- The dedicated operator route and embedded root health summary share a contract, but there is still a dual-surface health model for clients to understand.

## Optimization Backlog

- Normalize route ownership so compatibility routes are clearly temporary and all operator APIs have a documented namespace.

## Follow-up Audit Questions

- Should startup recovery failure make `/health` degraded until an operator acknowledges or reruns recovery?
- Should root `/health` and `/api/v1/operator/health` remain separate long-term, or should one become the canonical operator-facing contract?
- Should retrieval and recommendation proxy configuration be validated during startup or only reported as capability metadata?
