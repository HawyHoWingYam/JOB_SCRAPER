# Implementation plan: Repair and optimize Job Browser search

## Preconditions

- Review this PRD, design, and implementation plan before running
  `task.py start`.
- Keep the current Jev repair task separate; activate this task only when the
  team is ready to switch implementation context.

## Phase 1: Correct applied-state behavior and action semantics

- [x] Add failing `JobBrowser.test.jsx` regressions for facet retry using the
      committed retrieval mode, apply/facet mode parity, and no extra Jobs
      request on retry.
- [x] Centralize the committed scope/mode descriptor used by facets,
      pagination, export, and retry; remove any duplicate request property.
- [x] Add tests for Search all replacement, explicit refinement, edit/remove/
      clear behavior, and Enter in open/layered/edit states.
- [x] Update action labels/helper copy and keyboard dispatch so Enter matches
      the visible primary action.
- [x] Run focused frontend tests and the Job Browser usability E2E.

## Phase 2: Enforce the Description-only corpus

- [x] Add lexical query regressions for broad, exact, and quoted expressions
      that occur in Description versus only in title, AI summary, Company
      name/AI description, classification, or Skill labels/aliases.
- [x] Reduce lexical match predicates to Job Description while preserving
      structured filters and normalized exact boundaries.
- [x] Centralize the Description-only search-document builder used by
      embedding generation and hybrid lexical features.
- [x] Version/change the embedding document hash so broader legacy embeddings
      are stale, and test detection plus rebuild behavior.
- [x] Rebuild local embeddings through the supported operation and verify
      semantic/hybrid coverage before benchmarking ranked results.

## Phase 3: Establish performance baselines

- [x] Extend `backend/scripts/benchmark_job_search.py` with named lexical,
      facet, semantic, and hybrid scenarios plus cold/warm reporting.
- [x] Add candidate/result counts, timeout reporting, JSON output suitable for
      comparison, and independent budgets per scenario.
- [x] Capture baseline samples and query plans for representative broad text,
      exact phrase, structured-filter, semantic, hybrid, and facet requests.
- [x] Store summarized evidence in this task without committing secrets,
      vectors, or production text.

## Phase 4: Reuse the embedding model safely

- [x] Add unit/integration tests proving one model construction across
      sequential and concurrent requests with injected fakes.
- [x] Introduce a process-lifetime query-model provider while keeping database
      sessions request-scoped.
- [x] Route semantic and hybrid encoding through the provider and preserve
      normalized embeddings.
- [x] Add initialization timing/diagnostic logging and rerun cold/warm
      benchmarks plus retrieval entrypoint import-isolation tests.

## Phase 5: Bound semantic and hybrid work

- [x] Add tests for the approved bounded Top-K ranked-result total contract,
      no-embedding
      Jobs, empty/out-of-range pages, deterministic ties, structured filters,
      and export compatibility.
- [x] Separate database candidate ordering from optional hybrid reranking.
- [x] Fetch only the configured semantic window for hybrid and rerank only that
      bounded set in Python.
- [x] Apply the approved top-K/threshold contract to semantic results and
      expose response metadata needed for honest UI wording.
- [x] Update Job Browser result-count copy for bounded ranked results.
- [x] Compare representative top-result quality and latency to the baseline.

## Phase 6: Optimize database and facets

- [x] Use baseline plans to select text/vector/facet indexes; avoid speculative
      indexes with no observed plan benefit.
- [x] Add an idempotent existing-database upgrade path plus fresh-bootstrap
      parity for required extensions and named indexes.
- [x] Add schema verification and documented rollback commands/tests.
- [x] Optimize the shared Description candidate predicate/index path while
      retaining separate self-dimension-exclusion semantics for all three
      facet families.
- [x] Rerun facet correctness tests, plans, and benchmark scenarios after each
      query/index change.

## Phase 7: Full verification and documentation

- [x] Run targeted backend tests for search parsing/querying, facets,
      retrieval, ranking, API proxying, schema upgrade, and benchmark output.
- [x] Run targeted frontend component/scope/session tests and usability E2E.
- [x] Run repository formatting, lint, type-check, and build commands for every
      changed package; separate pre-existing failures with evidence.
- [x] Run the live warm benchmark with at least three samples per scenario and
      approved budgets. Confirm hybrid finishes below the public caller timeout
      with operational margin.
- [x] Update `.trellis/spec/backend/job-browser-search.md` with final contracts.
- [x] Run `trellis-check`, review the full diff, and commit only after all
      required checks pass.

## Likely files

- `frontend/src/components/JobBrowser.jsx`
- `frontend/src/components/SearchBar.jsx`
- `frontend/src/components/FilterPanel.jsx`
- `frontend/src/components/JobBrowser.test.jsx`
- `frontend/src/components/jobBrowserScopeUtils.js`
- `frontend/e2e/usability.spec.js`
- `backend/app/api/jobs.py`
- `backend/app/api/retrieval.py`
- `backend/app/schemas/job_search.py`
- `backend/app/services/retrieval_service.py`
- `backend/app/services/job_search_facets.py`
- `backend/app/search/semantic_query.py`
- `backend/app/search/hybrid_ranker.py`
- `backend/app/models/job_embedding.py`
- the existing embedding document builder and rebuild operation located during
  `trellis-before-dev`
- `backend/scripts/benchmark_job_search.py`
- `backend/tests/test_job_search_facets.py`
- new focused retrieval/model-lifecycle/schema-upgrade tests as appropriate

## Validation commands

Use repository-native commands discovered during `trellis-before-dev`; do not
assume package-manager or environment commands until then. Minimum validation:

```bash
python3 ./.trellis/scripts/task.py validate \
  .trellis/tasks/09-28-repair-optimize-job-browser-search

# Focused frontend component tests and usability E2E
# Focused backend search/facet/retrieval tests
# Frontend lint/build and backend formatter/linter/type checks
# Expanded benchmark with explicit jobs/facets/semantic/hybrid budgets
```

## Rollback points

- Commit frontend correctness separately from retrieval performance work.
- Commit model lifecycle separately from result-membership changes.
- Apply schema/index upgrades through deterministic named operations that can
  be reversed without dropping Job or embedding data.
- Keep the previous retrieval strategy selectable until the bounded strategy
  passes correctness, quality, and latency gates.
