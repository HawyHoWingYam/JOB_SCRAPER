# Operator Perspective: Admin Operator Scheduler

## Current Responsibilities

This perspective covers creating automation, selecting source site/categories, running direct overrides, selecting crawl phase/mode, and reviewing schedule history.

## Current Implementation Map

- Frontend: `frontend/src/components/scraper/ScheduleManager.jsx`, `ScheduleForm.jsx`, `ScheduleList.jsx`, `ScheduleHistory.jsx`
- Backend: `backend/app/api/schedules.py`, `crawl_jobs.py`
- Runtime: `backend/app/services/scheduler_runtime.py`, `scheduler_service.py`

## Data and Control Flow

Operators choose source, crawl phase, mode, categories, and run parameters. The UI calls schedules and crawl job APIs. Progress is shown through `ScrapeProgressPanel` and SSE-backed progress payloads.

## Tests and Coverage

- `frontend/src/components/scraper/ScheduleManager.test.jsx`
- `frontend/src/components/scraper/ScheduleForm.test.jsx`
- `backend/tests/test_scheduler_dispatcher.py`
- `backend/tests/test_crawl_jobs_api.py`

## Known Gaps or Risks

- Detail schedule and detail direct override validation need to remain aligned.
- Source switching clears category state and depends on operator confirmation.
- Operator health banner depends on health endpoint reachability.
- Scheduler ownership is ambiguous because API startup registers cron jobs while a scheduler worker service also exists.
- Stored schedule timezone is not yet fully reflected in runtime dispatch behavior.

## Optimization Backlog

- Choose a single scheduler owner and expose readiness/status for that owner in the operator UI.
- Share one frontend and backend request model between direct override and scheduled run creation.
- Fetch backend source defaults/capabilities for crawl phase, mode, headed support, and detail limits instead of hard-coding UI assumptions.
- Store and display schedule execution crawl payload snapshots with progress links for historical diagnosis.

## Follow-up Audit Questions

- Should direct override and scheduled run share one frontend form model?
- Should source-specific default mode/capability be fetched from backend?
- Should schedule history include crawl progress snapshots?
