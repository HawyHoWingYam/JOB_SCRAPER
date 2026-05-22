# Adapter Boundary: Search and Embedding Adapters

## Current Responsibilities

Search and embedding adapters bridge local lexical search, semantic and hybrid retrieval, embedding generation, retrieval proxy calls, recommendation proxy calls, and internal recommendation routes.

## Current Implementation Map

- Search modes: `backend/app/search/lexical_query.py`, `semantic_query.py`, `hybrid_ranker.py`
- Retrieval service/API: `backend/app/services/retrieval_service.py`, `backend/app/api/retrieval.py`
- Public jobs API and retrieval proxy: `backend/app/api/jobs.py`, `backend/app/services/retrieval_client.py`
- Embedding model/repository/builder: `backend/app/models/job_embedding.py`, `backend/app/repositories/job_embedding_repository.py`, `backend/app/services/embedding_document_builder.py`
- Embedding worker: `backend/app/workers/run_embedding_worker.py`
- Recommendation APIs/services: `backend/app/api/recommendations.py`, `backend/app/api/internal_recommendations.py`, `backend/app/services/recommendation_client.py`, `backend/app/services/job_recommendation_service.py`
- Frontend search controls: `frontend/src/components/JobBrowser.jsx`

## Data and Control Flow

The main Jobs API handles lexical search locally. Semantic and hybrid search requests are proxied to `retrieval-api` through `RetrievalClient`; when `retrieval_api_url` is missing, the public route returns an unavailable error. The internal retrieval API uses local retrieval service logic with query embedding, pgvector-backed job embeddings, lexical candidate scopes, and hybrid ranking.

Embedding workers consume lifecycle events, build deterministic job embedding documents from current job state, encode vectors, and upsert embedding rows with model, dimension, and version metadata. Public recommendation routes proxy to `recommendation-api`, while internal recommendation routes execute `JobRecommendationService` locally against embeddings, taxonomy, skills, and freshness signals.

If semantic query text is empty, internal retrieval falls back to lexical behavior. Public semantic/hybrid requests still require `retrieval_api_url` because they are proxied before local retrieval logic runs.

## Tests and Coverage

- `backend/tests/test_retrieval_service.py`
- `backend/tests/test_retrieval_client.py`
- `backend/tests/test_retrieval_api.py`
- `backend/tests/test_recommendations_api.py`
- `backend/tests/test_internal_recommendations_api.py`
- `backend/tests/test_job_recommendation_service.py`
- `backend/tests/test_embedding_worker.py`
- `backend/tests/test_embedding_document_builder.py`
- `backend/tests/integration/test_job_embeddings_pgvector.py`
- `backend/tests/integration/test_semantic_search_api.py`
- `frontend/src/components/JobBrowser.test.jsx`

## Known Gaps or Risks

- Public semantic/hybrid search depends on `retrieval_api_url` even when the same codebase contains the internal local retrieval service.
- Retrieval and recommendation process boundaries are split between public proxy APIs and internal local services, which can hide capability differences until runtime.
- Missing retrieval or recommendation services become runtime 503s rather than disabled UI modes or scheduler health warnings.
- Embedding freshness is event-driven; jobs without current embeddings are not surfaced as an operator-visible backlog.
- Embedding diagnostics expose limited model/version/freshness context to search users.

## Optimization Backlog

- Add retrieval and recommendation health/capability checks that can disable semantic, hybrid, or similar-job UI actions before request failure.
- Expose embedding diagnostics for model name, dimension, version, document hash, generated time, and stale/missing counts.
- Clarify the recommendation process boundary: keep a separate `recommendation-api`, co-locate it with retrieval, or make the public API call the local service directly.
- Add monitoring for jobs without current embeddings and for embedding rows with stale model/version/document hashes.
- Make empty semantic-text fallback behavior visible in diagnostics so lexical fallback is explicit.

## Follow-up Audit Questions

- Should public Jobs API semantic/hybrid routes be allowed to use local retrieval service when `retrieval_api_url` is not configured?
- Which fields should trigger embedding regeneration: raw scrape changes, AI enrichment changes, skill changes, taxonomy changes, or all of them?
- Should recommendation results snapshot the scoring version used for each response?
