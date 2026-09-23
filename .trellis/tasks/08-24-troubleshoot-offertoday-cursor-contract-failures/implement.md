# Implementation plan: Prevent isolated crawl failures from aborting recoverable work

## Phase A: OfferToday listing boundary

1. Build a fast deterministic replay from both persisted failure sequences and
   assert page-45 success followed by page-46 cursorless empty failure.
2. Run one bounded production-policy probe to verify the Source window. Record
   evidence in the task; return to planning if the fixed boundary is falsified.
3. Add failing runner tests for the exact eligible boundary and negative tests
   for early absence, partial tuples, non-empty rows, page-size drift, session
   rollover, identity issues, and endpoint violations.
4. Add one OfferToday production-policy boundary constant and derive
   `source_collection_window` at the runner boundary while preserving primitive
   `incomplete_cursor` evidence.
5. Route the derived reason through existing partial-target continuation and
   final `partial_coverage` aggregation.
6. Add a three-target integration test: middle target hits the window, third
   target runs, valid output remains deduplicated, and the run is not complete.
7. Update OfferToday task projection and executable production-crawl spec.

## Phase B: CTgoodjobs location ownership and persistence isolation

8. Add a failing CTgoodjobs fixture with an ordered `jobLocations` value over
   255 characters. Reproduce the Company update failure and prove the Job value
   and raw evidence are complete before persistence.
9. Add tests proving CTgoodjobs Job location must not create or overwrite
   Company.location, including an existing Company with a different location.
10. Change the current-schema ORM definition of `jobs.location` to `TEXT` and
    add empty-bootstrap parity plus long-value round-trip coverage. Do not add
    a migration runtime; deployment uses the documented sandbox cutover.
11. Introduce or refine a CTgoodjobs-specific Company persistence mapper that
    omits Job location while retaining source company identity/name. Keep
    JobsDB mapping and behavior unchanged.
12. Add failure-classification tests for one deterministic invalid item followed
    by a successful item. Assert rollback, listing failure evidence, progress,
    and continuation.
13. Add hard-stop tests for database connection failure, invalid transaction or
    rollback failure, cancellation, manual action, unknown
    `DetailPersistenceError`, and programming errors.
14. Implement only the explicit item-scoped continuation path. Preserve
    fail-fast behavior for systemic/unknown persistence failures and safe error
    payloads without full oversized values.
15. Add a focused replay/integration test for source job `10221752`: successful
    Job publication with full location evidence, unchanged
    `AURELION LIMITED.location`, and later snapshot-item progress.
16. Update relevant backend ingest/error-handling specs with Job/Company
    location ownership and item/systemic failure boundaries.

## Phase C: Integrated verification

17. Verify operator projections separately describe OfferToday partial listing
    coverage and CTgoodjobs detail item failures; neither appears as a generic
    infrastructure failure when its run settles normally.
18. Review the final diff by Source boundary and verify there is no JobsDB
    behavior change.
19. Run focused tests, empty-schema bootstrap/parity checks, lint/type/compile
    gates, and the complete backend suite.
20. Perform controlled production verification: OfferToday later targets
    continue after the boundary, and CTgoodjobs `10221752` publishes without
    changing its Company's location or stranding later detail rows.

## Validation Commands

```bash
cd backend
pytest -q tests/test_listing_runtime.py
pytest -q tests/test_ctgoodjobs_headless_probe.py tests/test_cross_source_crawl_logging.py
pytest -q tests/test_crawl_job_runtime.py tests/test_crawl_task_snapshot_service.py tests/test_crawl_control_api.py
pytest -q tests/test_crawl_control_bootstrap.py
ruff check app scripts tests
python -m compileall -q app scripts
pytest -q
```

Run PostgreSQL bootstrap testing only against a disposable database whose name
ends in `_test`. Never alter the shared non-empty database in place.

## Risk And Rollback Gates

- Do not implement the OfferToday predicate if the evidence probe falsifies the
  fixed boundary.
- Do not broaden cursor acceptance; all negative cursor-contract tests must pass
  before partial continuation is wired.
- Do not silently truncate location data or overwrite Company facts with Job
  facts.
- Do not continue after an unclassified persistence error. The systemic
  hard-stop matrix must pass before enabling item continuation.
- Do not proceed past the schema step unless current metadata, empty-bootstrap
  parity, and long-value round trip behavior are verified.
- Do not modify JobsDB behavior. Any JobsDB-focused diff requires returning to
  planning and explicit scope approval.

## Review Gate

Do not run `task.py start`, execute a live mutating verification, or edit
implementation files until the user reviews and approves the revised PRD,
design, and implementation plan.
