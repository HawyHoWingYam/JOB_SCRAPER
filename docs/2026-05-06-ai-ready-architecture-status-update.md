# AI-Ready Architecture Status Update

> Date: 2026-05-06
> Scope: execution progress update for the AI-ready eventized architecture plan
> Historical landed baseline: `main` at commit `dfcd3369`
> Current local follow-up baseline: uncommitted working tree atop `main`

## Summary

Execution started in isolated git worktrees and completed Tasks 1 through 10 on `main`. An initial Task 11 slice is present on `main`, and the current local follow-up working tree now completes the remaining Task 11 runtime split plus the Task 12 cutover/cleanup slice.

Task 5 and Task 6 were landed together on the feature branch in commit:

- `fc95800a` - `feat: land source-owned crawl worker runtime`

That work was then merged into `main` on 2026-05-06 in commit:

- `7e36f014` - `Merge branch 'feat/ai-ready-eventized'`

Task 7 was then landed in a follow-up isolated worktree on commit:

- `09ab8887` - `feat: add ingest worker and source-aware upsert flow`

Task 9 was then landed directly onto `main` in commit:

- `94c7b6af` - `feat: extract ai enrichment onto dedicated worker`

Task 10 was then landed on feature branch commit:

- `d2c6d268` - `feat: add embedding worker and semantic job retrieval`

That work was then merged into `main` on 2026-05-07 in commit:

- `a537c61a` - `Merge branch 'feat/task10-embedding-semantic'`

An initial Task 11 slice was then landed directly onto `main` in commit:

- `dfcd3369` - `feat: add job recommendations and retrieval mode controls`

Completed in `main`:

- Task 1: Dependency and Container Foundation
- Task 2: Durable Event Backbone and pgvector Schema
- Task 3: Redis Streams Messaging Layer
- Task 4: Crawl Job Control Plane APIs and Progress Refactor
- Task 5: Shared Source Contracts and Parser Extraction
- Task 6: Crawl Worker Runtime and Multi-Source Canonical Emission
- Task 7: Ingest Worker and Durable Upsert Flow
- Task 10: Embedding Worker and Semantic Retrieval
- Task 9: Enrichment Worker Extraction

Partially completed in `main`:

- Task 11: Recommendation Service and Frontend Search Modes
  - backend recommendation endpoints are now live in the control plane
  - frontend retrieval-mode controls and related-jobs modal rendering are now live
  - dedicated `recommendation-api` runtime extraction remains open

Completed in the current local working tree:

- Task 11: Recommendation Service and Frontend Search Modes
  - dedicated `recommendation-api` runtime now exists
  - public recommendation endpoints now proxy to the internal recommendation runtime
  - semantic / hybrid export now follows the retrieval runtime instead of silently falling back to lexical export
- Task 12: Cutover, Recovery, and Cleanup
  - legacy category-scrape entrypoints were removed from the runtime path
  - transitional in-memory `progress_store` usage was removed from the runtime path
  - scrape progress is now derived only from durable `crawl_jobs` + `crawl_job_events`

Next planned task:

- Run worker-profile real-data QA for retrieval, embeddings, recommendations, and durable progress; then land the local Task 11/12 follow-up slice

This update records:

- what has already been implemented
- what has been merged into `main`
- which commits contain that work
- which tests were run successfully
- known gaps and review findings that should be fixed in follow-up work
- environment notes discovered during execution

## Execution Branch and Merge Status

Initial eventized implementation was executed in:

- Worktree: `/Users/hawyho/Documents/GitHub/JOB_SCRAPER/.worktrees/ai-ready-eventized`
- Branch: `feat/ai-ready-eventized`

Task 7 follow-up implementation was executed in:

- Worktree: `/Users/hawyho/Documents/GitHub/JOB_SCRAPER/.worktrees/task7-ingest-worker`
- Branch: `feat/task7-ingest-worker`

Historical feature-branch milestones:

- `d347dfdb` - `feat: move crawl dispatch into durable control plane jobs`
- `fc95800a` - `feat: land source-owned crawl worker runtime`
- `09ab8887` - `feat: add ingest worker and source-aware upsert flow`
- `94c7b6af` - `feat: extract ai enrichment onto dedicated worker`
- `d2c6d268` - `feat: add embedding worker and semantic job retrieval`
- `dfcd3369` - `feat: add job recommendations and retrieval mode controls`

Integrated `main` state:

- merge commit: `7e36f014`
- current `main` head: `dfcd3369`
- local feature branch `feat/ai-ready-eventized` has been deleted
- isolated worktree `.worktrees/ai-ready-eventized` has been removed
- local feature branch `feat/task7-ingest-worker` has been deleted
- isolated worktree `.worktrees/task7-ingest-worker` has been removed

Current architecture status:

- Tasks 1 through 10 are now present on `main`
- the crawl-worker runtime has passed both unit/contract verification and live external smoke validation
- the ingest-worker runtime has passed both regression verification and live end-to-end persistence smoke validation
- the enrichment-worker runtime has now passed targeted regression coverage and a live worker-owned smoke validation
- embedding-worker and retrieval-api code paths are now present on `main`, with lexical-mode fallback preserved in `backend-api`
- recommendation endpoints and frontend retrieval-mode controls are now present on `main`, but dedicated recommendation runtime extraction remains open there
- the current local working tree adds a real `recommendation-api`, retrieval-backed non-lexical export, and durable-only progress aggregation
- the next execution target is no longer Task 11 implementation work; it is worker-profile real-data QA and then landing the current local follow-up, while Task 8 remains a hardening/cutover follow-up track

## Task 1 Status

### Completed

Task 1 is complete in worktree commit:

- `fb00b9c3`

### What Was Added

- `docker-compose.yml`
  - `postgres-db` image changed to `pgvector/pgvector:pg15`
  - worker-profile service stubs added for:
    - `scheduler-worker`
    - `crawl-worker`
    - `ingest-worker`
    - `enrichment-worker`
    - `embedding-worker`
    - `retrieval-api`
    - `recommendation-api`
