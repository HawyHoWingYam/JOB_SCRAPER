# Task Control Board UI

## Scenario: Board routes and normalized Task Details

### 1. Scope / Trigger

Use this composition for `#scheduler` operations and `#crawl-tasks?task=<id>` details. React decodes and renders backend authority; it does not classify rows or inspect raw execution payloads.

### 2. Signatures

- `#scheduler?source=<source>` renders `TaskControlBoardPage`.
- Wizard subroutes under `#scheduler/...` render `TaskControlWizard`.
- `#crawl-tasks?task=<encoded-id>` fetches `/api/v1/crawl-jobs/tasks/{encoded-id}` directly.
- `getTaskControlBoard(source, {signal})` always requests `version=2`.

### 3. Contracts

- Decoders reject malformed required fields before state is committed.
- Board reducers keep prior-good data on refresh failure and ignore stale request versions.
- Board renders backend section membership/order and sends displayed Automation revision or fresh delete-review token with mutations.
- Task Details renders normalized authority, listing/detail workload, immutable pacing, issue/guidance, recovery, actions, and an audit-events link.
- Cancellation uses the shared focus-trapped confirmation dialog, calls the existing helper, and polls at one second while status is `cancelling`; only the backend can report `cancelled`.
- Ordinary UI must not read or render raw `request_payload`, raw `manual_action`, or raw event payloads.

### 4. Validation & Error Matrix

| Condition | UI behavior |
|---|---|
| invalid Board route/source | stable unavailable/normalized route state |
| malformed Board/Task payload | decoder error; do not commit partial data |
| refresh fails after success | retain prior-good view and show stale warning |
| direct Task is unknown | render the structured detail error |
| cancellation request fails | keep dialog/action context and show the error |
| component unmounts or route changes | abort request and clear polling interval |

### 5. Good/Base/Bad Cases

- Good: deep-link a Task that is absent from the current list page and load it directly.
- Base: render an honest legacy authority warning when immutable plan metadata is absent.
- Bad: select the first list row to satisfy a deep link, or reconstruct guidance from raw events.

### 6. Tests Required

- Route encode/decode plus hash back/forward and Source changes.
- Board loading, all-clear, stale prior-good, table/disclosure, lifecycle/CAS, delete review, and dialog focus.
- Direct Task success/not-found, listing/detail/legacy rendering, safe guidance, and raw-payload absence.
- Cancellation confirmation, API failure, one-second polling, terminal behavior, and unmount cleanup.
- Scoped ESLint, focused Vitest, production build, then one complete frontend gate at parent integration.

### 7. Wrong vs Correct

```javascript
// Wrong: derive authority from a list row or raw request payload.
const phase = task.request_payload?.crawl_phase;

// Correct: load and render the normalized single-task projection.
const detail = await getCrawlTaskDetail(taskId, { signal });
renderAuthority(detail.run.authority);
```
