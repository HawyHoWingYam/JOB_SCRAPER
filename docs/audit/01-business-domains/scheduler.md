# Business Domain: Scheduler

## Current Responsibilities

The scheduler domain stores recurring scrape configurations, keeps `scheduler-worker` as the single cron dispatcher, starts manual runs through API-owned endpoints, and links every scheduled execution to a durable crawl job plus an immutable request snapshot.

## Current Implementation Map

- API: `backend/app/api/schedules.py`, `backend/app/api/crawl_jobs.py`
- Models: `backend/app/models/schedule.py`, `backend/app/models/crawl_job.py`
- Runtime: `backend/app/services/scheduler_runtime.py`, `backend/app/services/scheduler_service.py`, `backend/app/workers/run_scheduler_worker.py`
- Repository: `backend/app/repositories/schedule_repository.py`
- Dispatch: `backend/app/services/crawl_job_dispatch_service.py`
- Frontend: `frontend/src/components/scraper/ScheduleManager.jsx`, `ScheduleForm.jsx`, `ScheduleList.jsx`, `ScheduleHistory.jsx`

## Data and Control Flow

Schedules persist source site, crawl phase, crawl mode, category IDs, max pages, detail limits, cron expression, timezone, and worker-computed `next_run_at` in `scrape_schedules`. Schedule create/update schemas validate IANA timezone identifiers before persistence. `scheduler-worker` periodically reconciles APScheduler jobs from that table, applying each schedule's persisted timezone with `CronTrigger.from_crontab(..., timezone=ZoneInfo(schedule.timezone))` and writing the authoritative next run time from APScheduler job state.

When a cron fire occurs, the worker dispatches a durable `crawl_jobs` row through `CrawlJobDispatchService`, creates a `schedule_executions` row, and stores `request_payload_snapshot` so the exact crawl request can be reconstructed later. Manual direct overrides and manual per-schedule execute actions stay API-owned and do not depend on scheduler-worker heartbeat freshness.

## Tests and Coverage

- `backend/tests/test_scheduler_dispatcher.py`
- `backend/tests/test_crawl_request_validation.py`
- `backend/tests/test_capabilities_api.py`
- `backend/tests/test_health_api.py`
- `frontend/src/components/scraper/ScheduleManager.test.jsx`
- `frontend/src/components/scraper/ScheduleHistory.test.jsx`

## Known Gaps or Risks

- Schedule CRUD now persists cleanly without touching in-process APScheduler, but cron changes only take effect after the next worker reconcile loop.
- `next_run_at` reflects the most recent successful scheduler-worker reconcile, so it can become stale when the worker is offline.
- `apscheduler_jobs` remains operational cache state rather than an operator-friendly audit surface.
- Schedule execution still carries legacy phase counters even though `crawl_jobs` and event streams now own most runtime detail.
- Schedule timezone identifiers are validated at the API schema boundary, but the database still stores them as unconstrained strings.

## Optimization Backlog

- Expose richer operator drill-down for heartbeat history instead of only the latest scheduler-worker snapshot.
- Add database-level timezone validation only if migration/runtime portability requirements justify a custom constraint strategy.
- Reduce duplicated legacy phase fields in `schedule_executions` once downstream operator views fully rely on crawl job events.

## Follow-up Audit Questions

- Should scheduler heartbeat history remain a singleton latest-row table, or grow into a time-series audit log?
- Which legacy execution counters can be removed once operator history is fully request-snapshot and crawl-job driven?
