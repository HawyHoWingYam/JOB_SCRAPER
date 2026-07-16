# Implementation plan: Source-specific detail pacing runtime

1. Add model, repository/service, migration, defaults, uniqueness, and typed
   validation schemas.
2. Add settings API GET/PUT/reset tests, including independent writes and all
   safety boundaries.
3. Add typed `detail_pacing` contract to manual detail dispatch and task schema;
   preserve it on Resume.
4. Add transactional same-source active-detail exclusion and race tests.
5. Build the shared cancellation-aware pacing controller test-first.
6. Persist/restore cumulative attempt position without exposing UI counters.
7. Integrate JobsDB and CTGoodJobs detail loops.
8. Integrate OfferToday at its inner retry fetch boundary and prove no double
   retry/pause layer.
9. Project task snapshot value/null and run cross-source regression tests.
10. Verify listing/scheduled paths are untouched; run migration, focused/full
    backend tests.

## Validation Targets

- new pacing service/controller/API/migration tests
- dispatch service tests
- `backend/tests/test_crawl_job_runtime.py`
- `backend/tests/test_crawl_task_snapshot_service.py`
- `backend/tests/test_cross_source_crawl_logging.py`
- `backend/tests/test_cross_source_ip_recovery.py`
- OfferToday detail pipeline tests

## Rollback

Disable resolution at manual dispatch and use compiled defaults before removing
the table. Additive request-payload snapshots remain readable after rollback.
