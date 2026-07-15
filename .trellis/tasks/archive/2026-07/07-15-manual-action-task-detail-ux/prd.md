# Improve manual action task detail recovery UX

## Goal

Make a crawl task in `manual_action_required` state tell an operator what is
wrong, what to do next, and whether each recovery action is currently usable.
The immediate trigger is an OfferToday detail task whose host helper is offline;
the current Task Detail leaves the operator unsure how to recover it safely.

## Background

- The current Task Detail mixes helper-health guidance, raw setup values, crawl
  recovery, browser inspection, profile cleanup, and cancellation in one action
  area.
- Helper health is service-level evidence. Reuse status only proves that a
  task-specific browser session is reachable; it does not prove authentication,
  WAF/IP challenge completion, or source-site access.
- Normalized manual-action snapshots already expose resume support, reusable
  browser support, preferred strategy, classification, source, and instructions.
- Fresh-profile resume intentionally remains available while the host helper is
  offline.

## Requirements

- **R1 — Guided primary flow:** For tasks with
  `reuse_open_browser_supported`, show one recommended next step at a time in
  this order: recover helper, open/connect browser, complete the source-site
  action, explicitly resume the crawl.
- **R2 — Helper recovery:** When the helper is offline, make copying the exact
  PowerShell start command the primary action, state the required working
  directory, and automatically poll helper health after the copy interaction.
- **R3 — Explicit side effects:** Background checks may advance displayed
  readiness, but browser opening and crawl resume require explicit operator
  clicks.
- **R4 — Honest state language:** Separate helper availability, browser
  connectivity, and crawl state. A reachable browser may be called connected,
  but not authenticated, verified, healthy, or ready for source access.
- **R5 — Source-aware shared behavior:** Drive the guided flow from shared
  capabilities rather than hard-coding OfferToday. Use the task source and
  normalized instructions in operator copy. Legacy or unsupported tasks retain
  a simpler operator-review presentation.
- **R6 — Fresh fallback:** Keep `Resume with Fresh Profile` visible as a
  secondary escape path. Explain that it does not reuse the open browser and may
  encounter the same login, WAF, or IP challenge again.
- **R7 — Advanced diagnostics:** Keep raw helper command/working directory,
  health URL/error, manual reuse check, and profile-window cleanup in a collapsed
  advanced-troubleshooting disclosure.
- **R8 — Dangerous actions:** Confirm profile-window cleanup, explaining that
  it closes the dedicated profile's windows. Put crawl cancellation in a
  separate bottom danger area and confirm with the selected crawl-job ID.
- **R9 — Compatibility:** Preserve existing Task Detail metadata, event access,
  non-manual resume behavior, and non-manual task layouts.

## Out of Scope

- A resident host service, desktop application, custom URL protocol, or any
  mechanism that lets the browser directly launch a local process.
- New backend or source-specific access-verification endpoints.
- Claiming that browser connectivity proves source authentication or challenge
  completion.

## Acceptance Criteria

- [x] **AC1 (R1, R2):** A helper-offline reusable-browser task presents one
      unambiguous primary action that copies the helper start command and tells
      the operator where to run it.
- [x] **AC2 (R2, R3):** After copying, helper health is polled and the displayed
      next step advances when the helper becomes reachable, without opening a
      browser automatically.
- [x] **AC3 (R1, R3, R4):** Once helper/browser prerequisites change, the primary
      action advances through `Open Browser` and explicit resume; connected
      browser copy never claims source access is verified.
- [x] **AC4 (R6):** Fresh-profile recovery remains discoverable, visually
      secondary, usable while the helper is offline, and accompanied by a
      concise consequence warning.
- [x] **AC5 (R7, R8):** Diagnostics are collapsed by default; profile cleanup
      and cancellation are isolated from the recovery path and cannot execute
      without confirmation.
- [x] **AC6 (R5, R9):** Capability-driven and legacy manual-action tasks render
      the correct flow while existing non-manual Task Detail behavior remains
      intact.
- [x] **AC7:** Frontend tests cover helper offline, helper recovery, connected
      browser wording, explicit side effects, fresh fallback, confirmations,
      and a task without reusable-browser support.

## Evidence Anchors

- GitHub issue: https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/6
- `frontend/src/components/scraper/CrawlTasksPage.jsx`: current Task Detail state,
  helper note, and flat action list.
- `frontend/src/components/scraper/crawlTaskActions.js`: current health, helper,
  resume, cleanup, and cancellation calls.
- `backend/app/scraper/manual_action.py`: normalized capability and preferred
  resume-strategy contract.
- `backend/app/host_manual_action_helper.py`: service health and browser
  reachability semantics.
- `frontend/src/components/scraper/CrawlTasksPage.test.jsx`: existing
  helper-offline integration test.
