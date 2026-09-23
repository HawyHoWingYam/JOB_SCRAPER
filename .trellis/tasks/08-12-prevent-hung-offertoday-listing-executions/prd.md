# Prevent hung OfferToday listing executions

## Goal

Ensure a stalled OfferToday browser request cannot leave a Crawl Job reporting
`running` indefinitely. Bound each browser-side API request, terminate locally
owned workers whose durable heartbeat becomes stale, and settle the Crawl Job
and execution records truthfully while preserving committed crawl output.

## Background

- Production Crawl Job `9204ca2d-a0e4-4039-bda5-c4b883c9200d` started at
  `2026-08-11T14:29:51Z` and remained `running` more than eight hours later.
- The consumed plan contained 156 Query Targets. The worker completed 83,
  reached target 84 (`offertoday:118000`, keyword `java`), and successfully
  recorded page 28 at `2026-08-11T15:43:24.334Z`.
- Its execution heartbeat advanced once more at
  `2026-08-11T15:43:24.418Z`, then both progress and heartbeat stopped. The
  execution retained `status=running`, no `exited_at`, and no `exit_code`.
- The browser transport awaits an unbounded page-context `fetch()` inside
  `page.evaluate()` at
  `backend/app/scraper/offertoday_browser_runtime.py:586-601`.
- The cancellation token updates the execution heartbeat immediately before
  outbound I/O at `backend/app/services/crawl_cancellation_token.py:50-69`.
  The observed 84 ms ordering is consistent with the next request entering the
  unbounded browser fetch and never returning.
- Startup recovery treats every execution row with an active status as managed,
  regardless of heartbeat age, and excludes its Crawl Job from interruption
  recovery at `backend/app/services/startup_recovery_service.py:233-250`.
- Existing execution ownership already persists generation, PID, process create
  time, command, launcher identity, heartbeat, stop, and exit evidence. Existing
  cancellation supervision validates generation/process identity and confirms
  process exit before terminal acknowledgement.

## Requirements

- R1. Add a configurable hard timeout to every browser-side OfferToday JSON
  request used by listing, detail, and session probes. The timeout must abort
  both response-header and response-body waits rather than merely timing out the
  Python await while leaving an in-page fetch alive.
- R2. Classify an aborted request through the existing OfferToday transient
  transport path so current bounded retry, WAF/IP detection, event evidence, and
  hard-stop rules remain authoritative. A timeout must not be reported as
  successful progress or natural exhaustion.
- R3. Add a configurable stale-heartbeat threshold and a short supervision
  interval for directly launched Crawl Job executions. The stale threshold must
  exceed the browser request timeout and normal cancellation-aware waits.
- R4. A launcher may terminate a stale worker only after validating PID,
  process create time, command, Crawl Job ID, and execution generation. PID-only
  signalling remains forbidden.
- R5. Once a stale worker is confirmed absent or terminated, atomically mark the
  execution terminal, record `crawl.failed`, set the Crawl Job to `failed`, and
  include a stable machine-readable reason plus operator-readable timeout
  message. Do not leave `running`, claim `completed`, or use `cancelled` without
  operator cancellation intent.
- R6. Preserve all committed events, staged listings, metrics, and completed
  detail outcomes. Release only unresolved detail rows owned by the failed run
  using the existing recovery boundary.
- R7. API startup must reconcile stale active execution rows before generic
  Crawl Job recovery excludes them. A stale row with no matching process must
  no longer shield its Crawl Job from recovery. A matching live process must be
  safely stopped before the job is declared terminal.
- R8. Process identity that is temporarily unverifiable must never be treated as
  proof of exit. Keep retrying supervision and emit actionable diagnostics; do
  not signal an unverified process.
- R9. The fix must apply to shared directly launched execution ownership while
  keeping the browser request timeout OfferToday-specific. JobsDB and CTGoodJobs
  request semantics are otherwise unchanged.
- R10. After deployment, operational verification must confirm Crawl Job
  `9204ca2d-a0e4-4039-bda5-c4b883c9200d` is no longer `running`, its execution
  has terminal evidence, and its 3,101 staged listings remain preserved.

## Acceptance Criteria

- [ ] A test browser fetch that never resolves aborts within the configured
      timeout and produces an OfferToday transient transport classification.
- [ ] Timeout covers a response body that never finishes, not only a fetch that
      never returns headers.
- [ ] Existing IP-block redirect-race, WAF, non-fetch Playwright error, retry,
      and cancellation-gate tests continue to pass.
- [ ] A locally launched process with fresh heartbeats is not terminated.
- [ ] A stale, identity-matching process is terminated as a process tree; only
      after confirmed exit are its execution and Crawl Job marked terminal.
- [ ] A stale execution whose process is absent or identity-mismatched is marked
      stale and its Crawl Job fails without signalling the unrelated PID.
- [ ] An access-denied/unverifiable process remains non-terminal and is retried
      with diagnostics rather than being falsely acknowledged as stopped.
- [ ] Startup recovery reconciles stale active executions before filtering
      managed Crawl Jobs and remains idempotent across repeated starts.
- [ ] Stale failure preserves listing events/metrics/staging and releases only
      unresolved detail ownership through existing recovery logic.
- [ ] Focused OfferToday transport, launcher, startup recovery, runtime, and
      snapshot/API tests pass, followed by backend lint/type/compile gates and
      the complete backend test suite.
- [ ] Production verification shows the exemplar task terminal with preserved
      output, and a synthetic stalled request cannot remain `running` beyond the
      configured timeout plus watchdog grace.

## Out Of Scope

- Changing the 156-target OfferToday adaptive coverage plan or keyword catalog.
- Reducing Page Depth or Run Page Cap to hide the hang.
- Automatically resuming a partially completed listing plan from target 84.
- Changing scheduled crawl cancellation policy or adding new user-facing task
  statuses.
