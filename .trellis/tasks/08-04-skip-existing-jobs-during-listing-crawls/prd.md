# Skip existing jobs during listing crawls

## Goal

Prevent one-off and scheduled listing crawls from creating detail work for source job
IDs already present in the Published Job Corpus, and remove already-persisted IDs from
the two reported historical listing batches.

## Background

- Crawl job `720df33d-bcca-4ec0-b6e0-0da1f9c01a4f` (CTGoodJobs) staged 3,090
  distinct IDs with `skip_existing=false`; 2,095 matched persisted jobs during
  diagnosis.
- Crawl job `06e326b2-c4bf-440c-b196-b1a04fc8d6a5` (JobsDB) staged 3,803
  distinct IDs with `skip_existing=false`. Its persisted-job match count increased
  while diagnosis was running and reached 2,670 at the final planning query.
- Both crawl jobs are `completed`, their executions exited successfully, and no worker
  remains. The remaining work is durable `crawl_job_listings`, not a live process.
- Manual/scheduled dispatch currently writes `skip_existing=false` at
  `backend/app/services/crawl_job_dispatch_service.py:716`. Runtime Job lookup for
  non-OfferToday sources is conditional on that value at
  `backend/app/services/crawl_job_runtime.py:416-424,1002-1013`.
- Final Job persistence already uses source-aware upsert and a unique constraint on
  `(source_site, source_job_id)`. The defect therefore creates redundant listing/detail
  work, not duplicate persisted Job rows.
- OfferToday currently classifies an incomplete/failed published Job as a listing-time
  `repair` target. This task intentionally supersedes that part of
  `.trellis/spec/backend/offertoday-production-crawl.md:119-141`; dedicated detail or
  repair workflows become the only way to refresh an existing Job.
- The current database contains no soft-deleted Jobs. Changing Job deletion semantics
  is outside this task.

## Requirements

### R1. Universal published-Job filtering

- After a listing page yields source job IDs and before staging/detail scheduling, use
  one bulk lookup keyed by normalized `(source_site, source_job_id)`.
- One-off and scheduled JobsDB, CTGoodJobs, and OfferToday listing runs must skip every
  non-deleted published Job, regardless of completeness, prior detail failure, expiry,
  or age.
- Listing discovery has no force-refresh mode. Existing-Job refresh and repair belong
  to dedicated detail/repair workflows.
- Listing pages still run because IDs cannot be known beforehand. The optimization
  removes staging and detail fetches, not source listing requests.

### R2. Safety and source-specific behavior

- Identity comparison is source-aware; the same textual ID from another source must
  not be skipped.
- Bulk Job lookup is fail-closed for all sources. Failure rolls back/fails the batch;
  it must never be treated as an empty result.
- OfferToday historical code-2520 terminal skipping and identity-conflict hard stops
  remain unchanged. Only its published-incomplete-to-repair rule changes to skip.
- Cross-task reservation for the same not-yet-published ID is out of scope. Operations
  normally run one crawl task at a time, and the Job uniqueness constraint remains the
  final persisted-row safeguard.

### R3. Truthful new-run metrics

- `raw_job_ids_collected` and `job_ids_collected` preserve the IDs observed from source
  listing pages.
- `jobs_skipped_existing` counts persisted identities removed from actual work.
- `listings_staged` and detail pending/total metrics count only genuinely new backlog.

### R4. Historical physical cleanup

- For crawl jobs `720df33d-bcca-4ec0-b6e0-0da1f9c01a4f` and
  `06e326b2-c4bf-440c-b196-b1a04fc8d6a5`, physically delete every
  `crawl_job_listings` row whose source-aware identity currently exists in `jobs`,
  including rows already marked completed.
- Preserve all `jobs`, `crawl_jobs`, `crawl_job_events`, and execution rows. Preserve
  every listing row whose source-aware identity is not persisted.
- The approved JobsDB rows are frozen into detail Dispatch Plans
  `0c4418c9-2327-4c75-8268-f71f62369cd2` and
  `ba27b116-21f1-4440-b163-1d899ee3fe43`. Physically delete both plans and all
  target membership before deleting their referenced listing rows. Preserve the
  consumed plan's cancelled crawl-job row, but clear its now-invalid Dispatch Plan
  ID/fingerprint link. Abort on any additional plan or Schedule Execution reference.
- Do not cancel the terminal crawl jobs, append a remediation event, or automatically
  dispatch detail work. The operator will manually run detail tasks for remaining IDs.
- Run cleanup as one guarded transaction: dry-run matched/retained counts per expected
  task/source; validate exact IDs and sources; delete and replace metrics atomically;
  then verify no matching listing rows remain and missing-Job rows are preserved. Any
  mismatch aborts and rolls back.
- Replace result metrics with the post-deletion row snapshot, intentionally discarding
  historical counters. Recompute remaining distinct ID/staged/detail-status counts,
  set non-row-derived result counters such as `jobs_saved`, `items_emitted`, and
  `jobs_skipped_existing` to zero, remove `pages_processed`, and leave old events
  unchanged.

## Acceptance Criteria

- [x] One-off and scheduled listing runs for all three sources skip any published
      source identity before staging or detail fetch.
- [x] A new ID from the same batch is staged and remains detail-eligible.
- [x] A matching textual ID from another source is not skipped.
- [x] A bulk existing-Job lookup failure fails without staging the affected batch.
- [x] OfferToday complete and incomplete/failed published Jobs are skipped, while
      terminal-unavailable and identity-conflict behavior remains intact.
- [x] Dedicated detail/repair paths remain usable for existing Jobs.
- [x] New-run metrics separate discovered IDs, skipped existing IDs, staged new IDs,
      and genuine detail workload.
- [x] Cleanup dry-run proves its exact two-task/source boundary before apply.
- [x] Cleanup removes all matching listing rows across statuses, retains all missing-Job
      listing rows, changes no Published Job rows, and creates no event.
- [x] Cleanup destroys exactly the two approved JobsDB detail Dispatch Plans and their
      target membership, detaches but preserves the consumed plan's cancelled crawl
      job, and rejects any unexpected authority reference.
- [x] Cleanup replaces the two metrics objects with their post-deletion row-derived
      snapshots and removes `pages_processed`.
- [x] Focused tests and relevant backend regression suites pass.

## Out of Scope

- Deleting, soft-deleting, restoring, or changing lifecycle semantics for Published
  Jobs.
- Cross-task reservation/ownership for concurrent discovery of an unpublished ID.
- Automatically creating or dispatching follow-up detail tasks.
- A listing-time force-refresh control.
