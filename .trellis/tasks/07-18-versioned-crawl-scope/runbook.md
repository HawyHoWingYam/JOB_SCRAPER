# Versioned Crawl Control live rollout runbook

## Status and authority

**Execution status (2026-07-20): completed.** The user supplied the required
approval, and this runbook was executed against live `jobsdb`. The immutable
release identity, backup/reset hashes, published revisions, bounded smokes,
acknowledged cancellation, and post-rollout verification are indexed in
`evidence/cp10-live-rollout-20260720.md`.

This document remains the procedure and does not authorize a future rerun,
replacement backup, new Catalog publication, or another destructive reset. Any
new execution requires a fresh release identity and approval.

The required approval phrase is:

```text
批准执行 CP10 live rollout
```

That approval covered this runbook only. It did not approve the separate Job
Intelligence live rebuild/writer reopening. The three Crawl Control frontend
tasks retained their own review gate and were authorized separately after this
rollout.

The Alembic chain is linear. Upgrading from the observed candidate lineage
`20260718_120000` to head also creates the additive Job Intelligence schema.
It does **not** publish governed seeds, activate pointers, rebuild projections,
backfill the corpus, switch reads, rebuild embeddings, or reopen Job
Intelligence writers. The operator must acknowledge this additive schema scope
when approving CP10.

## Hard stops

Stop immediately if any of the following is true:

- the database, application commit/image/configuration, target Alembic revision,
  backup ID, or restored-backup hash differs from the reviewed value;
- the live schema no longer matches
  `research/live-schema-lineage-preflight.md`;
- the restored clone cannot be stamped at `20260718_120000`, upgraded to
  `20260720_210000`, and verified before the live stamp;
- any known writer is `running` or `unknown`, an external Scrapyd/local crawl
  remains, or any Crawl Job lacks terminal acknowledgement;
- any Source lacks one reviewed, validated, active Catalog Revision;
- the dry-run artifact is not `ready=true`, its SHA-256 envelope is invalid, or
  its report hash/counts/FKs differ when reset obtains its locks;
- backup creation or restore verification is unavailable;
- a Catalog validation is failed/manual-action-required, an impact review is
  stale, or the reviewed candidate fingerprint changes;
- reset changes a preserved table or published/unrelated outbox count;
- any bounded post-restart smoke is failed, unbounded, or uses a different
  Catalog Revision/plan fingerprint than the reviewed one.

Never run `backup-rehearsal` against live: that command accepts only a source
database ending in `_test`. Never use Alembic downgrade to recreate deleted
Crawl Control history. Never delete or edit an immutable Catalog Revision.

## Operator prerequisites

- Work from a trusted local operator host with project dependencies,
  PostgreSQL 15-compatible `pg_dump`/`pg_restore`, `curl`, `jq`, and Docker
  Compose access.
- Keep credentials in `DATABASE_URL` or PostgreSQL environment variables; do
  not place passwords in command arguments, copied logs, or artifacts.
- Pin and record the exact application commit/image/configuration and target
  revision `20260720_210000`.
- Use a new artifact directory and backup ID. Never reuse a reviewed report for
  a later database state.
- The restore target must be a distinct disposable database ending in
  `_cutover_restore`; it must never be `jobsdb`.

Example artifact setup (values are operator-reviewed inputs, not defaults):

```bash
export CUTOVER_DIR="runtime/crawl-control-cutover/<UTC-release-id>"
export BACKUP_ID="<immutable-backup-id>"
export TARGET_ALEMBIC_REVISION="20260720_210000"
export API_BASE="http://127.0.0.1:8000/api/v1"
mkdir -p "$CUTOVER_DIR"
chmod 700 "$CUTOVER_DIR"
```

Expected retained artifacts:

- release identity and approval record;
- custom-format backup plus SHA-256 and disposable restore evidence;
- lineage/stamp/upgrade/schema-parity report from the restored database;
- per-Source discovery, validation, impact review, and publication evidence;
- `crawl-control-dry-run.json` and its payload/report hashes;
- `crawl-control-reset.json`;
- preserved-count/FK verification;
- per-Source plan/fingerprint/runtime smoke evidence;
- rollback decision and final acceptance record.

