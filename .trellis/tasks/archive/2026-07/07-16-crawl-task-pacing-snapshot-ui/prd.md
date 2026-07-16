# Show effective pacing in Crawl Tasks

## Goal

Make each manual detail CrawlJob explain the pacing parameters it actually
adopted and make cancellation status/actions truthful.

## Requirements

- Add an explicit typed `detail_pacing` task-snapshot projection sourced only
  from the CrawlJob startup snapshot.
- For detail tasks with a snapshot, show a compact `Detail Pacing` card containing
  random interval, burst size, and burst pause.
- Historical detail tasks without a snapshot show `Not recorded`; listing tasks
  do not show a pacing card.
- Do not show countdowns, wait state, attempt counts, or pacing runtime counters.
- Add `cancelling` to status labels, filters, active-state projection, and event
  context.
- Cancel is available only for queued, dispatching, running, and
  manual-action-required tasks. It is disabled while cancelling and absent or
  disabled for terminal states.
- Resume is available only when the backend lifecycle supports it; cancelled or
  cancelling tasks cannot Resume.
- After Cancel is accepted, show pending cancellation and refresh until
  `cancelled`; do not claim the crawler stopped while `cancelling`.

## Acceptance Criteria

- [x] Snapshot API returns the typed pacing object, explicit historical-null
      behavior, and `cancelling` lifecycle consistently.
- [x] Detail Pacing card renders only the three approved parameters with correct
      units and historical wording.
- [x] Cancel/Resume/status/filter behavior matches backend lifecycle for all
      terminal and non-terminal states.
- [x] No countdown or pacing runtime counter appears.
- [x] Backend snapshot tests, frontend Crawl Tasks tests, full frontend tests,
      and production build pass.

## Dependencies

- Depends on reliable cancellation states/events and the pacing request-payload
  snapshot contract.
- Can be implemented after backend projections exist; it does not block Settings
  API/runtime work.
