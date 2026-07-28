# Design: Improve job filters frontend and backend

## Design goals

- Put facet computation behind one deep backend module interface.
- Put draft/layer transitions and selector rules behind small frontend module
  interfaces instead of expanding `JobBrowser` and `FilterPanel` further.
- Return results and facets atomically for an applied scope so the UI cannot
  combine Jobs from one search with counts from another.
- Preserve current stable-code, compatibility, and layered-AND semantics.

## Cross-layer data flow

```text
Filter selectors
  -> normalized draft
  -> replace / append / edit-layer command
  -> POST /jobs/search { scope, page, page_size, include_facets }
  -> scope validation + lexical clauses
  -> JobSearchFacets.build(scope) + paginated Job query
  -> { jobs, applied_scope, facets }
  -> active layer stack + facet option indexes
  -> sessionStorage(active scope only)
```

Validation ownership remains at the existing Pydantic request seam. Frontend
normalization prevents noisy payloads and corrupt session restoration, but does
not replace backend validation.

## Backend module and response interface

Introduce a `JobSearchFacets` module near the Jobs search read path with one
external interface:

```python
JobSearchFacets(db).build(scope: JobSearchScopeSchema) -> JobSearchFacetsSchema
```

The implementation owns:

- the mapping from a facet dimension to every current/legacy field belonging to
  that dimension;
- cloning a scope with that dimension removed from every layer;
- retained-Job candidate subqueries that preserve text and all other filters;
- distinct-Job aggregation for source, employment, source classifications, Job
  Taxonomy, and Company Industry;
- ancestor expansion and de-duplication for hierarchical counts;
- complete active catalog projection and stable option ordering.

Callers do not construct joins, strip fields, or aggregate ancestors. Tests use
the same module interface as the route.

Extend `JobSearchRequestSchema` with `include_facets: bool = True` and extend
`JobSearchResponse` with optional `facets`. The facet payload uses stable IDs and
one normalized option shape containing identity, label, order, count, optional
parent/level/source/path metadata, and selectability. Counts—not labels—are
scope-dependent.

The POST search path requests facets for a new/changed applied scope. Pagination
requests send `include_facets=false` and retain the last successful facets.
Existing callers that omit the flag receive facets without losing any existing
response fields. Legacy GET search remains compatible; `/jobs/filters` remains
available for existing consumers but JobBrowser moves to the atomic POST facet
payload. Existing current-taxonomy routes remain unchanged for other surfaces.

### Facet semantics

- `source`: omit `source_site` from every layer before counting distinct Jobs by
  source.
- `source_classification`: omit `source_classification_ids`; retain Source and
  all other fields; group distinct Job IDs by source-qualified path node.
- `employment_type`: omit current code and legacy label fields; count distinct
  Jobs per governed code and project every registry row.
- `job_taxonomy`: omit current and legacy domain/category/subcategory fields;
  count distinct candidate Job IDs at assigned leaves, then project each Job to
  every active ancestor once before grouping.
- `company_industry`: omit current node IDs and the rejected legacy field;
  join candidate Jobs through Company assignments and project each Job to every
  active ancestor once before grouping.

Hierarchical aggregation must never sum child totals because one Job may have
multiple descendant assignments. Use bounded bulk rows or a recursive/grouped
query that produces distinct `(node_code, job_id)` pairs; never issue one query
per node. Unknown/inactive selected codes continue to follow existing explicit
empty-result/validation behavior.

## Frontend modules and seams

### Search session module

Extract a pure `jobBrowserSearchSession` module that owns normalized state
transitions for:

- draft changes and discard;
- replace-all, append-refinement, begin-edit, save-edit, remove-layer, clear-all;
- stable unique layer IDs;
- pending-change comparison;
- versioned session serialization and safe restoration.

`JobBrowser` remains the orchestration caller: it invokes the search transport,
commits a transition only after success, and retains the prior results/facets on
failure. There is no adapter interface around `sessionStorage`; small
read/write/clear functions are sufficient because only one implementation is
needed.

The session decoder accepts only an object with a known version and a normalized
scope. Invalid JSON or invalid fields are discarded without preventing the
initial unfiltered search. If explicit route filters from the dashboard
drill-down task exist, they win over restored session state. Scope
normalization preserves governed fields outside the visible panel so route
seeds are not silently erased.

### Selector modules

Add a reusable `FilterSelectorCard` module for disclosure, selection summaries,
local search, count display, disabled state, loading/error state, and keyboard
focus. Compose it with:

- `CheckboxFacetSelector` for Employment Type;
- `SourceClassificationSelector` for source grouping and path search;
- `HierarchyFacetSelector` for Job Taxonomy and Company Industry.

A pure hierarchy-selection helper owns ancestor coverage and minimal-ID
normalization. A selected zero-count node bypasses disabled presentation only so
it can be removed; it cannot be newly selected at zero.

### Applied-layer stack

Render summaries from normalized applied layers plus facet/catalog label indexes
rather than the backend's incomplete prose label. Each layer card exposes
inspect, edit, and remove. Edit mode copies that layer into the draft editor;
save replaces the same array position after a successful request; discard exits
without a request. `Clear all layers` sends an empty scope, clears draft/edit
state and session persistence after success, and returns to page one.

## Layout and accessibility

- Replace the three-column grid with a maximum two-column grid for simple
  fields; selector cards span both columns.
- Collapse to one column at the existing narrow breakpoint. Do not introduce a
  modal or drawer.
- Use native disclosure/buttons/checkboxes with explicit labels, expanded state,
  keyboard-operable remove actions, visible focus, and live status for loading,
  errors, and pending changes.
- Keep the action bar at the bottom of the panel and visually persistent within
  the panel when useful; avoid covering content.

## Error, concurrency, and compatibility behavior

- Keep the existing newest-request-wins protection. A stale response may not
  replace Jobs, facets, active scope, or persisted session state.
- Failed apply/edit/remove/clear operations leave the last successful applied
  scope, results, facets, and session state intact; the draft remains available
  for correction or retry.
- Facets and Jobs are one successful response contract. Do not silently display
  stale counts beside new Jobs.
- Preserve legacy GET parameters, Employment Type label translation, rejected
  legacy Company Industry behavior, current taxonomy endpoints, and existing
  response fields.

## Rollout and rollback

No database migration is expected; current assignment tables and indexes own
the data. Additive request/response fields permit backend-first rollout. The
frontend can then switch from `/jobs/filters` plus separate taxonomy loading to
the unified search facets. Rollback consists of reverting the frontend consumer
and leaving additive backend fields harmless; no stored server data requires
rollback. Versioned session payloads are ignored when their version is unknown.

## Risks and mitigations

- Contextual facets add several aggregate queries. Reuse retained candidate
  subqueries, count distinct Jobs, bound statement count, and verify query shape
  against realistic PostgreSQL data before completion.
- Full taxonomy payloads increase response size. Keep option records compact and
  omit facets on pagination.
- Parent aggregation can double-count multi-assigned Jobs. Aggregate distinct
  `(node, job)` pairs, not summed child counts.
- Concurrent dashboard drill-down route work can conflict with session restore.
  Keep explicit route precedence and test both entry paths.
- Large selector refactors can regress keyboard access. Test roles, names,
  expansion, focus, disabled nodes, and removable selected-zero nodes through
  user-visible behavior.
