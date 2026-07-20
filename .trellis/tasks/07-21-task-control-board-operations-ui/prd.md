# Task Control Board and Task Details UI

## Goal

Replace the legacy scheduler composition with a single-source desktop
operations board and make listing/detail Task Details accurately explain
immutable run authority, normalized progress, manual action, and acknowledged
cancellation without exposing raw payloads as product truth.

## Confirmed state

- Versioned Crawl Control and CP10 live rollout are complete. Three active
  Catalog Revisions and normalized plan/run authority are available.
- `GET /api/v1/task-control-board` currently returns flat `automations` and
  `runs`. Automation rows contain lifecycle, Source, phase/mode, Authored Scope,
  and timestamps; run rows contain authority plus listing workload or detail
  snapshot (`backend/app/crawl_control/task_control_board_contracts.py:138-211`).
- The service currently fetches one Automation list and one Crawl Task page and
  returns them without named sections, cross-source summaries, catalog health,
  action capabilities, schedule summary, or latest outcome
  (`backend/app/crawl_control/task_control_board_service.py:325-390`).
- The current scheduler page is a launchpad with inline forms and cards rather
  than an operations board
  (`frontend/src/components/scraper/ScheduleManager.jsx:1053-1490`;
  `ScheduleList.jsx:223-359`).
- `CrawlTasksPage` already renders a list/detail split and receives normalized
  authority/workload/snapshot fields, but its Task Details still prints raw
  `manual_action` and `request_payload` JSON
  (`frontend/src/components/scraper/CrawlTasksPage.jsx:898-1056`).
- Existing cancellation is two-stage. UI must treat `cancelling` as active and
  wait for backend `cancelled` acknowledgement.
- Governance and Wizard children own `#source-catalogs`, authoring routes,
  structured errors, shared Crawl Control decoders/routes, and plan review.
  This child reuses those seams.

## Requirements

### Server-owned Board projection

- Extend the Board response so backend owns source summaries, section
  membership/priority/order, Catalog health, schedule summary, latest outcome,
  and allowed actions.
- Source summaries cover JobsDB, CTgoodjobs, and OfferToday and expose
  `attention`, `running`, or `all clear` plus counts. A selected Source filters
  rows; a cross-source critical/manual-action banner never mixes other Source
  rows into the selected board.
- `Needs attention`, `Active runs`, and `Upcoming` are explicit response
  sections. React must not reclassify raw status/error/event strings.
- Automation rows expose source-native scope summary, configured timezone/
  natural schedule, last outcome, next run, lifecycle, revision, Catalog health,
  current run, and server-owned action capabilities.
- Run rows expose normalized immutable authority, phase-correct workload, issue
  summary, recovery state, and action capabilities.
- Add a normalized single-task read for durable deep links. Task Details must not
  fetch a whole page and search client-side or fall back to raw Crawl Job JSON.

### Operations board

- Preserve `#scheduler` as entry and selected Source in the hash/query.
- Header actions are `New Automation` and `One-off Run`; they navigate through
  Wizard route builders with selected Source.
- Render Source tabs with text/count status and a cross-source critical/manual
  action banner that can switch to the affected Source.
- Render `Needs attention`, `Active runs`, and `Upcoming`. If all are empty,
  render one `All clear` state and no fourth work section.
- Needs-attention items expose one server-declared primary recovery action plus
  Task/Logs/Catalog secondary links.
- Active runs show phase-correct compact normalized progress and acknowledged
  Cancel when allowed.
- Catalog health links to Governance. The Board never publishes or rolls back a
  Catalog.

### Automation operations table

- Replace cards with one semantic, expandable desktop table in backend order.
- Columns prioritize name/expand, intent/Source Scope, schedule/timezone, last
  outcome, next run, lifecycle/health, and actions.
- Expanded content shows resolved-scope/revision summary, execution settings,
  current run, and durable links without fetching/parsing raw payloads.
- Actions are Edit, Run now, Pause/Resume, Archive, Logs, scope-aware Restore,
  and archived-only permanent-delete impact.
- Edit/Run now use Wizard routes. Pause/Resume affects future schedules only.
  Archive preserves history. Restore revalidates scope. Permanent delete shows
  exact removed/preserved impact and requires a fresh token.
