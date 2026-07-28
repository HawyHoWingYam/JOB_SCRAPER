# Remove application version systems and simplify classification

## Goal

Replace every application-owned version, revision, and release system with
ordinary current-state data and atomic sandbox operations. Simplify Source and
business classification so normal work is automated, newly observed Source
classifications do not block AI Enrichment, and operators never publish,
activate, bind, repair, select, or roll back application data versions.

## User Value

- Crawl work is configured by Source and broad classification, not catalog
  versions or hierarchy rules.
- Job Taxonomy, Company Industry, and Skill processing run as filtered batches
  instead of routine per-item human review.
- New Source classifications and sufficiently repeated Skills enter the system
  automatically without a release workflow.
- The sandbox contains only current business state; obsolete task and version
  history does not complicate operation.

## Confirmed Problem

The original failure exposed a version-governance dead end. The bounded JobsDB
scope `jobsdb:6281`, posted `2000-07-01` through `2026-07-22`, limit `4000`,
returns `3,131` `source_catalog_provenance_missing` exclusions while the linked
Governance queue returns zero rows. The scope handoff is correct, but preflight
can exclude Jobs without creating review rows, and the repair UI requires a
selected review row. See `research/excluded-handoff-repro.md`.

The approved response is not to surface provenance repair more prominently. It
is to remove Source Catalog provenance/versioning and the broader family of
application-owned version systems that created this operating model.

## Requirements

### R1. Remove application-owned version systems completely

- Remove Source Catalog candidate, validation, revision, active-pointer,
  publication, rollback, staleness, and provenance-repair models.
- Remove Canonical Job Taxonomy, Source-to-Canonical mapping, Company Industry,
  and Skill release/materialize/activate/version models.
- Remove Automation revision history and expected-revision conflict protocols.
- Remove application route/version negotiation such as `/api/v1`, event/payload
  `schema_version`, projection/decision version counters, and persisted
  embedding model/version identity.
- Remove the Alembic in-place migration ledger after the one-time cutover.
- Delete the corresponding frontend pages, routes, decoders, actions, backend
  endpoints/modules, database tables/columns/FKs/triggers, tests, fixtures, and
  superseded specs. Hiding navigation is not sufficient.
- Do not retain equivalent hidden counters or rename a version token to evade
  this requirement. Transactions, row locks, current-state guards, idempotency,
  evidence hashes, and audit may remain when they do not create a version
  identity.

### R2. Use one ordinary Source Classification Registry

- JobsDB, OfferToday, CTgoodjobs, and future Sources share one Source-qualified
  registry contract; equal IDs or labels from different Sources never merge.
- Source adapters proactively synchronize current top-level classifications on
  refresh/pre-crawl paths. Job ingestion idempotently upserts missed Source
  classification/path evidence.
- Newly observed Source classifications register directly without candidate,
  review, publication, or active-revision binding.
- Top-level classifications are never physically deleted. A classification no
  longer returned by its Source becomes inactive for new crawl authoring but
  remains resolvable for retained Jobs.
- A stable Source classification ID observed with a new label updates the
  registry label in place. Historical Job paths retain their captured labels.
- Preserve complete Source Classification Paths, including subclassifications,
  as evidence. Ordinary product surfaces and crawl authoring emphasize only
  top-level classifications.

### R3. Simplify crawl scope and Source execution

- Authored scope contains one Source plus either all active top-level Source
  classifications or an explicit set of active top-level IDs.
- Remove catalog revision, Exact/Subtree, and child-classification selection
  from UI, request, persistence, dispatch, and runtime contracts.
- A Source classification is valid evidence even when the Source has no
  dedicated classification query. The Source adapter may compile a dedicated
  query or use a safe broader-collection/filter strategy.
- Malformed Source identity/query data remains rejected. Registration alone
  never turns arbitrary data into an executable query.

### R4. Make Source-to-Canonical mappings optional

- Preserve existing useful Source-to-Canonical mappings as optional constraints
  or hints to existing Canonical Job Taxonomy targets.
- Missing mapping coverage never blocks AI Enrichment and does not produce
  `source_mapping_missing` solely because a new Source classification exists.
- Without a mapping, automated Job classification uses retained Job content,
  broad Source evidence, and the full existing Canonical Job Taxonomy.
- Direct Source classification creation never creates a Canonical Job Taxonomy
  node.

### R5. Flatten business taxonomies to ordinary stable data

- Migrate the current Canonical Job Taxonomy, Company Industry, Skill hierarchy,
  aliases, useful mappings, accepted assignments, and required evidence from
  revision-pinned rows to ordinary stable IDs and current-state foreign keys.
- Preserve existing Canonical Job and Company Industry content and hierarchy.
- Do not provide add/rename/retire management pages for Canonical Job or Company
  Industry data in this task. A future CRUD feature requires separate planning.
- Preserve human governance decisions, audits, accepted Job Taxonomy
  assignments, Company Industry assignments, Skill projections, and evidence as
  business state, while removing their revision/lock-version fields.

### R6. Replace Governance queues with automated processing batches

- Delete the Source Catalog and Job Intelligence Governance pages and routine
  per-item Job Taxonomy, Company Industry, and Skill review queues.
- Provide domain-specific filtered batch processing/status/retry surfaces with
  the interaction model of AI Enrichment: bounded selection, launch, progress,
  failure details, retry, and individual-record deep links.
- Ordinary Job Taxonomy, Company Industry, and Skill processing is automated.
  Individual manual correction remains optional, never the default queue.
- Uncertain processing remains unresolved/failed and retryable; it must not
  invent `Other`, `Unknown`, or fallback taxonomy nodes.

