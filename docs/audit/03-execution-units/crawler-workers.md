# Execution Unit: Crawler Workers

## Current Responsibilities

Crawler workers consume crawl commands, run source-specific listing and detail crawls, persist crawl/listing state transitions, emit operator progress, handle manual-action states, and publish canonical job payloads for ingestion.

## Current Implementation Map

- Headless worker: `backend/app/workers/run_crawl_worker.py`
- Headed worker wrapper: `backend/app/workers/run_headed_crawl_worker.py`
- Dispatch service: `backend/app/services/crawl_job_dispatch_service.py`
- Crawl repositories: `backend/app/repositories/crawl_job_repository.py`, `crawl_job_listing_repository.py`
- Source crawlers: `backend/app/scraper/*`
- Host runner: `backend/scripts/run_headed_crawl_worker_host.cmd`, `run_headed_crawl_worker_host.ps1`
- Docker service: `crawl-worker`
- Redis topics: `stream.crawl.commands`, `stream.crawl.commands.headed`, `stream.crawl.progress`, `stream.job.ingest`

## Data and Control Flow

Dispatch creates durable crawl jobs and emits `crawl.requested` commands. Workers acknowledge and ignore non-`crawl.requested` messages, then process listing or detail phases based on the request payload.

Listing crawls persist staging rows in `crawl_job_listings` and update crawl progress without publishing ingest messages. Detail crawls load candidates from listing rows, mark each target running, completed, failed, or manual-action-required, and publish canonical detail payloads to `stream.job.ingest`. Progress events are written directly to Redis and include phase, page/detail counts, manual action state, cancellation state, and downstream backlog state.

Cancellation is persisted and emitted in progress, but the running worker does not currently use an active cancellation token inside source extraction loops. Ingest publication and progress publication are direct Redis writes rather than outbox-backed events.

## Tests and Coverage

- `backend/tests/test_crawl_job_dispatch_service.py`
- `backend/tests/test_crawl_worker.py`
- `backend/tests/test_crawl_job_repository.py`
- `backend/tests/test_crawl_job_listing_repository.py`
- `backend/tests/test_crawl_jobs_api.py`
- `backend/tests/test_jobsdb_headed_spider.py`
- `backend/tests/test_ctgoodjobs_headed_spider.py`
- `frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`

## Known Gaps or Risks

- Headed workers run partly outside Docker on the Windows host, with browser profile and manual verification state as operational dependencies.
- Workers acknowledge unexpected command event types, which avoids retry noise but can hide producer mistakes.
- Cancellation is visible to operators but is not fully cooperative inside active crawl/extraction work.
- Progress and ingest events are direct Redis publications, so they do not share the outbox durability used by lifecycle events.
- Active crawl visibility depends mainly on progress messages and persisted crawl job rows; there is no worker heartbeat or active-job registry.
- Source crawler changes can affect listing staging, detail candidate quality, and ingest payload quality at the same time.

## Optimization Backlog

- Add heartbeat and active-job visibility for crawl workers, including headed host workers.
- Add cooperative cancellation checks and tests that prove a running listing/detail crawl stops before the next unit of work.
- Move extraction orchestration into smaller services so worker control flow, source scraping, detail transitions, and publication can be tested independently.
- Consider outbox-backed ingest and progress publication for phases where lost Redis writes create operator or downstream ambiguity.
- Add contract tests for canonical listing/detail payloads per source site before ingestion.

## Follow-up Audit Questions

- Should non-`crawl.requested` command messages be dead-lettered instead of acknowledged silently?
- Should manual-action-required detail rows be resumed by the same command path or a separate operator command?
- Should host worker setup be represented in Docker Compose docs as an explicit external dependency?
