# Source job attributes

## Goal

Preserve complete source-owned classification and employment evidence for every collected Job, and expose governed zero-to-many Source Classification Paths and Employment Types through consistent persistence, API, filters, and source adapters.

## Background

- Parent decisions are ADR-0005, ADR-0008, `CONTEXT.md`, and the reviewed
  `job-intelligence-foundation` contracts.
- JobsDB listing parsing truncates `classifications` to `[0]`, OfferToday
  canonicalization truncates `jobFunctions` and their children to `[0]`, and
  the current Job model stores only one classification/subclassification pair
  (`backend/app/sources/jobsdb/parsers.py:37-43`,
  `backend/app/sources/contracts.py:203-226`,
  `backend/app/models/job.py:72-75`).
- JobsDB and CTgoodjobs may emit multiple employment labels, but current
  canonicalization joins them into one free-text `employment_type`; OfferToday
  exposes both labels and codes (`backend/app/sources/contracts.py:35-41`,
  `backend/app/sources/ctgoodjobs/parsers.py:288-298,556-560`).
- `Job.raw_data` and crawl staging payloads preserve useful evidence, but some
  existing JobsDB/CTgoodjobs paths discarded arrays before persistence. A
  historical rebuild therefore cannot claim complete recovery for every row.

## Requirements

### R1 — Module and authority boundary

- Source Job Attributes owns automated normalization and current projections;
  it never becomes a Crawl Scope, Source Catalog publication, Canonical Job
  Taxonomy, or human governance authority.
- Reuse Foundation `Provenance`, normalized hashing, and outbox value semantics
  where applicable. Automated source projection must not use or expose
  `GovernanceUnitOfWork`, `DecisionCommand`, `DecisionTransition`, human audit,
  or governance idempotency records.
- A Source Catalog Revision is a separate Source Catalog identity, not a
  Foundation `RevisionRef`. Store a nullable, source-matching reference to the
  immutable Source Catalog revision when known; preserve historical evidence
  without inventing one when unknown.

### R2 — Source Classification Paths

- Model zero-to-many ordered Source Classification Paths with ordered nodes,
  source-qualified IDs, native label snapshots, source order, bounded evidence
  references, optional Source Catalog Revision, and explicit-primary
  provenance.
- JobsDB and OfferToday adapters preserve every returned path before existing
  scalar canonicalization can discard it. CTgoodjobs preserves its one known
  Source Classification path without inventing a subclassification.
- No adapter or migration may infer Primary from array order, display name,
  crawl selection, or local heuristics. `is_primary=true` requires an explicit
  Source declaration and non-empty basis.
- Historical paths with no known catalog revision remain queryable and expose
  `catalog_revision=null` plus a visible provenance-limited state.

### R3 — Source Employment Labels and Employment Types

- Preserve every ordered Source Employment Label/code before comma joining or
  scalar precedence discards it, including unmapped and malformed evidence.
- Governed Employment Type codes are exactly `full_time`, `part_time`,
  `permanent`, `contract`, `temporary`, `internship`, and `freelance`, with the
  display labels Full-time, Part-time, Permanent, Contract, Temporary,
  Internship, and Freelance.
- Map labels deterministically. One Job may project multiple governed values;
  unknown/unmapped/`Other`/`N, A`/malformed evidence projects no value and is
  never coerced to a plausible fallback.
- Work Arrangement and working-day evidence remain independent and may be
  retained as raw source evidence, but never becomes an Employment Type.

### R4 — Authoritative writes and transactions

- Source adapters emit one complete `SourceJobAttributeEvidence` value and do
  not write ORM rows directly.
- Every authoritative collected-Job writer projects through the Module in the
  same database transaction as the Job upsert and a
  `job.source_attributes_changed` event-outbox row. Exact evidence replay is a
  no-op and emits no duplicate event.
- New writers write the new Module only. Legacy scalar classification,
  subclassification, and `employment_type` columns remain read-only comparison
  evidence until the cutover child; there is no permanent dual-write.

### R5 — Read and filter contracts

- Job responses add complete `source_classification_paths[]` and
  `employment_types[]`; detail/evidence responses also expose ordered
  `source_employment_labels[]`. Arrays are empty rather than fabricated when
  evidence is absent.
- Filters use `source_classification_ids[]` and
  `employment_type_codes[]`. Values within one field are OR, different fields
  are AND, and display names/raw labels are never authoritative filter keys.
- Filter options expose stable source-qualified classification IDs and stable
  Employment Type codes with labels. Any deprecated scalar adapter must
  translate into the new code-based predicate and must not remain an
  independent scalar-equality path.

### R6 — Historical rebuild evidence

- Provide a read-only dry-run command over staging payloads, `Job.raw_data`, and
  legacy columns. This child exposes no live apply mode.
- Report, per Source, recoverable paths/labels, recovered multi-value evidence,
  unknown/malformed values, legacy conflicts, missing catalog revision,
  provenance-limited rows, and evidence that is already unrecoverable because
  an older parser discarded it.
- Dry-run ordering and output are deterministic, perform zero writes, and do
  not claim that legacy scalars reconstruct discarded arrays.

## Acceptance Criteria

- [x] AC-R1: Worker/import architecture tests prove automated projection cannot
  reach Foundation human-decision Interfaces, while persisted provenance and
  outbox payloads follow the reviewed Foundation value contracts.
- [x] AC-R2: Multi-classification JobsDB and OfferToday fixtures persist every
  semantic path/node in source order; CTgoodjobs remains a valid root-only path;
  no Source without explicit primary evidence produces `is_primary=true`.
- [x] AC-R2-History: A path with an unknown catalog revision remains queryable
  with `catalog_revision=null` and `provenance_limited=true`; a known revision
  must belong to the same Source and cannot be cascade-deleted.
- [x] AC-R3: Employment combinations normalize to multiple governed codes and
  retain raw labels/codes/order. `Other`, `N, A`, unknown, malformed,
  remote/hybrid/on-site, and working-day values produce no Employment Type.
- [x] AC-R4: PostgreSQL tests prove atomic Job/projection/outbox persistence,
  replacement idempotency, constraints/indexes, and Job deletion cascade; new
  writer tests prove legacy source-attribute scalars are not dual-written.
- [x] AC-R5: List/detail schemas return complete arrays and stable identities;
  filter tests prove OR-within/AND-across semantics and no authoritative
  comma-joined/scalar equality path.
- [x] AC-R6: The dry-run report deterministically distinguishes recovered,
  ambiguous, unknown, conflicting, provenance-limited, and unrecoverable rows
  and leaves all database tables byte-for-byte unchanged.

These criteria were reconciled against the implemented PostgreSQL, adapter,
API, architecture, and deterministic rebuild tests during the parent
integration audit on 2026-07-20. Live corpus execution remains child 7 and
operator scope.

## Dependencies and out of scope

- Depends on the completed and archived `07-18-job-intelligence-foundation`
  contracts.
- May consume the published Source Catalog identity/revision Interface from the
  separate Task Control Board program, but historical evidence never requires
  a catalog revision to exist.
- Canonical Job Taxonomy mapping, Crawl Scope, governance UI, full product UI,
  live corpus migration/cutover, and destructive cleanup of legacy columns are
  out of scope.
- Run migrations and rebuild tests only against disposable PostgreSQL. Do not
  migrate, backfill, or rebuild the live development corpus in this child.

## Notes

- Complex child: requires `design.md` and `implement.md` review before start.
