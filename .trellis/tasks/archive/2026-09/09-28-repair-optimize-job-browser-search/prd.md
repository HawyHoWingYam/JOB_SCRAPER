# Repair and optimize Job Browser search

## Goal

Make Job Browser search predictable and responsive across lexical, semantic,
and hybrid modes. Results, facets, pagination, export, and retry actions must
always describe the same committed search, while expensive retrieval work is
bounded and measured instead of repeatedly loading models or ranking the full
corpus in application memory.

## Background

The current Job Browser supports layered scopes and three retrieval modes over
approximately 21,706 retained Jobs. A live read-only audit found:

- Lexical search is the reliable daily path, but a representative exact search
  (`=ERP`) took about 2.37 seconds for Jobs and 5.02 seconds for facets.
- Semantic search took about 7.17 seconds in the observed run.
- Hybrid search exceeded the 30-second caller timeout once and completed in
  about 24 seconds on retry.
- `Retry filter counts` sends the draft retrieval mode rather than the mode of
  the committed results (`frontend/src/components/JobBrowser.jsx:765`).
- Pressing Enter with an existing applied scope implicitly executes
  `Refine current results`, appending another AND layer
  (`frontend/src/components/JobBrowser.jsx:532`).
- The retrieval API constructs `RetrievalService` per request and its model
  cache is instance-local, so semantic and hybrid requests can reload
  `sentence-transformers/all-MiniLM-L6-v2`
  (`backend/app/api/retrieval.py:12`,
  `backend/app/services/retrieval_service.py:29`).
- Hybrid retrieval fetches every embedding-qualified candidate, scores every
  row, sorts the complete list in Python, and only then slices a page
  (`backend/app/services/retrieval_service.py:122`,
  `backend/app/search/hybrid_ranker.py:78`).
- Semantic and hybrid `total` currently mean the entire embedding-qualified
  candidate corpus, not a relevance-filtered match count. There is no top-K or
  similarity threshold (`backend/app/search/semantic_query.py:27`).
- One facets request rebuilds three independent candidate queries and performs
  separate distinct-count aggregations
  (`backend/app/services/job_search_facets.py:51`).
- The visible schema has ordinary B-tree indexes, but no PostgreSQL trigram,
  full-text, or pgvector ANN index declarations. The repository uses metadata
  bootstrap rather than a visible versioned migration framework.
- Current lexical broad/exact search can match Job title, Job description, AI
  summary, source classification, Company name, Company AI description, and
  governed Skill labels/aliases. This is broader than the intended Job Browser
  text-search corpus.

## Requirements

### R1. Keep one committed search contract

- Results, facets, pagination, export, and facet retry must use the retrieval
  mode and normalized scope belonging to the latest successful application.
- Changing a draft query, filter, or retrieval-mode control must not mutate or
  reinterpret already-displayed results until an explicit search action
  succeeds.
- A facet retry must retry only the failed facet request; it must not submit a
  new Jobs search or silently use draft state.
- Stale and aborted responses must remain unable to overwrite newer committed
  state, consistent with `.trellis/spec/backend/job-browser-search.md`.

### R2. Make replace and refine actions explicit

- `Search all jobs` remains the replace operation: it replaces the applied
  layered scope with the submitted root layer.
- `Refine current results` remains the append operation: it adds an AND layer
  to the committed scope.
- The UI must state these consequences close to the actions, including the
  current layer count when refinement is available.
- Enter must not silently choose a different scope operation based only on
  whether an old layer exists. Its behavior must be visually discoverable and
  covered by a component test.
- Editing an existing layer remains distinct from replacing the entire search
  or appending a new layer.

### R3. Search only Job Description text

- Every user-entered text expression in Job Browser must search only the Job's
  `description` content. Job title, AI summary, Company name, Company AI
  description, source classification labels, governed Skill labels/aliases,
  and any other fields must not independently cause a text match.
- This corpus boundary applies consistently to broad lexical tokens, `=exact`
  tokens, quoted phrases, semantic retrieval, and hybrid retrieval.
- Structured filters remain separate and continue to filter their governed
  fields. Restricting text search to Job Description must not remove Source,
  Source Classification, Employment Type, date, experience, or other explicit
  structured-filter behavior.
- Semantic Job embeddings used by Job Browser must be generated from the Job
  Description corpus only. Existing embeddings built from broader documents
  must be detected as stale and rebuilt through the established embedding
  rebuild path before semantic/hybrid results are considered current.
- Result cards may continue displaying title, Company, skills, classifications,
  and other metadata; those display fields are not search-match evidence.

### R4. Reuse the embedding model across requests

- The retrieval process must own one lazily or eagerly initialized query model
  per configured model/runtime lifecycle, rather than one model per HTTP
  request.
- Concurrent initialization must be safe and must not construct duplicate
  models for simultaneous first requests.
- Tests must inject a fake model without downloading model assets and prove
  that consecutive semantic/hybrid requests reuse the same initialized model.
- Startup/import isolation of the retrieval service must remain intact.

### R5. Bound semantic and hybrid retrieval work

- A normal result-page request must not materialize and Python-sort every
  embedding-qualified Job in a broad scope.
