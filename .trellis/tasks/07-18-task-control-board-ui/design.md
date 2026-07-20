# Task Control Board and Crawl Control UI program design

## Architectural invariant

The UI renders server-owned projections of source-native intent and executable
authority:

```text
published Source Catalog
  -> Authored Crawl Scope
  -> server review / immutable Dispatch Plan
  -> Crawl Job authority + normalized progress
  -> Board / Task Details
```

Candidate data, browser-local draft state, compatibility `request_payload`, and
raw event payloads are never executable or display authority.

The parent coordinates three frontend feature modules. It does not own direct
implementation.

## Module ownership

```text
frontend/src/features/sourceCatalogs/       # governance child
frontend/src/features/taskControl/
  shared/                                   # introduced by wizard, reused by board
    apiError.js
    controlApi.js
    controlDecoders.js
    controlRoute.js
    ConfirmActionDialog.jsx
  wizard/                                   # wizard child
  board/                                    # board child

frontend/src/components/scraper/
  CrawlTasksPage.jsx                        # board child migrates Task Details
```

Feature-local sharing is permitted only for decoded contracts, route builders,
timezone formatting, and action helpers actually consumed by both Wizard and
Board. Governance remains separate because its candidate/revision lifecycle is
not the run-control state model.

The repository remains JavaScript. Use JSDoc/runtime decoders; do not introduce
TypeScript solely for this program.

## Shared application boundary

### Structured API errors

The existing API client is extended compatibly so every new feature receives:

```javascript
{
  code,
  message,
  details,
  requestId,
  status,
}
```

Older message-based callers keep their existing behavior. New adapters map
stable codes to view states once; components never parse strings.

The Governance child lands and tests this small shared client change first.
Wizard and Board reuse it.

### Hash navigation

Top-level `resolveAppView` still recognizes existing roots. It lower-cases only
the first raw segment and passes the untouched remainder/query to feature-local
parsers.

```text
#source-catalogs?source=jobsdb

#scheduler
#scheduler/automation/new?source=jobsdb&draft=<id>
#scheduler/automation/<id>/edit?draft=<id>
#scheduler/one-off/new?source=jobsdb&draft=<id>
#scheduler/run/<automation-id>/review?draft=<id>

#crawl-tasks
#crawl-tasks?task=<crawl-job-id>
```

Builders percent-encode opaque IDs and query values. Invalid subroutes return a
recoverable feature notice. Existing `#scheduler` and `#crawl-tasks` bookmarks
remain valid.

## Child 1 — Source Catalog governance

The governance module owns:

- source summary and active immutable revision;
- explicit candidate discovery;
- source-native diff and validation evidence;
- CTgoodjobs headed manual-action flow;
- Automation impact review;
- publish/rollback confirmation and authoritative refetch;
- immutable publication history.

It consumes `/api/v1/source-catalogs/*` and never calls discovery during page
load. Its detailed state model, API operations, accessibility, and tests live in
the child `design.md`.

## Child 2 — Automation and One-off wizard

### Frontend seam

```javascript
parseControlRoute(hash)
buildControlRoute(route)

readDraft(id)
writeDraft(id, draft)
clearDraft(id)

wizardReducer(state, action)
toAutomationReviewRequest(state)
toAutomationCommand(state, review)
toOneOffPlanRequest(state)
```

One reducer owns four variants:

- Automation listing;
- Automation detail;
- One-off listing;
- One-off detail.

The route, draft source, selected Catalog source, Authored Scope source, and
command source must agree before any review or mutation can be built.

### Narrow server-review closure

Current APIs validate create/update and provide listing scope preview, but do
not expose a complete read-only Automation review for both phases. The Wizard
child adds one bounded backend seam rather than deriving detail meaning in
React:

```http
POST /api/v1/automations/reviews
```

Request:

```text
AutomationReviewRequestV1 {
  configuration
  automation_id?          # edit only
  expected_revision?      # edit only
}
```

Response:

```text
AutomationReviewV1 {
  version
  input_fingerprint
  automation_id?
  expected_revision?
  catalog_revision_id
  authored_scope
  resolved_scope
  listing_workload?       # targets × page depth, run cap, system ceiling
  detail_preview?         # explicit population, eligible-now count, run cap;
                          # never a frozen scheduled-run snapshot
  schedule_summary
  readiness
  warnings
  before?                 # edit comparison
}
```

Review is read-only: it creates no Automation, Dispatch Plan, target claims, or
external request. Create/update revalidates the submitted configuration and
review fingerprint against the current Catalog/Automation Revision; drift
returns a stable refresh-required conflict. Future scheduled runs still resolve
and freeze their own plan at due time.

This is the only backend expansion owned by the Wizard child. One-off and Run
now continue using the existing prepared Dispatch Plan API.