- `backend/requirements.txt`
  - added:
    - `pgvector>=0.3.6`
    - `scrapy>=2.12.0`
    - `scrapy-playwright>=0.0.41`
- `backend/Dockerfile.worker`
- `backend/crawler/README.md`
- `backend/tests/test_config.py`

### Verification Performed

RED:

- `pytest backend/tests/test_config.py -q`
- initial result: `3 failed`

GREEN:

- `docker compose config`
- `pytest backend/tests/test_config.py -q`
- final result: `3 passed`

Regression checks:

- `pytest backend/tests/test_ai_overview_api.py backend/tests/test_api_taxonomy_compat.py -q`
- result: `12 passed`

### Notes

- `backend/Dockerfile.worker` currently uses a placeholder worker `CMD`. This was intentional for Task 1 scaffolding, but it is not a real runtime entrypoint and must be replaced in later worker tasks.
- `backend/requirements-dev.txt` was listed in the task scope, but no content change was needed for Task 1.

## Task 2 Status

### Completed

Task 2 is complete in worktree commit:

- `ff6cb50f`

### What Was Added

Models:

- `backend/app/models/crawl_job.py`
  - `CrawlJob`
  - `CrawlJobEvent`
- `backend/app/models/event_outbox.py`
  - `EventOutbox`
- `backend/app/models/job_embedding.py`
  - `JobEmbedding`

Modified models:

- `backend/app/models/__init__.py`
  - exports added for new models
- `backend/app/models/schedule.py`
  - `ScheduleExecution.crawl_job_id`
  - relationships linking schedule executions and crawl jobs

Repositories:

- `backend/app/repositories/crawl_job_repository.py`
- `backend/app/repositories/event_outbox_repository.py`
- `backend/app/repositories/job_embedding_repository.py`
- `backend/app/repositories/__init__.py`

Migration:

- `backend/alembic/versions/20260506_120000_add_event_backbone_and_pgvector.py`

Tests:

- `backend/tests/test_crawl_job_repository.py`
- `backend/tests/integration/test_job_embeddings_pgvector.py`

### Verification Performed

RED:

- `pytest backend/tests/test_crawl_job_repository.py backend/tests/integration/test_job_embeddings_pgvector.py -q`
- initial result:
  - import errors for missing `CrawlJob` and `JobEmbedding`

GREEN:

- `pytest backend/tests/test_crawl_job_repository.py -q`
- result: `3 passed`

- `DATABASE_URL=postgresql://admin:dev_password@localhost:5434/jobsdb pytest backend/tests/integration/test_job_embeddings_pgvector.py -q`
- result: `1 passed`

Regression checks:

- `pytest backend/tests/test_ai_overview_api.py backend/tests/test_api_taxonomy_compat.py -q`
- result: `12 passed`

### Follow-up Findings Status

The main Task 2 review findings were addressed in the later Task 4 follow-up window:

1. `JobEmbedding` now explicitly uses single-current-row semantics keyed by `job_id`.
   - repository upsert behavior and schema intent now match
   - fixed-dimension enforcement was added for the current single-model design

2. `CrawlJobEvent.sequence_no` is now protected by schema and repository logic.
   - `(crawl_job_id, sequence_no)` uniqueness was added
   - append logic now locks the parent crawl job row before computing the next sequence

3. `job_embeddings` now uses fixed `vector(384)` semantics.
   - ORM and follow-up migration now align on one global dimension
   - this matches the current single-model retrieval design used in the plan

### Alembic Caveat

The new Task 2 migration itself was added successfully, but a full `alembic upgrade head` on a brand-new empty database still fails before reaching the new revision because this repository does not yet have a full baseline migration chain for the pre-Alembic schema.

Observed failure pattern:

- earlier migration references tables such as `jobs` that do not exist in a brand-new empty database

This is a pre-existing repository condition, not a Task 2-only regression.

Follow-up action:

- keep using the repository’s documented bootstrap path for fresh databases
- do not treat `alembic upgrade head` from empty as a green signal until the baseline problem is separately solved

## Task 3 Status

### Completed

Task 3 is complete in worktree commit:

- `587450dd`

### What Was Added

Messaging package:

- `backend/app/messaging/__init__.py`
- `backend/app/messaging/topics.py`
- `backend/app/messaging/event_envelope.py`
- `backend/app/messaging/redis_stream_bus.py`
- `backend/app/messaging/outbox_publisher.py`

Modified support code:

- `backend/app/repositories/event_outbox_repository.py`
  - `mark_published(...)`
  - `mark_retryable_failure(...)`
- `backend/app/utils/redis_client.py`
  - injectable Redis client / URL support for Streams and tests
  - existing pub/sub and cache helpers retained

Tests:

- `backend/tests/test_redis_stream_bus.py`
- `backend/tests/test_outbox_publisher.py`

### Behavior Landed

- canonical Redis Streams topic registry:
  - `stream.crawl.commands`
  - `stream.crawl.progress`
  - `stream.job.ingest`
  - `stream.job.lifecycle`
  - `stream.job.embedding`
- stable event envelope with:
  - `event_id`
  - `event_type`
  - `aggregate_type`
  - `aggregate_id`
  - `source_service`
  - `occurred_at`
  - `schema_version`
  - `payload`
- Redis Streams bus methods for:
  - publish
  - consumer-group creation
  - group consumption
  - ack
- outbox publisher batch flow that:
  - reads pending rows from `event_outbox`
  - publishes to Redis Streams
  - marks rows published only after Redis success
  - records retryable failures with deterministic exponential backoff
- Task 3 currently uses explicit single-publisher, at-least-once semantics
- no new migration was added in Task 3
- existing in-memory progress store and SSE path were intentionally left untouched in this task

### Verification Performed

RED:

- `cd backend && REDIS_URL=redis://localhost:6379/15 pytest tests/test_redis_stream_bus.py tests/test_outbox_publisher.py -q`
- initial result:
  - `ModuleNotFoundError: No module named 'app.messaging'`

GREEN:

