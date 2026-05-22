# Operator Perspective: Admin Operator Scheduler

## Current Responsibilities

This perspective covers creating automation, selecting source site and categories, running direct overrides, manually executing schedules, monitoring scheduler-worker ownership and heartbeat state, and reviewing schedule history with request snapshots.

## Current Implementation Map

- Frontend: `frontend/src/components/scraper/ScheduleManager.jsx`, `ScheduleForm.jsx`, `ScheduleList.jsx`, `ScheduleHistory.jsx`
- Backend: `backend/app/api/schedules.py`, `crawl_jobs.py`, `health.py`
- Runtime: `backend/app/services/scheduler_runtime.py`, `scheduler_service.py`

## Data and Control Flow

Operators choose source, crawl phase, mode, categories, and run parameters in `ScheduleManager`. The UI fetches `/api/v1/capabilities` and `/health` to surface scheduler-worker ownership, heartbeat freshness, and broader operator pipeline issues. `ScheduleList` displays `next_run_at` from the worker-reconciled schedule row.

When scheduler-worker is stale or missing, the UI keeps API-owned manual actions available and surfaces the worker state instead of pretending cron automation is healthy. Schedule history now shows compact `request_payload_snapshot` details so operators can see which source, phase, mode, categories or listing batch, detail limit, and crawl job ID were used for each historical run.

## Tests and Coverage

- `frontend/src/components/scraper/ScheduleManager.test.jsx`
- `frontend/src/components/scraper/ScheduleHistory.test.jsx`
- `backend/tests/test_scheduler_dispatcher.py`
- `backend/tests/test_capabilities_api.py`
- `backend/tests/test_health_api.py`

## Known Gaps or Risks

- Schedule creation and toggling can succeed while cron automation is paused, so operators still need the heartbeat banner to understand when changes will actually execute.
- Displayed `next_run_at` is only as fresh as the latest scheduler-worker reconcile.
- Schedule history is more reproducible now, but it still compresses request details into a compact snapshot instead of a fully linked run explorer.
- Operator health and capability state are read-only summaries; there is no UI action yet to restart or recover scheduler-worker.

## Optimization Backlog

- Add a dedicated operator view for scheduler-worker heartbeat history and reconcile drift over time.
- Link schedule history entries directly into crawl job event timelines for deeper troubleshooting.
- Add explicit UI guidance for schedule edits made while cron automation is paused.

## Follow-up Audit Questions

- Should direct override and scheduled run eventually share one unified operator form model?
- Should schedule history expose the raw JSON snapshot behind a compact summary toggle?
- Should operator recovery controls include scheduler-worker restart or reconcile triggers from the console?
