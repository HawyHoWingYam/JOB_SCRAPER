# Job Browser Search Contracts

## Scenario: Apply layered Job searches with contextual facets

### 1. Scope / Trigger

Use this contract when changing the Job Browser filter UI, layered scope state,
`POST /api/jobs/search`, search retrieval, facet aggregation, pagination, or
same-tab restoration. Stable governed codes remain authoritative; labels are
display data.

### 2. Signatures

```python
JobSearchFacets(db).build(scope: JobSearchScopeSchema) -> JobSearchFacetsSchema
RetrievalService.facets(request: JobSearchFacetsRequestSchema) -> JobSearchFacetsSchema
POST /api/jobs/search {
  scope, retrieval_mode, page, page_size, include_facets
} -> JobSearchResponse
POST /api/jobs/search/facets {
  scope, retrieval_mode
} -> JobSearchFacetsSchema
```

Frontend applied state crosses these seams:

```javascript
normalizeScopeForSubmit(scope) -> { layers }
writeJobBrowserSession(sessionStorage, appliedScope)
readJobBrowserSession(sessionStorage) -> normalizedScope | null
```

### 3. Contracts

- A scope is an ordered list of layers. Fields are OR within one structured
  filter and layers/filter dimensions are ANDed. Editing replaces the same
  `client_id`; refinement appends a new unique `client_id`.
- Data Explorer page-one applies request `include_facets=false`, commit fresh
  Jobs/total and the successful applied scope first, then start an independent
  `POST /api/jobs/search/facets` refresh. Existing callers may continue using
  atomic `include_facets=true` for compatibility.
- Result and facet requests use independent abort controllers and monotonically
  increasing generations. A new scope invalidates both older lifecycles. Stale
  facets remain visible only for orientation and every governed facet selector
  stays disabled until the latest facet generation succeeds.
- Facet failure keeps the successful Jobs and applied scope, reports a local
  accessible error in the filter area, and retries only the facets endpoint for
  the current committed scope. Pagination requests `include_facets=false`, do
  not refresh facets, and retain the latest successful options.
- Each facet removes its own dimension from every layer, preserves text and all
  other dimensions, and counts distinct Jobs. Company Industry projects
  distinct Jobs to active ancestors.
- Source, Employment Type, and Company Industry return complete
  active governed catalogs. Source Classification returns only source-qualified
  paths represented by retained searchable Jobs.
- Semantic and hybrid facets use `build_semantic_candidate_scope(scope)`, the
  same candidate scope used by result retrieval. The original scope remains
  `applied_scope` for display and restoration.
- Exact lexical predicates may use cheap raw `ILIKE` fragment anchors only as
  necessary `AND` conditions ahead of normalized boundary comparisons. The
  normalized exact predicate remains authoritative; an `OR` anchor would
  broaden search semantics and is forbidden.
- Normal result pages obtain their total with a window count in the ordered
  page query. An out-of-range empty page may issue a fallback count so it still
  returns the true total; page-one zero results return total zero directly.
- Use `backend/scripts/benchmark_job_search.py` for the read-only warm latency
  gate. It records corpus/result totals, at least three samples and medians for
  Jobs and facets, and exits non-zero when explicit budgets are missed.
- Parent selection covers descendants and removes redundant descendant IDs.
  Zero-count options are disabled unless already selected, in which case they
  remain removable.
- Persist only a normalized successful applied scope in versioned
  `sessionStorage`. Explicit route seeds take precedence; drafts, pagination,
  and URLs are not persisted. Normalization preserves supported hidden backend
  fields as well as visible FilterPanel fields.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Invalid governed code, negative range, or malformed scope | Pydantic/HTTP 422; keep prior frontend results and applied session |
| Experience `from > to` | HTTP 422 |
| Active experience filter with `not_specified` and null Job bounds | Treat the Job as inclusive `[0, 1]` |
| Stale or aborted frontend response | Must not replace Jobs, facets, scope, or session |
| Latest Jobs succeed but facets fail | Keep Jobs/scope; disable stale facet controls and offer local retry |
| Older facets finish after a newer scope | Ignore the older payload and loading/error transitions |
| Invalid/unknown session payload version | Ignore it and run the normal initial search |
| Explicit route seed plus saved session | Route scope wins |
| Empty successful scope | Load unfiltered Jobs and remove the session key |

### 5. Good / Base / Bad Cases

- **Good:** select a Source Classification, apply it, add an Employment Type
  refinement, edit the first layer in place, then refresh and restore both
  layers at page 1.
- **Base:** an empty scope returns unfiltered Jobs plus complete zero-aware
  facets; pagination reuses those facets.
- **Good:** semantic results and counts use the same candidate scope while the
  original semantic text remains visible in the applied layer.
- **Good:** a fresh Layer renders Jobs and total, shows “Refreshing filter
  counts…”, then enables selectors only after the matching facet response.
- **Bad:** await Jobs and facets as one frontend promise, or let pagination
  launch a facet refresh for an unchanged scope.
- **Bad:** fetch `/jobs/filters` and taxonomy routes independently, then combine
  those options with Jobs from a different applied request.
- **Bad:** sum child counts to derive a parent count; a multi-assigned Job can be
  counted twice.

### 6. Tests Required

- `test_job_search_facets.py`: complete catalogs, self-dimension exclusion,
  other-dimension intersection, distinct Job/ancestor counts,
  `include_facets=false`, date boundaries, layered experience overlap, and
  semantic candidate facet scope.
- `filterFacetUtils.test.js` and `FilterPanel.test.jsx`: parent coverage,
  redundant-child removal, search, counts, selected-zero removal, and stable
  code payloads.
- `jobBrowserScopeUtils.test.js` and `jobBrowserSessionStorage.test.js`: in-place
  replacement, hidden-field preservation, versioned normalization, and invalid
  restoration fallback.
- `JobBrowser.test.jsx`: replace/refine/edit/remove/clear/discard requests,
  route precedence, page-one restoration, stale-response protection, and
  progressive Jobs-before-facets rendering, local facet retry, stale facet
  protection, and pagination with no facets request.
- Backend search tests assert exact-anchor normalization fragments, window
  totals, default ordering, preserved semantic ordering, zero results, and
  out-of-range totals. The benchmark command verifies the live PostgreSQL path;
  timing thresholds are not unit-test assertions.

### 7. Wrong vs Correct

#### Wrong

```python
# Semantic results use candidate_scope, but counts reapply lexical text.
facets = JobSearchFacets(db).build(request.scope)
```

#### Correct

```python
candidate_scope = build_semantic_candidate_scope(request.scope)
facets = JobSearchFacets(db).build(candidate_scope)
# Response still exposes applied_scope=request.scope.
```

Frontend lifecycle:

```javascript
const results = await search({ include_facets: false });
commitJobsAndScope(results);
void refreshFacetsForLatestScope(results.applied_scope);
```

Do not put the facet request back inside the result-loading promise or enable
stale selectors while that independent refresh is pending.
