# JOB_SCRAPER AI-Ready Architecture Design

> Date: 2026-05-06
> Status: Approved design baseline
> Preferred target state: Event-driven microservices
> Preferred delivery style: Incremental migration, not big-bang rewrite

## 1. Summary

This document defines the target architecture for upgrading `JOB_SCRAPER` from a single FastAPI-heavy scraping application into an AI-ready, event-driven data platform built on:

- PostgreSQL + `pgvector`
- Redis
- Scrapy + Playwright
- FastAPI control plane
- dedicated workers for crawl, ingestion, enrichment, embedding, retrieval, and recommendation

The target state is a full event-driven microservice topology. The delivery path is intentionally staged:

1. establish the event and persistence backbone
2. split crawl execution out of the FastAPI process
3. move ingestion and AI work onto explicit workers
4. add `pgvector`-backed semantic retrieval and recommendation
5. tighten observability, recovery, and cutover safety

This keeps the long-term architecture ambitious without turning the first execution pass into an unmanageable rewrite.

## 2. Why This Change Is Worth It

The current repository already has strong building blocks:

- multiple sources: JobsDB and CTgoodjobs
- schedule-driven execution
- explicit enrichment runs
- governed taxonomy and skill normalization
- React UI for search, filters, dashboard, and operations

The current limits are architectural, not feature-level:

- crawl orchestration is source-specific and service-specific
- scraping runs inside the same backend deployment boundary as API and scheduler logic
- progress is mostly in-process memory, with Redis available but not yet acting as a job backbone
- search is still lexical/structured only
- vector search is not present even though the repo already uses embedding logic in-process for skill similarity

The upgrade should therefore optimize for:

- explicit service boundaries
- resilient async processing
- reusable source adapters
- query-time semantic retrieval
- recommendation features that are grounded in the existing job/taxonomy/skill data

## 3. Current-State Constraints That Must Be Preserved

The following current behaviors are correct and should remain true after the refactor:

- FastAPI remains the user-facing control plane for the frontend.
- Scheduled scraping remains a first-class feature.
- AI enrichment remains downstream of ingestion. Crawl success must not depend on LLM availability.
- Existing frontend routes and payload shapes should be preserved whenever possible.
- Existing taxonomy and skill governance logic should be reused, not rewritten.
- Multi-source support should stay explicit via `source_site`.

The following current implementation details should change:

- in-process progress store for crawl state
- direct scheduler-to-service crawl execution
- source-specific orchestration code paths for every source
- lexical-only job search
- string-only `Job.search_vector`

## 4. Target Architecture

### 4.1 Service Topology

The target monorepo should contain multiple deployable services:

1. `backend-api`
   - external control plane
   - schedules CRUD
   - jobs search/filter endpoints
   - semantic search proxy
   - recommendation proxy
   - stats, settings, AI monitoring

2. `scheduler-worker`
   - polls schedule definitions
   - creates crawl jobs
   - emits crawl command events

3. `crawl-worker`
   - runs Scrapy spiders
   - uses Playwright only for pages that require rendering or interaction
   - emits normalized crawl item events and progress events

4. `ingest-worker`
   - consumes crawl item events
   - upserts companies and jobs
   - persists raw payloads and normalized job fields
   - emits `job.ingested`

5. `enrichment-worker`
   - consumes `job.ingested`
   - runs taxonomy, skills, summary, and experience enrichment
   - emits `job.enriched`

6. `embedding-worker`
   - consumes `job.ingested` and `job.enriched`
   - builds embedding documents
   - generates vectors with a local sentence-transformer model
   - writes `pgvector` rows
   - emits `job.embedded`

7. `retrieval-api`
   - internal API for semantic search and retrieval
   - combines vector similarity with metadata filters
   - supports hybrid retrieval

8. `recommendation-api`
   - internal API for similar jobs and recommendation scoring
   - reuses job embeddings, taxonomy, skill mentions, and freshness signals

### 4.2 Runtime Diagram

```text
Frontend UI
   |
   v
backend-api  ----------------------------+
   |                                     |
   | create manual crawl jobs            | query search / stats / AI state
   v                                     |
Redis Streams <---- scheduler-worker ----+
   |
   +--> crawl-worker ------> crawl progress events
   |            |
   |            +--> normalized crawl item events
   |
   +--> ingest-worker ------> Postgres jobs/companies/raw_data
   |            |
   |            +--> job.ingested
   |
   +--> enrichment-worker --> Postgres taxonomy/skills/summary
   |            |
   |            +--> job.enriched
   |
   +--> embedding-worker ---> Postgres job_embeddings (pgvector)
   |
   +--> retrieval-api / recommendation-api
```

## 5. Repository Layout After Refactor

The refactor should keep a single repo, but move toward multi-service boundaries.

### 5.1 Control Plane

Keep under `backend/app/`:

- API routers
- repositories
- core domain models
- schedule management
- settings
- stats and filters
- query orchestration

### 5.2 New Worker and Search Packages

Add these package roots:

