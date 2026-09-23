# Scheduler verification — 2026-09-23

## Outcome

Approved Scheduler board/authoring workflow improvements implemented. Quality gate passed; work committed as `43b245e1` (implementation) and `d09ec64b` (planning). Not pushed or deployed. Issue #75 remains open pending manual QA. Siblings #76 and #77 remain planning.

## Automated checks

- `npm test -- src/features/taskControl`: 46 tests passed across 9 files.
- `npm test`: 242 tests passed across 34 files on the final source changes.
- `npm run lint`: passed across the frontend.
- `npm run build`: passed.
- `npx playwright test --config playwright.scheduler.config.js`: 5 scenarios passed (12.6s final browser run). Dedicated Vite process and fully intercepted `/api/` requests; no backend/database or live crawler/AI mutation.
- `git diff --check`: passed.
- JavaScript package has no separate type-check script.

## Browser evidence and journeys

- `research/before-board-1366.png` and `before-board-1440.png`: populated baseline; wide table caused horizontal overflow with actions beyond the viewport.
- `research/before-wizard-1366.png` and `before-wizard-1440.png`: baseline new Automation authoring.
- `research/after-board-1366.png` and `after-board-1440.png`: responsive board, visible header actions, source context, refresh time, and ordered Automation list.
- `research/after-review-1366.png` and `after-review-1440.png`: editable review, meaningful summary and sticky action area.
- `research/after-wizard-1280.png`: explicit source at entry and clear listing/detail intent choices.

Main agent visually inspected representative before/after board and after wizard/review captures. Screenshots show the app viewport (the main content has its own scroll container), not every vertical state in one image. Browser scenarios scroll to and operate the controls.

Browser coverage: existing edit opens configuration, edits survive reload, review correction obtains new authority, save sends changed settings without lifecycle mutation, success reports paused state; guided new Automation and One-off launch; exact resulting Task link and no duplicate submit control; saved run versus independent one-off; OfferToday return context; 760px keyboard step navigation and browser Back. Browser geometry asserts no page-level horizontal overflow at laptop and narrow sizes.

## Regression coverage

Component/reducer tests cover restored incompatible detail scope/backlog, expired plans, latest/fingerprint authority fencing, current review payloads, in-memory navigation with unavailable storage, load retry, paused receipts, visible disabled reasons, stale-board retry, request-only cancellation feedback, and existing cancellation-acknowledgement polling. Existing source-specific OfferToday/CTGoodJobs behavior remains covered.

## Limits and review

Backend/API contracts, default paused state, execution caps, and dispatch rules unchanged. No live service deployment or end-to-end backend execution performed. The broader database-backed Playwright suite was not run; the new suite specifically closes the prior Scheduler fixture gap. Manual QA is still needed with representative real operational data before issue closure.

Specification updates record responsive board action presentation, direct editing and history/draft behavior, pre-review validation, clear receipts, and safe isolated browser fixtures. Corrected the spec's draft-key description to the actual existing `DRAFT_PREFIX`; no storage migration was introduced.
