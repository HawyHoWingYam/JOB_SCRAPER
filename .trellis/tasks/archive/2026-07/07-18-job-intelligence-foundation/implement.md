# Job intelligence foundation implementation plan

## Dependency

First child; no other program child may start implementation until these contracts are reviewed and tests pass.

## Ordered checklist

1. Load `trellis-before-dev` for backend/database specs and reread parent/child artifacts.
2. Add failing contract tests for revision immutability, decision atomicity, idempotent replay/conflict, stale version, audit/outbox, and worker-interface isolation.
3. Define foundation value types/errors with no domain-specific enums or node types.
4. Add Alembic migration and SQLAlchemy models/repositories for revisions, audit events, and idempotency records.
5. Implement normalized manifest hashing and deterministic full-report seed validation primitives.
6. Implement `GovernanceUnitOfWork` transaction protocol using the existing outbox repository.
7. Add two fake domain adapters in tests; remove any foundation branch that knows their domain semantics.
8. Add audit read pagination and response schema for child 6 consumption.
9. Document trusted-local operator mode, future authentication wrapper seam, and legacy compatibility conventions.
10. Run targeted tests, migration upgrade/downgrade on disposable PostgreSQL, then full backend validation.

## Validation

```bash
cd backend && pytest -q tests/test_job_intelligence_foundation.py
cd backend && alembic upgrade head
cd backend && ruff check app tests && black --check app tests && mypy app
cd backend && pytest -q
python3 ./.trellis/scripts/task.py validate 07-18-job-intelligence-foundation
```

Use a disposable database for downgrade/rollback tests; do not downgrade the live development corpus.

## Risk and rollback points

- Freeze the Interface before children 2–5 branch from it; later incompatible changes require coordinated PRD/design updates.
- Do not add a generic evidence or taxonomy-node table to “help” children; that would move domain rules into a shallow Module.
- If outbox atomicity cannot be reused cleanly, stop and revise design rather than introducing a parallel event bus.
- Before dependent data exists, migration can roll back normally. After adoption, preserve foundation history even if application code is rolled back.

## Implementation evidence — 2026-07-18

- Targeted foundation gate: 21 PostgreSQL-backed tests passed; targeted ruff,
  black, and mypy passed with zero findings.
- Real disposable-PostgreSQL rehearsal: stamped predecessor
  `20260718_180000`, upgraded to `20260718_210000`, verified three tables and
  three immutability triggers, proved direct revision UPDATE and audit DELETE
  fail, then downgraded to the predecessor with zero foundation tables left.
- Full backend behavior was run file-by-file against the disposable database:
  196 tests passed, 1 existing optional PostgreSQL test skipped, and no test
  file failed. One-shot combined pytest collection blocks even when the
  foundation test is ignored, so this is recorded as a pre-existing collection
  interaction rather than a foundation failure.
- Repository-wide ruff/black/mypy remain red on pre-existing files outside this
  child (255 ruff findings, 197 black reformat candidates, and 28 mypy errors).
  The changed foundation files pass all three targeted checks; unrelated files
  were preserved.
