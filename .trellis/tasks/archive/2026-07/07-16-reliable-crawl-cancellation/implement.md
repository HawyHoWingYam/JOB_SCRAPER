# Implementation plan: Reliable manual crawl cancellation

1. Add cancellation states/events and guarded repository transitions with race
   tests.
2. Add durable `crawl_job_executions` generations to launcher dispatch and close
   the commit-to-Popen cancellation window.
3. Add shared cancellation token, cancellation-aware sleep, and acknowledgement
   service.
4. Integrate request gates into all three standalone listing/detail workers and
   their normal/manual-action/error exits.
5. Add the 30-second cooperative supervisor and process-tree termination adapter.
6. Add backend-startup reconciliation, execution identity verification, stale
   record handling, and PID-reuse safety tests.
7. Normalize only execution-owned in-progress detail rows and preserve listing
   partialness/completed data.
8. Project `cancelling` through task snapshot/API and update Cancel/Resume/status
   controls.
9. Run focused dispatch/runtime/snapshot/cross-source/frontend tests, then full
   backend/frontend suites and build.

## Validation Targets

- `backend/tests/test_crawl_job_runtime.py`
- new dispatch cancellation/state-machine tests
- `backend/tests/test_crawl_job_execution_launcher.py`
- `backend/tests/test_crawl_task_snapshot_service.py`
- `backend/tests/test_cross_source_crawl_logging.py`
- `backend/tests/test_cross_source_ip_recovery.py`
- `frontend/src/components/scraper/CrawlTasksPage.test.jsx`

## Rollback

Keep event/status readers additive. If process supervision proves unsafe, disable
new Cancel requests before reverting worker guards; worker guards are safe to
leave deployed because they only react to persisted cancellation state.
