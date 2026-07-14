# Design: Stable crawl tasks and OfferToday detail scope

## 1. Problem boundary

The task fixes three connected truthfulness failures without changing crawl
depth or the OfferToday listing algorithm:

1. durable task rows move because history is sorted by mutable activity time;
2. the normal OfferToday detail launch can silently choose global category
   backlog instead of the listing batch the operator just produced; and
3. detail progress mixes resume-cohort sizes and duplicate staging-row counts,
   so neither API nor UI can state distinct job completion.

The minimum mechanism is an immutable history order, an explicit detail-scope
contract, and a read projection over already durable detail events. No schema
migration or historical-event rewrite is required.

## 2. Stable history order

`CrawlJobRepository.list_crawl_task_page()` will order by:

```text
queued_at DESC, created_at DESC, id DESC
```

The API already preserves repository order and the frontend assigns returned
items directly, so no client sort is added. `updated_at` remains visible as
activity information but no longer controls position. Offset pages can still
shift when a genuinely new task is queued; progress updates alone cannot move
rows.

## 3. OfferToday detail-scope contract

### 3.1 Operator launch

The existing direct-run form and API already support
`source_listing_crawl_job_id`. For OfferToday detail mode:

- load listing batches as today;
- automatically choose the newest eligible batch with pending, failed, or
  manual-action rows when the operator has not made an explicit scope choice;
- relabel the field as current listing-batch scope rather than a legacy filter;
- retain an explicit `Global category backlog` option for intentional unbound
  recovery; and
- never overwrite an explicit user choice when async batch data refreshes.

The submitted payload remains the single source of truth. The dispatch service
persists the supplied listing ID in the durable crawl-job request payload.

### 3.2 Runtime selection

The existing runtime boundary is retained:

- bound request: filter by `crawl_job_listings.crawl_job_id`, and
  `resolve_offertoday_detail_category_ids()` returns no category restriction;
- unbound request: expand requested OfferToday category IDs and filter by
  `source_classification_id`; and
- group candidate rows by canonical `source_job_id` before the detail limit so
  duplicate staging siblings produce one fetch.

Regression tests will make this distinction executable, including null
classification keyword/hybrid rows. Dispatch/resume tests will prove that a
bound ID survives manual-action recovery.

## 4. Distinct detail-progress projection

### 4.1 Durable evidence

Existing events are authoritative:

- `crawl.detail_cohort_frozen` records each resume cohort, its distinct size,
  and reconciled IDs;
- `crawl.detail_attempt` records canonical `source_job_id` and classification;
  and
- terminal crawl events define the current lifecycle state.

`detail_run_completed` remains a legacy staging-row metric and is not reused as
distinct job completion.

### 4.2 Batch summary

Add a service batch projection for the crawl-job IDs already on the requested
page. The existing repository batch API loads only the required detail event
types for all page IDs in one query, then the service folds those events by
crawl job and distinct canonical source job ID. This avoids per-task queries
and database-specific JSON extraction while keeping SQLite and PostgreSQL
behavior identical; raw event payloads never cross the API boundary.

For each OfferToday detail task:

```text
target_total = largest frozen fetch cohort (the original cohort for resume flows)
success_ids = distinct IDs with a success attempt
terminal_ids = distinct IDs with a terminal_unavailable attempt
failed_ids = distinct IDs with a settled non-recoverable failure and no later success/terminal
reconciled_ids = union of reconciled IDs from frozen cohorts
remaining = max(target_total - |success U terminal U failed|, 0)
```

Recoverable `ip_blocked`, auth, and WAF attempts do not settle a target and do
not inflate processed counts. Outcome precedence prevents one source ID from
appearing in multiple settled counters.

The task-list API and the active-task snapshot path call the same batch
projection; neither performs a per-task query. If a legacy task has no cohort
events, the snapshot retains its existing raw-metric fallback.

### 4.3 Additive snapshot fields

The snapshot adds distinct-unit fields while preserving current response keys:

```text
detail_distinct_target_total
detail_distinct_succeeded
detail_distinct_terminal_unavailable
detail_distinct_failed
detail_distinct_reconciled
detail_distinct_remaining
```

`jobs_saved` fallback will include raw `metrics.jobs_saved` for runtimes that do
not use ingest counters.

## 5. UI projection

For OfferToday detail tasks with the additive fields, list-row chips and the
detail panel show:

```text
Fetched <success> / <target>
Terminal <terminal>          (when non-zero)
Reconciled <reconciled>      (when non-zero)
Failed <failed>              (when non-zero)
Remaining <remaining>
```

The old `Queue <detail_target_rows>` fallback remains for tasks/sources without
the new contract. Listing-only and completed-partial wording is unchanged.

## 6. Compatibility and performance

- No database migration and no historical event mutation.
- Event aggregation is bounded to crawl-job IDs on the current page/active
  snapshot set, uses one batch query, and exposes only grouped distinct counts
  to the frontend.
- Existing category-backlog runs remain valid when explicitly selected.
- Existing full OfferToday runs already bind their current listing job and keep
  that behavior.
- Stable ordering affects only durable Crawl Tasks history; live scrape progress
  ordering is out of scope.

## 7. Operational boundary and rollback

Deterministic verification may query the existing `4cee...` and `21436...`
records read-only, but it will not launch the pending live detail backlog. After
code verification, a listing-bound selection preview is reviewed and the user
is asked before any large OfferToday repair run.

Each change is independently reversible: repository ordering, scope-default UI,
batch progress projection, and additive UI fields can be rolled back without a
schema downgrade.
