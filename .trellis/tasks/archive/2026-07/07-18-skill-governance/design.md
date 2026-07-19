# Skill governance design

## Module Interfaces

```text
SkillGovernance.extract(job_id, extracted_terms, context) -> MentionProjection
SkillGovernance.get_job_state(job_id) -> JobSkillView
SkillGovernance.list_candidates(query) -> Page[SkillCandidateView]
SkillGovernance.recommend(candidate_id) -> Recommendations
SkillGovernance.decide(DecisionCommand) -> DecisionResult
SkillGovernance.rebuild(job_ids, dry_run=true) -> RebuildReport
```

`extract` is worker-safe and applies only reviewed deterministic rules. `recommend` is read/advisory. `decide` is the isolated local-operator Interface.

## Governed seed and validation

- Publish revision-bound Skill Category → Technology → Skill nodes with stable codes, aliases, source metadata, and active/retired state.
- Reconcile `skill_taxonomy.json`, `skill_curation_rules.json`, and `skill_backfill_curations.json` before publication.
- Validation detects orphan paths/targets, duplicate/case/Unicode alias collisions, aliases targeting absent Skills, generic/review/suppression overlap, cycles, polluted `Other/General` auto nodes, and non-deterministic normalized keys.
- Wi-Fi/Vue 3/PCI DSS and Oracle/Jira/Confluence inconsistencies must be deliberately resolved, not silently created by the importer.

## Persistence and states

- Revision-bound Skill Category/Technology/Skill tables with stable codes; referenced nodes retire instead of cascade deletion.
- `job_skill_mentions`: Job, raw/normalized term, constrained resolution (`match_existing`, `review_candidate`, `generic_tag`, `rejected`), optional Skill/Candidate FK with resolution-dependent check constraints, generic tag, source/confidence/provenance, version/timestamps.
- `skill_candidates`: unique normalized candidate key within active revision, constrained status (`pending`, `resolved_merged`, `resolved_created`, `resolved_generic`, `rejected`, `superseded`), occurrence metrics, evidence summary, version, decision/audit reference.
- `job_skills`: governed projection unique Job/Skill with source/confidence/provenance; generated only from valid match-existing mentions.

Candidate occurrence counts are recomputable metrics, not the identity/source of truth.

## Extraction and normalization

1. Normalize Unicode/spacing and preserve raw term.
2. Apply exact governed Skill/alias match deterministically.
3. Apply reviewed generic/suppression rules.
4. Technical unresolved term creates or links one Candidate and one Job-level Unreviewed Skill Mention.
5. Nontechnical generic term creates a generic mention; rejected evidence remains auditable but not product-visible.

Fuzzy/semantic logic only returns recommendations. Tie-breaking is stable by score, governed Skill code/name, and ID; database load order never decides.

## Operator decisions and transitions

Actions:

- `merge_existing(skill_id)`
- `create_skill(category_id, technology_id, stable_code, name, aliases)`
- `classify_generic(generic_tag)`
- `reject(reason)`

One decision transaction locks the Candidate, validates target/revision/version/idempotency, updates all active linked mentions, creates/removes Job-Skill projections, recomputes Candidate/taxonomy metrics, appends audit/outbox, and sets final status. Partial mention updates are forbidden.

Creating a Skill is allowed only through this human decision and must pass the same seed/reference/alias collision rules. AI never executes it.

## Read/API contracts

- Ordinary Job view: governed `skills[]` only.
- Detail/evidence view: `unreviewed_skill_mentions[]` separately, with Candidate/deep-link reference but no governed styling.
- Candidate queue: normalized/raw variants, affected Job count, recency, Source/taxonomy context, recommendations, status/version, audit.
- Stats/search/recommendation endpoints join `job_skills`/governed active Skills only.

## Embedding integration

Embedding document includes governed Skills and accepted Canonical Job Taxonomy; it excludes Candidate/generic/rejected evidence. Decision changes emit invalidation for every affected Job, de-duplicated through outbox consumers.

## Rebuild and tests

- Dry-run re-extracts from preserved descriptions/AI extraction evidence against a pinned Skill revision/rule hash.
- Report governed matches, candidates, generic/rejected, collisions, affected Jobs, and difference from legacy mentions.
- PostgreSQL tests cover constraints, concurrent Candidate registration, every decision action, atomic fan-out, idempotency, retirement, and serialization.
