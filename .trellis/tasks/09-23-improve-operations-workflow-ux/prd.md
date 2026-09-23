# Improve Scheduler, Crawl Tasks, AI Enrichment, and Settings workflows

## Goal

Improve UI/UX across Scheduler, Crawl Tasks, AI Enrichment, and Settings, including the downstream workflows reached from each page. This parent tracks four independently reviewable deliverables explicitly requested by the user on 2026-09-23.

## Requirements

1. Plan and deliver one child for Scheduler authoring, review, dispatch, lifecycle management, and monitoring handoff.
2. Plan and deliver one child for Crawl Tasks discovery, detail/progress inspection, diagnostics, cancellation, and supported recovery.
3. Plan and deliver one child for AI Enrichment scope/preview, launch, monitor, stop/retry, and result follow-up.
4. Maintain coherent terminology, action hierarchy, feedback, and cross-page context across the four workflows. Preserve exact run identity and source/scope in handoffs.
5. Build on the completed local implementation of #73 (whose GitHub issue remains open). Relate Scheduler discovery to #11; this task does not close or replace either issue. Treat #61 as related enrichment correctness work, not a UI deliverable here.
6. Use ask-matt routing: requirements discovery with persisted notes, a prototype only if a decision requires a runnable answer, then reviewed design and implementation planning per child. Design and implementation plans are persisted per child.

## Acceptance Criteria

- [x] Each named page and downstream workflow has a child task, bound GitHub issue, clear scope, and testable acceptance targets.
- [x] Each child records rendered current-state findings, a reviewed interaction design, an execution plan, and relevant validation evidence before being considered delivered.
- [x] Cross-page Scheduler-to-Crawl-Task and applicable crawl-to-enrichment/result journeys preserve identity and context without dead ends.
- [x] Shared loading, empty, stale, error, confirmation, progress, and terminal-state patterns remain coherent and accessible.
- [x] Relevant frontend tests and end-to-end journeys pass at proposed 1366x768 and 1440x900 viewports; any touched backend contracts are checked. Manual QA remains a separate completion gate.

## Planning Status

Implementation explicitly authorized by the user's instruction to complete the tasks with comprehensive tests. Settings was added to the same goal by the user. All four child implementations now have persisted designs and validation evidence. Final commit and manual QA handoff follow automated integration verification.

## Constraints

Carry forward the existing dark theme, plain English interface, accessible keyboard interactions, laptop usability, and directly accessible configuration controls from #73. Preserve backend authority, data, existing capabilities, deep links, and acknowledgement semantics. Backend contract changes require explicit planning rather than incidental UI edits. Do not run paid AI jobs or live crawls for design exploration.

## Resolved interaction decisions

- Prioritize actionable states, preserved context and accurate receipts while retaining backend authority.
- Keep existing dark styling and directly accessible configuration controls.
- Preserve AI's two-slot monitor and add separate history; keep Settings drafts in memory while switching sections.
- Testing uses intercepted APIs or isolated test databases with local fake providers.

## Child Task Map

- Scheduler: `09-23-improve-scheduler-workflow-ux`
- Crawl Tasks: `09-23-improve-crawl-tasks-workflow-ux`
- AI Enrichment: `09-23-improve-ai-enrichment-workflow-ux`
- Settings: `09-23-improve-settings-workflow-ux`

## Sequencing and Non-goals

Execution order: Scheduler, Crawl Tasks, AI Enrichment, then Settings. Children can be planned independently; shared interaction decisions must be reconciled before integration. The parent owns final cross-workflow review, not duplicate implementation.

Exclude unrelated page redesigns, destructive data operations, scheduling engine replacement, new AI providers, and changes to enrichment correctness rules. Exact layouts and priority of usability pain points remain discovery decisions.

## Tracking

GitHub issue: https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/74

Child issues: #75 (Scheduler), #76 (Crawl Tasks), #77 (AI Enrichment), #78 (Settings).

## Authorized goal extension — 2026-09-23

The user instructed completion of the tasks with comprehensive tests, then explicitly added Settings UI/UX to the same goal. This supersedes the initial discovery-only authorization note above. Settings is the fourth child: `09-23-improve-settings-workflow-ux`. Execution order is Crawl Tasks, AI Enrichment, Settings, then parent integration verification. Include Settings configuration, save/validation/error recovery and AI runtime troubleshooting handoffs.
