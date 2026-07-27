# Backend database contracts

## Scenario: Job Intelligence governance transaction foundation

### 1. Scope / Trigger

Use this contract for Canonical Job Taxonomy, Company Industry, Skill, and other
Job Intelligence Modules that publish governed revisions or execute a human
decision. It prevents domain state, audit history, idempotency results, and
projection invalidation events from diverging across partial commits.

This is a trusted-local transaction boundary, not authentication. HTTP adapters
may call decision Modules; background workers may only call recommendation or
normalization ports.

### 2. Signatures

The shared Module is `app.job_intelligence.foundation`:

```python
RevisionStore(db).publish(manifest: RevisionManifest) -> RevisionRef
GovernanceUnitOfWork(db).execute(
    command: DecisionCommand,
    transition: DecisionTransition[SubjectT],
) -> DecisionResult
AuditReader(db).list(query: AuditQuery) -> AuditPage
SeedValidator.validate(document, rules) -> ValidationReport
```

Domain decision adapters implement:

```python
class DecisionTransition(Protocol[SubjectT]):
    domain: str
    subject_type: str

    def load_for_update(self, db, subject_id: str) -> SubjectT | None: ...
    def version(self, subject: SubjectT) -> int: ...
    def snapshot(self, subject: SubjectT) -> Mapping[str, Any]: ...
    def apply(self, db, subject: SubjectT, command: DecisionCommand) -> DecisionEffect: ...
```

Persistence tables are `governance_revisions`, `governance_audit_events`, and
`governance_idempotency_records`. Decision events reuse `event_outbox`; do not
create a parallel governance event queue.

PostgreSQL integration tests require an explicit disposable URL:

```text
JOB_INTELLIGENCE_TEST_DATABASE_URL=postgresql://.../<dedicated-test-db>
```

Never point that key, schema bootstrap checks, or destructive test cleanup at
the live development corpus.

Every test suite that reads this key must parse the URL and require the database
name to end in `_test` before its first `create_engine`, schema DDL, or fixture
cleanup call. A configured URL is not sufficient evidence of safety.

### 3. Contracts

`DecisionCommand` contains `subject_id`, domain-owned `action`, optional
`target_id`, `expected_version`, `idempotency_key`, `confirmed`, optional note
and correlation ID, and the fixed actor `local-operator`.

`GovernanceUnitOfWork.execute` owns the transaction:

1. require `confirmed=true` and `actor=local-operator`;
2. serialize the domain-scoped idempotency key;
3. replay an exact prior command or reject conflicting content;
4. load/lock the domain subject and compare `expected_version`;
5. invoke the domain transition without allowing it to commit;
6. require the returned subject/version to match persisted state and require at
   least one outbox event;
7. append audit, enqueue outbox rows with `auto_commit=False`, and store the
   idempotency result;
8. commit once, or roll back every effect on any exception.

Every audit row keeps the subject type/ID snapshot rather than a cascading
subject FK, records `local-operator`, before/after summaries, evidence refs,
command hash, idempotency key, correlation ID, and timestamp. Audit reads page
newest-first using stable `(created_at, id)` cursors.

Revision identity is unique by `(domain, release_key)` and `(domain,
content_hash)`. Exact publication replay returns the first `RevisionRef`;
rebinding either identity fails. Revision, audit, and idempotency rows are
immutable through ORM guards and PostgreSQL triggers.

Seed validation accumulates all domain-owned issues and sorts by JSON path,
code, related ID, message, and severity. Foundation owns report determinism, not
domain hierarchy or mapping rules.

### Current empty-schema bootstrap

#### 1. Scope / Trigger

Use this contract whenever the current ORM schema changes. This sandbox does
not migrate an existing database in place: application services are stopped,
the sandbox database is cleared, the complete code set is deployed, and one
empty database is bootstrapped to the current metadata.

#### 2. Signatures

```text
bootstrap_database(db_engine=engine) -> None
python backend/scripts/bootstrap_db.py
```

`bootstrap_database` accepts an SQLAlchemy Engine and metadata. It creates the
current schema only when inspection finds zero existing tables.

#### 3. Contracts

- Any existing table, including a stray migration/version table, makes
  bootstrap fail without creating, dropping, or altering tables.
- PostgreSQL bootstrap obtains the advisory transaction lock before inspection
  and creates the `vector` extension before `metadata.create_all`.
- After creation, the actual table-name set must exactly equal the current ORM
  metadata table-name set. Missing or unexpected tables fail bootstrap.
- There is no migration directory, migration runtime, schema stamp, downgrade,
  compatibility column, or mixed-code deployment path.
- Schema changes are deployed atomically as `stop -> clear sandbox database ->
  deploy complete code set -> bootstrap -> start`.
- PostgreSQL tests that may create or clear schema require a parsed database
  name ending in `_test` before opening an engine.

#### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Database has zero tables | Create the PostgreSQL extension when needed, create all current metadata tables, then verify exact table parity |
| Database has any table | Raise `DatabaseBootstrapError`; preserve the database unchanged |
| Created table set differs from metadata | Raise `DatabaseBootstrapError`; do not start application services |
| PostgreSQL test database name does not end in `_test` | Fail before `create_engine`, DDL, or cleanup |
| Old and new application processes would overlap | Unsupported deployment; stop all persistent services before clearing/bootstrap |

#### 5. Good / Base / Bad Cases

