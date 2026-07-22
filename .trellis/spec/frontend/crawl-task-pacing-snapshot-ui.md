# Crawl Task Pacing Snapshot UI Contract

## Scenario: Explain finite detail snapshots, pacing, and cancellation state

### 1. Scope / Trigger

Use this contract in Crawl Tasks and Task Details when rendering versioned
detail history or changing Cancel/Resume behavior. The UI consumes normalized
backend projections; it never reconstructs detail authority, progress, or
pacing from raw request/event payloads.

### 2. Signatures

```text
CrawlTaskListItem.detail_pacing: DetailPacingConfig | null
CrawlTaskListItem.detail_snapshot: DetailSnapshotProjectionV1 | null
CrawlTaskListItem.status: ... | cancelling | cancelled

DetailSnapshotProjectionV1 {
  version: 1
  backlog_scope
  limit_kind: "entire_snapshot" | "stop_after" | "legacy"
  cutoff_at
  target_count
  fetched_count
  saved_count
  failed_count
  unavailable_count
  manual_action_count
  remaining_count
  future_eligible_count
  detail_run_cap
}
```

```jsx
<DetailPacingCard task={selectedTask} />
```

### 3. Contracts

- Render Detail Pacing only when the normalized requested crawl phase is
  `detail`. Listing tasks never render it.
- A non-null `detail_pacing` snapshot shows exactly random interval, burst
  attempts, and burst pause. Null means `Not recorded`; never substitute the
  current global setting.
- A non-null `detail_snapshot` owns the current run's frozen scope, cutoff,
  target denominator, outcomes, remaining work, limit kind, and complete-run
  cap. Render these normalized fields directly; do not derive them from raw
  request payloads, events, staging-row counters, or live backlog fields.
- Label `remaining_count` as work remaining in this snapshot. Show
  `future_eligible_count`, when nonzero, separately as work eligible for a later
  run. Never add or substitute the two values.
- A Recovery Segment and pacing `burst_size` only partition the frozen target
  order. Neither is the task's `detail_run_cap`, and neither may imply that the
  current run can absorb later-eligible work.
- Do not render a countdown, current wait, cumulative attempt position, or any
  mutable runtime pacing counter.
- `cancelling` is an active pending-shutdown state. Show the pending banner,
  disable repeated Cancel, hide Resume, and poll task snapshots every second
  until the backend reports `cancelled`.
- Terminal tasks expose no Cancel. Manual-action Resume is available only when
  the backend state and recovery contract allow it.

### 4. Validation & Error Matrix

| Snapshot/state | UI result |
|---|---|
| detail + valid pacing | show three formatted values |
| detail + null pacing | show `Not recorded` |
| versioned finite snapshot | show normalized target/outcome/remaining values and reviewed run cap |
| remaining and future are both nonzero | label them as current-snapshot and later-run work; do not total them |
| Recovery Segment or burst metadata is present | render as pacing only; never as run cap or denominator |
| raw request/events disagree with normalized fields | ignore raw data and render the normalized projection |
| listing + any pacing value | no pacing card |
| cancelling | pending-stop banner, disabled Cancel, no Resume, 1-second poll |
| cancelled/completed/failed | no Cancel |
| malformed backend pacing | backend projects null; UI shows historical wording |

### 5. Good / Base / Bad Cases

- **Good:** A detail task displays `1-3 seconds`, `20 attempts`, and `30
  seconds`, matching its immutable startup snapshot. It separately displays
  `4 remaining in snapshot` and `27 eligible for a later run`.
- **Base:** A historical detail task displays `Not recorded` and no guessed
  values.
- **Bad:** The component reads `request_payload.detail_pacing` directly and
  accidentally shows a listing task's malformed pacing object.
- **Bad:** The component adds snapshot remaining to future eligible or labels a
  20-attempt burst as the complete-run cap.

### 6. Tests Required

- Backend snapshot tests cover valid, missing, malformed, and listing-excluded
  pacing projection, immutable plan-authority precedence, and snapshot/future
  separation.
- Crawl Tasks tests cover exact values, historical wording, listing omission,
  absence of runtime counters, normalized detail fields, Recovery Segment/run
  cap distinction, cancelling polling/actions, and terminal actions.
