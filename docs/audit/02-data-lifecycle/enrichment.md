# Data Lifecycle: Enrichment

## Current Responsibilities

Enrichment adds AI summaries, skill mentions, company descriptions, embeddings, and recommendation-ready metadata after base job ingestion.

## Current Implementation Map

- Job enrichment: `backend/app/services/ai_enrichment_service.py`, `enrichment_run_service.py`
- Company enrichment: `backend/app/services/company_enrichment_service.py`, `company_enrichment_run_service.py`
- Embeddings: `backend/app/workers/run_embedding_worker.py`, `backend/app/services/embedding_document_builder.py`
- Skill governance: `backend/app/services/skill_normalizer.py`, `backend/scripts/govern_skill_history.py`

## Data and Control Flow

Ingest publishes lifecycle events. Enrichment workers consume lifecycle events and process pending enrichment runs. Embedding workers also consume lifecycle events and persist vectors for semantic search and recommendations.

## Tests and Coverage

- `backend/tests/test_enrichment_worker.py`
- `backend/tests/test_enrichment_run_service.py`
- `backend/tests/test_skill_governance.py`
- `backend/tests/test_skill_history_governance.py`
- `backend/tests/test_ai_runtime_settings_service.py`

## Known Gaps or Risks

- Enrichment depends on runtime provider readiness and can be blocked by untested settings.
- Skill governance is powerful but script-heavy.
- Embedding generation depends on ML image/service profile availability.
- Job enrichment is lifecycle/outbox driven, while company enrichment is API/background driven and not processed by the same worker path.
- Run-level provider status exists, but item-level provider/model/fingerprint telemetry is still limited.

## Optimization Backlog

- Split lifecycle event types for job enrichment, company enrichment, embedding generation, and skill governance so workers consume narrower contracts.
- Persist provider, model, runtime fingerprint, prompt version, and response classification on enrichment runs and individual items.
- Move company enrichment to a durable queue/worker path or explicitly document why BackgroundTasks are sufficient for this workload.
- Promote skill governance reports into a first-class UI review workflow with accept/reject audit history.

## Follow-up Audit Questions

- Should lifecycle events separate job AI, company AI, and embedding triggers?
- Should enrichment runs record provider fingerprint per item?
- Should governance review output become a first-class UI workflow?
