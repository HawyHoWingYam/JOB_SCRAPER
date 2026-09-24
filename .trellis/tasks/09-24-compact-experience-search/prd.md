# Compact experience labels and search contract

## Goal

Compact experience labels on cards and details while preserving original bounds, provenance, and interval-overlap search.

## Requirements

- Search cards and Job Detail share one compact label: range/minimum `N+`,
  explicit zero `0+`, upper-only `≤N`, unspecified `Not specified`, and inferred
  minimum `About N+` with estimated provenance.
- Detail retains the original minimum/maximum range and evidence explanation.
- Search API returns the experience data needed by cards without N+1 reads.
- Compact labels never change inclusive overlap against original stored bounds.
- Applied filter summaries describe the query range rather than the compact Job
  label. Issue #61 owns inferred-window generation and historical repair.

## Acceptance Criteria

- [ ] Search cards and details render all agreed label cases consistently.
- [ ] A `[1,2]` Job and `[1,5]` Job both display `1+`; query `[3,4]` excludes
  the first and includes the second in lexical, semantic/hybrid candidate,
  facet, and export paths.
- [ ] Detail exposes full bounds/source and never presents unspecified fallback
  as an employer requirement.
- [ ] Frontend component, backend contract, and browser E2E tests pass.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