```text
backend/
  app/
    api/
    models/
    repositories/
    services/
    search/
    workers/
    messaging/
    sources/
  crawler/
    scrapy.cfg
    job_crawler/
      settings.py
      items.py
      pipelines.py
      middlewares.py
      emitters/
      spiders/
```

Recommended responsibilities:

- `app/sources/`
  - pure source parsing and normalization contracts
  - reusable by both spiders and tests
- `app/messaging/`
  - Redis Streams bus
  - event envelope helpers
  - outbox publisher
- `app/workers/`
  - process entrypoints and worker loops
- `app/search/`
  - lexical query builder
  - semantic query builder
  - hybrid scorer
- `crawler/job_crawler/`
  - Scrapy project only

## 6. Data Model Changes

### 6.1 Existing Tables To Keep

- `jobs`
- `companies`
- `scrape_schedules`
- `schedule_executions`
- `enrichment_runs`
- skill taxonomy and mention tables

### 6.2 New Tables

The following tables should be added.

#### `crawl_jobs`

Purpose:
- the durable control-plane representation of a requested crawl

Recommended columns:

- `id UUID PK`
- `source_site VARCHAR(32)`
- `trigger_type VARCHAR(32)` with values like `manual`, `schedule`, `replay`
- `schedule_id UUID NULL`
- `status VARCHAR(32)` with values like `queued`, `running`, `partial`, `completed`, `failed`, `cancelled`
- `request_payload JSONB`
- `requested_by VARCHAR(255) NULL`
- `queued_at TIMESTAMP`
- `started_at TIMESTAMP NULL`
- `completed_at TIMESTAMP NULL`
- `error_message TEXT NULL`
- `metrics JSONB`
- `created_at TIMESTAMP`
- `updated_at TIMESTAMP`

#### `crawl_job_events`

Purpose:
- durable history for crawl progress and state transitions

Recommended columns:

- `id BIGSERIAL PK`
- `crawl_job_id UUID FK`
- `sequence_no INTEGER`
- `event_type VARCHAR(100)`
- `payload JSONB`
- `emitted_by VARCHAR(100)`
- `created_at TIMESTAMP`

#### `event_outbox`

Purpose:
- reliable publication boundary between Postgres writes and Redis Streams

Recommended columns:

- `id BIGSERIAL PK`
- `topic VARCHAR(100)`
- `aggregate_type VARCHAR(100)`
- `aggregate_id VARCHAR(100)`
- `event_type VARCHAR(100)`
- `payload JSONB`
- `status VARCHAR(32)` with values like `pending`, `published`, `failed`
- `attempt_count INTEGER`
- `available_at TIMESTAMP`
- `published_at TIMESTAMP NULL`
- `last_error TEXT NULL`
- `created_at TIMESTAMP`

#### `job_embeddings`

Purpose:
- versioned, queryable vector store inside Postgres

Recommended columns:

- `job_id UUID PK FK -> jobs.id`
- `embedding_model VARCHAR(255)`
- `embedding_dimensions INTEGER`
- `embedding_version INTEGER`
- `document_text TEXT`
- `document_hash VARCHAR(64)`
- `embedding vector(384)`
- `updated_at TIMESTAMP`

This design is preferred over storing a single vector column directly on `jobs` because it:

- avoids overloading the core job row
- supports model/version changes
- makes embedding refresh logic explicit
- keeps semantic search concerns isolated

### 6.3 Optional Later Tables

Do not add these in the first execution pass unless needed:

- `company_embeddings`
- `job_document_chunks`
- `recommendation_snapshots`
- `query_embedding_cache`

They are valid future extensions, but not required for the first AI-ready release.

## 7. Messaging Backbone

### 7.1 Transport Choice

Use Redis Streams as the operational event transport.

Why Redis Streams over pub/sub:

- durable pending work
- replayable consumer-group semantics
- backpressure support
- easier worker recovery than in-memory state or raw pub/sub

### 7.2 Stream Set

Keep the stream count small and topic-driven.

Recommended streams:

- `stream.crawl.commands`
- `stream.crawl.progress`
- `stream.job.ingest`
- `stream.job.lifecycle`
- `stream.job.embedding`

Recommended event types:

- `crawl.requested`
- `crawl.started`
- `crawl.page_processed`
- `crawl.item_emitted`
- `crawl.completed`
- `crawl.failed`
- `job.ingested`
- `job.enriched`
- `job.embedding.requested`
- `job.embedded`

### 7.3 Event Envelope

Use a stable envelope across all streams:

```json
{
  "event_id": "uuid",
  "event_type": "job.ingested",
  "aggregate_type": "job",
  "aggregate_id": "job-uuid",
  "source_service": "ingest-worker",
  "occurred_at": "2026-05-06T12:00:00Z",
  "schema_version": 1,
  "payload": {}
}
```

## 8. Scrapy + Playwright Design

### 8.1 Rule

Scrapy becomes the default crawl engine.

Playwright is only enabled:

- for pages that require JS rendering
- for anti-bot fallback flows
- for interactive detail-page retrieval that cannot be solved with HTTP + parser logic

