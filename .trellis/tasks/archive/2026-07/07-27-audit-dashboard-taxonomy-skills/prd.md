# Improve dashboard taxonomy and skills analytics

## Goal

Make “Jobs by Canonical Job Taxonomy” and the renamed “Top Matched Canonical Skills” trustworthy and useful by aligning population semantics, exposing coverage and readiness, making every counted item inspectable, and adding missing contract and accessibility coverage.

The default population is all non-deleted acquired jobs. “Current” refers to the latest canonical assignment, not an assertion that the source listing is still active. A future active/expired or date-range filter is separate product work.

The Dashboard is an internal Operations Dashboard, not a labor-market analytics product. These two sections are operational corpus snapshots: they help an operator understand canonical-assignment health and the distribution of the retained Published Job Corpus without claiming to describe current market demand.

## Background

- Overview and Job Taxonomy currently exclude deleted Jobs, while Skill aggregation does not join Jobs and cannot apply the same population filter (`backend/app/api/stats.py:75-125`, `:128-200`).
- Skill stats return a global Top-N, but the UI renders only four rows per bucket while its badge counts every grouped row as “shown” (`frontend/src/components/charts/SkillChart.jsx:133-174`).
- The Skill ranking contains only current resolved canonical assignments. Candidate, generic, and rejected mentions are excluded, despite the current “Requested Skills” title (`backend/app/job_intelligence/current_taxonomies/enrichment.py:275-405`; `frontend/src/components/charts/SkillChart.jsx:136-149`).
- Job Taxonomy Classification preview selects all non-deleted unassigned Jobs, but processing requires a source-attribute projection; the current preview can therefore admit predictably failing Jobs (`backend/app/services/classification_domain_adapters.py:444-510`; `backend/app/job_intelligence/source_attributes/module.py:170-174`).

## Requirements

- Apply one explicit Dashboard population contract to overview, Job Taxonomy, and Skill aggregates: include non-deleted acquired Jobs, preserve the Dashboard as an internal operational surface, and never imply that the corpus represents active listings or current market demand.
- Describe Job Taxonomy results as current accepted canonical assignments and show assignment coverage against that shared population.
- Make Canonical Assignment Coverage the primary Job Taxonomy signal: show assigned Jobs, unassigned Jobs, and their coverage rate before the distribution of accepted assignments.
- Distinguish all unassigned Jobs from the Classification-Ready subset that has the required source-attribute projection. Coverage uses all unassigned Jobs; the Classification action reports only the ready subset.
- Expose the taxonomy unassigned signal as a navigation action to the Job Taxonomy Classification target; route implementation is owned by child task `07-28-dashboard-classification-actions`.
- Keep the top-six taxonomy summary compact, but make `Other` expandable so every counted canonical path remains inspectable. The aggregate `Other` row is not itself a taxonomy identity.
- Rename “Top Requested Skills” to “Top Matched Canonical Skills” and keep the ranking canonical-only. Do not mix unresolved Candidate Mentions, generic tags, or rejected terms into the same leaderboard.
- Report Canonical Skill Match Coverage as distinct successfully enriched, non-deleted Jobs with at least one current canonical Skill assignment divided by successfully enriched, non-deleted Jobs. Jobs still awaiting enrichment are outside this denominator.
- Show each ranked Skill's distinct Job count and Canonical Skill Prevalence against the same successfully enriched, non-deleted cohort. State that multi-Skill prevalence values are independent and do not sum to 100%.
- Surface an “Unresolved Skill Candidates” signal with total unresolved Candidate count, affected distinct Job count, and the subset currently meeting the configured automatic Classification threshold. Keep it separate from the Top Matched Canonical Skills ranking and link it to the Classification surface.
- Navigate threshold-ready Skill Candidates to the Skill Classification target without starting a batch; route implementation is owned by child task `07-28-dashboard-classification-actions`.
- Preserve one global Top-N ranking for Matched Canonical Skills. Dashboard buckets are presentation groups only and must not impose quotas or change membership/rank. Every returned Skill must be reachable through visible rows or operable expansion, and summary copy must distinguish visible from returned rows.
- Make aggregate ordering deterministic, validate or bound caller-controlled limits, and preserve dynamically introduced non-empty dashboard buckets.
- Remove retired fallback fields from the Job Taxonomy dashboard contract and fixtures, or explicitly isolate them behind a documented compatibility boundary if a consumer is discovered before implementation.
- Expose full taxonomy paths without relying on hover-only `title` text, and give chart/list values accessible structure and names.
- Provide meaningful loading, empty, error, and retry states without setting state after unmount.
- Display when the current Dashboard snapshot was loaded and provide one page-level manual Refresh action that reloads all Dashboard sections. Automatic polling is out of scope.
- Isolate partial failures by section: successful sections may update, while a failed section retains its last successful data only when visibly marked stale with its own timestamp and retry state.
- Add backend response-contract tests plus focused frontend tests for population filtering, ordering/ties, truncation/expansion, dynamic buckets, empty/error states, and accessible names.

