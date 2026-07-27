# Ordinary Current Taxonomy Contracts

## Scenario: Read and write Job, Company Industry, and Skill taxonomy state

### 1. Scope / Trigger

Use this contract when changing current taxonomy tables, seed transforms,
optional Source mappings, Job or Company assignments, Skill projections and
Candidate evidence, AI Enrichment classification, taxonomy filters and stats,
embedding documents, or the current taxonomy HTTP API.

These domains have one ordinary current state. They do not publish, activate,
pin, compare, or roll back releases or revisions. JobsDB, OfferToday, and
CTgoodjobs use the same Source-qualified mapping and assignment behavior.

### 2. Signatures

The storage and read seams are:

```python
CurrentTaxonomyStore(db).synchronize(snapshot) -> None
CurrentTaxonomyStore(db).resolve_allowed_codes(
    taxonomy, *, source_site, source_key
) -> tuple[str, ...]
CurrentTaxonomyStore(db).assign_job(command) -> None
CurrentTaxonomyStore(db).replace_company_industries(command) -> None
CurrentTaxonomyStore(db).replace_job_skills(command) -> None

CurrentTaxonomyReader(db).get_tree(taxonomy) -> CurrentTaxonomyTreeView
CurrentTaxonomyReader(db).get_job_taxonomy_state(job_id) -> CurrentJobTaxonomyStateView
CurrentTaxonomyReader(db).get_company_industry_state(company_id) -> CurrentCompanyIndustryStateView
CurrentTaxonomyReader(db).get_job_skills(job_id) -> CurrentJobSkillStateView
CurrentTaxonomyReader(db).resolve_assignable_codes(taxonomy, codes) -> tuple[str, ...]
CurrentTaxonomyReader(db).build_job_taxonomy_embedding_document(job_id) \
    -> CurrentJobTaxonomyEmbeddingDocument | None
```

Current HTTP reads are:

```text
GET /api/job-intelligence/job-taxonomy/tree
GET /api/job-intelligence/jobs/{job_id}/job-taxonomy
GET /api/job-intelligence/company-industries/tree
GET /api/job-intelligence/companies/{company_id}/industries
GET /api/job-intelligence/skills/tree
GET /api/job-intelligence/jobs/{job_id}/skills
```

Persistence is owned by `current_taxonomy_nodes`,
`current_taxonomy_aliases`, `current_job_taxonomy_assignments`,
`current_company_industry_assignments`, `current_job_skill_assignments`,
`current_skill_candidates`, `current_job_skill_mentions`, and
`current_source_taxonomy_mappings`.

### 3. Contracts

- Stable `code` values are taxonomy identity. Nodes use `parent_code` directly;
  no row or API payload carries a release, revision, active pointer, or lock
  version.
- The Job seed preserves the 25 Domain / 63 Category / 198 assignable
  Subcategory structure. Company Industry preserves the current HSIC hierarchy;
  Skills preserve current Category / Technology / Skill nodes and aliases.
- `synchronize` and preservation replay flush but do not commit. Callers own one
  transaction. Runtime Job writes are last-write-wins; Company and Skill writes
  replace the complete current set for their owner.
- A present Source-to-Job mapping constrains assignable codes. When no usable
  mapping exists, `resolve_allowed_codes` returns the complete active assignable
  Job taxonomy. Missing mapping never excludes a Job or creates a review item.
- Job and Company assignments reference stable taxonomy codes and retain
  method, evidence hash, evidence/provenance payloads, breadcrumb, and capture
  time without taxonomy or mapping versions.
- Resolved Skills live in `current_job_skill_assignments`. Unknown normalized
  terms live as `current_skill_candidates` plus
  `current_job_skill_mentions`; distinct-Job and occurrence counts are derived
  from Mention evidence. Candidate evidence is not a manual review queue.
- Product, filter, stats, search, AI Enrichment, OfferToday projection, ingest,
  and embedding workers read or write only the current tables.
- The preservation loader is a temporary, read-only bridge for the one-time
  sandbox cutover. It may read legacy active rows to produce revision-free
  retained records, but no API or runtime consumer may import a legacy publisher,
  reader, decision adapter, or review queue. The final cutover deletes the bridge
  and legacy tables after import verification.
- Governance audit rows may be retained as evidence, but known legacy node IDs
  are rewritten to stable codes and revision/lock-version keys are removed from
  preserved summaries.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Node code, parent code, level, label, order, or assignability is invalid | Reject the snapshot before writes |
| Parent code is absent from the same taxonomy | Reject; never create an implicit parent |
| Job/Company/Skill assignment code is unknown, inactive, or not assignable | Reject and roll back the caller transaction |
| Source mapping is absent or has no active assignable target | Return the complete active assignable Job taxonomy |
| Job has no current assignment | Return `state=unassigned`, `assignment=null`; no Review reference |
| Unknown Skill term repeats | Upsert Candidate/Mention evidence and recompute metrics; do not auto-decide in this module |
| Preservation row references an unmapped legacy identity | `TaxonomyPreservationError`; import nothing |
| API receives an unknown Job or Company UUID | Return an empty current state for that owner; do not query legacy tables |

### 5. Good / Base / Bad Cases

- **Good:** a JobsDB path has a useful mapping, so AI sees only that mapped
  slice and stores one stable-code assignment.
- **Base:** a new CTgoodjobs or OfferToday classification has no mapping. AI
  receives all active assignable Job nodes and may still classify the Job.
- **Base:** an unenriched Job has no assignment and no Candidate Mentions. Reads
  return Unassigned plus empty arrays.
- **Bad:** require a mapping release before enrichment, expose a revision route,
  or create a per-item Review row for missing coverage.
- **Bad:** infer a Canonical Job node from a Source classification label or
  create a fallback taxonomy node.

### 6. Tests Required

- `test_current_taxonomies.py` asserts stable fixture transforms, exact Job
  counts, no version fields, optional mapping fallback, last-write-wins writes,
  preserved assignment/evidence remaps, current API serialization, and current
  embedding documents.
- `test_job_intelligence_response_contracts.py` runs against a disposable
  PostgreSQL database ending in `_test` with only current taxonomy tables. It
  covers Job Detail, Company reads, filters, stats, recommendations, and CSV.
- AI Enrichment and ingest tests assert current assignments, current Skill
  Candidate evidence, optional mapping behavior, and outer transaction
  ownership.
- Frontend current taxonomy/API, Job Browser, Job Detail, Company Industry, and
  Dashboard tests assert stable-code payloads and absence of Governance UI.
- Architecture searches allow legacy taxonomy imports only in the explicit
  preservation/cutover bridge until the final cutover task deletes it.

### 7. Wrong vs Correct

#### Wrong

```python
revision = CanonicalTaxonomyReader(db).get_active_revision()
if not mapping_release_covers(path):
    create_review_item(job.id, reason="source_mapping_missing")
```

#### Correct

```python
allowed_codes = CurrentTaxonomyStore(db).resolve_allowed_codes(
    "job",
    source_site=job.source_site,
    source_key=source_classification_id,
)
CurrentTaxonomyStore(db).assign_job(command)
```

The ordinary store treats mapping absence as full-taxonomy fallback and writes
stable current state in the caller's transaction.
