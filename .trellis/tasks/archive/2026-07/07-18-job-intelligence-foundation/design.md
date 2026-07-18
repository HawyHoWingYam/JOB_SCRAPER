# Job intelligence foundation design

## Module shape

Foundation is an internal Module used by domain Modules. Its Interface is deliberately small:

```text
RevisionStore.publish(manifest) -> RevisionRef
GovernanceUnitOfWork.execute(command, transition) -> DecisionResult
AuditReader.list(query) -> Page[AuditEvent]
SeedValidator.validate(document, rules) -> ValidationReport
```

`transition` is a domain-owned adapter invoked inside the unit of work; foundation does not interpret actions, targets, statuses, or taxonomy nodes. HTTP callers never invoke foundation directly.

## Value contracts

- `RevisionManifest`: domain, release key, source metadata, normalized content hash, created timestamp.
- `RevisionRef`: immutable ID/domain/release/hash.
- `Provenance`: method plus optional Source/mapping/model/evidence references; domain Modules may add typed evidence payloads.
- `DecisionCommand`: subject/action/target, expected version, idempotency key, confirmed flag, actor, note.
- `DecisionResult`: updated subject/projection reference, audit ID, resulting version, replay flag.
- Errors: invalid transition/target, unconfirmed, stale version, conflicting idempotency, missing subject.

No contract accepts raw Bearer credentials. HTTP adapters set the fixed actor `local-operator` in trusted local mode.

## Persistence

### `governance_revisions`

- UUID PK, constrained domain, release key, content hash, source metadata JSON, status, created/published timestamps.
- Unique `(domain, release_key)` and `(domain, content_hash)`.
- Published rows are immutable by model/repository guard and database trigger or restricted update path.

### `governance_audit_events`

- UUID PK, domain, subject type/ID snapshot, action, actor, command hash, idempotency key, before/after summaries, evidence refs, correlation ID, timestamp.
- Append-only; no subject FK cascade.
- Index `(domain, created_at, id)` and `(subject_type, subject_id, created_at)`.

### `governance_idempotency_records`

- Unique `(domain, idempotency_key)`, command hash, audit/result reference, created timestamp.
- Exact replay returns stored result. Hash mismatch raises conflict.

Domain assignment/review rows own `lock_version`. Foundation locks/reloads the subject through the supplied transition adapter and checks `expected_version` before effects.

## Transaction protocol

1. Require `confirmed=true` and actor `local-operator`.
2. Check/replay idempotency record.
3. Load/lock domain subject and compare version.
4. Invoke domain transition adapter.
5. Append audit event and existing event-outbox row.
6. Store idempotency result.
7. Commit once and return `DecisionResult`.

Any exception rolls back all effects. Domain transitions cannot commit independently.

## Worker/decision separation

- Recommendation/normalization ports live in each domain package and do not receive `GovernanceUnitOfWork`.
- Governance HTTP route adapters receive decision Modules.
- Constructor/import contract tests ensure worker entry points do not instantiate decision adapters.
- This is accidental/architectural protection in trusted local mode, not resistance to a malicious caller that can reach the API.

## Seed validation

Foundation provides deterministic traversal/report primitives: stable issue ordering, JSON path, code, message, and related ID. Domain rules validate hierarchy, aliases, crosswalks, duplicate identities, and references. Validation returns a complete report rather than failing at the first issue.

## Compatibility seam

Legacy reads are adapters outside foundation. Foundation only defines migration provenance and revision/audit contracts. New Modules never dual-write legacy scalar fields; cutover child owns final read switch and later cleanup.

## Testing

- PostgreSQL integration tests run two minimal fake domain transitions through the same Interface to prove reuse without domain conditionals.
- Concurrency tests use two sessions and stale versions.
- Failure injection verifies effect/audit/outbox/idempotency atomicity.
- Immutability and append-only constraints are tested at repository and direct SQL levels.
- Seed report ordering and content hash normalization are deterministic.

## Rollback

Migration rollback may remove empty foundation tables before domain children depend on them. Once audit/revision records exist, application rollback keeps tables and old code ignores them; destructive deletion of audit history is not an acceptable downgrade.

