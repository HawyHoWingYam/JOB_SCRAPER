# Automation and One-off wizard UI design

## Feature boundary

The child establishes shared Crawl Control route/decoder seams and implements
only the authoring/review flows. The legacy scheduler board stays available
until the Board child replaces it.

```text
frontend/src/features/taskControl/
  shared/
    controlApi.js
    controlDecoders.js
    controlRoute.js
    controlTime.js
    ConfirmActionDialog.jsx
  wizard/
    TaskControlWizard.jsx
    wizardDraft.js
    wizardReducer.js
    wizardCommands.js
    WizardShell.jsx
    IntentStep.jsx
    ScopeStep.jsx
    ExecutionStep.jsx
    ReviewStep.jsx
    SourceScopeTree.jsx
    ScheduleBuilder.jsx
    RunNowReview.jsx
    TaskControlWizard.test.jsx
    wizardDraft.test.js
    wizardReducer.test.js
    wizardCommands.test.js

backend/app/crawl_control/automation_review_contracts.py
backend/app/crawl_control/automation_review_service.py
backend/app/api/crawl_control.py
backend/app/schemas/crawl_control.py
```

The feature uses the Governance-delivered structured API error and existing
Crawl Job cancellation helper. It does not add TypeScript, a router package, or
global UI primitives.

## Hash routes

```text
#scheduler/automation/new?source=jobsdb&draft=<id>
#scheduler/automation/<automation-id>/edit?draft=<id>
#scheduler/one-off/new?source=jobsdb&draft=<id>
#scheduler/run/<automation-id>/review?draft=<id>
```

`App.jsx` recognizes only the first hash segment and passes the untouched rest
to `parseControlRoute`. Builders percent-encode IDs/query values. Unsupported
routes return to `#scheduler` with a recoverable notice.

Existing `#scheduler` remains the board entry. This child may add a temporary
feature switch/route composition but may not replace the Board or delete legacy
forms.

## Versioned session draft

Storage key:

```text
taskControl.draft.v1.<draft-id>
```

Envelope:

```json
{
  "version": 1,
  "updated_at": "2026-07-21T00:00:00+08:00",
  "flow": "automation",
  "mode": "create",
  "automation_id": null,
  "expected_revision": null,
  "source_site": "jobsdb",
  "step": "scope",
  "intent": "listing",
  "scope": null,
  "execution": {},
  "schedule": {}
}
```

`scope: null` is an incomplete view state only. Command creation requires
explicit all mode or non-empty rules. Detail intent additionally requires an
explicit backlog scope.

`readDraft`, `writeDraft`, and `clearDraft` validate version, enums, IDs,
numbers, strings, timestamps, and cross-field Source consistency. Malformed or
old data returns a clean draft plus notice. Storage exceptions are caught;
in-memory work continues. Tokens, Dispatch Plan IDs, review fingerprints, and
server readiness are not persisted as reusable authority.

Ordinary navigation preserves the draft. Explicit `Discard draft` confirms when
meaningful fields exist. Successful create/update/dispatch clears it.

## API adapter

`controlApi.js` exposes domain-shaped operations:

```javascript
getPublishedCatalog(source, options)
getAutomation(id, options)
reviewAutomation(request, options)
createAutomation(request)
updateAutomation(id, request)
prepareDispatchPlan(request)
getDispatchPlan(id, options)
dispatchPlan(id, confirmationToken, expectedFingerprint)
cancelCrawlJob(id)
```

Every response is decoded once. Components receive decoded Catalog,
Automation, AutomationReview, DispatchPlan, and conflict views. Stable backend
codes map to explicit reducer actions; raw messages are secondary diagnostics.

## Automation review seam

### Contracts

