# Skill threshold history

## Finding

The remembered “count occurrences” mechanism exists, but it does not currently
auto-create governed Skills.

- `.trellis/spec/backend/skill-governance.md:142-180` specifies Candidate
  aggregation plus trusted-local human decisions.
- `backend/app/job_intelligence/skill_governance/service.py:542-565` recomputes
  Candidate `occurrence_count` and `distinct_job_count` without promotion.
- `backend/app/job_intelligence/skill_governance/decisions.py:166-185,338-369`
  creates a Skill only for an explicit decision with a valid existing Category
  and Technology placement.
- `backend/scripts/govern_skill_review_candidates.py:26-44,85-89` applies a
  minimum occurrence threshold only to a read-only candidate report.
- `backend/app/config.py:115-121` and
  `backend/app/services/taxonomy_visibility_service.py:15-68` use thresholds
  5/10/20 for filter visibility, not Skill creation.
- Archived task `.trellis/tasks/archive/2026-07/07-18-skill-governance/` confirms
  that the original design intentionally required human `create_skill`.

`trellis mem` found no earlier auto-create decision in readable project session
history. OpenCode 1.2+ SQLite history was unavailable to the installed reader, so
that platform could not be searched.

## New approved behavior

- Aggregate by normalized candidate identity.
- Count distinct Jobs, not raw occurrences.
- Threshold is a Settings value, default `5`.
- At threshold, automated processing rejects duplicates/aliases/generic terms,
  selects an existing Skill Category/Technology, and creates the Skill.
- If placement is uncertain, keep the candidate in the failed batch for retry.
- Never create `Other`, `Unknown`, or unclassified fallback Skills.
