# Design: OfferToday global detail backlog recovery

## 1. Problem boundary

The current detail flow conflates three different concepts:

1. a listing batch inventory (`8,035 staged` rows);
2. a category-filtered global query (`category_ids=[118000]`); and
3. the detail targets fetched by one capped execution segment.

When the operator leaves Listing Batch Scope empty, the desired contract is a
source-wide OfferToday recovery. The implementation must therefore include
unclassified staging rows, preserve the real OfferToday job function during
detail persistence, continue successful segments, and stop truthfully on
manual action or retryable failure.

The smallest mechanism is an explicit scope field plus a
same-crawl-job segment loop. No new database table, listing algorithm change,
or historical-event rewrite is required.

## 2. Durable scope contract

### 2.1 Request payload

Add an additive `detail_scope` request field:

```text
global        source-wide OfferToday detail backlog
listing_batch one explicit source_listing_crawl_job_id
```

New direct detail requests set:

```json
{
  "crawl_phase": "detail",
  "detail_scope": "global",
  "source_listing_crawl_job_id": null,
  "detail_statuses": ["pending", "failed", "manual_action_required"],
  "detail_limit": 5000
}
```

When a batch is selected, `detail_scope` is `listing_batch` and the batch ID
is required. Resume dispatch copies both fields from the persisted request;
it must not recompute scope from the newest batch or replace the original
batch ID.

If an old detail payload has no `detail_scope`, normalize it to
`listing_batch` when a batch ID is present, otherwise to `global`. Preserving
the old category-filtered interpretation is explicitly out of scope; the
implementation should not grow a legacy-only category branch.

### 2.2 Candidate query

Keep the existing repository ownership and canonical grouping:

```text
scope=listing_batch -> crawl_job_id = selected batch; no category predicate
scope=global        -> source_site = offertoday; no category predicate
```

Both scopes apply the configured eligible detail statuses and the existing
OfferToday terminal/identity-conflict sibling blocker. Group rows by canonical
`source_job_id` before applying `detail_limit`.

The existing `resolve_offertoday_detail_category_ids()` boundary should accept
the resolved scope. It returns no category restriction for either a bound
batch or a global scope. Category IDs from the detail form are not a second
global filter; they remain listing-phase input only.

## 3. Classification preservation

Global selection changes which staging rows are eligible; it does not assign a
classification to the published Job.

The existing detail path remains authoritative:

```text
listing_payload + detail_payload
        -> build_offertoday_canonical_job()
        -> build_offertoday_job_data()
        -> JobRepository.upsert_source_job()
```

`OfferTodayDetailPipeline._build_canonical_payload()` already merges listing
and detail raw data (`backend/app/services/offertoday_detail_pipeline.py:450-462`).
`build_offertoday_canonical_job()` derives the first `job_functions` code/name
(`backend/app/sources/contracts.py:183-266`). Therefore a staging row whose
database classification column is `NULL` can still publish as its actual
OfferToday category, including non-IT categories. If both payloads lack
`job_functions`, the published classification remains `NULL`; the crawler must
not invent an IT or global category.

Add a regression at the canonical/pipeline boundary and one runtime fixture
with a null staging classification plus non-IT `job_functions`.

## 4. Same-task continuation controller

### 4.1 Segment lifecycle

Keep one durable `crawl_job_id` and run the existing detail pipeline in bounded
segments. Refactor the current `_run_detail_phase()` so it can execute one
segment without marking the crawl completed; an outer controller owns final
task state.

For each segment:

1. load all eligible candidate groups using the resolved scope;
2. reconcile complete OfferToday Jobs as today;
3. slice distinct fetch targets to `detail_limit`;
4. freeze one segment event with its ID hash and counts;
5. process the segment through the existing identity/retry/persistence
   pipeline;
6. refresh cumulative metrics and current remaining-backlog counts; and
7. decide whether to continue, pause, fail, or complete.

The existing loader currently queries without a repository limit, groups rows,
then slices targets at `targets[:detail_limit]`
(`backend/app/services/crawl_job_runtime.py:761-984`). Expose the pre-slice
eligible distinct target count so the controller can distinguish “exactly at
the cap; more work may exist” from “the backlog is exhausted.”

### 4.2 Stop/continue rules

```text
manual_action / IP / WAF stop -> persist progress; status manual_action_required
any retryable failed target  -> persist progress; status failed; no auto-loop
segment target count == 0    -> status completed
segment target count < limit -> status completed, if no failed target remains
segment target count == limit -> load the next segment, if all outcomes settled
```

