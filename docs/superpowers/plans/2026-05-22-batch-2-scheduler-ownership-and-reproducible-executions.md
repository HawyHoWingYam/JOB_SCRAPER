# Batch 2: Scheduler Ownership And Reproducible Executions

## Goal

Make `scheduler-worker` the only cron dispatcher, keep `backend-api` on CRUD/manual dispatch/health duties, and make schedule runs reproducible through persisted request snapshots and worker heartbeat state.

## Delivered Changes

- `backend-api` no longer starts APScheduler in `backend/app/main.py`.
- `scheduler-worker` now runs `python -m app.workers.run_scheduler_worker` in `docker-compose.yml`.
- `backend/app/services/scheduler_service.py` reconciles APScheduler jobs from `scrape_schedules`, applies per-schedule timezone, and writes runtime heartbeat state.
- `schedule_executions.request_payload_snapshot` now matches the dispatched crawl job payload exactly.
- `/api/v1/capabilities` and `/health` now surface scheduler owner, heartbeat freshness, counts, and stale/missing reasons.
- `ScheduleManager` exposes scheduler-worker state while preserving manual actions during stale-worker conditions.
- `ScheduleHistory` now renders compact request snapshot metadata for each historical execution.

## Verification

- `python -m pytest backend/tests/test_scheduler_dispatcher.py backend/tests/test_capabilities_api.py backend/tests/test_health_api.py backend/tests/test_validate_audit_docs.py -q`
- `npm --prefix frontend test -- --run src/components/scraper/ScheduleManager.test.jsx src/components/scraper/ScheduleHistory.test.jsx`
- `npm --prefix frontend run build`