- `cd backend && REDIS_URL=redis://localhost:6379/15 pytest tests/test_redis_stream_bus.py tests/test_outbox_publisher.py -q`
- result: `5 passed`

Regression checks:

- `cd backend && REDIS_URL=redis://localhost:6379/15 pytest tests/test_crawl_job_repository.py tests/test_config.py tests/test_ai_overview_api.py tests/test_api_taxonomy_compat.py -q`
- result: `18 passed`

### Notes

- Task 3 is now committed and serves as the Redis Streams base for Task 4 and later worker tasks.
- Redis-backed Task 3 verification used the existing `redis-mq` runtime on `localhost:6379`, isolated to logical database `15`.
- Because Task 3 does not implement outbox row claim/lease semantics, later multi-publisher deployment should not assume concurrent-safe publishing yet.

## Task 4 Status

### Completed

Task 4 is complete in worktree commit:

- `d347dfdb`

### What Was Added

Control plane:

- `backend/app/api/crawl_jobs.py`
- `backend/app/schemas/crawl_job.py`
- `backend/app/services/crawl_job_dispatch_service.py`

Scheduler and runtime:

- `backend/app/services/scheduler_service.py`
- `backend/app/services/scheduler_runtime.py`
- `backend/app/workers/run_scheduler_worker.py`
- `backend/app/main.py`

Progress and recovery:

- `backend/app/api/progress.py`
- `backend/app/services/startup_recovery_service.py`
- `backend/app/services/progress_store.py`

Constraint and migration follow-up:

- `backend/app/models/crawl_job.py`
- `backend/app/models/job_embedding.py`
- `backend/app/repositories/crawl_job_repository.py`
- `backend/app/repositories/job_embedding_repository.py`
- `backend/app/repositories/schedule_repository.py`
- `backend/app/schemas/schedule.py`
- `backend/alembic/versions/20260506_150000_refine_crawl_job_constraints_and_embeddings.py`

Frontend cutover:

- `frontend/src/components/scraper/ScheduleManager.jsx`
- `frontend/src/components/scraper/ScrapeProgressPanel.jsx`
- `frontend/src/components/scraper/ScheduleManager.test.jsx`

Tests:

- `backend/tests/test_crawl_jobs_api.py`
- `backend/tests/test_scheduler_dispatcher.py`
- follow-up updates to:
  - `backend/tests/test_crawl_job_repository.py`
  - `backend/tests/test_startup_recovery_service.py`
  - `backend/tests/integration/test_job_embeddings_pgvector.py`

### Behavior Landed

- `POST /api/v1/crawl-jobs` now creates durable crawl jobs and outbox rows
- manual and scheduled crawl requests now queue work instead of invoking scraper services inline
- progress SSE now reads durable crawl-job state, with the existing in-memory store left as a transitional overlay
- startup recovery now marks interrupted crawl jobs as failed on restart
- the frontend direct-trigger flow now calls the crawl-job control plane instead of the legacy `run-now` execution path

### Verification Performed

GREEN:

- `pytest backend/tests/test_crawl_jobs_api.py backend/tests/test_scheduler_dispatcher.py backend/tests/test_crawl_job_repository.py backend/tests/test_startup_recovery_service.py backend/tests/integration/test_job_embeddings_pgvector.py -q`
- result: `14 passed`

- `pytest backend/tests/test_ai_overview_api.py -q`
- result: `1 passed`

- `npm test -- src/components/scraper/ScheduleManager.test.jsx src/components/scraper/ScrapeProgressPanel.test.jsx`
- result: `30 passed`

- `npm run build`
- result: success

### Notes

- Task 4 itself is committed at `d347dfdb`.
- Task 4 is now also present on `main` through merge commit `7e36f014`.

## Task 5 Status

### Completed and Merged

Task 5 is complete, committed in `fc95800a`, and merged into `main` via `7e36f014`.

### What Was Added

Shared source package:

- `backend/app/sources/__init__.py`
- `backend/app/sources/contracts.py`
- `backend/app/sources/jobsdb/__init__.py`
- `backend/app/sources/jobsdb/parsers.py`
- `backend/app/sources/ctgoodjobs/__init__.py`
- `backend/app/sources/ctgoodjobs/parsers.py`

Compatibility refactors:

- `backend/app/scraper/job_detail_scraper.py`
- `backend/app/scraper/ctgoodjobs/list_scraper.py`
- `backend/app/scraper/ctgoodjobs/detail_scraper.py`
- `backend/app/scraper/ctgoodjobs/__init__.py`

Tests and fixtures:

- `backend/tests/fixtures/jobsdb/search_response.json`
- `backend/tests/fixtures/jobsdb/detail_page.html`
- `backend/tests/fixtures/ctgoodjobs/category_page.html`
- `backend/tests/fixtures/ctgoodjobs/detail_page.html`
- `backend/tests/test_jobsdb_parsers.py`
- `backend/tests/test_ctgoodjobs_parsers.py`

### Behavior Landed

- parser logic now lives under `app/sources/.../parsers.py` instead of being owned only by the legacy scraper classes
- shared canonical contract helpers now live under `app/sources/contracts.py`
- existing JobsDB and CTgoodjobs scraper entrypoints now delegate to the new pure parser modules
- parser coverage is now fixture-backed and source-specific

### Verification Performed

GREEN:

- `pytest backend/tests/test_jobsdb_parsers.py backend/tests/test_ctgoodjobs_parsers.py -q`
- result: `4 passed`

- `pytest backend/tests/test_jobsdb_parsers.py backend/tests/test_ctgoodjobs_parsers.py backend/tests/test_crawl_job_repository.py backend/tests/test_crawl_jobs_api.py backend/tests/test_crawl_worker.py backend/tests/test_jobsdb_spider.py backend/tests/test_ctgoodjobs_spider.py -q`
- result: `15 passed`

### Notes

- Task 5 is functionally complete for the current parser extraction goal
- this work intentionally does not change scheduler or crawl control-plane APIs

## Task 6 Status

### Completed, Hardened, and Merged

Task 6 is complete, committed in `fc95800a`, and merged into `main` via `7e36f014`.

