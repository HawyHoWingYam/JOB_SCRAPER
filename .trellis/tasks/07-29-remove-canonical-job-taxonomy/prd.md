# Remove canonical job taxonomy

## Goal

Remove the project-owned Canonical Job Taxonomy as a product and persistence
capability. Jobs retain the classification paths captured from their source sites,
without treating unlike source classifications as one cross-source hierarchy.

Preserve the existing Skill governance lifecycle: unresolved AI-extracted terms remain
visible as Skill Candidate Evidence and may be promoted by automatic processing into
Governed Skills.

## Background

- Canonical Job Taxonomy currently appears in Job detail, Job Browser results and
  structured filters, Dashboard/category reporting, automated classification batches,
  AI enrichment, exports, embedding documents, and Related Jobs scoring.
- Job Taxonomy shares current-taxonomy infrastructure with Company Industry and Skills.
  Removal must be limited to the Job-specific domain.
- Source Classification Paths have an independent source-evidence model and remain
  valid after Canonical Job Taxonomy is removed.
- Existing Job embeddings include Canonical Job Taxonomy text and cannot be retained
  without preserving an indirect influence on recommendations.
- The project deploys schema changes through an unversioned sandbox cutover, not
  in-place migrations: stop services, export retained state, clear the sandbox, deploy
  one complete code set, bootstrap, import, verify, then restart. The cutover artifact
  is transient and there is no rollback after finalization.

## Requirements

### R1 — Remove the Job taxonomy product surface

- Remove Canonical Job Taxonomy from Job detail, Job Browser cards, route/query state,
  structured filters and facets, API response contracts, CSV export, and runtime
  capability/availability payloads.
- Remove cross-source Canonical Job Taxonomy Dashboard/category charts, summaries, and
  navigation links. Do not relabel them with mixed Source Classification data.

### R2 — Retain source-native classification

- Continue capturing and displaying Source Classification Paths supplied by job sites.
- Source classifications may be used only in their relevant source context; they must
  not be presented as a globally comparable hierarchy or cross-source statistic.

### R3 — Remove Job taxonomy processing and persistence

- Remove Job Taxonomy seeds, transforms, reads, assignments, Source-to-Canonical Job
  mappings, AI classification, automated classification domain support, taxonomy
  readiness logic, events, and background-worker dependencies.
- Remove Job-specific taxonomy ORM metadata and omit Job taxonomy rows/tables from the
  retained sandbox artifact and bootstrapped target schema.
- Preserve shared current-taxonomy infrastructure required by Company Industry and
  Skills.

### R4 — Preserve Skill governance

- Keep Governed Skills and Skill Candidate Evidence visible.
- Preserve Candidate/Mention aggregation and automatic processing into a governed
  Skill, Generic Skill Tag, or rejection.
- Do not treat Skill Candidate Evidence as a governed search or recommendation skill
  before resolution.

### R5 — Update recommendations and embeddings

- Remove Canonical Job Taxonomy from Related Jobs candidate scoring.
- Score Related Jobs using 80% semantic similarity, 15% Governed Skill overlap, and 5%
  freshness.
- Remove Canonical Job Taxonomy text and change events from embedding document
  generation.
- Do not retain old Job embeddings during cutover; regenerate them from Job content and
  Governed Skills after the new schema is running.

### R6 — Retire obsolete contracts safely

- Update tests, fixtures, product/domain documentation, and Trellis specifications so
  Canonical Job Taxonomy is no longer described as active.
- Adjust or supersede active Job-taxonomy-specific Trellis tasks before implementation;
  preserve unrelated Company Industry and Skill task scope.
- Follow the existing destructive sandbox cutover guardrails. Before database clearing,
  the operator can abort and keep the old sandbox; after transient artifact finalization
  there is no application-level rollback.

## Acceptance Criteria

- [x] Job detail, Job Browser, Dashboard, filters, routes, API contracts, exports, and
      runtime capability payloads contain no Canonical Job Taxonomy surface.
- [x] Jobs continue to expose captured Source Classification Paths without presenting
      them as one cross-source hierarchy.
- [x] AI enrichment and automated classification no longer run or require a Job
      Taxonomy domain, mapping, assignment, readiness check, or change event.
- [x] The bootstrapped schema contains no Job-specific current taxonomy assignment
      table or `job` rows/constraints in shared taxonomy storage.
- [x] Company Industry assignments/mappings and Skill nodes, assignments, Candidates,
      Mentions, curation, and automatic Candidate processing remain operational.
- [x] Related Jobs uses exactly 80% semantic similarity, 15% Governed Skill overlap,
      and 5% freshness, with no taxonomy score or taxonomy response field.
- [x] Existing Job embeddings are omitted from retained cutover data and regenerated
      using Job content plus Governed Skills after deployment.
- [x] Sandbox export/import/verification preserves Jobs, Companies, source attributes,
      Company Industry data, and Skill governance data while excluding Job Taxonomy and
      stale embeddings.
- [x] Backend and frontend tests, fixture-parity checks, lint/type checks, builds, and
      architecture searches pass.

## Out of Scope

- Creating a replacement cross-source Job taxonomy.
- Combining source-native classification paths across job sites for Dashboard metrics.
- Removing or redesigning Company Industry taxonomy.
- Collapsing Governed Skills and Skill Candidate Evidence into one authority.
- Changing the semantic embedding model or Related Jobs candidate-retrieval algorithm
  beyond removing taxonomy input and applying the approved score weights.
