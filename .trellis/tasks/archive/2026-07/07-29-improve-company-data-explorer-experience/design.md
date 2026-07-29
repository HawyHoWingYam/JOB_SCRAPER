# Design: Improve company and Data Explorer experience

## Overview

Deliver the work as three separately verifiable slices inside one task:

1. Correct the Companies run-size presentation without changing its backend contract.
2. Reshape applied Layers into responsive cards without changing layered-scope behavior.
3. Split Job results from contextual facets, then optimize the measured lexical and facet paths without changing search semantics.

The two Data Explorer slices share `JobBrowser`, its request lifecycle, and its integration tests, so keeping one implementation task provides a single race-condition and responsive-layout review gate. Each slice should still be committed and validated independently where practical.

## Interfaces and Seams

### Company run-size control

The existing global-run interface remains:

```text
POST /api/companies/enrichment-runs
{ mode, requested_limit, web_search_enabled, regenerate_confirmed }
```

Only the frontend presentation changes. Checkbox dimensions must target `input[type="checkbox"]`; the numeric input receives its own class and normal control width. The hint states that `50` is a safe default, not a maximum, and that the frozen cohort is bounded by eligible Companies.

The legacy explicit-ID batch interface and its 50-ID maximum remain untouched.

### Layer-card interface

`activeScope.layers` and `summarizeJobBrowserLayer()` remain authoritative. The rendering module changes shape only:

```text
Applied Layers section
├── section header: title + Clear all layers
└── layer list
    └── layer card
        ├── card header: Layer N + Edit/Remove
        └── wrapping condition list
```

The card has `min-width: 0`; summary content uses `overflow-wrap: anywhere`; action buttons do not share the summary row. At the narrow breakpoint, the card header stacks and the action group moves below the summary. Existing button labels and callbacks remain stable for accessibility and tests.

### Progressive Job search

Keep the existing search interface backward compatible:

```text
POST /api/jobs/search
{ scope, retrieval_mode, page, page_size, include_facets }
```

Add a small facets-only interface:

```text
POST /api/jobs/search/facets
{ scope, retrieval_mode }
-> JobSearchFacetsSchema
```

The deep module seam is `RetrievalService.facets(request)`. It hides retrieval-mode differences from the route and frontend:

- lexical, or semantic/hybrid without semantic query text: build facets from the applied scope;
- semantic/hybrid with semantic query text: build facets from `build_semantic_candidate_scope(scope)`;
- never create an embedding model or repeat semantic/hybrid ranking merely to compute facets.

The existing `include_facets=true` response remains supported for compatibility, but Data Explorer page-one operations use `include_facets=false` and then call the facets-only interface after the Job response succeeds. Pagination continues to reuse the last successful facets and does not refresh them.

## Frontend State Flow

Use independent result and facet request lifecycles:

1. A new initial/apply/edit/remove/clear operation aborts any older result request and any older facet refresh.
2. The result request sends `include_facets=false` and owns `isLoading`, Job errors, applied-scope/session commits, and result pagination.
3. Only the latest successful result response may commit Jobs, total, applied scope, route/session state, and begin a facet refresh.
4. After that commit, existing facet values become stale and non-interactive. They may remain visible for orientation but are marked busy and cannot be selected.
5. The facets-only request owns `isFacetsLoading`, `facetsError`, a separate abort controller, and a monotonically increasing generation. It may replace facet options only when its generation still matches the latest committed result scope and retrieval mode.
6. Facet failure leaves successful Jobs visible, keeps stale facets disabled, shows a local accessible error, and offers a retry for the current committed scope.
7. A pagination request changes only Jobs/pagination; it neither invalidates nor refreshes facets because the scope is unchanged.

This makes result success and facet success independent while preserving stale-response safety.

## Backend Performance Design

No schema changes or destructive rebuild are authorized. Optimize in measured stages and retain only changes that preserve existing lexical/facet tests:

1. Add a cheap, logically necessary case-insensitive substring anchor before the expensive normalized exact-token predicate for each searchable field and governed Skill label/alias. The anchor must derive from normalized search tokens so it cannot exclude a row accepted by current exact-match semantics.
2. Replace the unconditional count-then-page double scan with an internal paginated-search module that obtains rows and total from one filtered scan (for example, a window count). Preserve ordering, eager-loaded Job card data, zero-result totals, and out-of-range-page behavior.
3. Add per-stage benchmark visibility for result retrieval and each facet family. Optimize repeated effective candidate scopes and broad catalog materialization only where timings prove they dominate. Candidate reuse must preserve self-dimension exclusion and distinct Job/ancestor counts; do not replace exact counts with estimates.
4. Benchmark the public results interface and the facets-only interface with the current `=ERP` scope after warm-up. The provisional gate is Jobs/total `≤1s` and facets `≤2s` on the documented 6,743-Job corpus.

If the zero-schema path cannot meet the gate, stop at the evidence boundary. A `pg_trgm`/functional-index or denormalized search-document design requires a separate decision and a fully authorized sandbox cutover; it is not an implicit fallback in this task.

## Benchmark Interface

Add or document a read-only repeatable command that:

- targets a configurable base URL;
- warms each endpoint once;
- runs at least three `=ERP` samples with page size 24;
- reports corpus/result count plus per-run and median latency separately for Jobs and facets;
- exits non-zero when explicit budgets are supplied and missed.

Timing thresholds are a local release gate, not a timing-sensitive unit test.

## Compatibility and Failure Semantics

- Existing callers using atomic `include_facets=true` continue to work.
- Exact, phrase, broad, layered, lexical, semantic, and hybrid meanings do not change.
- Contextual facets continue to remove their own dimension across every Layer and count distinct Jobs.
- Session state changes only after successful Job results, as today; a facet failure does not roll the applied scope back.
- Aborted or stale Job/facet responses cannot mutate current state.
- Company generation still submits any positive whole number unchanged and retains the safe default of 50.
- Responsive changes preserve the application minimum width of 320px and all existing action labels.

## Rollout and Rollback

- Roll out the Company CSS/copy slice first; rollback is frontend-only.
- Roll out Layer markup/CSS next; rollback restores the old markup without touching scope data.
- Roll out the additive facets interface before switching Data Explorer to it. During rollback, Data Explorer can return to `include_facets=true` because that compatibility path remains intact.
- Query optimizations must be benchmarked and regression-tested independently. Revert an optimization if semantic or ordering parity fails; progressive loading does not depend on a particular SQL optimization.
- No database rebuild, extension, or index change is part of rollout.

## Spec Impact

Update `.trellis/spec/backend/job-browser-search.md` to replace the atomic page-one-only frontend rule with the progressive Jobs-then-facets contract, including independent stale/error handling and the facets-only interface. The Company backend quantity contract already states that `requested_limit` has no product maximum; no backend behavior change is required there.