### What Was Added

Crawl worker runtime:

- `backend/app/workers/__init__.py`
- `backend/app/workers/run_crawl_worker.py`

Crawler package scaffolding:

- `backend/crawler/__init__.py`
- `backend/crawler/scrapy.cfg`
- `backend/crawler/job_crawler/__init__.py`
- `backend/crawler/job_crawler/items.py`
- `backend/crawler/job_crawler/settings.py`
- `backend/crawler/job_crawler/pipelines.py`
- `backend/crawler/job_crawler/middlewares.py`
- `backend/crawler/job_crawler/emitters/__init__.py`
- `backend/crawler/job_crawler/emitters/redis_stream_emitter.py`
- `backend/crawler/job_crawler/spiders/__init__.py`
- `backend/crawler/job_crawler/spiders/jobsdb_spider.py`
- `backend/crawler/job_crawler/spiders/ctgoodjobs_spider.py`

Contract support and runtime wiring:

- `backend/app/sources/contracts.py`
  - added canonical builder helpers for JobsDB and CTgoodjobs crawl output
- `docker-compose.yml`
  - `crawl-worker` now runs `python -m app.workers.run_crawl_worker`

Tests:

- `backend/tests/test_crawl_worker.py`
- `backend/tests/test_jobsdb_spider.py`
- `backend/tests/test_ctgoodjobs_spider.py`

### Behavior Landed

- a real `crawl-worker` runtime entrypoint now exists and consumes `stream.crawl.commands`
- `crawl.requested` messages are now routed by `source_site`
- worker-side lifecycle publishing now emits:
  - `crawl.started`
  - `crawl.page_processed`
  - `crawl.item_emitted`
  - `crawl.completed`
- canonical job payloads are now emitted onto `stream.job.ingest`
- crawl lifecycle is now durably projected back into:
  - `crawl_jobs`
  - `crawl_job_events`
- worker runtime now updates durable crawl state with:
  - `status`
  - `started_at`
  - `completed_at`
  - `error_message`
  - `metrics`
- default runner registry now includes both JobsDB and CTgoodjobs source runners
- the compose worker profile now has a real crawl-worker command instead of only inheriting the placeholder Dockerfile `CMD`

### Verification Performed

GREEN:

- `pytest backend/tests/test_crawl_worker.py backend/tests/test_jobsdb_spider.py backend/tests/test_ctgoodjobs_spider.py -q`
- result: `3 passed`

- `pytest backend/tests/test_jobsdb_parsers.py backend/tests/test_ctgoodjobs_parsers.py backend/tests/test_crawl_worker.py backend/tests/test_jobsdb_spider.py backend/tests/test_ctgoodjobs_spider.py -q`
- result: `7 passed`

- `pytest backend/tests/test_jobsdb_parsers.py backend/tests/test_ctgoodjobs_parsers.py backend/tests/test_crawl_job_repository.py backend/tests/test_crawl_jobs_api.py backend/tests/test_crawl_worker.py backend/tests/test_jobsdb_spider.py backend/tests/test_ctgoodjobs_spider.py -q`
- result: `15 passed`

- `docker compose config`
- result: success

- live end-to-end smoke run on 2026-05-06 against real external sources
- result:
  - JobsDB smoke completed with:
    - `pages_processed=1`
    - `items_emitted=32`
    - `job_ids_collected=32`
  - CTgoodjobs smoke completed with:
    - live category id `ctgoodjobs:001` fetched from the source registry at runtime
    - `pages_processed=1`
    - `items_emitted=32`
    - `job_ids_collected=32`
  - both runs durably recorded:
    - `crawl.requested`
    - `crawl.started`
    - `crawl.page_processed`
    - `crawl.completed`
  - both runs emitted canonical `stream.job.ingest` payloads successfully

### Notes

- Task 6 is now both unit/contract verified and live-smoke verified
- the current worker implementation now publishes stream-level lifecycle and ingest events and persists crawl lifecycle back into `crawl_jobs` / `crawl_job_events`
- the current `backend/crawler/` package provides runnable worker-side source runners and scaffolding, but this should still be treated as a worker-runtime bring-up rather than a full Scrapy-engine operational hardening program
- because CTgoodjobs runner support was also landed here, the original Task 8 scope should now be treated as hardening/cutover follow-up rather than initial runtime bring-up

## Task 7 Status

### Completed, Verified, and Merged

Task 7 is complete, committed in `09ab8887`, and is now present on `main`.

### What Was Added

New worker/runtime and identity support:

- `backend/app/workers/run_ingest_worker.py`
- `backend/app/services/source_identity_backfill_service.py`
- `backend/app/utils/source_identity.py`

Schema and migration updates:

- `backend/alembic/versions/20260506_210000_add_source_identity_and_ingest_outbox_fields.py`
- `backend/alembic/versions/20260506_120000_add_event_backbone_and_pgvector.py`
  - corrected `job_embeddings` initial vector shape so upgrade from `20260504_170000` can create the pgvector index path cleanly

Modified models and repositories:

- `backend/app/models/company.py`
- `backend/app/models/job.py`
- `backend/app/models/event_outbox.py`
- `backend/app/repositories/company_repository.py`
- `backend/app/repositories/job_repository.py`
- `backend/app/repositories/crawl_job_repository.py`
- `backend/app/repositories/event_outbox_repository.py`
- `backend/app/messaging/outbox_publisher.py`

Canonical payload and mapper compatibility:

- `backend/app/sources/contracts.py`
- `backend/app/utils/data_mapper.py`

Compose/runtime wiring:

- `docker-compose.yml`
  - `ingest-worker` now runs `python -m app.workers.run_ingest_worker`

Tests:

- `backend/tests/test_ingest_worker.py`
- `backend/tests/test_job_repository_upsert.py`
- `backend/tests/test_crawl_job_repository.py`
- `backend/tests/test_outbox_publisher.py`

### Behavior Landed

