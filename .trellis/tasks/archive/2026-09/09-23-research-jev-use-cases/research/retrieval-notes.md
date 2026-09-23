# Retrieval scout synthesis

The retrieval scout returned its findings in the conversation rather than writing files because its read-only role disallowed writes. This note preserves the actionable portion; IDs 81–160 were individually skimmed upstream (121 unavailable) and integrated into the main ledger.

## Verified upstream facts

- `llama-index-jev` uses independent query/passage state, keeps original scores in metadata, and falls back to original retrieval order if any scoring call fails. Its confidence annotation does not itself remove results. [JevRerank source](https://github.com/WiktorB2004/llama-index-jev/blob/72c73dc50bca4b7ea6928ef65ea09f1a7ee4a01e/packages/llama-index-postprocessor-jev/llama_index/postprocessor/jev/base.py#L132).
- `invalidate` stores new evidence, audit judgments, source trust policy and lifecycle status separately. A loose candidate relevance screen precedes detailed judgments for larger pools; destructive disagreements become review. [Engine](https://github.com/chopratejas/invalidate/blob/d6ed0ea4e72660408dc175cd20caf6cb8658e9b0/src/invalidate/engine.py#L179).
- `jev-layer` filters route eligibility in code and uses explicit fallback paths for absent providers, malformed/unknown answers and low confidence. [Route implementation](https://github.com/typakon4/jev-layer/blob/b6a3cf455d0b855903b6e5140ed3a764e663e910/src/route.mjs#L7). Its context relevance filter is deterministic; it should not be described as a Jev semantic filter. [Filter](https://github.com/typakon4/jev-layer/blob/b6a3cf455d0b855903b6e5140ed3a764e663e910/src/relevance-filter.mjs#L1).
- `hippo-memory`'s README reports that three graded tests did not improve answer rate over a free local cross-encoder; a private recall result alone is not proof of better final answers. [README](https://github.com/kitfunso/hippo-memory).
- `jev-sift` documents preservation of source URLs, per-item errors and truncation; errors/truncation are not proof of irrelevance. This was a README observation, not source verification. [README](https://github.com/kbhuw/jev-sift).

## Local observations

`backend/app/services/retrieval_service.py:51` dispatches lexical, semantic and hybrid retrieval. Hybrid scores currently weight semantic 0.65, lexical 0.15, source classification 0.10, skills 0.05 and freshness 0.05 (`backend/app/search/hybrid_ranker.py:87`). The ranking path and CSV export need consistent treatment. The candidate scope preserves structured filters while removing the semantic text condition (`backend/app/search/semantic_query.py:10`).

## Inferences

Introduce a bounded candidate stage before any proposed remote rerank, preserve current order as fallback, and retain both retrieval and semantic-judgment provenance. Cache keys must include evidence/question/model identity; no such cache abstraction exists in the current retrieval service. Treat freshness suggestions as annotations on derived intelligence, never as permission to rewrite source postings. These are design proposals, not completed code changes.
