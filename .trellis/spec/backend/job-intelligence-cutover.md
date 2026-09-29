# Unversioned Sandbox Cutover Contracts

## Scenario: preserve business data while deleting all historical runtime state

### 1. Scope / Trigger

Use this contract for the one destructive sandbox rebuild that removes every
application release/revision/review system and every historical task, run,
outbox, schedule, and Redis stream state. This is an operator workflow, never
an application startup hook.

The transient retained artifact is transformation input. It is not a backup,
has no restore or rollback command, and is deleted after exact verification.

### 2. Operator Commands

```text
python backend/scripts/sandbox_cutover.py export --output <artifact>
python backend/scripts/sandbox_cutover.py clear-redis --confirm-services-stopped
python backend/scripts/sandbox_cutover.py clear-database \
  --artifact <artifact> \
  --confirm-services-stopped \
  --confirm-destroy-sandbox
python backend/scripts/sandbox_cutover.py bootstrap
python backend/scripts/sandbox_cutover.py import --artifact <artifact>
python backend/scripts/sandbox_cutover.py verify --artifact <artifact>
python backend/scripts/sandbox_cutover.py finalize --artifact <artifact>
```

The application seam is `app.job_intelligence.sandbox_cutover.SandboxCutover`.

### 3. Retention Boundary

Retain exactly:

- Companies and Jobs, including collected details and AI enrichment fields;
- Company `website` and `ai_description_updated_at`, plus Manual Job evidence,
  freshness hashes, operator field authority, and mutation receipts;
- no Job embeddings; they are regenerated from retained Job, Source, Company,
  and governed Skill data after cutover;
- ordinary Source Classification rows and complete Job source-path evidence;
- complete Job Employment Type assignments and raw label evidence; the
  canonical `employment_types` parent registry itself is bootstrap-authoritative
  and is not exported or imported;
- current Skill nodes, aliases, assignments, Candidates, Mentions and
  projections; current taxonomy tables accept only `taxonomy=skill`;
- required Skill audit/idempotency evidence after excluding retired domains and
  recursively removing application revision/release/version keys.

Delete exactly:

- crawl, automation, dispatch, schedule, manual-action, enrichment, retired
  review, and embedding run history;
- retired provider settings and credentials, bounded runs, work items,
  receipts, classifications, maintenance batches, duplicate associations,
  quality observations/evaluations, rerank evaluations, and triage records;
  these records are intentionally excluded from the transient retained artifact;
- Event Outbox rows;
- all application release/revision/active-pointer/review tables;
- Redis Streams, consumer groups, pending entries, and dead letters;
- schema-history tables and every compatibility archive.

Never delete or regenerate retained Job IDs, Company IDs, details, enrichment,
or source evidence. Job embeddings are the explicit rebuildable exception.

`companies.extra_data` and `jobs.search_vector` are the only intentionally
removed compatibility columns in this cutover. Export records their pre-cutover
non-null counts for operator review, omits their values from retained rows, and
does not treat them as restorable data.

### 4. Artifact Contracts

- Export visits the fixed retained-table order and stores every row in
  deterministic order.
- Each table records an exact row count and SHA-256 content hash. The whole
  canonical JSON payload is wrapped by its own SHA-256 envelope.
- UUID, timezone-aware datetime/date, Decimal, bytes, and vectors round-trip
  through explicit type tags.
- Artifact writes use a mode-`0600` temporary file and atomic replace; symbolic
  link destinations are rejected.
- Before database destruction, validation checks the envelope, exact retained
  table set and order, entry shape, row count, per-table hash, and row shape.
- Import refuses any non-empty retained target table and inserts self-referential
  hierarchies parent-first inside one database transaction.
- Bootstrap creates the seven-row Employment Type registry before import.
  Because `employment_types` is not a retained artifact table, its canonical
  rows do not violate the non-empty retained-target gate; imported Job
  assignments reference those bootstrapped parents.
- Pre-start verification re-exports every retained table, compares exact
  count/hash, and requires runtime tables (including Job embeddings) to be
  empty. This includes every table named in `RUNTIME_TABLE_NAMES`, including
  all declared runtime tables, so neither credentials nor retired runtime/audit
  state cross the destructive sandbox cutover. It also requires
  the exact canonical Employment Type registry. After
  service startup and embedding regeneration, `finalize` repeats
  exact checks for immutable retained tables. It permits startup-authoritative
  changes only in Source Classifications, OfferToday taxonomy snapshots, and
  the bootstrapped OfferToday keyword catalog, then requires exact schema/no
  forbidden tables and one valid 384-dimensional embedding for every retained
  Job. Normal post-start runtime rows no longer block deletion. Any failure
  preserves the artifact.

### 5. Good / Base / Bad Cases

