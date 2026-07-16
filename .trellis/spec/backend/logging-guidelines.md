# Backend Crawl Logging Contracts

## Scenario: Cross-source listing and detail observability

### 1. Scope / Trigger

Use this contract when changing CTGoodJobs, JobsDB, or OfferToday transports,
standalone crawl executors, listing staging, detail processing, retries, or
manual-action handling. Operational logs let an operator identify the current
page/target and terminal reason without querying crawl tables.

Logs complement durable `CrawlJobEvent` rows and metrics; they are not a second
state store. The canonical pause event remains `crawl.manual_action_required`.

### 2. Signatures

```python
build_scrape_log_event(event: str, **fields: Any) -> str

redact_url(url: str, *, redact_query: bool = False) -> str

CrawlJobRuntime.write_progress_event(
    *, crawl_job_id, event_type, emitted_by, payload
) -> None
```

Source executors emit through their module logger:

```python
logger.info(build_scrape_log_event("SCRAPE_LISTING_PAGE_START", ...))
logger.warning(build_scrape_log_event("SCRAPE_DETAIL_ITEM_FAIL", ...))
```

### 3. Contracts

#### Correlation fields

Every executor, listing, and detail record includes, where applicable:

```text
source
crawl_job_id
crawl_phase
crawl_mode
source_listing_crawl_job_id  # detail work bound to a listing batch
```

Do not create a second formatter for one source. Use
`build_scrape_log_event()` so values have the same `EVENT key=value` shape and
embedded newlines cannot forge records.

Reusable-browser attach records follow the same rule. Attempt, success, and
failure logs include configured `cdp_host`, resolved `cdp_connect_host`, and
`debug_port` in the formatted message, not only as `LogRecord.extra`; container
log collectors may not render arbitrary extra fields.

#### Listing cadence

For each source, emit:

```text
SCRAPE_LISTING_CATEGORY_START
SCRAPE_LISTING_PAGE_START
SCRAPE_LISTING_BATCH_STAGED
SCRAPE_LISTING_PAGE_RETRY       # only when a real retry will occur
SCRAPE_LISTING_MANUAL_ACTION    # immediate, non-retryable stop
SCRAPE_LISTING_PAGE_FAIL        # immediate terminal/non-manual failure
SCRAPE_LISTING_DONE             # normal, empty, partial, or early stop
```

One page-start and one persisted-result record are the routine unit. The staged
record contains numeric page counts (`job_ids`, `listings_staged`, skipped and
cumulative counters), elapsed milliseconds, and scope fields. Never enumerate
the page's Job IDs in a log record. A listing IP/WAF stop must emit the manual
record and final summary before returning; it must not start detail work.

#### Detail cadence

For every selected target, emit exactly one start and one terminal result:

```text
SCRAPE_DETAIL_TARGETS_LOADED
SCRAPE_DETAIL_TARGETS_EMPTY
SCRAPE_DETAIL_ITEM_START
SCRAPE_DETAIL_ITEM_OK | SCRAPE_DETAIL_ITEM_FAIL |
SCRAPE_DETAIL_ITEM_MANUAL_ACTION
SCRAPE_DETAIL_RETRY
SCRAPE_DETAIL_DONE
```

Item records include `detail_index`, `detail_total`, compact
`source_job_id`, elapsed milliseconds, outcome, and cumulative processed /
succeeded / failed / saved counters. Retry, confirmed block, and manual action
are logged immediately. `SCRAPE_DETAIL_DONE` is required for empty, completed,
manual-action, and handled early-failure exits. Durable progress events may use
a lower cadence than operational logs.

#### Executor boundary and levels

- `INFO`: starts, persisted page results, successful item results, empty and
  completed summaries.
- `WARNING`: retry, confirmed IP/WAF/manual action, handled per-page or
  per-target failure.
- `ERROR` / `logger.exception`: unexpected executor failure.

Every direct source executor uses `SCRAPE_EXECUTOR_START`,
`SCRAPE_EXECUTOR_DONE`, `SCRAPE_EXECUTOR_MANUAL_ACTION`, and
`SCRAPE_EXECUTOR_FAIL` at its outer boundary.

