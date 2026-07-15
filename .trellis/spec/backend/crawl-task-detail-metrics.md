# Crawl Task Detail Metrics Contract

## Scenario: Cross-source normalized detail metrics

### 1. Scope / Trigger

Use this contract when adding or changing CTGoodJobs, JobsDB, or OfferToday
detail status transitions, crawl-task snapshots, or Crawl Tasks metric labels.
The snapshot service owns normalization so UI consumers do not reinterpret raw
event and listing-batch counters independently.

### 2. Signatures

`build_crawl_task_snapshot(...)` emits these additive numeric fields:

```text
detail_target_count
detail_fetched_count
detail_saved_count
detail_failed_count
detail_unavailable_count
detail_manual_action_count
detail_remaining_count
```

Existing source/raw fields remain available for compatibility.

### 3. Contracts

For OfferToday, prefer distinct frozen-cohort fields:

```text
target      = detail_distinct_target_total
fetched     = detail_distinct_succeeded
failed      = detail_distinct_failed
unavailable = detail_distinct_terminal_unavailable
remaining   = detail_distinct_remaining
saved       = jobs_saved
```

For CTGoodJobs and JobsDB, use detail-run transitions:

```text
target      = detail_target_rows
fetched     = detail_run_completed
saved       = max(jobs_saved, detail_run_completed)
failed      = detail_run_failed
unavailable = detail_run_terminal_unavailable
manual      = detail_run_manual_action_required
remaining   = max(target - fetched - failed - unavailable, 0)
```

Manual action remains included in remaining work; it explains why some work is
blocked and is not an additive settled outcome. Saved is a subset of successful
work, not part of denominator conservation. Reconciled/skipped rows are outside
the selected target denominator and must not be subtracted twice.

The frontend always renders the ordered common core, including zeros:

```text
Detail targets | Fetched | Saved | Failed | Remaining
```

Nonzero `Unavailable` and `Manual action` follow. OfferToday may additionally
render real segment and backlog metrics; other sources must not synthesize them.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Running CTGoodJobs/JobsDB task | Live run transitions populate common fields |
| Frozen OfferToday cohort | Distinct IDs define target/outcome counts |
| Manual-action target | Included in remaining; excluded from failed |
| Terminal-unavailable target | Excluded from remaining and failed |
| Zero values | Numeric zero fields and visible zero labels |
| Historic missing run counters | Bounded legacy fallback; never mix batch and run denominators |

### 5. Good / Base / Bad Cases

- **Good:** `targets=10 fetched=3 failed=2 unavailable=1 manual=1` projects
  `remaining=4`; manual is one reason among those four unresolved targets.
- **Base:** An empty detail task displays five zero-valued core metrics.
- **Bad:** Using listing-batch `detail_completed` with a current-run target count
  can produce negative or inflated remaining work.
- **Bad:** The JSX component falls back through raw event fields, creating a
  second normalization implementation that drifts from the API.

### 6. Tests Required

- `backend/tests/test_crawl_task_snapshot_service.py` covers generic run
  conservation, numeric zero fields, historic fallback, and OfferToday distinct
  cohort projection.
- `frontend/src/components/scraper/CrawlTasksPage.test.jsx` asserts exact common
  ordering, visible zeros, separate outcome labels, and OfferToday-only extras.
- Run focused/full backend tests, frontend full tests, and the production build.

### 7. Wrong vs Correct

#### Wrong

```jsx
const fetched = task.detail_completed - task.detail_reconciled_rows;
```

#### Correct

```jsx
const fetched = Number(task.detail_fetched_count ?? 0);
```

Raw-source compatibility belongs in `build_crawl_task_snapshot`; rendering code
formats the normalized contract only.
