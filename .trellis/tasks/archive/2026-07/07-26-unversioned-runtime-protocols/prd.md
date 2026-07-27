# Remove application version protocols

Parent: `07-26-excluded-jobs-governance-handoff`

## Goal

Remove application API/event/projection/Automation/embedding/migration version
systems and establish explicitly atomic, current-state sandbox operation.

## Requirements

- Mount one current root API; remove `/api/v1` and version-selected projections.
- Remove event/payload/projection version fields from all producers/consumers.
- Keep current Automation rows only; remove revision snapshots, ETags, expected
  revision, revision-bound deletes, and stale conflicts. Writes are last-wins.
- Remove persisted embedding model/version identity; keep current vectors and add
  an explicit full reset/rebuild operation.
- Replace Alembic with one current empty-database schema bootstrap that refuses
  non-empty/incompatible mutation.
- Document/test stop/clear/deploy/start atomic deployment and destructive future
  schema rebuild policy.

## Acceptance Criteria

- [ ] Root frontend/backend API and events contain no application version field.
- [ ] Two stale Automation forms save in submission order and the later
      transaction is final; dispatch freezes current scope without revision.
- [ ] Current embeddings work without model/version columns and full reset works.
- [ ] Empty PostgreSQL bootstrap creates all target objects; non-empty mutation
      is refused; Alembic runtime/history is absent.
- [ ] Mixed-code deployment is documented unsupported and queue-clear tests pass.

## Dependency

Runs after target Source/taxonomy schemas are defined so the current schema
bootstrap has one final shape. Must complete before batch UI and cutover.