- a real `ingest-worker` runtime entrypoint now exists and consumes `stream.job.ingest`
- canonical crawl payloads are now durably upserted into `companies` and `jobs`
- ingest now preserves `raw_data`
- ingest upsert semantics are now idempotent for replayed or duplicate deliveries
  - create on first-seen source identity
  - update on changed payload
  - skip on no-op replay
- `job.ingested` is now emitted onto `stream.job.lifecycle`
- outbox-published lifecycle events now preserve logical producer identity through `source_service`
- `crawl_jobs.metrics` now merges worker-side metrics instead of clobbering prior keys
- ingest writes back:
  - `ingest_items_seen`
  - `ingest_jobs_created`
  - `ingest_jobs_updated`
  - `ingest_jobs_skipped`
- `jobs` now carry source-aware identity via:
  - `source_site`
  - `source_job_id`
- `companies` now carry source-aware identity via:
  - `source_site`
  - `source_company_id`
- backfill logic now upgrades existing mixed-source company/job data into source-owned identity
  - mixed-source company rows are split by source when needed
  - existing source-owned rows are reused when already present

### Verification Performed

GREEN:

- `pytest backend/tests/test_job_repository_upsert.py backend/tests/test_ingest_worker.py backend/tests/test_crawl_job_repository.py backend/tests/test_outbox_publisher.py -q`
- result: `12 passed`

- `pytest backend/tests/test_job_repository_upsert.py backend/tests/test_ingest_worker.py backend/tests/test_crawl_job_repository.py backend/tests/test_outbox_publisher.py backend/tests/test_redis_stream_bus.py backend/tests/test_crawl_worker.py backend/tests/test_jobsdb_spider.py backend/tests/test_ctgoodjobs_spider.py backend/tests/test_scheduler_dispatcher.py backend/tests/test_api_taxonomy_compat.py backend/tests/test_job_taxonomy_governance.py backend/tests/test_skill_history_governance.py backend/tests/test_startup_recovery_service.py backend/tests/test_batch_enrich_jobs.py backend/tests/test_ai_overview_api.py backend/tests/test_enrichment_run_service.py backend/tests/test_skill_governance.py -q`
- result: `119 passed`

- `DATABASE_URL=postgresql://admin:dev_password@localhost:5434/jobsdb alembic upgrade head`
- result:
  - upgraded a cloned pgvector-backed verification database from `20260504_170000` to `20260506_210000`
  - completed Task 7 backfill on real existing data
  - mixed-source companies reduced to `0`

- live end-to-end smoke run on 2026-05-06 against the temporary pgvector clone and isolated Redis DB `14`
- result:
  - JobsDB smoke completed with crawl job `c51a4643-af80-4459-a598-659c8bdbf0b5`
    - `pages_processed=1`
    - `items_emitted=32`
    - `job_ids_collected=32`
    - `ingest_items_seen=32`
    - `ingest_jobs_created=26`
    - `ingest_jobs_updated=6`
  - CTgoodjobs smoke completed with crawl job `92e3fc3b-65be-48ef-b226-abdaa151d28b`
    - `pages_processed=1`
    - `items_emitted=30`
    - `job_ids_collected=30`
    - `ingest_items_seen=30`
    - `ingest_jobs_created=27`
    - `ingest_jobs_updated=3`
  - Redis stream counts after smoke:
    - `stream.job.lifecycle=62`
    - `stream.job.ingest=62`
    - `stream.crawl.commands=2`
  - temp verification database totals after smoke:
    - `jobs=7361`
    - `companies=2262`

### Notes

- Task 7 is now both regression-verified and live-smoke verified
- the source-aware identity model is now explicit in code and migration state
- the verification path for Task 7 used a cloned pgvector-backed database because the long-running local project database was still at `20260504_170000` and should not be mutated in place during smoke work
- the eventized crawl -> ingest -> durable persistence chain is now proven for both JobsDB and CTgoodjobs
- the most important remaining gap on the critical path is no longer crawl or ingest bring-up; it is moving AI enrichment behind worker-owned event consumption

## Task 9 Status

### Completed

Task 9 is complete in `main` commit:

- `94c7b6af`

### What Was Added

- `backend/app/workers/run_enrichment_worker.py`
  - consumes `job.ingested`
  - consumes `crawl.completed` / `crawl.failed`
  - consumes `enrichment.run.requested`
  - owns startup AI-run recovery
- `backend/app/services/enrichment_run_service.py`
  - crawl-scoped auto-run aggregation keyed by `trigger_crawl_job_id`
  - durable run-request outbox emission
  - worker-side run claiming
  - `job.enriched` lifecycle emission
- `backend/app/api/ai.py`
  - manual AI APIs now create runs and dispatch work instead of executing inline
  - `POST /api/v1/ai/enrich-job/{job_id}` now routes through a worker-owned single-item run and returns run + refreshed job snapshot
- `backend/app/main.py`
  - API startup recovery no longer owns AI enrichment runs
- `backend/app/services/startup_recovery_service.py`
  - selective recovery switches added so AI-run recovery can move to the enrichment worker
- `backend/app/models/enrichment_run.py`
  - `trigger_crawl_job_id`
- `backend/alembic/versions/20260506_230000_add_trigger_crawl_job_id_to_enrichment_runs.py`
- `docker-compose.yml`
  - `enrichment-worker` now runs `python -m app.workers.run_enrichment_worker`

### Verification Performed

GREEN:

- `pytest backend/tests/test_enrichment_run_service.py backend/tests/test_enrichment_worker.py backend/tests/test_ai_enrichment_dispatch_api.py backend/tests/test_ai_overview_api.py backend/tests/test_ai_settings_api.py backend/tests/test_startup_recovery_service.py backend/tests/test_ingest_worker.py -q`
- result: `32 passed`

