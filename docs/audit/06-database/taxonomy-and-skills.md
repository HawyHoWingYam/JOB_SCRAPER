# Taxonomy and Skills

## Current Responsibilities

This scope stores governed job taxonomy, governed skill taxonomy, job-to-skill links, and unresolved skill candidates. It supports search filters, AI enrichment output, governance scripts, and public display of canonical versus provisional skills.

## Current Implementation Map

- Job taxonomy models: `backend/app/models/job_domain.py`, `job_category.py`, `job_subcategory.py`
- Skill taxonomy models: `backend/app/models/skill_category.py`, `skill_technology.py`, `skill.py`
- Link/mention models: `backend/app/models/job_skill.py`, `job_skill_mention.py`, `skill_review_candidate.py`
- Services: `backend/app/services/job_category_normalizer.py`, `skill_normalizer.py`, `taxonomy_visibility_service.py`
- Scripts: `backend/scripts/seed_taxonomy.py`, `govern_job_taxonomy.py`, `govern_skill_history.py`, `govern_skill_review_candidates.py`, `verify_migration.py`
- Tests: `backend/tests/test_job_taxonomy_governance.py`, `test_skill_governance.py`, `test_skill_history_governance.py`, `test_seed_taxonomy.py`, `test_api_taxonomy_compat.py`

## Tables and Column Use

| Table | Key columns | Column purpose |
| --- | --- | --- |
| `job_domains` | `id`, `name`, `description` | Level 1 job taxonomy nodes |
| `job_categories` | `id`, `domain_id`, `name`, `description` | Level 2 job taxonomy nodes under domains |
| `job_subcategories` | `id`, `category_id`, `name`, `description` | Level 3 job taxonomy leaves referenced by `jobs.subcategory_id` |
| `job_* taxonomy tables` | `created_by`, `is_auto_created`, `is_filter_visible` | Governance provenance and filter exposure decisions |
| `job_* taxonomy tables` | `usage_count`, `distinct_job_count`, `last_used_at` | Metrics used to promote or prune taxonomy nodes |
| `skill_categories` | `id`, `name`, `description` | Level 1 skill taxonomy nodes |
| `skill_technologies` | `id`, `category_id`, `name`, `description` | Level 2 skill taxonomy nodes |
| `skills` | `id`, `technology_id`, `name`, `aliases`, `popularity` | Level 3 canonical skills linked to jobs |
| `skills` | `created_by`, `is_auto_created`, `is_filter_visible`, `usage_count`, `distinct_job_count`, `last_used_at` | Skill governance provenance, visibility, and metrics |
| `job_skills` | `job_id`, `skill_id`, `source`, `confidence` | Canonical many-to-many job-skill links |
| `job_skill_mentions` | `job_id`, `raw_name`, `normalized_name`, `resolution` | Raw extracted terms and their resolution state |
| `job_skill_mentions` | `skill_id`, `review_candidate_id`, `generic_tag`, `source`, `confidence` | Link to canonical skill, review candidate, or generic bucket |
| `skill_review_candidates` | `raw_name`, `normalized_name`, `status`, `occurrence_count` | Queue of unresolved terms needing governance |
| `skill_review_candidates` | `suggested_category`, `suggested_technology`, `first_seen_job_id`, `last_seen_job_id` | Review hints and traceability |

## Data and Control Flow

1. Seed scripts load canonical taxonomy JSON into hierarchy tables.
2. AI enrichment proposes job taxonomy and skill terms.
3. Job taxonomy normalizer resolves valid taxonomy leaf IDs and writes `jobs.subcategory_id`.
4. Skill normalizer maps extracted terms into `job_skills`, `job_skill_mentions`, or `skill_review_candidates`.
5. Governance scripts merge candidates, mark generic terms, create approved taxonomy nodes, and rebuild usage metrics.
6. Search/detail APIs expose only governed visible skill instances for primary display while unresolved mentions remain provisional.

## Constraints and Indexes

- Job taxonomy uniqueness is hierarchical: `job_domains.name`, `job_categories(domain_id, name)`, `job_subcategories(category_id, name)`.
- Skill taxonomy uniqueness is hierarchical: `skill_categories.name`, `skill_technologies(category_id, name)`, `skills(technology_id, name)`.
- `job_skills` has composite primary key `(job_id, skill_id)`.
- `job_skill_mentions` indexes `job_id`, `normalized_name`, `resolution`, `skill_id`, and `review_candidate_id`.
- `skill_review_candidates.normalized_name` is unique.

## Current Database Snapshot

The connected local DB currently has 0 rows in all taxonomy/skills tables and 0 rows in `job_skills`, `job_skill_mentions`, and `skill_review_candidates`. That may be a local setup issue if the UI is expected to show governed filters.

## Tests and Coverage

- Governance tests cover taxonomy resolution, metric rebuilds, visibility thresholds, pruning, and skill review flows.
- API tests validate canonical taxonomy serialization and hiding legacy AI category fields.
- Seed tests cover dry-run and execute behavior for taxonomy data.

## Known Gaps or Risks

- Empty taxonomy tables in the connected DB mean enrichment/search behavior may fall back or show incomplete filters.
- Taxonomy state is managed by a mix of seed files, scripts, AI decisions, and governance thresholds.
- Metric counters are denormalized and require rebuild discipline after bulk changes.
- `job_skills` is canonical, while `job_skill_mentions` preserves raw extraction; consumers must choose the right table intentionally.

## Optimization Backlog

- Make taxonomy seed execution part of bootstrap or expose a clear operator setup check when required tables are empty.
- Add an operator governance UI for skill review candidates, taxonomy promotions, generic-term decisions, and visibility changes.
- Add actor, reviewed_at, decision_reason, and source_run fields to review/governance records so decisions are auditable.
- Version governance thresholds and metric rebuild jobs so visibility policy changes can be explained later.
- Add monitoring for stale denormalized metrics and a safe rebuild command with dry-run, execute, and JSON output.

## Follow-up Audit Questions

- Should taxonomy seed be mandatory during bootstrap?
- Which tables should be editable by operators versus only scripts?
- Do visibility thresholds belong in runtime settings, static config, or database policy tables?
- Should unresolved skill candidates have a stricter review lifecycle with actor/audit columns?
