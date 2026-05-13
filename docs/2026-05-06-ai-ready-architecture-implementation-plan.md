# AI-Ready Eventized Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade `JOB_SCRAPER` into an event-driven, AI-ready platform with PostgreSQL + `pgvector`, Redis Streams, Scrapy/Playwright crawl execution, and dedicated workers for ingestion, enrichment, embedding, retrieval, and recommendation.

**Architecture:** The target state is a full event-driven microservice topology, but execution is intentionally staged. The first half of the plan establishes durable job state, messaging, and crawl-worker separation. The second half moves enrichment and semantic capabilities onto explicit workers and APIs without breaking the current frontend contract.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, PostgreSQL 15 + `pgvector`, Redis Streams, Scrapy, Playwright, sentence-transformers, React 19, Vite, pytest, Vitest.

---

## File Structure

The implementation should converge toward the following structure.

```text
backend/
  app/
    api/
      crawl_jobs.py
      recommendations.py
    messaging/
      event_envelope.py
      redis_stream_bus.py
      outbox_publisher.py
      topics.py
    models/
      crawl_job.py
      event_outbox.py
      job_embedding.py
    repositories/
      crawl_job_repository.py
      event_outbox_repository.py
      job_embedding_repository.py
    schemas/
      crawl_job.py
    search/
      lexical_query.py
      semantic_query.py
      hybrid_ranker.py
    services/
      retrieval_service.py
      job_recommendation_service.py
      embedding_document_builder.py
    sources/
      contracts.py
      jobsdb/
        parsers.py
      ctgoodjobs/
        parsers.py
    workers/
      run_scheduler_worker.py
      run_crawl_worker.py
      run_ingest_worker.py
      run_enrichment_worker.py
      run_embedding_worker.py
  crawler/
    scrapy.cfg
    job_crawler/
      items.py
      settings.py
      pipelines.py
      middlewares.py
      emitters/redis_stream_emitter.py
      spiders/jobsdb_spider.py
      spiders/ctgoodjobs_spider.py
docs/
  2026-05-06-ai-ready-architecture-design.md
  2026-05-06-ai-ready-architecture-implementation-plan.md
```

The control plane stays in `backend/app/`. Scrapy is isolated under `backend/crawler/`. Search and messaging become explicit packages instead of being embedded inside `jobs.py` and ad hoc service code.

## Task 1: Dependency and Container Foundation

**Files:**
- Modify: `docker-compose.yml`
- Modify: `backend/requirements.txt`
- Modify: `backend/requirements-dev.txt`
- Create: `backend/Dockerfile.worker`
- Create: `backend/crawler/README.md`
- Test: `backend/tests/test_config.py`

- [ ] **Step 1: Switch local Postgres to a pgvector-capable image**

Update `docker-compose.yml` so the `postgres-db` service runs a pgvector-enabled Postgres 15 image. Keep the existing port and volume layout stable so current local workflows do not break.

Recommended image:

```yaml
postgres-db:
  image: pgvector/pgvector:pg15
```

- [ ] **Step 2: Add explicit worker services to Compose**

Add service stubs for:

- `scheduler-worker`
- `crawl-worker`
- `ingest-worker`
- `enrichment-worker`
- `embedding-worker`
- `retrieval-api`
- `recommendation-api`

Keep them behind `profiles` initially so local development can start a subset:

```yaml
profiles: ["workers"]
```

- [ ] **Step 3: Add missing Python dependencies**

Append to `backend/requirements.txt`:

```text
pgvector>=0.3.6
scrapy>=2.12.0
scrapy-playwright>=0.0.41
```

Do not remove `playwright`; it is already present and should be reused.

- [ ] **Step 4: Add a worker-oriented Dockerfile**

Create `backend/Dockerfile.worker` by reusing the backend dependency layer but defaulting to a worker command instead of `uvicorn`.

- [ ] **Step 5: Verify dependency and compose validity**

Run:

```bash
docker compose config
cd backend && pytest tests/test_config.py -v
```

Expected:

- Compose renders without schema errors
- configuration test still passes

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml backend/requirements.txt backend/requirements-dev.txt backend/Dockerfile.worker backend/crawler/README.md
git commit -m "chore: add eventized worker runtime foundation"
```

## Task 2: Durable Event Backbone and pgvector Schema

**Files:**
- Create: `backend/app/models/crawl_job.py`
- Create: `backend/app/models/event_outbox.py`
- Create: `backend/app/models/job_embedding.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/models/schedule.py`
- Create: `backend/app/repositories/crawl_job_repository.py`
- Create: `backend/app/repositories/event_outbox_repository.py`
- Create: `backend/app/repositories/job_embedding_repository.py`
- Create: `backend/alembic/versions/20260506_120000_add_event_backbone_and_pgvector.py`
- Test: `backend/tests/test_crawl_job_repository.py`
- Test: `backend/tests/integration/test_job_embeddings_pgvector.py`

- [ ] **Step 1: Add the new ORM models**

Define:

- `CrawlJob`
- `CrawlJobEvent`
- `EventOutbox`
- `JobEmbedding`

`JobEmbedding` should use a dedicated table, not `Job.search_vector`.

Recommended SQLAlchemy shape:

```python
class JobEmbedding(Base):
    __tablename__ = "job_embeddings"
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    embedding_model = Column(String(255), nullable=False)
    embedding_dimensions = Column(Integer, nullable=False)
    embedding_version = Column(Integer, nullable=False, default=1)
    document_text = Column(Text, nullable=False)
    document_hash = Column(String(64), nullable=False, index=True)
    embedding = Column(Vector(384), nullable=False)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)
```

- [ ] **Step 2: Link schedule executions to crawl jobs**

Add `crawl_job_id` to `schedule_executions` so every scheduled run can point to the new durable crawl entity.

- [ ] **Step 3: Write the Alembic migration**

The migration must:

- `CREATE EXTENSION IF NOT EXISTS vector`
- create `crawl_jobs`
- create `crawl_job_events`
- create `event_outbox`
- create `job_embeddings`
- add `crawl_job_id` to `schedule_executions`
- add indexes for `status`, `source_site`, timestamps, and vector lookup

Use HNSW for cosine similarity:

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_job_embeddings_embedding_hnsw
ON job_embeddings
USING hnsw (embedding vector_cosine_ops);
```

- [ ] **Step 4: Add repository coverage**

Create repositories for:

- crawl job creation and event appends
- outbox insertion and retry queries
- job embedding upsert by `job_id + document_hash`

- [ ] **Step 5: Add Postgres integration testing for vectors**

Do not attempt to fake `pgvector` behavior in SQLite. Add a Postgres-backed integration test that verifies:

- extension exists
- vector row inserts cleanly
- cosine query returns expected top-1

Run:

```bash
docker compose up -d postgres-db
cd backend && alembic upgrade head
cd backend && pytest tests/test_crawl_job_repository.py tests/integration/test_job_embeddings_pgvector.py -v
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/crawl_job.py backend/app/models/event_outbox.py backend/app/models/job_embedding.py backend/app/models/__init__.py backend/app/models/schedule.py backend/app/repositories/crawl_job_repository.py backend/app/repositories/event_outbox_repository.py backend/app/repositories/job_embedding_repository.py backend/alembic/versions/20260506_120000_add_event_backbone_and_pgvector.py backend/tests/test_crawl_job_repository.py backend/tests/integration/test_job_embeddings_pgvector.py
git commit -m "feat: add durable crawl jobs outbox and job embeddings"
```

## Task 3: Redis Streams Messaging Layer

**Files:**
- Create: `backend/app/messaging/topics.py`
- Create: `backend/app/messaging/event_envelope.py`
- Create: `backend/app/messaging/redis_stream_bus.py`
- Create: `backend/app/messaging/outbox_publisher.py`
- Modify: `backend/app/utils/redis_client.py`
- Test: `backend/tests/test_redis_stream_bus.py`
- Test: `backend/tests/test_outbox_publisher.py`

- [ ] **Step 1: Create the canonical topic registry**

Add a small constants module for:

- `stream.crawl.commands`
- `stream.crawl.progress`
- `stream.job.ingest`
- `stream.job.lifecycle`
- `stream.job.embedding`

- [ ] **Step 2: Add a shared event envelope builder**