## Acceptance Criteria

- [ ] Overview, Job Taxonomy, and Skill aggregates use and test the same non-deleted-job population, with copy that does not call that population active/current listings.
- [ ] Skill counts exclude deleted jobs, have deterministic tie ordering, and reject or clamp unsafe limits.
- [ ] The Skill UI never says an item is “shown” when it is hidden; all returned grouped skills are keyboard- and pointer-accessible through visible rows or an expand/collapse control.
- [ ] The Skill UI is titled “Top Matched Canonical Skills”, explains that unresolved Candidate Mentions are outside the ranking, and never labels the result as complete market demand.
- [ ] The Skill UI reports matched-Job count, enriched-Job denominator, and Canonical Skill Match Coverage without treating pending enrichment as a failed Skill match.
- [ ] Every ranked Skill reports both distinct Job count and Canonical Skill Prevalence using the response's processed denominator, without presenting the percentages as a composition.
- [ ] The Skill card reports unresolved active Candidate count, affected distinct Jobs without cross-Candidate double-counting, and threshold-ready Candidate count using the current runtime setting; its Classification destination does not imply that below-threshold Candidates are immediately actionable.
- [ ] The Job Taxonomy UI reports accepted-assignment coverage against the matching overview denominator and exposes each full taxonomy breadcrumb to assistive technology and touch users.
- [ ] The Job Taxonomy card makes assigned count, unassigned count, and Canonical Assignment Coverage visible before presenting the top distribution among assigned Jobs.
- [ ] The Job Taxonomy card separately reports Classification-Ready unassigned Jobs and never implies that every unassigned Job can be processed immediately.
- [ ] Expanding taxonomy `Other` reveals every constituent canonical path with its count and full breadcrumb; collapsing restores the compact Top 6 view without losing keyboard focus or accessible state.
- [ ] Retired fallback fields and stale fallback fixtures are removed unless an implementation-time consumer audit proves that a compatibility seam is still required.
- [ ] Both sections expose accessible loading, empty, error/retry, list/chart semantics, and retain responsive layouts.
- [ ] The page exposes a human-readable refresh status and accessible Refresh action; each data section exposes its last-successful time when section freshness differs.
- [ ] A partial refresh failure does not blank or roll back successful sections. A failed section never presents retained data as fresh and exposes an accessible error/retry state.
- [ ] Backend tests cover deleted jobs, assignment/node eligibility, ties, limits, top-six/Other math, and empty data; frontend tests cover visible/hidden counts, expansion, dynamic buckets, full paths, error/retry, and accessible names.
- [ ] Existing dashboard and current-taxonomy suites pass, including the dynamic unknown-bucket regression.

## Out of Scope

- Labor-market analytics, active/expired and date-range filters, and historical trend charts.
- Automatic Dashboard polling.
- Candidate auto-classification policy, taxonomy catalog redesign, and bucket taxonomy redesign.
- Jobs deep-link and Classification target-route implementation, which are owned by the child tasks below.

## Notes

- Implementation starts only after the user reviews these planning artifacts and explicitly approves `task.py start`.
- The operational-corpus product boundary is recorded in `docs/adr/0002-dashboard-operational-corpus-snapshot.md`.
- Concrete taxonomy/Skill Jobs drill-down is planned separately in child task `07-28-dashboard-chart-jobs-drilldown`; this parent supplies stable response identities but does not own route or JobBrowser implementation.
- Coverage-gap Classification actions are planned separately in child task `07-28-dashboard-classification-actions`; this parent supplies accurate unassigned/Candidate counts but does not own target-route implementation.
