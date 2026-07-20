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

- [x] Add versioned routes/schemas and stable machine error codes.
- [x] Return current revision on conflict and forbid implicit merge.
- [x] Add normalized Task Control Board, Automation row, run, workload, and detail snapshot projections.
- [x] Add normalized fallback fields to Crawl Tasks/Logs so new control UI and post-cutover history never need raw request/event parsing.
- [x] Make legacy schedule routes delegate temporarily; stop new writes of `category_ids`.
- [x] Add contract tests that frontend never needs raw request/event decoding.

Checkpoint 7 adds the versioned Crawl Scope, Automation, Dispatch Plan, and
Task Control Board HTTP contracts; compare-and-swap revision headers; normalized
plan-backed listing/detail/recovery projections; and temporary legacy Schedule
delegation that never writes primitive scope fields for versioned rows. Mixed
configuration/lifecycle compatibility updates fail before mutation, Dispatch
confirmation requires the reviewed fingerprint, and unsupported Source/Catalog
failures remain structured.

Verification covered the 16 API contract tests, 59 focused Automation/Dispatch
Plan/snapshot regressions with three skips, and the full backend suite
(`384 passed, 155 skipped`). Touched-file Ruff, focused mypy, compileall, and
`git diff --check` passed.

### 8. Integrate catalog impact/publication

- [x] Provide the real `CatalogImpactEvaluator` to child 1's catalog module.
- [x] Test label/move compatible changes, future descendant inclusion, removed/query-changed nodes, alias dedup changes, and cap overflow.
- [x] Mark incompatible Automations `scope_review_required` in publication/rollback transaction.
- [x] Exercise explicit initial revision publication with legacy-reset warning in staging.

Checkpoint 8 supplies the production Automation impact evaluator to both the
Source Catalog API and operator CLI. Reviews now contain deterministic per-
Automation before/after scope and workload projections; mutation-time digest
revalidation fences the complete Automation set; and publish/rollback append
the `scope_review_required` Automation revision in the same transaction as the
active catalog pointer and publication audit. Initial publication remains
explicit and reports legacy Crawl Control rows requiring the approved reset.

Verification covered 30 focused scope/lifecycle/catalog-impact regressions,
10 Source Catalog API/service/integration tests, and the full backend suite
(`387 passed, 155 skipped`). Touched-file Ruff, focused mypy, compileall, and
`git diff --check` passed.

Checkpoint: every Source has one active validated revision before cutover rehearsal.

### 9. Build migration and cutover tooling

- [x] Keep ORM metadata canonical for fresh `create_all`; use one migration/convergence path for existing DB and avoid duplicate ad-hoc DDL for these tables.
- [x] Test schema parity for fresh bootstrap, upgraded current-schema fixture, and a metadata-created fixture despite the incomplete baseline.
- [x] Implement maintenance preflight: service/process state, actual FKs, backup acknowledgement, preserve/reset counts.
- [x] Implement dry-run count report and FK-safe reset script scoped to crawl outbox rows.
- [x] Add transaction failure injection and preserve-count assertions.
- [x] Rehearse backup/restore and fresh DB bootstrap on disposable databases.
- [x] Update `.gitignore` so all new migration/test artifacts are tracked.

Checkpoint 9 replaced startup's ad-hoc convergence DDL with an explicit
fresh-metadata/stamped-Alembic flow and adds head `20260720_210000`. The head
converges the historical staging FK plus Source Catalog, Automation, and
Dispatch Plan PostgreSQL guards; only a transaction-local maintenance setting
permits the reviewed reset to break immutable authority links. Non-empty
unstamped databases fail closed pending operator lineage verification.

`CrawlControlCutover` inventories real FK delete rules, all application table
counts, active Catalogs, active Crawl Jobs, the shared service/process writer
probe, and an acknowledged backup identity. Its reviewed-report hash fences an
atomic reset that deletes only pending crawl outbox rows and Crawl Control data,
handles the Dispatch Plan/Crawl Job FK cycle, and asserts every dynamically
discovered preserve-table count before commit. Failure injection proves the
whole reset rolls back. The operator CLI keeps dry-run, reset confirmation, and
disposable backup rehearsal separate.

