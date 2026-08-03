# Backend Database Contracts

## Scenario: bootstrap the current schema from an empty sandbox

### 1. Scope / Trigger

Use this contract whenever ORM metadata changes or the sandbox is rebuilt. The
application has one current schema. It does not migrate, stamp, downgrade, or
repair an existing database in place.

### 2. Signatures

```python
bootstrap_database(db_engine=engine, metadata=Base.metadata) -> None
repair_employment_type_registry(db_engine=engine) -> EmploymentTypeRegistrySyncResult
clear_database(db_engine=engine, confirmed=True) -> None
```

```text
python backend/scripts/bootstrap_db.py
python backend/scripts/repair_employment_type_registry.py
python backend/scripts/sandbox_cutover.py clear-database \
  --artifact <transient-retained.json> \
  --confirm-services-stopped \
  --confirm-destroy-sandbox
```

### 3. Contracts

- Persistent services are stopped before any destructive database action.
- `bootstrap_database` accepts only a database with zero tables. One ordinary
  table, a stray compatibility table, or a schema-history table makes it fail
  without mutation.
- PostgreSQL bootstrap takes the advisory transaction lock, creates the
  `vector` extension, creates `Base.metadata`, verifies exact table parity, and
  converges the seven canonical `employment_types` rows in the same transaction.
- `EMPLOYMENT_TYPE_SEEDS` is the only registry authority. Fresh bootstrap
  rejects unknown Employment Type codes. The explicit repair command is the
  only non-empty-database path: it inserts missing canonical rows, corrects
  canonical labels/order, reports and preserves non-conflicting unknown codes,
  and creates or alters no schema object.
- An unknown code occupying a canonical label or sort order makes repair fail
  and roll back; preserving that row and restoring the canonical registry are
  otherwise mutually impossible under the unique constraints.
- `clear_database` is limited to PostgreSQL databases named `jobsdb` or ending
  in `_test`; the caller must explicitly confirm destruction.
- The sandbox cutover validates the complete retained artifact before calling
  `clear_database`. An envelope hash alone is not sufficient.
- There is no Alembic directory, migration runtime, schema stamp, downgrade,
  compatibility column, or mixed-code deployment path.
- Manual intake schema includes `manual_job_evidence` and
  `manual_job_mutation_receipts`; Companies include `website` and
  `ai_description_updated_at`. `companies.extra_data` and `jobs.search_vector`
  are absent from current metadata.
- Schema deployment order is `stop -> export -> clear -> deploy complete code
  set -> bootstrap -> import -> verify -> start`.
- Tests that may create or clear PostgreSQL state parse their URL with
  `make_url` and require a database name ending in `_test` before the first
  engine open, DDL statement, or cleanup call.

### 4. Validation Matrix

| Condition | Required result |
|---|---|
| Empty database | Create the complete current schema and verify exact parity |
| Empty current bootstrap | Commit exactly the seven canonical Employment Type rows with the schema |
| Any existing table | Fail without creating, dropping, or altering anything |
| Repair sees missing or drifted canonical row | Insert/correct it and remain idempotent on rerun |
| Repair sees non-conflicting unknown code | Preserve and report it |
| Repair sees unknown row occupying canonical label/order | Fail and roll back without schema mutation |
| Metadata/table parity differs after bootstrap | Fail; do not start services |
| Destructive confirmation missing | Refuse the clear operation |
| Retained artifact is incomplete, reordered, malformed, or hash-invalid | Refuse before clearing the database |
| PostgreSQL test database name does not end in `_test` | Fail before connection or mutation |
| Old and new application processes overlap | Unsupported; keep services stopped |

### 5. Tests Required

- Bootstrap tests cover empty creation, exact parity, canonical registry
  insertion, real-PostgreSQL persistence, and non-empty refusal.
- Registry repair tests cover missing rows, label/order canonicalization,
  idempotent rerun, unknown preservation/reporting, blocking unknown conflicts,
  and refusal when the table is absent.
- Disposable cutover tests prove Manual evidence/receipts and new Company fields
  survive exact export/import while removed-column values are intentionally discarded.
- `test_job_intelligence_test_safety.py` inventories every PostgreSQL-bound
  suite and proves parsed `_test` checks precede engine creation and mutation.
- `test_sandbox_cutover.py` covers explicit destruction, complete artifact
  validation, and absence of schema-history/version tables.
- `integration/test_sandbox_cutover_rehearsal.py` rebuilds a disposable
  PostgreSQL `_test` database twice and never connects to shared `jobsdb`.

### 6. Wrong vs Correct

```python
# Wrong: silently make an old schema look partly current.
metadata.create_all(bind=connection)

# Correct: reject every non-empty target.
if inspect(connection).get_table_names():
    raise DatabaseBootstrapError("Refusing to bootstrap a non-empty database")
metadata.create_all(bind=connection)
```

```python
# Wrong: use bootstrap as an in-place data repair path.
bootstrap_database(db_engine=nonempty_engine)

# Correct: invoke the narrow registry-only command explicitly.
repair_employment_type_registry(db_engine=nonempty_engine)
```
