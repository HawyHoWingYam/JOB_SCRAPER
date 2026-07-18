# Job intelligence foundation

## Goal

Provide the small shared foundation Interfaces that let Source Job Attributes, Canonical Job Taxonomy, Company Industry, and Skill Governance enforce immutable revisions, provenance, local-operator decisions, idempotency, optimistic concurrency, audit, and outbox atomicity without duplicating those rules or collapsing domain behavior into one generic taxonomy Module.

## Background

- Parent requirements and invariants live in `../07-18-job-intelligence-taxonomy-governance/prd.md` and `design.md`.
- The repository currently uses unconstrained string statuses/resolutions, has no common decision audit contract, and has no authentication system.
- First-version operation is trusted single-user local-operator mode, not a public-network security boundary.
- Existing `event_outbox` provides the transactional event seam and should be reused rather than creating a second event mechanism.

## Requirements

- Define typed `RevisionRef`, `Provenance`, `DecisionCommand`, `DecisionResult`, decision error, and audit event contracts.
- Persist immutable governance revision identities/content hashes without embedding domain-specific node behavior in the foundation.
- Persist append-only audit events that survive subject retirement and record `actor=local-operator`, command hash, evidence references, before/after summaries, and correlation/idempotency keys.
- Enforce idempotent replay, conflicting-key rejection, and optimistic `expected_version` checks inside the decision transaction.
- Write decision effects, audit, idempotency result, and existing event-outbox event atomically.
- Separate worker-safe recommendation/normalization Interfaces from human decision Interfaces; background workers must not import or receive decision adapters.
- Provide deterministic seed/reference validators that domain children can extend without a generic all-taxonomies schema.
- Provide compatibility/read adapter conventions for legacy fields during expand/cutover without permanent dual-write.
- Document trusted-local deployment limits and preserve an authentication seam that can wrap decision Interfaces later.
- Add Alembic migration(s), PostgreSQL-backed Interface tests, and failure/rollback tests for all shared persistence rules.

## Acceptance Criteria

- [x] Two domain test adapters can use the same foundation contracts without moving domain rules into foundation conditionals.
- [x] Revisions are content-addressed/immutable and duplicate publication is deterministic.
- [x] Valid decisions commit domain effect, audit, idempotency record, and outbox atomically.
- [x] Stale versions and conflicting idempotency keys produce no partial writes; exact replay returns the original result.
- [x] Every audit event records `local-operator`; no credential/auth system is introduced.
- [x] Worker modules cannot reach decision Interfaces through their injected dependencies.
- [x] Seed validation reports all reference errors deterministically before any governed revision is published.
- [x] Migration upgrade/downgrade or documented rollback path is tested against PostgreSQL.

## Dependency and scope

- This is child 1 and has no dependency on other children in this program.
- Children 2–5 depend on its reviewed contracts.
- Domain node schemas, mapping policies, governance UI, and live-data cutover execution are out of scope.

## Notes

- Complex child: requires `design.md` and `implement.md` review before start.
