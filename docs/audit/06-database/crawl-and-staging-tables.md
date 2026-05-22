# Crawl and Staging Tables

## Current Responsibilities

This scope stores crawl orchestration state and intermediate scraped data before records become canonical `jobs` and `companies`. It is the database side of the listing/detail crawl pipeline.

## Current Implementation Map

- Models: `backend/app/models/crawl_job.py`, `backend/app/models/crawl_job_listing.py`
- Repositories: `backend/app/repositories/crawl_job_repository.py`, `backend/app/repositories/crawl_job_listing_repository.py`
- API: `backend/app/api/crawl_jobs.py`, `backend/app/api/progress.py`
- Workers: `backend/app/workers/run_crawl_worker.py`, `backend/app/workers/run_ingest_worker.py`
- Recovery: `backend/app/services/startup_recovery_service.py`, `backend/scripts/recover_failed_crawl_auto_runs.py`
- Tests: `backend/tests/test_crawl_job_repository.py`, `backend/tests/test_crawl_job_listing_repository.py`, `backend/tests/test_crawl_worker.py`, `backend/tests/test_ingest_worker.py`, `backend/tests/test_startup_recovery_service.py`

## Tables and Column Use

| Table | Key columns | Column purpose |
| --- | --- | --- |
| `crawl_jobs` | `id`, `source_site`, `trigger_type`, `schedule_id`, `status` | Durable crawl request and current lifecycle state |
| `crawl_jobs` | `request_payload`, `requested_by` | Original crawl parameters and operator/API attribution |
| `crawl_jobs` | `queued_at`, `started_at`, `completed_at`, `error_message`, `metrics` | Timing, failure, and worker result metadata |
| `crawl_job_events` | `crawl_job_id`, `sequence_no`, `event_type`, `payload` | Ordered audit log for crawl progress and UI progress reconstruction |
| `crawl_job_events` | `emitted_by`, `created_at` | Worker/source attribution and event timestamp |
| `crawl_job_listings` | `crawl_job_id`, `source_site`, `source_job_id`, `source_url` | Listing-phase staging identity and source link |
| `crawl_job_listings` | `source_classification_id`, `source_classification_name`, `listing_page`, `listing_rank` | Source taxonomy and ordering context from listing pages |
| `crawl_job_listings` | `listing_payload`, `detail_payload` | Raw structured listing and detail data used by ingest |
| `crawl_job_listings` | `detail_status`, `detail_attempts`, `last_detail_crawl_job_id`, `detail_error_message` | Detail acquisition state machine and retry/debug fields |
| `crawl_job_listings` | `published_job_id`, `detail_started_at`, `detail_completed_at` | Link to canonical published job and detail timing |

## Data and Control Flow

1. API, scheduler, or recovery creates a `crawl_jobs` row.
2. `crawl_job_events` receives `crawl.requested` and later worker status events with monotonically increasing `sequence_no`.
3. Listing-phase workers upsert `crawl_job_listings` by `(crawl_job_id, source_site, source_job_id)`.
4. Detail-phase workers select pending/manual-action rows by `detail_status`, write `detail_payload`, and update attempts/timestamps.
5. Ingest worker consumes successful staged rows, creates/updates canonical `companies` and `jobs`, then writes `published_job_id`.
6. Startup recovery marks active `crawl_jobs` and running detail rows as failed after process interruption, except manual-action paths that remain resumable.

## Constraints and Indexes

- `crawl_jobs.id` is the primary key and has indexes on `source_site`, `status`, `schedule_id`, `queued_at`, and `created_at`.
- `crawl_job_events` enforces `UNIQUE (crawl_job_id, sequence_no)` and cascades from `crawl_jobs`.
- `crawl_job_listings` enforces `UNIQUE (crawl_job_id, source_site, source_job_id)` and indexes `detail_status`, `source_site`, `source_job_id`, `source_classification_id`, `last_detail_crawl_job_id`, and `published_job_id`.

## Current Database Snapshot

- `crawl_job_listings`: 5436 rows
- `crawl_job_events`: 724 rows
- `crawl_jobs`: 50 rows

The snapshot shows a large staging backlog relative to canonical `jobs` rows, so ingest and detail completion should be checked operationally.

## Tests and Coverage

- Repository tests cover creation, event sequencing, listing upsert, detail state transitions, and status filters.
- Worker tests cover listing and detail worker behavior.
- Startup recovery tests cover active job recovery and detail row status repair.

## Known Gaps or Risks

- `crawl_job_listings.crawl_job_id`, `last_detail_crawl_job_id`, and `published_job_id` are modeled as UUID references but are not enforced as database foreign keys in the connected schema.
- Raw payload columns can grow quickly and lack documented retention/archive rules.
- Staging rows represent multiple phases in one table, which keeps flow compact but makes state transitions more important to guard.
- Listing-batch APIs expose recent operational state, but grouped backlog queries and older pending detail visibility need hardening.
- Manual-action and cancellation state live in durable crawl records, but active worker behavior is not fully enforced by database state alone.

## Optimization Backlog

- Add foreign keys for staging-to-crawl, last-detail-crawl, and published-job references once data cleanup verifies existing rows.
- Constrain canonical `detail_status` values and document allowed state transitions.
- Add composite indexes for listing batch views by source, category, detail status, crawl job, and age.
- Add retention/archive rules for `listing_payload` and `detail_payload` after publication or after failed attempts age out.
- Promote manual-action state into explicit columns or a related table if lease, acknowledgement, timeout, and retry policy are added.

## Follow-up Audit Questions

- Should listing rows have enforced foreign keys to `crawl_jobs` and `jobs`?
- Which `detail_status` values are canonical, and should they be constrained?
- What cleanup rule should apply after `published_job_id` is populated?
- Should failed detail attempts be normalized into a separate attempt table?