Success, terminal-unavailable, reconciliation, and identity-conflict outcomes
must be accounted for before the next segment. Completed/terminal rows are
already excluded by status, so the next load naturally advances without
re-fetching them. A segment containing a retryable failure must not immediately
select that same failed row forever; it stops the task and leaves the row
eligible for a later operator-triggered recovery.

The current manual-action path remains authoritative: detail IP/WAF responses
call `mark_manual_action_required()` and return before later targets. Resume
uses the persisted global/bound scope and original statuses, then re-enters the
segment controller. It never marks the task completed merely because one
resume cohort was exhausted.

### 4.3 Events and metrics

Keep the current event names needed by active projection consumers and add
segment metadata; historical event compatibility is not a goal:

```text
crawl.detail_cohort_frozen
  detail_scope
  segment_index
  segment_target_rows
  eligible_distinct_rows_before_segment
  continuation=true|false

metrics
  detail_scope
  detail_segment_index
  detail_segments_completed
  detail_segment_target_rows
  detail_backlog_pending
  detail_backlog_failed
  detail_backlog_manual_action_required
  detail_backlog_remaining
  detail_continuation_state
```

`detail_run_completed` remains a legacy staging-row metric and is never used
as a job count. Existing distinct event projection remains valid for the
success/terminal/failed/reconciled sets; the new backlog fields explicitly
describe current eligible work and segment state.

The final `crawl.completed` event is emitted only by the outer controller after
an empty eligible query. Manual action emits the existing manual-action event;
retryable segment failure emits `crawl.failed` with the remaining breakdown.

## 5. Frontend behavior

### 5.1 Direct detail form

Remove the effect that auto-selects `findNewestEligibleListingBatch()`
(`frontend/src/components/scraper/ScheduleManager.jsx:839-858`). Initialize
detail scope empty and submit `detail_scope=global` when the selector is empty.

Keep the batch selector as an advanced control with an explicit label such as
`Listing Batch Scope (advanced)`. Its empty option should say
`Global OfferToday backlog (default)`.

Detail-mode sector checkboxes must not imply a narrower global scope. They can
be hidden for detail mode or clearly marked as listing-only; listing mode keeps
its current category selection behavior. A selected batch remains the only
detail scope that narrows to a historical listing run.

### 5.2 Progress display

Add source-aware global/bound scope wording and show the segment/backlog split:

```text
Segment: 5,000 fetched
Global backlog remaining: 12,431
Failed: 0
```

Manual-action and failed states show the preserved cumulative progress and the
remaining eligible breakdown. Existing non-OfferToday and legacy snapshots
keep their current fallback labels.

### 5.3 Helper/browser recovery boundary

The recovery UI has two independent dependencies:

```text
worker reuse strategy -> live browser registry + CDP attach
Open Browser action   -> host manual-action helper + browser launcher
```

The worker-side `reuse_open_browser` failure must not disable or mislabel the
host helper action. The helper capability endpoint should report actual health
or a clearly provisional configured state, and the frontend action should
surface the helper URL, health failure, and retry/manual-start guidance. While
the helper is unreachable, `Open Browser` is disabled and a health retry plus
copyable manual-start instruction remains visible; health recovery re-enables
the action.

The frontend cannot start the host helper when it is offline. The capability
response should therefore provide the configured helper URL, health URL, and a
copyable manual-start command. The UI performs a real health check, shows
`Helper offline`, disables `Open Browser`, and offers Retry until the helper is
reachable. No resident launcher, host-process control endpoint, or automatic
startup is part of this task. Starting/opening the browser never implicitly
resumes the crawl; resume remains an explicit operator action.

`Resume Fresh` is independent of this helper boundary and remains enabled when
the helper is offline. Its own headed/browser-runtime capability and launch
errors are reported separately.

## 6. Compatibility and operational boundaries

- No schema migration: `detail_scope` and continuation counters live in JSON
  request/metric/event payloads.
- Historical event/task readability and old category-filtered semantics are
  not compatibility goals for this rollout.
- Explicit bound-run identity, terminal, retry, and resume behavior remains
  unchanged except for the additive scope preservation.
- Do not launch the live 8,000+ row recovery during deterministic verification.
- Do not require a live OfferToday browser or helper process for deterministic
  tests; use health, launch, and transport-failure fakes.
- Do not change listing pagination, search families, cursor policy, or
  supplemental-row handling.
- Preserve unrelated dirty worktree files.

## 7. Rollback shape

The changes are independently reversible by layer:

1. revert the UI default/scope payload;
2. revert global candidate scope resolution;
3. disable the continuation controller while retaining one-segment behavior;
4. retain additive snapshot fields as harmless compatibility fields.

No data rollback is required because detail transitions and job upserts remain
transactional and historical events are append-only.
