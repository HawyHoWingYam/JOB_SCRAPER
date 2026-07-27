# Automate classification batch processing

Parent: `07-26-excluded-jobs-governance-handoff`

## Goal

Replace Job Intelligence Governance queues with automated Job Taxonomy, Company
Industry, and Skill batches plus configurable repeated-Skill creation.

## Requirements

- Reuse one shared bounded batch runtime with domain selection/processing
  adapters and AI Enrichment-style preview/progress/stop/retry UI.
- Delete legacy Governance navigation and routine per-item review flows.
- Keep optional direct correction from individual Job/Company records.
- Aggregate unknown Skills by distinct Jobs; expose threshold in Settings with
  default five.
- At threshold, reject duplicates/aliases/generic terms, choose an existing
  Category/Technology, and auto-create. Uncertain placement stays failed.

## Acceptance Criteria

- [ ] All three domains support bounded preview/start/progress/stop/retry/failure.
- [ ] No Governance queue/navigation/API remains.
- [ ] Settings threshold defaults to five and affects subsequent evaluation.
- [ ] Skill tests cover threshold, duplicate reuse, generic rejection, automatic
      placement/create, and unresolved failure without fallback taxonomy nodes.
- [ ] Frontend interaction/accessibility tests and production build pass.

## Dependency

Runs after ordinary taxonomy data and unversioned protocols exist.