```python
class AutomationReviewRequestV1(FrozenContract):
    configuration: AutomationConfigurationV1
    automation_id: UUID | None = None
    expected_revision: int | None = Field(default=None, ge=1)

class AutomationDetailPreviewV1(FrozenContract):
    backlog_scope: DetailBacklogScopeV1
    eligible_now_count: int = Field(ge=0)
    limit_kind: Literal["entire_snapshot", "stop_after"]
    detail_run_cap: int
    absolute_safety_cap: int
    snapshot_frozen: Literal[False] = False

class AutomationReviewV1(FrozenContract):
    version: Literal[1] = 1
    input_fingerprint: str
    automation_id: UUID | None
    expected_revision: int | None
    catalog_revision_id: UUID
    authored_scope: AuthoredCrawlScopeV1
    resolved_scope: ResolvedRunScopeV1
    listing_workload: ListingWorkloadPreviewV1 | None
    detail_preview: AutomationDetailPreviewV1 | None
    schedule_summary: AutomationScheduleSummaryV1
    readiness: DispatchPlanReadinessV1
    warnings: tuple[CrawlScopeErrorPayloadV1, ...]
    before: AutomationProjectionV1 | None
```

Create/update requests gain `review_fingerprint`. The service recomputes the
same review under current Catalog/Automation state before writing. A mismatch
returns a stable `AUTOMATION_REVIEW_STALE` conflict containing the current
Automation Revision/Catalog Revision where applicable.

### Boundaries

- Review is read-only and issues no source request.
- It creates no Automation, revision row, Dispatch Plan, target membership,
  Crawl Job, event, or outbox command.
- Listing uses the existing resolver/workload calculator.
- Detail uses the same eligibility/count seam as future plan preparation but
  does not freeze/claim membership. `snapshot_frozen=false` is explicit.
- Scheduled execution later resolves and freezes its own immutable plan.
- Create/update still performs normal CAS and validation in its write
  transaction; the review fingerprint is an additional stale-review fence.

## Wizard state model

```javascript
{
  route: {flow, mode, automationId, draftId},
  step: "intent" | "scope" | "execution" | "review",
  sourceSite,
  intent: null | "listing" | "detail",
  scopeDraft,
  executionDraft,
  scheduleDraft,
  catalog: {status, value, requestVersion, error},
  automation: {status, value, error},
  review: {status, value, inputFingerprint, error},
  dispatchPlan: {status, value, error},
  conflict: null | {run, actions},
  mutation: {status, kind, error},
  notice
}
```

Reducer invariants:

- Source change clears scope, Catalog-dependent state, review, and plan.
- Intent change clears phase-incompatible execution/backlog state.
- Any editable change invalidates review and Dispatch Plan.
- Route/draft/source mismatch cannot build a request.
- Next is disabled until local step completeness.
- Review requires a current server response matching the draft fingerprint.
- Automation save requires current review and expected revision when editing.
- Dispatch requires a ready, unexpired plan matching the current draft.
- Pending mutation prevents duplicate submit/navigation that would consume a
  token twice.

## Layout

```text
Back to board              New Automation / One-off Run
1 Intent — 2 Scope — 3 Execution — 4 Review
main step content                    live summary
Back                               Continue / Confirm
```

Desktop uses a wide content column and stable summary rail. Focus moves to the
new step heading. Actions remain in normal/sticky feature flow only when they do
not obscure focused content. Dedicated mobile behavior is not added.

## Step 1 — Intent

Automation:

- `Discover listings`
- `Enrich job details`

One-off:

- `Discover listings now`
- `Recover detail backlog`

Each card explains output and scheduled/immediate behavior. Source is inherited
from the route/board. Edit mode loads current intent; changing it requires an
explicit reset of incompatible scope/settings.

## Step 2 — Scope

### Listing

- Explicit all only when `supports_all_scope`.
- Choose classifications through source-native hierarchy.
- OfferToday recommends visible subtree `offertoday:118000`; it never silently
  defaults.

### Detail

Choose exactly one:

- Source backlog;
- source-classification Crawl Scope;
- explicit listing batch.

Listing batch never picks “latest” implicitly. Classification scope reuses the
same rule controls. The summary calls this the eligible population, not a
frozen snapshot.

### Classification interaction

- Expand button only expands.
- Selectable nodes expose `This classification only` and/or `Entire category
  tree` according to capabilities.
