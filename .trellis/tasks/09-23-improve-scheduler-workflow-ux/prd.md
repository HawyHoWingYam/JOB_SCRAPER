# Improve Scheduler page and end-to-end workflow UX

## Goal

Make Scheduler easier to scan, configure, review, and follow through to execution. The user approved restructuring steps, editing entry points, and layout on 2026-09-23 after reviewing the initial journey findings. Proceed with the agreed direction while preserving execution rules.

## Requirements

- R1: Retain the separate Scheduler board and guided authoring. Distinguish source context, attention, active runs, recurring configuration, primary actions, and lifecycle actions. Keep configuration accessible and make disabled reasons visible.
- R2: Existing Automation edits open at configuration; completed prerequisites remain directly reachable. Review offers explicit editing/back navigation. New authoring remains guided and recoverable across hash navigation and refresh.
- R3: Summary answers source, task, selected scope, limits, and schedule. Review explains the operation and its consequences before confirmation; diagnostics remain available separately.
- R4: Detect incompatible detail backlog/scope combinations at configuration with a correction path. Preserve valid drafts rather than silently changing scope or execution defaults.
- R5: Saving reports the refreshed Automation lifecycle and next schedule where supplied. Editing does not pretend to change Initial state. Dispatch links to the exact Task and distinguishes accepted work from completion. Return navigation preserves Source.
- R6: Preserve backend authority, fingerprint invalidation, one-use plan tokens, expiry, cancellation acknowledgement, action capabilities, and source-specific limits. Maintain dark English UI and laptop/keyboard usability.

## Acceptance Criteria

- [x] AC1 / R1: At 1366x768 and 1440x900 a populated board exposes primary actions without a mandatory wide-table scroll; current source, attention, runs, and recurring configurations remain distinguishable.
- [x] AC2 / R2: Edit opens configuration, review-to-edit-to-review keeps values and obtains fresh authority, and back/refresh retain the correct draft and Source.
- [x] AC3 / R3: User-facing summary and review describe the planned work, limits and timing; saved-run review clearly distinguishes a one-off copy from editing the Automation.
- [x] AC4 / R4: Invalid detail scope/backlog combinations prevent continuation before review and provide explicit correction; positive finite limits retain existing server constraints.
- [x] AC5 / R5: Paused/active save receipts are accurate, edit cannot change lifecycle through an ignored field, and dispatch has an exact Task link with no false completion claim.
- [x] AC6 / R6: Loading, missing data, review errors, stale/expired authority, pending mutations, cancellation, and successful outcomes remain safe. Relevant frontend tests, production build, scoped lint, and isolated browser journeys pass.

## Constraints and Non-goals

Keep separate Scheduler/Crawl Tasks pages, dark theme, English copy, existing APIs, storage identity, paused defaults, execution limits, and backend dispatch rules. No live crawl, paid AI, database mutation, unrelated page redesign, or backend engine changes. #73 is the presentation baseline; #11 remains broader scheduling discovery. Sibling tasks #76/#77 remain planning.

## Evidence

`research/current-workflow-audit.md` records current journey findings and code anchors. The current E2E backend lacks Scheduler endpoints; browser coverage will intercept API requests with dedicated fixtures, not use live execution.

## Tracking

Issue: https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/75
Parent: https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/74

## Verification

Automated acceptance passed; see `verification.md` for evidence and limits. Manual QA, commit, and deployment are pending.
