# Skip historical listing identities in manual listing runs

GitHub issue: [#53](https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/53)

## Goal

Prevent manual listing runs from recreating work for a Source Job identity that the
system has already published or staged in any earlier crawl run. Existing detail
backlog remains owned by its original run and can be processed through the existing
manual detail/recovery workflows.

## Background

- Published-Job filtering is already implemented for manual JobsDB, CTGoodJobs, and
  OfferToday listing runs under GitHub issue #51.
- That filtering does not treat a historical `CrawlJobListing` as existing work when
  its Job detail has not yet been published. The database permits one occurrence of a
  Source Job identity per crawl run, so a later run can stage the same identity again.
- CTGoodJobs run `17366a36-eab3-4860-ac26-8823e8521843` completed with 995 distinct
  staged identities and no within-run duplicates or Published Job matches. Of those,
  993 had already been staged by run `720df33d-bcca-4ec0-b6e0-0da1f9c01a4f`; only 2
  were new.
- JobsDB run `3c25080b-beea-4e5d-a147-c5b0f7af6935` completed with 1,140 distinct
  staged identities and no within-run duplicates or Published Job matches. Of those,
  1,112 had already been staged by run
  `06e326b2-c4bf-440c-b196-b1a04fc8d6a5`; only 28 were new.
- The operator approved physical cleanup after implementation. A guarded transaction
  deleted the 993 and 1,112 overlapping rows from the two later runs. The later runs
  now retain exactly 2 and 28 identities respectively, with zero historical overlap.
- `raw_job_ids_collected` and `job_ids_collected` describe IDs observed while paging;
  they are not a global distinct-identity count. The defect is demonstrated by the
  staged cross-run overlap, not by those collection counters alone.

## Requirements

### R1. Historical identity exclusion

- For every manual JobsDB, CTGoodJobs, and OfferToday listing run, exclude a normalized
  `(source_site, source_job_id)` before staging when either:
  - it already exists as a non-deleted Job in the Published Job Corpus; or
  - it exists in `CrawlJobListing` for any other crawl run, regardless of that
    listing's detail status.
- Identity comparison must remain Source-aware. The same textual ID from a different
  Source is not the same identity.
- Rows already staged by the current run remain governed by current-run uniqueness;
  the historical exclusion must not misclassify the current run as prior work.

### R2. Existing backlog ownership

- A later manual listing run must not take ownership of an older pending, failed,
  manual-action-required, terminal, completed, or otherwise retained listing.
- Existing manual detail and recovery workflows remain the way to process or retry
  old pending/failed detail backlog.
- Do not automatically create, dispatch, move, delete, or update historical detail
  work as part of listing discovery.

### R3. Operational safety and metrics

- Historical identity lookup is fail-closed: if it cannot be completed, the affected
  listing batch fails rather than staging potentially duplicate work.
- Preserve truthful collection history: collection counters continue to report what
  the Source returned, while staged/detail-work counters include only identities that
  survive both Published Job and historical-listing exclusion.
- Existing source-specific terminal-unavailable and identity-conflict behavior remains
  unchanged.

### R4. Approved historical cleanup

- Physically delete only the source-aware identities in CTGoodJobs run
  `17366a36-eab3-4860-ac26-8823e8521843` that overlap run
  `720df33d-bcca-4ec0-b6e0-0da1f9c01a4f`, and only the identities in JobsDB run
  `3c25080b-beea-4e5d-a147-c5b0f7af6935` that overlap run
  `06e326b2-c4bf-440c-b196-b1a04fc8d6a5`.
- Abort the transaction unless the exact delete boundaries remain 993 CTGoodJobs rows
  and 1,112 JobsDB rows, every row is pending, and no row has a Published Job, detail
  owner, or Dispatch Plan reference.
- Preserve the old runs, Published Jobs, Crawl Jobs, events, and historical metrics.
  Do not automatically dispatch detail work.

## Acceptance Criteria

- [x] A manual listing run for each of JobsDB, CTGoodJobs, and OfferToday skips a
      Source Job identity found in any earlier crawl run, for every historical listing
      status, except that OfferToday identity-conflict evidence retains its existing
      hard-stop behavior.
- [x] A Source Job identity already in the Published Job Corpus is still skipped.
- [x] A genuinely new Source Job identity is staged and remains detail-eligible.
- [x] The same textual ID from another Source is not skipped.
- [x] Repeated observations inside the current run do not create duplicate rows and
      are not mistaken for a historical-task match.
- [x] Historical lookup failure does not stage the affected batch.
- [x] Collection metrics preserve observed crawl history; staged and detail-work
      metrics reflect only newly accepted identities.
- [x] Existing historical listing rows and their statuses are unchanged, and manual
      detail/recovery workflows can still process eligible backlog.
- [x] A regression check reproduces the CTGoodJobs 993-of-995 and JobsDB
      1,112-of-1,140 overlap pattern before the fix and proves later runs no longer
      stage those historical identities.
- [x] Focused cross-source tests and relevant backend regression suites pass.
- [x] The guarded cleanup hard-deletes exactly 993 CTGoodJobs and 1,112 JobsDB
      overlapping rows, leaving 2 and 28 distinct identities with zero historical
      overlap and no authority references.
- [x] Cleanup leaves old runs, Published Jobs, events, and historical metrics
      unchanged.

## Out of Scope

- Automatically dispatching detail or recovery work for old backlog.
- Changing Published Job lifecycle or deletion semantics.
- Adding cross-process reservation or locking for concurrent listing runs; ordinary
  operation has only one crawl run executing at a time.
- Changing scheduled listing-run behavior beyond its existing Published Job filter.
