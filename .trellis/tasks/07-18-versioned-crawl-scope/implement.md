# Versioned Crawl Scope and Automation control implementation plan

## Ordered implementation

### 1. Add versioned schemas and pure scope resolver

- [x] Define Pydantic/domain contracts for Authored Scope, rules/all mode, selected snapshots, Query Targets, listing/detail settings, Detail Backlog Scope, Resolved Scope, impact, and errors.
- [x] Implement source-qualified parsing and rule canonicalization.
- [x] Implement preview/resolve against published catalog adapters.
- [x] Implement catalog compatibility classification.
- [x] Add pure tests for exact/subtree/all, future descendants, aliases, stale IDs, capability changes, and workload impact.

Checkpoint commit: pure scope logic only.

### 2. Add Automation persistence/lifecycle

- [x] Extend current schedule model with revision/lifecycle/scope/settings/review/archive fields.
- [x] Add immutable `automation_revisions`.
- [x] Make Automation instant columns timezone-aware UTC while preserving the IANA cron timezone; cover non-HKT/DST serialization.
- [x] Add fresh metadata bootstrap and one existing-DB Alembic/convergence migration, then compare resulting tables/FKs/indexes for schema parity.
- [x] Implement compare-and-swap repository and valid transition table.
- [x] Change Schedule Execution's Automation FK to nullable `SET NULL`, add immutable execution snapshots, and define archived-only permanent-delete impact.
- [x] Implement create/update/pause/resume/archive/restore/delete-impact services plus eventually consistent scheduler reconciliation.
- [x] Make every due callback validate registered/current Automation Revision and active lifecycle under DB lock before dispatch; test stale/repeated reconcile and crash recovery.
- [x] Verify no lifecycle action mutates existing Schedule Execution/Crawl Job snapshots.

Checkpoint 2 verification used an isolated `job_scraper_automation_test` PostgreSQL
database: a stamped current-schema fixture upgraded, downgraded, and upgraded again.
The repository-wide migration chain still cannot bootstrap from an empty database
because its historical base assumes `jobs` exists; checkpoint 9 retains that known
fresh-baseline repair instead of hiding it with duplicate bootstrap DDL.

Checkpoint commit: lifecycle backend, no cutover.

### 3. Add Dispatch Plan persistence

- [x] Add plan, distinct target, and target-to-staging-row membership models/FKs/indexes.
- [x] Link Crawl Job/Schedule Execution to plan ID and fingerprint while retaining compatibility snapshots.
- [x] Add repository locking, expiry, fingerprint/token, single-use, and cleanup.
- [x] Make executor startup load/verify the consumed plan; forbid Schedule/`request_payload` reconstruction and keep resume context as a separate overlay.
- [x] Test double consume, expiry, plan/payload tamper, missing fingerprint, rollback, deterministic target/row order, and no unbounded logs.

Checkpoint 3 verification covered 34 focused Dispatch Plan/Automation regressions
and the full backend suite (`333 passed, 152 skipped`), plus focused Ruff and
mypy, compileall, and `git diff --check`. An isolated
`job_scraper_dispatch_plan_test` PostgreSQL database rehearsed metadata
`create_all`, stamp/downgrade/upgrade, ORM/schema parity, immutable plan/job/
payload/target triggers, expired-plan cascade cleanup, and Automation
`SET NULL` snapshot retention; the disposable database was removed afterward.

Versioned worker execution intentionally remains fail-closed at this checkpoint:
launcher, standalone-worker, and resume entry points validate consumed plan
authority and then reject with `runtime_authority_adapter_required`. Checkpoints
4 and 5 replace that safety gate with listing and detail plan-backed runtime
adapters; no versioned path falls back to mutable `request_payload` meanwhile.

### 4. Implement listing preview and enforcement

- [x] Resolve target count, Page Depth, estimated maximum, operator Run Page Cap, and system ceiling.
- [x] Reject over-cap preparation with structured details.
- [x] Update all listing runtimes to iterate resolved Query Targets and one aggregate page counter.
- [x] Disable retained Scrapy listing callbacks from auto-starting detail work for versioned plans.
- [x] Add cross-source captured-outbound-request tests for early empty pages, aggregate cap, and target-specific URL/query/body constraints.

