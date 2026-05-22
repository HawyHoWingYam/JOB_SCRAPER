# Execution Unit: Ingest Workers

## Current Responsibilities

Ingest workers consume canonical job payloads, validate source identity and minimum job content, upsert companies and jobs, update crawl/listing metrics, and publish lifecycle events for enrichment and embedding.

## Current Implementation Map

- Worker: `backend/app/workers/run_ingest_worker.py`
- Docker service: `ingest-worker`
- Repositories: `backend/app/repositories/job_repository.py`, `company_repository.py`, `crawl_job_listing_repository.py`, `event_outbox_repository.py`
- Outbox publisher: `backend/app/messaging/outbox_publisher.py`
- Redis topics: `stream.job.ingest`, `stream.job.lifecycle`, `stream.job.ingest.dead_letter`

## Data and Control Flow

The worker reads `stream.job.ingest` consumer-group messages and extracts either a nested `job` envelope or legacy flat payload. `_validate_canonical_job` checks source site, source job id, URL/raw data, and minimum title/description content before database writes.

Valid records upsert company and job rows through repositories, update ingest/listing metrics, enqueue a `job.ingested` lifecycle event through `event_outbox`, commit, publish pending outbox rows, and acknowledge the Redis message. Duplicate replays rely on source-aware repository upsert behavior and lifecycle emission guards.

Malformed records are converted to `ingest.message_dead_lettered` events on `stream.job.ingest.dead_letter`, and crawl job metrics are updated when possible. Dead-letter publication is a direct Redis write rather than an outbox event.

## Tests and Coverage

- `backend/tests/test_ingest_worker.py`
- `backend/tests/test_job_repository_upsert.py`
- `backend/tests/test_crawl_job_listing_repository.py`
- `backend/tests/test_redis_stream_bus.py`

## Known Gaps or Risks

- `_validate_canonical_job` exists, but schema validation is still partial and hand-rolled in the worker.
- Dead-letter events are not persisted through the outbox and are not exposed through an operator API or UI.
- Ingest is the bridge between crawlers and downstream AI/search systems, so source payload shape drift can cascade quickly.
- Idempotency depends on source identity normalization and repository upsert behavior remaining aligned.
- Lifecycle publication uses the outbox, but error/dead-letter publication does not.

## Optimization Backlog

- Replace hand-rolled canonical payload checks with a Pydantic canonical ingest envelope shared by crawler tests and ingest.
- Add an operator API/UI for dead-letter inspection, retry, and acknowledgement.
- Move dead-letter publication onto the outbox or persist dead-letter rows before Redis publication.
- Keep expanding `job_repository_upsert` coverage around source identity backfill, duplicate replay, and company reassignment.
- Add fixture-based contract tests for each source crawler's canonical payload.

## Follow-up Audit Questions

- Which malformed payload classes should be retryable after operator correction?
- Should ingest accept legacy flat payloads long term or require the nested canonical envelope?
- Should lifecycle events include a schema version for downstream consumers?
