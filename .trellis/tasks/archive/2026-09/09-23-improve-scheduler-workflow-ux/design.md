# Scheduler UX design

The user approved the proposed board + guided authoring direction on 2026-09-23. This document makes that direction concrete; implementation uses existing contracts.

## Board

Keep backend section membership and ordering. Replace the wide Automation table with responsive rows/cards: name and lifecycle, scope, schedule/next run, last outcome, then visible primary and secondary actions. Expanded configuration retains diagnostics. Distinguish dangerous actions using text and styling, not hidden menus. Render disabled reasons beside their controls with accessible association. Source tabs show attention/run counts and selected source; add a readable refresh timestamp and retry action for stale data.

## Authoring

Retain four history-visible stages with user-facing labels. Make stage navigation available when preceding required choices are complete. Existing edit routes open configuration, while explicit history routes remain honored. Review exposes Edit task, Edit scope, and Edit configuration controls. Run-now is a saved configuration review with a separate Create one-off with changes action, not a misleading selectable card.

Move source choice to the beginning of authoring and explain reset consequences. Summary describes source, task, human-readable selected categories, execution limits, and schedule; diagnostics are secondary. Keep current input controls and existing disclosures. Incompatible detail backlog options explain their requirement and are disabled for selected-category scope; restored incompatible drafts show corrective guidance and cannot continue.

Save receipts use refetched Automation lifecycle, not draft Initial state; only creation exposes Initial state. Paused receipts explain enablement in Scheduler. Accepted dispatch offers the exact Task link. Freeze editing/navigation during mutations; success removes stale submission controls.

## State and authority

Extend existing reducers/route helpers instead of adding a parallel state model. Step changes must preserve in-memory values even without sessionStorage and preserve edit drafts on reload. New edits invalidate authority; stale asynchronous responses cannot overwrite current draft authority. Server review/Dispatch Plan remains the execution boundary. Plan expiry updates the UI and is rechecked at click time. Unknown disabled reason codes remain visible with a conservative explanation.

## Validation and compatibility

Use existing component fixtures and an isolated Playwright config with intercepted API responses for browser journeys and screenshots. Cover viewports 1366x768 and 1440x900 plus narrow layout, keyboard navigation, review correction, saved config/one-off branching, and acknowledgement. No API or database migration. Changes confined to taskControl presentation/navigation/validation and dedicated tests can be reverted without data changes.
