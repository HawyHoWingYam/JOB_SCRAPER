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

resolve_skill_curation(raw_name) \
    -> SkillCurationDisposition(kind, generic_tag, rejection_reason) | None

load_company_industry_mapping_manifest(path) \
    -> CompanyIndustryMappingManifest
CompanyIndustryMappingSynchronizer(db).plan(manifest, observed_labels=...) \
    -> CompanyIndustryMappingSyncPlan
CompanyIndustryMappingSynchronizer(db).synchronize(manifest, observed_labels=...) \
    -> CompanyIndustryMappingSyncPlan
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
- Governed Skill curation rules are Unicode-safe and apply before Candidate
  upsert as well as before batch placement. A multilingual generic alias keeps
  its raw Mention evidence but stores one canonical Generic Skill Tag. A known
  local disposition never depends on runtime translation or a fresh LLM call.
- Company Industry Source Mapping uses one governed current-state manifest with
  no release, revision, history, or startup synchronization. Each Source
  section is complete, and every normalized label has exactly one `mapped` or
  `non_mapping` disposition.
- `python backend/scripts/sync_company_industry_source_mappings.py` validates
  all Sources and observed-label coverage before mutation. Positive rows are
  synchronized atomically per Source; non-mapping dispositions remain only in
  the manifest and never create fake taxonomy targets.
- Runtime Source Industry Label extraction prefers structured `industry.name`
  evidence and falls back to retained `company_industry` evidence only when the
  structured label is absent. Preview and projection share the same
  Unicode-normalized `label:<value>` identity.
- Product, filter, stats, search, AI Enrichment, OfferToday projection, ingest,
  and embedding workers read or write only the current tables.
- Sandbox retention exports only current rows. No API, worker, script, or
  preservation path may import a legacy publisher, active-state reader,
  decision adapter, or review queue.
- Retained audit rows are evidence only; application revision/release/version
  keys are recursively removed from their JSON summaries.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Node code, parent code, level, label, order, or assignability is invalid | Reject the snapshot before writes |
| Parent code is absent from the same taxonomy | Reject; never create an implicit parent |
| Job/Company/Skill assignment code is unknown, inactive, or not assignable | Reject and roll back the caller transaction |
| Source mapping is absent or has no active assignable target | Return the complete active assignable Job taxonomy |
| Job has no current assignment | Return `state=unassigned`, `assignment=null`; no Review reference |
| Unknown Skill term repeats | Upsert Candidate/Mention evidence and recompute metrics; do not auto-decide in this module |
| Known multilingual generic alias is extracted as technical | Resolve directly to its canonical Generic Skill Tag; create no Candidate or Skill assignment |
| Company mapping manifest is malformed, misses an observed label, or targets an unknown/inactive/non-assignable node | Reject before mutation |
| Company manifest and positive database mapping rows drift | Fail closed as actionable unsupported evidence; never infer a target |
| Company manifest disposition is `non_mapping` | Terminal exclusion; create no mapping row, Batch item, or Retry item |
| Preservation row references an unmapped legacy identity | `TaxonomyPreservationError`; import nothing |
| API receives an unknown Job or Company UUID | Return an empty current state for that owner; do not query legacy tables |

### 5. Good / Base / Bad Cases

- **Good:** a JobsDB path has a useful mapping, so AI sees only that mapped
  slice and stores one stable-code assignment.
- **Base:** a new CTgoodjobs or OfferToday classification has no mapping. AI
  receives all active assignable Job nodes and may still classify the Job.
- **Base:** an unenriched Job has no assignment and no Candidate Mentions. Reads
  return Unassigned plus empty arrays.
- **Good:** `項目管理` remains the raw Mention and resolves deterministically to
  canonical tag `Project Management` without creating a Candidate.
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
- Skill curation tests assert Unicode alias matching, canonical Generic Skill
  Tags, raw evidence retention, repeated-ingest determinism, and zero Candidate
  or assignment writes for governed generic aliases.
- Company mapping manifest tests assert normalized identity, disposition
  exclusivity, observed coverage, target validity, deterministic planning,
  stale-row removal, idempotence, and atomic rollback. Company adapter tests
  assert mapped provenance writes, actionable drift, and terminal exclusions.
- Frontend current taxonomy/API, Job Browser, Job Detail, Company Industry, and
  Dashboard tests assert stable-code payloads and absence of Governance UI.
- Architecture searches reject every legacy taxonomy publisher, reader,
  preservation bridge, and review-queue import.

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

#### Wrong: trust transient extractor kind over governed curation

```python
if kind == "technical":
    candidate = upsert_candidate(raw_name)
```

#### Correct

```python
local = resolve_skill_curation(raw_name)
if local and local.kind == "generic":
    persist_mention(raw_name=raw_name, generic_tag=local.generic_tag)
else:
    candidate = upsert_candidate(raw_name)
```

The extractor supplies evidence; explicit current curation data owns known
terminal dispositions.
