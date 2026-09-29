# Technical design: Repair and optimize Job Browser search

## Scope and boundaries

This change keeps the existing public endpoints and layered-scope vocabulary:

```text
JobBrowser draft state
    -> POST /api/jobs/search
    -> public API / RetrievalClient
    -> retrieval API / RetrievalService
    -> PostgreSQL lexical or vector candidate query
    -> ordered page + committed applied scope/mode
    -> independent POST /api/jobs/search/facets
    -> JobBrowser applied state
```

The implementation should deepen these existing boundaries rather than create
an alternate search stack. `JobBrowser` owns draft versus committed UI state;
the public API owns request validation and compatibility; `RetrievalService`
owns retrieval semantics; query modules own database candidate selection and
ordering; `JobSearchFacets` owns self-dimension-excluding counts.

## 1. Description-only search corpus

Define one shared Job Browser search-document contract whose only text source
is `Job.description`. Lexical predicate construction, embedding document
construction, hybrid lexical features, benchmark fixtures, and match tests must
all consume this same contract. Company joins remain available for result
projection but must not contribute text-match predicates.

The parser syntax does not change:

- broad terms apply Description-only substring/token semantics;
- `=exact` applies normalized boundary matching within Description only;
- quoted phrases apply normalized phrase/boundary matching within Description
  only;
- semantic and hybrid query vectors compare against Description-only Job
  embeddings.

Structured filters remain orthogonal. A Source Classification or Skill filter
may constrain candidates only when the user explicitly selects that structured
filter; those labels cannot satisfy a text expression.

Embedding provenance must be versioned. Change the canonical embedding
document/hash contract so rows produced from title, Company, AI summary,
classification, skills, or other former inputs are stale. Reuse the existing
rebuild operation to regenerate them from Description only, and expose coverage
until rebuilding is complete rather than silently mixing document versions.

## 2. Frontend committed-search state

Treat the latest successful `{scope, retrievalMode}` as one immutable applied
search descriptor. The existing separate state variables may remain if all
consumers are centralized through one applied descriptor/helper, but retry,
pagination, and export must not reach into draft state.

Action semantics:

| Action | Scope effect | Mode source |
|---|---|---|
| Search all jobs | Replace with one root layer, or clear | Draft mode submitted by the action |
| Refine current results | Append one non-empty AND layer | Draft mode submitted by the action |
| Save layer | Replace one existing `client_id` | Draft mode submitted by the action |
| Retry filter counts | No scope mutation | Committed mode |
| Pagination | No scope mutation | Committed mode |
| Export | No scope mutation | Committed mode |

The primary keyboard action should match the visually designated primary
button. Recommended behavior: Enter activates `Search all jobs` outside edit
mode, even when applied layers exist; refinement remains an explicit button.
In edit mode Enter continues to `Save layer`. If product review chooses a
different Enter behavior, the primary-action label and test must change with
it so the operation is never implicit.

## 3. Retrieval model lifecycle

Move query-model ownership out of request-scoped `RetrievalService` instances.
Use a process-lifetime provider with:

- lazy initialization to avoid loading the model for lexical-only traffic;
- a concurrency-safe once-only initializer;
- dependency injection for tests and alternative configured models;
- a narrow `encode_query(text) -> normalized vector` interface;
- a process-shutdown release hook only if the runtime requires one.

Do not place mutable request data in the singleton. `RetrievalService` remains
request-scoped around its database session and receives the model provider.
This preserves testability and prevents a long-lived service from retaining a
request-scoped SQLAlchemy session.

## 4. Bounded semantic and hybrid execution

Separate retrieval into explicit stages:

```text
normalized scope
    -> structured candidate scope
    -> database-ranked semantic candidate window
    -> optional hybrid rerank of that bounded window
    -> deterministic page projection
```

Approved contract:

- Semantic: order candidates in PostgreSQL by vector distance, with stable Job
  tie-breakers, and apply a configured ranked-result bound.
