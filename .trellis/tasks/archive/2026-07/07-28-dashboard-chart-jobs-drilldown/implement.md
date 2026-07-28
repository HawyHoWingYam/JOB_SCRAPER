# Implementation plan

1. Add failing backend response-contract tests requiring stable Subcategory and Skill codes on concrete Dashboard rows while keeping `Other` identity-free.
2. Extend the parent stats projections/schemas with canonical codes and verify label collisions cannot merge or redirect rows.
3. Add route serializer/parser tests for exact canonical Subcategory and Skill filters, refresh round-trips, invalid values, and legacy `#jobs` navigation.
4. Seed `JobBrowser` structured filters from the validated route without changing manual FilterPanel behavior.
5. Add Dashboard component tests for pointer and keyboard activation, accessible action names, and non-interactive `Other`.
6. Implement semantic row actions and navigation wiring for CategoryChart and SkillChart.
7. Run focused frontend and backend tests, lint/type/build checks, `git diff --check`, and manual refresh/share/back-navigation checks.

## Risk and rollback points

- Route encoding is the main compatibility boundary; keep legacy `#jobs` behavior covered and commit route changes separately from presentation changes.
- Never resolve chart selections from labels or Dashboard buckets.
- Do not add an `Other` or unassigned approximation merely to make every row clickable.
