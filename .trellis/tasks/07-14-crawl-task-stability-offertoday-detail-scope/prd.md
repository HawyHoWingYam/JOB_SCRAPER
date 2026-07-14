# Stabilize crawl tasks and fix OfferToday detail scope

## Goal

Make durable crawl history stable and truthful: automatic refresh must not
reorder existing task rows, OfferToday detail runs must consume the intended
listing batch (including keyword and hybrid rows), and detail progress must use
distinct job-level counters that remain coherent across IP-block resumes.

## Background

- `CrawlJobRepository.list_crawl_task_page()` currently orders by mutable
  `updated_at DESC`, then `queued_at DESC` and `created_at DESC`
  (`backend/app/repositories/crawl_job_repository.py:379-411`). Metrics updates
  therefore move tasks every ten-second frontend poll
  (`frontend/src/components/scraper/CrawlTasksPage.jsx:322-332`).
- Detail transitions also resync metrics on their source listing jobs
  (`backend/app/services/crawl_job_runtime.py:1340-1364`), so an already
  completed listing task can repeatedly jump above a running detail task.
- OfferToday listing task `4cee200d-9b1b-40ad-88da-8866bacd71a7` discovered
  `9,707` distinct IDs, skipped `2,738` already-complete jobs, and staged
  `6,969` distinct targets. Its current staging state is `1,013 completed` and
  `5,956 pending`; every pending row has `source_classification_id=NULL`.
- Detail task `21436eff-7d0f-4df2-9460-e4ab9d8805e2` used
  `source_listing_crawl_job_id=null` and `category_ids=[118000]`. The resulting
  global category-backlog query filtered on `source_classification_id IN (...)`
  (`backend/app/repositories/crawl_job_listing_repository.py:214-264`) and
  excluded the listing task's keyword/hybrid rows with null classification.
- That detail task froze `1,311` fetch targets plus `95` reconciled IDs, then
  finished with `1,305` distinct successful persists and `6` terminal
  unavailable outcomes after five recoverable IP-block stops. It was not a
  complete detail pass over the `4cee...` listing batch.
- Current metrics mix incompatible units: `detail_target_rows=68` describes the
  final resume cohort, while `detail_run_completed=2464` counts staging rows
  associated with the detail task rather than distinct jobs
  (`backend/app/services/crawl_job_runtime.py:1406-1450`). The task snapshot and
  frontend consequently cannot present a trustworthy ratio.

## Requirements

### R1. Stable crawl-task ordering

- Order task history by immutable queue/creation identity:
  `queued_at DESC`, `created_at DESC`, then `id DESC` as a deterministic
  tie-breaker.
- Auto refresh may update task content and selection, but an existing row must
  not move merely because progress, issue state, or downstream staging metrics
  changed its `updated_at`.
- New tasks appear in the correct immutable chronological position; filters and
  pagination retain deterministic ordering.

### R2. Listing-bound OfferToday detail scope

- A detail run launched for a completed OfferToday listing task must persist and
  honor that task's `source_listing_crawl_job_id`.
- The OfferToday direct-run UI defaults to the newest eligible listing batch
  with remaining detail work. Global category backlog remains available only as
  an explicit operator selection and is labelled as a different scope.
- A listing-bound detail run must not apply category narrowing; all eligible
  current-batch `new` and `repair` staging rows are candidates, including rows
  produced by keyword and hybrid conditions with null
  `source_classification_id`.
- A deliberately unbound category-backlog detail run must retain its existing
  global category filtering behavior.
- Resume dispatch must preserve the original listing-bound scope and must never
  broaden a bound run into global backlog or narrow it to category-only.
- Duplicate historical staging rows for the same canonical OfferToday job must
  not cause duplicate detail fetches.

### R3. Distinct, resume-safe detail progress contract

- User-facing target, fetched, success, terminal, reconciled, failed, and
  remaining counts use distinct canonical `source_job_id` units, never staging
  row counts.
- The original run denominator remains stable across recoverable resumes; a
  resume cohort size is exposed separately if operationally useful and must not
  overwrite the run total.
- Completed targets are not fetched again after IP-block recovery. Five blocked
  attempts followed by successful/terminal retries must not inflate the
  distinct processed count.
- Legacy jobs with existing event history remain readable. When persisted
  metrics are ambiguous, projection may derive trustworthy distinct counters
  from durable cohort/outcome/reconciliation evidence without rewriting old
  events.

### R4. Truthful Crawl Tasks UI

- OfferToday detail rows show a coherent summary equivalent to:
  `Fetched 1,305 / 1,311`, `Terminal 6`, `Reconciled 95`, `Remaining 0` for the
  verified completed task.
- Running and manual-action states show cumulative distinct progress rather than
  only `Queue <resume cohort size>`.
- The task-detail panel exposes the same progress semantics as the list row.
- The snapshot's OfferToday saved count must use the applicable raw
  `metrics.jobs_saved` evidence instead of falling through to an unrelated
  ingest-only counter.
- Existing non-OfferToday metric wording and completed-partial listing display
  remain unchanged unless a shared contract requires an additive field.

### R5. Preserve partial-listing semantics

- Page-cap `retain-and-continue` behavior remains unchanged: capped conditions
  retain validated rows, set `listing_partial=true`, and do not masquerade as an
  IP/WAF/network failure.
- The existing `4cee...` projection remains `IDs 9,707`, `Staged 6,969`,
  `107/152 capped`, and `2,615 / max 3,040` query requests.

## Acceptance Criteria

- [x] Repeated task-page reads return identical task ID order when only
      `updated_at`/metrics change.
- [x] Exact timestamp ties are deterministic through `id DESC`.
- [x] A listing-bound OfferToday detail target query includes eligible null
      classification keyword/hybrid rows and excludes rows from other listing
      batches.
- [x] OfferToday detail mode defaults to the newest eligible listing batch,
      clearly labels that scope, and requires an explicit operator choice to
      switch to global category backlog.
- [x] An unbound category-backlog query still filters to the expanded requested
      category family.
- [x] Resume payloads preserve `source_listing_crawl_job_id` and the same target
      universe.
- [x] Distinct progress tests cover duplicate listing siblings, reconciled jobs,
      success, terminal unavailable, recoverable IP block, and multiple resumes.
- [x] The historical `21436...` snapshot projects `1,311` fetch targets,
      `1,305` successes, `6` terminal outcomes, `95` reconciled IDs, and zero
      remaining without using the `2,464` staging-row count as completed jobs.
- [x] Crawl Tasks frontend tests verify stable-order consumption and detail
      progress chips/panel fields for running, manual-action, and completed
      states.
- [x] Existing partial-listing regression tests remain green and the `4cee...`
      listing metrics retain their corrected meanings.
- [x] Focused backend tests, focused frontend tests, Ruff for touched Python,
      frontend production build, and relevant broader regression suites pass.

## Constraints and Out of Scope

- Preserve unrelated changes in the dirty worktree; task edits and any eventual
  commit must remain narrowly scoped.
- Do not change OfferToday listing depth, query families, response-cursor policy,
  page-cap policy, or supplemental-row policy.
- Do not rewrite historical crawl events merely to repair their projection.
- Do not automatically launch thousands of live OfferToday detail requests as
  part of deterministic code verification. A live repair of the existing
  `4cee...` backlog is an explicit operational step requiring separate runtime
  confirmation after code and selection evidence are reviewed.
