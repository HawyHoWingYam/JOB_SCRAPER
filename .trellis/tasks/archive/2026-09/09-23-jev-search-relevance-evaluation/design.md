# Phase 4 design

The evaluator consumes query cases containing a bounded ordered candidate list,
source-qualified identities, evidence hashes, explicit relevance grades, and a
frozen baseline score/order. It can record Jev judgments later, but candidate
membership remains immutable.

Metrics are candidate recall@K, MRR, NDCG@10, top-10 false relevance, tie
stability, and page/export parity. A technical failure returns the original
baseline order as product behavior while remaining an evaluation failure.

The runtime search system is not modified. In particular, semantic candidate
scope, structured filters, facet self-exclusion, applied scope, totals, and CSV
membership stay outside the model decision boundary.
