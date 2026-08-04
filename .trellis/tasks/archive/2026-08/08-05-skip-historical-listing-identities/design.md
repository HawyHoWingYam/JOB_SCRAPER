# Design: Skip historical listing identities in manual listing runs

## Boundary

`CrawlJobRuntime.stage_listing_batch` remains the single acceptance boundary for
listing payloads from JobsDB, CTGoodJobs, and OfferToday. It will decide whether the
current crawl is manual, bulk-load historical identities for that Source, and exclude
them before `upsert_listing` creates current-run rows.

No API, database schema, or Dispatch Plan change is required. The operator separately
approved one guarded physical cleanup of the two diagnosed later-run overlap sets.

## Data Flow

1. Open the existing staging transaction and normalize the Source and payload IDs.
2. Load the current `CrawlJob` and fail if it is missing. The historical exclusion is
   active only when `trigger_type == "manual"`.
3. Preserve the existing fail-closed bulk lookup of non-deleted Published Jobs.
4. For a manual run with candidate IDs, call
   `CrawlJobListingRepository.list_existing_source_job_ids` with the normalized Source
   and `exclude_crawl_job_id` set to the current run. This produces a distinct set of
   identities owned by other crawl runs without loading full rows.
5. Treat the union of Published Job IDs and historical listing IDs as excluded from
   new staging. Preserve ordered, distinct tuples in the persist result so callers,
   events, metrics, and tests can distinguish published from historical exclusion.
6. Continue current-run uniqueness handling through the existing database constraint
   and `upsert_listing` result. Current-run rows are never returned by the historical
   query.
7. Update collection metrics from observed payloads as today. Increment existing-skip
   metrics for payload occurrences excluded by either Published Job or historical
   listing ownership; staged/detail counters continue to derive from accepted rows.
8. Commit once. Any crawl lookup, Published Job lookup, historical listing lookup,
   OfferToday identity validation, staging, or metric failure rolls back the batch.

## OfferToday Compatibility

OfferToday still loads full historical rows to validate encrypted identity authority,
preserve identity-conflict hard stops, and retain terminal-unavailable observations.
That validation occurs before staging exclusion.

For a manual listing run, an otherwise repairable identity owned by another crawl run
is classified as historical existing and is not restaged as `repair`. This is the
intentional behavior change approved by the requirement that manual listing always
skip existing identities. Dedicated OfferToday detail/repair workflows remain
unchanged and continue to operate on the original listing row.

## Result Contract and Metrics

Extend `ListingBatchPersistResult` with an ordered
`historical_source_job_ids` tuple. Keep `published_source_job_ids` unchanged so the two
reasons remain auditable. `skipped_existing` and `jobs_skipped_existing` retain each
Source runner's existing aggregation unit while including exclusions for either
reason; raw and collected counters continue to describe Source observations and are
not redefined as global distinct counts.

OfferToday listing-observation events may use a `historical_existing` classification
for rows that pass identity validation but belong to an earlier run. Same-run
observations retain the current `duplicate` classification.

## Compatibility and Scope

- Manual JobsDB, CTGoodJobs, and OfferToday listing runs gain historical exclusion.
- Scheduled runs retain their existing Published Job exclusion and do not gain a new
  cross-run policy in this task.
- The same textual ID at another Source remains eligible because both lookups are
  Source-qualified.
- All historical detail statuses block new manual staging; status is irrelevant to
  ownership.
- Existing rows, events, metrics, tasks, and Published Jobs are not rewritten.

## Rollback

Rollback of the runtime restores the prior classification and result contract. Runs
executed while enabled merely stage fewer redundant rows.

The approved cleanup is deliberately irreversible: it deletes only redundant later-run
pending rows after proving exact counts and zero Published Job, detail-owner, and
Dispatch Plan references. The original runs retain the canonical backlog, so restoring
the later-run duplicates would recreate the defect rather than recover unique data.
