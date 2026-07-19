# Job Intelligence Product Read Contracts

## Scenario: Compose governed projections for product surfaces

### 1. Scope / Trigger

Use this contract when changing Job Intelligence Governance summary reads,
Job/Company search or detail payloads, Dashboard coverage, Related Jobs,
frontend governance queues, or backend-owned fixtures consumed by the frontend.

Product surfaces compose the domain contracts owned by Source Job Attributes,
Canonical Job Taxonomy, Company Industry, and Skill Governance. They do not
reimplement mapping or transition rules and never promote legacy scalar fields
to governed knowledge.

This is the child-6 product-read boundary. Switching embedding/corpus authority,
rebuilding live projections, backfilling, activating revisions, and destructive
cutover remain child-7 operations and require their own rollout approval.

### 2. Signatures

The backend composition seam is:

```python
JobIntelligenceProductReadModel(db).get_governance_summary() \
    -> JobIntelligenceGovernanceSummaryView
JobIntelligenceProductReadModel(db).get_job_detail(
    job_id: UUID,
    company_id: UUID,
) -> JobIntelligenceJobDetailView
JobIntelligenceProductReadModel(db).get_company_details(
    company_ids: Sequence[UUID],
) -> dict[UUID, dict[str, object]]
JobIntelligenceProductReadModel(db).get_canonical_job_states(
    job_ids: Sequence[UUID],
) -> dict[UUID, dict[str, object]]
JobIntelligenceProductReadModel(db).get_employment_type_states(
    job_ids: Sequence[UUID],
) -> dict[UUID, dict[str, object]]
JobIntelligenceProductReadModel(db).get_governed_skill_name_states(
    job_ids: Sequence[UUID],
) -> dict[UUID, dict[str, object]]
```

The route/adaptor seams include:

```text
GET /api/v1/job-intelligence/governance/summary
GET /api/v1/jobs/search
GET /api/v1/jobs/{job_id}
GET /api/v1/companies
GET /api/v1/companies/{company_id}
GET /api/v1/jobs/{job_id}/recommendations
```

Frontend governance queue hashes are:

```text
#job-intelligence/<area>?item=<stable-id>&q=<domain-filter>&cursor=<opaque-cursor>
```

`governanceAreas.js` owns the domain filter mapping: Canonical Review uses
`job_id`, Skill Candidates use `search`, and Company Industry Review uses
`raw_value`. React queue mechanics only pass `query`, `cursor`, and `limit`.

### 3. Contracts

- Every governed read is pinned to the domain's active revision. Assignments,
  Review references, backlog counts, oldest timestamps, coverage, and reason
  distributions from inactive revisions are excluded.
- An unavailable active revision returns domain availability with
  `available=false` and a stable `unavailable_code`. It never falls back to a
  legacy column and contributes zero governed backlog/coverage.
- Available-but-empty is distinct from unavailable. An existing Source Job
  Attribute projection with no Employment Types is `available=true` plus `[]`;
  no projection is `available=false`, `SOURCE_JOB_ATTRIBUTES_NOT_PROJECTED`,
  plus `[]`.
- Search cards, Company lists, and Related Jobs batch projection reads for the
  whole result set. Per-result domain reader calls are forbidden.
- Related Jobs expose `employment_types[]`, `canonical_taxonomy`, and
  `job_intelligence_availability`. `jobs.employment_type`, legacy
  `job_taxonomy`, provisional Skills, and other legacy evidence are excluded
  from ranking and serialized governed fields.
- Recommendation scoring reads active governed Skill names and stable
  Canonical Taxonomy codes. Unexpected untyped payload values fail closed to
  empty governed sets rather than becoming iterable legacy data.
- Frontend route/response tests consume committed backend fixtures. Backend
  Pydantic schemas validate each fixture and tests assert backend/frontend JSON
  copies are equal.
- Queue search is server-side and domain-owned, cursor pagination is opaque,
  and `q`/`cursor` survive item deep links and narrow-detail back navigation.
  Arrow/Home/End navigation moves queue focus; Back and successful decisions
  return focus to a surviving queue item or the queue search field.
