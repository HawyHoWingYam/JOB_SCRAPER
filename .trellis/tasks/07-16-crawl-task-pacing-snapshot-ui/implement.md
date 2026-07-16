# Implementation plan: Crawl Task pacing and cancellation projection

1. Add explicit typed pacing/cancellation fields to Crawl Task API schemas.
2. Normalize request-payload snapshots and historical-null behavior in the
   snapshot service; include cancellation events/state.
3. Add `cancelling` filter/label/operator-state support.
4. Add compact Detail Pacing card with phase-aware and historical behavior.
5. Gate Cancel and Resume by lifecycle; represent accepted cancellation without
   claiming completion.
6. Add backend projection and frontend interaction/rendering tests.
7. Run full backend/frontend tests and production build.

## Validation Targets

- `backend/tests/test_crawl_task_snapshot_service.py`
- Crawl Jobs API/schema tests
- `frontend/src/components/scraper/CrawlTasksPage.test.jsx`

## Rollback

The UI card is additive and can be hidden. Keep schema readers tolerant of the
additive request-payload snapshot even if the projection is rolled back.
