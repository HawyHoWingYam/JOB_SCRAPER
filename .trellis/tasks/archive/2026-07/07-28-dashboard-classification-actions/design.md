# Design: Dashboard Classification actions

## Route contract

Extend the existing Classification hash route with one validated domain target whose allowed values are the Classification page's domain IDs: `job_taxonomy` and `skill`. Keep `#classification` backward compatible by resolving it to `job_taxonomy`. Serialize tab changes through the same route helper so refresh, browser navigation, and shared links agree with visible state.

## Dashboard actions

The taxonomy card distinguishes all unassigned Jobs from the Classification-Ready subset; only the ready count is attached to the explicit Job Taxonomy action. The Skill card's threshold-ready Candidate signal navigates to the explicit Skill target. Actions communicate destination and actionable backlog count but never trigger Classification preview or mutation APIs.

## Readiness contract

Create one reusable Job Taxonomy candidate predicate: the Job is non-deleted, lacks a current Canonical Taxonomy Assignment, and has the source-attribute projection required by `process_candidate`. Use it for the Dashboard ready count and `JobTaxonomyClassificationAdapter.select_candidates` before optional source filters, ordering, and limits. Total unassigned coverage deliberately remains broader.

## Boundary and rollback

The parent task owns total/ready response fields and zero/error states. This child owns the shared readiness predicate, Classification preview alignment, and routing/navigation. Route support is additive; candidate-predicate changes remain independently testable and rollbackable.
