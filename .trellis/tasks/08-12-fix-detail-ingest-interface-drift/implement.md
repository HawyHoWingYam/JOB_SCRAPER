# Implementation plan

1. Load current backend specs and inspect the exact dirty versions of the
   runtime, cancellation service, JobsDB executor, CTGoodJobs executor, and
   focused tests before editing.
2. Add failing regression tests for the current ingest contract:
   - JobsDB and CTGoodJobs success paths require Company/Job upsert plus
     `project_source_attributes()` and do not provide the removed method;
   - supported projections remain inside the existing transaction boundary.
3. Add failing exception-boundary tests for both executors:
   - an unexpected persistence/programming exception records the current target
     once, aborts before the next target, and reaches terminal run settlement;
   - modeled unavailable, content anomaly, manual-action, and cancellation
     behavior remains unchanged.
4. Add a runtime failed-detail settlement operation that locks the Crawl Job,
   releases only owned still-running frozen rows through the existing
   cancellation recovery primitive, records terminal failure and recovery
   events atomically, and exposes the released count in the failure payload.
5. Remove both stale `project_company_industry()` calls and update test fakes to
   represent the current `IngestWorkerService` interface.
6. Reshape the JobsDB and CTGoodJobs detail exception boundaries so modeled
   target outcomes continue or pause, while unexpected persistence/programming
   failures roll back and escape to the outer detail failure settlement.
7. Preserve existing crawl query metadata during incremental detail-ingest
   classification observation, add a regression test for CTGoodJobs IT, and
   recover the affected row through validated catalog synchronization.
8. Run focused tests first, then backend formatting/lint/type/compile checks and
   the relevant regression suite. Review the diff against the heavily dirty
   worktree and avoid modifying unrelated Job Intelligence work.
9. Perform the Trellis quality check, update backend specs only if the failed-run
   settlement becomes a reusable contract, then present results before commit.

## Validation commands

- `pytest -q backend/tests/test_cross_source_crawl_logging.py -k 'jobsdb or ctgoodjobs'`
- `pytest -q backend/tests/test_crawl_job_runtime.py backend/tests/test_dispatch_plan_service.py -k 'detail or failed or release'`
- `pytest -q backend/tests/test_source_job_attribute_architecture.py backend/tests/test_source_job_attribute_ingest.py`
- `python3 -m compileall -q backend/app backend/scripts backend/tests`
- Run the repository-documented backend lint/type commands discovered by
  `trellis-before-dev`; do not invent or install new tooling.

## Risk and rollback points

- Risk: a broad fail-fast boundary could turn ordinary source data defects into
  run failures. Lock behavior with source-specific regression tests before
  changing the loop.
- Risk: failure and recovery events could commit separately. Keep Crawl Job
  failure, row release, metrics/payload, and recovery event in one transaction.
- Risk: shared tests contain stale fakes that make the old method appear valid.
  Delete that fake capability and assert the current call sequence.
- Risk: the worktree contains many unrelated uncommitted edits. Read every
  touched file immediately before patching and restrict changes to the symbols
  named in this plan.
- Rollback: revert the new runtime settlement and executor exception boundary;
  there is no database migration and released rows remain safely retryable.

## Start gate

- Re-read `prd.md`, `design.md`, and `implement.md` together.
- Confirm no unresolved product question remains.
- Obtain explicit user approval before running `task.py start` or editing
  implementation files.
