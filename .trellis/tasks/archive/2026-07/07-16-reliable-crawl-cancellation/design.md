# Design: Reliable manual crawl cancellation

## State Machine

```text
queued/dispatching/running/manual_action_required
  -- Cancel --> cancelling + crawl.cancel_requested
  -- stop acknowledged --> cancelled + crawl.cancelled
```

`completed`, `failed`, and `cancelled` are terminal. Repeated Cancel on
`cancelling` or `cancelled` returns current state without duplicate effects.

## Execution Ownership

The launcher creates a distinct execution generation and a killable process
tree. It must close the dispatch-before-Popen race by rechecking cancellation
immediately before launch and registering execution ownership atomically enough
that Cancel can find the right generation.

Persist each launch in `crawl_job_executions` using a unique generation passed to
the child process. Record CrawlJob identity, bounded PID/process-group identity,
launcher identity, lifecycle state, and launch/heartbeat/stop/exit timestamps.
An in-memory registry may accelerate normal control, but the database record is
the recovery authority. Startup reconciliation validates process command and
generation before resuming supervision or signalling; PID alone is never trusted.

## Cooperative Token

A shared cancellation token reads CrawlJob state through a bounded repository
operation. Source loops call it immediately before outbound navigation/fetch.
Cancellation-aware sleep divides long waits into at-most-one-second slices.

Worker exit acknowledges cancellation through one guarded repository operation.
Normal runtime transitions reject writes that would move a cancelling/cancelled
job back to an active or completed/error state.

## Cleanup

On cancellation acknowledgement, keep settled detail outcomes and normalize only
rows owned by the cancelled execution generation that remain `running`. Listing
metrics/events retain collected/staged counts while explicitly indicating that
the listing did not naturally complete.

## UI/API Projection

The Cancel endpoint accepts intent and may return `cancelling`. Crawl Tasks adds
the status to filters/labels and disables Cancel/Resume while shutdown is pending.
Only `cancelled` communicates that the crawler is gone.

## Tests

Use fake process handles and clocks for 30-second escalation; do not make unit
tests spawn uncontrolled OS processes. Add integration coverage for the real
launcher/process-tree adapter appropriate to Windows and deployed containers.
Add restart reconciliation and PID-reuse safety tests.
