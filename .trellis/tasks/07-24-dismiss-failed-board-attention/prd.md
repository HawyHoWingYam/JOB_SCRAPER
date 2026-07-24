# Dismiss terminal failed runs from Task Control Board attention

## Goal

Let an operator permanently dismiss a specific terminal crawl failure from the
Task Control Board `Needs attention` section without deleting the crawl task,
changing its failed status, or hiding any later failure.

## User value

Resolved or obsolete failures no longer keep a Source in attention forever,
while Task Details and Logs retain the complete operational record.

## Confirmed facts

- Board V2 currently projects every run whose normalized status is `failed` as
  a `failed_run` attention item with only Task and Logs actions.
- Crawl jobs already have an append-only event stream with a per-job sequence
  and row-locked event append operation.
- The current historical CTGoodJobs failure predates the repaired headless
  profile/catalog rollout and is safe for the operator to dismiss.
- The frontend already owns generic Board mutations, busy/error feedback, and
  post-mutation refresh behavior.

## Requirements

- R1. Every supported Source (`jobsdb`, `ctgoodjobs`, `offertoday`) exposes a
  `Dismiss` action only for a terminal `failed_run` attention item.
- R2. Dismiss acts immediately with no confirmation, Undo, Restore, or Task
  Details duplicate action.
- R3. Dismiss removes only the targeted failure from Board `Needs attention`.
  The crawl job remains `failed` and remains visible in Crawl Tasks, Task
  Details, Events, and Logs.
- R4. Dismiss is bound to the exact current `crawl.failed` event sequence. A
  later Resume/new failure must appear as new attention.
- R5. The mutation is idempotent for the same job/failure sequence. A request
  targeting an obsolete sequence or a job no longer in terminal failed state
  fails with a structured conflict and cannot hide newer state.
- R6. `manual_action_required`, `cancelling`, queued/running, completed, and
  cancelled runs never expose or accept Dismiss.
- R7. The Board refreshes after a successful Dismiss. Mutation failure remains
  visible through the existing Board error surface.
- R8. Dismissal is durable across API/container restarts and records actor and
  target failure sequence in append-only history.
- R9. The implementation must not special-case the historical CTGoodJobs run;
  that run is dismissed through the same public contract.

## Acceptance criteria

- [x] A failed Board card renders Task, Logs, and Dismiss; other attention/active
      kinds do not render Dismiss.
- [x] Dismissing a failed card immediately removes it and updates the Source
      attention count without changing the crawl job status or task/event reads.
- [x] Repeating the same dismissal succeeds without appending duplicate state.
- [x] A stale failure sequence, a later failure, or a non-failed job is rejected
      and remains correctly projected.
- [x] A newly failed attempt after Resume appears even if the previous failure
      was dismissed.
- [x] Backend contract/API/projection tests and frontend interaction/error tests
      cover the behavior for the source-neutral path.
- [x] The current historical CTGoodJobs failed card can be dismissed via the new
      UI action and disappears from Board attention.

## Out of scope

- Hard-deleting crawl jobs, events, logs, staged data, or browser profiles.
- Dismissing manual-action, cancelling, active, catalog, worker, or automation
  attention items.
- A dismissed-items archive, confirmation dialog, Undo, Restore, or bulk action.
- Automatically expiring or dismissing failures.
