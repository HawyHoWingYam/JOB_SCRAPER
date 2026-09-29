# Implementation plan: Repair Jev batch retry and failure propagation

## Implementation

1. Add focused failing tests for Skills outer retry proving that an old terminal
   provider failure produces a new underlying attempt while an answered current
   classification remains reusable.
2. Introduce the smallest operation-specific Skills retry seam in the runner,
   store, and/or backfill service; wire the outer batch's explicit retry intent
   through that seam without broad force reevaluation.
3. Add focused failing tests for duplicate no-work, success, partial failure,
   and total failure; make the outer item inspect the refreshed bounded-run
   terminal state before returning completed.
4. Add an idempotent, provider-free legacy duplicate reconciliation method and
   tests proving it touches only false-completed duplicate items in the selected
   batch.
5. Verify batch Stop/Resume/retry state transitions when stopped and failed work
   coexist. Preserve explicit manual authority and make any required state-
   machine correction with regression tests.
6. Update the Jev backend specification with the executable retry, propagation,
   reconciliation, and recovery contracts learned from this incident.

## Validation

- Run the focused Jev operation batch, online Skills, backfill, duplicate
  association, run service, and route tests.
- Run the relevant broader backend test group and the repository's backend
  lint/type/format checks discovered from package configuration.
- Run `git diff --check` and Trellis task validation.
- Confirm through fake provider assertions that reconciliation/deploy/startup
  cause zero provider calls and explicit retry causes the expected calls.

## Production recovery gate

1. Confirm batch `8dfa61d9-f055-4dc9-88d3-a27fd5d5171f` is still `stopped` with
   zero running items before deployment.
2. Restart the backend only after tests pass and recheck the stopped snapshot.
3. Execute provider-free duplicate reconciliation and record exact before/after
   counts.
4. Explicitly start failed-item recovery and verify fresh Skills provider
   attempts before allowing it to continue unattended.
5. Explicitly resume stopped work after the failed-work phase is understood;
   monitor history without issuing overlapping actions.

## Rollback points

- Before deployment: no production data change; keep the batch stopped.
- After reconciliation but before retry: outer duplicate statuses may be failed,
  but no receipts are deleted and no provider call has occurred.
- After explicit retry: Stop remains available and sticky; already committed
  successes are preserved.