- Governance decisions exist only in the trusted-local Governance workspace.
  Job Detail, Companies, AI Enrichment, Dashboard, and Browser remain read-only
  and deep-link into Governance.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Domain has no active revision | `available=false`, stable domain code, no legacy fallback |
| Active pointer exists but is inconsistent | Domain conflict code; no partial governed payload |
| Source projection exists with zero mappings | `available=true`, empty Employment Types |
| Source projection is absent | `SOURCE_JOB_ATTRIBUTES_NOT_PROJECTED`, empty data |
| Inactive revision has pending Reviews/Candidates | Exclude from summary, coverage, reasons, and Company review refs |
| Availability says unavailable while governed data is populated | Pydantic validation failure |
| Queue filter/cursor changes | Abort stale request; URL and API receive the same domain filter/cursor |
| Optional detail section fails | Keep evidence visible; name the partial failure and disable only dependent actions |
| Decision returns stale version | Close stale confirmation, reload detail, explain conflict |
| Container fixture test cannot see frontend copy | Mount frontend read-only; do not skip equality validation |

### 5. Good / Base / Bad Cases

- **Good:** one Related Jobs request bulk-loads projections for source plus all
  candidates, scores governed Skills/stable codes, and returns explicit
  availability for every recommendation.
- **Good:** a new active taxonomy revision has one pending Review while an old
  revision has ten. Summary reports one and its oldest timestamp; old reasons
  do not affect Dashboard coverage.
- **Base:** a Job has a Source projection but no Employment Type mappings. The
  product displays an available empty state rather than `Unknown` or a legacy
  scalar.
- **Base:** a deep-linked Review is no longer on the current queue page. Its
  typed detail still loads while the queue independently shows its empty page.
- **Bad:** count all `status='active'` Reviews without filtering the active
  revision, or expose every historical Company Industry review reference.
- **Bad:** loop through recommendation candidates and call domain readers once
  per candidate, or render `job.employment_type` as governed Employment Type.

### 6. Tests Required

- `test_job_intelligence_response_contracts.py` validates the complete product
  fixture, availability/data consistency, Job/Company/search/Dashboard reads,
  governed Related Jobs, one-query-per-projection batching, empty-versus-missing
  Source projections, inactive-revision backlog isolation, and inactive Company
  Review reference isolation.
- Domain fixture tests validate Canonical, Company Industry, Skill, and Source
  response models; exact-copy tests compare all four frontend fixtures.
- `JobIntelligenceGovernancePage.test.jsx` covers peer tabs, trusted-local
  warning, server filters/cursors, deep links, queue keyboard focus, narrow Back,
  partial errors, confirmation variants, stale conflict, and post-decision
  focus.
- `JobBrowser.test.jsx`, `FilterPanel.test.jsx`, `JobDetailModal.test.jsx`,
  `CompanyIndustryDisplay.test.jsx`, `AIEnrichmentPage.test.jsx`, and
  `Dashboard.test.jsx` prove canonical terminology, stable IDs, unavailable /
  Unassigned / Unknown states, and read-only deep links.
- Run PostgreSQL files sequentially against an explicitly disposable database
  whose name ends in `_test`. In the backend container, mount
  `frontend:/frontend:ro` for fixture equality tests.
- Manual browser QA covers desktop and narrow width, long English/CJK labels,
  long hashes/IDs, tab and queue keyboard navigation, dialog focus/Escape, and
  zero document-level horizontal overflow.

### 7. Wrong vs Correct

#### Wrong: revision-agnostic product metrics and per-item reads

```python
pending = db.query(ReviewItem).filter(ReviewItem.status == "active").count()
for job in candidates:
    skills = SkillGovernanceReader(db).get_job_state(job.id)
```

Old releases pollute current metrics and the candidate loop creates N+1 reads.

#### Correct: active-revision predicates and bulk composition

```python
pending = db.query(ReviewItem).filter(
    ReviewItem.status == "active",
    ReviewItem.taxonomy_revision_id == active_revision.id,
).count()

states = JobIntelligenceProductReadModel(db).get_governed_skill_name_states(
    [source_job.id, *(job.id for job in candidates)]
)
```

One active governed authority drives metrics and one bulk read feeds every
consumer result.
