# Data Lifecycle: Persistence

## Current Responsibilities

Persistence stores durable application state for jobs, companies, crawls, schedules, enrichment runs, embeddings, taxonomy, skills, and runtime settings.

## Current Implementation Map

- Models: `backend/app/models/*`
- Repositories: `backend/app/repositories/*`
- Migrations: `backend/alembic/versions/*`
- Bootstrap: `backend/scripts/bootstrap_db.py`, `backend/scripts/init_db.py`
- Database service: `backend/app/services/database_service.py`

## Data and Control Flow

The API and workers use SQLAlchemy sessions against PostgreSQL. Docker runs `db-bootstrap` before API and worker startup. Alembic carries recent migration history, while README notes the repository does not yet have a complete baseline.

## Tests and Coverage

- `backend/tests/test_bootstrap_db.py`
- `backend/tests/test_crawl_job_repository.py`
- `backend/tests/test_crawl_job_listing_repository.py`
- `backend/tests/integration/test_job_embeddings_pgvector.py`

## Known Gaps or Risks

- The project still has bootstrap/convergence paths alongside Alembic migrations.
- Some tests use SQLite-like fixtures while production uses PostgreSQL plus pgvector.
- Runtime settings include secrets and test metadata in a singleton row, requiring careful response masking.
- Recent listing, schedule phase, detail limit, and app runtime settings changes make schema drift checks more important.
- Database-stored provider secrets are convenient for local operation but need a deliberate security decision.

## Optimization Backlog

- Consolidate the schema into a true Alembic baseline and add CI that upgrades an empty PostgreSQL database.
- Add a generated schema drift report comparing SQLAlchemy models, migrations, and live PostgreSQL metadata.
- Encrypt provider secrets at rest or move them to an external secrets manager while retaining masked API responses.
- Document retention and archival policy for raw listing payloads, crawl events, outbox rows, enrichment runs, and embeddings.

## Follow-up Audit Questions

- Should the schema be consolidated into a true Alembic baseline?
- Should secret material move out of the main application database?
- Should migrations include explicit rollback policy for crawl listing tables?
