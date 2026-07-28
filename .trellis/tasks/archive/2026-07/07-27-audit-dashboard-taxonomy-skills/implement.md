# Implementation plan

1. Add backend endpoint tests that reproduce the current contract gaps: deleted Skill assignments, equal-count ties, invalid/extreme limits, empty data, inactive/unassignable hierarchy nodes, matching overview/category denominators, taxonomy assigned/unassigned/ready totals, top-six/expandable-Other math, Skill processed/matched coverage and prevalence, and unresolved/ready Candidate distinct counts.
2. Introduce/reuse the non-deleted Job population seam in Skill and Job Taxonomy aggregation; return stable codes and self-consistent denominators, group Skills by stable code, and add deterministic ordering and bounded query parameters.
3. Audit all dashboard-category response consumers, then remove retired fallback schemas/fields/fixtures or document and isolate the compatibility seam.
4. Update `SkillChart` tests first for accurate visible/returned counts, keyboard-operable overflow expansion, match coverage/prevalence copy, independent unresolved/ready Candidate signals, dynamic unknown buckets, loading/error/retry, and request cleanup; then implement the component behavior.
5. Update `CategoryChart` tests first for assigned/unassigned/ready signals, visible/accessibly named full paths, keyboard-operable `Other` expansion, semantic values, empty/error/retry, and request cleanup; then implement the component behavior.
6. Add Dashboard orchestration tests for the unified manual Refresh action, per-section data/freshness state, partial failure with stale retention, retry, and abort cleanup.
7. Add a Dashboard-level contract fixture/integration test that exercises the real chart payload shapes rather than mocking both children.
8. Run backend focused stats/current-taxonomy tests, frontend chart/Dashboard tests, frontend lint/build, backend lint/type checks used by the repository, and `git diff --check`.
9. Manually verify desktop, narrow viewport, keyboard-only expansion/retry/refresh, screen-reader names, snapshot time, live counts, and that dynamic Skill buckets still append without a black screen.

## Risk and rollback points

- Response-field removal is the primary breaking compatibility risk; commit it separately from additive aggregation fields and UI changes.
- Do not change Candidate resolution policy, taxonomy catalogs, or bucket taxonomy in this task.
- Do not infer active listing state from the Python `Job.is_expired` property.
- Preserve user work in the already dirty worktree and limit implementation edits to stats/dashboard files and focused tests/specs.