Verification used disposable `crawl_control_cp9_test` and
`crawl_control_cp9_cutover_restore` databases only. Fresh bootstrap, existing
`20260720_180000` downgrade/upgrade convergence, trigger/FK/index parity, the
FK-safe seeded reset, outbox scoping, preservation, and injected rollback all
passed (`9 passed`). A real custom-format `pg_dump`/`pg_restore` rehearsal
matched non-zero counts for Jobs, Companies, Crawl Control, three Source
Catalog revisions, enrichment, and outbox rows; artifact SHA-256 was
`4c628a8baf1a9a733dd0176b15ba6a025db0b4d32eabb58e8f0715f460d6bff6`.
Focused regressions passed (`114 passed, 6 skipped`) and the full backend suite
passed once (`394 passed, 158 skipped`). Touched Ruff, focused mypy,
compileall, migration-head offline SQL, real downgrade/upgrade, and
`git diff --check` passed. This was the pre-rollout checkpoint; the separately
approved live execution and acceptance evidence are recorded below.

### 10. Perform approved cutover

- [x] Identify the live unstamped schema's candidate lineage as `20260718_120000` using read-only table/column/index evidence; record the fail-closed proof in `research/live-schema-lineage-preflight.md`.
- [x] Obtain user/operations approval for maintenance execution; planning approval alone is not production cutover approval.
- [x] Before touching live schema, restore the approved backup to a distinct `*_cutover_restore` database, stamp the clone at `20260718_120000`, upgrade it to `20260720_210000`, and require schema/FK/trigger/preserve-count parity.
- [x] Stop scheduler/workers/outbox/API mutations and verify no external crawl remains.
- [x] Take backup and record preflight report.
- [x] Run reset transaction/script.
- [x] Verify preserved corpus/taxonomy/enrichment/catalog counts and FKs.
- [x] Restart services and create one bounded smoke Automation/One-off plan per Source.
- [x] Keep backup until full acceptance.

The user approved the exact phrase `批准执行 CP10 live rollout`. Live schema
`jobsdb` reached `20260720_210000`; backup
`jobsdb-crawl-control-20260720T144720Z-3a2fd136` has SHA-256
`1d1b4274c5c4e4f421269e29028e03a2ebb498d9c61d3fa2d7b6f4849a856280`.
The fenced ready report (`payload f2a14311...`, `report 9186c6c5...`) and reset
(`payload 438b1c52...`) preserved 17,596 Jobs, 4,657 Companies, 8 enrichment
runs, 4,042 embeddings, three published Catalog Revisions, and 10,310 unrelated
outbox rows. Post-reset SQL independently confirmed the counts, schema, and the
validated listing FK with `ON DELETE CASCADE`.

JobsDB (`jobsdb:6281`) and CTgoodjobs (`ctgoodjobs:021`, headed) completed their
one-target, one-page smoke plans. OfferToday consumed the immutable exact
`offertoday:118000` plan, reported truthful `manual_action_required/ip_blocked`,
and was cancelled through `crawl.cancel_requested -> crawl.cancelled` without
an IP bypass, retry, categoryless query, or detail crawl. All five non-terminal
Crawl Job status totals are now zero, and the six persistent services are
running. Full evidence is indexed in
`evidence/cp10-live-rollout-20260720.md`; the backup remains retained through
the rollback window.

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

- [x] After finite membership/cap, normalized metrics, cancellation/recovery, and cross-source runtime tests pass, review and update `.trellis/spec/backend/offertoday-production-crawl.md`.
- [x] Under the same verified gate, update `.trellis/spec/backend/crawl-task-detail-metrics.md`.
- [x] Update affected frontend snapshot/pacing contracts only after the backend behavior and spec review pass.
- [x] Preserve logging and cancellation specs.

Checkpoint 11 contract convergence is complete. It records finite
plan-owned detail membership, complete-run caps, normalized snapshot-versus-
future metrics, and unchanged recovery/cancellation authority without modifying
the dedicated logging or cancellation specs. The separately approved CP10 live
evidence is now complete and linked above, so this child may proceed through its
single final Trellis check and archive gate without reopening the already passed
backend suites.

## Rollback points

- Before cutover: revert code/migrations normally; existing data remains.
- During reset transaction: rollback immediately on any preserve-count/FK failure.
- After reset commit: restore the pre-cutover backup and compatible application image.
- A stale/failed Dispatch Plan never falls back to dynamic scope/backlog; the safe rollback is to require a fresh plan.
