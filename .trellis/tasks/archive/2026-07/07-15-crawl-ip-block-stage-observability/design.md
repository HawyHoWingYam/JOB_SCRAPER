# Cross-source IP-block recovery and crawl-stage observability design

## Summary

This task keeps the existing crawl-job/manual-action architecture and makes two
connected changes:

1. Normalize positively identified IP restrictions from CTGoodJobs, JobsDB,
   and OfferToday into one source-aware `ip_blocked` manual-action contract for
   listing and detail phases.
2. Fill the operational logging gaps inside the same source executors so an
   operator can see the current page or detail target, its result, elapsed time,
   and terminal reason from backend logs.

The work remains one Trellis task rather than a parent with children because
both deliverables modify the same source adapters, standalone executors,
manual-action payload, task projection, and focused regression tests. Splitting
them would create overlapping edits and duplicate integration gates.

## Design invariants

- Only positive source/browser evidence becomes `ip_blocked`. DNS failures,
  timeouts, parser failures, authentication expiry, and generic human
  verification retain their existing classifications.
- A confirmed IP block stops the current execution immediately and persists
  `manual_action_required`; it is never consumed as a normal transient retry.
- Recovery is explicit. No worker remains alive and no source is polled while
  waiting. The operator changes network/IP and clicks Resume for the same crawl
  job.
- Already committed listing rows and completed details remain durable. Resume
  may repeat an idempotent page request, but it must not create a duplicate
  `(crawl_job_id, source_site, source_job_id)` row or refetch a completed detail
  target.
- Logs are operational output, not a second durable event store. Existing
  `CrawlJobEvent` and metrics cadence remains bounded unless a task/status
  contract requires an event.
- No cookie, token, auth header, CSRF value, storage state, full response body,
  or job description is logged.
- The intentionally deleted legacy test suites remain deleted. This task adds
  only compact production-path regression coverage.

## Current-state gap matrix

| Source / phase | Current safe boundary | Current gap |
|---|---|---|
| OfferToday preflight/listing | Cursor-aware listing runner and page staging already stop on typed classifications | A Playwright `Failed to fetch` escapes before classification when the page redirects to `verify.html?code=-1000035` |
| OfferToday detail | Pipeline persists each target outcome and already understands API code `-1000035` | Per-target operational logs are absent; durable progress appears every ten targets |
| CTGoodJobs listing | Each parsed page is staged atomically; same-crawl upsert is idempotent | Browser interstitials are generic human verification; navigation status/IP evidence is not retained |
| CTGoodJobs detail | Current target can be marked manual-action and completed targets remain excluded on resume | Same classification gap and long silent fetch/parse/persist interval |
| JobsDB listing | Final aggregate staging is idempotent | All categories are buffered in memory; an IP stop loses the unstaged prefix and cannot truthfully resume |
| JobsDB detail | Target status is persisted and resume reloads manual-action/pending targets | Headless HTTP failures are flattened to `None`; headed interstitials have no IP/WAF classification |
| Shared projection/UI | Resume API and snapshot structure are source-generic | Default backend and frontend IP text is hard-coded to OfferToday |

## 1. Source access classification boundary

Classification stays close to each source transport because the same status or
HTML marker does not mean the same thing on every site. The shared layer owns
the resulting payload, not a broad cross-site heuristic.

### Shared manual-action contract

Extend `ManualActionRequiredError` in
`backend/app/scraper/manual_action.py` with optional, backward-compatible
fields:

```text
classification
code
evidence
```

`to_payload()` emits those fields when present and mirrors `classification`
into `resume_context` so old normalization paths remain usable. Add a small
factory for source-aware session recovery that produces:

```text
action_type = session_recovery
classification = ip_blocked | waf_challenge | auth_expired
source_site
stage
blocked_url
code (when the source provides one)
message and instructions using the actual source display name
evidence (status/code/final URL/reason only; no body)
resume_supported = true
```

Replace the hard-coded OfferToday defaults in
`normalize_manual_action_payload()` with source-aware message/instruction
lookups. Existing explicit payload text remains authoritative.

### Positive evidence matrix

