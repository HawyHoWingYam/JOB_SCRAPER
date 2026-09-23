# Improve Crawl Tasks page and end-to-end workflow UX

## Goal

Make finding, inspecting, monitoring, and handling Crawl Tasks a coherent workflow with clear outcomes and next steps.

## Requirements

1. Cover the task list, filters, task selection/deep links, normalized Task Details, listing/detail progress, diagnostics and audit events, cancellation, and supported manual recovery.
2. Clarify current state, source/scope, progress denominators, saved/remaining work, blocking reason, and the next supported action.
3. Improve list-to-detail navigation and return context; make task details, diagnostics, and recovery destinations distinguishable.
4. Keep cancellation pending until backend acknowledgement and show recovery actions only when declared capabilities allow them; do not invent terminal detail recovery dispatch.
5. Clarify handoffs from Scheduler and toward existing result/processing surfaces where supported, preserving task identity and scope. Build on #73 rather than assuming previously fixed problems still exist.

## Acceptance Criteria

- [ ] A task linked from Scheduler loads directly even when absent from the current list page; returning to the list preserves or predictably restores user context.
- [ ] Running, waiting/manual action, cancelling, cancelled, failed, and completed scenarios each show accurate progress and appropriate supported actions.
- [ ] An operator can inspect diagnostics, request cancellation, and follow capability-gated recovery without confusing request success with task completion.
- [ ] Loading, no matches, unknown task, API failure, and stale refresh remain distinguishable; focused task tests and end-to-end monitoring/recovery journeys pass at target laptop sizes.

## Planning Status

Discovery backlog created at the user's explicit request. Scope and acceptance below are proposed planning targets, not an approved interaction design. No implementation is authorized by this task creation. Before implementation, inspect rendered workflows, resolve product decisions, and prepare reviewed `design.md` and `implement.md`.

## Constraints

Carry forward the existing dark theme, plain English interface, accessible keyboard interactions, laptop usability, and directly accessible configuration controls from #73. Preserve backend authority, data, existing capabilities, deep links, and acknowledgement semantics. Backend contract changes require explicit planning rather than incidental UI edits. Do not run paid AI jobs or live crawls for design exploration.

## Open Questions

- Which friction should lead the redesign: information hierarchy/readability, too many steps/unclear navigation, or understanding progress and recovery? Recommended starting point: map the full workflow and prioritize unclear next actions, then refine visual hierarchy; confirm during discovery.
- Which proposed layout and interaction changes best resolve the observed friction? Capture rendered evidence and review a concrete proposal before implementation.

## Evidence and Entry Points

- `frontend/src/components/scraper/CrawlTasksPage.jsx`
- `.trellis/spec/frontend/task-control-board-ui.md`
- `.trellis/spec/frontend/crawl-task-pacing-snapshot-ui.md`
- `.trellis/spec/backend/crawl-task-detail-metrics.md`

These are source/spec inspection entry points, not a rendered UX audit or confirmed defects.

## Dependencies and Non-goals

No hard dependency on sibling completion is established. Coordinate shared components, terminology, and handoffs through the parent task. Exclude unrelated pages, backend engine redesign, data migration, and model/provider changes.

## Tracking

GitHub issue: https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/76

Parent issue: https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/74
