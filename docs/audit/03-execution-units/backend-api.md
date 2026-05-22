# Execution Unit: Backend API

## Current Responsibilities

The backend API owns the public HTTP boundary, CORS, route composition, startup recovery for API-owned work, scheduler runtime startup, operator health, and proxying to internal retrieval and recommendation services.

## Current Implementation Map

- Entrypoint and lifespan: `backend/app/main.py`
- Route composition: `backend/app/api/__init__.py`
- Core routes: `backend/app/api/health.py`, `jobs.py`, `companies.py`, `crawl_jobs.py`, `schedules.py`, `progress.py`
- Self-prefixed routes: `backend/app/api/ai.py`, `settings.py`, `stats.py`
- Compatibility routes: `backend/app/api/category_routes.py`
- Scheduler runtime: `backend/app/services/scheduler_runtime.py`, `scheduler_service.py`, `backend/app/workers/run_scheduler_worker.py`
- Startup recovery: `backend/app/services/startup_recovery_service.py`
- Internal service clients: `backend/app/services/retrieval_client.py`, `recommendation_client.py`
- Docker services: `backend-api`, `scheduler-worker` in `docker-compose.yml`
- Runtime helper: `backend/app/server_runtime.py`

## Data and Control Flow

The API lifespan runs `StartupRecoveryService.recover_interrupted_operations` with `recover_ai_runs=False` and recovery enabled for company enrichment runs, crawl jobs, and schedule executions. AI enrichment recovery is intentionally owned by the enrichment worker through `recover_ai_runs_only`.

After recovery, `backend/app/main.py` calls `initialize_scheduler_runtime`, so the API process still starts the scheduler. A `scheduler-worker` Compose service exists, but it has no service-level `command` and falls back to `backend/Dockerfile.worker` default sleep instead of running `app.workers.run_scheduler_worker`.

Route shape is mixed. The app exposes `/health`, compatibility categories under `/api/categories`, most routes under `/api/v1`, and several routers that carry their own `/api/v1/...` prefixes for AI, settings, and stats. Non-lexical job search/export calls are proxied to `retrieval-api`; related-job recommendation calls are proxied to `recommendation-api`.

## Tests and Coverage

- `backend/tests/test_api_runtime.py`
- `backend/tests/test_health_api.py`
- `backend/tests/test_startup_recovery_service.py`
- `backend/tests/test_scheduler_dispatcher.py`
- `backend/tests/test_retrieval_client.py`
- `backend/tests/test_recommendations_api.py`
- API-specific tests across `backend/tests/test_*_api.py`

## Known Gaps or Risks

- Scheduler ownership is split: `scheduler-worker` is declared but inactive by default, while the API starts scheduler runtime.
- Startup recovery failures are logged and startup continues; readiness does not reflect a failed recovery sweep.
- Route namespace conventions are inconsistent across root health, compatibility categories, `/api/v1` routers, and self-prefixed routers.
- Internal retrieval and recommendation sidecar availability is discovered at request time, usually as a 503, rather than exposed as an operator capability before use.
- API health covers operator runtime summary, but it does not fully gate readiness on scheduler, startup recovery, or internal sidecar dependencies.

## Optimization Backlog

- Decide whether scheduler runtime belongs in `backend-api` or `scheduler-worker`; add an explicit Compose command for the worker or remove the unused service.
- Add readiness fields for last startup recovery status, scheduler runtime state, and configured internal sidecar reachability.
- Normalize route ownership so compatibility routes are clearly temporary and all operator APIs have a documented namespace.
- Expose a small capability endpoint for frontend feature gating across scheduler, retrieval, recommendation, and AI runtime readiness.
- Add smoke coverage that verifies the Compose scheduler worker command when the service is intended to run.

## Follow-up Audit Questions

- Should startup recovery failure make `/health` degraded until an operator acknowledges or reruns recovery?
- Should `/health` remain root-level while operator-specific health moves under `/api/v1/operator/health`?
- Should retrieval and recommendation proxy configuration be validated during startup or only reported as capability metadata?
