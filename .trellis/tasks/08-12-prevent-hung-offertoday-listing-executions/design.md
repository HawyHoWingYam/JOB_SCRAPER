# Design: Prevent hung OfferToday listing executions

## Failure Model

The current worker heartbeats immediately before an outbound request. A
browser-context `fetch()` has no deadline, so one request can hold the only
worker coroutine forever. The launcher monitor blocks in `process.wait()` and
therefore detects exits but not a live, hung process. Startup recovery then
mistakes any active execution row for valid ownership without consulting its
heartbeat.

The fix uses two independent containment layers:

1. Bound the source request where the hang occurs.
2. Bound the worker execution when the source/request layer or event loop fails
   to make progress despite the request deadline.

## OfferToday Request Deadline

Add `offertoday_browser_request_timeout_ms` with a positive default of 60,000
ms. Keep it distinct from `offertoday_headed_navigation_timeout_ms`: navigation
controls `page.goto()`, while request timeout controls API `fetch()` and body
consumption inside `page.evaluate()`.

Pass the deadline into the evaluated function. Create an `AbortController`,
start a timer, attach its signal to the fetch options, await both `fetch()` and
`response.text()`, and clear the timer in `finally`. Normalize abort evidence to
`OfferTodayTransportError(error_kind="network")`; the existing response policy
then emits `transient_transport` and the existing retry policy decides whether
the operation retries or fails.

Do not wrap `page.evaluate()` only in `asyncio.wait_for()`: that could cancel the
Python await without proving the in-page request was aborted and could leave the
browser context with an active fetch.

## Execution Watchdog

Add shared settings for directly launched executions:

```text
crawl_execution_heartbeat_stale_seconds = 120
crawl_execution_watchdog_interval_seconds = 5
```

The stale threshold is deliberately greater than the 60-second request timeout.
The exact defaults should be covered by configuration validation and may be
raised operationally without code changes.

Replace the launcher's blocking exit-only monitor with a bounded polling loop.
Each pass checks process exit and reads the durable execution heartbeat. A fresh
heartbeat continues monitoring. A stale heartbeat enters the same safe process
identity validation used by cancellation:

```text
fresh heartbeat -> keep monitoring
stale + matching live process -> terminate process tree -> confirm exit
stale + absent/mismatched process -> do not signal PID; record execution stale
stale + access denied/unverifiable -> retain active state, log, retry
```

Only the launcher that holds the local process handle performs ordinary live
watchdog termination. Database state remains the authority for the final
transition and race guard.

## Terminal Settlement

Introduce one shared settlement operation rather than duplicating cancellation
or launch-failure code. Under row locks it must:

- re-read the execution and Crawl Job;
- no-op if execution/job already reached a terminal or cancellation-protected
  state;
- mark the execution `terminated` when the watchdog killed a matching process,
  or `stale` when no owned process exists;
- release unresolved detail rows using
  `CrawlJobCancellationService.release_running_detail_rows()`;
- record `crawl.failed` with an execution-generation, heartbeat age, threshold,
  reason code such as `execution_heartbeat_timeout`, and released-row count;
- set Crawl Job `failed`, `completed_at`, and an operator-readable error;
- commit execution/job/event/recovery changes atomically.

Committed listing rows and prior events are not rolled back. Runtime transition
guards must preserve a concurrent `cancelling`/`cancelled` state.

## Startup Reconciliation

Before `_recover_crawl_jobs()` constructs `managed_job_ids`, reconcile active
execution rows whose heartbeat is missing or older than the configured stale
threshold. Reuse generation-aware process validation; never trust a PID alone.

After reconciliation, only fresh active execution rows may shield Crawl Jobs
from generic restart recovery. This repairs deployments where the API process
restarted, lost its in-memory monitor, and left a dead child execution marked
`running`.

Startup reconciliation is idempotent: terminal executions and Crawl Jobs are
no-ops, and repeated runs cannot append duplicate terminal events.

## Compatibility And Operations

- No schema migration is required; existing execution states, timestamps, and
  Crawl Job events are sufficient.
- Existing cancellation state and 30-second force-stop behavior remain intact.
- JobsDB and CTGoodJobs retain their existing request implementations but gain
  the shared local-execution watchdog.
- Deployment startup should reconcile the production exemplar automatically.
  Verify its terminal state and preserved staged-row count after rollout.
- Rollback can disable the watchdog with a high threshold while retaining the
  OfferToday request timeout. Do not roll back durable terminal evidence already
  written for stale executions.

## Main Files

- `backend/app/config.py`
- `backend/app/scraper/offertoday_browser_runtime.py`
- `backend/app/services/crawl_job_execution_launcher.py`
- `backend/app/services/startup_recovery_service.py`
- `backend/app/repositories/crawl_job_execution_repository.py`
- `backend/tests/test_offertoday_quality.py`
- `backend/tests/test_cross_source_ip_recovery.py`
- `backend/tests/test_crawl_job_execution_launcher.py`
- new focused startup-recovery tests if no suitable test module exists
