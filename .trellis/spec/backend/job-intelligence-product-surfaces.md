# Job Intelligence Product Read Contracts

## 1. Scope / Trigger

Use this contract when changing Job Detail, Browser cards, export, embeddings,
Related Jobs, schemas, or mirrored product fixtures.

## 2. Signatures

```python
JobIntelligenceProductReadModel(db).get_governed_skill_name_states(job_ids)
CurrentEmbeddingDocumentBuilder().build_for_job(db, job)
RelatedJobsService(db).recommend_for_job(job_id, limit=5)
```

Primary reads include `GET /api/jobs/{id}`, `POST /api/jobs/search`,
`POST /api/jobs/search/export`, and `GET /api/jobs/{id}/similar`.

## 3. Contracts

- Job Detail exposes Source-qualified Classification Paths, governed Employment
  Types, governed Skills, summary, experience, and one Related Jobs section.
- Internal unresolved Skill evidence is not serialized into the product
  payload and is not searchable.
- A usable current snapshot returns `result_source="ai_ranked"`, at most five
  live targets in saved order, and one concise `reason` per result.
- Missing, empty, or unusable snapshots return
  `result_source="similarity"` from the deterministic service without an AI
  reason or provider call.
- The UI labels these states exactly `AI-ranked from the latest enrichment`,
  `Suggested by job similarity`, or `No related jobs available`.
- Product responses expose no separate provider receipt, model, request ID,
  cost, evaluation status, secondary operation state, or duplicate-vacancy
  review surface.
- Deterministic similarity uses semantic score, governed Skill overlap, and
  freshness with stable tie breakers and title deduplication.
- Backend and frontend copies of
  `job_intelligence_product_surfaces.json` remain exact mirrors.

## 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Skill projection exists but is empty | Available empty governed Skill state |
| Unresolved Skill evidence exists | Keep internal; omit from product response |
| Saved target is deleted/unavailable | Omit target; fall back if no live target remains |
| Source embedding is missing | Deterministic service may return an empty list |
| Fixture copies differ | Contract test fails |

## 5. Good / Base / Bad Cases

- Good: Job Detail shows governed Python and an AI-ranked related role with a
  concise reason.
- Base: snapshot has no usable row, so deterministic similarity is shown.
- Bad: issue an LLM call while opening Job Detail.
- Bad: expose internal unresolved evidence as a review action.

## 6. Tests Required

- Backend tests cover schema/fixture parity, governed Skills, export,
  embeddings, snapshot ordering, replacement, deleted targets, and fallback.
- Frontend tests cover the three exact Related Jobs labels and absence of
  secondary operations or unresolved-evidence panels.

## 7. Wrong vs Correct

### Wrong

```python
return llm.rank_candidates(job_id)
```

### Correct

```python
snapshot = load_usable_snapshot(job_id)
return snapshot or deterministic_similarity(job_id)
```
