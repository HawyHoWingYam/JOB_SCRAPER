# Task Control Board and Task Details UI design

## Feature boundary

```text
frontend/src/features/taskControl/
  shared/                         # reuse Wizard-owned seams
  board/
    TaskControlBoardPage.jsx
    boardApi.js
    boardDecoders.js
    boardReducer.js
    BoardSourceTabs.jsx
    AttentionSection.jsx
    ActiveRunsSection.jsx
    AutomationTable.jsx
    AutomationRowDetails.jsx
    AutomationActions.jsx
    TaskControlBoardPage.test.jsx
    boardReducer.test.js

frontend/src/components/scraper/
  CrawlTasksPage.jsx
  CrawlTaskDetails.jsx
  CrawlTaskAuthority.jsx
  CrawlTaskWorkload.jsx
  ManualActionRecoveryPanel.jsx

backend/app/crawl_control/
  task_control_board_contracts.py
  task_control_board_service.py
backend/app/api/crawl_control.py
backend/app/api/crawl_jobs.py
backend/app/schemas/crawl_job.py
```

Board owns operational read composition and ordinary Automation lifecycle
actions. Wizard owns authoring/Edit/Run-now review. Governance owns Catalog
mutation. Task Details remains under the existing Crawl Tasks top-level view so
history has one durable home.

## Backend Board V2 contract

### Source summary

```python
class BoardSourceSummaryV2(FrozenContract):
    source_site: SourceSite
    state: Literal["attention", "running", "all_clear"]
    attention_count: int
    active_run_count: int
    upcoming_count: int
    catalog_health: CatalogHealthProjectionV1
```

State priority is backend-owned: attention wins over running; running wins over
all clear. All three supported Sources are always present in stable product
order.

### Actions

```python
class BoardActionV1(FrozenContract):
    action: Literal[
        "view_task", "view_logs", "open_catalog", "edit", "run_now",
        "pause", "resume", "archive", "restore", "delete_review",
        "cancel", "resume_manual_action"
    ]
    enabled: bool
    reason_code: str | None
```

Action capability derives from backend lifecycle/status/readiness and is not a
security boundary. Mutations still revalidate revision/state.

### Attention and active/upcoming sections

```python
class BoardAttentionItemV2(FrozenContract):
    item_id: str
    kind: Literal[
        "manual_action", "cancelling", "scope_review_required",
        "catalog_unpublished", "catalog_stale", "worker_unavailable",
        "failed_run", "overdue_automation"
    ]
    priority: int
    source_site: SourceSite
    code: str
    title: str
    summary: str
    entity_kind: Literal["run", "automation", "catalog"]
    entity_id: str
    primary_action: BoardActionV1
    secondary_actions: tuple[BoardActionV1, ...]

class BoardActiveRunV2(FrozenContract):
    run: CrawlControlRunProjectionV1
    issue: CrawlTaskIssueProjectionV1 | None
    actions: tuple[BoardActionV1, ...]

class AutomationRowProjectionV2(FrozenContract):
    # V1 identity/lifecycle/scope/timestamps plus:
    schedule: AutomationScheduleProjectionV1
    latest_outcome: AutomationLatestOutcomeV1 | None
    catalog_health: CatalogHealthProjectionV1
    resolved_scope_summary: ResolvedScopeSummaryV1 | None
    current_run: CrawlControlRunProjectionV1 | None
    actions: tuple[BoardActionV1, ...]
```

```python
class TaskControlBoardProjectionV2(FrozenContract):
    version: Literal[2] = 2
    selected_source: SourceSite
    source_summaries: tuple[BoardSourceSummaryV2, ...]
    needs_attention: tuple[BoardAttentionItemV2, ...]
    active_runs: tuple[BoardActiveRunV2, ...]
    upcoming: tuple[AutomationRowProjectionV2, ...]
    all_clear: bool
    refreshed_at: datetime
```

`all_clear` is true only when all three selected-source sections are empty.
Priority/order is deterministic and tested. Projection queries batch Catalog,
latest outcome/current run, and action data; the UI may not introduce per-row
fetches.

The existing V1 endpoint may be replaced in-place only if no consumer depends
on its exact shape; otherwise negotiate `version=2` during migration and remove
V1 after frontend parity. The child decides from repository search before code
changes and records the compatibility choice in tests.

## Normalized single-task contract

```http
GET /api/v1/crawl-jobs/tasks/{crawl_job_id}
```

```python
class CrawlTaskDetailProjectionV1(CrawlTaskListItemSchema):
    actions: tuple[BoardActionV1, ...]
    issue: CrawlTaskIssueProjectionV1 | None
    manual_action_guidance: ManualActionGuidanceProjectionV1 | None
```

The builder is the same normalized snapshot seam used by the list/Board.
`manual_action_guidance` contains bounded action type, Source, stage,
classification/code, safe message/instructions, supported resume strategies,
and worker readiness. It excludes cookies, bodies, browser state, raw resume
payload, and unbounded IDs.

The API may keep `request_payload` in compatibility list responses, but the new
detail decoder deliberately drops it. Raw events remain accessible through the
existing audit endpoint and are not decoded into product truth.

## Frontend data flow

```text
hash/source change
  -> abort previous request + increment request version
  -> GET Board V2
  -> decode once
  -> render backend sections/order/actions

task deep link
  -> GET normalized single task
  -> decode authority/workload/issue/actions once
  -> render Task Details
```

Mutations use current expected Automation Revision or Crawl Job ID. Success
invalidates/refetches Board or Task. Failure preserves prior good data and shows
structured recovery state.

## Routes

