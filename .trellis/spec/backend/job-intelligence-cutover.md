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
- Job embeddings without persisted taxonomy/model version identity;
- ordinary Source Classification rows and complete Job source-path evidence;
- current Job Taxonomy, Company Industry, Skill nodes, aliases, mappings,
  assignments, Candidates, Mentions, and projections;
- required audit/idempotency evidence after recursively removing application
  revision/release/version keys.

Delete exactly:

- crawl, automation, dispatch, schedule, manual-action, enrichment,
  classification-batch, and embedding run history;
- Event Outbox rows;
- all application release/revision/active-pointer/review tables;
- Redis Streams, consumer groups, pending entries, and dead letters;
- schema-history tables and every compatibility archive.

Never delete or regenerate retained Job IDs, Company IDs, details, enrichment,
embeddings, or source evidence.

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
- Verification re-exports every retained table and compares exact count/hash.
  A failed verification preserves the artifact; `finalize` deletes it only
  after both retained-state and target-state checks pass.

### 5. Ordered Cutover

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

### 6. Validation Matrix

| Condition | Required result |
|---|---|
| Services-stopped confirmation missing | Refuse Redis/database clearing |
| Database name is not `jobsdb` or `*_test` | Refuse destruction |
| Artifact set/order/shape/count/hash differs | Refuse before destruction or import |
| Retained target table is non-empty | Roll back the import |
| Retained verification differs | Keep artifact and services stopped |
| Runtime table contains any row | Verification fails |
| Forbidden release/revision/review/schema-history table exists | Verification fails |
| Redis stream remains | Redis cleanup fails |
| All checks pass | Delete artifact, start complete stack, smoke test |

### 7. Tests Required

- `test_sandbox_cutover.py`: deterministic export, recursive identity stripping,
  strict artifact gate, exact import/verification, parent-first hierarchy,
  failed-verification retention, Redis cleanup, runtime emptiness, forbidden
  table absence, additive Manual-table handling for older source schemas,
  removed-column discard counts, and no backup/restore/rollback CLI commands.
- `integration/test_sandbox_cutover_rehearsal.py`: a disposable PostgreSQL
  database ending in `_test` plus non-zero Redis DB; real RESTRICT cycles,
  consumer group pending entries, dead letters, retained corpus, vectors, and
  two complete clean-start passes.
- Full backend tests, frontend lint/tests/build, and fixture parity pass before
  any shared sandbox action.

### 8. Forbidden Patterns

- A backup, restore, rollback, migration, publish, activate, or version command.
- Clearing shared state while a persistent service is running.
- Treating an envelope hash as sufficient destroy authorization without
  validating the retained table manifest.
- Recreating historical tasks, run rows, outbox events, stream commands, or
  application version identity during import.
