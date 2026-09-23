# Improve UI/UX usability

## Goal

Make the existing Job Scraper easier to read, understand, operate, and monitor on an ordinary laptop. Support both primary workflows: inspecting results and handling exceptions while configured work proceeds, and deliberately arranging individual runs with clear progress and next steps.

## Background and Evidence

The user reports friction across browsing, collection, monitoring, enrichment, and governance, and confirms all four problem dimensions: visual density/readability, confusing language, excessive interaction effort, and unclear feedback. The user approved the consolidated plan and implementation, explicitly requiring backend compatibility and passing frontend E2E tests.

- Nine peer navigation entries currently appear above Settings (`frontend/src/components/Sidebar.jsx:6`).
- Scheduler offers New Automation and One-off Run (`frontend/src/features/taskControl/board/TaskControlBoardPage.jsx:204`); execution history is separate (`frontend/src/components/scraper/CrawlTasksPage.jsx:846`). Its board contains developer-facing explanations at :204 and :218.
- Job Browser distinguishes draft edits and applied layers (`frontend/src/components/JobBrowser.jsx:710`, `frontend/src/components/JobBrowser.jsx:933`). Local browser inspection at 1366×768 showed no result rows in the initial viewport because search/filter panels and the following Jev section precede them.
- The observed collection failure card has two Task-labelled buttons; whether their targets duplicate each other remains to be traced. The AI monitor shows raw status values and timestamps, and the zero-pending form does not clearly explain why there are no options. Rendered evidence and limitations are recorded in design.md.

## Requirements

### R1 — Shared presentation

Retain the dark theme and use consistent, plain English for interface copy. Improve typography, contrast, spacing, grouping, and action emphasis on ordinary laptops. Keep existing configuration controls directly accessible; do not add an Advanced Options disclosure as the default simplification mechanism. This does not require expanding existing disclosures. Preserve source content and proper names.

### R2 — Navigation

Keep Dashboard as the default entry. Use always-expanded groups: Data (Job Browser, Add Job, Companies), Collection (Scheduler, Crawl Tasks, OfferToday Keywords), Processing (AI Enrichment, Classification). Keep Settings at the bottom. Each destination remains one click away.

### R3 — Job Browser

Use a compact top search/mode/action area, visible left-side filters, and right-side results/count/export. Show result rows within the initial laptop viewport when results exist. Apply edits only after a user click, distinguish pending edits from applied conditions, and acknowledge loading. Preserve layered search, retrieval modes, facet behavior, and export of the successfully applied result scope. Failed application retains previous results and applied conditions.

### R4 — Collection workflow

Keep Scheduler and Crawl Tasks separate. Improve authoring-to-run continuity using the exact run identity, make lifecycle states understandable, distinguish action acknowledgement from execution, and label task/log/recovery actions by their actual purpose. Keep diagnostics accessible and preserve available server-authorized actions.

### R5 — AI processing

Explain metrics, queue eligibility, run status, timestamps, and action availability in operator-facing English. Clearly distinguish no eligible work, loading, request failure, running, completed, and completed-with-failures states. Keep existing preview, scope acknowledgement, retry, and stop semantics.

### R6 — Remaining pages

Apply the same visual, wording, form-feedback, empty-state, and error-state standards to Dashboard, Add Job, Companies, Classification, OfferToday Keywords, Settings, and related detail surfaces. Preserve each page's capabilities and data meanings. Prioritize concrete inconsistencies found during inspection; do not force every page into identical geometry.

## Acceptance Criteria

- [x] AC1 / R1: At 1366×768 and 1440×900, primary controls and text are legible, no page-level horizontal overflow obscures actions, and wide tables scroll within their own region when needed. Ordinary labels/body copy target at least 14px; smaller auxiliary text remains legible. Interactive elements have visible keyboard focus and associated names. Color is not the sole status indicator.
- [x] AC2 / R2: All current destinations remain accessible through the approved expanded groups; existing deep links work and Dashboard remains the default.
- [x] AC3 / R3: With a representative populated fixture and no blocking error, at least the first result row is visible without scrolling at both target sizes. Filters remain reachable without a new advanced-settings gate.
- [x] AC4 / R3: Editing filters alone leaves results unchanged; explicit apply updates results on success. Pending edits, applying, and failure are visible. Replace/refine/edit/remove/clear, pagination, same-tab restoration, facet recovery, and export continue to obey existing contracts.
- [x] AC5 / R4: After a successful dispatch, the exact run is identifiable and directly accessible. Pending cancellation is not reported as completed. Distinct task/log actions are identifiable; any duplicate removal is justified by target/action equivalence.
- [x] AC6 / R5: Empty eligible queues explain why no run can start; API errors are not reported as empty queues. Known statuses and timestamps are readable, IDs remain copyable, and retry/stop retain their existing scope and acknowledgement behavior.
- [x] AC7 / R6: Every named page is reviewed at laptop size with findings recorded; loading, empty, success, error, and validation states are checked where applicable. No capability is removed and backend contracts remain unchanged.
- [x] AC8 / R1–R6: Frontend checks and relevant behavior tests pass, with rendered before/after evidence for Job Browser, collection, and AI processing and a cross-page regression review.
- [x] AC9 / Integration: Existing backend/API contracts, frontend data loading, and server-authorized actions continue to work without backend regressions. Run relevant backend tests for touched contracts and verify the frontend against the configured API path.
- [x] AC10 / E2E: Frontend end-to-end tests pass after the UI changes. Run the existing E2E suite as configured and add or run focused browser coverage for changed navigation and workflows; report environment-only limitations separately.

Viewport sizes and numeric presentation targets are proposed engineering acceptance targets, not user-specified hardware.

## Out of Scope

New business features, backend/API/schema changes, new background automation, changed search or classification semantics, a merged collection workspace, dedicated mobile redesign, a light theme, and a multilingual framework. If an improvement requires changing a business rule, return that specific trade-off for discussion. Backend behavior must remain healthy and be verified alongside frontend work.

## Review Gate

The user approved all three artifacts and implementation. See verification.md for test evidence and the pre-existing live deployment mismatch. The user approved the commit, recorded as 6d686d00, and subsequently authorized coordinated service replacement with business data retained. This operational rollout adds no business feature or schema design change; it deploys the current schema through the existing cutover contract.
