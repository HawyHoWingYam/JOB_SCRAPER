# Implementation plan

1. Add backend tests proving the shared Job Taxonomy readiness predicate excludes deleted, already-assigned, and missing-source-projection Jobs while respecting optional source filters and limits.
2. Reuse that predicate in the Dashboard ready count and `JobTaxonomyClassificationAdapter.select_candidates`, with contract tests proving their populations match.
3. Add route parser/serializer tests for bare Classification, both allowed domain targets, invalid targets, refresh, and browser navigation.
4. Make `ClassificationBatchesPage` derive its initial/current domain from the validated route and serialize user tab changes without triggering batch mutations.
5. Add Dashboard action tests for taxonomy-ready → Job Taxonomy and threshold-ready Skill Candidate → Skill, including accessible names and zero-backlog behavior.
6. Wire the two actions through the application navigation boundary without duplicating route strings in chart components.
7. Run focused backend candidate, route, Dashboard, Classification page, lint/build, and `git diff --check` validation; manually verify preview parity, refresh, back/forward, keyboard use, and that no preview/start request fires on navigation.

## Risk and rollback points

- Preserve legacy `#classification` as Job Taxonomy.
- Treat unknown domain values as invalid input and fall back safely.
- Keep navigation separate from all Classification mutation calls.
