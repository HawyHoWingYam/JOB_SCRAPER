# Implementation plan: Prevent hung OfferToday listing executions

1. Add failing OfferToday runtime tests using a page stub whose fetch/evaluate
   never resolves and a second stub whose response body never completes. Assert
   bounded abort, transient transport classification, and no false success.
2. Add the OfferToday request-timeout setting and validation. Implement an
   in-page `AbortController` deadline covering fetch and body consumption, then
   preserve redirect-race/IP/WAF and non-fetch-error behavior.
3. Add failing launcher tests with fake clocks/processes for fresh heartbeat,
   stale matching process, absent/mismatched process, access denied, concurrent
   terminal state, and cancellation-protected state.
4. Refactor the local process monitor from blocking `wait()` into a short polling
   watchdog. Reuse generation/PID/create-time/command validation and confirm
   process-tree exit before settlement.
5. Add one atomic stale-execution settlement path that marks execution terminal,
   emits `crawl.failed`, fails the Crawl Job, preserves listing output, and
   releases only unresolved detail rows owned by the run.
6. Add startup-recovery tests proving stale active executions are reconciled
   before `managed_job_ids` filtering, fresh executions remain protected, PID
   reuse is safe, and repeated startup recovery is idempotent.
7. Wire startup reconciliation through the existing API lifespan and retain
   current cancellation recovery ordering and semantics.
8. Update `.trellis/spec/backend/error-handling.md` and, if needed,
   `.trellis/spec/backend/offertoday-production-crawl.md` with the executable
   request-timeout and stale-heartbeat contracts.
9. Run focused tests, then lint/type/compile and the complete backend suite.
10. Deploy and verify Crawl Job
    `9204ca2d-a0e4-4039-bda5-c4b883c9200d`: terminal Crawl Job, terminal
    execution evidence, no later progress events, and exactly 3,101 preserved
    staged listing rows. Run one controlled stalled-request smoke and confirm it
    settles within request timeout plus watchdog grace.

## Validation Commands

```bash
cd backend
pytest -q tests/test_offertoday_quality.py tests/test_cross_source_ip_recovery.py
pytest -q tests/test_crawl_job_execution_launcher.py tests/test_startup_recovery_service.py
pytest -q tests/test_crawl_job_runtime.py tests/test_crawl_task_snapshot_service.py tests/test_crawl_control_api.py
ruff check app tests
python -m compileall -q app scripts
pytest -q
```

If the repository has no `test_startup_recovery_service.py`, create it and use
that exact focused target rather than hiding recovery coverage in an unrelated
suite.

## Risk And Rollback Points

- Browser timeout normalization must not swallow programming errors or erase
  settled verification URLs. Re-run IP/WAF redirect-race tests immediately after
  step 2.
- Process termination is the highest-risk boundary. Do not proceed past step 4
  unless wrong-command, wrong-generation, PID-reuse, and access-denied tests are
  green.
- Settlement must lock and re-read state so a concurrent Cancel cannot become
  Failed. Re-run cancellation launcher/API tests after step 5.
- If production watchdog behavior is unexpectedly aggressive, raise/disable the
  stale threshold through configuration while keeping the source request
  deadline deployed.

## Review Gate

Do not run `task.py start` or edit implementation files until the user reviews
and approves `prd.md`, `design.md`, and this plan.
