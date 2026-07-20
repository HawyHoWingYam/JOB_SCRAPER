# Automation and One-off wizard UI

## Goal

Replace the current long inline New Automation and immediate-run forms with one
desktop-first, source-truthful four-step wizard for Automation listing/detail
and One-off listing/detail. Every final screen must be a server-owned review,
and every immediate run must consume exactly the reviewed Dispatch Plan.

## Confirmed state

- The live versioned backend and all three published Source Catalog Revisions
  are available after CP10.
- `ScheduleManager.jsx` currently owns both Automation and immediate-run form
  state, while `ScheduleForm.jsx` assumes legacy flat category IDs
  (`frontend/src/components/scraper/ScheduleManager.jsx:376-418,793-1021,1211-1457`;
  `ScheduleForm.jsx:27-128,142-282`).
- Hash navigation exists without a router package
  (`frontend/src/App.jsx:1-19,33-57,80-87`).
- Backend APIs already expose published Catalogs, listing scope preview,
  Automation CRUD/CAS lifecycle, Dispatch Plan prepare/read/dispatch, and
  stable Crawl Control errors (`backend/app/api/crawl_control.py:118-437`).
- The backend does not yet expose one read-only Automation review for both
  listing and detail configuration. `CrawlScopePreviewRequestV1` accepts only
  optional listing settings, while create/update performs final validation
  (`backend/app/schemas/crawl_control.py:20-35`). This child owns a narrow
  Automation-review/fingerprint addition; React must not invent detail backlog
  readiness or scheduled-run snapshot semantics.
- The Governance child lands the compatible structured API-error seam first.
  This child reuses it rather than parsing message strings.

## Requirements

### Routes and versioned drafts

- Preserve `#scheduler` as the Board entry and add feature-local routes for New
  Automation, Edit Automation, New One-off, and Run-now review. Do not add a
  router dependency.
- Browser back/forward changes steps/routes without silently losing work.
- Draft key `taskControl.draft.v1.<id>` stores a validated versioned envelope.
  Ordinary navigation/reload preserves it; successful completion or explicit
  `Discard draft` clears it.
- Malformed, old-version, cross-source, unavailable-storage, and quota-failure
  drafts fail safely with a recoverable notice. Browser storage is never server
  authority.
- Route Source, draft Source, Catalog Source, Authored Scope Source, and command
  Source must agree before review/mutation.

### One shell and four flows

- One reducer and shell own:
  - Automation → Discover listings;
  - Automation → Enrich job details;
  - One-off → Discover listings now;
  - One-off → Recover detail backlog.
- Steps are `intent → scope → execution → review` with visible progress,
  Back/Continue, focus movement, and a persistent live summary.
- Listing is never described as backlog recovery. One-off never implies a saved
  Automation mutation.
- Edit initializes from the current Automation Revision; an intent/Source
  change explicitly clears incompatible state.

### Source-native scope

- Scope reads only the active published Catalog Revision.
- Expand, Exact, and Subtree are separate interactions. Partial state is
  informational; alias/non-queryable nodes are not independently selectable.
- All mode is explicit only when supported. OfferToday `All IT categories` is a
  visible `offertoday:118000` subtree recommendation, never an empty/default
  selection.
- Search leads with source-native labels/full paths and may show trusted
  canonical aliases secondarily.
- Server canonicalization/resolution owns rule deduplication and Query Targets;
  React does not compile source requests.

### Execution configuration

- Listing shows Page Depth per Query Target, resolved target count,
  `targets × depth`, Run Page Cap, system ceiling, crawl mode, and readiness.
- Detail explicitly chooses Source backlog, source-classification Crawl Scope,
  or a named listing batch. It then chooses an entire future run snapshot or a
  complete-run Detail Run Cap.
- A scheduled Automation review may show eligible-now preview only as a
  non-frozen estimate; the future scheduled Dispatch Plan freezes membership at
  due time. Recovery Segment remains hidden from ordinary UI.
- Automation schedule uses friendly presets/builder plus a natural-language
  summary. HKT is visible by default; custom cron and IANA timezone are
  Advanced. Formatters always receive an explicit timezone.
- CTgoodjobs exposes headed only and displays headed-worker/manual-action
  readiness.

