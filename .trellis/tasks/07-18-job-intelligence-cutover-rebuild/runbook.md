# Job Intelligence cutover and rebuild runbook

## Status and authority

This runbook prepares and rehearses the controlled cutover. It does not grant
approval to execute against the live `jobsdb` database. Live execution,
publication, activation, corpus mutation, writer shutdown, and writer reopening
require a separate operator approval after the go/no-go checklist is complete.

The only approved automated rehearsal database names end in `_test`; restore
targets must be distinct and end in `_cutover_restore`.

## Hard stops

Stop immediately if any of the following is true:

- the manifest database, application image, commit, configuration hash, schema,
  governed seed, or preserved fingerprint differs from the reviewed value;
- any writer is `running` or `unknown`, the 30-second database sentinel changes,
  an active run exists, or the pre-cutover outbox is not drained;
- PostgreSQL backup/restore tooling is unavailable or the disposable restore
  fingerprints differ;
- a checkpoint or progress artifact fails its SHA-256 envelope check;
- a Job lacks both a current Canonical assignment and an explicit active review;
- an eligible Job lacks a fresh embedding for the pinned model/version/dimension;
- runtime smoke evidence is missing, pre-dates the rebuilt state, or contains a
  failed/unknown check;
- writer reopening lacks a second explicit confirmation or returns unknown state.

Never use Alembic downgrade as the data rollback mechanism. Never delete the
legacy columns during this cutover window.

## Operator prerequisites

- Run from a trusted operator environment with Python project dependencies,
  `pg_dump` and `pg_restore` compatible with PostgreSQL 15, and Docker Compose
  access when system writer probing/reopening is requested.
- Supply database credentials only through `DATABASE_URL` / PostgreSQL
  environment variables. Do not put passwords in command arguments or artifacts.
- Pre-create the explicit disposable restore database. It must not be `jobsdb`.
- Verify sufficient disk space for a custom-format dump and all checkpoint files.
- Confirm the pinned embedding model is locally available before execute.

The current Compose images are not cutover operator images. `backend-api` does
not include the embedding runtime or PostgreSQL client binaries, while the ML
images do not include PostgreSQL clients or Docker Compose control. Run the CLI
from a verified trusted host unless a separately reviewed operator image is
introduced; do not grant the public API container Docker-daemon access.

Tool check:

```bash
pg_dump --version
pg_restore --version
docker compose config --services
```

## Artifact directory

Use one new directory per manifest. Never reuse a checkpoint directory for a
different manifest or code commit.

```bash
export CUTOVER_DIR="runtime/job-intelligence-cutover/20260720T090000Z"
mkdir -p "$CUTOVER_DIR"
chmod 700 "$CUTOVER_DIR"
```

Expected artifacts include:

- `manifest.json`
- `dry-run-report.json`
- `quiescence-report.json`
- `<backup-id>.dump`
- `backup-verification.json`
- `legacy-audit.jsonl` and `legacy-audit-manifest.json`
- `01-*.json` through `13-*.json`
- per-domain progress files
- `runtime-smoke-evidence.json`
- `cross-layer-verification.json`, `verify-report.json`
- `execute-state.json` and `rollback-plan.json`

## 1. Inventory

Set the reviewed release identity. Do not guess these values.

```bash
python backend/scripts/job_intelligence_cutover.py inventory \
  --output "$CUTOVER_DIR/manifest.json" \
  --application-commit "$APPLICATION_COMMIT" \
  --application-image "$APPLICATION_IMAGE" \
  --configuration-hash "$CONFIGURATION_SHA256" \
  --target-schema-revision "$TARGET_ALEMBIC_REVISION"
```

Review the manifest envelope and record its `manifest_hash`. It deliberately
contains no password, raw description, cookie, session, or source payload.

## 2. Zero-write dry run

```bash
python backend/scripts/job_intelligence_cutover.py dry-run \
  --manifest "$CUTOVER_DIR/manifest.json" \
  --checkpoint-dir "$CUTOVER_DIR"
```

Proceed only when `mutation_detected=false`, the before/after preserved
fingerprints are identical, and all five domain inspections are present.

## 3. Quiesce and drain

Before the first execute attempt:

1. Drain the existing outbox.
2. Finish/cancel active crawl and enrichment runs.
3. Stop API, scheduler, ingest, enrichment, embedding, Scrapyd, manual helpers,
   source-catalog admin processes, and any external publisher.
4. Confirm the system writer probe reports every manifest writer as `stopped`.
5. Keep the database stable for the full 30-second sentinel window.

The CLI does not infer safety from a missing process. Probe failure is `unknown`
and blocks execute.

## 4. First execute attempt: rebuild through Phase 11

Use a newly created backup ID and an explicit disposable restore URL. The
restore database name must end in `_cutover_restore`.

