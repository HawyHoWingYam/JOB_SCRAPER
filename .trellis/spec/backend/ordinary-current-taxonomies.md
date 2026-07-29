# Ordinary Current Taxonomy Contracts

## Scenario: Read and write Company Industry and Skill state

### 1. Scope / Trigger

Use this contract when changing current taxonomy nodes, aliases, Company
Industry assignments/mappings, governed Job Skills, Skill Candidates/Mentions,
their product reads, or the current-taxonomy HTTP API.

The project does not own a cross-Source Job taxonomy. Job classification stays
as Source-qualified `Source Classification Path` evidence. Company Industry and
Skill each have one ordinary current state without releases or review queues.

### 2. Signatures

```python
CurrentTaxonomyStore(db).synchronize(snapshot) -> None
CurrentTaxonomyStore(db).replace_company_industries(command) -> None
CurrentTaxonomyStore(db).replace_job_skills(command) -> None
CurrentTaxonomyReader(db).get_tree("company_industry" | "skill")
CurrentTaxonomyReader(db).get_company_industry_state(company_id)
CurrentTaxonomyReader(db).get_job_skills(job_id)
CurrentSkillEnrichment(db).replace_job_skills(...)
project_current_company_industry(db, company_id, evidence)
```

```text
GET /api/job-intelligence/company-industries/tree
GET /api/job-intelligence/companies/{company_id}/industries
GET /api/job-intelligence/skills/tree
GET /api/job-intelligence/jobs/{job_id}/skills
```

Persistence is owned by `current_taxonomy_nodes`,
`current_taxonomy_aliases`, `current_company_industry_assignments`,
`current_job_skill_assignments`, `current_skill_candidates`,
`current_job_skill_mentions`, and `current_source_taxonomy_mappings`.
`taxonomy` is restricted to `company_industry` or `skill`.

### 3. Contracts

- Stable node `code` values are identity; no payload carries a release,
  revision, active pointer, or lock version.
- Company Industry preserves the current HSIC hierarchy. Skills preserve
  Category / Technology / Skill nodes and aliases.
- Resolved governed Skills live in `current_job_skill_assignments` and power
  Job filtering, export, analytics, embeddings, and Related Jobs scoring.
- Unknown normalized terms remain visible evidence through
  `current_skill_candidates` and active `current_job_skill_mentions`.
  Candidate evidence is not silently promoted into ordinary Skill reads.
- Repeated Candidates may be automatically classified and promoted; promotion
  resolves Mentions and rebuilds affected Job Skill projections atomically.
- Governed local generic/rejected dispositions run before Candidate upsert.
- Company Industry Source mappings are Source-qualified and deterministic;
  display-label guessing is forbidden.
- Shared taxonomy infrastructure must not be deleted when removing one domain.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| `taxonomy` is not `company_industry` or `skill` | Reject before write |
| Parent code is absent from the same taxonomy | Reject snapshot |
| Assignment target is unknown, inactive, or not assignable | Reject and roll back caller transaction |
| Company mapping is absent or drifts from its manifest | Leave unassigned or fail the batch item; never infer |
| Unknown Skill repeats | Recompute Candidate/Mention evidence; do not expose it as governed Skill |
| Known generic/rejected term appears | Retain terminal Mention evidence; create no Candidate or assignment |
| Unknown owner UUID is read | Return an empty current state |

### 5. Good / Base / Bad Cases

- **Good:** `Py` resolves through an alias to governed Python and appears in
  ordinary Skill filtering and recommendations.
- **Good:** visible `Rust` Candidate evidence remains on Job Detail until
  promotion resolves it.
- **Base:** a Company has no supported Source Industry mapping and remains
  unassigned without a fabricated classification.
- **Bad:** combine Source Classification labels into a project Job hierarchy.
- **Bad:** hide Candidate evidence merely because it is not governed yet.

### 6. Tests Required

- Current taxonomy tests cover Company/Skill transforms, constraints, reads,
  writes, Candidate aggregation, local dispositions, and four retained APIs.
- Product contracts cover Company Industry and Skill composition, visible
  Candidate evidence, embeddings, filters, CSV, and Related Jobs.
- Frontend tests keep Candidate evidence and Skill failure reasons visible.
- Architecture searches reject Job-taxonomy tables, APIs, schemas, filters,
  prompts, assignments, stats, and fixtures outside legacy cutover detection.

### 7. Wrong vs Correct

#### Wrong

```python
global_job_category = infer_from_source_label(path.label)
```

#### Correct

```python
source_paths = source_attribute_reader.get_paths(job.id)
skills = CurrentTaxonomyReader(db).get_job_skills(job.id)
```

Source classification remains Source-owned; only Company Industry and Skill
use project-owned current taxonomies.
