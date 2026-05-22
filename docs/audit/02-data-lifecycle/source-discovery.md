# Data Lifecycle: Source Discovery

## Current Responsibilities

Source discovery establishes which source sites and categories can be crawled. It is the first boundary where JobsDB integer category IDs and CTgoodjobs string IDs diverge.

## Current Implementation Map

- Category API: `backend/app/api/category_routes.py`
- Registry service: `backend/app/services/source_category_registry.py`
- JobsDB categories: `backend/app/scraper/categories.py`
- CTgoodjobs registry: `backend/app/scraper/ctgoodjobs/category_registry.py`
- Frontend selectors: `frontend/src/components/scraper/ScheduleManager.jsx`, `ScheduleForm.jsx`

## Data and Control Flow

The frontend requests categories with `source_site`. JobsDB categories come from static local data. CTgoodjobs categories are refreshed from source HTML where possible, with stale cache and static fallback behavior.

## Tests and Coverage

- `backend/tests/test_source_category_registry.py`
- `backend/tests/test_ctgoodjobs_html_fetcher.py`
- `frontend/src/components/scraper/ScheduleManager.test.jsx`

## Known Gaps or Risks

- Source category refresh depends on remote site availability.
- JobsDB and CTgoodjobs use different category ID types, so validation must be source-aware.
- Source discovery is used by both schedule creation and direct override, but the frontend maintains separate form state.
- Schedule and crawl job schemas validate source/category choices in multiple places, increasing drift risk as sources add capabilities.
- CTgoodjobs registry fallback behavior is useful operationally but not yet visible enough to operators.

## Optimization Backlog

- Return category metadata such as `loaded_at`, `is_stale`, `fallback_used`, and `fallback_reason` so UI and health checks can distinguish fresh from fallback data.
- Centralize source/category validation across `schemas/schedule.py`, `schemas/crawl_job.py`, `api/schedules.py`, and `api/crawl_jobs.py`.
- Add a typed category identifier object or discriminated schema so JobsDB integer IDs and CTgoodjobs string IDs are validated at the boundary.
- Surface stale or fallback category state in schedule/direct-run forms before operators launch crawls.

## Follow-up Audit Questions

- Should category registry responses include freshness and fallback status?
- Should category IDs be wrapped in a typed object rather than raw `int | string`?
- Should the UI show unavailable or stale source category state explicitly?
