# Job Intelligence Cutover Operations

## Scenario: Rebuild governed projections without risking the preserved corpus

### 1. Scope / Trigger

Use this contract when changing the Job Intelligence cutover CLI, manifest or
artifact formats, writer quiescence, PostgreSQL backup/restore, destructive
projection rebuild phases, checkpoint recovery, embedding reindexing, runtime
smoke evidence, rollback planning, or writer reopening.

The cutover preserves the Job/Company corpus and raw evidence while rebuilding
only the explicit projection allowlist. It is a trusted-local operator workflow,
not an application startup hook, migration side effect, worker backfill, or live
rollout authorization. A live `jobsdb` execute, publication/activation, corpus
mutation, production smoke, or writer restart requires separate operator
approval outside implementation and disposable-database tests.

### 2. Signatures

The operator commands are:

```text
python backend/scripts/job_intelligence_cutover.py inventory \
  --output <manifest> \
  --application-commit <commit> \
  --application-image <image> \
  --configuration-hash <sha256> \
  --target-schema-revision <revision>

python backend/scripts/job_intelligence_cutover.py dry-run \
  --manifest <manifest> --checkpoint-dir <dir>

python backend/scripts/job_intelligence_cutover.py execute \
  --manifest <manifest> --checkpoint-dir <dir> \
  --backup-id <id> --restore-database-url <distinct *_cutover_restore URL> \
  --confirm-manifest-hash <sha256> --confirm-execute \
  [--runtime-evidence <json>] [--confirm-reopen-writers]

python backend/scripts/job_intelligence_cutover.py verify \
  --manifest <manifest> --checkpoint-dir <dir> \
  [--runtime-evidence <json>]

python backend/scripts/job_intelligence_cutover.py rollback-plan \
  --manifest <manifest> --checkpoint-dir <dir>
```

The orchestration seams are:

```python
JobIntelligenceCutover(environment).inventory(output) -> CutoverManifest
JobIntelligenceCutover(environment).dry_run(
    manifest_path, checkpoint_dir
) -> DryRunReport
JobIntelligenceCutover(environment).execute(
    manifest_path,
    checkpoint_dir,
    backup_id,
    restore_database_url,
    confirm_execute,
    confirm_manifest_hash,
) -> CutoverExecutionResult
JobIntelligenceCutover(environment).verify(
    manifest_path, checkpoint_dir
) -> CutoverVerificationResult
JobIntelligenceCutover(environment).rollback_plan(
    manifest_path, checkpoint_dir
) -> CutoverRollbackPlan

PostgresBackupAdapter.create_and_restore(
    source_database_url,
    restore_database_url,
    backup_id,
    checkpoint_dir,
) -> PostgresBackupArtifact

EmbeddingIndexer.is_current(existing, document) -> bool
EmbeddingIndexer.index(
    db,
    job_id,
    document,
    trigger_event_type,
    crawl_job_id=None,
    source_service="embedding-worker",
) -> EmbeddingIndexResult
```

PostgreSQL integration uses only an explicit disposable URL whose database name
ends in `_test`:

```text
JOB_INTELLIGENCE_TEST_DATABASE_URL=postgresql://.../<dedicated_test>
```

The operator CLI reads its source connection through the application
`DATABASE_URL`. `PostgresBackupAdapter` converts credentials and TLS parameters
to `PG*` environment variables; a URL or password must never appear in the
`pg_dump` / `pg_restore` argument list or persisted artifacts.

Runtime API imports have two distinct seams:

```python
from app.api import router  # full backend API aggregation, loaded lazily
from app.api.retrieval import router as retrieval_router  # isolated sidecar
```

### 3. Contracts

#### Manifest and verified artifacts

- Inventory pins the application commit/image/configuration hash, current and
  target schema, governed release identities, preserved and legacy dataset
  fingerprints, writer inventory, rebuild versions, operator, and reset
  allowlist. Raw descriptions, source payloads, cookies, sessions, and secrets
  are excluded.
- A manifest is canonical JSON plus a SHA-256 over its exact payload. Every
  mutable report/checkpoint uses an envelope containing exactly `payload` and
  `payload_hash`; reads recompute the hash and reject additional or missing
  envelope fields.
- Artifact writes create parent directories mode `0700`, reject a symlink at the
  destination, write a unique mode-`0600` temporary file, `fsync`, and atomically
  replace the destination. Backup dumps are immutable and cannot overwrite an
  existing backup ID.

#### Dry run, quiescence, and backup gates

- `dry-run` performs read-only domain inspections and compares complete before /
  after inventory. Execute accepts only the same manifest's verified report with
  `mode=dry-run` and `mutation_detected=false`.
- Every manifest writer needs one explicit `stopped` observation. Missing,
  unexpected, `running`, or `unknown` evidence fails closed. The database
  sentinel must remain unchanged for at least 30 seconds, relevant outbox count
  must be zero before first execute, and every active-run count must be zero.
- Backup uses PostgreSQL custom format with no owner/privilege restoration. The
  restore target must be different from the source and end in
  `_cutover_restore`. Execute compares every restored preserved fingerprint and
  records the backup ID, artifact SHA-256, client versions, target database, and
  timezone-aware verification time.

