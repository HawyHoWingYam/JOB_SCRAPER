# Taxonomy Governance Design

> Date: 2026-05-01
> Scope: job taxonomy canonicalization, skill governance split, historical backfill, verification, and index cleanup

## Goal

Make `subcategory_id -> category -> domain` the only business-truth job taxonomy, split controlled skills from raw extracted phrases, and add a repeatable governance rollout that can clean current data without breaking the existing app in one cut.

## Current State

The current database is structurally healthy but semantically mixed:

- `jobs`: 2931 rows
- `job_skills`: 26164 rows
- `skills`: 5593 rows
- `jobs` with `subcategory_id`: 2856
- `jobs` with `ai_category`: 2559
- `jobs` with null `subcategory_id`: 75
- `skills` with `is_auto_created = true`: 5567
- `skills` under `Other / General`: 5511
- `skills` with `distinct_job_count = 1`: 3263
- `skills.usage_count` mismatches against `job_skills`: 14 rows

Observed behavior from MCP inspection:

- Job taxonomy statistics are internally consistent. `job_domains`, `job_categories`, and `job_subcategories` all match actual job linkage counts.
- The main problem in job taxonomy is not corruption. It is dual business semantics: source classification fields, `ai_category`, and normalized taxonomy all coexist.
- The main problem in skills is governance. The controlled vocabulary is polluted by raw extracted phrases and high-volume `Other / General` auto-created entries.
- The database also contains redundant indexes already covered by unique or composite indexes.

## Decision Summary

This rollout will follow a compatibility-first design:

1. Keep `jobs.ai_category` as a legacy audit string, not the canonical business classification.
2. Keep source classification fields as source metadata only.
3. Treat `jobs.subcategory_id` as the only business-truth job classification anchor.
4. Keep `skills` and `job_skills` as the controlled, user-facing skill vocabulary.
5. Introduce a separate raw mention layer for extracted phrases so noisy model output no longer has to become a controlled skill.
6. Migrate API behavior in phases rather than hard-cutting everything off `ai_category` in one release.

## In Scope

- Tighten job taxonomy resolution and fallback behavior
- Backfill the 75 unmapped jobs
- Introduce a raw extracted skill mention model
- Route new enrichment output through controlled-vocabulary governance
- Clean historical polluted `Other / General` skills
- Rebuild taxonomy metrics from source-of-truth link tables
- Add verification for coverage and drift
- Remove redundant indexes that are provably covered

## Out of Scope

- Full redesign of the frontend filter UI
- Deleting `ai_category` in this rollout
- Rebuilding all historical enrichment output from scratch
- Large taxonomy content redesign beyond the minimum curation needed for current data

## Design

### 1. Canonical Job Taxonomy

`jobs.subcategory_id` becomes the only business classification field used for business logic, filtering, and statistics.

Field roles after the rollout:

- `source_classification_id`, `source_classification_name`, `source_subclassification_id`, `source_subclassification_name`
  - Purpose: preserve source metadata from JobsDB or CTGoodJobs
  - Not used as the final business category
- `subcategory_id`
  - Purpose: canonical business taxonomy anchor
  - Must always resolve to one path in `job_subcategories -> job_categories -> job_domains`
- `ai_category`
  - Purpose: legacy human-readable audit string and backward-compatibility payload
  - Derived from canonical taxonomy when present
  - Not treated as the source of truth

`JobCategoryNormalizer` will be tightened:

- Allowed outcomes:
  - match an existing taxonomy path allowed by `JobTaxonomyRegistry`
  - fall back to the registry default path for the source slice
- Disallowed default behavior:
  - freely creating new domain/category/subcategory nodes from AI output
- New node creation should be limited to explicit governance paths only, not the default online enrichment path

The backfill job for unmapped jobs will:

- use source classification data first
- use source subclassification hints when present
- fall back to the slice default path if no valid leaf match is safe
- never invent a new taxonomy node during routine backfill

### 2. Controlled Skills vs Raw Mentions

The current schema conflates two different concepts:

- a controlled skill used for search, filters, and reporting
- a raw phrase extracted from a job description

These must be separated.

Controlled layer:

- `skill_categories`
- `skill_technologies`
- `skills`
- `job_skills`

This layer is for reusable canonical skills only. It powers search, filters, and reporting.

Raw mention layer:

- add `job_skill_mentions`

Recommended columns:

- `id`
- `job_id`
- `raw_name`
- `normalized_name`
- `resolution`
- `skill_id` nullable
- `generic_tag` nullable
- `review_candidate_id` nullable
- `source`
- `confidence`
- `created_at`

Behavior for future enrichment:

- `match_existing`
  - insert into `job_skill_mentions`
  - link canonical skill in `job_skills`
- `generic_tag`
  - insert into `job_skill_mentions`
  - append tag into `jobs.ai_generic_tags`
- `review_candidate`
  - insert into `job_skill_mentions`
  - upsert into `skill_review_candidates`
- `reject`
  - insert into `job_skill_mentions`
  - do not create canonical skill links

This preserves auditability without polluting the user-facing skill vocabulary.

### 3. Historical Skill Cleanup

Historical cleanup keeps using `backend/scripts/govern_skill_history.py`, but its purpose becomes narrower and clearer:

- remove polluted high-volume `Other / General` skills from the controlled layer
- merge them into curated canonical skills when a clear target exists
- convert generic capability terms into `ai_generic_tags`
- move unresolved technical phrases into `skill_review_candidates`

The first cleanup wave should target the current high-frequency polluted set surfaced by MCP and the existing curation files.

Expected treatment classes:

- merge
  - examples: `Python`, `Java`, `JavaScript`, `Node.js`, `CI/CD`
- generic
  - examples: `Project Management`, `Vendor Management`, `Troubleshooting`
