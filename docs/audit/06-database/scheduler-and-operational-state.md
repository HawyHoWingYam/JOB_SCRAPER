# Scheduler and Operational State

## Current Responsibilities

This scope stores schedule definitions, execution history, scheduler-worker heartbeat state, and APScheduler's persisted jobstore cache. It bridges operator-created schedules with durable crawl jobs while keeping cron ownership outside `backend-api`.

## Current Implementation Map

- Models: `backend/app/models/schedule.py`
- Services: `backend/app/services/scheduler_service.py`, `scheduler_runtime.py`, `crawl_job_dispatch_service.py`
- API: `backend/app/api/schedules.py`, `backend/app/api/health.py`
- Runtime worker: `backend/app/workers/run_scheduler_worker.py`
- APScheduler jobstore: `apscheduler_jobs`
- Tests: `backend/tests/test_scheduler_dispatcher.py`, `backend/tests/test_capabilities_api.py`, `backend/tests/test_health_api.py`

## Tables and Column Use

| Table | Key columns | Column purpose |
| --- | --- | --- |
| `scrape_schedules` | `id`, `name`, `description` | Operator-visible schedule identity |
| `scrape_schedules` | `cron_expression`, `timezone`, `next_run_at`, `last_run_at` | Scheduling cadence, per-schedule timezone, and runtime timestamps |
| `scrape_schedules` | `source_site`, `crawl_phase`, `crawl_mode`, `detail_limit` | Source-aware crawl behavior and listing/detail mode |
| `scrape_schedules` | `category_ids`, `keywords`, `location`, `max_pages` | Scrape query parameters |
| `scrape_schedules` | `is_active`, `created_at`, `updated_at` | Activation and audit timestamps |
| `schedule_executions` | `schedule_id`, `crawl_job_id`, `status` | Execution record linked to schedule and dispatched crawl |
| `schedule_executions` | `started_at`, `completed_at`, `duration_seconds`, `error_message` | Execution timing and error reporting |
| `schedule_executions` | `request_payload_snapshot` | Exact crawl request payload used for that historical execution |
| `schedule_executions` | `jobs_scraped`, `jobs_saved`, `ids_collected`, `jobs_classified` | Crawl result counters |
| `schedule_executions` | `phase*_completed`, `phase*_duration` | Legacy/multi-phase progress audit |
| `scheduler_runtime_heartbeats` | `owner`, `worker_name`, `status`, `last_heartbeat_at` | Latest scheduler-worker ownership and heartbeat state |
| `scheduler_runtime_heartbeats` | `started_at`, `active_schedule_count`, `registered_job_count`, `last_reconcile_at`, `last_error` | Reconcile/runtime observability for cron dispatch |
| `apscheduler_jobs` | `id`, `next_run_time`, `job_state` | APScheduler SQLAlchemy jobstore cache internals |

## Data and Control Flow

1. Operators create or edit `scrape_schedules` through schedule APIs.
2. Schedule create/update schemas validate IANA timezone identifiers before storing them as `scrape_schedules.timezone`.
3. `scheduler-worker` periodically reconciles APScheduler jobs from active `scrape_schedules` rows, treating APScheduler as rebuildable cache rather than canonical state.
4. Each active schedule is registered with `CronTrigger.from_crontab(..., timezone=ZoneInfo(schedule.timezone))`.
5. Scheduler-worker persists each registered job's `next_run_time` back to `scrape_schedules.next_run_at`, and clears stale values when a schedule is no longer registered.
6. Scheduler-worker writes its current ownership and freshness snapshot into `scheduler_runtime_heartbeats`.
7. When a schedule fires, the worker creates `schedule_executions`, dispatches a `crawl_jobs` row, emits `crawl.requested`, and stores the exact `request_payload_snapshot` that matched the crawl job payload.
8. `/health` and `/api/v1/capabilities` read the latest heartbeat row to tell operators whether cron automation is actually alive.

## Tests and Coverage

- Scheduler dispatcher tests cover reconcile registration, update/removal, persisted `next_run_at`, cron dispatch, manual API execution, CTgoodjobs validation, timezone application, and request payload snapshots.
- Crawl request validation tests cover schedule create/update rejection for invalid timezone identifiers.
- Capability and health tests cover missing, fresh, and stale scheduler-worker heartbeat reporting.
- Compose smoke coverage asserts `scheduler-worker` uses `python -m app.workers.run_scheduler_worker`.

## Known Gaps or Risks

- APScheduler serializes `job_state` as `bytea`, so the jobstore remains operationally opaque compared with first-party schedule and heartbeat rows.
- `schedule_executions` still duplicates some progress fields that overlap with crawl job events.
- `crawl_phase`, `crawl_mode`, schedule status fields, and timezone strings are still guarded mostly by application/schema logic rather than database constraints.
- `next_run_at` is a latest reconcile snapshot, not an append-only schedule timing audit.

## Optimization Backlog

- Add database-level timezone validation only if portability requirements justify a custom constraint strategy.
- Consider a heartbeat history table if operators need more than the latest scheduler-worker snapshot.
- Reduce legacy execution progress columns once operator reporting fully depends on crawl job events and snapshots.

## Follow-up Audit Questions

- Should APScheduler jobstore remain a pure cache, or should any of its fields be mirrored into first-party tables for easier operator reporting?
- Should `scheduler_runtime_heartbeats` stay singleton latest-state storage, or gain historical rows for audits?
- Which `schedule_executions` progress fields can be dropped once crawl job events become the only source of truth?
- Should source-specific schedule validation be reflected in database constraints?
