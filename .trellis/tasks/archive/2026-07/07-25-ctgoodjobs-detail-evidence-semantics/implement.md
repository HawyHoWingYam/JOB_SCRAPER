# Implementation plan

1. Load the backend source-attribute, crawl-task metrics/projection, frontend
   task-control, CTGoodJobs transport, and error-handling specs.
2. Add a red regression test proving CTGoodJobs merge → canonical construction
   loses `source_attribute_evidence`, including detail-first and listing-fallback
   cases.
3. Update `merge_ctgoodjobs_job` to preserve evidence without weakening ingest
   validation; run focused CTGoodJobs parser/merge/ingest tests.
4. Add backend snapshot tests for a completed listing run whose staged rows are
   owned by an active independent detail run, while retaining terminal detail
   frozen-snapshot backlog coverage.
5. Make operator-state derivation phase-aware so downstream detail row states do
   not reclassify completed listing runs.
6. Remove the Task Details “Start detail recovery run” UI, its callback/draft
   path, and behavior-specific tests; retain manual-action Resume and snapshot
   metrics tests.
7. Run targeted backend pytest, frontend Vitest/ESLint/build, Python lint/type or
   compile checks required by repository specs, and `git diff --check`.
8. Perform a final contract review: listing task remains completed, detail
   snapshot metrics remain authoritative, CTGoodJobs evidence reaches ingest,
   and manual browser verification remains same-task Resume.

## Risk and rollback points

- Projection logic is shared across sources; tests must cover listing and detail
  phases for JobsDB, CTGoodJobs, and OfferToday-compatible contracts.
- Frontend cleanup must not remove manual-action controls merely because both
  features use “recovery” terminology.
- Stop and reassess if production detail runs do not expose a reliable phase or
  frozen-snapshot discriminator; do not infer ownership from mutable row counts.

## Validation result

- Backend focused contract gate: 62 passed, 1 skipped.
- Backend Ruff and `compileall`: passed.
- Frontend full Vitest gate: 239 passed across 39 files.
- Frontend ESLint and production Vite build: passed.
- Current-code read-only API projection for listing task
  `1d018b6b-80f3-4dcc-95b2-1172bbcb3e67`: `operator_state=completed`,
  `crawl_phase=listing`, and `detail_snapshot=null`.
- No historical crawl task was cancelled, repaired, migrated, or resumed.
