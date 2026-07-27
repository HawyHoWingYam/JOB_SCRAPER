# Cut over retained data and clear task history

Parent: `07-26-excluded-jobs-governance-handoff`

## Goal

Perform the one approved preserving cutover: retain accepted business data,
remove every old task/version/queue record, create the target schema, import and
verify retained state, then start the complete application atomically.

## Requirements

- Export only agreed Job/detail/AI, Company, embedding, Source evidence, current
  taxonomy/mapping/assignment/projection, and required audit/idempotency data.
- Stop all services and clear database task/run/outbox plus Redis stream/group/
  pending/dead-letter state.
- Destroy the sandbox DB, bootstrap the target schema, import/remap retained
  data, and verify exact identities/content/counts.
- Handle crawl-job/dispatch-plan/schedule RESTRICT cycles explicitly and never
  delete from retained Job/Company roots.
- Delete the transient export after successful verification; no backup or old
  compatibility state remains.

## Acceptance Criteria

- [x] Disposable production-shaped cutover passes twice from a clean start.
- [x] Shared sandbox before/after manifests match for every retained dataset.
- [x] Every old task/run/outbox/Redis command and application version/release row
      is absent after import.
- [x] No old worker command resumes; complete stack starts atomically and
      cross-source/business-data smoke tests pass.
- [x] Transient export is deleted only after verification and no Alembic history
      or compatibility archive remains.

## Dependency

Final child. Requires all four target-code children complete and green. Owns the
final integration/forbidden-version gate and destructive shared sandbox action.
