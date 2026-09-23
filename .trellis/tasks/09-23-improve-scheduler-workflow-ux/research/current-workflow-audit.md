# Scheduler workflow discovery — 2026-09-23

## Evidence limits

Source/spec inspection with two independent read-only scouts; main agent spot-checked the relevant JSX and validation branches. No browser rendering or live mutations performed in this discovery round. Findings below are interaction opportunities, not measured user failures.

## Existing journey

- New Automation: intent -> Source scope -> execution and schedule -> server review -> save.
- One-off: intent -> Source scope -> execution -> server Dispatch Plan -> confirm/start -> exact Task.
- Edit Automation: existing values hydrate, but entry still starts at intent.
- Run now: saved Automation review; Run with changes creates an independent One-off draft.
- Board: source tabs -> attention -> active runs -> upcoming/archived Automations.

## Findings

1. Board actions share one visual treatment; disabled reasons are only HTML title text. Source: `frontend/src/features/taskControl/board/TaskControlBoardPage.jsx:189`.
2. Automation table has seven columns and a 1100px minimum width. Source: `frontend/src/features/taskControl/board/TaskControlBoardPage.css:19`. Assess rendered layout before choosing cards or a compact table.
3. Editing always starts at intent despite restored configuration. Sources: `frontend/src/features/taskControl/board/TaskControlBoardPage.jsx:87`, `frontend/src/features/taskControl/wizard/wizardCommands.js:120`.
4. Source selection is in the side summary, and changing it resets scope/execution. Sources: `frontend/src/features/taskControl/wizard/TaskControlWizard.jsx:416`, `frontend/src/features/taskControl/wizard/wizardReducer.js:56`.
5. Detail backlog choices can conflict with an earlier selected-category scope; execution completion does not check this combination before command building rejects it at review. Sources: `frontend/src/features/taskControl/wizard/TaskControlWizard.jsx:102`, `frontend/src/features/taskControl/wizard/wizardReducer.js:148`, `frontend/src/features/taskControl/wizard/wizardCommands.js:54`.
6. Automation creation defaults to paused, but the success receipt only says Automation saved. Existing edit form also displays Initial state although update payload does not include it. Sources: `frontend/src/features/taskControl/wizard/wizardDraft.js:19`, `frontend/src/features/taskControl/wizard/TaskControlWizard.jsx:125`, `frontend/src/features/taskControl/wizard/TaskControlWizard.jsx:413`, `frontend/src/features/taskControl/wizard/wizardCommands.js:98`.
7. Review/summary exposes internal terms alongside operator decisions (fingerprints, draft identity, canonical targets). Inspect actual rendering before deciding what should remain visible as diagnostic detail. Source: `frontend/src/features/taskControl/wizard/TaskControlWizard.jsx:138` and `:416`.

## Preserved decisions

Keep Scheduler and Crawl Tasks separate; dark English UI; configuration directly accessible. Preserve server-owned scope/workload, reviewed authority invalidation, one-use dispatch confirmation, source-specific limits, backend action capabilities, exact Task links, and cancellation acknowledgement. No change to paused default or execution limits is proposed merely to improve usability.

## Browser validation gap

Current `frontend/e2e/usability.spec.js` checks Scheduler navigation/heading only. The fixture backend in `backend/tests/e2e/jev_app.py` lacks task-control board and wizard review/dispatch routes. Existing component fixtures live in `TaskControlBoardPage.test.jsx` and `TaskControlWizard.test.jsx`. A later rendered audit should use isolated request interception or extend dedicated fixtures, never launch live crawls for UI review.

## First product decision

Recommended: retain separate board and guided authoring, but substantially reorganize the content and navigation within Scheduler. Prioritize clear source/task/scope selection, direct editing of existing configuration, comprehensible review, and explicit save/start outcomes. Confirm whether the user wants this depth or prefers preserving the current interaction sequence and focusing on readability/copy.
