# Flatten Job Company and Skill taxonomies

Parent: `07-26-excluded-jobs-governance-handoff`

## Goal

Replace release-pinned Canonical Job, Company Industry, Skill, and optional
Source mapping data with ordinary stable current identities while preserving
accepted business assignments and evidence.

## Requirements

- Flatten the current active Job/Company/Skill hierarchies and aliases to stable
  IDs and direct hierarchy FKs.
- Flatten useful Source mappings to optional current mappings; remove coverage
  releases/active pointers and make missing mapping non-blocking.
- Remap accepted assignments/projections/audits/evidence without revision or
  lock-version fields.
- Preserve unresolved Skill Candidate/Mention evidence needed by later automatic
  threshold processing.
- Delete release/publisher/materializer/activation/read contracts and per-item
  review/recommendation queues.
- Provide no Job Taxonomy or Company Industry CRUD UI.

## Acceptance Criteria

- [x] Current Job 25/63/198 structure, Company HSIC structure, Skill hierarchy,
      codes, labels, aliases, and stable identities match the source fixture.
- [x] Accepted Job/Company/Skill projections and audit/evidence remap exactly.
- [x] Useful Source mappings constrain when present and return full-taxonomy
      fallback when absent.
- [x] No release, active-pointer, coverage, revision-pinned FK, publisher, or
      per-item review queue remains in runtime consumers for these domains.
      Legacy source rows remain isolated behind the one-time preservation /
      cutover bridge and are deleted by the parent task's final cutover child.

## Dependency

Runs after ordinary Source classification identities exist. Produces the target
ordinary taxonomy schema consumed by automated batches and cutover.
