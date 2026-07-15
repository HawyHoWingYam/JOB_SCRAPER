# Verification

## Result

All task acceptance criteria passed. GitHub issue:
https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/7

## Red / Green evidence

- Before the service fix, the new regression failed with
  `snapshot["manual_action"] is None` while the latest stored manual-action
  event was resumable.
- After the fix, `backend/tests/test_crawl_task_snapshot_service.py` passes
  7/7, including later-event ordering, stale-action suppression, and
  source-correct browser defaults.

## Commands

- `python -m pytest tests/test_crawl_task_snapshot_service.py tests/test_cross_source_ip_recovery.py tests/test_cross_source_crawl_logging.py -q`
  - Passed: 42 tests.
- `python -m pytest tests -q`
  - Passed: 52 tests.
- `python -m ruff check app/services/crawl_task_snapshot_service.py tests/test_crawl_task_snapshot_service.py`
  - Passed.
- `python -m compileall -q app/services/crawl_task_snapshot_service.py tests/test_crawl_task_snapshot_service.py`
  - Passed.
- `npm test -- --run src/components/scraper/CrawlTasksPage.test.jsx`
  - Passed: 7 tests.
- `npm test`
  - Passed: 13 files, 114 tests.
- `npm run build`
  - Passed: 1,798 modules transformed.
- `git diff --check`
  - Passed.

## Known repository baseline

- `npm run lint` remains red with 16 errors and 3 warnings in existing,
  task-unmodified frontend files. No lint finding points to this task's backend
  changes.
- A bare `pytest` from `backend/` incorrectly collects the live browser profile
  and `tmp_stress_test.py`; the maintained `pytest tests` suite is green.

## Live read-only verification

- `/api/v1/crawl-jobs/tasks?page_size=100` returns a non-null manual action for
  task `88ff0eb8-5c27-4a24-bf61-0a917727a67a`, with both resume capability flags
  true and the OfferToday Edge profile preserved.
- Browser smoke shows `Resume Task with Open Browser` and
  `Resume with Fresh Profile`, replacing the unsupported operator-review state.
- No recovery, browser-open, cancel, or other task-mutating action was invoked.

## Spec update

- `.trellis/spec/backend/error-handling.md` now records event-kind selection,
  stale-action suppression, source-correct browser defaults, and required
  regression coverage for Crawl Tasks recovery projection.