### Server-owned review and mutation

- Add `POST /api/v1/automations/reviews` as a read-only review for listing and
  detail drafts. It returns resolved scope, Catalog Revision, workload/detail
  preview, schedule summary, readiness, warnings, input fingerprint, and edit
  before/after context.
- Review creates no Automation, Dispatch Plan, target claims, or external
  request. Create/update revalidates the review fingerprint and current
  Automation/Catalog Revision; drift forces refresh instead of silent save.
- One-off and Run now continue to prepare a short-lived, single-use Dispatch
  Plan. `Confirm and start` sends its exact token and expected plan fingerprint.
- Any editable change invalidates the current review/plan. Expired, stale,
  already-consumed, blocked, or mismatched plans cannot dispatch.
- Edit conflicts preserve the local draft, show the current server revision,
  and offer refresh/review; there is no overwrite action.
- Run now offers `Run saved configuration` and `Run with changes`. The latter
  opens a prefilled One-off draft and never edits the Automation.
- A successful listing Automation may offer a separate detail Automation draft,
  copying only safe Source/Authored Scope context and creating no chain.

### Detail conflict cancellation

- A conflicting active manual detail run shows normalized run/progress context
  and a `View task` link.
- Confirmed cancellation reuses the existing Crawl Job cancellation helper.
- UI renders `cancelling`, disables repeat cancel/dispatch/resume, polls at one
  second with cleanup, and builds a fresh review/plan only after backend
  `cancelled` acknowledgement.
- Completed outcomes remain visible; unfinished work returns to a later backlog
  through backend authority.

### Quality and accessibility

- Feature adapters decode Catalog, Automation review, Dispatch Plan, run
  conflict, and structured errors once. Components never read raw
  `request_payload` or event payloads.
- Reducer state makes implicit empty scope, cross-source scope, stale review,
  and dispatch without a current plan unrepresentable.
- Dialog, nested classification controls, step navigation, errors, and status
  are keyboard/screen-reader usable with visible focus and non-color text.
- Preserve the calmer dark operations style. Desktop is the dedicated target;
  mobile-specific flow is out of scope.

## Out of scope

- Task Control Board sections, source summary banner, Automation operations
  table, ordinary Pause/Resume/Archive/Restore/Delete menus, and durable Task
  Details; these belong to `07-21-task-control-board-operations-ui`.
- Source Catalog discovery/publish/rollback UI.
- Backend crawler/runtime changes, Job Intelligence rollout, cross-source
  Automations, keyword-only scope, or automatic listing-to-detail chaining.
- Global Router/Wizard/Table/Dialog/Toast abstractions.

## Acceptance criteria

- [ ] Hash back/forward, reload, draft retention/discard/completion, malformed
  draft, and storage failure behave safely.
- [ ] All four flows reach server review without Crawl Phase as the first
  decision and produce the correct versioned command.
- [ ] Exact/Subtree/all, aliases, search, Source changes, and canonicalization
  cannot create empty, ambiguous, or cross-source scope.
- [ ] JobsDB, CTgoodjobs, and OfferToday render only active Catalog capabilities;
  CTgoodjobs never offers headless.
- [ ] Listing review distinguishes target/depth/estimate/run cap; detail review
  distinguishes eligible-now preview, future snapshot, complete-run cap, and
  hidden Recovery Segment.
- [ ] Automation review is read-only, server-owned, and fingerprint-revalidated
  on create/update for both listing and detail.
- [ ] One-off and Run now dispatch exactly the reviewed plan; stale/expired/
  double-consumed plans force a fresh review.
- [ ] Edit conflict, Run saved/with changes, paired detail draft, and detail
  conflict cancellation match the requirements above.
- [ ] Cancelling polls at one second until acknowledgement and cleans up on
  unmount/route/source change.
- [ ] No Wizard component parses raw request/event payloads or error strings.
- [ ] Focus, keyboard, status semantics, all blocked/error/success states,
  focused backend/frontend tests, and production build pass.

## Dependency and approval

- Backend runtime/scope children and CP10 are complete.
- Implement after Governance lands the shared structured-error seam; keep the
  legacy Board reachable for the next child.
- The user approved this final plan and authorized `task.py start`.
