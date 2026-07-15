# Design: CTGoodJobs recovery classification and common detail metrics

## 1. Design summary

The change has two connected paths:

```text
CTGoodJobs response
  -> positive access/unavailable classification
  -> parse + persist
  -> bounded structural-anomaly guard
  -> detail status transition
  -> runtime metrics
  -> crawl-task snapshot common projection
  -> Crawl Tasks metric chips
```

The source adapter owns positive page evidence. The CTGoodJobs executor owns the consecutive anomaly guard because it spans targets within one run. `CrawlJobRuntime` remains the owner of durable detail-status transitions. `build_crawl_task_snapshot` becomes the sole backend owner of the normalized cross-source UI metrics.

## 2. CTGoodJobs outcome model

### 2.1 Positive page evidence

Keep `classify_public_access_evidence` authoritative for `ip_blocked` and `waf_challenge`. Extend CTGoodJobs detail handling with a small source-specific page-state classifier that consumes only:

- response status;
- final URL;
- document title;
- bounded, non-persisted HTML used in memory for explicit markers.

It returns one of:

- `access_manual_action` with compact positive evidence;
- `terminal_unavailable` with a compact reason;
- `normal_or_unknown`.

HTTP 404/410 is terminal unavailable, not IP blocking. Explicit unavailable markers must be scoped to page-state/title or structured payload evidence rather than an arbitrary occurrence inside a job description.

### 2.2 Structural anomaly guard

The post-parse/persist path recognizes only a bounded allowlist of stable `InvalidIngestPayloadError.reason` values that demonstrate a non-job document shape, initially `missing_job_content` and `missing_company_identity`.

The executor keeps an in-memory `(reason, consecutive_count)` guard:

- valid persisted detail -> reset;
- first supported reason -> persist ordinary `failed`, remember the reason, continue;
- different supported reason -> persist ordinary `failed`, replace remembered reason, continue;
- second consecutive same reason -> do not persist as ordinary failure; create a `ManualActionRequiredError` with `classification=content_anomaly`, mark the current row `manual_action_required`, emit the standard crawl manual-action event, and return immediately;
- unrelated exceptions follow existing failure behavior and reset the structural signature so unrelated failures do not trip the guard.

The first anomaly remains `failed`. The resume payload must include `failed`, `manual_action_required`, and `pending`, ensuring it is retried. Completed and terminal outcomes stay excluded by the existing target loader.

### 2.3 Manual-action compatibility

Add `content_anomaly` to the resumable manual-action classification contract with source-aware default message/instructions. It must not receive an IP-specific code or guidance. Existing `ip_blocked`, `waf_challenge`, and `auth_expired` behavior remains unchanged.

### 2.4 Terminal unavailable transition

Add a narrow runtime convenience operation that calls the existing generic `transition_detail_outcome(..., status="terminal_unavailable")`. Do not add a new table or status enum; `terminal_unavailable` already exists in detail-status counting and retry exclusion.

## 3. Common metrics contract

### 3.1 Canonical snapshot fields

Add normalized additive snapshot fields while preserving existing source/raw fields:

| Field | Meaning |
|---|---|
| `detail_target_count` | Current selected/frozen detail denominator |
| `detail_fetched_count` | Successful detail outcomes; OfferToday uses distinct succeeded IDs |
| `detail_saved_count` | Successfully persisted jobs; for CTGoodJobs/JobsDB a completed transition follows persistence |
| `detail_failed_count` | Unexpected/retryable failed outcomes only |
| `detail_unavailable_count` | Explicit terminal-unavailable outcomes |
| `detail_manual_action_count` | Targets currently requiring operator action |
| `detail_remaining_count` | Targets not in fetched, failed, or terminal-unavailable outcomes; includes manual-action work |

For OfferToday, prefer the existing distinct cohort projection:

```text
target      = detail_distinct_target_total
fetched     = detail_distinct_succeeded
failed      = detail_distinct_failed
unavailable = detail_distinct_terminal_unavailable
remaining   = detail_distinct_remaining
saved       = jobs_saved
```

For CTGoodJobs and JobsDB, use detail-run transition counts:

```text
target      = detail_target_rows
fetched     = detail_run_completed
saved       = detail_run_completed (persistence precedes completed transition)
failed      = detail_run_failed
unavailable = detail_run_terminal_unavailable
manual      = detail_run_manual_action_required
remaining   = max(target - fetched - failed - unavailable, 0)
```

`manual` is intentionally included in `remaining`; it describes why some remaining work cannot proceed. Reconciled/skipped rows are outside `detail_target_rows` and are not subtracted again. Saved is not part of the denominator conservation equation.

Compatibility fallbacks may use legacy fields when a historic snapshot lacks run metrics, but new normalized fields must never mix a listing-batch total with a detail-run denominator.

### 3.2 Frontend rendering

`buildDetailMetricSummary` reads only normalized common fields for the common chips and always renders:

```text
Detail targets N | Fetched N | Saved N | Failed N | Remaining N
```

Then it appends nonzero `Unavailable` and `Manual action`. OfferToday segment/backlog chips remain conditional source-specific supplements. Historic API payload fallback remains at the snapshot layer rather than being reimplemented in JSX.

## 4. Data and compatibility

- No schema migration is required.
- Existing crawl jobs are projected from stored metrics/events at read time.
- Existing snapshot field names remain available to other consumers.
- `content_anomaly` is additive; old manual-action events continue to normalize unchanged.
- No response body is written to events, logs, or database fields.

## 5. Logging and operator behavior

- Positive verification continues to log `SCRAPE_DETAIL_ITEM_MANUAL_ACTION` with compact classification/reason.
- First anomaly logs ordinary failure with bounded `error_type` and anomaly reason.
- Circuit-breaker activation logs manual action with `classification=content_anomaly`, `consecutive_count=2`, and bounded reason; it logs the standard final detail summary and sends no later request.
- Terminal unavailable logs a terminal result distinct from ordinary failure, with no raw body.
- Resume remains explicit through `POST /api/v1/crawl-jobs/{id}/resume`.

## 6. Risks and mitigations

- False anomaly pause: require two consecutive identical allowlisted reasons and reset on success/different failure.
- False expiry: require HTTP/structured/top-level explicit evidence; never infer from missing fields.
- Metric denominator drift: compute all common fields together in the snapshot service from one source-specific branch and cover conservation cases in tests.
- Historic record gaps: use bounded compatibility fallbacks, always returning numeric common fields.
- External verification instability: deterministic synthetic fixtures are the release gate; do not provoke a live block.

## 7. Rollback

The change is code-only and additive. Roll back the classifier/guard, normalized snapshot aliases, and JSX rendering together. No database downgrade or data repair is needed; existing detail statuses remain valid.