Every event must be serialized through one helper so fields like `event_id`, `event_type`, `aggregate_id`, and `schema_version` remain stable.

- [ ] **Step 3: Implement a Redis Streams bus**

Add methods for:

- `publish(topic, event)`
- `consume_group(topic, group_name, consumer_name, count=..., block_ms=...)`
- `ack(topic, group_name, message_id)`
- `ensure_group(topic, group_name)`

Do not overload the current pub/sub helper. Keep pub/sub support if needed, but Streams should be the default bus.

- [ ] **Step 4: Add an outbox publisher loop**

This loop should:

- poll `event_outbox` for pending rows
- publish to Redis Streams
- mark rows published only after success
- backoff and retain error state on failure

- [ ] **Step 5: Cover the bus with unit tests**

Tests should verify:

- event serialization
- group creation idempotency
- publish + consume + ack flow
- retry path for a failed outbox row

Run:

```bash
cd backend && pytest tests/test_redis_stream_bus.py tests/test_outbox_publisher.py -v
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/messaging/topics.py backend/app/messaging/event_envelope.py backend/app/messaging/redis_stream_bus.py backend/app/messaging/outbox_publisher.py backend/app/utils/redis_client.py backend/tests/test_redis_stream_bus.py backend/tests/test_outbox_publisher.py
git commit -m "feat: add redis streams bus and outbox publisher"
```

## Task 4: Crawl Job Control Plane APIs and Progress Refactor

**Files:**
- Create: `backend/app/api/crawl_jobs.py`
- Create: `backend/app/schemas/crawl_job.py`
- Create: `backend/app/workers/run_scheduler_worker.py`
- Modify: `backend/app/api/schedules.py`
- Modify: `backend/app/api/progress.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/repositories/schedule_repository.py`
- Modify: `backend/app/services/scheduler_service.py`
- Modify: `backend/app/services/startup_recovery_service.py`
- Test: `backend/tests/test_crawl_jobs_api.py`
- Test: `backend/tests/test_scheduler_dispatcher.py`

- [ ] **Step 1: Add explicit crawl job APIs**

Create endpoints:

- `POST /api/v1/crawl-jobs`
- `GET /api/v1/crawl-jobs/{crawl_job_id}`
- `GET /api/v1/crawl-jobs/{crawl_job_id}/events`
- `POST /api/v1/crawl-jobs/{crawl_job_id}/cancel`

Manual scrape requests should create a `crawl_jobs` row and an outbox event. They should not execute source services directly.

- [ ] **Step 2: Make schedules dispatch crawl jobs**

Change `schedules/{id}/run` and cron execution paths so they:

- create `schedule_executions`
- create `crawl_jobs`
- link `schedule_execution.crawl_job_id`
- publish `crawl.requested`

They must no longer call the old source services as the primary execution path.

- [ ] **Step 3: Extract scheduler runtime from FastAPI startup**

Create `run_scheduler_worker.py` so cron polling and crawl-job dispatch can run outside the API process. `backend/app/main.py` should stop being the only place that initializes scheduling behavior.

- [ ] **Step 4: Replace in-memory crawl progress with durable state**

Refactor the SSE progress API to read from:

- `crawl_jobs`
- latest `crawl_job_events`
- optional Redis stream-derived progress cache

The singleton `ScrapeProgressStore` should be marked transitional and then removed after worker cutover.

- [ ] **Step 5: Extend startup recovery**

Recover interrupted:

- crawl jobs
- pending schedule executions linked to crawl jobs
- outbox rows left in pending state

- [ ] **Step 6: Verify the API layer**

Run:

```bash
cd backend && pytest tests/test_crawl_jobs_api.py tests/test_scheduler_dispatcher.py tests/test_ai_overview_api.py -v
```

Expected:

- manual crawl requests create durable rows
- schedules dispatch crawl commands instead of executing inline
- startup recovery still works

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/crawl_jobs.py backend/app/schemas/crawl_job.py backend/app/workers/run_scheduler_worker.py backend/app/api/schedules.py backend/app/api/progress.py backend/app/main.py backend/app/repositories/schedule_repository.py backend/app/services/scheduler_service.py backend/app/services/startup_recovery_service.py backend/tests/test_crawl_jobs_api.py backend/tests/test_scheduler_dispatcher.py
git commit -m "feat: move crawl dispatch into durable control plane jobs"
```

## Task 5: Shared Source Contracts and Parser Extraction

**Files:**
- Create: `backend/app/sources/contracts.py`
- Create: `backend/app/sources/jobsdb/parsers.py`
- Create: `backend/app/sources/ctgoodjobs/parsers.py`
- Modify: `backend/app/scraper/category_scraper.py`
- Modify: `backend/app/scraper/job_detail_scraper.py`
- Modify: `backend/app/scraper/ctgoodjobs/list_scraper.py`
- Modify: `backend/app/scraper/ctgoodjobs/detail_scraper.py`
- Test: `backend/tests/test_jobsdb_parsers.py`
- Test: `backend/tests/test_ctgoodjobs_parsers.py`

- [ ] **Step 1: Define the canonical source item contract**

Create `CanonicalScrapedJob` and helper mappers under `app/sources/contracts.py`.

- [ ] **Step 2: Extract pure parsing from HTTP classes**

JobsDB and CTgoodjobs parser logic should become pure functions:

- HTML/API payload in
- normalized dict out

The old scraper classes may temporarily call the new parser helpers until they are fully retired.

- [ ] **Step 3: Add parser parity tests**

Write fixture-driven tests that assert the new parser modules reproduce the same field mapping as the old source implementations.

Run:

```bash
cd backend && pytest tests/test_jobsdb_parsers.py tests/test_ctgoodjobs_parsers.py -v
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/sources/contracts.py backend/app/sources/jobsdb/parsers.py backend/app/sources/ctgoodjobs/parsers.py backend/app/scraper/category_scraper.py backend/app/scraper/job_detail_scraper.py backend/app/scraper/ctgoodjobs/list_scraper.py backend/app/scraper/ctgoodjobs/detail_scraper.py backend/tests/test_jobsdb_parsers.py backend/tests/test_ctgoodjobs_parsers.py
git commit -m "refactor: extract source parser contracts for worker reuse"
```

## Task 6: Scrapy Crawl Worker and JobsDB Migration

**Files:**
- Create: `backend/crawler/scrapy.cfg`
- Create: `backend/crawler/job_crawler/settings.py`
- Create: `backend/crawler/job_crawler/items.py`
- Create: `backend/crawler/job_crawler/pipelines.py`
- Create: `backend/crawler/job_crawler/middlewares.py`
- Create: `backend/crawler/job_crawler/emitters/redis_stream_emitter.py`
- Create: `backend/crawler/job_crawler/spiders/jobsdb_spider.py`
- Create: `backend/app/workers/run_crawl_worker.py`
- Test: `backend/tests/test_jobsdb_spider.py`
- Test: `backend/tests/test_jobsdb_crawl_progress_emission.py`

- [ ] **Step 1: Create the Scrapy project**

Set up a standalone Scrapy project under `backend/crawler/` that can be run by the new `crawl-worker`.

- [ ] **Step 2: Build a JobsDB spider**

Implement:

- list-page discovery via the current JobsDB search API
- detail-page follow-up via current detail parsing logic
- emission of `CanonicalScrapedJob`
- emission of crawl progress events

Playwright should be disabled by default for this spider.

- [ ] **Step 3: Emit to Redis Streams, not directly to Postgres**

The spider pipeline should publish normalized items to `stream.job.ingest` and progress to `stream.crawl.progress`.

- [ ] **Step 4: Create the crawl worker runtime**

Add a worker entrypoint that:

- consumes `crawl.requested`
- chooses the spider by `source_site`
- launches the crawl with the payload from `crawl_jobs.request_payload`
- appends `crawl_job_events`

- [ ] **Step 5: Verify JobsDB parity before cutover**

Compare old and new JobsDB paths on:

- job count
- detail completeness
- duplicate behavior

Run:

```bash
cd backend && pytest tests/test_jobsdb_spider.py tests/test_jobsdb_crawl_progress_emission.py -v
```

- [ ] **Step 6: Commit**

```bash
git add backend/crawler/scrapy.cfg backend/crawler/job_crawler/settings.py backend/crawler/job_crawler/items.py backend/crawler/job_crawler/pipelines.py backend/crawler/job_crawler/middlewares.py backend/crawler/job_crawler/emitters/redis_stream_emitter.py backend/crawler/job_crawler/spiders/jobsdb_spider.py backend/app/workers/run_crawl_worker.py backend/tests/test_jobsdb_spider.py backend/tests/test_jobsdb_crawl_progress_emission.py
git commit -m "feat: add scrapy crawl worker and jobsdb spider"
```

## Task 7: Ingest Worker and Durable Upsert Flow

**Files:**
- Create: `backend/app/workers/run_ingest_worker.py`
- Modify: `backend/app/repositories/job_repository.py`
- Modify: `backend/app/repositories/company_repository.py`
- Create: `backend/app/services/ingest_worker_service.py`
- Test: `backend/tests/test_ingest_worker.py`
- Test: `backend/tests/test_job_repository_upsert.py`

- [ ] **Step 1: Build an ingest worker loop**

Consume `stream.job.ingest` and:

- upsert company
- upsert job
- preserve `raw_data`
- normalize `job_id` using source-aware identifiers
- emit `job.ingested`

- [ ] **Step 2: Make upserts idempotent**

Ingestion must tolerate:

- replayed crawl events
- worker restarts
- duplicate stream deliveries

Use `source_site + source_job_id` as the stable uniqueness base.

- [ ] **Step 3: Append crawl completion metrics**

The ingest worker should update `crawl_jobs.metrics` so control-plane status reflects:

- items seen
- jobs created
- jobs updated
- jobs skipped

- [ ] **Step 4: Verify ingestion**

Run:

```bash
cd backend && pytest tests/test_ingest_worker.py tests/test_job_repository_upsert.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/workers/run_ingest_worker.py backend/app/repositories/job_repository.py backend/app/repositories/company_repository.py backend/app/services/ingest_worker_service.py backend/tests/test_ingest_worker.py backend/tests/test_job_repository_upsert.py
git commit -m "feat: add ingest worker and durable job upsert flow"
```

## Task 8: CTgoodjobs Spider Migration

**Files:**
- Create: `backend/crawler/job_crawler/spiders/ctgoodjobs_spider.py`
- Modify: `backend/app/services/source_category_registry.py`
- Modify: `backend/app/api/schedules.py`
- Test: `backend/tests/test_ctgoodjobs_spider.py`
- Test: `backend/tests/test_ctgoodjobs_schedule_dispatch.py`

- [ ] **Step 1: Implement the CTgoodjobs spider**

Reuse the extracted parser helpers and emit the same canonical item contract as JobsDB.

- [ ] **Step 2: Route CTgoodjobs schedules through crawl jobs**

CTgoodjobs should stop using the old direct service path once parity passes.

- [ ] **Step 3: Verify category registry compatibility**

The source registry and schedule validation must still enforce source-specific category identifiers.

Run:

```bash
cd backend && pytest tests/test_ctgoodjobs_spider.py tests/test_ctgoodjobs_schedule_dispatch.py -v
```

- [ ] **Step 4: Commit**

```bash
git add backend/crawler/job_crawler/spiders/ctgoodjobs_spider.py backend/app/services/source_category_registry.py backend/app/api/schedules.py backend/tests/test_ctgoodjobs_spider.py backend/tests/test_ctgoodjobs_schedule_dispatch.py
git commit -m "feat: migrate ctgoodjobs onto scrapy crawl worker"
```

## Task 9: Enrichment Worker Extraction

**Files:**
- Create: `backend/app/workers/run_enrichment_worker.py`
- Modify: `backend/app/services/ai_enrichment_service.py`
- Modify: `backend/app/services/enrichment_run_service.py`
- Modify: `backend/app/api/ai.py`
- Modify: `backend/app/services/startup_recovery_service.py`
- Test: `backend/tests/test_enrichment_worker.py`
- Test: `backend/tests/test_enrichment_run_service.py`

- [ ] **Step 1: Separate worker execution from API-triggered orchestration**

The control plane should create runs and emit commands. The enrichment worker should perform the actual enrichment.

- [ ] **Step 2: Consume `job.ingested` for automatic enrichment**

For crawl-driven jobs, automatically queue enrichment after ingestion.

- [ ] **Step 3: Preserve manual enrichment APIs**

The existing AI pages and APIs should still work, but they now dispatch work to the worker path instead of spawning in-process background tasks.

- [ ] **Step 4: Update startup recovery**

Recover worker-owned enrichment work similarly to the current in-process run recovery.

- [ ] **Step 5: Verify enrichment behavior**

Run:

```bash
cd backend && pytest tests/test_enrichment_worker.py tests/test_enrichment_run_service.py tests/test_ai_overview_api.py -v
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/workers/run_enrichment_worker.py backend/app/services/ai_enrichment_service.py backend/app/services/enrichment_run_service.py backend/app/api/ai.py backend/app/services/startup_recovery_service.py backend/tests/test_enrichment_worker.py backend/tests/test_enrichment_run_service.py
git commit -m "feat: extract ai enrichment onto dedicated worker"
```

## Task 10: Embedding Worker and Semantic Retrieval

**Files:**
- Create: `backend/app/workers/run_embedding_worker.py`
- Create: `backend/app/services/embedding_document_builder.py`
- Create: `backend/app/services/retrieval_service.py`
- Create: `backend/app/search/semantic_query.py`
- Create: `backend/app/search/lexical_query.py`
- Create: `backend/app/search/hybrid_ranker.py`
- Modify: `backend/app/api/jobs.py`
- Test: `backend/tests/test_embedding_document_builder.py`
- Test: `backend/tests/integration/test_semantic_search_api.py`

- [ ] **Step 1: Build the deterministic embedding document**

Compose document text from:

- title
- company name
- source classification names
- AI summary
- canonical skills
- cleaned description excerpt

Hash this document. Re-embed only when the hash changes.

- [ ] **Step 2: Implement the embedding worker**

Consume `job.ingested` and `job.enriched`, generate vectors with `all-MiniLM-L6-v2`, and upsert `job_embeddings`.

- [ ] **Step 3: Add semantic and hybrid search paths**

Refactor `jobs.py` so search orchestration uses:

- `lexical_query.py` for current filter behavior
- `semantic_query.py` for vector search with SQL filters
- `hybrid_ranker.py` for blended ranking

- [ ] **Step 4: Keep the public jobs search API stable**

Extend `POST /api/v1/jobs/search` rather than replacing it. Add an optional retrieval mode field such as:

```json
{
  "retrieval_mode": "lexical|semantic|hybrid"
}
```

Default must remain compatible with the current frontend.

- [ ] **Step 5: Verify vector-backed retrieval**

Run:

```bash
docker compose up -d postgres-db redis-mq
cd backend && alembic upgrade head
cd backend && pytest tests/test_embedding_document_builder.py tests/integration/test_semantic_search_api.py -v
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/workers/run_embedding_worker.py backend/app/services/embedding_document_builder.py backend/app/services/retrieval_service.py backend/app/search/semantic_query.py backend/app/search/lexical_query.py backend/app/search/hybrid_ranker.py backend/app/api/jobs.py backend/tests/test_embedding_document_builder.py backend/tests/integration/test_semantic_search_api.py
git commit -m "feat: add embedding worker and semantic job retrieval"
```

## Task 11: Recommendation Service and Frontend Search Modes

**Files:**
- Create: `backend/app/api/recommendations.py`
- Create: `backend/app/services/job_recommendation_service.py`
- Modify: `backend/app/main.py`
- Modify: `frontend/src/components/JobBrowser.jsx`
- Modify: `frontend/src/components/jobBrowserQueryUtils.js`
- Modify: `frontend/src/components/JobBrowser.test.jsx`
- Test: `backend/tests/test_job_recommendation_service.py`
- Test: `frontend/src/components/JobBrowser.test.jsx`

- [ ] **Step 1: Add similar jobs and recommendation endpoints**

Expose:

- `GET /api/v1/jobs/{job_id}/similar`
- `GET /api/v1/recommendations/jobs?job_id=...`

Keep the scoring interpretable:

- semantic similarity
- skill overlap
- taxonomy path match
- freshness bonus

- [ ] **Step 2: Add frontend retrieval mode controls**

Update the Job Browser so users can switch between:

- lexical
- hybrid
- semantic

without losing the existing scope layer model.

- [ ] **Step 3: Add UI for similar jobs**

At minimum, expose a related-jobs panel from the job detail modal or detail page.

- [ ] **Step 4: Verify backend and frontend**

Run:

```bash
cd backend && pytest tests/test_job_recommendation_service.py -v
cd frontend && npm test -- JobBrowser.test.jsx
cd frontend && npm run build
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/recommendations.py backend/app/services/job_recommendation_service.py backend/app/main.py frontend/src/components/JobBrowser.jsx frontend/src/components/jobBrowserQueryUtils.js frontend/src/components/JobBrowser.test.jsx backend/tests/test_job_recommendation_service.py
git commit -m "feat: add similar job recommendations and search modes"
```

## Task 12: Cutover, Recovery, and Cleanup

**Files:**
- Modify: `backend/app/services/category_scrape_service.py`
- Modify: `backend/app/services/ctgoodjobs_scrape_service.py`
- Modify: `backend/app/services/progress_store.py`
- Modify: `backend/app/api/progress.py`
- Modify: `README.md`
- Modify: `docs/2026-05-06-ai-ready-architecture-design.md`
- Modify: `docs/2026-05-06-ai-ready-architecture-implementation-plan.md`
- Test: `backend/tests/test_startup_recovery_service.py`
- Test: `frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`

- [ ] **Step 1: Remove old crawl paths from primary execution**

The old in-process source services should no longer be the default production path once the new workers are green. Leave them available only as temporary fallback behind an explicit feature flag if needed.

- [ ] **Step 2: Remove the in-memory progress singleton from the runtime path**

`ScrapeProgressStore` should not remain the source of truth once Redis Streams + durable events are live.

- [ ] **Step 3: Verify recovery on interrupted work**

Run recovery tests for:

- pending crawl jobs
- pending enrichment runs
- partially published outbox rows

Run:

```bash
cd backend && pytest tests/test_startup_recovery_service.py -v
cd frontend && npm test -- ScrapeProgressPanel.test.jsx
```

- [ ] **Step 4: Update operator documentation**

Document:

- how to start each worker
- how to inspect streams and crawl jobs
- how to rebuild embeddings
- how to validate semantic search

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/category_scrape_service.py backend/app/services/ctgoodjobs_scrape_service.py backend/app/services/progress_store.py backend/app/api/progress.py README.md docs/2026-05-06-ai-ready-architecture-design.md docs/2026-05-06-ai-ready-architecture-implementation-plan.md backend/tests/test_startup_recovery_service.py frontend/src/components/scraper/ScrapeProgressPanel.test.jsx
git commit -m "chore: cut over to eventized crawl and semantic runtime"
```

