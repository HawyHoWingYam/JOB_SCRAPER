# Phase 4 search relevance result

Decision: **inconclusive**.

The offline bounded evaluation contract is ready, but no Jev reranking request
was sent because Phase 3B stopped on an ambiguous OpenRouter HTTP 520. Therefore
there is no legitimate measured NDCG improvement to compare with baseline.

## Frozen baseline

- Six explicit query/candidate sets across en, zh-Hant, and mixed language.
- Candidate recall@20: 1.0.
- Baseline MRR: 0.8333333333.
- Baseline NDCG@10: 0.8741169558.
- Source-identity tie stability: 1.0.
- Frozen page slices concatenate to the exact export ordering and membership.

## Product risks confirmed

- Current hybrid tokenization removes CJK characters, making Chinese lexical,
  source-classification, and Skill components zero.
- Semantic, hybrid, and related-Job orderings lack a final source-identity tie
  key for otherwise equal rows.
- Hybrid search/export loads and sorts the full embedding candidate set in
  Python without a candidate cap.

## Existing suite drift

- Backend `test_job_search_facets.py` cannot collect because it imports removed
  `CurrentCompanyIndustryAssignment`.
- Frontend JobBrowser: 15 passed, 2 failed; both failures still expect the
  removed `Company Industry` selector.
- These failures predate and are outside the offline Jev module; no obsolete
  Company Industry behavior was restored.

## Quality

- Phase 4 focused tests: 2 passed.
- Complete Jev regression: 77 passed, 1 skipped.
- Ruff, Black, and compileall passed.

No product search route, rank weights, facets, pagination, export, or UI was
changed.