- Contract tests prove the UI does not read raw request/event payloads.
- Run focused backend/frontend contract tests and the production frontend build;
  run complete suites once at the final integration gate.

### 7. Wrong vs Correct

#### Wrong

```jsx
const pacing = task.request_payload?.detail_pacing || currentGlobalPacing;
const remaining =
  task.detail_target_count - task.metrics.detail_run_completed;
const totalBacklog = remaining + task.detail_live_future_eligible_count;
```

This bypasses backend validation and rewrites history with mutable settings.

#### Correct

```jsx
if (task.crawl_phase !== "detail") return null;
const pacing = task.detail_pacing;
const remaining = Number(task.detail_snapshot?.remaining_count ?? 0);
const future = Number(task.detail_snapshot?.future_eligible_count ?? 0);
const runCap = task.detail_snapshot?.detail_run_cap;
```

The explicit API projections remain the only display contract, including null
for historical or invalid snapshots. Frozen-run and later-run work remain
separate.

## Scenario: Explain a completed partial listing and continue capped targets

### 1. Scope / Trigger

Use this contract for Crawl Tasks listing rows and normalized Task Details when
the backend reports retained results after per-Query-Target page-depth caps.
This is a listing-completeness warning, not a generic failed/cancelled status.

### 2. Signatures

```text
listing_recovery: ListingRecoveryProjectionV1 | null
  listing_partial: boolean
  query_target_count: non-negative integer
  capped_query_target_count: non-negative integer
  page_depth: non-negative integer
  pages_requested: non-negative integer
  capped_classification_ids: string[]
  continuation_supported: boolean
```

### 3. Contracts

- Show `Completed with partial listing` only when the normalized run is
  `status=completed`, `phase=listing`, and `listing_partial=true`.
- Keep `run_page_cap` separate from `pages_requested / estimated_max_pages`;
  do not imply that the whole-run cap was reached when Query Targets hit depth.
- Show the capped count, total Query Target count, page depth, and requested
  pages in Task Details. Keep existing source, phase, and authority context.
- A continuation button is rendered only for `continuation_supported=true`.
  Clicking it writes a reviewed Task Control one-off draft containing only the
  recorded source-qualified classification IDs and navigates to review; it
  never dispatches directly.
- Missing IDs, cancelled/failed/manual-action runs, or natural completion show
  no continuation action. Technical IDs remain available through normalized
  authority/details, not as a misleading primary status.

### 4. Validation & Error Matrix

| State | UI result |
|---|---|
| Completed listing + per-target partial | Partial status, count/depth warning, optional reviewed continuation |
| Completed listing + natural exhaustion | Normal `Completed`; no partial warning/button |
| Cancelled/failed/manual-action with stale partial metrics | Preserve terminal/actionable status; no completed-partial label or style |
| `continuation_supported=false` | Explain that target IDs are unavailable; no direct action |
| Run page cap shown in workload | Render as independent ceiling; never convert to capped target count |

### 5. Good / Base / Bad Cases

- **Good:** The list reads `Completed with partial listing`, `5 of 23 query
  targets reached the page-depth limit`, and `Pages requested 408/920`; detail
  shows `Run page cap 1,000` separately and the draft contains only capped IDs.
- **Base:** A natural listing remains `Completed` with ordinary page metrics.
- **Bad:** A cancelled listing gets yellow partial styling or a continuation
  button merely because its legacy snapshot retained `listing_partial=true`.

### 6. Tests Required

- Crawl Tasks list/detail tests assert exact status text, page metrics, and
  terminal-status regression.
- Decoder/fixture tests assert snake_case to camelCase parity for every
  `listing_recovery` field and nullable historical behavior.
- Draft tests assert review routing, exact capped-ID rules, and no dispatch API
  call when the button is clicked.
- Run focused/full frontend tests, lint, and production build.

### 7. Wrong vs Correct

#### Wrong

```jsx
const label = recovery?.listingPartial
  ? "Completed with partial listing"
  : run.status;
```

#### Correct

```jsx
const label =
  run.status === "completed" && run.phase === "listing" && recovery?.listingPartial
    ? "Completed with partial listing"
    : run.status;
```

Status and continuation are terminal-state aware; the normalized projection,
not raw event flags, remains the UI authority.