#### Ordered checkpoints and recovery

The only valid phase order is:

```text
1  inventory_and_quiesce
2  backup_and_restore_test
3  legacy_audit_snapshot
4  schema_expand_and_seed_revisions
5  rebuild_source_classification_paths
6  rebuild_employment_types
7  rebuild_canonical_job_taxonomy
8  rebuild_company_industries
9  rebuild_skill_state
10 switch_authoritative_reads
11 rebuild_embeddings
12 cross_layer_verify
13 reopen_writers
```

- Each checkpoint pins ordinal, phase, manifest hash, code version, previous
  output hash, status, output, and timezone-aware timing. `completed` requires an
  output hash; `failed` requires a bounded error and completion time; `running`
  cannot pretend to be completed.
- Resume reuses a completed phase only when manifest, code, phase, ordinal, and
  chained input hash all match. A failed phase retries from that phase; a drifted
  artifact requires a new manifest/checkpoint directory.
- Domain progress artifacts are manifest-bound and deterministic. Source,
  Canonical, Company Industry, Skill, and embedding rebuilds must reuse completed
  progress without resetting valid results or duplicating assignments, reviews,
  mentions, audit, or outbox events.
- Reset is limited to `RESET_ALLOWLIST`; no cutover command deletes Jobs,
  Companies, raw evidence, Source Catalog evidence, or unrelated enrichment.
  Phase replay does not drain or delete valid rebuild outbox rows. Only the
  pre-execute quiescence gate requires the relevant outbox to be empty.

#### Rebuild evidence and embedding freshness

- Recovery ports expose preserved Source evidence, company-owned Industry
  evidence, and preserved Skill terms without granting workers human-governance
  decision access. Unsupported evidence becomes a typed empty/Unassigned state
  or an active review with a stable reason; legacy scalar values never become
  automatic governed authority.
- Embeddings start only after active Canonical and Skill targets match the
  manifest. The shared `EmbeddingIndexer` is current only when all four values
  match: document hash, model name, version, and `384` dimensions.
- Phase 11 progress pins manifest, embedding configuration, eligible count,
  stable Job cursor, ready count, and coverage. Resume rejects drift and the
  cross-layer gate requires one fresh embedding for every non-deleted eligible
  Job. Governed documents contain accepted Canonical taxonomy plus active
  governed Skills; pending, generic, rejected, provisional, and legacy values
  remain excluded.

#### Runtime verification and writer reopening

- Runtime smoke evidence is created only after Phase 11 and must pin schema
  version 1, the exact manifest hash/application identity, `status=passed`, a
  timezone-bearing observation time, and exactly five true checks:
  `backend_api`, `embedding`, `frontend`, `governance`, and `search`.
- The expected first execute has no post-rebuild smoke evidence and therefore
  pauses fail-closed at Phase 12. The operator supplies evidence to `verify`,
  then resumes execute; completed phases are not replayed.
- Phase 13 also fails closed unless cross-layer verification for the same
  manifest is recorded and an explicit writer-control adapter was injected by
  `--confirm-reopen-writers`. This second confirmation is separate from
  `--confirm-execute`.
- Writer control starts only persistent Compose services, probes the complete
  writer inventory, rejects missing/unknown evidence, and requires all expected
  persistent writers to be running. Manual helpers and Source Catalog admin
  remain transient.
- Current Compose application images are not operator images: `backend-api`
  lacks the embedding runtime and PostgreSQL clients, while ML images still lack
  PostgreSQL clients and Docker control. Run from a verified trusted host; do
  not mount Docker-daemon authority into the public API container.
- `app.api` must remain import-light. Its public `router` export lazily loads the
  full backend aggregation, while retrieval/recommendation entrypoints import
  only their sidecar router. Eagerly importing every production route from the
  package initializer makes the trimmed ML runtime depend on crawl/scheduler
  packages and can pass host tests while failing container startup.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Manifest payload hash differs | `ManifestIntegrityError`; no session or mutation |
| Dry-run report missing, wrong-manifest, wrong mode, or mutated | `CUTOVER_DRY_RUN_REQUIRED` / `CUTOVER_DRY_RUN_INVALID` |
| Execute flag or exact manifest-hash confirmation missing | `CUTOVER_EXECUTION_UNCONFIRMED` / `CUTOVER_MANIFEST_CONFIRMATION_MISMATCH` |
| Backup ID is unsafe or restore URL is absent/non-PostgreSQL/same DB/not `*_cutover_restore` | Reject before dump or destructive phase |
| Writer is running/unknown/missing/unexpected | `CUTOVER_WRITERS_NOT_QUIESCENT` |
| Sentinel changes or observes less than 30 seconds | `CUTOVER_DATABASE_NOT_QUIESCENT` |
| Pre-execute outbox or active run remains | `CUTOVER_OUTBOX_NOT_DRAINED` / `CUTOVER_ACTIVE_RUNS_PRESENT` |
| Restored fingerprint or backup identity differs | `CUTOVER_BACKUP_RESTORE_MISMATCH` |
| Checkpoint/progress manifest, code, phase, ordinal, input hash, or rebuild configuration drifts | Fail closed; require matching resume or a new artifact directory |
| Job lacks Canonical assignment/review or current embedding tuple | Cross-layer verification fails; writers stay stopped |
| Runtime evidence is absent, stale, false, incomplete, or belongs to another application/manifest | Phase 12 fails; no writer control |
| Cross-layer record missing or writer control not explicitly injected | Phase 13 fails; no service restart |
| Writer restart returns unknown/incomplete state or a persistent writer is not running | Reopen fails and records no successful Phase 13 checkpoint |
| Retrieval entrypoint imports the production root router or its crawl modules | Runtime image import/health check fails; rollout is not complete |