```bash
export MANIFEST_HASH="$(jq -r '.manifest_hash' "$CUTOVER_DIR/manifest.json")"

python backend/scripts/job_intelligence_cutover.py execute \
  --manifest "$CUTOVER_DIR/manifest.json" \
  --checkpoint-dir "$CUTOVER_DIR" \
  --backup-id "$BACKUP_ID" \
  --restore-database-url "$RESTORE_DATABASE_URL" \
  --confirm-manifest-hash "$MANIFEST_HASH" \
  --confirm-execute
```

Without post-rebuild runtime smoke evidence, the expected safe outcome is a
fail-closed pause at `cross_layer_verify` after the completed embedding phase.
The failed Phase 12 checkpoint is resumable; completed phases are not replayed.

## 5. Post-rebuild runtime smoke evidence

Run the reviewed smoke matrix against the rebuilt, still-quiesced environment or
its exact restored clone:

- backend governed response/API contract smoke;
- governance assignment/review/decision read smoke;
- Job search/filter/recommendation smoke using governed projections;
- embedding metadata/document/retrieval smoke;
- frontend governance, Job Browser/Detail/Company/Dashboard tests and build.

Create a JSON object only after all checks pass:

```json
{
  "schema_version": 1,
  "manifest_hash": "<exact manifest hash>",
  "application": {
    "commit": "<exact manifest commit>",
    "image": "<exact manifest image>",
    "configuration_hash": "<exact manifest configuration hash>"
  },
  "status": "passed",
  "checks": {
    "backend_api": true,
    "embedding": true,
    "frontend": true,
    "governance": true,
    "search": true
  },
  "observed_at": "<UTC timestamp after Phase 11>"
}
```

Then verify and hash-wrap the evidence:

```bash
python backend/scripts/job_intelligence_cutover.py verify \
  --manifest "$CUTOVER_DIR/manifest.json" \
  --checkpoint-dir "$CUTOVER_DIR" \
  --runtime-evidence "$RUNTIME_EVIDENCE_JSON"
```

## 6. Resume without reopening

Resume execute without a writer-reopen confirmation first. This proves Phase 12
can complete while Phase 13 remains blocked by the absent writer-control adapter.

```bash
python backend/scripts/job_intelligence_cutover.py execute \
  --manifest "$CUTOVER_DIR/manifest.json" \
  --checkpoint-dir "$CUTOVER_DIR" \
  --backup-id "$BACKUP_ID" \
  --restore-database-url "$RESTORE_DATABASE_URL" \
  --confirm-manifest-hash "$MANIFEST_HASH" \
  --runtime-evidence "$RUNTIME_EVIDENCE_JSON" \
  --confirm-execute
```

## 7. Separately approved writer reopening

Only after a fresh operator decision and a fully checked go/no-go sheet, resume
with the second confirmation:

```bash
python backend/scripts/job_intelligence_cutover.py execute \
  --manifest "$CUTOVER_DIR/manifest.json" \
  --checkpoint-dir "$CUTOVER_DIR" \
  --backup-id "$BACKUP_ID" \
  --restore-database-url "$RESTORE_DATABASE_URL" \
  --confirm-manifest-hash "$MANIFEST_HASH" \
  --runtime-evidence "$RUNTIME_EVIDENCE_JSON" \
  --confirm-execute \
  --confirm-reopen-writers
```

The controller starts only the persistent Compose services, probes all known
writers, and fails if any state is unknown or a required persistent writer did
not become running. Manual helper and source-catalog admin remain transient.

## 8. Rollback plan

Generate the immutable plan at any time after backup verification:

```bash
python backend/scripts/job_intelligence_cutover.py rollback-plan \
  --manifest "$CUTOVER_DIR/manifest.json" \
  --checkpoint-dir "$CUTOVER_DIR"
```

Rollback execution remains deliberately manual and separately approved:

1. stop all current services;
2. restore the recorded verified backup into the approved target;
3. deploy the recorded previous application image/configuration;
4. verify legacy health and preserved fingerprints;
5. reopen the previous writer set.

Prefer checkpoint resume before the authoritative read switch. After the read
switch or any widespread post-reopen writes, restore the backup instead of
attempting reverse translation.

## Rehearsal evidence (2026-07-20)

- Source: `job_intelligence_product_surfaces_test`
- Disposable target: `job_intelligence_cutover_restore`
- PostgreSQL clients: 15.18
- Custom dump SHA-256:
  `cc5ef184fb80ebcefcb9d17e0bc2e456d846fb6bf72e6a601ed9ba9b48614a79`
- Restored marker: `1|anonymized-rehearsal`
- Source marker, restore database, and temporary dump were removed afterward.
- No command connected to or mutated `jobsdb`.

Automated checkpoint failure injection covers phases 3 through 13 and proves
resume begins at the failed phase without replaying completed checkpoints.
