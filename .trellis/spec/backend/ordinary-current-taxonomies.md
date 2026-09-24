# Ordinary Current Taxonomy Contracts

## Scenario: Read and write governed Skill state

### 1. Scope / Trigger

Use this contract when changing current Skill nodes, aliases, governed Job
Skills, Candidate/Mention evidence, product reads, or taxonomy HTTP APIs.
Company Industry has been removed from the current product and database schema.

### 2. Signatures

```python
CurrentTaxonomyStore(db).synchronize(snapshot) -> None
CurrentTaxonomyStore(db).replace_job_skills(command) -> None
CurrentTaxonomyReader(db).get_tree("skill")
CurrentTaxonomyReader(db).get_job_skills(job_id)
CurrentSkillEnrichment(db).replace_job_skills(...)
```

```text
GET /api/job-intelligence/skills/tree
GET /api/job-intelligence/jobs/{job_id}/skills
```

Persistence is owned by `current_taxonomy_nodes`,
`current_taxonomy_aliases`, `current_job_skill_assignments`,
`current_skill_candidates`, and `current_job_skill_mentions`.
`taxonomy` is restricted to `skill`.

### 3. Contracts

- Stable Skill node `code` values are identity; taxonomy has Category →
  Technology → Skill levels and aliases.
- Resolved governed Skills live in `current_job_skill_assignments` and power
  Job filtering, export, analytics, embeddings, and Related Jobs scoring.
- Unknown terms remain visible as Candidate/Mention evidence and are not
  silently promoted into ordinary Skill reads or filters.
- Exact names, aliases, and explicit generic/rejected rules are deterministic;
  new governed Skills require operator confirmation.
- Ordinary AI Skill evidence is a usable baseline. Current-evidence Jev
  correction may add, reject, or remap automated evidence, while operator
  decisions remain active across later AI/Jev projections. Changed Job evidence
  invalidates Jev applicability without deleting its historical Mentions.
- Taxonomy bootstrap is idempotent and never overwrites operator-owned nodes.
- Baseline manifest upgrades are additive on a non-empty sandbox: missing
  governed nodes and aliases are installed, while existing/operator-owned
  nodes remain unchanged. Startup then reruns deterministic reconciliation so
  historical exact-name and alias candidates do not remain in the review queue.
- LLM placement is advisory only and is reached after exact/alias and local
  curation rules. It cannot invent a Category or Technology parent or write a
  governed Skill without an explicit operator decision.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| `taxonomy` is not `skill` | Reject before write |
| Parent code is absent from Skill taxonomy | Reject snapshot |
| Assignment target is unknown, inactive, or not assignable | Roll back caller transaction |
| Unknown Skill repeats | Recompute Candidate/Mention evidence; keep it non-governed |
| Known generic/rejected term appears | Retain terminal Mention evidence; create no Candidate/assignment |
| Candidate decision succeeds | Resolve Mentions and rebuild affected Job projections atomically |

### 5. Good / Base / Bad Cases

- **Good:** `Py` resolves through an alias to governed Python and appears in
  ordinary Skill filtering and recommendations.
- **Good:** unresolved `Rust` remains visible as collapsed Job Detail evidence
  until an operator resolves it.
- **Base:** no reliable recommendation; operator searches or chooses a
  structured generic/reject reason.
- **Bad:** expose Candidate evidence as a canonical Skill filter or invent a
  parent Category/Technology.

### 6. Tests Required

- Current taxonomy tests cover Skill transforms, constraints, reads, writes,
  Candidate aggregation, local dispositions, and retained APIs.
- Candidate API tests cover threshold, recommendations/evidence bounds,
  decisions, invalid placement, and idempotency.
- Frontend tests cover governed Skill display, pending evidence, compact review,
  Settings, and taxonomy-unavailable states.

### 7. Wrong vs Correct

#### Wrong

```python
job.skills = candidate_mentions
```

#### Correct

```python
skills = CurrentTaxonomyReader(db).get_job_skills(job.id)
pending = skills.candidate_mentions
```