### 5. Good / Base / Bad Cases

- **Good:** an operator creates inventory and zero-write dry-run artifacts,
  proves quiescence, restores and fingerprints a custom-format backup, rebuilds
  through embeddings, supplies post-rebuild smoke evidence, verifies, and only
  then makes a separate confirmed resume that reopens writers.
- **Base:** Phase 12 fails because runtime evidence does not exist yet. Phases
  1-11 remain completed; after valid evidence arrives, resume starts at Phase 12
  and Phase 13 remains blocked until independently confirmed.
- **Base:** a process/container probe cannot observe Docker or returns an
  ambiguous state. Every affected writer is `unknown`; execution stops instead
  of treating absence as stopped.
- **Bad:** run the CLI inside `backend-api`, point a test/rehearsal variable at
  `jobsdb`, fabricate runtime evidence before embeddings, use a legacy scalar as
  governed authority, or automatically inject writer control on every execute.
- **Bad:** clear valid rebuild outbox rows to make checkpoint replay appear
  idempotent. Outbox uniqueness/count assertions must prove replay instead.
- **Good:** importing `app.retrieval_main` leaves production crawl route modules
  unloaded, and the built ML image passes both import and `/health` probes.
- **Bad:** add crawl/scheduler dependencies one at a time to the ML image to
  mask an eager package import. This expands the image without restoring the
  intended service boundary.

### 6. Tests Required

- `test_job_intelligence_cutover.py`: manifest/artifact tamper and permission
  checks; zero-write dry run; unsafe restore/backup rejection; quiescence and
  unknown-writer failures; subprocess argv/environment secrecy; runtime evidence
  validation; explicit writer adapter; checkpoint corruption and failure/resume
  injection for phases 3-13; CLI default safety and confirmation flags.
- `integration/test_job_intelligence_rebuild.py` plus the anonymized legacy
  fixture: execute all domain rebuilds on an explicit PostgreSQL `*_test`
  database; assert preserved fingerprints, explicit Canonical review reasons,
  company-owned evidence policy, governed Skill outcomes, embedding four-tuple,
  cross-layer verification, writer-control call, phase replay equality, and the
  exact non-duplicated outbox count.
- Rehearse the real `pg_dump` / `pg_restore` adapter against a disposable
  `_test` source and distinct `_cutover_restore` target. Record client versions,
  dump SHA-256, and restored marker/fingerprints; remove the disposable data and
  never connect the rehearsal to `jobsdb`.
- Run affected domain suites, the complete backend test directory, targeted
  Ruff/Black/mypy/compileall, and frontend lint/test/build. Backend/frontend
  fixture-copy checks must see the committed frontend fixture and may not be
  skipped because a container mount is missing.
- Live execute, activation, production smoke, and writer reopening are not test
  commands. They remain separately approved runbook operations.
- `test_service_entrypoint_imports.py`: import the retrieval entrypoint in a
  fresh Python subprocess and assert the production crawl router is absent from
  `sys.modules`; the built retrieval image must also import the entrypoint and
  report healthy before target-environment semantic search is accepted.

### 7. Wrong vs Correct

#### Wrong: treat execute as one automatically authorized transaction

```python
environment = PostgresCutoverEnvironment(
    ...,
    writer_control=SystemWriterControl(),
)
cutover.execute(...)  # fabricated pre-rebuild smoke file already present
```

This erases the independent runtime-evidence and writer-reopen decisions and can
grant Docker control before the rebuilt state has been observed.

#### Correct: make verification and reopening separate resumable gates

```text
inventory -> dry-run -> quiesce -> execute (expected Phase 12 pause)
          -> post-Phase-11 smoke -> verify
          -> execute (Phase 12 completes; expected Phase 13 pause)
          -> separate approval + --confirm-reopen-writers -> execute resume
```

The same manifest/checkpoint chain proves every completed phase, while runtime
evidence and writer control become available only at their own explicit gates.

#### Wrong: make every API submodule load the full production router

```python
# app/api/__init__.py
from app.api import crawl_control, jobs, retrieval
```

Importing `app.api.retrieval` executes the package initializer first, so the
trimmed retrieval image inherits unrelated crawl and scheduler dependencies.

#### Correct: lazily expose the production root router

```python
def __getattr__(name: str):
    if name == "router":
        from app.api.root_router import router

        return router
    raise AttributeError(name)
```

Sidecar submodules can then import without loading the production aggregation;
the full backend keeps the stable `from app.api import router` interface.
