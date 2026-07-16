# Crawl Task Pacing Snapshot UI Contract

## Scenario: Explain effective detail pacing and cancellation state

### 1. Scope / Trigger

Use this contract in Crawl Tasks when rendering manual detail task history or
changing Cancel/Resume behavior. The UI consumes the normalized task snapshot;
it does not parse pacing out of the raw request payload.

### 2. Signatures

```text
CrawlTaskListItem.detail_pacing: DetailPacingConfig | null
CrawlTaskListItem.status: ... | cancelling | cancelled
```

```jsx
<DetailPacingCard task={selectedTask} />
```

### 3. Contracts

- Render Detail Pacing only when the normalized requested crawl phase is
  `detail`. Listing tasks never render it.
- A non-null snapshot shows exactly random interval, burst attempts, and burst
  pause. Null means `Not recorded`; never substitute the current global setting.
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
| listing + any pacing value | no pacing card |
| cancelling | pending-stop banner, disabled Cancel, no Resume, 1-second poll |
| cancelled/completed/failed | no Cancel |
| malformed backend pacing | backend projects null; UI shows historical wording |

### 5. Good / Base / Bad Cases

- **Good:** A detail task displays `1-3 seconds`, `20 attempts`, and `30
  seconds`, matching its immutable startup snapshot.
- **Base:** A historical detail task displays `Not recorded` and no guessed
  values.
- **Bad:** The component reads `request_payload.detail_pacing` directly and
  accidentally shows a listing task's malformed pacing object.

### 6. Tests Required

- Backend snapshot tests cover valid, missing, malformed, and listing-excluded
  pacing projection.
- Crawl Tasks tests cover exact values, historical wording, listing omission,
  absence of runtime counters, cancelling polling/actions, and terminal actions.
- Run the full backend/frontend suites and the production frontend build.

### 7. Wrong vs Correct

#### Wrong

```jsx
const pacing = task.request_payload?.detail_pacing || currentGlobalPacing;
```

This bypasses backend validation and rewrites history with mutable settings.

#### Correct

```jsx
if (resolveRequestedCrawlPhase(task) !== "detail") return null;
const pacing = task.detail_pacing;
```

The explicit API projection remains the only display contract, including null
for historical or invalid snapshots.