#### Sensitive and bounded values

Never log cookies, auth headers, CSRF values, storage state, browser fetch
options, response bodies, full descriptions, encrypted-ID collections, or
unbounded Job-ID lists. Log error class/classification and bounded counters,
not raw response data.

`build_scrape_log_event()` removes query and fragment values from fields named
`url` or ending in `_url`; the durable manual-action payload may retain the
full blocked URL needed by the operator. Log the classification/code as
separate fields, for example `classification=ip_blocked code=-1000035`.

### 4. Validation & Error Matrix

| Condition | Required logging behavior |
|---|---|
| Page fetch and staging succeed | Page start, numeric staged result, cumulative counters |
| Page is valid but empty | Start, staged result with zero counts, final summary if phase ends |
| Transient retry will occur | Immediate retry record with attempt/max and no terminal summary yet |
| Confirmed IP/WAF block | Manual-action record plus final phase summary; no later request |
| Generic DNS/timeout/parser failure | Failure/retry classification; never relabel as IP |
| Detail target succeeds/fails | One start and exactly one OK/FAIL result |
| No detail targets | `TARGETS_EMPTY` followed by `DETAIL_DONE` |
| URL contains query token | Log keeps scheme/host/path but omits query/fragment values |
| Raw payload contains secret/body | Secret/body is absent from every emitted log string |
| Unexpected executor exception | `SCRAPE_EXECUTOR_FAIL` with error type and correlation, then normal state transition |
| Reusable-browser attach succeeds | Formatted attempt/success records expose configured and resolved host plus port |
| Reusable-browser attach fails | Formatted failure uses bounded `error_type` or reason; no raw browser/session data |

### 5. Good / Base / Bad Cases

- **Good:** JobsDB stages page 2, logs `job_ids=20 listings_staged=18`, then
  page 1 returns 429. The log immediately shows `ip_blocked` and a listing
  summary with the committed prefix; detail never starts.
- **Base:** A detail phase selects zero rows. It logs loaded/empty/done with the
  crawl and source-listing IDs, then completes normally.
- **Bad:** A staged-page log prints `job_ids=['1', '2', ...]` or a blocked URL
  containing `token=...`. This creates noisy output and leaks request evidence.
- **Bad:** Only the outer stack trace is logged. The operator cannot tell which
  page/target stalled or whether completed work is safe.

### 6. Tests Required

- `backend/tests/test_cross_source_crawl_logging.py` asserts listing
  category/page start, persisted result, early/manual and final summaries for
  all three sources; detail start/result/retry/empty/manual/final cadence; common
  fields; elapsed/cumulative counters; bounded IDs; and secret/query exclusion.
- `backend/tests/test_cross_source_ip_recovery.py` asserts a confirmed block
  stops later requests, retains committed listing work, and resumes from the
  same task boundary without refetching completed details.
- Run Ruff on every touched Python module, `compileall`, focused tests, frontend
  source-aware guidance tests/build, container log inspection, and
  `git diff --check`.
- `backend/tests/test_jobsdb_browser_detail_scraper.py` asserts the formatted
  attach success/failure strings contain crawl correlation and both CDP host
  forms, rather than relying on invisible logger extras.

### 7. Wrong vs Correct

#### Wrong

```python
logger.info("staged jobs=%s response=%s", job_ids, response_body)
logger.error("crawl failed: %s", exc)
```

This enumerates IDs, risks body/secret leakage, and loses crawl/page context.

#### Correct

```python
logger.info(
    build_scrape_log_event(
        "SCRAPE_LISTING_BATCH_STAGED",
        source="jobsdb",
        crawl_job_id=crawl_job_id,
        crawl_phase="listing",
        crawl_mode=crawl_mode,
        current_page=page,
        job_ids=batch_result.job_ids_seen,
        listings_staged=batch_result.rows_staged,
        cumulative_pages=pages_processed,
    )
)
```

The event is comparable across sources, bounded, and safe to inspect in
backend/container logs.
