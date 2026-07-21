# Design: Job Intelligence live rollout

## Boundary

The existing `job_intelligence_cutover.py` controller is the sole mutation orchestrator. The main worktree owns Trellis records only; live commands run from the clean reviewed release worktree so unrelated local changes cannot enter release identity.

## Operator environment

Use the trusted host with PostgreSQL 15 clients and the release worktree's Python/ML dependencies. Docker Compose remains the source of writer inventory and service control. Secrets stay in environment variables and never enter argv or persisted artifacts.

## Data flow

1. Pin release identity and governed seed/model versions in `manifest.json`.
2. Produce a zero-write dry-run report.
3. Quiesce Compose writers and prove database stability.
4. Back up `jobsdb`, restore to a distinct `_cutover_restore` database, and compare preserved fingerprints.
5. Execute the fixed 13-phase state machine through Phase 11; the expected first pause is Phase 12 because runtime evidence does not yet exist.
6. Observe the rebuilt still-quiesced system, create the exact five-check runtime evidence, run `verify`, then resume Phase 12 without writer control.
7. Hold at Phase 13 until separate approval, then inject writer control and resume.

## Contracts and compatibility

- The reset allowlist is fixed by the archived cutover contract; corpus and raw evidence are invariant.
- Checkpoint reuse is allowed only when manifest hash, code version, phase, ordinal, and chained input hash match.
- Embedding freshness requires document hash, exact model name, version 1, and 384 dimensions. Inventory output is authoritative for whether the normalized pinned value is short or fully qualified.
- Existing Crawl Control authority and live catalog revisions remain unchanged.

## Failure and rollback

- Any unknown writer, manifest drift, fingerprint mismatch, active run, non-drained pre-cutover outbox, sentinel movement, or invalid artifact is an immediate hard stop.
- Before the authoritative read switch, prefer valid checkpoint resume.
- After the read switch or post-reopen writes, use the verified backup and reviewed previous image/configuration; never reverse-translate or Alembic-downgrade data.
- Generate `rollback-plan.json` after backup verification and retain it through the monitoring window.