### Wizard review authority

- Automation create/edit confirms `AutomationReviewV1` and saves with expected
  revision plus review fingerprint.
- One-off and Run now confirm a prepared Dispatch Plan and consume its exact ID,
  fingerprint, and one-time token.
- Any editable change invalidates review/plan state.
- Plan expiry, Catalog drift, eligibility drift, or Automation Revision drift
  requires a fresh server review.
- Detail conflict cancellation reuses the existing Crawl Job cancellation
  action, waits through `cancelling`, and creates a new plan only after terminal
  acknowledgement.

The legacy `ScheduleManager` board remains reachable until the Board child
replaces it.

## Child 3 — Task Control Board and Task Details

### Narrow board-projection closure

The current endpoint returns flat Automation/run arrays. The Board child extends
the normalized backend contract before building UI sections:

```text
TaskControlBoardProjectionV2 {
  version: 2
  selected_source
  source_summaries[] {
    source_site
    state: attention | running | all_clear
    attention_count
    active_run_count
    catalog_health
  }
  needs_attention[] {
    id, kind, priority, source_site, code, title, summary,
    entity_ref, primary_action, secondary_actions
  }
  active_runs[] {
    run: CrawlControlRunProjectionV1
    actions
  }
  upcoming[] {
    automation: AutomationRowProjectionV2
    latest_outcome
    schedule_summary
    actions
  }
  all_clear
  refreshed_at
}
```

`AutomationRowProjectionV2` adds the saved timezone/schedule summary, latest
outcome, catalog health, resolved scope summary, and server-owned action
capabilities. React preserves backend section membership, priority, and order.

The child also adds a normalized single-task read:

```http
GET /api/v1/crawl-jobs/tasks/{crawl_job_id}
```

It returns the same normalized Task projection as the list, plus bounded manual
action guidance/action capabilities. It never requires Task Details to display
raw `request_payload` or raw event JSON. Events may remain available behind a
separate audit link; they are not parsed to reconstruct authority or metrics.

### Board composition

```text
Task Control Board
  Source tabs + cross-source critical/manual-action banner
  Needs attention
  Active runs
  Upcoming Automation table
  All clear (only when all three sections are empty)
```

The Board owns ordinary Automation lifecycle actions:

- Pause/Resume;
- Archive;
- Restore after scope validation;
- archived-only permanent-delete impact;
- links to Edit, Run now, Logs, Source Catalogs, and Task Details.

Edit and Run now navigate to Wizard routes. The Board does not duplicate Wizard
state or Dispatch Plan preparation.

### Task Details

`#crawl-tasks?task=<id>` deep-links to durable listing/detail history. The detail
view shows:

- Automation/Dispatch Plan/Catalog authority;
- authored and resolved source-native scope;
- listing target/depth/cap/pages or detail snapshot/outcomes/remaining/future;
- pacing separately from run cap;
- normalized issue/manual-action guidance;
- recovery attempt and acknowledged cancellation lifecycle;
- explicit audit-event link.

It removes the ordinary raw `manual_action` and `request_payload` JSON blocks.
Terminal tasks expose no Cancel; `cancelling` disables repeat actions and polls
at one second until backend acknowledgement.

## Concurrency and stale-response rules

- Every Source/route change aborts or versions pending reads.
- Late responses cannot replace good state for another Source/route.
- A mutation invalidates only affected caches, then refetches server truth.
- Review tokens, plan tokens, impact tokens, and Automation Revisions are never
  stored as long-lived reusable draft authority.
- Validation/cancellation polling is bounded to the owning component lifecycle
  and cleans up on unmount/route/source change.

## Compatibility and retirement

- Governance is additive and can be hidden without changing active revisions.
- Wizard routes ship while legacy board/forms remain available behind a local
  temporary switch.
- Board replaces `#scheduler` only after its projection and action parity pass.
- Task Details replaces raw payload blocks only after normalized authority,
  issue, and action fields pass focused tests.
- The temporary scheduler switch is removed before parent acceptance; it is not
  a permanent dual implementation.
- A UI rollback never mutates Catalog, Automation, plan, or run state.

## Validation strategy

Each child runs pure/feature-focused tests during implementation. The parent
integration gate runs the complete frontend suite, lint, and production build
once after all three children converge. Backend tests are focused only on the
two narrow review/projection additions; the already accepted CP10/full backend
suite is not repeated without a concrete regression.

Cross-child integration proves:

```text
governance publish/rollback
  -> active revision/refetch
  -> wizard review/plan
  -> run authority
  -> board/task details
```

The same IDs, revisions, fingerprints, workload units, lifecycle states, and
cancellation acknowledgement must survive the entire flow.