### R7. Auto-create repeated Skills

- Aggregate unknown normalized Skill evidence using distinct Job count, not raw
  occurrence count.
- Expose a Settings value for the automatic creation threshold; default `5`.
- At threshold, automated processing rejects duplicates, aliases, and generic
  terms, then chooses an existing Skill Category/Technology and creates the
  ordinary Skill.
- If placement is uncertain, keep the candidate in the failed batch for retry.
  Do not create an unclassified fallback Skill.
- Changing the threshold affects subsequent evaluation only; it does not rewrite
  already created Skills.

### R8. Adopt explicitly unversioned runtime behavior

- Editable records are last-write-wins in this trusted-local single-operator
  product. Two stale forms may save; the later complete transaction is final.
- Incompatible frontend/backend/worker changes require an atomic deployment:
  stop all processes, clear old queues/consumer state, deploy the complete
  application, then restart together. Rolling or mixed-code deployments are
  unsupported.
- Preserve existing embedding vectors during this cutover without checking or
  storing their model/version provenance. Mixed-model retrieval-quality risk is
  accepted.
- A future embedding model change deletes and regenerates the complete embedding
  index before retrieval resumes; a dimension change also rebuilds the vector
  schema.

### R9. Perform a one-time preserving sandbox cutover

- This sandbox needs no backup or compatibility archive.
- Stop all services and export only retained business/governance state: Job
  source IDs/details/AI fields, Companies, embeddings, Source path evidence,
  current taxonomy/industry/skill data, accepted assignments/projections, and
  required decision/audit evidence.
- Permanently delete every pre-cutover crawl, Automation, dispatch, schedule,
  manual-action, AI Enrichment, Company Enrichment, embedding, recommendation,
  recovery, ingestion, and scheduler task/run record.
- Clear durable outbox commands, Redis Streams, dead letters, consumer groups,
  and pending/claimed messages. No old task may resume or republish.
- Rebuild the database directly from the target schema and import only retained
  data. Do not restore task history, release/version data, or Alembic history.
- Explicitly handle RESTRICT/cyclic crawl-job/dispatch-plan references; never use
  a cascade path rooted at retained Jobs or Companies.
- After cutover, future schema changes destructively rebuild the sandbox unless
  a new preservation exception is explicitly approved.

### R10. Keep external dependency identities

- Preserve pinned Python, npm, Docker, PostgreSQL, and third-party model release
  identifiers required for reproducible installation and execution.
- These external software identities are not application-owned version systems.

## Acceptance Criteria

- [x] AC1: Static architecture checks find no production application-owned
      release/revision/active-pointer/publication/rollback/provenance-repair,
      optimistic-version, API-version, event-schema-version, projection-version,
      embedding-version, or Alembic-history interface/schema remnants.
- [x] AC2: JobsDB, OfferToday, and CTgoodjobs proactively populate the ordinary
      Source Classification Registry, reactively upsert missed evidence, update
      labels in place, retain inactive top-level identities, and preserve child
      paths without exposing children as crawl choices.
- [x] AC3: New crawl authoring supports only Source plus all/selected active
      top-level classifications; each adapter's dedicated-query or broader-fetch
      behavior is tested without catalog revision or Exact/Subtree data.
- [x] AC4: No Job is excluded solely for missing Source Catalog provenance or
      Source-to-Canonical mapping coverage. Useful mappings constrain AI when
      present; absent mappings fall back to the existing Canonical taxonomy.
- [x] AC5: Current Canonical Job, Company Industry, Skill, mappings, assignments,
      projections, and required evidence resolve through stable ordinary IDs
      after all revision-pinned FKs and active pointers are gone.
- [x] AC6: No Source Catalog or Job Intelligence Governance queue remains in
      navigation. Job Taxonomy, Company Industry, and Skill batch surfaces cover
      bounded selection, launch, progress, failures, retry, and optional direct
      correction.
- [x] AC7: Settings persists a distinct-Job Skill threshold defaulting to `5`;
      tests cover threshold crossing, duplicate reuse, generic rejection,
      existing-category placement, unresolved placement, and no fallback node.
- [x] AC8: Root API/event contracts contain no application version selector;
      stale forms are last-write-wins; deployment checks/documentation enforce
      stop/clear/deploy/start for incompatible changes.
- [x] AC9: Existing embedding row identities/vectors survive the cutover without
      model/version columns, and a full reset/rebuild path exists for a future
      model or dimension change.
- [x] AC10: Before/after manifests prove identical retained Job, Job detail,
      Company, AI field, embedding, assignment/projection, and governance-evidence
      identities/content after export/rebuild/import.
- [x] AC11: All database task/run/outbox records and Redis task/consumer state are
      empty after cutover; no old worker command can resume or republish.
- [x] AC12: The fresh target database contains no application release/version or
      Alembic history tables, and subsequent documented schema changes use the
      approved destructive sandbox rebuild policy.
- [x] AC13: Backend/frontend/integration tests and cross-source smoke tests pass
      after an atomic startup against the fresh target schema.

## Technical Evidence

- `research/version-system-impact.md`
- `research/cutover-retention-map.md`
- `research/skill-threshold-history.md`
- `research/excluded-handoff-repro.md`

## Out of Scope

- Removing or unpinning third-party dependency/runtime/model release identities.
- Adding Canonical Job Taxonomy or Company Industry CRUD management pages.
- Supporting rolling deployments, mixed old/new workers, or in-place database
  upgrades after this cutover.
- Preserving any pre-cutover task/run/release/version history.