- **Good:** pre-start exact verification passes, the restarted stack changes
  only the three declared startup-authoritative tables, every retained Job gets
  one 384-dimensional embedding, smoke checks pass, and `finalize` deletes the
  artifact.
- **Base:** Source Classification labels or the OfferToday startup catalog
  refresh after restart; immutable retained tables still match exactly and
  post-cutover verification succeeds.
- **Bad:** compare every retained table after startup and block forever on
  expected catalog refreshes, or ignore all retained hashes and accidentally
  hide loss in Jobs, Companies, Source evidence, or internal unresolved Skill evidence.
- **Bad:** let APScheduler recreate `apscheduler_jobs`; this bypasses current ORM
  metadata and makes the supposedly exact bootstrapped schema drift immediately.

### 6. Ordered Cutover

1. Run the disposable PostgreSQL/Redis rehearsal twice.
2. Stop every persistent application, worker, sidecar, frontend, and Scrapy
   service that can read or write shared state.
3. Export the retained artifact and inspect its complete count/hash manifest.
4. Clear all known Redis stream topics.
5. Validate the complete artifact, then clear the shared PostgreSQL schema.
6. Deploy one complete code set and bootstrap the empty current schema.
7. Import retained rows and verify exact identity/content/count parity.
8. Verify every runtime table is empty and every forbidden table is absent.
9. Delete the transient artifact.
10. Start the complete stack atomically and run health plus cross-source product
    smoke checks. No old command may resume.

There is no rollback after step 9. Any ambiguity before database destruction
aborts the workflow while the existing sandbox remains intact.

### 7. Validation Matrix

| Condition | Required result |
|---|---|
| Services-stopped confirmation missing | Refuse Redis/database clearing |
| Database name is not `jobsdb` or `*_test` | Refuse destruction |
| Artifact set/order/shape/count/hash differs | Refuse before destruction or import |
| Retained target table is non-empty | Roll back the import |
| Employment Type registry differs from the canonical seven rows | Verification fails before service start |
| Retained verification differs | Keep artifact and services stopped |
| Runtime table contains any row | Verification fails |
| Forbidden release/revision/review/schema-history table exists | Verification fails |
| Redis stream remains | Redis cleanup fails |
| Immutable retained table changes after restart | Finalization fails and preserves artifact |
| Declared startup-authoritative catalog changes | Finalization continues to post-cutover checks |
| Job/embedding counts differ or an embedding is not 384-dimensional | Finalization fails and preserves artifact |
| APScheduler or another subsystem creates an unexpected table | Finalization fails; remove the private persistence path |
| All checks pass | Delete artifact, start complete stack, smoke test |

### 8. Tests Required

- `test_sandbox_cutover.py`: deterministic export, recursive identity stripping,
  strict artifact gate, exact import/verification, parent-first hierarchy,
  failed-verification retention, Redis cleanup, runtime emptiness, forbidden
  table absence, additive Manual-table handling for older source schemas,
  removed-column discard counts, pre-start exact verification, declared
  post-start mutable-table handling, embedding completeness, and no
  backup/restore/rollback CLI commands.
- `integration/test_sandbox_cutover_rehearsal.py`: a disposable PostgreSQL
  database ending in `_test` plus non-zero Redis DB; real RESTRICT cycles,
  consumer group pending entries, dead letters, retained corpus, vectors,
  canonical registry verification, and two complete clean-start passes.
- Full backend tests, frontend lint/tests/build, and fixture parity pass before
  any shared sandbox action.

### 9. Wrong vs Correct

#### Wrong

```python
AsyncIOScheduler(
    jobstores={"default": SQLAlchemyJobStore(url=settings.database_url)}
)
```

This recreates an `apscheduler_jobs` table outside `Base.metadata` even though
`scrape_schedules` already owns durable schedule state.

#### Correct

```python
AsyncIOScheduler(timezone="UTC")
```

The scheduler reconciles this in-memory timer from current `scrape_schedules`
after every startup. Pre-start `verify` owns exact retention/runtime emptiness;
post-start `finalize` owns immutable retention, exact schema, and complete
embedding checks.

```python
# Wrong: export/import the bootstrap-owned parent registry.
RETAINED_TABLE_NAMES = ("employment_types", "job_employment_types")

# Correct: bootstrap parents, retain only business assignments/evidence.
RETAINED_TABLE_NAMES = ("job_employment_types",)
```

#### Forbidden patterns

- A backup, restore, rollback, migration, publish, activate, or version command.
- Clearing shared state while a persistent service is running.
- Treating an envelope hash as sufficient destroy authorization without
  validating the retained table manifest.
- Recreating historical tasks, run rows, outbox events, stream commands, or
  application version identity during import.
- Persisting a second APScheduler table; `scrape_schedules` is authoritative and
  the in-memory scheduler is rebuilt from it after startup.
