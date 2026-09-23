# UI/UX Usability Design — Review Draft

Status: implementation approved and completed. See verification.md for test results and the existing live deployment mismatch.

## Confirmed Design Constraints

Retain Dashboard as the default entry, use English as the primary interface language, retain the dark theme, and design primarily for ordinary laptop viewports. Keep configuration controls directly accessible rather than introducing an Advanced Options disclosure as a general simplification strategy. Support both result/exception monitoring and deliberate run authoring.

## Approved Navigation Direction

Keep Dashboard directly accessible. Group existing sidebar destinations under non-collapsible headings:

- Data: Job Browser, Add Job, Companies.
- Collection: Scheduler, Crawl Tasks, OfferToday Keywords.
- Processing: AI Enrichment, Classification.
- Keep Settings accessible in its existing footer position.

The user approved these presentation groups. They are not new domain concepts or route changes. Existing English destination names are retained in this draft pending a semantic review. Grouping related work adds no navigation click. Group spacing must fit laptop height without displacing common actions unnecessarily.

Evidence: frontend/src/components/Sidebar.jsx defines the current flat destination list; frontend/src/App.jsx and appRoute.js define page selection. The collection board starts runs and links to Crawl Tasks for execution details. Navigation regrouping alone does not resolve cross-page continuity.

## Search Application Boundary

The user selected explicit click-to-apply filtering rather than immediate result updates. Preserve the existing draft versus successfully applied scope boundary and layered search semantics documented in `.trellis/spec/backend/job-browser-search.md`. Present pending changes, request progress, and applied conditions distinctly. A failed submission must retain previous results and applied scope; export must continue to target applied results. Exact labels for replace, refine, and edit actions must preserve their different effects instead of flattening them into an ambiguous single action.

## Collection Page Responsibilities

The user confirmed keeping Scheduler and Crawl Tasks separate. Preserve their authoring versus execution-history responsibilities. Improve the handoff to the exact run and distinguish the action acknowledgement from actual execution state. The existing wizard already provides a View task link; inspect and improve continuity rather than assuming this link is absent. Do not introduce a merged collection workspace.

## Visual Inspection

Inspect small uppercase labels, muted text, table density, and action emphasis against realistic page states at 1366×768 and 1440×900. Existing shared styles live in frontend/src/index.css and App.css; Sidebar.css currently fixes desktop sidebar width at 268px. Determine actual changes through rendered inspection rather than assuming all small labels or dense layouts are defective.

## Evidence from Initial Inspection

### Rendered Observations: Collection and AI

Read-only local browser inspection at 1366×768 found:

- Scheduler opens a page titled Task Control Board. Its subtitle says "Server-owned sections, normalized run authority, and current Automation actions." The automation section says "Backend order is preserved." These implementation descriptions do not explain the operator's next action. Source anchors: frontend/src/features/taskControl/board/TaskControlBoardPage.jsx:204 and :218.
- The observed JobsDB failure card displays RUN_FAILED, a disconnect summary, and two separate buttons both labelled Task alongside Logs and Dismiss. Their targets were not inspected; do not assume they are duplicates before tracing their actions. Evidence: `.playwright-mcp/page-2026-09-23T09-35-12-049Z.png`.
- The AI monitor displays manual_pending and completed_with_failures as raw labels, a full UUID prominently, and an ISO timestamp. Its description says "Active plus latest terminal, or the latest two terminal runs." In the observed zero-pending state, filter groups say No options while the form says Choose filters to preview the run. Evidence: browser accessibility snapshot of `http://localhost:3000/#ai` on 2026-09-23. Confirm data semantics before revising copy.

Proposed presentation improvements: operator-focused English descriptions, readable status names and local date/time with timezone context, identifiable action labels, and explicit explanations for unavailable actions or empty queues. Preserve raw IDs and diagnostics for traceability. These observations do not establish recovery correctness or authorize executing/retrying live jobs.

### Rendered Observation: Job Browser

