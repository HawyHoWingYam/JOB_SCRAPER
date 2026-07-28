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
POST /api/jobs/search {
  scope, retrieval_mode, page, page_size, include_facets
} -> JobSearchResponse
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
- Successful page-one applies request `include_facets=true` and atomically
  replace Jobs, applied scope, and facets. Pagination requests
  `include_facets=false` and retain the last successful facets.
- Each facet removes its own dimension from every layer, preserves text and all
  other dimensions, and counts distinct Jobs. Job Taxonomy and Company
  Industry project distinct Jobs to active ancestors.
- Source, Employment Type, Job Taxonomy, and Company Industry return complete
  active governed catalogs. Source Classification returns only source-qualified
  paths represented by retained searchable Jobs.
- Semantic and hybrid facets use `build_semantic_candidate_scope(scope)`, the
  same candidate scope used by result retrieval. The original scope remains
  `applied_scope` for display and restoration.
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
| Invalid/unknown session payload version | Ignore it and run the normal initial search |
| Explicit route seed plus saved session | Route scope wins |
| Empty successful scope | Load unfiltered Jobs and remove the session key |

### 5. Good / Base / Bad Cases

- **Good:** select a Job Domain, apply it, add an Employment Type refinement,
  edit the Domain layer in place, then refresh and restore both layers at page 1.
- **Base:** an empty scope returns unfiltered Jobs plus complete zero-aware
  facets; pagination reuses those facets.
- **Good:** semantic results and counts use the same candidate scope while the
  original semantic text remains visible in the applied layer.
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
  `include_facets=false` pagination.

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

