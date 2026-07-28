# Application version-system impact map

## Purpose

Inventory the application-owned version, revision, and release systems that the
target design removes. Third-party dependency/runtime versions are excluded.

## Source Catalog and crawl authority

- `backend/app/models/source_catalog.py:25-225` defines candidates,
  validations, immutable revisions, active pointers, reviews, and publications.
- `backend/app/models/source_job_attributes.py:105-163` binds each preserved
  Source Classification Path to a catalog revision and exposes
  `provenance_limited` when the binding is absent.
- `backend/app/models/crawl_dispatch_plan.py:27-39,121-159` pins dispatch plans
  to catalog revisions and creates RESTRICT links between plans and crawl jobs.
- `backend/app/services/source_catalog_service.py:82-125,309-507` owns
  discover/validate/review/publish/activate semantics.
- `backend/app/services/scope_service.py:339-406` rejects authored scope when
  its reviewed catalog revision differs from the active revision.
- `backend/app/job_intelligence/source_attributes/provenance_repair.py:137-374`
  exists solely to bind old path evidence to an active catalog revision.

Target consequence: replace the complete vertical slice with one ordinary
Source-qualified classification registry, proactive adapter synchronization,
reactive ingest upsert, active/inactive top-level crawl choices, and preserved
child-path evidence.

## Canonical Job Taxonomy and optional mappings

- `backend/app/models/canonical_job_taxonomy.py:20-545` defines immutable
  taxonomy and mapping releases, active pointers, revision-pinned hierarchy,
  Source Catalog coverage, mappings, and targets.
- `backend/app/models/canonical_job_taxonomy.py:548-700` pins assignments and
  review rows to taxonomy/mapping revisions through RESTRICT foreign keys.
- `backend/app/job_intelligence/canonical_taxonomy/publisher.py:97-483`
  materializes and activates taxonomy/mapping releases with count, hash, and
  active-Source-Catalog guards.
- `backend/app/job_intelligence/canonical_taxonomy/read_model.py:369-415`
  resolves current reads through active pointers.

Target consequence: migrate the current active hierarchy, optional mappings,
current/historical assignments, and accepted evidence to stable ordinary IDs;
drop releases, active pointers, complete-coverage requirements, and revision
foreign keys. Missing mappings become non-blocking.

## Company Industry and Skill taxonomies

- `backend/app/models/company_industry.py:28-468` defines immutable releases,
  active pointer, revision-pinned nodes/crosswalks/mappings/assignments/reviews.
- `backend/app/job_intelligence/company_industry/publisher.py:360-543` owns
  materialize/activate and lock-version checks.
- `backend/app/models/skill_governance.py:30-640` applies the same release model
  to Skill categories, technologies, skills, aliases, candidates, mentions, and
  job-skill projections.
- `backend/app/job_intelligence/skill_governance/publisher.py:166-223` owns Skill
  release activation.

Target consequence: flatten the current active nodes and accepted projections
to stable ordinary identities; preserve accepted business evidence; remove
publication/activation and per-item governance queues.

## Automation and optimistic revisions

- `backend/app/models/schedule.py:97-205` stores `ScrapeSchedule.revision` plus
  immutable `automation_revisions` snapshots.
- `backend/app/services/automation_service.py:138-158,550-583` locks, compares,
  increments, and appends revisions on edits.
- `backend/app/services/dispatch_plan_service.py:175-230,505-545` rejects a plan
  if the Automation revision changed.
- `backend/app/api/crawl_control.py:121-123` exposes revision/ETag contracts.

Target consequence: remove revision history and stale-write conflicts. Current
Automation rows are last-write-wins; transactions/current-state checks remain.
Legacy tasks are deleted rather than migrated.

## Technical application versions

- `frontend/src/api/base.js:14-15` prefixes every application route with
  `/api/v1`.
- `backend/app/messaging/event_envelope.py:11-50` carries event
  `schema_version`.
- `backend/app/models/job_embedding.py:15-38` persists embedding model,
  dimensions, and version.
- `backend/app/models/source_job_attributes.py:30-50` and governance decision
  contracts carry projection/expected versions.
- `backend/alembic/versions/*.py` and Alembic history implement in-place schema
  upgrades.

Target consequence: root routes with no version selector, versionless atomic
events, no persisted embedding provenance, no optimistic revision tokens, and no
in-place migration ledger. Incompatible code changes deploy atomically after
stopping all services and clearing queues. Future schema changes destructively
rebuild the sandbox unless a new preservation exception is approved.

## Preserved technical identities

Python/npm/Docker/PostgreSQL and third-party model release identifiers remain
pinned because they identify external dependencies, not application-owned data
versions.
