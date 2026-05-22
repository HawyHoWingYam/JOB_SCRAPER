# Execution Unit: AI Workers

## Current Responsibilities

AI workers process durable job enrichment runs, recover interrupted job enrichment state on worker startup, react to crawl/ingest lifecycle events, and publish downstream job-enriched lifecycle events. Company enrichment shares provider readiness infrastructure but currently runs through API background/service flows.

## Current Implementation Map

- Worker: `backend/app/workers/run_enrichment_worker.py`
- Run services: `backend/app/services/enrichment_run_service.py`, `ai_enrichment_service.py`
- Company services: `backend/app/services/company_enrichment_service.py`, `company_enrichment_run_service.py`
- Company API background entry: `backend/app/api/companies.py`
- Provider runtime: `backend/app/ai/llm_client.py`, `backend/app/services/ai_runtime_settings_service.py`
- Startup recovery: `backend/app/services/startup_recovery_service.py`
- Docker service: `enrichment-worker`
- Redis topics: `stream.job.lifecycle`, `stream.crawl.progress`

## Data and Control Flow

On startup, the enrichment worker calls `StartupRecoveryService.recover_ai_runs_only`, complementing API startup recovery where `recover_ai_runs=False`. The worker consumes lifecycle and crawl progress streams, handles `enrichment.run.requested`, accumulates crawl-auto pending items from `job.ingested`, dispatches ready crawl-auto runs after terminal crawl progress, executes run items with configured concurrency, writes enrichment output, and emits `job.enriched` lifecycle events.

Job enrichment requests are durable: API/service code creates run/item rows and enqueues lifecycle events through the event outbox. Company enrichment has persisted run/item tables, but `backend/app/api/companies.py` launches persisted company runs with FastAPI `BackgroundTasks`; single and selected company endpoints call `CompanyEnrichmentService` directly.

Provider readiness gates job and company work through runtime settings. Current persisted item/run data does not capture provider name, model, token counts, per-item latency, cost, or provider request id.

## Tests and Coverage

- `backend/tests/test_enrichment_worker.py`
- `backend/tests/test_enrichment_run_service.py`
- `backend/tests/test_ai_enrichment_dispatch_api.py`
- `backend/tests/test_ai_overview_api.py`
- `backend/tests/test_ai_settings_api.py`
- `backend/tests/test_ai_runtime_settings_service.py`
- `backend/tests/test_company_enrichment_service.py`
- `backend/tests/test_startup_recovery_service.py`
- `backend/tests/test_llm_client.py`

## Known Gaps or Risks

- Company enrichment `BackgroundTasks` are not durable across API process restarts in the same way as job enrichment worker tasks.
- Job enrichment worker startup recovers AI runs, but active item/provider telemetry is sparse after recovery or failure.
- Provider readiness can block run creation and retries, but operator feedback depends on each caller surfacing backend detail clearly.
- Worker concurrency is stored in AI runtime settings, while queue pressure and active work visibility remain mostly operational.
- Run and item rows do not snapshot provider, model, token usage, per-item latency, cost, or provider request ids.

## Optimization Backlog

- Move company enrichment onto a durable queue/worker path or explicitly document why API background execution is acceptable.
- Add item-level telemetry for provider scope, provider name, model, config fingerprint, request latency, token counts, cost estimate, and provider request id.
- Expose enrichment worker health with active run ids, item counts, provider/model metadata, and last recovery summary.
- Add operator-visible queue depth and active item state for job enrichment.
- Keep startup recovery split explicit in docs and tests: API recovers company/crawl/schedule; enrichment worker recovers AI runs.

## Follow-up Audit Questions

- Should job and company enrichment share a worker protocol or remain separate workloads with shared provider primitives?
- Should retry-created runs snapshot the provider settings at retry time?
- Which enrichment item failures should block downstream embedding refresh?
