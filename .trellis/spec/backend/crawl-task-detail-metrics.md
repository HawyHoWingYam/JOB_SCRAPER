# Crawl Task Detail Metrics Contract

## Scenario: Versioned cross-source detail snapshots

### 1. Scope / Trigger

Use this contract when changing JobsDB, CTGoodJobs, or OfferToday detail
selection/outcomes, Crawl Task snapshots, Task Control Board projections, or
frontend metric labels. The backend owns normalization; consumers never combine
raw events, mutable request payloads, staging-row counters, or live backlog
queries into their own denominator.

### 2. Signatures

`build_crawl_task_snapshot(...)` emits these flat compatibility projections:

```text
detail_target_count
detail_fetched_count
detail_saved_count
detail_failed_count
detail_unavailable_count
detail_manual_action_count
detail_remaining_count
detail_run_cap
detail_snapshot_cutoff_at
detail_snapshot_target_count
detail_snapshot_fetched_count
detail_snapshot_failed_count
detail_snapshot_unavailable_count
detail_snapshot_manual_action_count
detail_snapshot_remaining_count
detail_live_future_eligible_count
```

Versioned Crawl Tasks and `GET /api/v1/task-control-board` also expose:

```python
DetailSnapshotProjectionV1(
    backlog_scope=...,
    limit_kind="entire_snapshot|stop_after|legacy",
    cutoff_at=...,
    target_count=...,
    fetched_count=...,
    saved_count=...,
    failed_count=...,
    unavailable_count=...,
    manual_action_count=...,
    remaining_count=...,
    future_eligible_count=...,
    detail_run_cap=...,
)
```

### 3. Contracts

#### Versioned finite denominator

When `detail_snapshot_cutoff_at`/Dispatch Plan authority exists:

```text
target       = frozen selected canonical source_job_id count
fetched      = successful frozen targets
saved        = successfully persisted Jobs (subset of fetched)
failed       = settled failed frozen targets
unavailable  = settled terminal-unavailable frozen targets
manual       = unresolved frozen targets waiting for operator action
remaining    = unresolved frozen targets, including manual-action work
future       = currently eligible canonical IDs outside the frozen plan
run cap      = reviewed complete-run cap, never a Recovery Segment size
```

Immutable plan content owns backlog scope, limit kind, cutoff, target count,
and run cap. Mutable runtime metrics may update outcomes and the separately
queried future count but cannot replace those authority fields. Every count is
in distinct canonical `source_job_id` units even when one target owns several
staging rows.

`remaining_count` and `future_eligible_count` describe different sets. Do not
add them, use future work to keep the current task running, or present future
work as failure to complete the reviewed plan.

#### Legacy fallback

Historical OfferToday cohorts may use the distinct-event projection; historical
JobsDB/CTGoodJobs tasks may use detail-run transitions:

```text
OfferToday target/fetched/failed/unavailable/remaining
  = detail_distinct_* fields

JobsDB/CTGoodJobs target      = detail_target_rows
JobsDB/CTGoodJobs fetched     = detail_run_completed
JobsDB/CTGoodJobs saved       = max(jobs_saved, detail_run_completed)
JobsDB/CTGoodJobs failed      = detail_run_failed
JobsDB/CTGoodJobs unavailable = detail_run_terminal_unavailable
JobsDB/CTGoodJobs manual      = detail_run_manual_action_required
```

This fallback is read compatibility only. New versioned paths cannot author
primitive `detail_limit`, dynamically grow a cohort, or reconstruct authority
from these fields.

The UI always renders the ordered common core, including zeros:

```text
Detail targets | Fetched | Saved | Failed | Remaining in snapshot
```

Nonzero `Unavailable` and `Manual action` follow. `Future eligible` is a
separate value and must be labeled as later-run work.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Versioned snapshot has mutable target/cap metrics | Ignore them; use plan authority |
| Duplicate staging siblings | One canonical target/outcome |
| Manual-action target | Included in snapshot remaining; excluded from failed |
| Terminal-unavailable target | Excluded from remaining and failed |
| Future row appears after cutoff | Increment future only; do not change target/remaining |
| Finite plan completes with future work | Current run may complete; future stays for a later plan |
| Zero values | Numeric zero fields and visible zero labels |
| Historic task lacks snapshot authority | Use one bounded source-specific fallback only |
| Frontend receives raw request/event fields | Ignore them; render normalized projections |

### 5. Good / Base / Bad Cases

- **Good:** `targets=10 fetched=3 failed=2 unavailable=1 manual=1` projects
  `remaining=4`, while `future=27` remains visibly separate and does not change
  the ten-target denominator.
- **Base:** An empty blocked review displays zero selected targets and cannot be
  dispatched.
- **Bad:** A component displays `remaining=31` by adding four frozen remaining
  targets to 27 future targets.
- **Bad:** Runtime reports `detail_run_cap=999`, overriding the reviewed plan
  cap of 10 in history.

### 6. Tests Required

- `backend/tests/test_crawl_task_snapshot_service.py`: versioned authority
  precedence, common conservation, numeric zeros, future/snapshot separation,
  cancellation/recovery, and bounded historical fallback.
