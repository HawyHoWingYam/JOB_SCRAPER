# Job Intelligence Product Read Contracts

## Scenario: Compose product responses from ordinary current taxonomies

### 1. Scope / Trigger

Use this contract when changing Job Detail, manual-Job snapshots, Job or Company
search responses, Dashboard taxonomy statistics, Related Jobs, CSV export, or
backend-owned fixtures consumed by the frontend.

### 2. Signatures

```python
compose_current_job_detail(db: Session, job: Job) -> JobDetailSchema
JobIntelligenceProductReadModel(db).get_job_detail(
    job_id: UUID,
    company_id: UUID,
) -> JobIntelligenceJobDetailView
JobIntelligenceProductReadModel(db).get_company_details(company_ids) -> dict
JobIntelligenceProductReadModel(db).get_canonical_job_states(job_ids) -> dict
JobIntelligenceProductReadModel(db).get_governed_skill_name_states(job_ids) -> dict
```

The product composes current state from the ordinary taxonomy routes and tables
documented in `ordinary-current-taxonomies.md`.

### 3. Contracts

- `compose_current_job_detail` serializes ordinary Job fields through
  `JobSchema`, adds safe detail scalars, overlays the current product payload,
  and validates one complete `JobDetailSchema`.
- Job Detail includes structured salary, `origin`, `manual_editable`,
  `enrichment_eligibility`, `job_intelligence_freshness`, and
  `company_website`. Manual Entry renders as `manual_entry`; only Manual Jobs
  are editable. Freshness is derived from Manual evidence hashes, never in the UI.
- Company reads expose normalized `website` and
  `ai_description_updated_at`; ordinary Company create input does not accept
  `ai_description`.
- Manual structured salary accepts only `AUD`, `CAD`, `CNY`, `EUR`, `GBP`,
  `HKD`, `JPY`, `SGD`, or `USD`; the command normalizes the code to uppercase.
- Never validate a raw `Job` ORM instance as `JobDetailSchema`: a retired ORM
  property can trigger a query against a table absent from the current schema
  before the current payload is overlaid.
- Job Taxonomy state is `assigned` or `unassigned`. There are no reasons,
  revision IDs, Review references, or Governance deep links.
- Skill authority is `current_job_skill_assignments`. Active unresolved
  evidence appears as `skill_state.candidate_mentions` and the equal top-level
  `skill_candidate_mentions` convenience field. `provisional_skills` and
  `unreviewed_skill_mentions` are absent.
- Company Industry returns current stable-code assignments; product reads never
  fall back to `Company.industry` as taxonomy authority.
- Search cards, Company lists, Related Jobs, stats, and CSV load current
  projections in bulk for the result set. Per-item taxonomy reader calls are
  forbidden.
- Related Jobs score current Skill names and stable Job Taxonomy codes. Model
  provenance metadata may contain a third-party model version; this is not a
  taxonomy version and is never used to select taxonomy state.
- Backend and frontend fixture copies are exact JSON equals.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Raw ORM Job is passed directly to `JobDetailSchema` | Forbidden implementation; regression suite fails without legacy tables |
| Current Job assignment is absent | `state=unassigned`, `assignment=null` |
| Candidate Mentions are absent | Both Candidate Mention arrays are empty |
| Current taxonomy code is unknown to the reader | Fail the composed response; do not use legacy text |
| Required composed state is missing or availability contradicts data | Pydantic validation failure |
| Frontend/backend fixture copies differ | Product contract test failure |
| Manual Job description is blank | `enrichment_eligibility=needs_job_description` |
| Manual evidence hash differs from last enriched hash | Old intelligence remains visible with `job_intelligence_freshness=stale` |
| Collected Job requests Manual edit route | Reject; collected facts remain read-only |

### 5. Good / Base / Bad Cases

- **Good:** one bulk read composes Job, Company Industry, Skills, and Candidate
  Mentions while no legacy Governance tables exist.
- **Base:** an unenriched Job is Unassigned with empty Skills and Candidate
  Mentions.
- **Good:** Manual Job Detail exposes operator fields as editable and keeps AI
  summary/taxonomy/Skills outside the mutation command.
- **Bad:** serialize the raw ORM object first and overwrite Skills afterward.
- **Bad:** show a Governance link or use a legacy revision-bound projection when
  the current assignment is empty.

### 6. Tests Required

- `test_job_intelligence_response_contracts.py` creates only ordinary current
  taxonomy tables in a disposable `_test` PostgreSQL database and covers Job
  Detail, manual snapshot, Company, filters, recommendations, stats, and CSV.
- `test_current_taxonomies.py` validates current response shapes and the absence
  of revision/review routes.
- `JobDetailModal.test.jsx`, `JobBrowser.test.jsx`,
  `CompanyIndustryDisplay.test.jsx`, and `Dashboard.test.jsx` consume committed
  current fixtures and assert no legacy fallback or Governance workspace.
- The backend test container mounts `/frontend` read-only for exact fixture
  equality.
- Manual intake/product tests cover structured salary, origin/editability,
  needs-description, stale/current intelligence, and Company website round-trip.

### 7. Wrong vs Correct

#### Wrong

```python
payload = JobDetailSchema.model_validate(job).model_dump(mode="python")
payload.update(current_product_payload)
```

#### Correct

```python
return compose_current_job_detail(db, job)
```

The shared composer prevents API, snapshots, and exports from privately
reintroducing retired ORM authority.
