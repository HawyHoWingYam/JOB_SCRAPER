# Task Control Board projections

## Scenario: Server-owned operations Board and Task Details

### 1. Scope / Trigger

Use these contracts whenever a UI needs Crawl Control operations, Automation rows, or one Crawl Task. The backend owns section membership, priority/order, authority, workload, Catalog health, and action capability so clients never reconstruct state from raw payloads or events.

### 2. Signatures

- `GET /api/v1/task-control-board` returns the compatibility V1 projection.
- `GET /api/v1/task-control-board?version=2&source_site=<source>&run_limit=<1..100>` returns Board V2.
- `GET /api/v1/crawl-jobs/tasks/{crawl_job_id}` returns `CrawlTaskDetailProjectionV1`.
- `TaskControlBoardProjectionService.get_v2(selected_source, run_limit)` loads each supported Source independently, then batches events for the combined rows.

### 3. Contracts

- Board V2 always returns summaries for `jobsdb`, `ctgoodjobs`, and `offertoday`; only the selected Source contributes `needs_attention`, `active_runs`, `upcoming`, and `archived_automations`.
- V1 remains the default. V2 must be explicitly requested; do not replace the V1 response model in place.
- Task Detail reuses `build_crawl_task_snapshot` and `build_crawl_control_run_projection` so list, Board, and direct detail agree.
- Manual guidance is bounded and may expose only normalized message/instructions/capabilities. A resumable normalized manual action always supports the baseline `fresh_profile` path; `reuse_open_browser` appears only when explicitly normalized as supported.
- Browser-profile recovery fields are capability-gated: `reset_supported` is
  true only for a JobsDB or CTGoodJobs profile-lock action whose canonical path
  is proven to be the configured fixed profile or a task-owned child and whose
  liveness probe proves the profile dead. Unknown/live liveness or unverified
  ownership stays disabled and exposes the bounded `reset_reason`;
  `profile_scope` distinguishes task-owned temporary profiles from fixed
  reusable-browser profiles.
- `reset_browser_profile` is an active-run action only while the task is
  `manual_action_required`; the Task Details and Board clients route it to the
  crawl-task reset endpoint, never to Automation lifecycle transitions.
- Ordinary projections exclude `request_payload`, raw `manual_action`, cookies, browser state, raw event payloads, and unbounded identifiers.

### 4. Validation & Error Matrix

| Condition | Result |
|---|---|
| unsupported `source_site` | stable 422 control-source error |
| `version` outside 1..2 | FastAPI 422 |
| `run_limit` outside 1..100 | FastAPI 422 |
| unknown Task UUID | 404 `CRAWL_TASK_NOT_FOUND` with the requested ID |
| action is invalid for current status/lifecycle | action remains present with `enabled=false` and a reason code |
| profile lock points outside the configured browser-profile root | Reset is disabled with `profile_ownership_unverified`; do not probe or mutate it |

### 5. Good/Base/Bad Cases

- Good: query each Source with its own `run_limit`, batch event reads, and preserve backend order.
- Base: a legacy run returns `authority_kind=legacy` and null unavailable revisions without inventing them.
- Bad: load one global page and partition it by Source; busy Sources can displace the selected Source.

### 6. Tests Required

- Contract test that V1 stays default and V2 requires `version=2`.
- Assert all three Source queries occur and selected sections contain no cross-Source rows.
- Assert direct Task Detail shares authority/workload values with the dispatched run.
- Assert structured not-found behavior and absence of raw payload/manual-action fields.
- Assert server-declared action truth for active, cancelling, terminal, and manual-action states.
- Assert both JobsDB and CTGoodJobs expose Reset only for owned/configured,
  proven-dead profiles; live, unknown, and unowned paths stay disabled.

### 7. Wrong vs Correct

```python
# Wrong: cross-Source truncation before partitioning.
rows = repo.list_crawl_task_page(source_site=None, page_size=run_limit)

# Correct: the limit applies independently to each Source.
rows = []
for source in SUPPORTED_BOARD_SOURCES:
    source_rows, _ = repo.list_crawl_task_page(
        source_site=source,
        page=1,
        page_size=run_limit,
        status=None,
        crawl_mode=None,
        updated_since=None,
    )
    rows.extend(source_rows)
```

## Scenario: Dismiss one terminal failed-run attention revision

### 1. Scope / Trigger

Use this contract when an operator no longer wants one exact terminal
`crawl.failed` result shown in Board V2 `Needs attention`. This is a Board
acknowledgement only; it is not a crawl lifecycle transition or task deletion.

### 2. Signatures

```http
POST /api/v1/crawl-jobs/{crawl_job_id}/dismiss-failed-attention
Content-Type: application/json

{
  "version": 1,
  "expected_failure_event_sequence": 3
}
```

A `failed_run` `BoardAttentionItemV2` exposes the same positive sequence as
`failure_event_sequence` and advertises `dismiss_failed_run` as a secondary
action. Persistence appends `crawl.failed_attention_dismissed` with the target
sequence and actor `local-operator`.

### 3. Contracts

- Lock the Crawl Job row before inspecting status or events.
- Accept only persisted status `failed` and only the latest `crawl.failed`
  sequence. Repeating the same job/sequence returns the first dismissal with
  `replayed=true` and appends no duplicate event.
- Suppress `failed_run` only when its current failure sequence has a matching
  dismissal. A later failure has a new sequence and appears again.
- The dismissal event is not a lifecycle/progress event. Task snapshots,
  Task Details, Events, Logs, and persisted status continue to project the
  underlying failure.
- This contract is source-neutral for JobsDB, CTGoodJobs, and OfferToday and
  requires no schema migration because it reuses Crawl Job event history.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Crawl Job does not exist | 404 `CRAWL_TASK_NOT_FOUND` |
| Current status is not `failed` | 409 `FAILED_ATTENTION_STATE_INVALID` |
| Expected sequence is not the latest failure | 409 `FAILED_ATTENTION_REVISION_CONFLICT` with current sequence |
| Same failure was already dismissed | 200 with original dismissal sequence and `replayed=true` |
| Later `crawl.failed` follows a dismissal | New failed attention with the later sequence |

### 5. Good / Base / Bad Cases

- **Good:** sequence 3 is dismissed once; Board attention disappears while
  Task Details remains `failed`; sequence 5 later fails and appears again.
- **Base:** a historical failed run without a recoverable failure-event
  sequence remains visible but its Dismiss action is disabled.
- **Bad:** filtering the Crawl Job itself, matching only by task ID, or treating
  the dismissal as the latest lifecycle event hides history or a newer failure.

### 6. Tests Required

- Backend API/projection tests cover action/sequence serialization, successful
  suppression, one-event idempotency and actor payload, preserved Task Details,
  stale revision, non-failed, not-found, and later-failure visibility.
- Snapshot tests prove a dismissal event cannot replace the latest lifecycle
  failure projection.
- Frontend decoder tests require a positive sequence; interaction tests prove
  immediate mutation, server refetch, no dialog, and durable error feedback.

### 7. Wrong vs Correct

```python
# Wrong: acknowledges whichever failure happens to be current at write time.
dismiss_failed_attention(crawl_job_id)

# Correct: fence the write to the revision rendered by the Board.
dismiss_failed_attention(
    crawl_job_id,
    expected_failure_event_sequence=item.failure_event_sequence,
)
```
