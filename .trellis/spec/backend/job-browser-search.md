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

JobSearchResponse {
  jobs, total, page, page_size, total_pages,
  result_kind: "exhaustive" | "ranked",
  result_limit: int | null,
  ranked_candidate_count: int | null,
  applied_scope, layer_summaries, facets
}

python -m scripts.upgrade_job_embedding_contract
python -m scripts.upgrade_job_search_indexes
python -m scripts.rebuild_job_description_embeddings \
  [--batch-size N] [--limit N]
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
- Every text clause searches Job Description only. Broad, exact, and quoted
  lexical predicates must not read Job title, AI summary, Company name or AI
  description, source classification labels, governed Skill labels/aliases,
  or other display metadata. Structured filters remain independent and may
  constrain those governed dimensions only when explicitly selected.
- Semantic and hybrid compare query vectors only with Description-derived Job
  embeddings whose `document_contract` equals `job-description-v1`. The shared
  producer/query contract lives in `app.search.embedding_contract`; model name,
  dimensions, document contract, candidate bound, and ranked-result bound must
  not be redefined in workers, services, models, or scripts.
- Retrieval owns one concurrency-safe, lazily initialized query model per
  process. Keep request database sessions inside request-scoped services; never
  retain a SQLAlchemy session in the process-level model provider.
- Semantic returns at most 1,000 database-ranked rows. Hybrid fetches at most
  2,000 semantic candidates, reranks only that bounded window using Description
  text plus semantic/freshness signals, and returns at most 1,000 rows.
  Semantic/hybrid responses use `result_kind="ranked"`, `result_limit=1000`,
  and an observable `ranked_candidate_count`; their `total` is the bounded
  ranked-set size, not an exhaustive relevance claim. Lexical remains
  `result_kind="exhaustive"`.
- Data Explorer page-one applies request `include_facets=false`, commit fresh
  Jobs/total and the successful applied scope first, then start an independent
  `POST /api/jobs/search/facets` refresh. Existing callers may continue using
  atomic `include_facets=true` for compatibility.
- Result and facet requests use independent abort controllers and monotonically
  increasing generations. A new scope invalidates both older lifecycles. Stale
  facets remain visible only for orientation and every governed facet selector
  stays disabled until the latest facet generation succeeds.
- Facet retry, pagination, and export use the committed scope and committed
  retrieval mode. A draft mode selector change cannot reinterpret existing
  results. Outside edit mode, Enter performs the visible `Search all jobs`
  replacement action; refinement remains an explicit button. In edit mode,
  Enter saves that layer in place.
- Facet failure keeps the successful Jobs and applied scope, reports a local
  accessible error in the filter area, and retries only the facets endpoint for
  the current committed scope. Pagination requests `include_facets=false`, do
  not refresh facets, and retain the latest successful options.
- Each facet removes its own dimension from every layer, preserves text and all
  other dimensions, and counts distinct Jobs.
- Source and Employment Type return complete active governed catalogs. Source
  Classification returns only source-qualified paths represented by retained
  searchable Jobs. Company Industry is not a current filter or facet.
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
  gate. It records lexical/semantic/hybrid cold requests, at least three warm
  samples and medians for Jobs and facets, ranked-result metadata, and exits
  non-zero when explicit per-mode budgets are missed.
- Fresh PostgreSQL bootstrap creates `vector` and `pg_trgm` plus the Description
  trigram GIN index. Existing sandboxes
  must run the two idempotent upgrade commands; `metadata.create_all()` is not
  an upgrade mechanism. The embedding schema upgrade labels all existing rows
  `legacy`, keeps the database default at `legacy` as a fail-safe against an
  old producer, and only current code explicitly writes `job-description-v1`.
- Description-only embedding rebuild is manually started. It uses keyset
  pagination and per-batch commits, batches model encoding, skips current rows,
  and is safe to rerun. Semantic/hybrid ignore legacy rows throughout rebuild,
  so corpus coverage grows monotonically without mixed document semantics.
- Do not add a filtered HNSW index without proving its returned cardinality.
  In this corpus, a broad `LIMIT 1000` HNSW plan with the current-contract
  predicate returned only 61 rows under the default search breadth, while the
  exact bounded vector path returned 1,000 in a 470.854ms warm median. Correct
  ranked coverage takes precedence over an unnecessary approximate index.
