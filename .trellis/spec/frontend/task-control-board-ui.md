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
- JobsDB and CTGoodJobs Task Details use the same normalized recovery panel.
  Fresh Profile is the baseline explicit resume; Reset follows
  `reset_supported`; Open Browser follows helper health; Reuse Open Browser
  follows both helper/session evidence and `reuse_open_browser_supported`.
  The panel never infers availability from raw failure text.
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
| CTGoodJobs profile-lock task | Render capability-gated Reset/Fresh/Open/Reuse controls; do not replace them with an ambiguous generic Resume |

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

## Scenario: Immediate failed-run attention dismissal

### 1. Scope / Trigger

Use this contract only for Board V2 attention items whose backend kind is
`failed_run` and whose backend actions include enabled `dismiss_failed_run`.

### 2. Signatures

```javascript
dismissFailedRunAttention(taskId, expectedFailureEventSequence)
```

The command posts `version: 1` and `expected_failure_event_sequence` to the
crawl-task dismissal endpoint. `decodeBoard` maps the nullable backend field to
`failureEventSequence` and requires any non-null value to be a positive integer.

### 3. Contracts

- Render the label `Dismiss` only from the server-declared action; do not infer
  it from status, source, error text, or item ID.
- Invoke the mutation immediately. Do not open confirmation, Undo, Restore, or
  add the action to Task Details.
- Pass the exact decoded failure sequence and reload Board V2 after success so
  attention cards and Source counts reflect server projection.
- Reuse the Board mutation busy/error surface. A rejected stale revision stays
  visible and must not be hidden optimistically.

### 4. Validation & Error Matrix

| Condition | UI behavior |
|---|---|
| Non-null sequence is zero, negative, fractional, or a string | Decoder rejects the Board payload |
| Dismiss succeeds | Show mutation notice and refetch the Board |
| Dismiss returns structured conflict | Keep the card and show the existing error alert |
| Other attention or active-run kind | No Dismiss action unless the backend explicitly supplies one |

### 5. Good / Base / Bad Cases

- **Good:** click Dismiss on failure sequence 7, call the endpoint once, then
  render the refreshed attention count.
- **Base:** a failed historical item with disabled Dismiss remains readable.
- **Bad:** parse sequence 7 from `item_id`, hide locally before the server
  accepts it, or reuse an old sequence after Board refresh.

### 6. Tests Required

- Decoder tests cover positive sequence, nullable non-failed attention, and
  malformed sequence rejection.
- Board tests cover failed-only label rendering, immediate API arguments,
  refetch without a dialog, and visible mutation failure.
- Run scoped ESLint/Vitest and the full frontend test/build gate.

### 7. Wrong vs Correct

```javascript
// Wrong: local-only hiding can conceal a rejected stale revision.
setAttention(items => items.filter(item => item.entityId !== taskId));

// Correct: fence the mutation and reload the server-owned projection.
await dismissFailedRunAttention(taskId, item.failureEventSequence);
await loadBoard();
```
