# Job Intelligence live rollout

## Goal

Complete the separately approved Job Intelligence live rebuild and cutover against the local Compose `jobsdb`, preserve the Job/Company/raw-evidence corpus, and leave writers closed after verified Phase 12 until a fresh reopening approval is received.

## Background

- Implementation, disposable rehearsal, rollback tooling, CP10, and the three Crawl Control UI children are already complete.
- The approved release source is clean detached worktree `/tmp/job_scraper-release-db6` at commit `db6ad96ca9eb92424960ab5d27395a78b22134af`.
- The approved release image is `job_scraper-backend-api:ji-cutover-db6`, digest `sha256:9b5e7b22dd19e4cb8e767184c4d0db8b0b7786638ee2e68bb5d60ecbbbb5d4be`.
- The clean effective Compose configuration SHA-256 is `1d98415d1de289168b626f4195f153cafb63f17f4c9d61422ec258ba63832425`.
- User approval covers task creation, writer shutdown, backup/restore verification, live migration/rebuild, authoritative read switch, and execution through Phase 12. It does not cover Phase 13 writer reopening.

## Requirements

1. Use only the reviewed release commit, image, configuration hash, schema target, and governed seed/model pins; abort on drift.
2. Establish a trusted operator environment with project/ML dependencies, PostgreSQL 15-compatible clients, and Docker Compose control. Do not grant Docker-daemon authority to the public API container.
3. Create a new mode-0700 manifest/checkpoint directory and produce inventory plus zero-write dry-run evidence with `mutation_detected=false`.
4. Drain/verify the pre-cutover outbox and active-run counts, stop every known writer, and prove a stable 30-second database sentinel before execute.
5. Create an immutable PostgreSQL custom-format backup, restore it to a distinct database ending `_cutover_restore`, and prove preserved fingerprints match exactly.
6. Execute ordered phases 1–11 using the manifest-bound resumable checkpoint chain; preserve Jobs, Companies, raw evidence, Source Catalog evidence, and unrelated enrichment.
7. Run the post-Phase-11 five-check smoke matrix, create exact runtime evidence, and produce `verify-report.json` with verified status.
8. Resume Phase 12 without writer control and prove Phase 13 remains closed.
9. Do not reopen writers until a new, separate user approval is received. After that approval, resume Phase 13, check worker/API/search health, and record final target-environment evidence.
10. Keep unrelated dirty worktree changes untouched.

## Acceptance Criteria

- [x] Manifest identity/hash, seed pins, schema revisions, and mode-0700 checkpoint directory are recorded and verified.
- [x] Dry run is zero-write and preserved fingerprints are unchanged.
- [x] All writer observations are explicitly stopped, no active run remains, pre-cutover outbox is drained as required, and the 30-second sentinel is unchanged.
- [x] Backup ID, dump SHA-256, PostgreSQL client versions, restore target, and exact restored fingerprints are recorded.
- [x] Phases 1–11 complete in order with valid checkpoint envelopes and full rebuild reconciliation, including 100% eligible embedding coverage for the pinned model/version/384 dimensions.
- [x] Post-rebuild runtime evidence is newer than Phase 11 and all five checks are true.
- [x] Phase 12 completes and `verify-report.json` reports verified for the exact manifest/application identity.
- [x] Writers remain stopped while awaiting the second approval.
- [x] After separately approved Phase 13, persistent writer state and post-reopen health are verified, rollback evidence is retained, and `docs/20260718.md` records final completion.

## Out of Scope

- Alembic downgrade as rollback.
- Deleting legacy columns during the cutover window.
- Reopening writers under the first rollout approval.
- Unrelated refactors or reopening already accepted Crawl Control/UI checkpoints.
