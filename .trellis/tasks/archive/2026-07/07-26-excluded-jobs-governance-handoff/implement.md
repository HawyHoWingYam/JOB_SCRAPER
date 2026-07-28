# Implementation plan

## Delivery structure

The current task is the parent/integration task. Implement child tasks in the
order below; do not start the parent as a monolithic implementation target.

1. Ordinary Source classifications and top-level crawl scope.
2. Ordinary Job/Company/Skill taxonomy data and optional mappings.
3. Unversioned application protocols, Automation state, and schema bootstrap.
4. Automated classification batches and Skill threshold Settings.
5. One-time retained-data cutover, task/queue reset, and full integration.

Each child must finish its own focused tests and keep a compatibility adapter
only until the next dependent child lands. The final child deletes all temporary
bridges and runs the forbidden-version architecture gate.

## Step 1: Freeze the cutover contract

- Inventory every retained table/field and every deleted task/version table.
- Define stable ordinary IDs and old-to-new maps for Source, Canonical Job,
  Company Industry, Skill, mappings, assignments, evidence, and embeddings.
- Build retention manifest fixtures from a disposable populated PostgreSQL DB.
- Add a failing architecture inventory that enumerates all production
  application-owned version/release interfaces to be removed.
- Rollback point: planning/test artifacts only; no runtime change.

## Step 2: Ordinary Source classifications

- Add the ordinary Source Classification Registry schema and deep module.
- Update JobsDB, OfferToday, and CTgoodjobs adapters to synchronize top-level
  classifications and compile direct/broader query strategies.
- Remove catalog revision identity from Source Job Attribute projection/path
  persistence and preflight.
- Simplify authored/resolved crawl scope and dispatch contracts to all/selected
  top-level IDs.
- Remove Source Catalog pages/API/modules/specs and provenance repair.
- Verify cross-source sync, inactive retention, label update, child evidence,
  crawl choices, query/fallback, and non-blocking AI preflight.
- Rollback point: ordinary registry populated alongside legacy catalog until
  focused parity tests pass; delete the bridge before completing this child.

## Step 3: Flatten current taxonomies and mappings

- Create ordinary stable Canonical Job, Company Industry, Skill, alias, mapping,
  assignment, projection, Candidate, and Mention schemas.
- Write fixture-level transforms from current active release rows to ordinary
  rows; remap accepted business references.
- Change reads/filters/embedding documents/AI constraints to current ordinary
  stores.
- Make Source mappings optional and missing coverage non-blocking.
- Delete release/active-pointer/coverage/publisher/materializer tables/modules,
  revision-pinned FKs, review queues, and version-specific APIs/tests/specs.
- Verify exact current taxonomy counts/hierarchy, stable IDs/codes, assignments,
  audit/evidence preservation, and full-taxonomy fallback.
- Rollback point: transform tests must pass from committed fixtures before any
  destructive local DB action.

## Step 4: Remove remaining application protocols

- Collapse `/api/v1` and version-selected response shapes to one root API.
- Remove event/payload/projection schema versions and update all producers,
  consumers, fixtures, and frontend decoders atomically.
- Replace Automation revision snapshots/ETags/expected revision/delete review
  contracts with current-row last-write-wins transactions.
- Remove embedding model/version columns and freshness logic; add explicit full
  index reset/rebuild operation.
- Replace Alembic with one current empty-database schema bootstrap; include
  extensions, constraints, indexes, and required triggers.
- Delete Alembic versions/config/runtime entrypoints and update developer/ops
  documentation for destructive schema rebuilds and atomic deployments.
- Verify root API, event round trips, stale-form last-write-wins, dispatch current
  scope, embedding preservation/reset, empty DB bootstrap, and non-empty refusal.

## Step 5: Automated classification batches

- Extract/deepen the shared batch orchestration interface from AI Enrichment
  behavior without coupling domain selection logic.
- Add Job Taxonomy, Company Industry, and Skill candidate adapters.
- Add filtered batch pages with preview/start/progress/stop/retry/failure and
  optional individual correction deep links.
- Remove Job Intelligence Governance navigation/pages/decoders/actions.
- Add persisted Settings threshold for Skill auto-create, default five distinct
  Jobs.
- Implement duplicate/alias/generic validation, AI placement into existing Skill
  Category/Technology, automatic creation, and unresolved failure.
- Verify all domain adapters plus frontend interaction/accessibility tests.

## Step 6: One-time sandbox cutover

- Implement `export_retained`, `create_target_schema`, `import_retained`,
  `verify_retention`, and `clear_runtime_state` operator commands.
- Prove commands refuse unsafe process/DB state and never treat Jobs/Companies as
  cleanup roots.
- Exercise the complete sequence on a disposable production-shaped fixture,
  including cyclic RESTRICT task references and Redis pending entries.
- Stop the local stack, export the agreed retained sandbox data, clear runtime
  state, destroy/recreate the DB, import, and verify.
- Delete the transient export only after all manifests and smoke checks pass.
- Start the entire target application atomically.
- Verify no old task/version command resumes and all retained business surfaces
  load.

## Final deletion gate

- Search production code/schema/frontend/specs for application-owned:
  `revision`, `release`, `active_revision`, `lock_version`, `expected_version`,
  `schema_version`, `embedding_version`, `/api/v1`, Source Catalog publication,
  rollback, provenance repair, and Governance queue symbols.
- Maintain a narrow allowlist only for third-party dependency/runtime/model
  release identifiers and ordinary words in historical research artifacts.
- Delete all temporary bridges, compatibility routes, stale fixtures, generated
  artifacts, and the transient cutover export.

## Validation commands

Exact test filenames will evolve with the target modules, but every child and the
final integration must run the repository's current equivalents of:

```bash
python3 -m compileall -q backend/app backend/scripts backend/tests
docker compose exec backend-api pytest -q <focused backend files>
docker compose exec backend-api pytest -q backend/tests
npm --prefix frontend run lint
npm --prefix frontend test -- --run
npm --prefix frontend run build
python3 ./.trellis/scripts/task.py validate <active-child>
```

Final cutover validation additionally runs:

```bash
python3 backend/scripts/bootstrap_current_schema.py --check-empty
python3 backend/scripts/cutover_unversioned_state.py export --verify
python3 backend/scripts/cutover_unversioned_state.py import --verify
python3 backend/scripts/verify_unversioned_architecture.py
```

Command names above specify the required interfaces; implementation may choose
different filenames only if `design.md` and this plan are updated before coding.

## Review gates

- Do not run destructive cutover against the shared sandbox until the complete
  disposable integration fixture passes twice from a clean start.
- Do not delete a legacy module until its target caller and retained-data
  transform are tested.
- Do not start mixed old/new services after route/event version removal.
- Return to planning if retained business identities cannot be mapped without
  ambiguity or if a required PostgreSQL object cannot be represented by the
  current schema bootstrap.