## 1. Record approval and release identity

Record the exact approval message, actor, UTC time, database target, commit,
image, configuration hash, migration target, backup ID, maintenance window, and
rollback owner. If any value is missing, status remains NO-GO.

Run tool checks without connecting to the database:

```bash
pg_dump --version
pg_restore --version
docker compose config --services
git rev-parse HEAD
```

## 2. Prevent new work and obtain cancellation acknowledgement

Stop the scheduler and crawl executor first so no new Crawl Job starts, while
keeping the trusted-local API available for cancellation:

```bash
docker compose stop scheduler-worker scrapyd
```

Cancel every non-terminal manual Crawl Job through the existing acknowledged
cancellation contract. The observed 162 queued and 13 manual-action jobs are
manual/no-Schedule jobs; queued jobs acknowledge immediately when no execution
exists. Re-query after every batch instead of trusting the old count.

```bash
for status in queued dispatching running cancelling manual_action_required; do
  while true; do
    ids="$(curl --fail --silent --show-error \
      "$API_BASE/crawl-jobs/tasks?status=$status&page=1&page_size=100&time_range=all" \
      | jq -r '.items[].crawl_job_id')"
    test -n "$ids" || break
    while IFS= read -r crawl_job_id; do
      test -n "$crawl_job_id" || continue
      curl --fail --silent --show-error -X POST \
        "$API_BASE/crawl-jobs/$crawl_job_id/cancel" >/dev/null
    done <<<"$ids"
  done
done
```

If a task remains `running`/`cancelling`, confirm the execution process stopped
and wait for `cancelled`; do not rewrite status directly. A Schedule-backed task
or unknown external process is a hard stop requiring separate resolution.

## 3. Stop all writers and take the pre-migration backup

Stop persistent application writers and explicitly terminate transient manual
action/source-catalog admin processes. Keep PostgreSQL running.

```bash
docker compose stop \
  backend-api scheduler-worker ingest-worker enrichment-worker \
  embedding-worker scrapyd
```

Confirm there is no `app.workers.run_manual_action_helper`,
`source_catalog_admin`, external publisher, local crawler, or unmanaged Scrapyd
process. Missing/unobservable evidence is `unknown`, not `stopped`.

Create one custom-format backup using PostgreSQL environment variables, record
the file SHA-256, and restore it to the reviewed distinct
`*_cutover_restore` database. Do not proceed merely because `pg_dump` exited
zero; the restored schema and preserved table counts must match.

```bash
export BACKUP_PATH="$CUTOVER_DIR/$BACKUP_ID.dump"
pg_dump --format=custom --no-owner --no-acl \
  --file "$BACKUP_PATH" "$PGDATABASE"
shasum -a 256 "$BACKUP_PATH"

createdb "$RESTORE_DATABASE_NAME"
pg_restore --clean --if-exists --single-transaction \
  --dbname "$RESTORE_DATABASE_NAME" "$BACKUP_PATH"
```

Keep the backup through full acceptance and the agreed rollback window.

## 4. Prove lineage and migration on the restored database

The read-only candidate is `20260718_120000`. Apply the stamp to the restored
database first, never directly to live as the first experiment:

```bash
export DATABASE_URL="$RESTORE_DATABASE_URL"
python3 -m alembic -c backend/alembic.ini stamp 20260718_120000
python3 -m alembic -c backend/alembic.ini upgrade 20260720_210000
```

On the restored database, require:

- exactly one `alembic_version=20260720_210000` row;
- all Source Catalog, Job Intelligence, Automation, and Dispatch Plan tables;
- every required FK/index/immutability trigger, including
  `crawl_job_listings.crawl_job_id -> crawl_jobs.id ON DELETE CASCADE`;
- unchanged Job, Company, raw evidence, enrichment, embedding, and unrelated
  outbox counts;
- a ready Crawl Control dry-run after the restored clone has three test/reviewed
  active Catalogs, or the equivalent schema-parity test fixture when Catalog
  publication is intentionally deferred to live.

Any failure invalidates the candidate. Preserve the clone and evidence for
review; do not try a later stamp until it happens to pass.

## 5. Stamp and upgrade live only after clone acceptance

