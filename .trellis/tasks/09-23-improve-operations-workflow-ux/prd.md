# Improve Scheduler, Crawl Tasks, and AI Enrichment workflows

## Goal

Improve UI/UX across Scheduler, Crawl Tasks, and AI Enrichment, including the downstream workflows reached from each page. This parent tracks the three independently reviewable deliverables explicitly requested by the user on 2026-09-23.

## Requirements

1. Plan and deliver one child for Scheduler authoring, review, dispatch, lifecycle management, and monitoring handoff.
2. Plan and deliver one child for Crawl Tasks discovery, detail/progress inspection, diagnostics, cancellation, and supported recovery.
3. Plan and deliver one child for AI Enrichment scope/preview, launch, monitor, stop/retry, and result follow-up.
4. Maintain coherent terminology, action hierarchy, feedback, and cross-page context across the three workflows. Preserve exact run identity and source/scope in handoffs.
5. Build on the completed local implementation of #73 (whose GitHub issue remains open). Relate Scheduler discovery to #11; this task does not close or replace either issue. Treat #61 as related enrichment correctness work, not a UI deliverable here.
6. Use ask-matt routing: requirements discovery with persisted notes, a prototype only if a decision requires a runnable answer, then reviewed design and implementation planning per child. These are discovery backlog tasks, not finalized implementation tickets.

## Acceptance Criteria

- [ ] Each named page and downstream workflow has a child task, bound GitHub issue, clear scope, and testable acceptance targets.
- [ ] Each child records rendered current-state findings, a reviewed interaction design, an execution plan, and relevant validation evidence before being considered delivered.
- [ ] Cross-page Scheduler-to-Crawl-Task and applicable crawl-to-enrichment/result journeys preserve identity and context without dead ends.
- [ ] Shared loading, empty, stale, error, confirmation, progress, and terminal-state patterns remain coherent and accessible.
- [ ] Relevant frontend tests and end-to-end journeys pass at proposed 1366x768 and 1440x900 viewports; any touched backend contracts are checked. Manual QA remains a separate completion gate.

## Planning Status

Discovery backlog created at the user's explicit request. Scope and acceptance below are proposed planning targets, not an approved interaction design. No implementation is authorized by this task creation. Before implementation, inspect rendered workflows, resolve product decisions, and prepare reviewed `design.md` and `implement.md`.

## Constraints

Carry forward the existing dark theme, plain English interface, accessible keyboard interactions, laptop usability, and directly accessible configuration controls from #73. Preserve backend authority, data, existing capabilities, deep links, and acknowledgement semantics. Backend contract changes require explicit planning rather than incidental UI edits. Do not run paid AI jobs or live crawls for design exploration.

## Open Questions

- Which friction should lead the redesign: information hierarchy/readability, too many steps/unclear navigation, or understanding progress and recovery? Recommended starting point: map the full workflow and prioritize unclear next actions, then refine visual hierarchy; confirm during discovery.
- Which proposed layout and interaction changes best resolve the observed friction? Capture rendered evidence and review a concrete proposal before implementation.

## Child Task Map

- Scheduler: `09-23-improve-scheduler-workflow-ux`
- Crawl Tasks: `09-23-improve-crawl-tasks-workflow-ux`
- AI Enrichment: `09-23-improve-ai-enrichment-workflow-ux`

## Sequencing and Non-goals

Suggested discovery order follows the user's list: Scheduler, Crawl Tasks, AI Enrichment. This is a recommendation, not a hard blocking dependency. Children can be planned independently; shared interaction decisions must be reconciled before integration. The parent owns final cross-workflow review, not duplicate implementation.

Exclude unrelated page redesigns, destructive data operations, scheduling engine replacement, new AI providers, and changes to enrichment correctness rules. Exact layouts and priority of usability pain points remain discovery decisions.

## Tracking

GitHub issue: https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/74

Child issues: #75 (Scheduler), #76 (Crawl Tasks), #77 (AI Enrichment).
