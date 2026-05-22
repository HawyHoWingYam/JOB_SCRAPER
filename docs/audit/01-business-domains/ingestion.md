# Business Domain: Ingestion

## Current Responsibilities

Ingestion converts crawl outputs into canonical jobs, companies, listing state, skill lifecycle events, and downstream enrichment triggers.

## Current Implementation Map

- Worker: `backend/app/workers/run_ingest_worker.py`
- Repositories: `backend/app/repositories/job_repository.py`, `company_repository.py`, `crawl_job_listing_repository.py`
- Models: `backend/app/models/job.py`, `company.py`, `crawl_job_listing.py`
- Canonical source contracts: `backend/app/sources/contracts.py`
- Queue topics: `backend/app/messaging/topics.py`

## Data and Control Flow

Crawlers emit payloads to `stream.job.ingest`. The ingest worker upserts source identity, jobs, companies, detail listing state, and then publishes lifecycle events to `stream.job.lifecycle` for enrichment and embedding workers.

## Tests and Coverage

- `backend/tests/test_ingest_worker.py`
- `backend/tests/test_crawl_job_listing_repository.py`
- `backend/tests/test_crawl_job_repository.py`
- `backend/tests/test_source_category_registry.py`

## Known Gaps or Risks

- Ingest is both source-normalization aware and persistence aware, creating a large blast radius.
- Dead-letter handling exists, but operator-facing remediation is still script-driven.
- Canonical contracts are present, but source payload shape drift can still surface late during ingestion.
- `EventEnvelope.schema_version` exists, but canonical job payloads are not yet enforced as a versioned schema at the stream boundary.
- Listing state transitions are split between crawler and ingest concerns, making replay and partial-detail recovery harder to reason about.

## Optimization Backlog

- Promote canonical job payload validation to a Pydantic schema with explicit versioning before persistence and before lifecycle fan-out.
- Move listing detail status transitions behind one repository/service API so replay, duplicate handling, and completed-detail-without-published-job health checks are consistent.
- Add operator-facing dead-letter remediation for ingest failures, including retry, quarantine, and reason summaries.
- Normalize source identity and salary parsing before repository upsert, then retire compatibility backfill paths once existing rows are converged.

## Follow-up Audit Questions

- Should the canonical job contract become an explicit schema version on stream payloads?
- Should ingest publish richer failure metadata for operator recovery?
- Should listing state transitions be isolated from job/company persistence?