- live worker-owned smoke run on 2026-05-06 against the temporary pgvector clone and isolated Redis DB `13`
- result:
  - JobsDB smoke completed with crawl job `a9f3ccc7-49f4-40d4-afb5-d26993714d47`
    - `pages_processed=1`
    - `items_emitted=32`
    - `job_ids_collected=32`
    - `ingest_items_seen=32`
    - `ingest_jobs_created=1`
    - `ingest_jobs_updated=31`
  - crawl-scoped enrichment run `8443b7f3-2531-4c85-8c5d-66f82323a63c`
    - `status=completed`
    - `total_items=32`
    - `completed_items=32`
    - `failed_items=0`
  - Redis stream counts after smoke:
    - `stream.crawl.commands=1`
    - `stream.crawl.progress=3`
    - `stream.job.ingest=32`
    - `stream.job.lifecycle=65`

### Notes

- Task 9 is now both regression-verified and live-smoke verified
- worker-owned enrichment no longer depends on FastAPI background tasks
- automatic enrichment dispatch now waits for crawl terminal state plus ingest catch-up before starting the run
- the critical-path architecture gap after Task 7 is now closed; the next main-path gap is downstream embedding/retrieval enablement

## Task 10 Status

### Completed, Merged, and Runtime-Split

Task 10 is complete in feature-branch commit:

- `d2c6d268`

and merged into `main` via:

- `a537c61a`

### What Was Added

Embedding/retrieval runtime:

- `backend/app/workers/run_embedding_worker.py`
- `backend/app/services/embedding_document_builder.py`
- `backend/app/services/retrieval_service.py`
- `backend/app/services/retrieval_client.py`
- `backend/app/retrieval_main.py`
- `backend/app/api/retrieval.py`
- `backend/app/search/lexical_query.py`
- `backend/app/search/semantic_query.py`
- `backend/app/search/hybrid_ranker.py`

Runtime/image split:

- `backend/requirements-runtime.txt`
- `backend/requirements-ml.txt`
- `backend/Dockerfile.ml`
- `docker-compose.yml`
- `README.md`

Tests:

- `backend/tests/test_embedding_worker.py`
- `backend/tests/test_embedding_document_builder.py`
- `backend/tests/test_retrieval_service.py`
- `backend/tests/test_retrieval_api.py`
- `backend/tests/test_retrieval_client.py`
- `backend/tests/integration/test_job_embeddings_pgvector.py`
- `backend/tests/integration/test_semantic_search_api.py`

### Behavior Landed

- a real `embedding-worker` runtime now consumes `job.ingested` and `job.enriched`
- deterministic embedding documents are now built from current job state and re-embedded only when `document_hash` changes
- `job_embeddings` are now updated durably and emit `job.embedded`
- semantic and hybrid search now run behind the internal `retrieval-api` runtime
- `POST /api/v1/jobs/search` remains stable and now accepts `retrieval_mode`
- lexical mode remains the default and still works without ML dependencies in the default `backend-api` image

### Verification Performed

GREEN:

- `pytest -q backend/tests/test_retrieval_service.py backend/tests/test_retrieval_client.py backend/tests/test_retrieval_api.py backend/tests/integration/test_job_embeddings_pgvector.py backend/tests/integration/test_semantic_search_api.py`
- result: targeted retrieval / embedding coverage passed during Task 10 landing and 2026-05-07 recovery follow-up

- live runtime smoke was also preserved through the 2026-05-07 recovery path:
  - lexical search remains available from `backend-api`
  - semantic / hybrid paths are wired behind `retrieval-api`
  - embedding runtime dependencies are isolated behind `backend/requirements-ml.txt`

### Notes

- Task 10 is complete as an implementation slice
- the main remaining gap after Task 10 is no longer embedding/retrieval bring-up; it is recommendation/runtime completion and cutover cleanup
- semantic/hybrid container use still depends on explicitly running the worker-profile ML services

## Task 11 Status

### Baseline Slice Landed on `main`

Task 11 started on `main` in commit:

- `dfcd3369`

That landed the first user-facing slice:

- public recommendation endpoints in the control plane
- frontend retrieval-mode controls (`lexical`, `hybrid`, `semantic`)
- related-jobs rendering in `JobDetailModal`

### Local Follow-Up Completed in the Current Working Tree

Additional runtime split / export consistency work now present locally:

- `backend/app/api/internal_recommendations.py`
- `backend/app/recommendation_main.py`
- `backend/app/services/recommendation_client.py`
- `backend/app/schemas/recommendations.py`
- `backend/app/api/recommendations.py`
- `backend/app/config.py`
- `backend/app/api/jobs.py`
- `backend/app/api/retrieval.py`
- `backend/app/services/retrieval_client.py`
- `backend/app/services/retrieval_service.py`
- `docker-compose.yml`

Tests added or updated for this follow-up:

- `backend/tests/test_internal_recommendations_api.py`
- `backend/tests/test_recommendations_api.py`
- `backend/tests/test_retrieval_api.py`
- `backend/tests/test_retrieval_client.py`
- `backend/tests/test_config.py`

### Behavior Now Present Locally

- `GET /api/v1/jobs/{job_id}/similar` and `GET /api/v1/recommendations/jobs?job_id=...` now proxy through a dedicated internal `recommendation-api` runtime boundary instead of executing recommendation ranking directly in the public FastAPI control plane
- `recommendation-api` now has a real app entrypoint and health endpoint:
  - `uvicorn app.recommendation_main:app`
  - `GET /health`
- the internal recommendation service now exposes:
  - `GET /api/v1/internal/jobs/{job_id}/similar`
  - `GET /api/v1/internal/recommendations/jobs`
- `POST /api/v1/jobs/search/export` now mirrors `retrieval_mode`
  - `lexical` stays local
  - `semantic` / `hybrid` export now proxy through `retrieval-api`
- the original Task 11 ranking behavior remains the same:
  - semantic similarity from existing job embeddings
  - governed skill overlap
  - taxonomy-path prefix match
  - freshness bonus

### Verification Performed

GREEN:

- `python -m pytest tests/test_config.py tests/test_category_routes.py tests/test_retrieval_service.py tests/test_retrieval_api.py tests/test_retrieval_client.py tests/test_job_recommendation_service.py tests/test_recommendations_api.py tests/test_internal_recommendations_api.py tests/test_crawl_jobs_api.py tests/test_scheduler_dispatcher.py tests/test_startup_recovery_service.py -q`
- result: `30 passed`

