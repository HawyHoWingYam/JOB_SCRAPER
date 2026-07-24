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
