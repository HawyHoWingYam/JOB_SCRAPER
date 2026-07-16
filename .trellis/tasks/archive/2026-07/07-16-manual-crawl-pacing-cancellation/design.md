# Design: Manual crawl pacing and cancellation

## Architecture

The feature has two control planes that meet at CrawlJob dispatch:

```text
Scraper Pacing Settings
  -> validated source row
  -> manual detail dispatch resolves effective values
  -> CrawlJob.request_payload.detail_pacing snapshot
  -> source-independent pacing controller
  -> source detail transport

Cancel action
  -> cancelling + crawl.cancel_requested
  -> cooperative worker checks / launcher supervision
  -> optional forced process-tree termination after 30 seconds
  -> cancelled + crawl.cancelled acknowledgement
```

Listing dispatch does not read pacing settings. Scheduled dispatch does not read
the new settings in this task.

## Data Contracts

### Saved configuration

Add a `scraper_pacing_settings` table with one row per supported source. The row
contains source identity, interval min/max seconds, burst size, burst pause
seconds, and normal audit timestamps. A uniqueness constraint owns the
one-row-per-source invariant.

Do not add scraper fields to AI-specific `app_runtime_settings`.

Typed GET/PUT API schemas own numeric validation and return the saved/effective
values. The backend remains authoritative even when the UI performs early
validation.

### CrawlJob snapshot

Manual detail dispatch adds this typed shape to `request_payload`:

```json
{
  "detail_pacing": {
    "interval_min_seconds": 1.0,
    "interval_max_seconds": 3.0,
    "burst_size": 20,
    "burst_pause_seconds": 30.0
  }
}
```

The snapshot is immutable for the task. Resume copies it unchanged. Mutable
attempt position belongs in CrawlJob runtime metrics/state, not in the config
snapshot. The snapshot projection exposes only the immutable parameters.

### Cancellation lifecycle

`CrawlJob.status` is already a string, so adding `cancelling` requires no status
column migration. The event taxonomy adds:

- `crawl.cancel_requested`: operator intent accepted; execution may still live.
- `crawl.cancelled`: execution stop acknowledged; task is terminal.

All repository/runtime transitions use row locking or guarded conditional
updates so cancellation wins over late worker writes. Repeated Cancel calls are
idempotent for `cancelling`/`cancelled`.

## Pacing Controller

Create one shared controller for all three detail workers. It owns:

- validated immutable parameters;
- cumulative outbound-attempt position loaded from persisted task runtime state;
- deterministic random and sleep dependencies for tests;
- cancellation-aware sleep sliced to no more than one second;
- a `before_attempt()` boundary that runs immediately before the actual
  transport call and persists the attempt position consistently.

The controller does not own retry policy. OfferToday retries call the same
controller before every actual fetch. JobsDB and CTGoodJobs continue their
current single-attempt behavior.

The per-source active-detail guard runs transactionally at manual detail
dispatch and considers queued, dispatching, running, manual-action-required,
and cancelling tasks active. A database query/lock, not a frontend-only check,
owns this invariant.

## Cancellation Execution Model

- Queued/manual-action tasks with no live worker can acknowledge cancellation
  immediately after proving no current execution generation exists.
- Running/dispatching tasks enter `cancelling`; a cooperative token reads the
  persisted status before each listing/detail request and during controlled
  sleeps.
- The current in-flight transport call may return and persist its truthful
  outcome. The next request gate sees cancellation and exits.
- The launcher must own an execution generation and process-tree handle. A
  30-second supervisor escalates from cooperative cancellation to process-tree
  termination and verifies exit before acknowledging `cancelled`.
- Worker completion/failure/manual-action paths detect cancellation and use the
  cancellation acknowledgement path instead of overwriting it.
- Any detail rows left `running` by forced termination are normalized back to an
  eligible state for a future task without erasing completed outcomes.

Persist execution identity in a dedicated `crawl_job_executions` record, with a
unique execution generation, CrawlJob identity, bounded process/process-group
identity, launch/heartbeat/stop/exit timestamps, and lifecycle state. Pass the
generation to the child process so both launcher and worker update the same
record. After backend restart, a recovery supervisor reconciles non-terminal
records, validates that the live process command/generation still belongs to the
CrawlJob, and then resumes cooperative waiting or force termination. PID alone
is never sufficient because it may have been reused.

## API and Projection

- Settings API: typed list/get plus source-specific PUT and reset-to-default
  semantics. Independent cards must not overwrite another source.
- Manual CrawlJob create: resolves settings server-side; clients cannot inject
  arbitrary pacing overrides in this scope.
- Crawl Tasks snapshot explicitly projects `detail_pacing` only for detail
  tasks with a stored snapshot; historical tasks return a null/not-recorded
  state.
- `cancelling` is added to status filters, labels, active counts, snapshot
  operator state, and progress event selection.
- Cancel API returns the accepted current state. The UI polls/refetches until
  terminal acknowledgement; it must not claim success while status is
  `cancelling`.

## UI Information Architecture

The existing Settings destination becomes a shell with two first-level
sections: AI Runtime and Scraper Pacing. Scraper Pacing uses three visually
parallel source cards, but each card has isolated form state and save/reset
actions. The page uses server responses to refresh saved state after writes.

Direct Override consumes a read-only source pacing summary and a Settings link.
It does not own pacing inputs.

Crawl Tasks places `Detail Pacing` near task facts/metrics, not in the Danger
Zone. Danger Zone owns permanent cancellation. During `cancelling`, controls
are disabled and the status is explicit; no countdown is rendered.

## Migration and Compatibility

- Migration creates and seeds the three settings rows with 1-3 / 20 / 30 and
  creates durable execution-generation ownership needed by cancellation.
- The service defensively resolves missing rows to the same defaults and records
  a bounded warning, so partial deployment does not break manual detail
  dispatch.
- Existing CrawlJobs remain readable. Their absence of `detail_pacing` is
  represented as `Not recorded`, not synthesized.
- Rollback removes the UI/API use first, then runtime resolution, then the new
  settings and execution-ownership tables.
  Existing request-payload snapshots remain harmless additive JSON.

## Verification Strategy

- Deterministic controller tests with fake random, clock/sleep, cancellation,
  and fetch functions.
- Dispatch transaction tests for snapshot immutability and same-source active
  task exclusion.
- State-machine tests for cancellation races, late worker transitions, queued
  cancellation, cooperative acknowledgement, timeout escalation, and repeated
  cancel calls.
- Cross-source worker tests prove one controller call per outbound attempt and
  preserve manual-action/terminal semantics.
- Snapshot/API tests prove explicit contracts and historical null behavior.
- Frontend interaction tests cover independent cards, ranges, dirty/save/reset,
  active warning/link, task detail display, and cancelling controls.