- `npm test -- --run src/components/JobBrowser.test.jsx src/components/JobDetailModal.test.jsx src/components/scraper/ScrapeProgressPanel.test.jsx`
- result: `33 passed`

- `npm run build`
- result: success

### Notes

- Task 11 implementation is complete in the current local working tree
- this Task 11 follow-up is not yet committed or merged onto `main`
- worker-profile real-data QA is still outstanding before calling the runtime split operationally complete

## Task 12 Status

### Completed in the Current Working Tree

The cutover / cleanup slice is now implemented locally.

### What Was Changed

- `backend/app/api/category_routes.py`
  - removed legacy category-level scrape/status endpoints from the runtime path
- `backend/app/api/progress.py`
  - progress payloads are now derived only from durable `crawl_jobs` + `crawl_job_events`
- `backend/app/services/crawl_job_dispatch_service.py`
  - no longer seeds the transitional in-memory progress snapshot path
- removed:
  - `backend/app/services/progress_store.py`
  - `backend/app/services/category_scrape_service.py`
  - `backend/app/services/ctgoodjobs_scrape_service.py`
- updated tests:
  - `backend/tests/test_category_routes.py`
  - `backend/tests/test_crawl_jobs_api.py`
  - `backend/tests/test_scheduler_dispatcher.py`

### Behavior Now Present Locally

- the public runtime no longer exposes the old in-process category scrape execution path
- scrape progress is now sourced only from durable control-plane state and event history
- direct override / schedule-driven execution continues through `crawl_jobs`
- the frontend progress consumers still use the same public endpoints:
  - `GET /api/v1/scrape/progress`
  - `GET /api/v1/scrape/progress/stream`

### Verification Performed

GREEN:

- covered by the same targeted backend / frontend verification set listed in Task 11

### Notes

- Task 12 implementation is complete in the current local working tree
- this cleanup is not yet landed on `main`
- Task 8 remains separate follow-up work for CTgoodjobs hardening / cutover safety

## Temporary Runtime and Environment Notes

### Python Dependencies

To execute Task 2 work and tests, backend dependencies were installed in the active local Python environment so that:

- `pgvector`
- `scrapy`
- `scrapy-playwright`
- related backend/test dependencies

were available for execution.

### Temporary pgvector Database

For Task 2 integration verification, a temporary pgvector-enabled Postgres container was started on port `5434`:

- container name: `ai-ready-pgvector-test`
- port mapping: `5434 -> 5432`

Reason:

- the existing project container `postgres-db` is already in use on `5433`
- the temporary database allowed isolated `pgvector` integration testing without disturbing the main running stack

Task 7 reuse of this environment:

- the current local project database snapshot was dumped from `postgres-db`
- restored into `ai-ready-pgvector-test`
- then upgraded through:
  - `20260506_120000`
  - `20260506_150000`
  - `20260506_210000`
- then further upgraded through:
  - `20260506_230000`
- this made it possible to verify source-identity backfill and live crawl-worker -> ingest-worker persistence on realistic existing data without mutating the long-running local stack
- the same cloned database was then reused for the Task 9 worker-owned enrichment smoke

### Redis Runtime Used for Task 3 Verification

Task 3 verification used the existing Redis container already running for the project:

- container name: `redis-mq`
- host port: `6379`
- logical database used for tests: `15`

Reason:

- Task 3 specifically needed real Redis Streams behavior
- using a non-default logical database kept the verification isolated from the app's normal Redis usage

Task 7 live smoke used:

- the same `redis-mq` container
- logical database `14`

Reason:

- worker streams needed to be exercised end-to-end without contaminating the app's default Redis namespace

Task 9 live smoke used:

- the same `redis-mq` container
- logical database `13`

Reason:

- worker-owned enrichment needed to be exercised end-to-end without reusing Task 7 stream state

## Current Plan Progress

### Completed

- Task 1: Dependency and Container Foundation
- Task 2: Durable Event Backbone and pgvector Schema
- Task 3: Redis Streams Messaging Layer
- Task 4: Crawl Job Control Plane APIs and Progress Refactor
- Task 5: Shared Source Contracts and Parser Extraction
- Task 6: Crawl Worker Runtime and Multi-Source Canonical Emission
- Task 7: Ingest Worker and Durable Upsert Flow
- Task 10: Embedding Worker and Semantic Retrieval
- Task 9: Enrichment Worker Extraction

### Completed in the Current Local Working Tree

- Task 11: Recommendation Service and Frontend Search Modes
- Task 12: Cutover, Recovery, and Cleanup

### Remaining Follow-Up

- Task 8: CTgoodjobs Hardening / Cutover Follow-Up
- worker-profile real-data QA for:
  - semantic search
  - hybrid search
  - non-lexical export
  - related jobs recommendations
  - durable progress behavior

## 2026-05-07 Local Runtime Recovery Follow-Up

### Summary

On 2026-05-07 the local long-running development stack was recovered and re-validated after multiple runtime drift failures appeared in the browser:

- `backend-api` boot failures caused by missing `pgvector`
- `GET /api/v1/ai/overview` `500` due to schema drift around `enrichment_runs.trigger_crawl_job_id`
- `POST /api/v1/jobs/search` `500` due to `RetrievalService` eagerly loading `sentence-transformers` even when the request stayed in default lexical mode

This follow-up did not change the architecture plan itself, but it did restore the local stack to a usable state and fix one real code-level regression in the search path.

### What Was Changed

Frontend API base normalization:

- `frontend/src/components/Dashboard.jsx`
- `frontend/src/components/ai/AIEnrichmentPage.jsx`
- `frontend/src/components/scraper/ScheduleManager.jsx`
- `frontend/src/components/scraper/ScrapeProgressPanel.jsx`
- `frontend/src/components/charts/SkillChart.jsx`
- `frontend/src/components/charts/CategoryChart.jsx`

Those components now use the shared `API_BASE_URL` helper instead of reading `VITE_API_URL` inline, so local browser traffic is consistent with the Vite proxy path.