- **Good:** stop services, clear the sandbox volume, deploy one complete code
  set, bootstrap the empty database, verify exact metadata parity, then start.
- **Base:** an empty disposable SQLite database creates the current tables
  without a PostgreSQL extension step.
- **Bad:** point bootstrap at a database containing one application table and
  expect it to repair or upgrade the schema.

#### 6. Tests Required

- SQLite tests assert empty creation, exact table parity, and refusal of both an
  ordinary table and a stray version-table name without mutation.
- An optional disposable PostgreSQL `_test` integration asserts advisory-lock
  bootstrap, `vector` extension availability, exact tables, and non-empty
  refusal.
- Deployment documentation and checks preserve the stop/clear/deploy/bootstrap/
  start order; no test starts long-running services or mutates shared `jobsdb`.

#### 7. Wrong vs Correct

```python
# Wrong: try to make an old database look current in place.
metadata.create_all(bind=connection)  # existing tables were never rejected

# Correct: fail closed unless the target has no tables.
if inspect(connection).get_table_names():
    raise DatabaseBootstrapError("Refusing to bootstrap a non-empty database")
metadata.create_all(bind=connection)
```

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| `confirmed=false` | `GOVERNANCE_DECISION_UNCONFIRMED`; no writes |
| actor is not `local-operator` | `GOVERNANCE_DECISION_ACTOR_INVALID`; no writes |
| subject missing | `GOVERNANCE_DECISION_SUBJECT_NOT_FOUND`; no writes |
| `expected_version` differs | `GOVERNANCE_DECISION_STALE_VERSION`; no partial writes |
| same key and exact command | Return original result with `replayed=true`; no new audit/outbox |
| same key and different command | `GOVERNANCE_IDEMPOTENCY_CONFLICT`; no writes |
| transition returns stale subject/version | `GOVERNANCE_DECISION_CONTRACT_INVALID`; roll back |
| transition emits no outbox event | `GOVERNANCE_DECISION_CONTRACT_INVALID`; roll back |
| audit/outbox/result serialization fails | Roll back domain effect, audit, outbox, and idempotency |
| same revision manifest | Return original `RevisionRef` |
| release key or hash rebound | `GOVERNANCE_REVISION_CONFLICT` |
| revision/audit/idempotency UPDATE or DELETE | ORM or PostgreSQL immutability error |
| malformed audit cursor | Stable `Invalid governance audit cursor` error |
| Test database URL is configured but its database name does not end in `_test` | Fail before `create_engine` or any DDL; never connect to the configured database |

### 5. Good / Base / Bad Cases

- **Good:** A Skill Candidate merge locks version 4, updates every domain-owned
  row, appends audit/outbox/idempotency with `auto_commit=False`, and commits
  once as version 5.
- **Base:** The operator retries the identical request after a lost response.
  The stored result returns with `replayed=true`; no duplicate event appears.
- **Bad:** A repository called inside the transition uses its default
  `auto_commit=True`. Later audit failure cannot roll back the already committed
  domain state.
- **Bad:** A worker receives `GovernanceUnitOfWork` “for convenience.” The
  recommendation path can now execute human decisions without an HTTP adapter.
- **Bad:** Legacy scalar columns and new projections are dual-written across a
  cutover. Two sources of truth can diverge before reconciliation.

### 6. Tests Required

`backend/tests/test_job_intelligence_foundation.py` must cover:

- two domain adapters using the same foundation without domain conditionals;
- deterministic hash/seed reports and revision replay/conflict/immutability;
- valid decision, stale version, actor/confirmation rejection, exact replay,
  conflicting replay, and two-session concurrency;
- failure after the domain mutation and audit flush proving all writes roll back;
- outbox event correlation with the audit ID;
- stable audit pagination and response-schema serialization;
- worker import/injection isolation;
- empty-schema bootstrap and real disposable-PostgreSQL `_test` safety checks.

`backend/tests/test_job_intelligence_test_safety.py` inventories every
PostgreSQL-bound Job Intelligence suite. For every engine-opening function, it
asserts that the parsed `make_url(database_url).database` name is checked for
the `_test` suffix and fails closed before each engine open, schema DDL, or
fixture cleanup call. A raw URL-tail check is insufficient because query text
can masquerade as a database-name suffix.

Targeted checks:

```bash
pytest -q tests/test_job_intelligence_foundation.py
ruff check app/job_intelligence app/models/governance.py \
  app/schemas/job_intelligence.py tests/test_job_intelligence_foundation.py
mypy --follow-imports=skip app/job_intelligence app/models/governance.py \
  app/schemas/job_intelligence.py
```

### 7. Wrong vs Correct

#### Wrong: nested commit inside a domain transition

```python
def apply(self, db, subject, command):
    subject.status = "assigned"
    db.commit()
    outbox_repository.enqueue(db, payload={...})
```

The decision can become visible without audit or idempotency if later work
fails.

#### Correct: return effects to the shared transaction owner

```python
def apply(self, db, subject, command):
    subject.status = "assigned"
    subject.lock_version += 1
    return DecisionEffect(
        subject=self.snapshot(subject),
        resulting_projection={"subject_id": subject.id},
        version=subject.lock_version,
        evidence_refs=({"kind": "raw-job", "id": subject.job_id},),
        outbox_events=(projection_invalidated_event(subject),),
    )

result = GovernanceUnitOfWork(db).execute(command, transition)
```

The foundation flushes domain changes, audit, the existing outbox, and the
idempotency result, then commits exactly once.