- Hierarchical Source Classification selection covers descendants and removes
  redundant descendant IDs.
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
| Text exists only in Company/title/AI/classification/Skill metadata | No lexical text match |
| Legacy or unknown embedding document contract | Exclude it from semantic/hybrid candidates |
| Rebuild interrupted after a committed page | Rerun; skip current rows and resume idempotently |
| Old producer omits `document_contract` | Database marks the row `legacy`; never serve it as current |
| Semantic/hybrid broad corpus exceeds bounds | Return bounded ranked set plus explicit ranked metadata |

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
- **Bad:** restore a Company Industry selector from legacy Company text or stale
  fixture fields.

### 6. Tests Required

- `test_job_search_facets.py`: complete current catalogs, self-dimension
  exclusion, other-dimension intersection, distinct Job counts,
  `include_facets=false`, date boundaries, layered experience overlap, and
  semantic candidate facet scope.
- `filterFacetUtils.test.js` and `FilterPanel.test.jsx`: Source Classification parent coverage,
  redundant-child removal, search, counts, selected-zero removal, and stable
  code payloads.
- `jobBrowserScopeUtils.test.js` and `jobBrowserSessionStorage.test.js`: in-place
  replacement, hidden-field preservation, versioned normalization, and invalid
  restoration fallback.
- `JobBrowser.test.jsx`: replace/refine/edit/remove/clear/discard requests,
  route precedence, page-one restoration, stale-response protection, and
  progressive Jobs-before-facets rendering, local facet retry, stale facet
  protection, and pagination with no facets request.
- **Good:** changing Company metadata without changing Description leaves the
  lexical predicate and embedding document/hash unchanged.
- **Good:** deploy schema provenance, replace the embedding worker, rebuild in
  batches, then replace retrieval-api; partially rebuilt coverage is honest
  because only current-contract rows are ranked.
- **Bad:** change only the embedding document builder while semantic queries
  continue joining every historical `job_embeddings` row.
- **Bad:** give `document_contract` a server default of the current contract;
  an old worker can then write broad documents falsely labeled as current.
- Backend search tests assert exact-anchor normalization fragments, window
  totals, default ordering, preserved semantic ordering, zero results, and
  out-of-range totals. The benchmark command verifies the live PostgreSQL path;
  timing thresholds are not unit-test assertions.
- Description-only query tests assert a Job matches when the clause is in
  Description and does not match when it appears only in title, AI summary,
  Company metadata, classification, or Skill metadata. Hybrid tests keep
  semantic vectors equal and prove only Description overlap changes order.
- Retrieval tests assert provider once-only construction under concurrency,
  semantic limit 1,000, hybrid candidate limit 2,000, ranked metadata, and
  legacy-contract exclusion/currentness. Rebuild canary must rebuild one row,
  then rerun it as `skipped=1` without a cursor/transaction failure.
- Frontend tests assert committed-mode facet retry, no extra Jobs request,
  explicit replace/refine/edit Enter behavior, and “Ranked results” rendering.

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

Description-only predicate:

```python
# Wrong: display metadata broadens the text corpus.
or_(Job.description.ilike(pattern), Company.ai_description.ilike(pattern))

# Correct: every text syntax targets Description; governed fields use filters.
Job.description.ilike(pattern)
```

Embedding provenance:

```python
# Wrong: all historical vectors are rankable.
query.join(JobEmbedding, JobEmbedding.job_id == Job.id)

# Correct: serve only the current explicit document contract.
query.join(
    JobEmbedding,
    (JobEmbedding.job_id == Job.id)
    & (JobEmbedding.document_contract == EMBEDDING_DOCUMENT_CONTRACT),
)
```

## Laptop presentation and failed application

- Job Browser places search/actions above a visible filter column and results.
  At 1366×768 and 1440×900, a populated initial result row must be visible
  without scrolling. Secondary advisory controls must not precede the primary list.
- Draft edits require explicit submission. Keep replace, refine, and edit
  semantics distinct; an unapplied draft never changes the export scope.
- A failed apply renders an accessible error alongside prior successful rows.
  Keeping rows in state while an error conditional hides them is insufficient.
- `frontend/e2e/usability.spec.js` verifies viewport geometry, explicit apply,
  failed-apply row retention, and export availability against an isolated API.
