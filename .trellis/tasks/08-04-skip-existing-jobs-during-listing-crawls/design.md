# Design: skip existing jobs during listing crawls

## Boundaries

The invariant belongs in `CrawlJobRuntime`, the shared boundary between validated
listing payloads and durable listing/detail work. Dispatch and standalone scripts must
author truthful `skip_existing=true` payloads, but runtime enforcement must not depend
solely on caller correctness or on historical frozen payload values.

The change covers JobsDB, CTGoodJobs, and OfferToday. Dedicated detail and repair
services are not changed except for tests proving they remain independently callable.

## Future-run data flow

1. A source runner requests and validates a listing page and extracts canonical source
   job IDs.
2. `stage_listing_batch` performs one source-aware bulk lookup against `jobs` with
   error propagation enabled for every source.
3. Identity conflicts and OfferToday terminal-unavailable evidence retain their
   existing precedence.
4. Every published identity is counted as skipped and produces no
   `crawl_job_listings` row. OfferToday no longer turns an incomplete published Job
   into a `repair` row.
5. Only absent identities are staged. Current-crawl deduplication continues to prevent
   repeated rows from pages/conditions inside one run.
6. `load_detail_targets` repeats a fail-closed published-Job lookup as a defensive gate
   for historical/legacy staged rows. Existing rows are never returned as fetch targets.
7. Source-observation metrics retain discovered counts; work metrics use the filtered
   cohort.

New dispatch plans and standalone runtime plans author `skip_existing=true`. Historical
false values remain readable but cannot disable the runtime invariant. Existing CLI
syntax may remain parse-compatible, but it cannot expose a force-refresh path.

## OfferToday compatibility change

Preserve identity-conflict and historical code-2520 terminal precedence. Replace the
published completeness partition with a single published-existing skip outcome. New
IDs remain `new` targets. Existing dedicated repair tooling remains the explicit path
for incomplete Jobs.

Update `.trellis/spec/backend/offertoday-production-crawl.md` so future work does not
restore listing-time repair accidentally. Tests must change the old incomplete→repair
expectations rather than treating this intentional contract change as a regression.

## Lookup failure and transaction behavior

`JobRepository.list_existing_jobs_by_source_ids` currently supports swallowing errors
for non-OfferToday callers. Shared runtime calls must request propagation for all three
sources. Staging remains within the existing page-batch transaction, so a failed lookup
creates no partial listing work.

## Historical cleanup

Add a narrowly scoped, dry-run-first remediation command for the two approved crawl
job/source pairs. It will:

1. lock and validate both terminal crawl job rows and expected sources;
2. compute matching listing IDs through a source-aware join to non-deleted `jobs`;
3. report matched and retained counts without mutation by default;
4. validate that JobsDB references are owned by exactly the two operator-approved
   detail Dispatch Plans, that their states/source/membership match the reviewed
   boundary, and that no Schedule Execution references either plan;
5. on explicit apply, detach the consumed plan from its preserved cancelled crawl job,
   persist a bounded removed-authority tombstone in that job's frozen request payload,
   physically delete both plans plus target membership, then delete all matching
   listing rows regardless of detail status;
6. derive a new metrics object from surviving rows, with remaining distinct/staged and
   detail-status counts, zeroed non-row-derived result counters, and no
   `pages_processed` key;
7. replace metrics and delete rows in one transaction;
8. verify the two plans and all their membership are absent, zero published-identity
   matches remain, and retained listing IDs plus preserved task/event/execution rows
   remain before
   commit.

The command does not touch Job, event, execution, or task status records and does not
dispatch follow-up detail work. It is idempotent: a second dry-run/apply finds zero
matching rows and leaves the surviving snapshot unchanged.

## Compatibility and rollback

- Runtime behavior is intentionally stricter: historical `skip_existing=false` cannot
  force refresh through listing discovery.
- Code rollback restores old scheduling behavior but cannot restore physically deleted
  listing payloads. The mandatory dry-run and transaction validation are therefore the
  cleanup rollback boundary.
- Published Jobs remain the recovery source for deleted matching rows; missing-Job
  listing rows remain available for a newly reviewed operator-created detail run. The
  two old detail plans are intentionally unrecoverable audit authority.
- Existing crawl events are retained and may show original page counts that differ from
  the replaced current metrics by explicit product decision.
- Board, Crawl Tasks, and Task Details accept only the explicit terminal tombstone as
  historical read authority. Ordinary missing/mismatched Dispatch Plans still fail
  closed.