| Source | `ip_blocked` evidence | Non-IP handling |
|---|---|---|
| OfferToday | API integer code `-1000035`, or verification URL query `code=-1000035` | Other `/web/passport/cm/verify` redirects remain `waf_challenge`; ordinary fetch failures remain transient transport |
| JobsDB | Public listing/detail response status 403 or 429, or explicit IP/rate-limit/access-block text in the final document | A 200 response containing only Cloudflare/human-verification markers is `waf_challenge`; other HTTP/network errors keep their transport behavior |
| CTGoodJobs | Public navigation/fetch status 403 or 429, or explicit IP/rate-limit/access-block text in page/final URL/title | Generic Cloudflare/human-verification markers remain `waf_challenge`; proxy exhaustion/configuration remains `proxy_unavailable` |

The source adapters inspect only a bounded marker set and retain the detected
status/final URL as compact evidence. They do not log or persist the HTML body.

## 2. OfferToday redirect race

`OfferTodayBrowserRuntime._fetch_json_response()` becomes the transport
normalization boundary:

1. Wrap Playwright `page.evaluate()` errors only when they represent a rejected
   browser fetch (for example `TypeError: Failed to fetch`).
2. Snapshot `page.url` after the exception and raise
   `OfferTodayTransportError` with `error_kind="network"`, no HTTP status/body,
   and that final URL.
3. Extend `OfferTodayTransportError.error_kind` with `network`.
4. In `classify_offertoday_response()`, parse a verification URL's exact
   integer `code` before the generic verification-path rule. `-1000035` becomes
   `IP_BLOCKED`; other verification URLs remain `WAF_CHALLENGE`.
5. The existing `check_session()` catch and `require_healthy_session()` flow
   then create a normal manual-action payload instead of leaking raw Playwright
   text.

Non-fetch Playwright programming/context errors still propagate. A failed fetch
on a normal page URL classifies as retryable transient transport; the verified
IP URL is non-retryable and stops the batch.

## 3. CTGoodJobs source adapter

Retain page navigation evidence in `CTGoodJobsBrowserPageScraper`:

- store the response status returned by `page.goto()` together with the current
  final URL/title;
- check explicit IP evidence before the generic interstitial check;
- raise a typed `ip_blocked` session-recovery error immediately when confirmed;
- raise a typed `waf_challenge` error after existing challenge retry exhaustion;
  and
- keep display/profile/proxy-environment manual actions distinct.

Listing already stages every page. On resume it may restart at page one; the
repository upsert and database unique constraint on
`(crawl_job_id, source_site, source_job_id)` preserve one row, while later
pending pages continue normally. Detail continues to mark the blocked target
`manual_action_required`, then reloads `manual_action_required,pending` after
Resume.

## 4. JobsDB source adapter and listing persistence

### Listing transport

Inspect the HTTP response before `raise_for_status()` in
`CategoryListScraper.fetch_page()`:

- confirmed 403/429 or explicit IP-block evidence raises typed
  `ManualActionRequiredError(classification="ip_blocked")`;
- generic interstitial evidence raises `waf_challenge`; and
- unrelated status/network/JSON errors retain their existing error behavior.

### Atomic page staging

Add an optional awaitable page sink to `CategoryListScraper.scrape_category()`.
The sink receives the category, page, total pages, and that page's jobs after a
successful parse. The existing aggregate return remains available, but the
standalone executor uses the sink to:

1. build page payloads;
2. call `CrawlJobRuntime.stage_listing_batch()` before requesting the next
   page;
3. update cumulative counters/events; and
4. emit the persisted page-result log.

The final phase no longer restages one in-memory aggregate. A same-task resume
restarts the deterministic category/page walk; repository upsert plus the
database unique constraint makes repeated committed pages idempotent. The
completed run still produces the same distinct Job ID set and metadata.

### Detail transports

- Headless `JobDetailScraper` inspects status/body before flattening HTTP
  failures. It propagates typed IP/WAF manual actions and continues to return
  `None` for ordinary fetch/parser failure behavior.
- `JobsDBBrowserDetailScraper` retains navigation status/final URL/title and
  uses the same JobsDB evidence rules before generic interstitial handling.
- The standalone detail catch keeps marking the current row
  `manual_action_required`; prior completed rows stay completed and Resume
  reloads only manual-action/pending rows.

## 5. Crawl-job state, projection, and UI

The canonical pause event remains `crawl.manual_action_required` with
`manual_action.classification="ip_blocked"`. No new database schema or metric
field is required.