Restore `DATABASE_URL` to the reviewed live target, reconfirm its read-only
lineage evidence has not changed, then perform exactly the accepted path:

```bash
python3 -m alembic -c backend/alembic.ini stamp 20260718_120000
python3 -m alembic -c backend/alembic.ini upgrade 20260720_210000
```

If either command fails, stop. Do not continue to Catalog publication or reset;
restore the pre-migration backup if the schema cannot be safely completed.

## 6. Discover, validate, review, and publish the initial Catalogs

Start only the trusted-local API needed for review endpoints. Keep scheduler,
workers, Scrapyd, and other writers stopped.

```bash
docker compose start backend-api
```

For each `jobsdb`, `ctgoodjobs`, and `offertoday`:

1. discover one immutable candidate and record ID/fingerprint/provenance/diff;
2. run full offline validation plus the bounded validation smoke;
3. resolve CTgoodjobs headed/manual action instead of treating it as passed;
4. request a short-lived publication review from the trusted-local API;
5. review the complete Automation impact and candidate fingerprint;
6. publish with the exact actor-bound token and fingerprint.

```bash
python3 backend/scripts/source_catalog_admin.py discover --source "$SOURCE"
python3 backend/scripts/source_catalog_admin.py validate \
  --candidate-id "$CANDIDATE_ID" --run

curl --fail --silent --show-error -X POST \
  -H 'Content-Type: application/json' \
  -d '{"actor":"local-operator"}' \
  "$API_BASE/source-catalogs/$SOURCE/candidates/$CANDIDATE_ID/publication-reviews"

python3 backend/scripts/source_catalog_admin.py publish \
  --candidate-id "$CANDIDATE_ID" \
  --review-token "$REVIEW_TOKEN" \
  --actor local-operator \
  --confirm-fingerprint "$CANDIDATE_FINGERPRINT" \
  --confirm-publish
```

Review tokens are short-lived/single-use. Never persist them in the runbook or
commit them. After all three publications, verify the published endpoints each
return the reviewed active revision/fingerprint, then stop the API and confirm
the transient admin process has exited.

```bash
docker compose stop backend-api
```

## 7. Generate and review the final dry-run artifact

Point `DATABASE_URL` at the reviewed live target and run:

```bash
python3 backend/scripts/crawl_control_cutover.py dry-run \
  --backup-id "$BACKUP_ID" \
  --confirm-backup \
  --output "$CUTOVER_DIR/crawl-control-dry-run.json"
```

The command exits `0` only when ready (`2` means NO-GO). Verify the artifact
envelope and review at least:

```bash
jq '{payload_hash, payload: {
  ready: .payload.ready,
  schema_revision: .payload.schema_revision,
  backup_id: .payload.backup_id,
  report_hash: .payload.report_hash,
  issues: .payload.issues,
  active_catalog_sources: .payload.active_catalog_sources,
  active_crawl_job_count: .payload.active_crawl_job_count,
  writer_evidence: .payload.writer_evidence,
  reset_counts: .payload.reset_counts,
  preserve_counts: .payload.preserve_counts,
  pending_crawl_outbox_count: .payload.pending_crawl_outbox_count,
  preserved_outbox_count: .payload.preserved_outbox_count
}}' "$CUTOVER_DIR/crawl-control-dry-run.json"
```

Required values are `ready=true`, schema `20260720_210000`, the exact backup ID,
zero active Crawl Jobs, all 11 known writers stopped, and active sources exactly
`ctgoodjobs`, `jobsdb`, `offertoday`. Review the actual FKs and every preserve/
reset count; do not approve from `ready` alone.

## 8. Execute the fenced atomic reset

This is the destructive boundary. Use the exact reviewed artifact, backup ID,
and literal confirmation token:

```bash
python3 backend/scripts/crawl_control_cutover.py reset \
  --report "$CUTOVER_DIR/crawl-control-dry-run.json" \
  --backup-id "$BACKUP_ID" \
  --confirm-backup \
  --confirm-reset RESET_CRAWL_CONTROL_DATA \
  --output "$CUTOVER_DIR/crawl-control-reset.json"
```

