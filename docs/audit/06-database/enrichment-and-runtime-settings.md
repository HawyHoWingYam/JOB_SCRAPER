# Enrichment and Runtime Settings

## Current Responsibilities

This scope stores persisted AI enrichment orchestration, item-level progress, and AI provider/runtime settings. It connects operator configuration, enrichment dispatch, worker progress, and failure recovery.

## Current Implementation Map

- Models: `backend/app/models/enrichment_run.py`, `company_enrichment_run.py`, `app_runtime_settings.py`
- Services: `backend/app/services/enrichment_run_service.py`, `ai_runtime_settings_service.py`, `ai_enrichment_service.py`
- APIs: `backend/app/api/ai.py`, `backend/app/api/companies.py`
- Workers/scripts: `backend/app/workers/run_enrichment_worker.py`, `backend/scripts/batch_enrich_jobs.py`
- Tests: `backend/tests/test_enrichment_run_service.py`, `test_enrichment_worker.py`, `test_ai_runtime_settings_service.py`, `test_ai_settings_api.py`, `test_ai_enrichment_dispatch_api.py`

## Tables and Column Use

| Table | Key columns | Column purpose |
| --- | --- | --- |
| `enrichment_runs` | `id`, `source_type`, `trigger_crawl_job_id`, `status` | Job enrichment run identity, source, crawl linkage, and lifecycle state |
| `enrichment_runs` | `job_ids`, `total_items`, `pending_items`, `completed_items`, `failed_items` | Batch membership and aggregate counters |
| `enrichment_runs` | `started_at`, `completed_at`, `current_job_title`, `error_message`, `created_at` | Operator progress and failure context |
| `enrichment_run_items` | `run_id`, `job_id`, `position`, `status` | Per-job work queue and ordering inside an enrichment run |
| `enrichment_run_items` | `error_message`, `started_at`, `completed_at`, `created_at` | Per-item progress and failure diagnostics |
| `company_enrichment_runs` | `id`, `status`, `total_items`, `pending_items`, `completed_items`, `failed_items` | Company enrichment batch status |
| `company_enrichment_runs` | `current_company_name`, `started_at`, `completed_at`, `error_message`, `created_at` | Operator progress for company descriptions |
| `company_enrichment_run_items` | `run_id`, `company_id`, `position`, `status` | Per-company enrichment work items |
| `app_runtime_settings` | `llm_provider`, `company_llm_provider`, `ai_enrichment_run_concurrency` | Effective provider selection and concurrency |
| `app_runtime_settings` | `*_api_key`, `*_model`, `*_base_url`, `*_api_format` | Provider credentials and model endpoints for jobs and companies profiles |
| `app_runtime_settings` | `jobs_last_*`, `companies_last_*` | Last provider test result, latency, fingerprint, and readiness metadata |
| `app_runtime_settings` | `updated_at` | Singleton settings freshness |

## Data and Control Flow

1. Operator configures AI provider settings through the settings APIs.
2. Runtime settings service persists provider/model/API-key fields and records test status metadata.
3. Enrichment dispatch validates the active profile and creates run/item rows.
4. Dispatch enqueues a durable event in `event_outbox`.
5. Job enrichment worker updates job run/item progress, writes AI-derived job fields, and emits lifecycle events.
6. Company enrichment currently runs through API/background service paths and writes company run/item progress separately.
7. Progress and AI overview APIs read run and item status for the frontend console.

## Constraints and Indexes

- Enrichment run item tables cascade when their parent run is deleted.
- `enrichment_runs.trigger_crawl_job_id` references `crawl_jobs(id)` with `ON DELETE SET NULL`.
- Status/source/created fields are indexed for run dashboards and worker lookups.
- `app_runtime_settings` is modeled as a singleton-style table with primary key `id`.

## Current Database Snapshot

- `app_runtime_settings`: 1 row
- `enrichment_runs`: 21 rows
- `enrichment_run_items`: 752 rows
- `company_enrichment_runs`: 0 rows
- `company_enrichment_run_items`: 0 rows

## Tests and Coverage

- Runtime settings tests cover profile updates, test metadata, and readiness gates.
- Enrichment run tests cover creation, item transitions, outbox dispatch, and duplicate dispatch prevention.
- Worker tests cover progress updates and failure handling.

## Known Gaps or Risks

- API keys are stored in database text columns; encryption, masking, and backup handling should be explicitly documented.
- Run aggregate counters can drift from item rows if updates are not transactional and tested.
- `job_ids` duplicates membership already represented by `enrichment_run_items`, which is convenient but denormalized.
- Status values are strings without database-level enum/check constraints.
- Provider/model/fingerprint metadata is mostly runtime/test oriented and is not yet persisted per run item.
- Company enrichment is not currently driven by the same durable worker path as job enrichment.

## Optimization Backlog

- Persist provider, model, API format, prompt version, runtime fingerprint, and response classification on run and item rows.
- Decide whether company enrichment should move to a durable queue/worker model or stay intentionally API/background driven.
- Replace string statuses with check constraints or enums across job and company enrichment run/item tables.
- Remove or strictly reconcile duplicated `job_ids` membership after item rows become the source of truth.
- Encrypt or externalize runtime secrets while keeping masked settings and readiness metadata in the database.

## Follow-up Audit Questions

- Should provider credentials move to a secrets manager, with DB storing only references?
- Should run counters be derived from item rows or enforced by database triggers/checks?
- What retention period should apply to completed/failed enrichment runs?
- Should company and job enrichment runs share a generic run table or stay separate?
