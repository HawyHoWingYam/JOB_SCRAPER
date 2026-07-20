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

- [ ] Extend current schedule model with revision/lifecycle/scope/settings/review/archive fields.
- [ ] Add immutable `automation_revisions`.
- [ ] Make Automation instant columns timezone-aware UTC while preserving the IANA cron timezone; cover non-HKT/DST serialization.
- [ ] Add fresh metadata bootstrap and one existing-DB Alembic/convergence migration, then compare resulting tables/FKs/indexes for schema parity.
- [ ] Implement compare-and-swap repository and valid transition table.
- [ ] Change Schedule Execution's Automation FK to nullable `SET NULL`, add immutable execution snapshots, and define archived-only permanent-delete impact.
- [ ] Implement create/update/pause/resume/archive/restore/delete-impact services plus eventually consistent scheduler reconciliation.
- [ ] Make every due callback validate registered/current Automation Revision and active lifecycle under DB lock before dispatch; test stale/repeated reconcile and crash recovery.
- [ ] Verify no lifecycle action mutates existing Schedule Execution/Crawl Job snapshots.

Checkpoint commit: lifecycle backend, no cutover.

### 3. Add Dispatch Plan persistence

- [ ] Add plan, distinct target, and target-to-staging-row membership models/FKs/indexes.
- [ ] Link Crawl Job/Schedule Execution to plan ID and fingerprint while retaining compatibility snapshots.
- [ ] Add repository locking, expiry, fingerprint/token, single-use, and cleanup.
- [ ] Make executor startup load/verify the consumed plan; forbid Schedule/`request_payload` reconstruction and keep resume context as a separate overlay.
- [ ] Test double consume, expiry, plan/payload tamper, missing fingerprint, rollback, deterministic target/row order, and no unbounded logs.

### 4. Implement listing preview and enforcement

- [ ] Resolve target count, Page Depth, estimated maximum, operator Run Page Cap, and system ceiling.
- [ ] Reject over-cap preparation with structured details.
- [ ] Update all listing runtimes to iterate resolved Query Targets and one aggregate page counter.
- [ ] Disable retained Scrapy listing callbacks from auto-starting detail work for versioned plans.
- [ ] Add cross-source captured-outbound-request tests for early empty pages, aggregate cap, and target-specific URL/query/body constraints.

### 5. Implement detail backlog scope/snapshot

- [ ] Build one eligibility query seam for Source backlog, Crawl Scope, and Listing Batch.
- [ ] Group by canonical `source_job_id` before limits.
- [ ] Freeze exact deterministic target and every contributing staging-row membership plus cutoff/count under safety cap.
- [ ] Make runtime consume only plan targets and segment within Detail Run Cap.
- [ ] Keep future eligible backlog separate from plan remaining.
- [ ] Cover duplicates, null classifications, listing-batch retention, failures/manual action, resume, and cancellation release.

Rollback point: old detail runtime remains selectable only in test until snapshot parity passes; never run both against the same production backlog.

### 6. Implement preparation/dispatch transactions

- [ ] Add saved-Automation and One-off request variants.
- [ ] Implement readiness, conflict, pacing, headed-worker, catalog, scope, and cap checks.
- [ ] Persist prepared plan without launch.
- [ ] Atomically consume plan into Schedule Execution/Crawl Job/event/outbox and launch after commit.
- [ ] Add scheduled prepare-and-consume path.
- [ ] Add stale catalog/Automation/eligibility/readiness and active-detail-conflict tests.
- [ ] Preserve existing cancellation service and regression tests.
- [ ] Verify publication after run commit does not invalidate the in-flight plan, while pre-dispatch active-revision drift rejects an unconsumed plan.

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