The reset obtains `ACCESS EXCLUSIVE NOWAIT` locks, recomputes the report hash,
and runs one serializable transaction. It deletes only pending crawl outbox and
Crawl Control/legacy Automation data. It must preserve Jobs, Companies,
taxonomy, enrichment, embeddings, Catalog Revisions, published/unrelated
outbox, and all other application tables exactly.

Verify the execute artifact carries the reviewed report hash/backup ID and that
its `preserved_counts` and `preserved_outbox_count` equal the dry-run values.

## 9. Restart persistent services and run bounded smoke plans

Restart only the persistent services, then verify health/writer evidence:

```bash
docker compose start \
  backend-api scheduler-worker ingest-worker enrichment-worker \
  embedding-worker scrapyd
```

For each Source, fetch its published Catalog and choose one reviewed selectable
classification from that exact active revision. Recommended smoke candidates,
only if they exist unchanged in the published tree, are:

| Source | Classification | Crawl mode |
|---|---|---|
| JobsDB | `jobsdb:6281` | `headless` |
| CTgoodjobs | `ctgoodjobs:021` | `headed` |
| OfferToday | `offertoday:118000` | `headless` |

Prepare one One-off listing plan with a single exact rule, `page_depth=1`,
`run_page_cap=1`, and no detail settings:

```json
{
  "version": 1,
  "kind": "one_off",
  "scope": {
    "version": 1,
    "source_site": "<source>",
    "reviewed_catalog_revision_id": "<active revision UUID>",
    "mode": "rules",
    "rules": [
      {"kind": "exact", "classification_id": "<source-qualified ID>"}
    ]
  },
  "listing_settings": {
    "version": 1,
    "crawl_mode": "<headed|headless>",
    "page_depth": 1,
    "run_page_cap": 1
  },
  "detail_settings": null
}
```

Call `POST /api/v1/dispatch-plans`, require readiness `ready`, one Query Target,
estimated maximum one page, and record the returned plan fingerprint and
one-time confirmation token. Dispatch only with both values:

```json
{
  "confirmation_token": "<one-time token>",
  "expected_plan_fingerprint": "<reviewed SHA-256>"
}
```

Send that body to
`POST /api/v1/dispatch-plans/{plan_id}/dispatch`, then require:

- the run authority points to the consumed plan/fingerprint and exact Catalog
  Revision; raw request payload is not used as authority;
- only one bounded outbound listing page is attempted;
- JobsDB evidence carries the reviewed native `classification`;
- CTgoodjobs uses the published headed URL path and exercises the real
  manual-action contract if challenged;
- OfferToday evidence carries the reviewed `jobFunctionCodes` request;
- no implicit categoryless query or detail crawl starts;
- task history reaches a truthful terminal/manual-action state and cancellation
  still requires acknowledgement.

Do not publish secrets, bodies, cookies, session state, or unbounded ID lists in
the smoke artifact.

## 10. Acceptance and backup retention

Checkpoint 10 is accepted only when all three smoke artifacts, post-reset
counts/FKs, API/catalog health, legacy `/categories`, Schedule validation,
Standalone, and Scrapy authority agree on the same active revision fingerprints.
Retain the backup and prior compatible application image through the rollback
window. Only then may Checkpoint 11 receive its final live evidence and the task
be completed/archived.

The 2026-07-20 execution met this gate. JobsDB and CTgoodjobs completed bounded
listing smokes. OfferToday preserved the same consumed plan/revision/fingerprint
authority, surfaced an upstream `ip_blocked` manual action, and reached
acknowledged `cancelled` without a retry or bypass. Final API/SQL checks found
zero active Crawl Jobs and matching active Catalog fingerprints; see the linked
evidence document for exact IDs, counts, hashes, and the retained rollback
asset.

## Rollback

- Before reset commit: allow the transaction to roll back and keep all services
  stopped while the cause is reviewed.
- After migration but before reset: restore the verified pre-migration backup if
  schema/Catalog state cannot be safely completed; an initial publication has no
  older revision to roll back to `none`.
- After reset commit or post-restart writes: stop all services, restore the
  verified backup, deploy the recorded compatible prior image/configuration,
  verify legacy health/preserved counts, then reopen the prior writer set only
  after a fresh operator decision.

No Alembic downgrade or direct row editing can recreate deleted Crawl Control
history.