Checkpoint 4 makes consumed listing plans executable while detail plans and
versioned resume remain fail-closed for Checkpoint 5. JobsDB, CTgoodjobs, and
OfferToday standalone and retained Scrapy runtimes reload authority by Crawl
Job ID, use the frozen target order and source-native parameters, enforce Page
Depth plus the aggregate Run Page Cap, and never re-resolve the active catalog.
Versioned Scrapy requests disable middleware retries so actual outbound work
cannot exceed the reviewed budget, and listing callbacks no longer start
detail requests.

Verification covered 91 focused scope/dispatch/source/runtime/launcher tests
and the full backend suite (`343 passed, 152 skipped`). Focused Ruff and mypy,
compileall, and `git diff --check` also passed. Failure injection covers Popen
and process-registration rollback, while cross-source tests capture JobsDB
query parameters, CTgoodjobs paths/early-empty behavior, and OfferToday browse
bodies with no hidden keyword/default scope.

### 5. Implement detail backlog scope/snapshot

- [x] Build one eligibility query seam for Source backlog, Crawl Scope, and Listing Batch.
- [x] Group by canonical `source_job_id` before limits.
- [x] Freeze exact deterministic target and every contributing staging-row membership plus cutoff/count under safety cap.
- [x] Make runtime consume only plan targets and segment within Detail Run Cap.
- [x] Keep future eligible backlog separate from plan remaining.
- [x] Cover duplicates, null classifications, listing-batch retention, failures/manual action, resume, and cancellation release.

Checkpoint 5 freezes source-qualified detail membership before dispatch, applies
the complete-run limit to canonical `source_job_id` groups, persists every
contributing staging row and cutoff/count/fingerprint metadata, and makes all
three standalone runtimes consume only that frozen authority. Recovery segments
partition the snapshot without extending it; resume and cancellation operate on
the same plan-owned membership; snapshot projections distinguish remaining
frozen work from future live eligibility.

Final verification covered 83 focused detail/dispatch/runtime/snapshot/
cancellation regressions and the full backend suite (`354 passed, 152 skipped`).
Touched-file Ruff, focused mypy (13 source files), compileall, and
`git diff --check` passed. Three independent final reviews found no actionable
integrity, resume/fail-closed, or cross-runtime regression.

Rollback point: old detail runtime remains selectable only in test until snapshot parity passes; never run both against the same production backlog.

### 6. Implement preparation/dispatch transactions

- [x] Add saved-Automation and One-off request variants.
- [x] Implement readiness, conflict, pacing, headed-worker, catalog, scope, and cap checks.
- [x] Persist prepared plan without launch.
- [x] Atomically consume plan into Schedule Execution/Crawl Job/event/outbox and launch after commit.
- [x] Add scheduled prepare-and-consume path.
- [x] Add stale catalog/Automation/eligibility/readiness and active-detail-conflict tests.
- [x] Preserve existing cancellation service and regression tests.
- [x] Verify publication after run commit does not invalidate the in-flight plan, while pre-dispatch active-revision drift rejects an unconsumed plan.

Checkpoint 6 adds reviewed One-off/Saved Automation requests, atomic scheduled
prepare-and-consume, frozen detail pacing for every versioned trigger, consume-
time catalog/Automation/readiness/eligibility rechecks, and post-commit launch
recovery limited to the plan-owned detail membership. Scheduler consumption
always reloads the Automation with `SELECT ... FOR UPDATE`; legacy Run now
fails with a structured review-required conflict instead of an unhandled 500;
expired consumption rolls back unrelated Session mutations before persisting
expiry; and cancellation/launch recovery locks running rows before release.

Final verification covered 37 Dispatch Plan tests with three opt-in PostgreSQL
tests skipped, plus 104 related Automation/runtime/pacing/cancellation tests
with three skips. A disposable `crawl_control_cp6_test` PostgreSQL database ran
three required transaction/concurrency scenarios: scheduled detail failure
rolled back plan/execution/job/event/outbox/claims, two concurrent consumers
produced exactly one consumed plan and one already-consumed error, and recovery
row locking could not overwrite a concurrent terminal detail outcome. The full
backend suite passed (`368 passed, 155 skipped`). Touched-file Ruff, focused
mypy (8 source files), compileall, and `git diff --check` also passed.

