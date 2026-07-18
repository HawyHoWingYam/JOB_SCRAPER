# Job Intelligence foundation

The Job Intelligence foundation is the small shared backend Module for governed
revisions, provenance, human-decision transactions, audit history, idempotency,
optimistic concurrency, outbox writes, and deterministic seed validation. Domain
Modules retain their own actions, statuses, targets, evidence schemas, and
transition rules.

## Trusted-local security boundary

Job Intelligence governance is intentionally unauthenticated in the first
single-operator version. Every accepted human decision records the audit actor
`local-operator`; that value identifies the operating mode and is not a verified
user identity.

- Do not expose governance decision routes to the public internet, an untrusted
  LAN, a public reverse proxy, or a remote tunnel.
- CORS configuration is browser policy, not authentication or authorization.
- The Docker API currently binds host port `8000`; operators must restrict host
  and network access while unauthenticated decision routes are enabled.
- Governance UI surfaces must display a visible trusted-local-only warning.
- Background workers may generate recommendations and normalized evidence, but
  must not import or receive `GovernanceUnitOfWork`, `DecisionCommand`, or a
  domain decision adapter.

Future authentication belongs at the HTTP/application adapter. It authenticates
the caller before constructing the existing domain decision command; it does not
change domain transitions, transaction rules, audit records, or worker ports.

## Transaction contract

Domain decision adapters implement the foundation `DecisionTransition` port.
They load and lock their own subject, expose its `lock_version`, apply their own
transition, and return the updated resource plus outbox events. They must not
commit independently.

`GovernanceUnitOfWork.execute` requires `confirmed=true`, the fixed local actor,
an expected version, and a domain-scoped idempotency key. It writes the domain
effect, append-only audit event, existing `event_outbox` rows, and serialized
idempotency result with `auto_commit=False`, then commits once. Any failure rolls
back all four effects. Exact command replay returns the first result; different
command content under the same key fails.

## Revision and seed contract

`RevisionStore.publish` accepts a normalized SHA-256 content identity. Exact
publication replay returns the original `RevisionRef`; rebinding a release key
or content hash fails. Published revision, audit, and idempotency rows are
protected against mutation by both ORM guards and PostgreSQL triggers.

`SeedValidator` only owns deterministic traversal/report behavior. Domain
children provide their own rules for hierarchy, aliases, mappings, duplicates,
and references. Validation returns every issue in stable JSON-path order before
a domain publishes its revision.

## Compatibility and rollback

Legacy Job/Company fields remain behind domain-owned read adapters during the
expand and cutover period. New Job Intelligence Modules must not dual-write
legacy scalar fields, and the foundation does not interpret legacy values.

Before dependent records exist, the foundation migration can downgrade normally
on a disposable database. After domain adoption, application rollback keeps the
foundation tables and their history; deleting revision, audit, or idempotency
records is not an acceptable rollback strategy.
