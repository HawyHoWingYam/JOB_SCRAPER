# Implementation plan: Job Intelligence live rollout

## Ordered checklist

1. Reconfirm the clean release worktree, commit, image digest, effective Compose hash, current/target schema, seed hashes, embedding pin, disk, and PostgreSQL 15 client availability.
2. Create a unique UTC checkpoint directory with mode 0700; run inventory and verify its canonical envelope/hash.
3. Run dry-run and record zero mutation plus unchanged preserved fingerprints.
4. Drain/inspect outbox and active runs; stop backend API, scheduler, ingest, enrichment, embedding, Scrapyd, manual helpers, source-catalog admin, and external publishers; prove all writer states stopped and sentinel stability for at least 30 seconds.
5. Create the distinct restore database ending `_cutover_restore`; execute with a new backup ID; verify custom dump/client versions/restore fingerprints.
6. Allow phases 3–11 to rebuild governed projections and embeddings. On a checkpointed failure, fix only the concrete failure and resume the same manifest chain.
7. Generate rollback plan after backup verification.
8. At the expected Phase 12 pause, run backend API, governance, search/recommendation, embedding, and frontend smoke against the rebuilt identity; write exact post-Phase-11 runtime evidence.
9. Run `verify`, require verified `verify-report.json`, and resume execute without `--confirm-reopen-writers`; require Phase 12 completed and Phase 13 blocked.
10. Present the checked go/no-go evidence and request fresh writer-reopen approval.
11. After approval, resume with `--confirm-reopen-writers`, verify persistent services and post-reopen health, update completion evidence/docs, commit/archive the task, and close the overall plan.

## Validation commands and evidence

- `pg_dump --version`; `pg_restore --version`; `docker compose config --services`
- `job_intelligence_cutover.py inventory`, `dry-run`, `execute`, `verify`, and `rollback-plan` using the exact reviewed release worktree and checkpoint directory
- JSON envelope/hash inspection for manifest, reports, progress, and checkpoints
- SQL/service probes required by the go/no-go checklist
- Focused live smoke for the five required runtime checks; no repeated broad gate without a new failure

## Rollback points

- Before Phase 10: keep writers stopped and resume matching checkpoints or restore the verified backup.
- From Phase 10 onward: restore the verified backup plus previous image/configuration if rollback is required.
- Never overwrite the backup artifact or reuse the checkpoint directory for a changed manifest/release.

## Review gate before start

- User has explicitly approved task creation and execution through Phase 12.
- Existing runbook, go/no-go checklist, and backend cutover spec are the authoritative execution contract.
- Writer reopening remains a separate approval and is intentionally excluded from the current execution authority.