### 7. Add Automation/plan/board APIs

- [ ] Add versioned routes/schemas and stable machine error codes.
- [ ] Return current revision on conflict and forbid implicit merge.
- [ ] Add normalized Task Control Board, Automation row, run, workload, and detail snapshot projections.
- [ ] Add normalized fallback fields to Crawl Tasks/Logs so new control UI and post-cutover history never need raw request/event parsing.
- [ ] Make legacy schedule routes delegate temporarily; stop new writes of `category_ids`.
- [ ] Add contract tests that frontend never needs raw request/event decoding.

### 8. Integrate catalog impact/publication

- [ ] Provide the real `CatalogImpactEvaluator` to child 1's catalog module.
- [ ] Test label/move compatible changes, future descendant inclusion, removed/query-changed nodes, alias dedup changes, and cap overflow.
- [ ] Mark incompatible Automations `scope_review_required` in publication/rollback transaction.
- [ ] Exercise explicit initial revision publication with legacy-reset warning in staging.

Checkpoint: every Source has one active validated revision before cutover rehearsal.

### 9. Build migration and cutover tooling

- [ ] Keep ORM metadata canonical for fresh `create_all`; use one migration/convergence path for existing DB and avoid duplicate ad-hoc DDL for these tables.
- [ ] Test schema parity for fresh bootstrap, upgraded current-schema fixture, and a metadata-created fixture despite the incomplete baseline.
- [ ] Implement maintenance preflight: service/process state, actual FKs, backup acknowledgement, preserve/reset counts.
- [ ] Implement dry-run count report and FK-safe reset script scoped to crawl outbox rows.
- [ ] Add transaction failure injection and preserve-count assertions.
- [ ] Rehearse backup/restore and fresh DB bootstrap on disposable databases.
- [ ] Update `.gitignore` so all new migration/test artifacts are tracked.

### 10. Perform approved cutover

- [ ] Obtain user/operations approval for maintenance execution; planning approval alone is not production cutover approval.
- [ ] Stop scheduler/workers/outbox/API mutations and verify no external crawl remains.
- [ ] Take backup and record preflight report.
- [ ] Run reset transaction/script.
- [ ] Verify preserved corpus/taxonomy/enrichment/catalog counts and FKs.
- [ ] Restart services and create one bounded smoke Automation/One-off plan per Source.
- [ ] Keep backup until full acceptance.

### 11. Verify and update specs

Focused tests:

```bash
python3 -m pytest -q backend/tests/test_crawl_scope_service.py
python3 -m pytest -q backend/tests/test_automation_lifecycle.py
python3 -m pytest -q backend/tests/test_dispatch_plan_service.py
python3 -m pytest -q backend/tests/test_detail_backlog_snapshot.py
python3 -m pytest -q backend/tests/test_catalog_automation_impact.py
python3 -m pytest -q backend/tests/test_crawl_task_snapshot_service.py
python3 -m pytest -q backend/tests/test_crawl_job_regressions.py
python3 -m pytest -q backend/tests/test_cross_source_ip_recovery.py
```

Full/migration:

```bash
python3 -m pytest --collect-only -q backend/tests
python3 -m pytest -q backend/tests
python3 -m ruff check backend/app backend/scripts backend/tests
python3 -m compileall -q backend/app backend/scripts
alembic -c backend/alembic.ini history
docker compose run --rm db-bootstrap
docker compose run --rm backend-api python -m pytest -q tests
git diff --check
```

- [ ] After finite membership/cap, normalized metrics, cancellation/recovery, and cross-source runtime tests pass, review and update `.trellis/spec/backend/offertoday-production-crawl.md`.
- [ ] Under the same verified gate, update `.trellis/spec/backend/crawl-task-detail-metrics.md`.
- [ ] Update affected frontend snapshot/pacing contracts only after the backend behavior and spec review pass.
- [ ] Preserve logging and cancellation specs.

## Rollback points

- Before cutover: revert code/migrations normally; existing data remains.
- During reset transaction: rollback immediately on any preserve-count/FK failure.
- After reset commit: restore the pre-cutover backup and compatible application image.
- A stale/failed Dispatch Plan never falls back to dynamic scope/backlog; the safe rollback is to require a fresh plan.