- Action requests carry expected Automation Revision. Conflicts refresh rather
  than overwrite; duplicate pending actions are disabled.

### Durable listing/detail Task Details

- Preserve `#crawl-tasks` and add `?task=<crawl-job-id>` deep links with browser
  back/forward.
- Task Details show Source, phase/mode, status/timestamps, Automation Revision,
  Dispatch Plan ID/fingerprint/state, Catalog Revision, Authored/Resolved Scope,
  readiness, and explicit audit-events link.
- Listing details show Query Target count, Page Depth, estimated maximum, Run
  Page Cap, and pages requested.
- Detail details show backlog scope, cutoff, target/outcome counts, remaining in
  snapshot, future eligible backlog, complete-run cap, and pacing separately.
- Normalized issue/manual-action guidance and current recovery attempt replace
  raw `manual_action` JSON. Ordinary raw `request_payload` rendering is removed.
- Historical/legacy authority is labelled honestly and does not invent missing
  plan/revision data.

### Cancellation and manual action

- Cancel appears only when backend capability allows it.
- Confirmation explains that committed work remains and unfinished detail work
  returns to later backlog.
- After request, render `cancelling`, disable repeated Cancel/Resume, and poll at
  one second with cleanup until terminal acknowledgement.
- Terminal tasks expose no Cancel. Manual-action Resume appears only when the
  normalized recovery contract permits it.
- OfferToday `ip_blocked` and CTgoodjobs headed/manual action use actionable,
  source-correct guidance; UI does not invent headless fallback, IP bypass, or
  automatic retry.

### Experience and quality

- Reuse Wizard/Governance route builders, decoded errors, timezone formatter,
  and confirmation behavior. Do not create parallel copies.
- Preserve prior good data under refresh failure and suppress late responses
  after Source/route change.
- Table, tabs, disclosure, dialogs, status/live regions, and Task Details are
  keyboard/screen-reader usable with visible focus and non-color meaning.
- Apply the calmer dark operations visual system. Desktop is the dedicated
  target; narrow overflow must remain safe.
- Keep a temporary local legacy-board switch only through parity. Remove it
  before acceptance; no permanent dual UI.

## Out of scope

- Wizard authoring/review implementation and Source Catalog governance UI.
- Reimplementing Crawl Scope, Automation lifecycle, Dispatch Plan, or
  cancellation rules in React.
- Job Intelligence live rollout or post-collection governance.
- Global router/design system, mobile-specific board, automatic cross-source
  actions, or automatic listing-to-detail chaining.

## Acceptance criteria

- [ ] Board response owns all three sections, source summaries, priority/order,
  catalog/schedule/outcome truth, and action capabilities.
- [ ] Source tabs/banner switch context without mixing rows; All clear appears
  only when all three sections are empty.
- [ ] Automation table/lifecycle actions preserve backend order/CAS semantics;
  Edit and Run now hand off to the exact Wizard routes.
- [ ] Pause/Resume, Archive/Restore, permanent-delete impact, conflicts, and
  duplicate-action prevention match backend contracts.
- [ ] `#crawl-tasks?task=<id>` loads one normalized Task directly and survives
  reload/back/forward.
- [ ] Listing and detail Task Details show all required normalized authority and
  workload/snapshot distinctions.
- [ ] Raw `manual_action` and `request_payload` JSON are absent from ordinary
  Task Details; events are audit-only, not reconstruction input.
- [ ] `cancelling` waits at one-second cadence for `cancelled`, disables invalid
  actions, and cleans polling up on terminal/unmount/route change.
- [ ] CTgoodjobs remains headed-only and OfferToday IP block remains truthful.
- [ ] Loading/empty/prior-good-error/stale/manual-action/conflict/success,
  keyboard/focus/table/dialog/status, focused backend/frontend tests, and build
  pass.
- [ ] Legacy scheduler composition and temporary switch are removed only after
  parity; full frontend suite/lint/build runs once at parent integration.

## Dependency and approval

- Implement after Governance and Wizard shared seams; backend/CP10 dependencies
  are complete.
- The user approved this final plan and authorized `task.py start`.