```text
#scheduler
#scheduler?source=jobsdb
#crawl-tasks
#crawl-tasks?task=<crawl-job-id>
```

Board uses the Wizard-owned route builder for New/Edit/One-off/Run-now and the
Governance route builder for Source Catalog health. Existing Sidebar top-level
views remain unchanged.

Source changes push a hash entry. Back/forward refetches the correct Source.
Cross-source banner changes only the Board Source; it never silently rewrites a
Wizard draft.

## Board state

```javascript
{
  sourceSite,
  board: {status, value, requestVersion, error, stale},
  expandedAutomationIds,
  archivedVisible,
  mutation: {kind, entityId, status, error},
  dialog: null | {kind, entityId, payload},
  notice
}
```

Section data is not copied into separate mutable arrays. View state owns only
Source, expansion, filters, dialogs, and pending mutation.

## Board layout

```text
Task Control Board               New Automation | One-off Run
JobsDB attention | CTgoodjobs running | OfferToday all clear
cross-source critical/manual-action banner

Needs attention
Active runs
Upcoming Automations (expandable table)

All clear                         # only if all sections empty
```

### Needs attention

Render backend title/summary/code and action descriptors. Each item gets one
primary action. The frontend maps action enum to a known route/callback; unknown
actions fail decoder validation rather than becoming generic buttons.

### Active runs

Render phase-correct compact cards/rows:

- listing: targets, pages requested/cap, scope/revision;
- detail: outcomes, remaining snapshot, future eligible separately;
- manual/cancelling issue state;
- Task Details/Logs and Cancel only when declared.

### Upcoming Automation table

Use real table headers and a disclosure cell. Expanded details are a following
row with `aria-expanded`/`aria-controls` and stable IDs.

Columns:

- Automation;
- intent/Source Scope;
- schedule/timezone;
- latest outcome;
- next run absolute + relative;
- lifecycle/Catalog health;
- actions.

Backend order is retained. Archived Automations are fetched/rendered under an
explicit filter, not mixed into Upcoming.

## Lifecycle actions

- Edit and Run now navigate to Wizard routes.
- Pause/Resume calls CAS endpoints and states that active work continues/no
  backfill occurs.
- Archive confirmation states future dispatch stops and history remains.
- Restore uses backend scope validation; activation is explicit.
- Permanent delete first fetches a fresh impact token and lists exact removed
  Automation/revisions versus preserved executions/jobs/history.
- Logs/Task links use durable IDs.

The shared accessible confirmation dialog handles least-destructive initial
focus, Tab cycle, Escape, and focus restoration. Pending actions disable
duplicates. Revision conflict refetches and requires a new decision.

## Task Details composition

```text
Task identity/status/timestamps
Authority
  Dispatch Plan / legacy
  Automation Revision
  Catalog Revision
  Authored / Resolved Scope
Workload
  Listing workload OR Detail Backlog Snapshot
Pacing (detail only; immutable snapshot)
Issue / manual-action guidance
Recovery attempt
Actions / cancellation lifecycle
Audit events link
```

### Listing workload

Render Query Target count, Page Depth, estimate, Run Page Cap, and pages
requested. Do not display Query Target payloads as editable data.

### Detail snapshot

Render backlog scope, cutoff, target count, fetched/saved/failed/unavailable/
manual counts, remaining in snapshot, future eligible for a later run, and
Detail Run Cap. Pacing/Recovery Segment remains separate and cannot redefine
the denominator/cap.

### Legacy history

`authority_kind=legacy` shows `Legacy run — immutable plan not recorded` and
only normalized fields the backend can support. It never guesses Catalog or
Automation Revision.

## Cancellation and polling

1. Backend action capability enables Cancel.
2. Confirmation explains preservation/release behavior.
3. Existing cancellation endpoint returns current status.
4. UI renders `cancelling` and disables Cancel/Resume.
5. Poll normalized single-task/Board at one second.
6. Stop on terminal status, unmount, route/Source change, or request error that
   requires explicit retry.

No status is rewritten locally to `cancelled`. Manual-action Resume is shown
only from normalized guidance/actions.

## Compatibility and retirement

- Introduce Board V2/single-task projections first.
- Render new Board behind a local temporary switch; keep legacy `#scheduler`.
- Reach parity for source selection, runtime warnings, settings/history links,
  Automation actions, active progress, and empty/error states.
- Switch default `#scheduler` to new Board.
- Remove legacy inline form/card composition only after Wizard and Board tests
  pass.
- Remove the temporary switch before child acceptance.
- Preserve reusable Crawl Task API/cancellation/manual-action modules where
  their normalized contracts remain valid.

## Testing

### Backend focused

- stable source summaries and attention priority/order;
- no N+1 projection reads;
- action capability truth table;
- Automation schedule/outcome/Catalog projection;
- Board filtering and all-clear;
- normalized single-task parity with list/Board;
- safe manual-action guidance allowlist;
- not-found/structured errors and legacy history.

### Frontend focused

- hash Source/task deep links and back/forward;
- stale response suppression/prior-good retention;
- source tabs/banner and All clear;
- three sections/backend order;
- table semantics/expansion/lifecycle conflicts;
- Wizard/Governance route handoffs;
- listing/detail/legacy Task Details;
- no raw payload/manual-action JSON;
- cancelling one-second poll/cleanup;
- keyboard/focus/dialog/status and narrow desktop.

## Rollback

Switch `#scheduler` back to the legacy composition while leaving new backend
projections and Task Details available. A UI rollback performs no Catalog,
Automation, plan, or run mutation. If only Board visuals regress, retain the
normalized APIs/decoders and cancellation improvements.
