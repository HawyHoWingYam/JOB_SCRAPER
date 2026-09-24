# Implementation plan

- [x] Add failing PostgreSQL-backed model/service tests for preview, idempotent
  start, operation selection, eligibility, stop, restart, retry, and partial
  failure.
- [x] Add batch/item models, schemas, deterministic selection, fingerprints,
  and operation adapter protocol.
- [x] Add explicit preview/start/read/stop/resume/retry API routes and background
  dispatch entry point.
- [x] Add startup recovery that only marks interrupted batches stopped.
- [x] Remove scheduled and inline Jev initiation paths; retain read-only status.
- [x] Integrate Skills, duplicate association, and Related Jobs operation
  adapters while keeping provider receipt audit data.
- [x] Remove the local monetary ledger, Settings fields, run admission gates,
  batch cost ceiling, local cost estimation, and exhaustion translations;
  retain operational bounds and optional provider-reported usage/cost.
- [x] Run targeted PostgreSQL tests, API tests, ruff, and parent E2E scenarios.