- Hybrid: fetch only a bounded semantic candidate window from PostgreSQL, then
  apply the existing lexical/classification/skill/freshness reranker to that
  bounded set in Python.
- Page slices come from the stable ranked set. A requested page outside the
  bounded set is empty and retains the bounded total.
- The API identifies the total as bounded/ranked rather than exhaustive; the
  UI uses wording such as “ranked results” instead of “matching jobs.”
- Facets continue to describe the structured candidate scope, not the top-K
  ranked window, matching the existing contract.

Candidate bound, over-fetch factor, and any similarity floor belong in one
typed retrieval configuration owner. They must not be duplicated between the
public API, retrieval API, export path, and benchmark script.

## 5. Database optimization and schema evolution

Begin with captured `EXPLAIN (ANALYZE, BUFFERS)` plans for representative broad,
exact, structured, and facet requests. Add only indexes the plans can use.

Likely candidates, to validate rather than assume:

- `pg_trgm` GIN indexes or a maintained normalized search document for broad
  `%term%` predicates;
- a pgvector HNSW/IVFFlat index with the cosine operator class for semantic
  ordering;
- composite/partial indexes supporting retained-Job predicates and common
  facet joins.

Because no versioned migration framework is visible, schema work must include
an idempotent upgrade command/script for existing databases and register the
same extension/index definitions in fresh bootstrap. It must verify extension
availability, use deterministic names, tolerate already-applied upgrades, and
document safe removal. Do not silently depend on `metadata.create_all()` to
alter existing tables.

## 6. Facet execution

Preserve the semantic rule that each facet removes its own filter family while
retaining every other layer/filter. Optimize by sharing normalized scope and
reusable base predicates, and by consolidating database round trips only where
the resulting SQL remains understandable and plan evidence improves.

Do not cache facets across arbitrary scopes in the first implementation. A
short-lived cache can be considered only after query optimization, with a
canonical normalized-scope key and explicit invalidation for Job/taxonomy
changes. This avoids hiding slow queries behind stale operational data.

## 7. Measurement and observability

Extend the existing benchmark rather than inventing a disconnected harness.
Each scenario should capture:

- retrieval mode and normalized scope label;
- retained corpus and embedding-qualified candidate counts;
- cold initialization separately from at least three warm samples;
- Jobs median, facets median, failures/timeouts, and configured budgets;
- optional saved explain-plan artifact for PostgreSQL-specific work.

Production-safe logs should include a request correlation identifier, mode,
candidate/window/page sizes, model initialization duration, database duration,
rerank duration, and total duration. They must not include vectors, full search
documents, secrets, or complete Job descriptions.

## Compatibility and rollout

1. Ship frontend consistency and model reuse first; neither requires changing
   result membership.
2. Establish expanded benchmarks and record a before baseline.
3. Add existing-database schema/index upgrade with bootstrap parity and verify
   rollback in the sandbox.
4. Rebuild stale embeddings from the Description-only document contract, then
   enable bounded retrieval behind one server-side configuration seam and
   compare result quality plus latency before making it the default.
5. Update UI total wording and API metadata atomically with the bounded default.

Rollback should be possible by restoring the previous retrieval strategy
configuration and dropping only explicitly named optional indexes. Applied UI
state fixes and process-lifetime model reuse are independently reversible and
should not depend on the ranked-result rollout.

## Risks

- Approximate vector indexes can change tie/order behavior and recall; tests
  must assert deterministic tie-breakers without pretending ANN is exact.
- Too-small hybrid candidate windows may improve latency while harming result
  quality. Record representative queries and compare expected top results.
- Index creation may lock or consume substantial resources. Use a documented
  sandbox procedure and choose concurrent creation where supported.
- Process-lifetime ML models consume memory continuously. Record resident-memory
  impact and keep lazy initialization.
- Facet counts and ranked totals intentionally describe different populations;
  UI wording must prevent users from reading one as the other.