- review
  - examples: `Linux`, `AWS`, `Azure`, `Windows`, `API`

The rollout should also add a second governance rule for low-frequency phrase pollution:

- long one-off phrases should not survive as canonical `skills`
- they should become raw mentions plus review candidates or generic tags depending on classification

### 4. API Compatibility Strategy

The API rollout should be phased instead of hard-switched.

Phase 1:

- keep current response payloads compatible
- continue returning `ai_category` where clients expect it
- derive `ai_category` from canonical taxonomy whenever `subcategory_id` exists

Phase 2:

- move filters and stats to canonical taxonomy fields first
- mark `ai_category` filters as legacy-compatible behavior
- prefer `subcategory_ids`, `job_category_ids`, and `domain_ids` in backend logic

Affected backend surfaces:

- `backend/app/api/jobs.py`
- `backend/app/api/stats.py`
- any category list or filter endpoints that still read `Job.ai_category`

Phase 3:

- once the client no longer depends on `ai_category`, remove business use of it from query logic

### 5. Metrics Rebuild and Verification

Governance metrics must be rebuilt from facts, not incrementally trusted.

Skill metrics:

- rebuild `usage_count`
- rebuild `distinct_job_count`
- rebuild `last_used_at`
- recompute `is_filter_visible`

Job taxonomy metrics should gain the same deterministic rebuild behavior:

- `job_subcategories`
- `job_categories`
- `job_domains`

Verification must cover:

- unmapped jobs count
- canonical taxonomy coverage
- polluted `Other / General` counts
- canonical skill count consistency
- visible nodes with zero `distinct_job_count`
- `job_skills` link integrity across the skill hierarchy

`backend/scripts/verify_migration.py` should be updated so the main post-rollout questions are:

- how many jobs still lack `subcategory_id`
- how many polluted `Other / General` canonical skills remain
- how many visible taxonomy nodes have invalid counters
- whether canonical and raw skill layers are internally consistent

### 6. Index Cleanup

Redundant indexes identified by MCP should be removed in a dedicated migration after verification passes.

Initial candidates:

- `idx_companies_company_id`
- `idx_job_categories_domain_id`
- `idx_job_skills_job_id`
- `idx_job_subcategories_category_id`
- `idx_jobs_job_id`
- `idx_skills_name`
- `idx_skills_technology_id`

Migration requirements:

- use safe Postgres index operations
- only remove indexes proven to be covered by unique or composite indexes
- keep this migration separate from behavior changes so failures are isolated

## File Impact

Primary application files:

- `backend/app/services/job_category_normalizer.py`
- `backend/app/services/job_taxonomy_registry.py`
- `backend/app/services/skill_normalizer.py`
- `backend/app/services/ai_enrichment_service.py`
- `backend/app/api/jobs.py`
- `backend/app/api/stats.py`
- `backend/app/api/skills.py`

Primary data and governance files:

- `backend/app/data/job_source_taxonomy_mapping.json`
- `backend/app/data/skill_curation_rules.json`
- `backend/app/data/skill_backfill_curations.json`
- `backend/scripts/govern_skill_history.py`
- `backend/scripts/verify_migration.py`

Schema and model files:

- new Alembic migration for `job_skill_mentions`
- new SQLAlchemy model for `job_skill_mentions`
- one dedicated Alembic migration for redundant index cleanup

Tests:

- `backend/tests/test_skill_governance.py`
- `backend/tests/test_skill_history_governance.py`
- new tests for canonical taxonomy backfill behavior
- new tests for API compatibility over canonical taxonomy

## Rollout Order

1. Add failing tests for canonical job taxonomy behavior and raw-vs-controlled skill routing.
2. Add schema support for raw skill mentions.
3. Tighten online normalization behavior so enrichment no longer creates polluted canonical skills by default.
4. Backfill the 75 unmapped jobs into canonical taxonomy.
5. Run historical skill governance cleanup with curated merge/generic/review actions.
6. Rebuild skill and job taxonomy metrics from fact tables.
7. Update verification reporting and run it against the local database.
8. Remove redundant indexes in a dedicated migration.
9. Move API query behavior to canonical taxonomy while keeping compatibility fields in responses.

## Testing Strategy

- Unit tests for `JobCategoryNormalizer` fallback and anti-creation rules
- Unit tests for `SkillNormalizer` routing decisions
- Script-level tests for governance cleanup and metrics rebuild
- Integration tests for jobs filtering using canonical taxonomy IDs
- Migration verification snapshot tests for new counters and mention-layer coverage
- Local database verification after backfill and cleanup

## Risks and Mitigations

Risk: legacy clients still filter on `ai_category`

- Mitigation: keep `ai_category` in responses during compatibility phase and derive it from canonical taxonomy

Risk: tightening normalization leaves some jobs unmapped

- Mitigation: deterministic fallback to the source slice default path and explicit verification for residual null `subcategory_id`

Risk: aggressive skill cleanup removes useful search terms

- Mitigation: separate raw mention storage from controlled vocabulary so information is preserved even when not promoted to canonical skill

Risk: index cleanup removes a path the app still uses

- Mitigation: only drop indexes already proven redundant by catalog inspection and keep cleanup in a standalone migration

## Success Criteria

- `jobs.subcategory_id IS NULL` is reduced from 75 to 0, or any remainder is explicitly justified
- canonical job taxonomy is the only backend business truth
- new enrichment no longer creates uncontrolled `Other / General` canonical skills by default
- controlled skills no longer absorb raw one-off phrases
- `skills.usage_count` and `skills.distinct_job_count` match `job_skills`
- verification reports no visible taxonomy nodes with zero `distinct_job_count`
- redundant covered indexes are removed without regressing tests or verification
