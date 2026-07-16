# Implementation plan: Manual crawl pacing and cancellation

## Rollout Order

1. Complete and verify reliable cancellation.
2. Add pacing persistence/API/controller and manual dispatch snapshots.
3. Add Settings UI and Direct Override summary.
4. Add Crawl Tasks pacing/cancellation projection and UI.
5. Run cross-child integration checks and migration verification.

Cancellation is the release prerequisite because configurable sleeps increase
the importance of an execution path that can really stop.

## Integration Checklist

- [ ] Implement children in the stated dependency order; keep each child
      independently testable and reviewable.
- [ ] Verify source names and defaults are defined by one backend contract, not
      copied independently across API, runtime, and UI.
- [ ] Verify request payload -> runtime controller -> Crawl Tasks snapshot -> UI
      round-trip for each source.
- [ ] Verify cancel request -> worker/process stop -> event projection -> UI
      lifecycle for queued, running, manual-action, and forced-stop cases.
- [ ] Restart the API/backend during a cancelling execution and verify recovery
      resumes supervision, validates execution identity, and never kills an
      unrelated reused PID.
- [ ] Verify late runtime writes cannot resurrect a cancelling/cancelled task.
- [ ] Verify a same-source second detail dispatch is rejected atomically while
      another source can start.
- [ ] Verify scheduled dispatch and listing request timing are unchanged.
- [ ] Run Alembic upgrade/downgrade against a representative existing database.
- [ ] Run focused backend tests identified in each child, then full backend
      tests.
- [ ] Run focused frontend tests, full frontend tests, and production build.
- [ ] Perform a bounded manual smoke for all three sources using small detail
      limits; do not deliberately trigger a block or automate verification.
- [ ] Review issue #10 only for follow-up schema findings; do not widen this
      implementation into a general schema cleanup.

## Review Gates

- Gate 1: cancellation tests prove `cancelled` means stopped.
- Gate 2: pacing contract/migration/runtime tests pass before UI is wired.
- Gate 3: Settings and Crawl Tasks show server-owned values and lifecycle.
- Gate 4: cross-source/manual-action regression suite and production build pass.

## Rollback Points

- Cancellation changes can be disabled at the API action boundary while keeping
  additive event/status readers compatible.
- Pacing resolution can fall back to compiled defaults if settings reads fail.
- UI sections/cards can be removed without deleting saved rows or historical
  task snapshots.
- Do not downgrade the database until deployed code no longer reads the new
  settings table or execution-ownership persistence chosen by the restart
  decision.
