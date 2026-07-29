# Implementation Plan: Improve company and Data Explorer experience

## Preconditions

- [x] User reviews and approves `prd.md`, `design.md`, and this plan.
- [x] Activate the task only after approval with `task.py start`.
- [x] Load `trellis-before-dev` and the relevant frontend/backend specs before source edits.
- [x] Preserve the existing dirty worktree; inspect diffs before touching every target file.

## 1. Company run-size presentation

- [x] Add/adjust the Companies page test first so the numeric control is visibly distinct from the checkbox, keeps default `50`, exposes no maximum, accepts `100000`, and renders the safe-default/no-product-maximum hint.
- [x] Narrow the checkbox CSS selector in `frontend/src/components/companies/CompaniesPage.css` and give the number input a normal responsive width.
- [x] Add concise explanatory copy in `frontend/src/components/companies/CompaniesPage.jsx`; do not change `useCompanyEnrichmentRun` submission semantics.
- [x] Run `cd frontend && npm test -- --run src/components/companies/CompaniesPage.test.jsx`.

## 2. Responsive applied-Layer cards

- [x] Extend `frontend/src/components/JobBrowser.test.jsx` around the existing add/edit/remove/clear test to assert the Applied Layers section, per-card action grouping, condition list, and Clear all placement without changing accessible action names.
- [x] Refactor only the scope-trail markup in `frontend/src/components/JobBrowser.jsx` into section header, list, card header/actions, and summary regions.
- [x] Replace the current inline-flex rules in `frontend/src/components/JobBrowser.css` with contained full-width cards, `min-width: 0`, wrapping summaries, and a narrow-screen stacked action layout.
- [x] Manually inspect at desktop width and 320px with a long condition summary; confirm no card or page-level horizontal overflow.
- [x] Run `cd frontend && npm test -- --run src/components/JobBrowser.test.jsx src/components/jobBrowserLayerSummary.test.js`.

## 3. Add the facets-only backend seam

- [x] Add backend tests first for `POST /api/jobs/search/facets`: lexical uses the applied scope; semantic/hybrid use the candidate scope only when semantic text is present; validation errors match search; the existing atomic `include_facets=true` and pagination `false` paths remain compatible.
- [x] Add the minimal facets request schema (`scope`, `retrieval_mode`) in `backend/app/schemas/job_search.py`.
- [x] Add `RetrievalService.facets(request)` in `backend/app/services/retrieval_service.py`, keeping retrieval-mode scope selection inside the module and avoiding embedding/ranking work.
- [x] Add the public route in `backend/app/api/jobs.py`; reuse expression validation and return `JobSearchFacetsSchema` directly.
- [x] Run `docker compose exec -T backend-api python -m pytest -q tests/test_job_search_facets.py`.

## 4. Progressive frontend loading

- [x] Add frontend tests first for: Jobs commit before deferred facets; contextual selectors are busy/disabled while stale; facet success enables fresh options; facet failure preserves Jobs and shows a local retryable error; stale/aborted facet responses are ignored; pagination does not refresh or interrupt facets.
- [x] Split Job and facet abort controllers, sequence counters, loading state, and error state in `frontend/src/components/JobBrowser.jsx`.
- [x] Make result requests send `include_facets=false`. After the latest successful page-one scope commit, launch the facets-only request without blocking the successful return used by route synchronization.
- [x] Pass facet readiness/loading/error/retry state into `FilterPanel` and the governed selector modules. Disable only controls whose options/counts are stale; keep unrelated draft inputs usable where safe.
- [x] Preserve current session, route, clear/edit/remove, unmount cancellation, and newest-response-wins behavior.
- [x] Run `cd frontend && npm test -- --run src/components/JobBrowser.test.jsx src/components/FilterPanel.test.jsx src/components/filterFacetUtils.test.js src/components/jobBrowserScopeUtils.test.js src/components/jobBrowserSessionStorage.test.js`.

## 5. Optimize the zero-schema search path

- [x] Add lexical regression tests for anchor fragments that preserve punctuation-normalized exact matches without broadening the authoritative boundary predicate.
- [x] Add a logically necessary cheap anchor ahead of normalized exact comparisons in `backend/app/api/job_search_query.py`; apply the same rule to governed Skill label/alias matching.
- [x] Add focused tests for an internal single-scan pagination interface: totals, ordering, zero results, out-of-range pages, eager-loaded card projections, and semantic order preservation where the helper is shared.
- [x] Replace count-then-page execution in `backend/app/api/jobs.py` only after parity tests pass.
- [x] Measure facet latency and retain the existing exact contextual aggregation after the zero-schema result/facet paths meet both budgets; no schema or catalog-semantics change is warranted.
- [x] Run `docker compose exec -T backend-api python -m pytest -q tests/test_job_search_facets.py` plus the targeted lexical-search tests introduced above.

## 6. Benchmark gate

- [x] Add or document a read-only benchmark command for the public results and facets-only interfaces with configurable warm-ups, runs, base URL, query, and budgets.
- [x] Record the 6,743-Job corpus and three warm `=ERP` runs at page size 24.
- [x] Confirm Jobs/total `≤1s` (684ms median) and facets `≤2s` (1478ms median) on the current local corpus.
- [x] The miss-only schema/index/rebuild decision was not triggered; both zero-schema paths met budget.

## 7. Full verification and documentation

- [x] Run all targeted frontend and backend suites above.
- [x] Run `cd frontend && npm run lint && npm test && npm run build`.
- [x] Run the project backend suite through Docker: `docker compose exec -T backend-api python -m pytest -q tests` (root collection is blocked by the unrelated executable `backend/tmp_stress_test.py`).
- [x] Run `trellis-check` for spec compliance, cross-layer data flow, lint, tests, and dirty-worktree review; fix the pagination/facet race it identified.
- [x] Update `.trellis/spec/backend/job-browser-search.md` with the additive facets-only interface, progressive loading lifecycle, independent stale/error rules, and pagination behavior.
- [x] Review `git diff` by slice and verify no unrelated user changes were overwritten.

## Rollback Points

- Company CSS/copy can be reverted independently.
- Layer markup/CSS can be reverted without changing persisted scope data.
- The frontend can return to atomic `include_facets=true` while the additive facets endpoint remains harmless.
- Each SQL optimization must be independently revertible; no schema rollback exists because this task performs no schema change.
