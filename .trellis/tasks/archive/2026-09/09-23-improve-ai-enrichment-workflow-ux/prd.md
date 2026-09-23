# Improve AI Enrichment page and end-to-end workflow UX

## Goal

Make AI Enrichment scope selection, launch, monitoring, exception handling, and result follow-up understandable as one complete workflow.

## Requirements

1. Cover overview metrics, Origin and classification filters, run limit, eligibility/exclusion preview, all-pending acknowledgement, launch, monitor, Stop, failed-item retry, and supported cancelled-backfill continuation.
2. Explain matching, effective, excluded, completed, failed, and cancelled counts; distinguish no eligible work from loading, preview failure, readiness failure, and active-run conflicts.
3. Make waiting on linked crawls/profile readiness, running, stopping, and terminal outcomes understandable, including what the operator can do next.
4. Keep retry tied to its run and failure scope, preserve cooperative Stop and non-persistent all-pending acknowledgement, and never reinterpret exclusions as provider failures.
5. Clarify existing result and exclusion follow-up destinations without widening the selected scope. Retain current monitor/filter behavior unless a reviewed design explicitly revises its UI contract; coordinate with #61 without absorbing its enrichment-data semantics work.

## Acceptance Criteria

- [x] A filtered run can be scoped, previewed, launched, identified, and monitored with the same run identity; zero/error/stale previews cannot launch guessed work.
- [x] Manual Entry and external origins retain correct cascading filter behavior; all-pending confirmation remains explicit and transient.
- [x] Waiting, running, stopping, completed, completed-with-failures, completed-with-exclusions, cancelled, and failed states have correct counts, explanations, and supported actions.
- [x] Retry targets only the chosen run failures; Stop explains in-flight completion; follow-up links retain bounded scope where supported.
- [x] Focused preview/persistence/conflict/action tests and browser journeys pass at target laptop sizes using fixtures, with before/after evidence and keyboard checks.

## Planning Status

Implementation authorized by the user's instruction to complete the tasks and subsequent confirmation. Keep the two-slot monitoring policy and add a separate inspectable history surface. Prioritize scope accuracy, durable run identity, and actionable waiting/failure states.

## Constraints

Carry forward the existing dark theme, plain English interface, accessible keyboard interactions, laptop usability, and directly accessible configuration controls from #73. Preserve backend authority, data, existing capabilities, deep links, and acknowledgement semantics. Backend contract changes require explicit planning rather than incidental UI edits. Do not run paid AI jobs or live crawls for design exploration.

## Design decisions

See `design.md` for the approved-scope implementation choices and `verification.md` for checks and rendered evidence. Preserve normalized backend authority and improve context, actionable feedback and downstream navigation.

## Evidence and Entry Points

- `frontend/src/components/ai/AIEnrichmentPage.jsx`
- `.trellis/spec/frontend/ai-enrichment-console.md`
- `.trellis/spec/backend/ai-enrichment-runs.md`

These are source/spec inspection entry points, not a rendered UX audit or confirmed defects.

## Dependencies and Non-goals

No hard dependency on sibling completion is established. Coordinate shared components, terminology, and handoffs through the parent task. Exclude unrelated pages, backend engine redesign, data migration, and model/provider changes.

## Tracking

GitHub issue: https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/77

Parent issue: https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/74
