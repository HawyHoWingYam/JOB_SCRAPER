# Schema Map

## Current Responsibilities

The database is the durable state boundary for crawl orchestration, listing staging, canonical job records, taxonomy governance, AI enrichment runs, embeddings, scheduler state, runtime settings, and event handoff. PostgreSQL is the production database, with pgvector enabled for semantic retrieval.

## Current Implementation Map

- Connection/session setup: `backend/app/database.py`
- ORM models: `backend/app/models/*`
- Alembic migrations: `backend/alembic/versions/*`
- Bootstrap path: `backend/scripts/bootstrap_db.py`, `backend/scripts/init_db.py`
- Docker database service: `docker-compose.yml` service `postgres-db`
- Connected schema snapshot via PostgreSQL MCP: 24 tables in `public`

## Table Groups

| Group | Tables | Role |
| --- | --- | --- |
| Crawl control and staging | `crawl_jobs`, `crawl_job_events`, `crawl_job_listings` | Durable crawl requests, ordered progress history, listing/detail staging rows |
| Canonical job data | `companies`, `jobs` | Source-normalized company and job records served to users |
| Scheduler state | `scrape_schedules`, `schedule_executions`, `apscheduler_jobs` | Persisted schedules, execution audit, APScheduler jobstore |
| Enrichment runs | `enrichment_runs`, `enrichment_run_items`, `company_enrichment_runs`, `company_enrichment_run_items` | AI run orchestration and per-item status |
| Taxonomy and skills | `job_domains`, `job_categories`, `job_subcategories`, `skill_categories`, `skill_technologies`, `skills`, `job_skills`, `job_skill_mentions`, `skill_review_candidates` | Governed job category and skill hierarchy plus extracted mentions |
| Retrieval | `job_embeddings` | One current vector/document snapshot per job |
| Runtime configuration | `app_runtime_settings` | Singleton AI provider/profile settings and last test metadata |
| Event delivery | `event_outbox` | Durable pending events for Redis Stream publication |

## Data and Control Flow

1. API or scheduler creates a `crawl_jobs` row and a matching `event_outbox` row.
2. Outbox publisher sends the durable event to Redis Streams.
3. Crawl workers update `crawl_jobs`, append `crawl_job_events`, and upsert `crawl_job_listings`.
4. Detail and ingest workers convert staged listing/detail payloads into `companies` and `jobs`.
5. Ingestion/enrichment emits lifecycle events that drive AI enrichment and embedding workers.
6. AI writes summaries, taxonomy decisions, skill links/mentions, and enrichment run progress.
7. Embedding workers upsert `job_embeddings`, which retrieval services join to `jobs`.
8. Health, progress, search, scheduler, and admin APIs read the same tables for operator and user-facing views.

## Current Database Snapshot

Connected local database row counts observed through PostgreSQL MCP:

| Table | Rows |
| --- | ---: |
| `crawl_job_listings` | 5436 |
| `event_outbox` | 1371 |
| `enrichment_run_items` | 752 |
| `crawl_job_events` | 724 |
| `crawl_jobs` | 50 |
| `enrichment_runs` | 21 |
| `jobs` | 3 |
| `job_embeddings` | 3 |
| `companies` | 2 |
| `app_runtime_settings` | 1 |
| Other tables | 0 each in the connected local DB snapshot |

## Tests and Coverage

- Repository/unit tests cover crawl jobs, crawl listings, job upsert, outbox publishing, runtime settings, enrichment runs, embeddings, taxonomy governance, and scheduler dispatch.
- PostgreSQL integration coverage exists for pgvector embeddings and semantic search.
- Several tests use SQLite-style in-memory schemas, so PostgreSQL-specific behavior is only partly covered.

## Known Gaps or Risks

- Bootstrap and Alembic both participate in schema creation, so the baseline story is split.
- Some production tables use PostgreSQL-only types and extensions while many tests use SQLite fixtures.
- Timestamp columns mix timezone-aware and timezone-naive definitions.
- Large JSON columns carry source payloads and worker metadata without a documented retention policy.
- The connected DB has many staged listings but only a few canonical jobs, suggesting the staging-to-ingest boundary needs operational attention.

## Optimization Backlog

- Generate schema documentation from SQLAlchemy models, Alembic migrations, and live PostgreSQL metadata to reduce audit drift.
- Define bounded ownership for table groups so crawl, scheduler, enrichment, retrieval, taxonomy, and operator state have explicit stewards.
- Add retention policies for raw payloads, crawl events, outbox rows, enrichment runs, embeddings, and runtime test metadata.
- Build a true Alembic baseline and a CI drift check that upgrades an empty PostgreSQL database and compares expected constraints/indexes.
- Track staged-listing to published-job ratios in operator health so stalled ingest/detail boundaries become visible.

## Follow-up Audit Questions

- Which tables should be treated as append-only audit history versus mutable current state?
- What retention policy should exist for `event_outbox`, `crawl_job_events`, raw staging payloads, and old enrichment runs?
- Should schema ownership be defined by bounded context instead of one shared ORM metadata surface?
- Should database documentation be generated from models/migrations to avoid drift?
