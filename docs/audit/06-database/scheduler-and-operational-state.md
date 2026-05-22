# Scheduler and Operational State

## Current Responsibilities

This scope stores scheduled scrape definitions, execution history, and APScheduler's persisted jobstore state. It bridges operator-created schedules with durable crawl jobs.

## Current Implementation Map

- Models: `backend/app/models/schedule.py`
- Services: `backend/app/services/scheduler_service.py`, `crawl_job_dispatch_service.py`
- API: `backend/app/api/schedules.py`
- APScheduler jobstore: `apscheduler_jobs`
- Tests: `backend/tests/test_scheduler_dispatcher.py`, `backend/tests/test_bootstrap_db.py`

## Tables and Column Use

| Table | Key columns | Column purpose |
| --- | --- | --- |
| `scrape_schedules` | `id`, `name`, `description` | Operator-visible schedule identity |
| `scrape_schedules` | `cron_expression`, `timezone`, `next_run_at`, `last_run_at` | Scheduling cadence and runtime timestamps |
| `scrape_schedules` | `source_site`, `crawl_phase`, `crawl_mode`, `detail_limit` | Source-aware crawl behavior and listing/detail mode |
| `scrape_schedules` | `category_ids`, `keywords`, `location`, `max_pages` | Scrape query parameters |
| `scrape_schedules` | `is_active`, `created_at`, `updated_at` | Activation and audit timestamps |
| `schedule_executions` | `schedule_id`, `crawl_job_id`, `status` | Execution record linked to schedule and dispatched crawl |
| `schedule_executions` | `started_at`, `completed_at`, `duration_seconds`, `error_message` | Execution timing and error reporting |
| `schedule_executions` | `jobs_scraped`, `jobs_saved`, `ids_collected`, `jobs_classified` | Crawl result counters |
| `schedule_executions` | `phase*_completed`, `phase*_duration` | Legacy/multi-phase progress audit |
| `apscheduler_jobs` | `id`, `next_run_time`, `job_state` | APScheduler SQLAlchemy jobstore internals |

## Data and Control Flow

1. Operator creates or edits `scrape_schedules` through schedule APIs.
2. Scheduler service validates supported `source_site` and source-specific category shape.
3. APScheduler registers jobs and persists scheduler internals to `apscheduler_jobs`.
4. When a schedule fires, the service creates `schedule_executions` and dispatches a `crawl_jobs` row.
5. Crawl progress updates the linked execution and crawl job status.
6. Schedule APIs expose current schedule state and recent execution history.

## Constraints and Indexes

- `schedule_executions.schedule_id` references `scrape_schedules(id)` with `ON DELETE CASCADE`.
- `schedule_executions.crawl_job_id` references `crawl_jobs(id)` with `ON DELETE SET NULL`.
- `crawl_jobs.schedule_id` references `scrape_schedules(id)` with `ON DELETE SET NULL`.
- Indexes exist on active schedule lookup fields such as `is_active`, `next_run_at`, `source_site`, execution `status`, and execution `started_at`.
- APScheduler indexes `next_run_time`.

## Current Database Snapshot

- `scrape_schedules`: 0 rows
- `schedule_executions`: 0 rows
- `apscheduler_jobs`: 0 rows

## Tests and Coverage

- Scheduler dispatcher tests cover schedule registration, dispatch, event creation, and CTgoodjobs validation.
- Bootstrap tests cover added schedule columns such as `crawl_mode`, `crawl_phase`, and `detail_limit`.

## Known Gaps or Risks

- APScheduler serializes `job_state` as `bytea`, so it is operationally opaque compared with first-party schedule rows.
- Schedule execution has legacy phase columns while newer crawl jobs and listing rows now own much of the runtime progress.
- `crawl_phase` and `crawl_mode` are strings without database-level checks.
- Current local DB has no schedules, so scheduler UI behavior depends on fixtures or operator setup.
- API startup currently owns scheduler runtime behavior even though a scheduler-worker service exists in deployment configuration.
- Schedule timezone is stored, but runtime dispatch has historically assumed `Asia/Hong_Kong`.

## Optimization Backlog

- Decide whether API or scheduler-worker owns cron dispatch, then make the other path a client or remove it.
- Apply per-schedule timezone consistently to next-run calculation and persisted execution timestamps.
- Store the full crawl request payload snapshot on `schedule_executions` for reproducibility and audit.
- Add database constraints or schema-level validation for `crawl_phase`, `crawl_mode`, and status fields.
- Treat crawl job events as the authoritative progress source and make schedule execution fields summary/cache fields.

## Follow-up Audit Questions

- Which progress fields are authoritative: `schedule_executions`, `crawl_jobs`, or `crawl_job_events`?
- Should APScheduler jobstore be treated as rebuildable cache rather than audit state?
- Should source-specific schedule validation be reflected in DB constraints?
- Should schedule changes have an audit trail of who changed what?