Read-only inspection of the locally served application at `http://localhost:3000/#jobs`, viewport 1366×768, showed the initial viewport occupied by a query panel and a tall filter panel, with the start of a Jev search relevance section below them and no Job result rows visible. The query panel ends noticeably above the filter panel, leaving unused space below it. Evidence: `.playwright-mcp/page-2026-09-23T09-33-31-632Z.png`. This is one observed local runtime state, not a completed audit or proof of parity with every current source file.

The user approved prioritizing visible result rows with a compact query/action bar above, directly visible filters on the left, and results/count/export on the right. Keep configuration available; avoid solving the space issue solely by reducing text size. Clearly distinguish pending filter edits from applied conditions. Placement of the Jev section and exact filter geometry remain subject to contract inspection and layout validation.

## Implementation Design for Review

### Ownership and boundaries

Implement this as one coordinated frontend task in sequential slices. Shared typography, controls, and navigation affect every page, so a common integration gate is more useful than independently activating multiple child tasks. The main session implements and validates; exploration may be delegated read-only. This task owns the cross-page acceptance matrix in prd.md.

Use existing shared CSS tokens and component boundaries first. Avoid creating a generic page framework or a second state model. Scoped page styles own layout exceptions. Check for hardcoded colors and page-specific overrides before changing shared tokens. Retain the dark palette with clearer text/action hierarchy; aim for normal-text contrast of 4.5:1 and non-text control/focus contrast of 3:1 where applicable, measuring the changed combinations.

### Job Browser layout and data flow

Restructure presentation around the existing stateful search component. Place the search/action area above a filter/results grid; use a roughly 260–300px filter column and a flexible results column, tuning against rendered target sizes. Keep filters visible and let the document scroll naturally. Put result count, export, and applied scope summary near the result list. Keep Jev controls accessible after primary results or in an appropriately sized adjacent section; do not let them precede the first visible result or alter paid-run confirmation semantics.

Keep current request owners, abort/generation handling, layered scope identities, and successful-scope persistence. Results and facet refresh remain independent. Explain mode and action effects in concise English; use distinct labels for searching all Jobs, refining current results, and applying edits to an existing layer. Export continues to consume applied scope, never draft state.

### Collection and processing

Preserve board/wizard/history routes and server action authority. Replace implementation-oriented prose with user intent and next-action guidance. Trace the two Task buttons before renaming or deduplicating them. Link acknowledgement to the created run; existing View task behavior is the starting point. Show understandable lifecycle labels without converting stop-requested/cancelling into terminal success.

Map known AI display codes to readable text without mutating payload values. Prefer readable local dates with explicit timezone context; handle missing/invalid dates truthfully. Keep run identifiers available for copying. Explain why initiation is disabled using actual eligibility/loading/error state. Do not infer a zero queue from a failed request.

### Other pages

Inspect Dashboard, Add Job, Companies, Classification, OfferToday Keywords, Settings, and detail views before editing their exact code. Standardize title/action hierarchy, readable field labels, inline validation, action acknowledgement, empty-state guidance, and user-facing English. Preserve glossary meanings and existing evidence, duplicate-review, upload-preview, settings, and governance contracts. No new domain concept has been agreed, so no glossary or ADR change is necessary merely to record layout decisions.

### Compatibility and rollback

Preserve hash routes, API shapes, storage keys, persisted drafts, action permissions, and source/governed identities. No migration is expected. Keep shared styling, search layout, and workflow copy changes separable so a problematic slice can be reverted without affecting data. Validate with read-only live inspection and deterministic mocked interactions; do not dispatch real crawl, AI, paid Jev, or governance work merely to check presentation.

### Validation limits

Current browser observations describe one locally served state, not guaranteed source/build parity. Reproduce screenshots against the implementation checkout before comparing. Initial page-level details for R6 remain inspection work within the approved standards, rather than unapproved product decisions. Any contract change or removed capability reopens planning.
