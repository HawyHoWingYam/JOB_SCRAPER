# Search audit — 2026-09-24

## Scope and evidence limits

Read-only code/test inspection of Job Browser, shared backend search, facets, export, and experience presentation. Main agent spot-checked the critical mode, export, Jev preview, overlap predicate, and response-schema anchors. No runtime reproduction, database benchmark, or tests were executed. Findings describe source behavior; performance opportunities are hypotheses.

## Findings and proposed priorities

### P1: Applied retrieval mode can diverge from visible results

`frontend/src/components/JobBrowser.jsx:750-768` changes retrievalMode without fetching new Jobs/facets. Pagination (`:547-555`) and export (`:680-689`) consume that mode, while the visible total and rows remain from the preceding search. Example: lexical results -> select semantic -> export or next page. Proposed fix: separate draft mode from successfully applied mode, consistent with explicit search submission, and use the applied snapshot for rows/counts/facets/pagination/export. Add regression tests for mode changes, failed applies, and exports.

### P1: Stale Jev preview/evaluation responses lack scope fencing

`frontend/src/components/JobBrowser.jsx:557-602` unconditionally applies asynchronous preview/evaluation results without request generations or scope/mode identity guards. An old preview can arrive after a newer search cleared it, restoring an evaluation button for an obsolete frozen scope. Do not assume the backend accepts a mismatched evaluation; the confirmed frontend defect is stale state and ambiguous evaluation scope. When moving controls to the unified Jev page, bind preview/start/result to the frozen operation scope and ignore stale responses. All provider work remains manually initiated.

### P2: Unknown capabilities optimistically enable semantic/hybrid modes

`frontend/src/components/JobBrowser.jsx:201-202` uses `available !== false`; initial or failed capabilities therefore appear available. Fetch failure resets capabilities to null (`:420-435`), while options use those booleans (`:763-767`). Proposed improvement: loading/unknown/unavailable states with lexical available and a retry action; test failed and malformed capability responses.

### P1: Compact experience labels need explicit search semantics

`backend/app/api/jobs.py:266-326` implements inclusive interval overlap. `[1,2]` matches query `[2,2]`; `[2,4]` matches query `[1,2]`. Compressing `[1,2]` to display `1+` must not silently reinterpret stored max as infinity. Confirmed after audit: retain inclusive interval overlap using original bounds; compact labels do not redefine membership. Clarify filter wording and expose original bounds.

The shared predicate is reused by lexical (`backend/app/search/lexical_query.py:4-7`), semantic/hybrid candidates (`backend/app/search/semantic_query.py:10-16`, `backend/app/services/retrieval_service.py:102-126`), facets, and exports (`backend/app/services/retrieval_service.py:157-209`; `backend/app/api/jobs.py:997-1028`). No separate experience facet was found. Add a cross-mode/export membership matrix rather than duplicating predicates. Existing experience coverage is predominantly lexical (`backend/tests/test_job_search_facets.py:616-750`).

Filter labels are ambiguous (`frontend/src/components/FilterPanel.jsx:268-301`); applied summaries (`frontend/src/components/jobBrowserLayerSummary.js:37-43`) should describe the actual query, not use the lossy Job display format.

### P2: Search cards lack experience data

`backend/app/schemas/job_search.py:198-215` and response construction (`backend/app/api/jobs.py:585-603`) omit experience fields; `frontend/src/components/JobBrowser.jsx:965-1013` does not show experience. Adding concise labels to cards requires API and UI work, not just changing the detail formatter (`frontend/src/components/JobDetailModal.jsx:100-128`). Treat card display as a proposed enhancement pending scope agreement.

## Relationship to issue #61

Existing `not_specified + null bounds` is a virtual `[0,1]` search interval; other level-only/null-bound rows are excluded by the active numeric filter (`backend/app/api/jobs.py:270-294`). Issue #61 already owns missing numeric evidence, inferred windows, historical repair, and explicit-vs-estimated provenance. Its historical counts are not fresh measurements. Coordinate rather than duplicate its repair scope, and revisit its interval-overlap contract only if the user explicitly chooses new search semantics here.

## Performance validation before optimization

The nullable OR overlap expression, independent min/max indexes (`backend/app/models/job.py:78-80`), and repeated facet candidate queries (`backend/app/services/job_search_facets.py:62-160`) are measurement targets, not demonstrated regressions. Use the existing read-only `backend/scripts/benchmark_job_search.py` for keyword baseline, extend benchmark coverage to experience windows if needed, and inspect PostgreSQL query plans with representative scopes. Consider indexes or candidate reuse only after timings/plans justify them. Existing progressive facet loading and window-count pagination are already optimizations and should be preserved.
