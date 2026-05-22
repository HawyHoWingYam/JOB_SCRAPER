# Data Lifecycle: Listing Staging

## Current Responsibilities

Listing staging records source job IDs found during listing crawls before full detail acquisition. It enables split listing/detail crawl phases and backlog visibility.

## Current Implementation Map

- Model: `backend/app/models/crawl_job_listing.py`
- Repository: `backend/app/repositories/crawl_job_listing_repository.py`
- API: `GET /api/v1/crawl-jobs/listing-batches` in `backend/app/api/crawl_jobs.py`
- Frontend batch selector: `frontend/src/components/scraper/ScheduleManager.jsx`

## Data and Control Flow

Listing crawls create or update `crawl_job_listings` rows keyed by crawl job and source job identity. Detail runs can request a specific listing batch by `source_listing_crawl_job_id`, and the UI lists recent batches with staged and pending counts.

## Tests and Coverage

- `backend/tests/test_crawl_job_listing_repository.py`
- `backend/tests/test_crawl_jobs_api.py`
- `frontend/src/components/scraper/ScheduleManager.test.jsx`

## Known Gaps or Risks

- Listing staging is a newer table and therefore a key migration boundary.
- Listing rows hold raw listing payloads plus detail status; that makes it both staging and detail tracking.
- UI currently exposes only recent batches, not full filtering or remediation.
- Listing batch counts are derived from recent crawl jobs and row scans rather than a grouped aggregate query.
- The table is now central to split-phase crawling, but retention and indexing policy are still implicit.

## Optimization Backlog

- Replace listing-batch enumeration with grouped queries over `crawl_job_listings` and composite indexes for crawl job, source, category, and detail status.
- Separate raw listing payload retention policy from detail status tracking so old payloads can be pruned without losing backlog visibility.
- Add operator filters for pending, failed, completed, stale, and source/category-specific detail batches.
- Record migration and data-shape expectations for `20260520_120000_add_crawl_job_listings.py` and related schedule phase/detail limit migrations.

## Follow-up Audit Questions

- Should listing staging retain historical raw payloads indefinitely?
- Should listing batch status be promoted to its own aggregate summary table?
- Should operators be able to filter batches by detail status and source category?
