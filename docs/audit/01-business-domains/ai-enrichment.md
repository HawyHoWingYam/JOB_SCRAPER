# Business Domain: AI Enrichment

## Current Responsibilities

AI enrichment turns scraped job and company data into operator- and search-facing intelligence. It classifies job content, writes AI summaries and experience metadata, resolves governed job taxonomy, extracts skill mentions, links governed skills, queues unresolved skill review candidates, generates company descriptions, tracks persisted enrichment runs, and gates provider usage through runtime settings.

## Current Implementation Map

- Job AI API: `backend/app/api/ai.py`
- Company API: `backend/app/api/companies.py`
- Settings API: `backend/app/api/settings.py`
- Job services: `backend/app/services/ai_enrichment_service.py`, `enrichment_run_service.py`
- Company services: `backend/app/services/company_enrichment_service.py`, `company_enrichment_run_service.py`
- Provider/runtime layer: `backend/app/ai/llm_client.py`, `backend/app/ai/job_insight_extractor.py`, `backend/app/services/ai_runtime_settings_service.py`
- Taxonomy/skill normalization: `backend/app/services/job_category_normalizer.py`, `skill_normalizer.py`, `taxonomy_visibility_service.py`
- Worker: `backend/app/workers/run_enrichment_worker.py`
- Frontend: `frontend/src/components/ai/AIEnrichmentPage.jsx`, `frontend/src/components/settings/AISettingsPage.jsx`, `frontend/src/components/companies/CompaniesPage.jsx`

## Data and Control Flow

Job enrichment run state is persisted in `enrichment_runs` and `enrichment_run_items`. Supported source types include `manual_pending`, `manual_batch`, `manual_single`, `manual_query`, `post_scrape`, `crawl_auto`, and `retry_failed`.

Manual job enrichment APIs validate the `jobs` runtime profile, create run/item rows, enqueue an `enrichment.run.requested` event through `event_outbox`, and rely on the outbox publisher to send it to `stream.job.lifecycle`. The enrichment worker consumes the lifecycle stream, claims the run, executes items with configured concurrency, updates aggregate and item counters, writes job enrichment output, and emits `job.enriched` events for downstream consumers such as embeddings.

Crawl auto-enrichment is assembled incrementally from `job.ingested` lifecycle events. The worker appends each ingested job to the crawl-scoped pending run and dispatches it only after the crawl reaches a terminal state, emitted items have all been seen by ingest, the run has items, and the `jobs` profile is ready.

Company enrichment is intentionally separate today. Persisted company runs use `company_enrichment_runs` and `company_enrichment_run_items`, but they are started from `backend/app/api/companies.py` using FastAPI `BackgroundTasks`; single/selected company enrichment endpoints call `CompanyEnrichmentService` directly. Company descriptions use the `companies` runtime profile and request web search only when the selected provider reports support for it.

Runtime provider settings are stored in `app_runtime_settings`. The table holds separate `jobs` and `companies` profile fields, provider credentials, model/base URL fields, last test status, latency, config fingerprints, and a global `ai_enrichment_run_concurrency` setting for job workers. Protected enrichment endpoints call `ensure_profile_runtime_ready`, so configured profiles must have a successful test for the current fingerprint before work starts.

Job enrichment output spans several tables and columns:

- `jobs`: `ai_enriched_at`, `ai_summary`, `experience_level`, `experience_min_years`, `experience_max_years`, `experience_summary`, `experience_evidence`, `subcategory_id`
- `job_skills`: governed canonical skill links
- `job_skill_mentions`: raw extracted terms, resolved canonical skills, generic tags, or review-candidate references
- `skill_review_candidates`: unresolved terms requiring governance
- taxonomy and skill hierarchy tables: usage metrics updated through visibility services

## Tests and Coverage

- `backend/tests/test_ai_enrichment_dispatch_api.py`
- `backend/tests/test_ai_overview_api.py`
- `backend/tests/test_ai_settings_api.py`
- `backend/tests/test_ai_runtime_settings_service.py`
- `backend/tests/test_enrichment_run_service.py`
- `backend/tests/test_enrichment_worker.py`
- `backend/tests/test_job_insight_extractor.py`
- `backend/tests/test_company_enrichment_service.py`
- `backend/tests/test_llm_client.py`
- `backend/tests/test_recover_failed_crawl_auto_runs.py`
- `frontend/src/components/ai/AIEnrichmentPage.test.jsx`
- `frontend/src/components/settings/AISettingsPage.test.jsx`
- `frontend/src/components/companies/CompaniesPage.test.jsx`

## Known Gaps or Risks

- Company enrichment does not use the durable job enrichment worker/outbox path, so company runs are less resilient to API process restarts than job runs.
- Run aggregate counters are denormalized from item rows and can drift if updates are not kept transactional.
- `enrichment_runs.job_ids` duplicates membership already represented by `enrichment_run_items`.
- Status values are strings without database-level enum/check constraints.
- API keys are stored in database text columns; masking exists at the API boundary, but encryption, backup handling, and secret audit policy remain operational risks.
- Runtime fingerprint gating exists before protected work starts, but run and item rows do not snapshot provider, model, config fingerprint, latency, token usage, or cost.
- Job and company enrichment share provider primitives but have different execution models, retry behavior, and UI flows.
- Skill normalization and governance are part of enrichment outcomes, but their operator review loop is still script-heavy.
- `POST /api/v1/ai/runs/{run_id}/retry-failed` should be checked for the same runtime readiness gate used by create/enrich endpoints.
- Company run failure handling should initialize and preserve first-error context consistently so item errors are not masked by run-status bookkeeping.
- AI console actions should distinguish queued runs from empty backlogs and should surface backend `detail` messages for runtime-not-ready errors.
- Scrape progress can navigate to the AI page with a run id, but the AI console currently has no selected-run focus state.
- Settings UI records successful profile tests on the backend, but summary state can remain stale until save or reload.

## Optimization Backlog

- Move company enrichment onto a durable outbox/worker path or document why API background execution is acceptable for this workload.
- Add run/item telemetry fields for provider scope, provider name, model, config fingerprint, request latency, token counts, cost estimate, and provider request id when available.
- Add a shared run-status abstraction only if it can reduce duplicated job/company run logic without hiding domain-specific differences.
- Add a small frontend API helper for JSON parsing, `detail` extraction, abortable timeouts, and shared AI/settings/company request behavior.
- Make AI run creation body-aware in the UI: show empty backlog, queued run id, and retry-created run id distinctly.
- Add selected-run support to `AIEnrichmentPage` so "View AI Run" from scraper progress can focus the relevant run.
- Expose company run item failures and retry actions in the Companies UI, backed by existing company run item APIs.
- Add an operator-facing skill governance console for review candidates, generic tags, and polluted skill cleanup.
- Clarify whether backend provider alias `claude` is only a compatibility alias for `anthropic` or should be visible in settings UI.

## Follow-up Audit Questions

- Should completed enrichment runs have a retention policy or archival job?
- Should provider credentials move from `app_runtime_settings` into a secrets manager with database references only?
- Should runtime concurrency remain global or become scoped per profile/workload?
- Which enrichment outputs should block downstream embedding or recommendation refresh when item execution partially fails?
