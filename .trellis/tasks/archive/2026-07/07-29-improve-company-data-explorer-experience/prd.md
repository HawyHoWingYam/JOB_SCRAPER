# Improve company and Data Explorer experience

## Goal

Make the Companies and Data Explorer workflows scale and feel responsive: remove or explain the apparent 50-company processing ceiling, keep search-layer controls within their visual container, and reduce or better mask Data Explorer loading latency.

## Background

The user reported three related usability problems from the current UI:

- A Companies AI-description run appears unable to process more than 50 companies.
- Data Explorer search-layer actions overflow or crowd the layer card boundary.
- Data Explorer loading feels slow.

The grilling session established a safe-default Company quantity, a responsive layer-card hierarchy, progressive result/facet loading, and provisional current-scale latency targets. Implementation remains unauthorized until the user reviews the final planning artifacts.

## Confirmed Facts

- Persisted Company enrichment runs do not have a 50-item product maximum. The backend accepts any positive `requested_limit`, and the governing spec requires freezing `min(requested_limit, eligible_count)`; it explicitly gives a 100,000-request example (`backend/app/api/companies.py:83-91`, `.trellis/spec/backend/company-enrichment-runs.md:122-124`, `.trellis/spec/backend/company-enrichment-runs.md:178-179`).
- The Companies UI initializes the run-size value to `50`, but its shared checkbox selector forces every input in that label to `18px × 18px`. That rule also affects the numeric input, matching the screenshot in which the run-size field appears as a tiny circle and obscures/editing its value (`frontend/src/components/companies/useCompanyEnrichmentRun.js:169`, `frontend/src/components/companies/CompaniesPage.css:57-70`, `frontend/src/components/companies/CompaniesPage.jsx:287-297`).
- A separate legacy batch endpoint limits an explicit `company_ids` list to 50; the persisted global-run UI does not use that contract (`backend/app/api/companies.py:77-81`). Runtime worker concurrency is also bounded separately and is not the number of items allowed in a run.
- Data Explorer layer summaries render inside an inline flex item whose summary child retains its intrinsic minimum width. The existing wrap rule targets a `span`, while actual summaries are list items; long text, skill, or taxonomy summaries can therefore expand past the card. There is no scope-trail-specific narrow-screen rule (`frontend/src/components/JobBrowser.jsx:727-767`, `frontend/src/components/JobBrowser.css:509-539`, `frontend/src/components/JobBrowser.css:710-735`).
- A Data Explorer search requests contextual facets by default. The backend serially counts results, fetches the page, and builds four facet families. Source Classification and Company Industry facet construction materialize broad row sets independent of the 24 visible results (`frontend/src/components/JobBrowser.jsx:207-243`, `backend/app/api/jobs.py:510-543`, `backend/app/services/job_search_facets.py:61-71`, `backend/app/services/job_search_facets.py:148-280`).
- Pagination deliberately skips facet recomputation and retains previous facet options; this was an explicit decision in the completed Job Browser filter work. Initial searches and layer apply/edit/remove operations still request facets. No Data Explorer-specific latency instrumentation, baseline, or performance test currently exists.
- A local warm-container baseline on the current 6,743-Job corpus shows that an empty lexical scope takes about 0.03–0.07 seconds without facets and 0.16–0.33 seconds with facets. The reported `=ERP` layer takes about 3.0–3.1 seconds without facets and 6.1–6.3 seconds with facets (three runs per mode on 2026-07-29). Therefore both text-result retrieval and facet computation require attention; progressive rendering alone would still leave an approximately three-second wait for fresh results.

## Requirements

- Preserve `50` as the safe default Company run size, while making the numeric input normally visible and editable.
- Explain beside the run-size control that there is no product maximum and that a run processes at most the currently eligible Company count.
- Render each Data Explorer layer as a structured card: a header with the layer name and directly visible Edit/Remove actions, followed by a full-width, wrapping condition summary.
- Place Clear all layers in the Layer section header rather than alongside an individual card.
- On narrow screens, move the layer actions below the summary and allow the action row to wrap without horizontal overflow.
- Decouple primary Job results from contextual facet refresh: render Jobs and total count as soon as their response is ready, while the facet controls show a localized loading state and remain non-interactive until fresh counts arrive.
- Never present stale facet counts as actionable for a newly applied scope.
- Optimize the backend facet path as well as progressive rendering; a loading-state change alone does not satisfy the performance requirement.
- Establish a reproducible current-data baseline and a measurable target before implementation is activated.
- On the current 6,743-Job local corpus, target warm `=ERP` requests at no more than 1 second for fresh Jobs/total and no more than 2 seconds for fresh contextual facets. Treat these as provisional current-scale targets to revisit as corpus size changes.

## Constraints and Out of Scope

- Preserve exact layered-scope, contextual-facet, pagination, same-tab restoration, and lexical/semantic/hybrid retrieval semantics.
- Preserve the legacy explicit-ID batch endpoint's independent 50-ID validation; it is not the Companies global-run interface reported here.
- Do not change the Company run-size default to All eligible.
- Do not hide Edit or Remove behind an overflow menu.
- Do not weaken contextual facet correctness, silently reuse stale counts, or make successful Jobs disappear when a facet refresh fails.
- Do not introduce an in-place schema migration or perform a destructive sandbox rebuild. Index-backed schema changes require separate operator authorization if code/query optimization cannot meet the provisional target.
- Do not add a new search engine or change semantic/hybrid ranking behavior.

## Acceptance Criteria

- [ ] The Company run-size field visibly displays `50` by default, accepts positive whole numbers greater than 50, and submits the entered value unchanged.
- [ ] The UI states that the quantity is not capped at 50 and that actual work is bounded by eligible Companies.
- [ ] Layer controls do not overflow their owning card down to the application's supported 320px viewport width.
- [ ] Long text, skill, and taxonomy summaries wrap inside the layer card without clipping or causing page-level horizontal scrolling.
- [ ] Edit and Remove remain directly visible on desktop; narrow-screen controls remain reachable without an overflow menu.
- [ ] Clear all layers is visually associated with the complete Layer section rather than one card.
- [ ] Data Explorer loading has a defined baseline and a testable target for the chosen scope.
- [ ] A reproducible benchmark on the current corpus records `=ERP` Jobs/total at `≤ 1s` and contextual facets at `≤ 2s` under documented warm-run conditions.
- [ ] Applying, editing, or removing a Layer can render the fresh Jobs and total before facet computation completes.
- [ ] Facet refresh has its own accessible loading state, and stale facet options cannot be selected during that state.
- [ ] Facet failure does not discard successfully loaded Job results and is reported locally to the filter area.
- [ ] Existing company generation, layer editing/removal, and Data Explorer result behavior remain correct.

## Notes

- This is a complex, cross-layer task and will require `design.md` and `implement.md` before activation.
