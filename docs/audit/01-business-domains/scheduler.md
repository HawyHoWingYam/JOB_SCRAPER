# Business Domain: Scheduler

## Current Responsibilities

The scheduler domain stores recurring scrape configurations, starts runs manually or by cron, and links schedule executions to durable crawl jobs.

## Current Implementation Map

- API: `backend/app/api/schedules.py`
- Models: `backend/app/models/schedule.py`, `backend/app/models/crawl_job.py`
- Runtime: `backend/app/services/scheduler_runtime.py`, `backend/app/services/scheduler_service.py`
- Repository: `backend/app/repositories/schedule_repository.py`
- Frontend: `frontend/src/components/scraper/ScheduleManager.jsx`, `ScheduleForm.jsx`, `ScheduleList.jsx`

## Data and Control Flow

Schedules persist source site, crawl phase, crawl mode, category IDs, max pages, detail limit, and cron expression. API-created schedules are registered with scheduler runtime. Manual "run now" dispatches a crawl job and records schedule execution linkage.

## Tests and Coverage

- `backend/tests/test_scheduler_dispatcher.py`
- `backend/tests/test_startup_recovery_service.py`
- `frontend/src/components/scraper/ScheduleForm.test.jsx`
- `frontend/src/components/scraper/ScheduleManager.test.jsx`

## Known Gaps or Risks

- Schedule validation currently differs from direct crawl validation, especially for detail runs.
- The frontend stores source-specific category choices and has to reset state when source site changes.
- Runtime scheduler behavior depends on API process lifecycle, not a standalone scheduler service in Docker.
- `scheduler-worker` exists in the Compose topology, but cron ownership currently remains tied to API startup/runtime behavior.
- Schedule rows store timezone, while runtime assumptions are still centered on `Asia/Hong_Kong`.

## Optimization Backlog

- Decide one scheduler owner: either make `scheduler-worker` the cron dispatcher or remove the dormant service path to avoid split-brain operations.
- Centralize crawl request validation so direct override and scheduled runs share one schema for source, phase, mode, detail limits, and listing batch references.
- Apply persisted schedule timezones in runtime dispatch and add tests for non-default timezone schedules.
- Persist the exact crawl request payload on each schedule execution so historical runs remain reproducible after defaults change.

## Follow-up Audit Questions

- Should scheduler-worker become the single owner of cron dispatch instead of API lifespan?
- Should detail schedules support `source_listing_crawl_job_id`, or remain category-scoped only?
- Should schedule execution records include the full crawl request payload snapshot?