### 8.2 Source Strategy

#### JobsDB

Implement first.

Why:

- it already has a natural list/detail split
- it already uses structured API discovery for lists
- it is the easiest source to map into a Scrapy spider + item pipeline model

#### CTgoodjobs

Implement second.

Why:

- the parsers already exist
- it will validate whether the shared source contract is real or only works for JobsDB

### 8.3 Shared Source Contract

Add a source-neutral normalized item shape:

```python
class CanonicalScrapedJob(TypedDict):
    source_site: str
    source_job_id: str
    source_url: str
    title: str
    description: str | None
    company_name: str | None
    location: str | None
    salary_range: str | None
    employment_type: str | None
    source_classification_id: str | int | None
    source_classification_name: str | None
    source_subclassification_id: str | None
    source_subclassification_name: str | None
    posted_date: str | None
    raw_data: dict[str, Any]
```

This becomes the only payload shape that the ingest worker accepts from crawl output.

## 9. Embedding and Semantic Search Design

### 9.1 Embedding Model

Use a local open-source model first:

- `sentence-transformers/all-MiniLM-L6-v2`
- dimension: `384`

Reason:

- already aligned with the current repo's optional `sentence-transformers` usage
- free to run locally
- sufficient for v1 job search and recommendation

### 9.2 Embedding Document Builder

Do not embed raw HTML or full unbounded descriptions.

Build a normalized document string from:

- title
- company name
- source taxonomy names
- AI summary
- canonical matched skills
- cleaned description excerpt

This document builder must be deterministic and hashable. Re-embed only when the document hash changes.

### 9.3 Query Modes

Support three retrieval modes:

1. lexical
   - existing filter and text matching
2. semantic
   - pure vector search plus metadata filters
3. hybrid
   - vector similarity + lexical/taxonomy/skill/freshness reranking

### 9.4 First Recommendation Formula

For `similar jobs`, use a transparent weighted score:

- `0.65` semantic similarity
- `0.20` matched canonical skill overlap
- `0.10` same taxonomy path bonus
- `0.05` recency/freshness bonus

Keep it simple and inspectable. Do not use an LLM inside the recommendation path.

## 10. RAG Design

Do not start with chunk-heavy document RAG.

For v1, the RAG layer should use:

- query embedding
- filtered top-k job retrieval
- compact job context objects

This supports:

- AI-assisted job browser search
- related jobs
- future assistant workflows

without immediately introducing chunk storage, chunk re-ranking, or a separate vector database.

## 11. Delivery Strategy

### 11.1 Target State

The target state remains the user's preferred choice:

- event-driven microservices
- explicit worker boundaries
- vector retrieval and recommendation as dedicated runtime concerns

### 11.2 Delivery Principle

Do not attempt to land the full target state in one pass.

The migration should move in this order:

1. schema and infrastructure backbone
2. message bus and durable crawl jobs
3. Scrapy crawl worker
4. ingest worker
5. enrichment extraction from in-process background logic
6. embedding worker + `pgvector`
7. retrieval and recommendation APIs
8. cutover and cleanup

This gives a path to the preferred architecture without losing operational control.

## 12. What Should Not Be In Scope

The following are explicitly out of scope for this migration:

- LinkedIn source reintroduction
- external vector DBs such as Pinecone, Qdrant, Weaviate, Milvus
- Dify or n8n as core runtime dependencies
- chunk-level document RAG in v1
- multi-model embedding strategies in v1
- replacing the React frontend with another UI stack

## 13. Operational Risks and Mitigations

### Risk: too many services too early

Mitigation:
- keep a single repo
- stage activation by compose profiles
- preserve API ownership in `backend-api`

### Risk: Redis events diverge from DB truth

Mitigation:
- add `event_outbox`
- persist `crawl_jobs` and `crawl_job_events`
- make workers idempotent by aggregate id + content hash

### Risk: vector search is hard to test with SQLite

Mitigation:
- keep most unit tests SQLite-backed
- add Postgres integration tests specifically for `pgvector`
- do not emulate vector behavior in SQLite

### Risk: crawl cutover breaks schedule operations

Mitigation:
- run manual crawl path and scheduled path through the same `crawl_jobs` mechanism
- keep old crawlers available until JobsDB parity is proven

## 14. Acceptance Criteria

The refactor is successful when:

- manual and scheduled crawl requests create durable `crawl_jobs`
- JobsDB runs through Scrapy, not the old service loop
- CTgoodjobs is migrated onto the same crawl contract
- crawl progress survives process restarts through durable event/state storage
- semantic search works on real `pgvector` data
- similar jobs endpoint returns stable results
- AI enrichment remains decoupled from crawl success
- the frontend can use lexical and semantic search modes without breaking current filters

## 15. Final Recommendation

Use the user's preferred target architecture, but implement it via staged service extraction.

That means:

- design for full event-driven microservices
- execute in the order of durability first, then service split, then semantics

This is the highest-upside route that still has a realistic chance of landing cleanly in this repository.
