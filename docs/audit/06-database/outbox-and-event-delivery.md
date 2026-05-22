# Outbox and Event Delivery

## Current Responsibilities

This scope provides reliable database-to-Redis event handoff. Application services write `event_outbox` rows inside database transactions, then the outbox publisher pushes pending rows to Redis Streams and marks them published or retryable.

## Current Implementation Map

- Model: `backend/app/models/event_outbox.py`
- Repository: `backend/app/repositories/event_outbox_repository.py`
- Publisher: `backend/app/messaging/outbox_publisher.py`
- Topics: `backend/app/messaging/topics.py`
- Producers: `backend/app/services/crawl_job_dispatch_service.py`, `enrichment_run_service.py`, `backend/app/workers/run_ingest_worker.py`, `run_embedding_worker.py`
- Tests: `backend/tests/test_outbox_publisher.py`, `test_crawl_job_dispatch_service.py`, `test_crawl_job_repository.py`, `test_enrichment_run_service.py`, `test_embedding_worker.py`

## Tables and Column Use

| Table | Key columns | Column purpose |
| --- | --- | --- |
| `event_outbox` | `id` | Monotonic database primary key and publish order |
| `event_outbox` | `topic` | Target Redis Stream topic |
| `event_outbox` | `aggregate_type`, `aggregate_id`, `event_type` | Idempotency/debugging identity for domain event |
| `event_outbox` | `source_service` | Producer attribution |
| `event_outbox` | `payload` | JSON event body to publish |
| `event_outbox` | `status` | `pending`, published, or retry/failure state |
| `event_outbox` | `attempt_count`, `available_at` | Retry scheduling and backoff support |
| `event_outbox` | `published_at`, `last_error`, `created_at` | Publication audit and failure diagnostics |

## Data and Control Flow

1. Domain service mutates durable business tables and enqueues `event_outbox` in the same DB session.
2. Outbox publisher queries pending rows where `available_at <= now`, ordered by `id`.
3. Publisher sends `topic` and `payload` to Redis Streams.
4. On success it marks the row published; on failure it increments attempts and records `last_error`.
5. Consumers acknowledge Redis Stream events separately, so DB outbox and Redis consumer state form two operational queues.

## Constraints and Indexes

- Primary key: `event_outbox.id`.
- Indexes exist on `status`, `available_at`, `aggregate_id`, and `created_at`.
- No database-level unique idempotency key is present for `(aggregate_type, aggregate_id, event_type)`.

## Current Database Snapshot

- `event_outbox`: 1371 rows

This is one of the largest tables in the connected local DB and should be reviewed for published/pending distribution and retention.

## Tests and Coverage

- Outbox publisher tests cover successful publish, failure retry marking, and repository pending-row ordering.
- Dispatch and enrichment tests assert outbox rows are created with durable domain changes.

## Known Gaps or Risks

- There is no documented purge/archive policy for published rows.
- Without a uniqueness constraint or explicit idempotency key, duplicate domain events must be controlled in service code.
- JSON payload shape is not enforced by the database.
- Large pending counts could indicate publisher downtime, Redis issues, or stuck retry backoff.
- Some progress, ingest, and dead-letter flows still publish directly to Redis streams rather than through the outbox.
- Dead-letter records are stream-oriented and not modeled as a first-class database remediation queue.

## Optimization Backlog

- Constrain outbox statuses and add an explicit idempotency key or unique domain-event key where duplicate events would be harmful.
- Add purge/archive jobs for published rows and long-retained failed rows with operator-visible retention settings.
- Validate outbox payloads at the application boundary with versioned schemas per event type.
- Add operator health metrics for pending count, retry count, oldest available event age, and last publisher success.
- Decide whether dead letters should be mirrored into database tables for remediation, search, and audit.

## Follow-up Audit Questions

- What statuses are allowed, and should they be constrained?
- Should published rows be purged after a fixed window?
- Should each event have an idempotency key or unique domain-event constraint?
- Should operator health report pending, retrying, and oldest available event age?