## Test Matrix

Run these suites at the end of each milestone group.

### Backend Unit and API

```bash
cd backend && pytest \
  tests/test_crawl_job_repository.py \
  tests/test_redis_stream_bus.py \
  tests/test_crawl_jobs_api.py \
  tests/test_ingest_worker.py \
  tests/test_enrichment_worker.py \
  tests/test_job_recommendation_service.py -v
```

### Backend Integration

```bash
docker compose up -d postgres-db redis-mq
cd backend && alembic upgrade head
cd backend && pytest \
  tests/integration/test_job_embeddings_pgvector.py \
  tests/integration/test_semantic_search_api.py -v
```

### Frontend

```bash
cd frontend && npm test
cd frontend && npm run build
```

## Rollout Notes

- Migrate JobsDB first, then CTgoodjobs.
- Do not enable semantic mode in the UI until `job_embeddings` has a meaningful backfill.
- Keep lexical mode as the default until hybrid search has passed manual QA.
- Treat `event_outbox` and `crawl_jobs` as the hard source of truth for operations, not Redis alone.

## Assumptions

- PostgreSQL remains the only persistent database.
- `pgvector` is acceptable as an in-database vector layer; no external vector DB is required.
- Local sentence-transformer embeddings are acceptable for v1.
- The repo will stay monorepo-style even after worker separation.
- LinkedIn remains out of scope.