- `backend/tests/test_crawl_control_api.py`: Crawl Tasks and Board return the
  same `DetailSnapshotProjectionV1`; mutable target/cap metrics cannot alter
  frozen plan content; raw request/events are absent from board projections.
- `backend/tests/test_dispatch_plan_service.py`: canonical target/sibling-row
  membership, cap/cutoff/fingerprint, exact claims, future work, and rollback.
- Frontend Crawl Tasks/Task Details tests assert exact common ordering, visible
  zeros, separate future work, and no raw-payload parsing.
- Run focused/full backend tests, frontend tests, and the production build.

### 7. Wrong vs Correct

#### Wrong

```jsx
const remaining = task.detail_completed
  ? task.detail_target_count - task.detail_completed
  : task.detail_backlog_remaining;
```

This mixes staging-row, frozen-plan, and live-backlog denominators.

#### Correct

```jsx
const remaining = Number(task.detail_snapshot?.remaining_count ?? 0);
const future = Number(task.detail_snapshot?.future_eligible_count ?? 0);
```

The backend projection owns normalization; rendering keeps current-run and
later-run work distinct.

## Scenario: Completed listing with per-Query-Target page-depth caps

### 1. Scope / Trigger

Use this contract when a listing run finishes `completed` after one or more
Query Targets hit the per-target page-depth limit, or when Task Control exposes
the reviewed continuation path for those targets. The global run page cap is a
separate ceiling and must not be described as a per-target cap.

### 2. Signatures

`build_crawl_task_snapshot(...)` preserves the runner's source-qualified
`listing_capped_classification_ids` as an ordered, deduplicated tuple. A
completed listing detail may expose:

```python
ListingRecoveryProjectionV1(
    version=1,
    listing_partial=...,
    query_target_count=...,
    capped_query_target_count=...,
    page_depth=...,
    pages_requested=...,
    capped_classification_ids=(...),
    continuation_supported=...,
)
```

### 3. Contracts

- `listing_partial=true` means at least one condition was retained at the
  configured per-Query-Target `page_depth`; the run may still be `completed`.
- `capped_classification_ids` are immutable source-qualified Query Target
  classification IDs, never display labels or reconstructed category names.
- `capped_query_target_count` is bounded by `query_target_count`; IDs are
  bounded by that count and preserve runtime-plan order.
- `listing_workload.run_page_cap` remains the whole-run ceiling. It is shown
  separately from `pages_requested` and is never used to invent capped target
  IDs.
- `listing_recovery` is `null` unless the normalized run status is `completed`,
  the crawl phase is `listing`, and `listing_partial=true`. Historical runs
  without IDs are readable but cannot advertise continuation.
- `continuation_supported=true` only when the partial run has recorded target
  IDs for a supported source. The UI creates a reviewed one-off draft; it does
  not dispatch or bypass confirmation.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Non-completed, cancelled, failed, or manual-action listing | `listing_recovery=null`; preserve the terminal/actionable status |
| Natural listing completion with no cap | `listing_partial=false`; no continuation action |
| Per-target page-depth cap with retained rows | `completed`, partial warning, capped count/IDs, reviewed continuation available when IDs exist |
| Global run page cap reached | Do not classify as per-target partial; retain the run-cap metric/reason and block continuation from invented IDs |
| Capped ID count exceeds target count | Reject the versioned projection |
| Historical payload lacks immutable target IDs | Render partial history if present, but `continuation_supported=false` |
| Capped IDs are absent or do not match the run's source prefix | Preserve the diagnostic IDs, but set `continuation_supported=false` |

### 5. Good / Base / Bad Cases

- **Good:** `23` targets, depth `40`, `408` pages requested, and `5` ordered
  source-qualified IDs produce `Completed with partial listing`; the UI says
  `5 of 23 query targets reached the page-depth limit` and offers a reviewed
  continuation draft for those five IDs.
- **Base:** A natural `23`-target run shows `Pages requested 408/920` (or its
  normalized values) and no partial warning or continuation button.
- **Bad:** A cancelled run with a stale `listing_partial` flag is labelled
  completed, or a global `run_page_cap` stop is counted as capped Query Targets.

### 6. Tests Required

- `backend/tests/test_crawl_task_snapshot_service.py`: preserve and deduplicate
  capped IDs, project counts/depth/pages, expose continuation only for a
  completed listing, and reject invalid projection shapes.
- `backend/tests/test_crawl_control_api.py`: serialize the nullable
  `listing_recovery` field without exposing raw request/events.
- Frontend Crawl Tasks tests: exact partial wording and page denominators,
  terminal-status regression (cancelled/failed), decoder field parity, and the
  reviewed draft containing only capped source-qualified IDs.
- Runner tests: per-target `page_cap` and whole-run `run_page_cap` remain
  distinguishable and only the former emits continuation IDs.

### 7. Wrong vs Correct

#### Wrong

```jsx
const partial = task.listing_partial;
const capped = task.listing_capped_condition_count;
// Label every partial flag as completed, including cancellation or run-cap stops.
```

#### Correct

```jsx
const isCompletedListing =
  run.status === "completed" && run.phase === "listing";
const showPartial = isCompletedListing && recovery?.listingPartial;
const runCap = run.listingWorkload?.run_page_cap;
```

Only the normalized completed-listing projection drives the warning and
continuation action; the run cap remains visible as an independent workload
limit.
