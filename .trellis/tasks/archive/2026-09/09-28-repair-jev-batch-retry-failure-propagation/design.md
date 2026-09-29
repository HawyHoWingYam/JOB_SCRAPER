# Design: Repair Jev batch retry and failure propagation

## Boundaries

The outer durable operation batch remains the manual authorization and progress
authority. Each operation-specific service remains responsible for its product
record, while `JevRunService` remains responsible for bounded provider attempts.
The fix aligns those layers instead of adding another queue or automatic retry
mechanism.

## Skills retry contract

The outer batch execution path must distinguish an initial Skills execution from
an explicit retry of an already-failed outer item. On explicit retry, a terminal
`unavailable` or `invalid` classification for the same dispatch fingerprint must
be prepared for a genuine new attempt (or superseded by a new attempt generation)
through the Skills runner/store API. It must not be returned as a reusable
terminal result.

The operation-specific API owns this transition so callers do not mutate Skills
records directly. Answered/current classifications remain reusable. Receipt
history or generation lineage must retain the old failure. The batch-level
retry action remains the only authorization; no retry occurs during eligibility
inspection or reconciliation.

## Duplicate outcome contract

After `JevDuplicateAssociationService.execute` drains a bounded run, the caller
must refresh and inspect the run. `completed` is the only provider-success
terminal state. `completed_with_failures` becomes an outer failure with a stable
error code/message while candidate-level records already written by the service
remain committed. A plan with `run_id=None` is a successful no-work completion.

This is intentionally operation-level truth: partial candidate success is
durable, but the Job-level Possible same vacancy operation is not reported as
fully completed when any of its planned provider items failed.

## Legacy reconciliation

Add an idempotent service operation that examines completed duplicate batch
items with a referenced `jev_run_id`. When the referenced run is
`completed_with_failures`, change only the outer item to failed and attach a
secret-safe reconciliation error. Already failed items and genuinely successful
or no-work completed items are no-ops.

Reconciliation must be explicit and provider-free. It can be integrated into
the explicit failed-item retry preparation or exposed as a narrowly scoped
maintenance/service command, but must be testable independently. It must not
run at application startup.

Retrying the reconciled duplicate item creates a new duplicate plan for only
candidate pairs that do not already have a current successful association.
Existing candidate-level successes therefore remain skipped/current; failed
candidates receive new work.

## Stopped-batch recovery sequence

1. Keep the affected batch stopped while code is changed and tested.
2. Deploy/restart the backend; verify that startup recovery does not dispatch it.
3. Run provider-free legacy reconciliation and capture new counts.
4. Explicitly retry failed items. Confirm new Skills `jev_run_attempts` rows and
   truthful duplicate outer failures/successes.
5. When failed-item recovery reaches a safe terminal state, explicitly resume
   the remaining stopped items.
6. Monitor durable counters and sample Job Detail states. Never reset or delete
   the batch, receipts, classifications, associations, or successful items.

If retry and resume cannot coexist in one state transition without accidentally
finishing while stopped items remain, adjust the batch state machine so
`stopped` membership is preserved and the next explicit action is unambiguous.
Do not silently convert stopped work into pending during failed-only retry.

## Compatibility and rollback

- No provider schema or public request-shape change is required.
- Prefer no database migration; persisted JSON run references and existing
  status fields are sufficient. If an additional durable marker proves
  necessary, it requires an additive migration and explicit rollback notes.
- Code rollback leaves the batch stopped. Data reconciliation is monotonic from
  false completed to failed and is recoverable through explicit retry; it does
  not delete successful receipts.
- Do not expose upstream response bodies, credentials, or full evidence in
  errors, logs, issue text, or UI state.