- Alias/non-queryable nodes remain informational.
- Rule chips name Exact/Subtree and full native path.
- Partial state is display-only.
- Search preserves full native path; trusted canonical alias is secondary.
- If full ARIA tree keyboard behavior is not implemented, use nested semantic
  lists/buttons instead of partial tree roles.

## Step 3 — Execution

### Listing

- Page Depth;
- resolved Query Target count;
- `targets × depth = estimated maximum`;
- Run Page Cap and system ceiling;
- crawl mode/readiness under Advanced.

Cap overflow blocks Continue.

### Detail

- explicit backlog population;
- eligible-now preview;
- Automation: maximum details per scheduled run;
- One-off: entire eligible snapshot or Stop after N;
- absolute safety cap;
- active detail conflict.

The Automation review labels eligible-now as non-frozen. One-off plan review
labels exact frozen target count/cutoff. Recovery Segment is absent.

### Schedule

Automation only:

- friendly presets/builder;
- natural-language summary;
- visible `Asia/Hong_Kong` default;
- Advanced custom cron/IANA timezone;
- next-run preview with explicit timezone label.

All formatters receive `timeZone`; browser-local defaults are forbidden.

## Step 4 — Review

Automation review shows:

- edit before/after;
- intent/source;
- Authored and Resolved Scope;
- current Catalog Revision;
- listing workload or non-frozen detail preview;
- schedule/timezone/mode/readiness;
- warnings and review fingerprint.

Save sends the reviewed fingerprint. `AUTOMATION_REVIEW_STALE` or revision
conflict keeps the draft and requests refresh; it never overwrites.

One-off/Run-now review displays plan expiry, exact Catalog/Resolved Scope,
listing workload or detail snapshot count/cutoff, readiness, and fingerprint.
Confirm dispatches only that plan. Expiry/staleness disables confirmation and
offers `Refresh review`.

## Run now, changes, and paired creation

- `Run saved configuration` prepares a saved-Automation plan.
- `Run with changes` creates a One-off draft from safe Source/scope/settings.
- Neither modifies the Automation.
- Successful listing Automation creation may create a separate detail draft
  with only safe Source/Authored Scope context.
- Never copy plan IDs, runtime state, snapshot membership, stale readiness, or a
  hidden dependency.

## Detail conflict cancellation

1. Render decoded conflict run/progress and Task Details link.
2. Confirm cancellation in the feature-local accessible dialog.
3. Reuse `crawlTaskActions.cancelCrawlJob`.
4. Render `cancelling`; disable cancel/dispatch/resume.
5. Poll at one second with cleanup on terminal/unmount/route/source change.
6. After `cancelled`, discard the blocked plan and request a new review/plan.

## Styling and accessibility

- Opaque/low-transparency dark panels, limited glow, visible focus.
- Step/status/error meaning includes text and icons, never color alone.
- Dialog uses labelled `role=dialog`, least-destructive initial focus, Tab cycle,
  Escape, and trigger-focus restoration.
- All interactive classification controls and progress steps expose correct
  names/states.

## Testing

### Backend focused

- listing/detail review response;
- read-only/no-side-effect proof;
- resolver/eligibility seam reuse;
- non-frozen detail preview;
- create/update review-fingerprint success and stale Catalog/Automation conflict;
- timezone/schedule summary and structured errors.

### Frontend pure

- route parse/build and invalid hashes;
- valid/malformed/old/storage-throw drafts;
- reducer invalidation and request builders;
- Exact/Subtree/all/cross-source rules;
- explicit timezone formatting.

### Frontend integration

- all four flows;
- Automation review/save and edit conflict;
- plan expiry/staleness/double-submit prevention;
- CTgoodjobs headed-only and OfferToday recommendation;
- detail conflict cancellation/poll cleanup;
- Run saved/with changes and paired draft;
- focus/keyboard/status and every blocked/error/success state.

## Rollback

Remove the new routes and Automation-review endpoint while leaving the legacy
Board/forms reachable. Review is read-only, so rollback requires no data repair.
Never compensate a stale plan by reconstructing it client-side.
