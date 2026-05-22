# Migrations, Bootstrap, and Integrity

## Current Responsibilities

This scope covers how the database schema is created, upgraded, and verified. It also tracks cross-table integrity, extension setup, and differences between production PostgreSQL and test schemas.

## Current Implementation Map

- Alembic config: `backend/alembic.ini`, `backend/alembic/env.py`
- Migration files: `backend/alembic/versions/*`
- Bootstrap: `backend/scripts/bootstrap_db.py`, `backend/scripts/init_db.py`
- Verification scripts: `backend/scripts/verify_migration.py`, `backend/scripts/converge_taxonomy_schema.py`
- Docker bootstrap service: `docker-compose.yml` service `db-bootstrap`
- README migration notes: `README.md`
- Tests: `backend/tests/test_bootstrap_db.py`, PostgreSQL integration tests under `backend/tests/integration`

## Data and Control Flow

1. Docker starts `postgres-db` using `pgvector/pgvector:pg15`.
2. `db-bootstrap` runs before API/worker services and executes `bootstrap_db.py`.
3. Bootstrap enables `vector`, calls `Base.metadata.create_all`, and applies a small set of idempotent schedule column updates.
4. Alembic migrations carry subsequent schema changes and are used for controlled upgrades.
5. Tests often create selected ORM tables directly through `Base.metadata.create_all`.

## Integrity Map

| Integrity type | Current examples |
| --- | --- |
| Source identity uniqueness | `jobs(source_site, source_job_id)`, `companies(source_site, source_company_id)` |
| Ordered crawl events | `crawl_job_events(crawl_job_id, sequence_no)` |
| Hierarchical taxonomy uniqueness | Domain/category/subcategory and category/technology/skill unique constraints |
| Join-table identity | `job_skills(job_id, skill_id)` composite primary key |
| Vector dimensionality | `job_embeddings.embedding_dimensions = 384` check constraint |
| Cascades | Run items cascade from runs; crawl events cascade from crawl jobs; embeddings cascade from jobs |
| Set-null links | Crawl job to schedule, schedule execution to crawl job, enrichment run to trigger crawl job |

## PostgreSQL-Specific Surface

- `pgvector` is required for `job_embeddings.embedding`.
- Several ID columns use PostgreSQL UUID types in production.
- JSON fields are used across job raw data, crawl payloads, outbox events, schedule parameters, and crawl metrics.
- APScheduler stores binary `job_state` in `apscheduler_jobs`.

## Tests and Coverage

- `test_bootstrap_db.py` checks extension creation and idempotent schedule column additions.
- Integration tests verify pgvector behavior and semantic search against PostgreSQL.
- Many unit tests use SQLite/in-memory databases and selected table creation, which is fast but less representative of production constraints and types.

## Known Gaps or Risks

- README notes indicate the repository does not have a clean complete Alembic baseline for every historical schema state.
- Bootstrap `create_all` and Alembic migrations coexist, which can hide migration drift if not checked regularly.
- `crawl_job_listings` contains logical references that are not enforced as database foreign keys in the connected schema.
- Timezone handling is inconsistent: some tables use `timestamp with time zone`, others use `timestamp without time zone`.
- JSON payload fields have no formal schema validation at the database level.

## Optimization Backlog

- Create a true Alembic baseline and make new environments migrate from that baseline instead of relying on `create_all`.
- Add CI that runs Alembic upgrade against empty PostgreSQL with pgvector, then verifies expected tables, FKs, indexes, and checks.
- Add foreign-key migrations for staging links after validating existing data and defining orphan repair behavior.
- Standardize timestamp storage to timezone-aware UTC and document conversion at API/frontend boundaries.
- Add generated schema reports under this audit section and fail validation when model/migration/live schema drift is detected.
- Version JSON payload schemas for crawl requests, staged payloads, outbox events, and runtime settings metadata.

## Follow-up Audit Questions

- Should new environments be created only through Alembic from a baseline migration?
- Should CI run an Alembic upgrade check against an empty PostgreSQL database?
- Should FK constraints be added for staging-to-crawl and staging-to-published job links?
- Should timestamp columns be standardized to timezone-aware UTC?
- Should there be a generated schema report committed under `docs/audit/06-database`?
