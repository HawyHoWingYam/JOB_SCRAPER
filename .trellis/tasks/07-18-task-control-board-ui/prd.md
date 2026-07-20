# Task Control Board and Crawl Control UI program

## Goal

Deliver three independently verifiable desktop UI features on top of the live,
versioned Crawl Control backend: Source Catalog governance, Automation/One-off
authoring, and the Task Control Board with durable Task Details.

The operator must always see the same source-native scope, Catalog Revision,
workload, immutable Dispatch Plan, lifecycle state, and cancellation truth that
the backend executes. React must not recreate those facts from legacy request
payloads or event JSON.

## Confirmed state

- Source Catalog runtime correctness and Versioned Crawl Scope are complete and
  archived. CP10 live rollout upgraded `jobsdb` to `20260720_210000`, preserved
  the Published Job Corpus, published one active revision for JobsDB,
  CTgoodjobs, and OfferToday, and left zero active Crawl Jobs. Exact evidence is
  in
  `.trellis/tasks/archive/2026-07/07-18-versioned-crawl-scope/evidence/cp10-live-rollout-20260720.md`.
- The current scheduler UI still concentrates source selection, API state,
  immediate-run state, progress, forms, and page composition in
  `ScheduleManager.jsx`; `ScheduleForm.jsx` and `ScheduleList.jsx` still assume
  legacy flat categories and card-oriented operations
  (`frontend/src/components/scraper/ScheduleManager.jsx:376-418,793-1021,1053-1490`;
  `ScheduleForm.jsx:27-128`; `ScheduleList.jsx:93-112,223-359`).
- `App.jsx` uses hash-based top-level views and lazy components, not a router
  package (`frontend/src/App.jsx:1-19,33-57,80-87`). Existing `#scheduler` and
  `#crawl-tasks` bookmarks must remain valid.
- Source Catalog governance endpoints, versioned Automation endpoints,
  `POST /crawl-scopes/preview`, Dispatch Plan preparation/dispatch, and
  `GET /task-control-board` are present
  (`backend/app/api/crawl_control.py:118-455`).
- The current board projection exposes normalized Automation rows and run
  authority/workload/snapshot fields, but it is still a flat
  `automations + runs` response. It does not yet own named board sections,
  cross-source summaries, catalog health, action capabilities, full schedule
  summary, or latest outcome
  (`backend/app/crawl_control/task_control_board_contracts.py:138-211`;
  `task_control_board_service.py:325-390`). The Board child must close this
  narrow projection gap before rendering those concepts.
- Automation create/update validates the final configuration, and listing scope
  has a preview endpoint. There is no dedicated read-only Automation review
  contract for both listing and detail drafts. The Wizard child must add that
  narrow server-owned review seam instead of fabricating detail readiness or
  backlog meaning in React.
- Crawl Tasks already receives normalized `authority`, `listing_workload`,
  `detail_snapshot`, and `recovery_attempt`; the current detail panel still
  prints raw `manual_action` and `request_payload` JSON
  (`frontend/src/components/scraper/CrawlTasksPage.jsx:898-1056`). The new Task
  Details must replace payload archaeology with normalized projections.
- CTgoodjobs remains headed-only. OfferToday upstream network blocks must remain
  truthful manual-action states; UI must not suggest an implicit retry, IP
  bypass, or headless fallback.
- Post-collection Canonical Job Taxonomy, Company Industry, Employment Type,
  and Skill governance remain the independent Job Intelligence program. They
  never become Crawl Scope authority.

## Shared product requirements

### Source and execution truth

- Source-native taxonomy is the only executable Crawl Scope authority.
- Every selection uses a source-qualified ID and one published immutable
  Catalog Revision. Display-name equality and canonical mappings never create
  or expand source queries.
- Authored Scope, Resolved Run Scope, Automation Revision, Dispatch Plan,
  Page Depth, Run Page Cap, Detail Run Cap, Backlog Snapshot, Recovery Segment,
  and future eligible backlog remain visibly distinct.
- Candidate Catalogs are non-executable. Publish/rollback requires durable
  validation, current Automation impact, an explicit confirmation, and
  authoritative refetch after mutation.
- CTgoodjobs shows headed-only capability and manual-action readiness.
- Components consume feature decoders and normalized projections. No new UI
  reads raw `request_payload`, raw event payloads, source adapter payloads, or
  message strings to infer recovery actions.

### Navigation and state

- Keep hash navigation and existing top-level bookmarks. Add feature-local
  parsers/builders; do not add a router dependency solely for these features.
- Browser back/forward must preserve the correct page, selected Source, and
  versioned wizard draft.
