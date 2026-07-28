# Implementation plan: Improve job filters frontend and backend

## Ordered checklist

1. Reconfirm affected specs and contracts before editing:
   `.trellis/spec/backend/source-job-attributes.md`,
   `.trellis/spec/backend/ordinary-current-taxonomies.md`,
   `.trellis/spec/backend/job-intelligence-product-surfaces.md`, and the
   cross-layer thinking guide. Inspect current dirty changes and avoid unrelated
   files.
2. Add failing backend contract tests for the additive search facet response:
   complete governed options, data-backed Source paths, self-dimension
   exclusion across multiple layers, other-dimension intersection, distinct Job
   counts, parent aggregation, selected/unknown behavior, and
   `include_facets=false`.
3. Extract the backend `JobSearchFacets` module and schemas. Reuse existing
   search parsing/filter helpers through one scope interface; add bounded bulk
   aggregation for each dimension and integrate optional facets into GET/POST
   response construction without changing existing fields.
4. Add backend regressions for posted-date and experience overlap, including
   unspecified 0–1 years, reversed ranges, empty strings, and layered AND
   behavior. Run the targeted backend suite before frontend integration.
5. Add failing pure frontend tests for hierarchy selection normalization,
   normalized scope transitions (replace, append, edit, remove, clear,
   discard), versioned session restore, corrupt-session fallback, page-one
   restore, and explicit route-seed precedence.
6. Implement the `jobBrowserSearchSession` module and versioned
   `sessionStorage` helpers. Preserve non-panel governed scope fields and stable
   client IDs; do not persist draft or pagination.
7. Add failing selector interaction tests, then implement reusable
   `FilterSelectorCard`, checkbox, source-path, and hierarchy selector modules.
   Cover local search, collapsed summaries, removable chips, zero-count disabled
   nodes, selected-zero removal, parent-first expansion, ancestor coverage, and
   redundant-descendant removal.
8. Refactor `FilterPanel` to the two-column/simple and full-row/complex layout.
   Keep date, experience, Posting Window, staged validation, and loading/error
   behavior; replace native multi-selects without changing governed payloads.
9. Refactor `JobBrowser` orchestration to consume atomic search facets, retain
   facets during pagination, and render the applied-layer stack. Implement
   inspect/edit/save/remove/clear, replace-all/refine, discard, newest-response
   protection, failure retention, and successful session persistence.
10. Coordinate with the dashboard drill-down route contract if it lands during
    implementation: valid explicit route seeds override session restoration and
    hidden governed fields survive normalization. Add regression coverage rather
    than duplicating its route parser.
11. Replace incomplete frontend reliance on backend prose summaries. Keep legacy
    backend response fields and `/jobs/filters` compatible for other consumers;
    remove code only after repository-wide usage search proves it unused.
12. Finish responsive/accessibility styling and tests: desktop maximum two
    columns, complex full-width cards, narrow single-column fallback, no clipped
    labels, keyboard-operable disclosure/checks/removal, visible focus, and live
    pending/loading/error status.
13. Run targeted checks, then full frontend/backend quality gates. Inspect the
    final diff for unrelated dirty-worktree changes, cross-layer field drift,
    query-count/N+1 regressions, and fixture compatibility.

## Validation commands

```bash
cd frontend && npm test -- src/components/FilterPanel.test.jsx src/components/JobBrowser.test.jsx
cd frontend && npm run lint
cd frontend && npm run build
python3 -m pytest -q backend/tests/test_job_intelligence_response_contracts.py
python3 -m pytest -q backend/tests/test_source_job_attribute_api.py backend/tests/test_source_job_attributes.py
python3 -m pytest --collect-only -q backend/tests
python3 -m pytest -q backend/tests
```

If realistic PostgreSQL verification is needed, use the documented Docker test
path and a database ending in `_test`; do not point destructive/bootstrap tests
at the development database.

## Review gates

- Backend schema and facet semantics review before wiring the frontend.
- Backend targeted tests green before selector integration.
- Pure state/selection tests green before `JobBrowser` orchestration changes.
- Cross-layer payload review after frontend integration: request normalization,
  response schemas, stable codes, route-seeded hidden fields, and session decode.
- Full lint/build/test gate before reporting implementation complete.

## Risky files and rollback points

- `backend/app/api/jobs.py` is a large shared route module. Prefer extraction;
  rollback the facet integration independently of existing search behavior.
- `frontend/src/components/JobBrowser.jsx` owns request concurrency and layered
  state. Land pure session transitions before orchestration changes so the old
  request path remains recoverable.
- `frontend/src/components/FilterPanel.jsx` currently carries compatibility
  mappings. Preserve them until new selectors prove identical governed payloads.
- Do not modify taxonomy persistence or create database migrations unless
  implementation evidence contradicts this design; stop and return to planning
  if that boundary changes.
