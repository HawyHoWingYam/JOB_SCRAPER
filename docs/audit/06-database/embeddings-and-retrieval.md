# Embeddings and Retrieval

## Current Responsibilities

This scope stores one current vector-backed retrieval snapshot per job. It supports semantic search, hybrid ranking, and job recommendation scoring.

## Current Implementation Map

- Model: `backend/app/models/job_embedding.py`
- Repository: `backend/app/repositories/job_embedding_repository.py`
- Worker: `backend/app/workers/run_embedding_worker.py`
- Document builder: `backend/app/services/embedding_document_builder.py`
- Retrieval: `backend/app/search/semantic_query.py`, `hybrid_ranker.py`, `backend/app/services/retrieval_service.py`, `job_recommendation_service.py`
- API: `backend/app/api/retrieval.py`, `backend/app/retrieval_main.py`, `backend/app/api/jobs.py`
- Tests: `backend/tests/test_embedding_worker.py`, `test_embedding_document_builder.py`, `test_retrieval_service.py`, `backend/tests/integration/test_job_embeddings_pgvector.py`, `backend/tests/integration/test_semantic_search_api.py`

## Tables and Column Use

| Table | Key columns | Column purpose |
| --- | --- | --- |
| `job_embeddings` | `job_id` | Primary key and foreign key to `jobs.id`; one current embedding row per job |
| `job_embeddings` | `embedding_model` | Model name that produced the current vector |
| `job_embeddings` | `embedding_dimensions` | Declared vector dimensionality; constrained to 384 |
| `job_embeddings` | `embedding_version` | Application-side embedding version for re-embedding decisions |
| `job_embeddings` | `document_text` | Deterministic normalized text used to create the embedding |
| `job_embeddings` | `document_hash` | Hash used to skip re-embedding unchanged documents |
| `job_embeddings` | `embedding` | pgvector column used for cosine-distance ordering |
| `job_embeddings` | `updated_at` | Freshness of the current vector snapshot |

## Data and Control Flow

1. Ingest and AI enrichment emit job lifecycle events.
2. Embedding worker loads the current `jobs`, `companies`, taxonomy, and skill state.
3. `EmbeddingDocumentBuilder` builds deterministic `document_text` and `document_hash`.
4. If no row exists or the hash changed, `JobEmbeddingRepository` upserts the vector.
5. Semantic retrieval joins `jobs` to `job_embeddings` and orders by vector cosine distance.
6. Hybrid retrieval fetches rows with embeddings and applies application-side score blending.
7. Recommendation service compares source and candidate embeddings with metadata/freshness signals.

## Constraints and Indexes

- `job_embeddings.job_id` is both primary key and foreign key to `jobs(id)` with `ON DELETE CASCADE`.
- Check constraint `ck_job_embeddings_dimensions_384` enforces 384 dimensions.
- `document_hash` is indexed for change detection.
- pgvector extension is required; bootstrap explicitly runs `CREATE EXTENSION IF NOT EXISTS vector`.

## Current Database Snapshot

- `job_embeddings`: 3 rows
- `jobs`: 3 rows

The connected local DB has embedding coverage for all current canonical jobs, but the job count is very small compared with staging rows.

## Tests and Coverage

- Integration tests verify pgvector persistence and cosine query behavior.
- Worker tests verify initial embedding, re-embedding after changed document hash, and skip behavior when unchanged.
- Retrieval tests cover lexical fallback, semantic search, hybrid mode, and retrieval API proxy behavior.

## Known Gaps or Risks

- There is no visible ANN index for the vector column in the connected schema; exact cosine ordering may become expensive as rows grow.
- The schema stores only the current embedding, not historical versions.
- Embedding document content is persisted as text, which helps debugging but may duplicate sensitive raw job content.
- Semantic retrieval requires pgvector and is not fully represented by SQLite-based tests.
- Lifecycle events include embedding triggers, but operator health does not yet expose stale or missing embeddings by model/version.

## Optimization Backlog

- Add an HNSW or IVFFlat pgvector index before canonical job volume makes exact vector scans expensive.
- Store or report embedding model/version/document hash coverage so re-embedding needs are visible to operators.
- Add an explicit re-embedding workflow for model upgrades, document builder changes, and failed embedding batches.
- Decide whether historical embedding versions are retained, archived, or intentionally overwritten.
- Add retrieval health for jobs without embeddings, stale document hashes, sidecar readiness, and vector index presence.

## Follow-up Audit Questions

- At what row count should an HNSW/IVFFlat index be added?
- Should embedding history be retained for model/version migrations?
- Which fields are allowed in `document_text` from a privacy and retention perspective?
- Should embedding coverage be tracked as an operator health metric with thresholds?
