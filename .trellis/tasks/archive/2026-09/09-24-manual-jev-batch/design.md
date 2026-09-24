# Design

Add an additive `jev_operation_batches` aggregate and
`jev_operation_batch_items` children. A batch freezes filter input, selected Job
IDs, operation set, runtime identities, force flag, and preview counters. Each
child owns one `(batch, job, operation)` lifecycle and references
the operation-specific durable result/run through JSON identifiers rather than
copying receipts.

`JevOperationBatchService.preview()` is a database-only planner. It normalizes
the request, selects Jobs deterministically, asks each operation adapter for an
eligibility state and input fingerprint, and returns a preview fingerprint.
`start()` repeats planning in the same transaction, rejects a stale preview
fingerprint, freezes rows, and returns an idempotent batch for the caller's key.

Dispatch is checkpointed item by item. The dispatcher locks the batch, checks
manual dispatch authority and stopping state before every item, marks one item
running, invokes the operation adapter, and commits its success/failure before
continuing. Skills runs before Related Jobs for the same Job; duplicate judging
is independent. A failed item never aborts later independent items.

The HTTP layer uses an explicit background task only after Start/Resume/Retry.
Startup recovery changes `running`/`stopping` batches and running items to
`stopped`; it never invokes the dispatcher. Stop only changes durable state.

The application has no local monetary admission control. `JevRunService`
dispatches an explicitly authorized bounded item directly to the configured
provider and records optional provider-reported usage/cost in the immutable
attempt receipt. Jev API Console is the only monetary quota authority. Missing
provider cost stays unknown; local token-rate estimation and reservation
fallbacks are forbidden.

Selection limits, typed-question bounds, concurrency, timeout, retry limits,
idempotency and lifecycle checks remain local operational safety controls.

Operation adapters initially wrap the current Skill and duplicate services and
the new Related Jobs service. The batch aggregate owns orchestration only; it
does not duplicate their evidence fingerprint, typed prompt, projection, or
result-read semantics.
