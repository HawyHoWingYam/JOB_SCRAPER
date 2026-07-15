# Cross-source IP-block recovery and crawl-stage observability

## Goal

Make source crawl failures and progress understandable from backend logs without
opening the database or reconstructing execution from a generic exception. In
particular, surface OfferToday `code=-1000035` verification redirects as an IP
problem and provide consistent operational progress logs for Job ID/listing and
job-detail work across CTGoodJobs, JobsDB, and OfferToday.

## Background

- OfferToday crawl job `b6e9035d-31ad-447a-a7d6-1ef25dadc4bc` failed during
  session preflight with a generic Playwright `Page.evaluate: TypeError: Failed
  to fetch` and produced zero pages or listings.
- A live, read-only network probe reproduced the failure and showed that the
  page redirected from `/hk/search` to
  `/web/passport/cm/verify.html?...&code=-1000035&gateway=otd`. The page stated
  that the current IP had abnormal access behavior, while the listing request
  was aborted with `net::ERR_ABORTED` during navigation.
- The repository already has structured `SCRAPE_*` logging and crawl-job
  correlation conventions. This task extends that baseline rather than
  introducing a separate logging system.
- Current source inspection confirms that all three standalone executors emit
  lifecycle and completion-boundary logs, but important in-flight work remains
  silent:
  - CTGoodJobs emits page results only after fetch/parse/stage completes and
    detail results only after fetch/parse/persist completes
    (`backend/scripts/ctgoodjobs_standalone_crawl.py:233-305,373-503`).
  - JobsDB wraps a whole category scrape behind one category-start log and has
    no explicit empty-target terminal record
    (`backend/scripts/jobsdb_standalone_crawl.py:161-207,237-375`).
  - OfferToday detail work emits durable progress only every ten targets, so a
    slow target or early stop may be invisible between checkpoints
    (`backend/scripts/offertoday_standalone_crawl.py:1060-1122`).
- During planning, branch HEAD advanced from `426b588e` to pushed commit
  `10eabf5c`, which deleted the full current `backend/tests` tree plus most
  frontend tests (71 files, approximately 49,275 deleted lines). The user
  confirmed this deletion was intentional. This task must not restore the old
  suites; it may add a compact set of new production-path regression tests for
  the behavior introduced here.
- Existing cross-source recovery capabilities are uneven:
  - CTGoodJobs stages listing work per page and persists detail target status.
    A resumed listing may safely restart at page one and rely on staging
    deduplication, while detail resume already reloads pending/manual-action
    targets. Its current challenge errors do not distinguish IP block from
    generic human verification.
  - JobsDB persists completed detail targets, but its listing executor buffers
    all categories in memory and stages only after the full listing phase
    (`backend/scripts/jobsdb_standalone_crawl.py:161-207`). A listing IP block
    therefore requires an incremental staging/checkpoint boundary before
    same-task recovery can be truthful.
  - The shared dispatcher already resumes a crawl only from
    `manual_action_required`, reuses the original request/resume context, and
    restores detail statuses `manual_action_required,pending`
    (`backend/app/services/crawl_job_dispatch_service.py:315-381`).
  - Shared manual-action normalization accepts all three source names, but its
    classification messages are hard-coded to OfferToday
    (`backend/app/scraper/manual_action.py:29-68`). Crawl Tasks and Scrape
    Progress also render OfferToday-specific IP text
    (`frontend/src/components/scraper/CrawlTasksPage.jsx:223-230`,
    `frontend/src/components/scraper/ScrapeProgressPanel.jsx:1647-1649`).
- The current product recovery mechanism is an explicit Resume API/button.
  Frontend polling refreshes task state but no worker polls the source or
  resumes automatically after the public IP changes.

## Requirements

### R1. OfferToday IP-block classification

- Detect an OfferToday verification redirect carrying `code=-1000035`,
  including the case where navigation aborts an in-flight Playwright
  `window.fetch` before an API payload is returned.
- Classify the condition as `ip_blocked`, not as a generic transport/runtime
  failure and not merely as an unspecified WAF challenge.
- Preserve the blocked URL and an operator-facing message that clearly says the
  current public IP/network must be changed or cleared before retrying.
- Route the condition through the existing manual-action / crawl-task issue
  model so backend logs and task APIs expose the same classification.
- Do not automatically retry a confirmed IP block as if it were a transient
  network failure.

### R2. Cross-source crawl-stage logs

- CTGoodJobs, JobsDB, and OfferToday must emit useful, consistently named
  structured logs for both:
  - Job ID/listing discovery and staging.
  - Job-detail target resolution, fetching, parsing, and persistence.
- Each phase must expose, where applicable:
  - lifecycle start and completion;
  - source, crawl-job ID, crawl phase/mode, and relevant scope identifier;
  - planned/selected target counts;
  - bounded periodic progress with processed/succeeded/failed/skipped and saved
    counts;
  - retry, manual-action, and terminal-failure context;
  - a final summary even when the phase exits early or has no targets.
