# Business Domain: Scraper and Crawl

## Current Responsibilities

This domain discovers source categories, queues crawl work, executes listing/detail crawls, and emits progress plus ingest events. It covers both JobsDB and CTgoodjobs and supports `headless` and `headed` crawl modes.

## Current Implementation Map

- API entrypoints: `backend/app/api/crawl_jobs.py`, `backend/app/api/schedules.py`
- Dispatch service: `backend/app/services/crawl_job_dispatch_service.py`
- Worker runtime: `backend/app/workers/run_crawl_worker.py`, `backend/app/workers/run_headed_crawl_worker.py`
- Source crawlers: `backend/crawler/job_crawler/spiders/*`, `backend/app/scraper/*`, `backend/app/sources/*`
- Frontend operator UI: `frontend/src/components/scraper/ScheduleManager.jsx`

## Data and Control Flow

`POST /api/v1/crawl-jobs` creates durable `crawl_jobs` rows, records request payloads, and publishes to Redis stream topics. `crawl_mode=headed` routes to `stream.crawl.commands.headed`; other crawls route to `stream.crawl.commands`.

Listing crawls stage discovered listing rows in `crawl_job_listings`. Detail crawls can target categories or a specific source listing crawl job through `source_listing_crawl_job_id`.

## Tests and Coverage

- `backend/tests/test_crawl_jobs_api.py`
- `backend/tests/test_crawl_job_dispatch_service.py`
- `backend/tests/test_jobsdb_spider.py`
- `backend/tests/test_jobsdb_headed_spider.py`
- `backend/tests/test_ctgoodjobs_spider.py`
- `frontend/src/components/scraper/ScheduleManager.test.jsx`

## Known Gaps or Risks

- The crawl domain mixes source-specific behavior, queue routing, and operator recovery in the same worker path.
- Headed crawl depends on host-side browser state and a single-user profile, so reproducibility differs from container workers.
- Frontend direct override has to mirror backend validation around crawl phase, detail limits, and listing batches.
- Cancellation is durable at the API level, but long-running worker loops still need more cooperative stop checks.
- The listing-batch selector is recent-batch oriented and can miss older pending detail rows when a backlog grows.

## Optimization Backlog

- Split the broad crawl worker into smaller listing, detail, dispatch, and progress services so source adapters stop owning queue and recovery concerns.
- Add a backend capability/default matrix per source and mode covering listing, detail, headed, headless, manual action, and recommended defaults for JobsDB and CTgoodjobs.
- Make cancellation cooperative inside crawler loops and add tests that prove a running listing/detail crawl stops before publishing more ingest events.
- Replace recent-batch discovery with grouped database queries and filters for source, category, detail status, and age so older pending detail batches stay operator-visible.

## Follow-up Audit Questions

- Should listing and detail crawls be separate domain services with separate queue contracts?
- Should headed crawl worker status be modeled as a first-class runtime dependency in health output?
- Should crawl source adapters expose a shared capability matrix for listing, detail, headed, and manual action support?