- Candidate selection, semantic ordering, hybrid reranking, pagination, and
  the meaning of `total` must have explicit contracts and deterministic
  ordering.
- Screen results and CSV export must use compatible membership/order rules;
  export may apply its existing independent maximum-row protection.
- Jobs without embeddings, empty result sets, out-of-range pages, ties, and
  structured filters must have explicit test coverage.
- Any relevance cutoff or candidate cap must be observable in the response or
  UI so that a bounded ranked result set is not presented as an exhaustive
  corpus match count.
- Semantic and hybrid use an explicitly bounded Top-K ranked result set. Their
  `total` and UI copy describe the bounded ranked set, not exhaustive matches
  across the embedding-qualified corpus.

### R6. Improve lexical and facet query execution safely

- Preserve normalized exact-match boundaries and layered AND semantics while
  optimizing the database path.
- Avoid repeated equivalent candidate-scope construction or aggregation inside
  one facet request when it can be shared without changing each facet's
  self-dimension-exclusion rule.
- PostgreSQL-specific text/vector indexes may be added only with an explicit
  existing-database upgrade path as well as a fresh-bootstrap path; model-only
  `create_all` changes are insufficient for existing sandboxes.
- Query/index changes must be justified by captured query plans or benchmark
  evidence and must not rely on unit-test timing assertions.

### R7. Extend measurement and operational diagnostics

- Extend `backend/scripts/benchmark_job_search.py` (or a focused companion)
  to measure lexical Jobs, facets, semantic, and hybrid paths separately.
- Record corpus/candidate/result counts, cold/warm distinction where relevant,
  at least three warm samples, medians, timeout/failure state, and explicit
  budget exit codes.
- Retrieval logs must make model initialization and bounded candidate counts
  diagnosable without logging query embeddings, secrets, or full Job text.
- A failure or timeout must keep the last successful rows visible and expose a
  local retry path for the failed operation.

## Acceptance Criteria

- [ ] After a successful semantic or hybrid search, changing the mode selector
      without applying and then clicking `Retry filter counts` sends the
      committed mode and scope; no Jobs request is issued.
- [ ] Result and facet requests created by one successful apply use identical
      retrieval modes, while pagination and export continue using that applied
      mode.
- [ ] Replace, refine, edit, remove, and clear operations each have component
      tests that assert the submitted layer list and visible applied layers.
- [ ] Enter-key behavior is stated in the UI and tested for open scope,
      layered scope, and edit mode; it never invisibly appends a layer contrary
      to the displayed primary action.
- [ ] Broad tokens, `=exact` tokens, and quoted phrases match Jobs when the
      expression occurs in Job Description and do not match when it occurs
      only in title, AI summary, Company name/AI description, classification,
      or Skill labels/aliases.
- [ ] Semantic and hybrid queries rank only Description-derived Job embeddings;
      the document hash/version invalidates previously broader embeddings, and
      the rebuild path restores current coverage without manual row edits.
- [ ] Structured filters continue working independently of the Description-only
      text corpus, including layered combinations with text expressions.
- [ ] Two consecutive semantic/hybrid requests in one retrieval process build
      the configured embedding model exactly once, including a concurrent
      first-request regression.
- [ ] Hybrid page retrieval does not fetch and rank the entire unbounded
      candidate corpus in Python; tests prove the candidate bound and stable
      pagination/tie behavior.
- [ ] Semantic/hybrid response and UI copy distinguish exhaustive filtered
      candidates from the approved bounded Top-K ranked-result total.
- [ ] Facet counts remain correct for self-dimension exclusion, structured
      intersections, source classifications, and semantic/hybrid candidate
      scope after optimization.
- [ ] Fresh database bootstrap and the documented existing-database upgrade
      path both create any new extensions/indexes; a rollback path is recorded.
- [ ] The benchmark command reports separate lexical Jobs, facets, semantic,
      and hybrid measurements with candidate counts and exits non-zero when an
      approved budget is missed.
- [ ] On the representative local corpus, warm requests meet budgets selected
      during implementation planning, with raw samples captured in the task;
      hybrid must complete within the public caller timeout with margin.
- [ ] Targeted frontend/backend tests, frontend build/lint, backend formatting,
      lint, and relevant type checks pass, with pre-existing failures clearly
      separated.
- [ ] `.trellis/spec/backend/job-browser-search.md` is updated with the final
      applied-state, Enter-action, retrieval-bound, total, index, and benchmark
      contracts.

## Out of Scope

- Replacing the current governed taxonomy or layered-scope domain model.
- Adding Company Industry back to Job Browser filters.
- Changing Jev, AI enrichment, crawler, or Job Detail behavior.
- Introducing a new external search platform unless measurements show that the
  existing PostgreSQL/retrieval-service boundary cannot meet the approved
  budget and the user separately approves that expansion.

## Product Decisions

- Job Browser text search uses Job Description as its only searchable text
  corpus across lexical, semantic, and hybrid modes.
- Semantic and hybrid return a bounded Top-K ranked result set with explicit
  ranked-result wording. They do not claim an exhaustive relevance-match total.