Backend search-path fix:

- `backend/app/services/retrieval_service.py`
  - query embedding model creation is now lazy
  - default lexical search no longer requires `sentence-transformers`
  - semantic / hybrid modes still load the embedding model when actually needed
- `backend/tests/test_retrieval_service.py`
  - added regression coverage proving lexical mode does not instantiate the embedding model
- `backend/tests/integration/test_job_embeddings_pgvector.py`
- `backend/tests/integration/test_semantic_search_api.py`
  - default local `DATABASE_URL` fallback now points to `localhost:5433` so integration tests align with the main Compose stack

Backend image reproducibility fix:

- `backend/requirements.txt`
  - removed `sentence-transformers` from the default API/runtime dependency set
- `backend/requirements-ml.txt`
  - added optional ML dependencies for semantic retrieval / embedding work
- `backend/Dockerfile.dev`
- `backend/Dockerfile.worker`
  - switched to the official Playwright Python base image
  - removed the unstable in-image Debian + browser bootstrap path from the default backend build

Developer documentation:

- `README.md`
  - added an explicit note that backend dependency changes require `docker compose up -d --build backend-api`

### Local Schema / Runtime Convergence Performed

The existing long-running local database was not at a clean Alembic head and could not be upgraded linearly in place because parts of the May 6 event-backbone schema had already been created manually while the Alembic version table still lagged behind.

For local recovery, the following convergence work was performed:

- recreated `postgres-db` on the checked-in `pgvector/pgvector:pg15` image
- confirmed the `vector` extension is available on the project database at `localhost:5433`
- bootstrapped missing ORM tables with:
  - `python backend/scripts/init_db.py`
- manually converged the missing runtime columns / foreign keys required by current code:
  - `enrichment_runs.trigger_crawl_job_id`
  - `schedule_executions.crawl_job_id`
  - the missing `schedule_executions` phase / metric columns expected by current models
- hot-installed `pgvector` into the running `backend-api` container so the active local container could import current models immediately

Important local note:

- the original hot-fixed `backend-api` recovery path on 2026-05-07 depended on an in-container `pip install pgvector`
- this caveat is now closed for the local dev API runtime
- after disk cleanup, Docker cache prune, Docker Desktop restart, and Dockerfile hardening, `backend-api` was rebuilt successfully from source and is now running from:
  - `sha256:8bab345c35b8824dd645a3162dd58911bb92054c615139b2917d0bb4b6d49380`

### Verification Performed on 2026-05-07

Backend tests:

- `pytest -q`
- latest result after the reproducible-image follow-up: `178 passed`

Targeted retrieval regression tests:

- `pytest -q backend/tests/test_retrieval_service.py backend/tests/integration/test_semantic_search_api.py backend/tests/integration/test_job_embeddings_pgvector.py`
- result: `8 passed`

Targeted frontend regression tests:

- `npm test -- src/components/Dashboard.test.jsx src/components/ai/AIEnrichmentPage.test.jsx src/components/scraper/ScheduleManager.test.jsx src/components/scraper/ScrapeProgressPanel.test.jsx src/components/charts/SkillChart.test.jsx src/components/charts/CategoryChart.test.jsx`
- result: `57 passed`

Live HTTP verification:

- `GET /health` -> `200`
- `GET /` -> `200`
- `GET /api/v1/ai/overview` -> `200`
- `GET /api/v1/ai/runs?monitor=true` -> `200`
- `GET /api/v1/schedules` -> `200`
- `GET /api/categories?source_site=jobsdb` -> `200`
- `GET /api/v1/settings/ai` -> `200`
- `GET /api/v1/companies/enrichment-runs/current` -> `200`
- `POST /api/v1/jobs/search` -> `200`

Post-rebuild image/runtime verification:

- `docker compose build backend-api`
- result: succeeded
- `docker compose up -d postgres-db redis-mq backend-api frontend-ui`
- result: all four core services returned to `healthy`
- `docker inspect backend-api --format '{{.Image}} {{.Config.Image}}'`
  - running backend image digest confirms the rebuilt image is active

### Remaining Runtime Caveat

The local stack is now reproducible for the current lexical-search / control-plane baseline. The remaining caveat has moved:

- semantic / hybrid retrieval and the embedding worker are no longer implicitly provisioned by the default backend image
- that dependency chain now lives behind `backend/requirements-ml.txt`
- enabling those paths in containers should be treated as part of Task 10 image/runtime design, not part of the default API baseline

## Recommended Next Step

Immediate operational next step:

- keep the current rebuilt `backend-api` image as the default lexical-search / crawler-control runtime baseline
- start the worker-profile runtimes required by the local follow-up:
  - `docker compose --profile workers up -d retrieval-api embedding-worker recommendation-api`
- verify that a realistic local dataset has enough populated `job_embeddings` rows to support:
  - semantic search
  - hybrid search
  - non-lexical export
  - related jobs recommendations
- run one direct-override crawl and confirm `/api/v1/scrape/progress` and `/api/v1/scrape/progress/stream` still reflect durable crawl-job state correctly

Architecture next step:

- if worker-profile QA is green, commit and land the current Task 11 / Task 12 follow-up slice
- then move the roadmap focus to Task 8 CTgoodjobs hardening / cutover follow-up

The most important thing not to lose is this:

- the event backbone now exists in code
- the control plane now durable-queues crawl requests through `crawl_jobs` + `event_outbox`
- crawl and ingest are both real worker runtimes now
- source-aware durable persistence is now proven live for both JobsDB and CTgoodjobs
- `job.ingested` now exists as a stable downstream contract
- `job.enriched` now exists as a stable downstream contract
- `job.embedded` now exists as a stable downstream contract

Task 11 and Task 12 are now implemented locally. The remaining execution focus is:

- run real-data QA on:
  - lexical search
  - semantic search
  - hybrid search
  - non-lexical export
  - related jobs ranking quality
  - durable progress behavior
- land the current local follow-up onto `main`
- then resume with Task 8 as a focused CTgoodjobs hardening / cutover follow-up rather than the main execution path
