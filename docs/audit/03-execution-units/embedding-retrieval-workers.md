# Execution Unit: Embedding and Retrieval Workers

## Current Responsibilities

Embedding and retrieval units generate job embedding documents, persist vectors, serve semantic and hybrid search, export non-lexical search results, and support related-job recommendations through internal sidecar APIs.

## Current Implementation Map

- Embedding worker: `backend/app/workers/run_embedding_worker.py`
- Document builder: `backend/app/services/embedding_document_builder.py`
- Embedding repository/model: `backend/app/repositories/job_embedding_repository.py`, `backend/app/models/job_embedding.py`
- Retrieval service app: `backend/app/retrieval_main.py`
- Recommendation service app: `backend/app/recommendation_main.py`
- Public proxy routes: `backend/app/api/jobs.py`, `backend/app/api/recommendations.py`
- Internal routes: `backend/app/api/retrieval.py`, `backend/app/api/internal_recommendations.py`
- Clients: `backend/app/services/retrieval_client.py`, `recommendation_client.py`
- Search modules: `backend/app/search/*`
- Docker services: `embedding-worker`, `retrieval-api`, `recommendation-api`

## Data and Control Flow

The embedding worker consumes `job.ingested` and `job.enriched` events from `stream.job.lifecycle`. It builds a document, skips reembedding when the document hash is unchanged, upserts `job_embeddings` with model and version metadata, enqueues `job.embedded` through the outbox, and publishes to `stream.job.embedding`.

The main API handles lexical job search locally. `POST /api/v1/jobs/search` and `/api/v1/jobs/search/export` proxy only non-lexical retrieval modes to `retrieval-api`; recommendation requests proxy to `recommendation-api` when configured. Retrieval and recommendation sidecars expose shallow `/health` endpoints that report service liveness.

No current consumer was identified for `stream.job.embedding`; it is emitted for downstream use but is not documented as part of an active pipeline.

## Tests and Coverage

- `backend/tests/test_embedding_worker.py`
- `backend/tests/test_embedding_document_builder.py`
- `backend/tests/test_retrieval_api.py`
- `backend/tests/test_retrieval_client.py`
- `backend/tests/test_retrieval_service.py`
- `backend/tests/test_recommendations_api.py`
- `backend/tests/test_internal_recommendations_api.py`
- `backend/tests/test_job_recommendation_service.py`
- `backend/tests/integration/test_job_embeddings_pgvector.py`
- `backend/tests/integration/test_semantic_search_api.py`

## Known Gaps or Risks

- These services are under the `workers` Compose profile, so semantic and recommendation features depend on optional runtime services.
- Retrieval and recommendation health is shallow and does not report pgvector readiness, model load state, or index/vector freshness.
- The main API exposes capability mismatch as request-time 503 responses for non-lexical modes.
- `stream.job.embedding` is emitted but its consumer contract is unclear.
- Embedding model and version are stored in `job_embeddings`, but search responses and operator health do not expose embedding freshness or reembedding needs.

## Optimization Backlog

- Add a capability endpoint that reports retrieval, recommendation, pgvector, embedding model, and configured sidecar state before the frontend enables semantic modes.
- Document and consume `stream.job.embedding`, or remove the stream emission if no downstream service needs it.
- Expose embedding model/version and document hash freshness in operator health and relevant search diagnostics.
- Add an explicit reembedding workflow for model/version changes and stale document hashes.
- Deepen sidecar health checks to include database/vector checks and model initialization status.

## Follow-up Audit Questions

- Should retrieval and recommendation remain separate apps or share one ML sidecar?
- Should search responses include embedding version metadata for semantic/hybrid modes?
- What SLA should apply when lexical search is available but semantic sidecars are degraded?
