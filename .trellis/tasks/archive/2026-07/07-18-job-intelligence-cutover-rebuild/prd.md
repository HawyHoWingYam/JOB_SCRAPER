# Job intelligence cutover rebuild

## Goal

Execute a controlled, auditable, and reversible cutover that preserves the core Job/Company corpus and raw evidence while destructively rebuilding all approved Job Intelligence Projections and embeddings under the new governed contracts.

## Background

- The 2026-07-18 snapshot contains 17,596 Jobs with raw data, 4,657 Companies, polluted industry values, entirely AI-created live Job taxonomy nodes, no governed Skill rows/links, more than 22k candidate mentions, and only 2,931 embeddings.
- Writers were active and counts changed during audit; cutover requires proven quiescence and one consistent snapshot.
- Exact preserve/reset boundary is ADR-0014 and `../07-18-job-intelligence-taxonomy-governance/research/current-data-migration-inventory.md`.

## Requirements

- Inventory and quiesce every ingest, enrichment, embedding, scheduler/manual, and API write path that can mutate affected data; fail closed if any writer remains.
- Record application commit/image, Alembic revision, taxonomy content hashes, worker state, database backup ID, and start timestamp.
- Create a consistent verified database backup plus immutable legacy audit export before destructive operations.
- Preserve Job/Company identities, source identities, raw data/metadata, descriptions, URLs, dates, salaries, unrelated enrichment, and approved audit evidence.
- Reset/reseed/rebuild only the approved derived projection and governed seed state for Canonical Job Taxonomy, Source Classification Paths, Employment Types, Company Industry, Skills, and embeddings in dependency order; never reset preserved raw Source/company evidence or Source Employment Labels.
- Default commands to dry-run; execute requires explicit flag, backup ID, expected counts/content hashes, and checkpoint directory.
- Make every phase checkpointed, idempotent/restartable, and observable with counts/reasons/timing.
- Reconcile referential integrity, provenance coverage, duplicate/Primary constraints, unresolved queues, serialization, search/filter behavior, and embedding readiness.
- Reopen writers only after all gates pass; retain prior image/schema/backup and legacy columns through rollback window.

## Acceptance Criteria

Completion below covers the implemented gates, automated disposable-PostgreSQL
rebuild, and backup/restore rehearsal. It does not authorize live `jobsdb`
execution or mark the separate go/no-go checklist as GO.

- [x] Dry-run performs no mutation and produces a complete preserve/reset/review report.
- [x] Quiescence check detects every known writer and aborts on uncertainty.
- [x] Backup restore is tested before destructive live execution.
- [x] Core Job/Company IDs and raw evidence counts/hashes are preserved.
- [x] Rebuild order produces valid governed revisions/projections with no guessed fallback values.
- [x] Every unsupported record becomes explicit Unknown/Unassigned/review with reason.
- [x] Restart from each checkpoint is idempotent and does not duplicate assignments/audit/outbox events.
- [x] Embeddings rebuild only after canonical/skill projections and reach the approved coverage gate.
- [x] Full backend/frontend/search smoke matrix passes before writers reopen.
- [x] Rollback restores prior database/application behavior within the documented window.

## Dependencies and scope

- Depends on children 2–5 schemas and rebuild logic after their dry-run fixtures pass; consumes foundation checkpoints/audit conventions.
- Can prepare/dry-run while child 6 proceeds, but parent release requires both children 6 and 7.
- Does not redesign domain contracts or delete the core corpus.

## Notes

- Complex child: requires `design.md` and `implement.md` review before start.