`CrawlJobDispatchService.resume_crawl_job()` remains the only continuation
entry point:

```text
running/failed -> not resumable
manual_action_required + resume_supported -> explicit Resume
detail resume -> manual_action_required,pending targets
listing resume -> original source/categories/page budget, same crawl_job_id
```

Make IP guidance source-aware in backend normalization and extract a small pure
frontend helper used by both Crawl Tasks and Scrape Progress. The displayed
message names CTGoodJobs, JobsDB, or OfferToday and always says to change/clear
the current IP/network before resuming the same task. Existing browser/fresh
resume buttons and request APIs are reused.

## 6. Operational log contract

Continue using `build_scrape_log_event()` and existing logger configuration.
Do not add a second logging framework.

### Common fields

```text
source
crawl_job_id
crawl_phase
crawl_mode
source_listing_crawl_job_id (detail when applicable)
```

### Listing cadence

```text
SCRAPE_LISTING_CATEGORY_START
SCRAPE_LISTING_PAGE_START
SCRAPE_LISTING_BATCH_STAGED   # persisted page result
SCRAPE_LISTING_PAGE_FAIL      # immediate
SCRAPE_LISTING_MANUAL_ACTION  # immediate, includes classification/stage
SCRAPE_LISTING_DONE           # normal, empty, partial, or early stop summary
```

Page logs add category/condition, current/total page or query-task index,
elapsed milliseconds, IDs seen, rows staged, skipped count, and cumulative
counters. They never enumerate every discovered ID.

### Detail cadence

Reuse the established item names across all sources:

```text
SCRAPE_DETAIL_TARGETS_LOADED
SCRAPE_DETAIL_TARGETS_EMPTY
SCRAPE_DETAIL_ITEM_START
SCRAPE_DETAIL_ITEM_OK | SCRAPE_DETAIL_ITEM_FAIL | SCRAPE_DETAIL_ITEM_MANUAL_ACTION
SCRAPE_DETAIL_DONE
```

Every target emits one start and one terminal result with index/total,
`source_job_id`, elapsed milliseconds, outcome, and cumulative counters.
OfferToday gains the same per-target operational logs while its durable
`crawl.detail_progress` checkpoint may remain every ten targets to avoid event
row growth.

Outer executor catches add structured `SCRAPE_EXECUTOR_MANUAL_ACTION` and
`SCRAPE_EXECUTOR_FAIL`; `SCRAPE_EXECUTOR_DONE` remains the final normal summary.

## 7. Test strategy after legacy-suite deletion

Add only the minimum test scaffolding and focused files needed by this task:

- `.gitignore`: add exact negation entries only for the three new backend test
  files below. Keep the broad `backend/tests/*` ignore policy and all other
  user-authored ignore changes intact.
- `backend/tests/conftest.py`: backend import-path setup only.
- `backend/tests/test_cross_source_ip_recovery.py`:
  - OfferToday rejected fetch plus `verify.html?code=-1000035`;
  - source-specific IP versus WAF/generic transport classification;
  - source-aware normalized payload and explicit Resume gating;
  - CTGoodJobs/JobsDB listing and detail stop boundaries;
  - JobsDB page staging idempotence and remaining-work resume.
- `backend/tests/test_cross_source_crawl_logging.py`:
  - page start/persisted result;
  - per-detail start/result and elapsed/counters;
  - empty/early/manual/failure summaries;
  - common correlation fields and secret/body exclusion.
- `frontend/src/components/scraper/ipBlockGuidance.test.js`: source-aware pure
  guidance and fallback behavior.

Tests use fakes/synthetic responses and do not call live job sites. Live smoke
is a separate final verification gate.

## 8. Compatibility, rollout, and rollback

- No migration is planned.
- Existing event types, metrics fields, crawl APIs, and resume endpoints remain
  compatible.
- JobsDB transaction timing changes from phase-end to per-page commits; the
  final distinct row contract remains unchanged and becomes recoverable.
- Roll out with focused tests, lint/compile/build, a container rebuild, then
  bounded source smoke and backend-log inspection.
- If a source detector proves too broad, roll back only that source's positive
  evidence adapter; do not weaken shared manual-action/resume or logging
  contracts.
- If JobsDB page staging fails, the current page transaction rolls back and the
  crawl stops. Earlier pages remain durable and same-task Resume safely
  restarts the deterministic walk.
