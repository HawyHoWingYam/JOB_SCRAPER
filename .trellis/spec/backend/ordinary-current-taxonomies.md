# Ordinary Current Skill Taxonomy Contracts

## 1. Scope / Trigger

Use this contract when changing current Skill nodes, aliases, governed Job
Skills, internal unresolved evidence, taxonomy reads, or unified enrichment.

## 2. Signatures

```python
CurrentTaxonomyStore(db).synchronize(snapshot) -> None
CurrentTaxonomyStore(db).replace_job_skills(command) -> None
CurrentTaxonomyReader(db).get_tree("skill")
CurrentTaxonomyReader(db).get_job_skills(job_id)
CurrentSkillEnrichment(db).build_skill_prompt(role_mode=...)
CurrentSkillEnrichment(db).replace_job_skills(...)
```

Persistence is owned by `current_taxonomy_nodes`,
`current_taxonomy_aliases`, `current_job_skill_assignments`,
`current_skill_candidates`, and `current_job_skill_mentions`. The latter two
are internal evidence storage, not a product queue.

## 3. Contracts

- Stable Skill `code` values are identity. Only active assignable Skill nodes
  may appear in Job assignments.
- Unified AI Enrichment receives the active codes and must use one of
  `match_existing`, `unresolved`, `generic`, or `rejected` for every emitted
  term.
- Unknown terms become internal Unresolved Skill Evidence. They never become
  searchable, appear in product payloads, create a governed node, or open an
  operator review workflow.
- Generic and rejected evidence creates no governed assignment.
- Operator-authored active mentions and assignments remain authoritative and
  survive later AI replacement.
- Taxonomy bootstrap is idempotent and does not overwrite operator-owned
  nodes. New governed Skills require a separate future curation mechanism.

## 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Taxonomy is not `skill` | Reject before write |
| Parent code is absent | Reject snapshot |
| Matched code is unknown, inactive, or non-assignable | Roll back caller transaction |
| Unknown evidenced term | Store internal unresolved evidence only |
| Generic/rejected term | Retain internal terminal mention; no assignment |
| Existing operator decision conflicts with AI | Preserve operator decision |

## 5. Good / Base / Bad Cases

- Good: `backend.python` is supplied to the model and safely assigned.
- Base: an unfamiliar framework remains internal unresolved evidence.
- Bad: expose unresolved evidence as a Job Detail panel or search filter.
- Bad: create a taxonomy node from model output.

## 6. Tests Required

- Cover constraints, stable-code reads/writes, internal evidence aggregation,
  each disposition, unknown-code rejection, and operator protection.
- Public Job Detail, dashboard, Settings, and navigation tests must prove there
  is no unresolved-evidence queue or action.

## 7. Wrong vs Correct

### Wrong

```python
taxonomy.create_skill(model_term)
job.skills.append(model_term)
```

### Correct

```python
if disposition == "unresolved":
    store_internal_evidence(model_term)
```

Only governed assignments are returned by ordinary Skill reads.
