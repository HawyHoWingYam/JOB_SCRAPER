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

Never point that key, Alembic rollback tests, or downgrade commands at the live
development corpus.

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

### Schema migration synchronization

#### 1. Scope / Trigger

Use this contract whenever an ORM model gains a persisted column or table used
by an API, worker, or serializer. A model change is incomplete until the
Alembic revision is present in the repository and the bootstrap path reaches
that revision.

#### 2. Signatures

```text
bootstrap_database(db_engine=engine) -> None
alembic upgrade head
```

The local Compose `db-bootstrap` service runs `bootstrap_database`, which
upgrades an existing stamped database and stamps/ upgrades a fresh one.

#### 3. Contracts

- Every new mapped column has one forward migration and a reversible downgrade.
- The migration's `down_revision` is the current repository head and its
  `revision` becomes the only head after the change.
- Existing stamped databases converge to the repository head before API and
  worker services query the changed model.
- API serializers may expose nullable recovery metadata, but they must not
  assume an older schema can select the new ORM columns.

#### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| ORM column exists but migration is absent | Do not ship; migration-head check fails before deployment |
| Database revision is behind the model | Run `db-bootstrap` / `alembic upgrade head` before starting API workers |
| API queries a missing mapped column | PostgreSQL `UndefinedColumn` is an operational schema-drift failure, not an empty result |
| Migration is applied | AI overview/runs queries select recovery metadata and return HTTP 200 |

#### 5. Good / Base / Bad Cases

- **Good:** `EnrichmentRun.run_snapshot`, `EnrichmentRunItem.error_code`, and
  `attempt_count` are added by revision `20260722_120000`, then the disposable
  database reports that revision as `head`.
- **Base:** An existing local volume is at the previous revision; rerun the
  one-shot `db-bootstrap` service and verify `alembic_version` before opening
  the AI Enrichment page.
- **Bad:** Commit the ORM/API changes while leaving the migration untracked;
  `/api/v1/ai/overview` or `/api/v1/ai/runs` then returns 500 from an
  `UndefinedColumn` query.

#### 6. Tests Required

- A migration unit test asserts the revision lineage, exact added columns,
  server default for non-null counters, and reverse drop order.
- A disposable PostgreSQL check runs `alembic upgrade head`, then queries the
  changed API endpoints and asserts HTTP 200.
- CI or release checks assert exactly one Alembic head and that the database
  revision equals the repository head before API smoke tests.

#### 7. Wrong vs Correct

```python
# Wrong: model/API change without a checked-in migration.
attempt_count = Column(Integer, nullable=False, default=0)

# Correct: pair the model field with an Alembic upgrade and downgrade,
# then converge existing databases before serving requests.
op.add_column(
    "enrichment_run_items",
    sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
)
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
- schema-only Alembic migration plus real disposable-PostgreSQL
  upgrade/trigger/downgrade rehearsal.

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
