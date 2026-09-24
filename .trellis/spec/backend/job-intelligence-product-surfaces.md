# Job Intelligence Product Read Contracts

## Scenario: Compose Source evidence and governed Skills

### 1. Scope / Trigger

Use this contract when changing Job Detail, Job Browser cards, Company reads,
CSV export, embeddings, Related Jobs, availability payloads, or mirrored product
fixtures. Job classification is Source-owned; product responses do not expose a
project Job taxonomy state.

### 2. Signatures

```python
JobIntelligenceProductReadModel(db).get_governed_skill_name_states(job_ids)
CurrentEmbeddingDocumentBuilder().build_for_job(db, job)
JobRecommendationService(db).recommend_for_job(job_id, limit)
```

Primary HTTP reads are `GET /api/jobs/{id}`, `POST /api/jobs/search`,
`POST /api/jobs/search/export`, `GET /api/jobs/{id}/similar`, and Company APIs.
Source-preserving duplicate reads use
`GET /api/jobs/{id}/duplicate-associations`; they are distinct from semantic
Related Jobs.

### 3. Contracts

- Role evidence exposes Source-qualified Classification Paths and governed
  Employment Types without promoting legacy scalar labels.
- Company responses expose ordinary Company-owned fields only. Company Industry
  governed state, availability, filters, routes and fixture fields were removed;
  do not reconstruct them from the legacy free-text `industry` column.
- `skill_state.skills` contains governed Skills. `candidate_mentions` and the
  compatibility `skill_candidate_mentions` expose unresolved Candidate evidence.
- Job Detail may expose one `jev_skill_classification` audit summary containing
  only classification/run identity, status/error, model, request ID, reported
  USD cost and completion time. This is a local latest-record read; it never
  dispatches Jev or serializes the full receipt/evidence/answers.
- Job Detail exposes `jev_operations` as the latest durable batch-item state for
  Skills correction, Possible same vacancy and Related Jobs. The state is
  independent of result counts, so a completed operation remains visible when
  it produced no governed Skill, duplicate proposal or Related Job.
- Ordinary Skill search/filter/export/embedding uses governed Skills only.
- Related Jobs requires the source embedding and ranks candidates as
  `0.80 semantic + 0.15 governed Skill overlap + 0.05 freshness`.
- Related Jobs initially fetches a wider vector candidate set, sorts by combined
  score with deterministic tie breakers, deduplicates case-insensitive titles,
  and then applies the requested limit.
- Possible Same Vacancy renders current `proposed`/`confirmed` association rows,
  the other Job's source-qualified identity, state and secret-safe Jev receipt.
  It never hides either Job and never labels the Related Jobs combined score as
  duplicate confidence.
- `backend/tests/fixtures/job_intelligence_product_surfaces.json` and its
  frontend mirror are exact copies and contain no removed Job-taxonomy or
  Company-Industry projection fields.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Source attributes were never projected | Empty source evidence plus explicit unavailable state |
| Skill projection exists but is empty | Available empty state, not missing |
| Candidate is unresolved | Show Candidate evidence; do not include in governed Skill filters/embedding |
| Source Job embedding is missing | Return no Related Jobs |
| Recommendation score is absent | Serialize/display score unavailable, never invent `0%` |
| Duplicate association provider/read is unavailable | Keep Job Detail and both Source Jobs usable; show no confirm action |
| Fixture copies differ | Contract test fails |

### 5. Good / Base / Bad Cases

- **Good:** Job Detail shows JobsDB paths, governed Python, and unresolved Rust
  Candidate evidence side by side.
- **Base:** no governed Skills matched yet while Candidate evidence remains
  visible and actionable through automatic processing.
- **Good:** two semantically close Jobs with shared Python receive a higher
  score; no Job-category score participates.
- **Bad:** combine Source classifications into one project hierarchy.
- **Bad:** feed Candidate terms into ordinary Skill filtering or embeddings.

### 6. Tests Required

- Backend schema/fixture tests validate Source evidence, Skills, Candidate
  Mentions, availability, CSV, embeddings, and 80/15/5 scores; they reject
  stale Company Industry projection assumptions by validating current schemas.
- Recommendation tests cover missing embeddings, governed Skill overlap,
  freshness, deterministic sort, title deduplication, and limits.
- Frontend Job Detail tests explicitly retain Skill Candidate Evidence and
  verify no legacy classification fallback.
- Duplicate component/E2E tests assert source identity, explicit review,
  unavailable fallback and both Job cards remaining after confirmation.
- Fixture parity is checked on the host when the backend-only test container
  does not mount `frontend/`.

### 7. Wrong vs Correct

#### Wrong

```python
payload["company_industries"] = infer_from_legacy_text(company.industry)
```

#### Correct

```python
score = semantic * 0.80 + governed_skills * 0.15 + freshness * 0.05
```

Company Industry is absent. Related Jobs uses semantic meaning, governed Skills,
and recency only.
