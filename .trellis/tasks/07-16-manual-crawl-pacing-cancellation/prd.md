# Stabilize manual crawl detail pacing and cancellation

## Goal

Make manually triggered JobsDB, CTGoodJobs, and OfferToday crawls safer to
operate by giving Job Detail work a configurable, source-specific request pace
and by making cancellation mean that the crawler has actually stopped.

## Background

- Job-ID/listing discovery has workload and freshness requirements that differ
  from Job Detail collection. This task intentionally leaves listing pacing
  unchanged.
- IP blocks, verification pages, and operator recovery are observed more often
  during detail collection. Slower, predictable detail traffic is preferred
  over maximum throughput.
- Current cancellation changes the CrawlJob status to `cancelled` immediately,
  but the launched subprocess is not retained or terminated and workers do not
  poll for cancellation. A later worker update can overwrite the cancelled
  status.
- The three current standalone detail workers already process targets serially.
  This project preserves that single-in-flight model.
- Scheduled crawling is rarely used and will be reassessed separately in
  GitHub issue #11. It is not part of this task.

## Scope and Child Deliverables

1. `07-16-reliable-crawl-cancellation`: reliable, permanent cancellation for
   manual listing and detail CrawlJobs.
2. `07-16-detail-pacing-runtime`: persistence, API contracts, task snapshots,
   and runtime pacing for manual detail CrawlJobs.
3. `07-16-scraper-pacing-settings-ui`: Settings information architecture and
   source-specific pacing editors.
4. `07-16-crawl-task-pacing-snapshot-ui`: cancellation lifecycle controls and
   effective pacing display in Crawl Tasks.

The parent owns cross-child acceptance and rollout order. Each dependency is
also stated in the child artifacts.

## Requirements

### R1. Detail-only pacing

- Apply pacing only to manually triggered `crawl_phase=detail` tasks.
- Do not change Job-ID/listing request speed.
- Do not apply this feature to scheduled crawls.
- Preserve one in-flight detail network request per task.
- Permit different sources to run concurrently, but allow at most one active
  detail task for the same source.

### R2. Independent global source settings

- JobsDB, CTGoodJobs, and OfferToday each have an independent saved global
  configuration.
- Default each source to a random interval of 1-3 seconds, a burst size of 20
  outbound detail attempts, and a 30-second burst pause.
- Valid ranges are:
  - interval minimum and maximum: 0.1-60 seconds;
  - minimum must be less than or equal to maximum;
  - the two interval values cannot both be zero;
  - burst size: integer 1-1000;
  - burst pause: 0-3600 seconds.
- Enforce the contract in both frontend and backend, and show ranges and units
  next to the controls.

### R3. Stable task semantics

- Resolve and snapshot effective pacing into the CrawlJob request payload when
  a manual detail task is dispatched.
- Global setting edits affect only newly created tasks; they never hot-update a
  running or paused task.
- Manual-action Resume preserves the original pacing snapshot and cumulative
  detail-attempt position.
- Seed existing installations with one default settings row per source.
- Historical tasks without a snapshot display `Not recorded`; never infer their
  pacing from current global settings.

### R4. Attempt pacing rules

- The first outbound detail attempt starts immediately.
- Before each later attempt, wait a random duration within the task snapshot's
  interval.
- Count every actual outbound detail attempt, including success, failure,
  terminal-unavailable responses, and each retry.
- Do not count listing, browser warmup, session checks, or manual-verification
  navigation.
- After each complete burst, use the burst pause instead of the ordinary random
  interval when more detail work remains.
- Do not add a final pause when no work remains.
- Existing OfferToday retry backoff must not create an accidental second outer
  retry loop; retries still participate in the shared attempt sequence.

### R5. Reliable permanent cancellation

- Cancellation covers both manual listing/Job-ID and manual detail tasks.
- Cancel is available for non-terminal queued, dispatching, running, and
  manual-action-required tasks. It is disabled while already cancelling and is
  unavailable for terminal tasks.
- Cancellation is permanent. A cancelled task cannot Resume.
- Preserve already committed/staged work. Listing output remains truthfully
  partial/incomplete, and unprocessed detail targets remain eligible for a new
  task.
- Use `cancelling` plus `crawl.cancel_requested` while shutdown is pending.
- Use `cancelled` plus `crawl.cancelled` only after the execution is confirmed
  stopped.
- During pacing or other controlled sleeps, observe cancellation at least once
  per second. An in-flight request may finish, but no new request may start
  after cancellation is observed.
- Give cooperative shutdown 30 seconds, then force-terminate the crawler process
  tree. Do not mark `cancelled` until termination is confirmed.
- Persist execution-generation ownership so the 30-second escalation and
  stop-confirmation guarantee survives an API/backend process restart. Recovery
  must verify process identity before signalling it; a reused PID must never be
  terminated as if it belonged to the CrawlJob.
- Runtime transitions must not overwrite `cancelling` or `cancelled` with a
  later started/completed/failed/manual-action status.

### R6. Operator-facing UI

- Reorganize Settings into clear `AI Runtime` and `Scraper Pacing` sections.
- Scraper Pacing shows one independent card per source. Each card saves and
  resets independently and exposes saved/dirty/saving/error feedback.
- Saving while detail tasks are active is allowed, with a warning that changes
  apply only to new tasks. Show the active detail-task count and an Open Crawl
  Tasks link.
- Direct Override shows only a read-only pacing summary/link, not duplicate
  editable controls.
- A detail task's Task Details view shows a compact `Detail Pacing` card with
  random interval, burst size, and burst pause from the startup snapshot.
- Do not show a countdown, live wait state, attempt counter, or pacing runtime
  counters.

## Acceptance Criteria

- [ ] AC1: Manual listing behavior and scheduled crawls are unchanged by pacing.
- [ ] AC2: Each source can save, validate, reset, and independently resolve its
      detail pacing settings using the agreed defaults and safety ranges.
- [ ] AC3: A newly dispatched detail task persists an immutable effective
      pacing snapshot; settings edits do not change it, and manual-action Resume
      retains its snapshot and attempt position.
- [ ] AC4: Detail requests remain serial and follow the first-immediate,
      ordinary-interval, burst-replacement, retry-counting, and no-final-pause
      rules under deterministic tests.
- [ ] AC5: A second active detail task for the same source is rejected with a
      clear API/UI message; other sources may run concurrently.
- [ ] AC6: Cancel transitions through `cancelling`, prevents further outbound
      requests, stops the execution cooperatively or by 30-second forced process
      termination, and emits `cancelled` only after stop acknowledgement.
- [ ] AC7: Cancellation preserves committed work, leaves listing truthfully
      partial, leaves unprocessed detail rows eligible, and cannot be resumed.
- [ ] AC8: Settings and Crawl Tasks render the approved information hierarchy,
      safety ranges, task snapshot, and cancellation controls without countdown
      or runtime pacing counters.
- [ ] AC9: Historical detail tasks display `Not recorded` and never borrow the
      current settings.
- [ ] AC10: Backend focused/full tests, frontend tests, production build, and
      migration upgrade/downgrade checks pass before rollout.

## Out of Scope

- Scheduled crawl pacing, lifecycle, or UI redesign.
- Changing listing/Job-ID pacing.
- Automated CAPTCHA or verification solving.
- Source-specific retry-policy redesign beyond integrating existing retries
  into the attempt sequence.
- A broad cleanup of unrelated schemas; that audit is tracked in issue #10.
