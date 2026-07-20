# Job intelligence cutover and rebuild implementation plan

## Dependencies

- Requires reviewed/completed schemas and rebuild Interfaces from children 2–5 after their dry-run fixtures pass.
- Uses foundation audit/idempotency conventions.
- May prepare while product surfaces proceed, but execute/reopen requires parent release coordination.

## Ordered checklist

1. Load `trellis-before-dev`, parent artifacts, ADR-0014, current-data inventory, operations/database specs, and every domain rebuild Interface.
2. Add an anonymized representative legacy database fixture and preservation hash helpers.
3. Implement manifest schema, deterministic inventory, secret redaction, and checkpoint store.
4. Implement writer inventory/quiescence checks with fail-closed tests.
5. Implement backup command integration and automated disposable restore verification.
6. Implement immutable legacy audit export with checksums.
7. Wire domain rebuild phases in approved order; enforce table/column reset allowlist.
8. Implement dry-run reports and prove no mutation at database level.
9. Implement execute/resume input-hash and code-version checks.
10. Implement database/API/search/frontend/embedding verification gates.
11. Implement rollback-plan output and rehearse full restore on disposable environment.
12. Run failure injection at every checkpoint and correct non-idempotent behavior.
13. Produce the exact live/local cutover runbook and one-shot go/no-go checklist; do not execute until separately approved.

## Validation

```bash
cd backend && pytest -q tests/test_job_intelligence_cutover.py tests/integration/test_job_intelligence_rebuild.py
cd backend && ruff check app tests scripts && black --check app tests scripts && mypy app
cd backend && pytest -q
cd frontend && npm run lint && npm test && npm run build
python3 ./.trellis/scripts/task.py validate 07-18-job-intelligence-cutover-rebuild
```

Required rehearsals:

- dry-run against current snapshot clone;
- execute against clone with all writers stopped;
- fail/resume at every phase;
- backup restore and previous-image smoke;
- full integration verification before any live execute request.

## Risk and rollback points

- This child may write scripts/tests/runbooks before live approval, but live `execute` is a separate explicit user decision.
- Never run against the current database while workers remain active.
- Never use Alembic downgrade as the data rollback mechanism.
- Stop immediately on preserved hash mismatch, unknown writer, missing backup restore proof, taxonomy hash drift, or unexplained reconciliation count.
- Keep legacy columns and previous images through the agreed rollback window; cleanup is a follow-up after acceptance.