- Loading, prior-good refresh failure, empty, stale, conflict, worker-offline,
  manual-action, cancelling, expired-plan, and success states each have explicit
  copy and recovery actions.
- Backend/server state wins after every mutation. Optimistic UI may indicate
  pending work but cannot invent an active revision, terminal cancellation, or
  consumed plan.

### Experience and accessibility

- Preserve the dark theme while reducing glass/glow, strengthening hierarchy,
  and reserving accent colors for status, risk, and primary action.
- Desktop is the dedicated target. Narrow desktop overflow must remain usable;
  mobile-specific full-screen/sticky flows are out of scope.
- Tabs, tables, nested classification controls, wizard steps, status messages,
  confirmations, and focus restoration are keyboard and screen-reader usable;
  state is never color-only.
- Shared code is feature-local and extracted only where two UI children need the
  same decoded contract or route/action helper. Do not build a speculative
  project-wide design system.

## Three UI children and ownership

### 1. Source Catalog governance UI

`07-18-source-catalog-governance-ui` owns `#source-catalogs`, read-only revision
health, candidate discovery/diff, durable validation/manual action, real
Automation impact, explicit publish/rollback, and immutable history. It never
owns Crawl Scope resolution, Board rendering, or wizard authoring.

### 2. Automation and One-off wizard UI

`07-18-task-control-board-wizard-ui` owns full-page create/edit Automation,
One-off listing/detail, and Run-now review routes. It owns versioned session
drafts, the shared four-step shell (`intent → scope → execution → review`),
classification interaction, schedule builder, server-owned review, Dispatch
Plan confirmation, and conflict cancellation inside the review flow. It does
not own the Board, Automation table, persistent Task Details, or ordinary
lifecycle menus.

### 3. Task Control Board and Task Details UI

`07-21-task-control-board-operations-ui` owns `#scheduler`, source summaries and
critical banner, `Needs attention`, `Active runs`, `Upcoming`, the expandable
Automation table, lifecycle actions, and durable listing/detail Task Details.
It owns the minimal backend projection extension required for those normalized
sections/action capabilities. It links to the wizard/governance routes and
reuses their decoders/helpers instead of duplicating them.

## Dependency and execution order

1. Backend children are complete and archived.
2. Governance UI establishes the shared structured API-error behavior and
   Source Catalog route.
3. Wizard UI establishes Crawl Control route/draft/review seams while the
   legacy board remains reachable.
4. Board/Task Details consumes those seams, replaces the legacy scheduler
   composition, and retires raw Task Details payload rendering only after
   parity.
5. Parent remains a planning/integration coordinator and is not an
   implementation target.

All three UI children may be moved to `in_progress` now because the user has
approved the final plan. Their implementation order remains sequential where
files or shared seams overlap.

## Out of scope

- Job Intelligence live rebuild, pointer switch, embedding rebuild, or writer
  reopening.
- CTgoodjobs headless-first execution or automatic headed fallback.
- Canonical-taxonomy-driven Crawl Scope, keyword-only scope, cross-source
  Automations, or automatic listing-to-detail chaining.
- Reconstructing or preserving pre-cutover legacy Crawl Control rows.
- A new project-wide router, generic design system, mobile-specific wizard, or
  speculative global polling/state framework.

## Parent acceptance criteria

- [x] Versioned backend, three active Catalog Revisions, cutover, bounded smoke
  authority, cancellation acknowledgement, and rollback evidence are complete.
- [ ] Governance UI cannot expose a candidate as executable or publish with
  stale validation/impact.
- [ ] All four authoring flows, Edit, and Run now show server-owned reviewed
  scope/workload/readiness and dispatch exactly the reviewed plan.
- [ ] Board sections, source summaries, Automation table, lifecycle actions,
  and Task Details consume normalized backend projections.
- [ ] Listing and detail Task Details distinguish authored/resolved authority,
  workload/snapshot progress, future backlog, manual action, and cancellation
  without raw JSON rendering.
- [ ] `cancelling` remains pending until backend `cancelled` acknowledgement;
  repeated actions are disabled and fresh readiness is built afterward.
- [ ] Hash back/forward, draft corruption/storage failure, stale responses,
  structured errors, keyboard/focus, and narrow-desktop behavior are tested.
- [ ] Governance, Wizard, and Board children pass their focused checks; the full
  frontend suite/build runs once at the final UI integration gate.
- [ ] Parent integration confirms no automatic publication, runtime discovery,
  static executable fallback, implicit categoryless query, or React payload
  archaeology remains.

## Planning approval

The user explicitly approved final Task Control Board UI planning and starting
three UI children. The parent stays in `planning`; start only the three child
tasks listed above.