- Use the approved routine cadence:
  - listing/Job ID discovery logs one category/page start and one persisted page
    result; do not log every Job ID discovered inside a page;
  - detail logs one start and one result for every target, including
    `detail_index`, `detail_total`, `source_job_id`, elapsed time, outcome, and
    cumulative counters;
  - retry, failure, confirmed IP block, and manual action are logged
    immediately; and
  - phase start, empty-target/early-exit, and final summary are always logged.
- Source-specific semantics may remain source-specific (for example,
  OfferToday query tasks versus literal CTGoodJobs/JobsDB pages), but shared
  fields and event naming must be comparable in backend logs.

### R3. Operational safety and signal quality

- Logs must not expose cookies, auth headers, CSRF tokens, storage state, full
  job descriptions, or other sensitive payloads.
- Routine listing volume is bounded at page granularity. Detail volume is
  bounded to one start/result pair per selected target. Individual retries,
  failures, and manual actions may still be logged immediately with compact
  identifiers and error classes.
- Existing low-noise logging controls and request/crawl-job correlation must be
  preserved.

### R4. Compatibility

- Do not change crawl selection, pagination, retry, staging, or persistence
  results except where a persisted safe boundary is required for cross-source
  pause/resume. JobsDB may move listing persistence from phase-end buffering to
  atomic per-page staging, but the completed run must produce the same
  deduplicated Job ID set and source metadata.
- Existing task metrics/events and frontend consumers must remain compatible.

### R5. Cross-source IP-block pause and same-task recovery

- Apply one operator-facing IP-block contract to CTGoodJobs, JobsDB, and
  OfferToday during both Job ID/listing discovery and job-detail fetching.
- Classify a condition as `ip_blocked` only when source/browser/proxy evidence
  positively identifies an IP restriction. Do not relabel generic DNS,
  timeout, connection, parser, or authentication failures as IP problems.
- On confirmed IP block:
  - stop issuing later listing/detail requests promptly;
  - set the crawl job to `manual_action_required` rather than `failed`;
  - expose `classification=ip_blocked`, the affected phase/stage, blocked URL,
    source, crawl-job ID, and clear change-IP/network instructions in task APIs,
    UI issue text, durable events, and backend logs;
  - preserve already committed pages, staged Job IDs, completed details,
    counters, and the remaining target scope;
  - do not consume ordinary transient retry attempts once the IP block is
    confirmed.
- After the operator changes the public IP/network and resumes, redispatch the
  same crawl job and continue from a safe persisted boundary. Completed detail
  targets must not be fetched again, and listing continuation must not discard
  already committed Job IDs.
- Recovery is explicitly operator-driven: the crawl remains
  `manual_action_required` and issues no source requests until the operator has
  changed/cleared the network and clicks Resume for the same task. Background
  IP polling and automatic resume are not permitted.
- A listing-stage IP block is a hard stop for that execution and must not allow
  detail loading until listing is resumed and reaches its normal completion
  boundary.

## Acceptance Criteria

- [ ] A regression test reproduces an OfferToday redirect to
      `/web/passport/cm/verify.html?...code=-1000035...` during preflight and
      proves the result is `ip_blocked` with actionable blocked-URL/message
      metadata rather than raw `Page.evaluate` failure text.
- [ ] Confirmed OfferToday IP blocks do not consume normal transient retry
      attempts.
- [ ] Focused tests prove listing/Job ID and detail phases for all three sources
      emit lifecycle, progress, failure/manual-action, and completion summaries
      with crawl-job correlation and meaningful counters.
- [ ] Empty-target and early-failure paths still emit a terminal summary.
- [ ] Tests or explicit assertions prove sensitive request/session values are
      absent from the new log records.
- [ ] New focused backend/frontend tests, lint/type checks required by
      repository guidance, and a container/runtime smoke pass succeed.
- [ ] New compact regression coverage proves `ip_blocked` pause/projection and
      same-task resume behavior for all three sources in both listing and
      detail phases without restoring the deleted legacy test suites.
- [ ] For every source/phase combination, confirmed IP-block evidence stops
      later requests, preserves completed work, exposes actionable IP text, and
      resumes safely: detail does not repeat completed targets; listing may
      replay already committed pages but must upsert/deduplicate them, retain
      prior rows, and continue to the remaining pages.
- [ ] Generic transport/parser/auth failures remain distinct from IP blocks.

## Out of Scope

- Automatically changing the machine's public IP, solving OfferToday
  verification, or bypassing source anti-bot controls.
- Adding a new external telemetry platform, dashboard, or frontend monitoring
  redesign.
- Changing the crawl-task metric schema solely to support logging.
- Keeping a worker alive to poll blocked sources or automatically resuming a
  task after an IP/network change.
