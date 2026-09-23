# Jev phase 4: bounded search relevance evaluation

## Goal

Evaluate whether a bounded Jev judgment can improve ordering inside an existing
search candidate set without changing scope, filters, facets, totals,
pagination membership, export membership, or source-qualified Job identity.

## Requirements

- Versioned explicit relevance cases cover en/zh-Hant/mixed queries, hard
  negatives, negation, missing evidence, ties, filters, and page boundaries.
- Candidate generation and reranking are scored separately. Missed relevant
  Jobs remain candidate-recall failures.
- Offline reranking is bounded, deterministic, and falls back to the complete
  baseline order on unavailable/invalid/budget failure.
- Facets derive from the full candidate scope, not the reranked page. Search
  pages and export must be slices of the same stable complete ordering.
- Freeze gates before held-out work: candidate recall@20 >= .95, NDCG@10
  improvement >= .03 without MRR regression, top-10 false-relevance rate <=
  .05, tie stability 1.0, page/export parity 1.0, technical failure <= .05.
- No product search route/weights/schema/UI change in this evaluation task.
- Because the current provider sequence stopped on HTTP 520, no Phase 4 real
  Jev request may be sent until that ambiguous state is explicitly resolved.

## Acceptance criteria

- [x] Strict controlled corpus and deterministic metrics pass tests.
- [x] Existing hybrid baseline is measured with Chinese/token and tie risks
  explicit; no upstream/model agreement is called ground truth.
- [x] Pagination/export membership invariants pass on frozen data. Existing
  backend/frontend facet suites are blocked by stale removed Company Industry
  expectations and are reported, not silently ignored.
- [x] Produce proceed/defer/inconclusive result with cost and limitations.
- [x] Focused/full Jev regression, lint/format/compile and diff checks pass.
