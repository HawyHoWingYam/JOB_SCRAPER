# Canonical job taxonomy governance

## Goal

Establish the project-owned Canonical Job Taxonomy as governed immutable seed
state and ensure every evaluated Job has either one provenance-bearing accepted
assignment to an existing governed Job Subcategory or an explicit
Unassigned/review state.

## User value

- Canonical filters, analytics, recommendations, and embeddings use stable
  governed identities instead of mutable labels or AI-created rows.
- A fallback, unsupported Source Classification, or uncertain AI answer remains
  visibly Unassigned instead of becoming an authoritative-looking path.
- Taxonomy changes, automatic assignments, and operator decisions are
  reproducible from pinned releases and preserved evidence.

## Confirmed facts

- `07-18-job-intelligence-foundation` and `07-18-source-job-attributes` are
  complete. This child reuses Foundation revision/provenance/decision/audit/
  idempotency/outbox contracts and consumes complete Source Classification
  Paths; it does not own Source Catalog or Crawl Scope.
- The current static seed has 25 Domains, 88 Categories, and 223 Subcategory
  leaves but no explicit stable codes. It contains 25 `General` Categories and
  25 `General` leaves; `Project Management` also occurs under two different
  parents. UUIDs or labels therefore cannot be regenerated as stable identity.
  The approved governed seed removes all 25 `General → General` fallback paths,
  yielding 25 Domains, 63 Categories, and 198 Subcategories; Unassigned is the
  formal state for missing or insufficient classification evidence.
- The live snapshot contains 8/13/23 legacy Domain/Category/Subcategory rows,
  all `created_by=ai` and `is_auto_created=true`. Roughly 3.8k Jobs reference
  those UUIDs through `jobs.subcategory_id`; those links are migration evidence,
  not accepted governed assignments.
- Legacy hierarchy rows are mutable, name-resolved, cascade-linked, and deleted
  by the old governance script. Revision-binding them in place would mix
  AI-created history with governed seed state and require rewriting live Job
  FKs, contrary to the additive rollout and cutover boundary.
- `AIEnrichmentService` currently calls `JobCategoryNormalizer`, which may
  clamp invalid output to a default path, accept `create_new`, or create hidden
  AI nodes under `governance_override`, then writes `jobs.subcategory_id`
  without assignment provenance or a review item.
- The label-based Source mapping file has 62 entries and 35 hints. It covers 12
  CTgoodjobs IDs, while a separate legacy `CTGOODJOBS_CATEGORY_MAPPINGS`
  constant mentions 15 additional IDs. Neither file is coverage authority;
  their `default_path`/`proposed_internal_domain` values are advisory evidence
  and the 15-ID discrepancy must remain visible until checked against a pinned
  published Source Catalog revision.

## Requirements

### R1 — Governed release and stable identity

- Store governed Canonical Job Taxonomy releases in replacement domain tables;
  leave `job_domains`, `job_categories`, `job_subcategories`, and
  `jobs.subcategory_id` as read-only legacy evidence until child 7 cutover.
- Every Domain, Category, and Subcategory has an explicit immutable stable code
  in the committed seed manifest. Bootstrap tooling may derive a code from the
  full path once and persist it, but runtime publication and future revisions
  never recompute identity from labels or parentage.
- The initial governed manifest contains exactly 25 Domains, 63 Categories,
  and 198 assignable Subcategories. It omits the 25 legacy `General` Categories
  and leaves entirely rather than retaining non-assignable compatibility or
  navigation nodes; legacy fallback paths remain comparison evidence only.
- Publish the normalized manifest through Foundation revision identity and bind
  every node to that revision. Parent/child FKs must prove same-revision
  ancestry; node/release contents are immutable after activation.
- Materialize and validate a release before changing the canonical active
  pointer. A Foundation revision identity committed before domain
  materialization is not executable authority; failed materialization may be
  retried and cannot become active.
- Validate unique codes, deterministic order/hash, complete parentage,
  assignability, mapping references, exact initial counts, and absence of exact
  `General`, `Unknown`, or other implicit fallback targets.

### R2 — Reviewed Source-to-Canonical mapping authority

- The Canonical Job Taxonomy Module owns versioned, reviewed
  Source-to-Canonical Job Mappings and Source-Bound Canonical Slices. Source Job
  Attributes supplies evidence only; Source Catalog never becomes canonical
  mapping authority.
- A mapping release pins exactly one immutable published Source Catalog
  revision per covered Source by revision ID, sequence, fingerprint, and exact
  mapping-eligible Source Classification identity set hash/count. Publication
  fails closed when a catalog is unpublished, stale, fingerprint-mismatched, or
  its identity coverage has missing, extra, or duplicate entries.
- Every mapping-eligible Source Classification identity in each pinned catalog
  has exactly one mutually exclusive disposition: `deterministic`,
  `allowed_slice`, `excluded`, or `unmapped`. `deterministic` has exactly one
  assignable target; `allowed_slice` has one or more assignable targets; and
  `excluded`/`unmapped` have none. Legacy labels, static fallback registries,
  and proposed-domain constants never imply identity coverage or approval.
- Mapping targets and allowed slices use governed stable codes, not display
  labels. Current `default_path` values are compatibility/fallback evidence and
  are never automatic assignment targets.
- For a Job with multiple Source Classification Paths, any missing mapping,
  `excluded`, or `unmapped` disposition creates review and cannot be hidden by
  another path. Multiple deterministic targets must converge on one governed
  Subcategory; disagreement creates review.
- The AI allowed slice is the deterministic union of all `allowed_slice`
  targets contributed by preserved Source paths. One convergent deterministic
  target may auto-assign only when no path blocks automation and, when an
  allowed union also exists, the target belongs to that union. Otherwise the
  evidence conflicts and enters review. With no deterministic target, AI may
  assign only inside a non-empty allowed union. Path order never grants
  authority.

### R3 — Automatic evaluation policy

- `evaluate` applies the complete multi-path mapping policy before mutation. It
  accepts one non-blocked, compatible convergent deterministic target;
  otherwise it may accept a structurally valid AI choice only when no path
  blocks automation and the target is an existing assignable Subcategory
  inside the pinned Source-Bound Canonical Slice.
- Every accepted assignment records taxonomy revision, method, mapping release/
  mapping IDs when used, Source evidence refs/hash, model/provider/version when
  used, captured time, and the complete accepted breadcrumb.
- Invalid, out-of-slice, unknown, missing-provenance, fallback/default,
  `create_new`, conflicting-mapping, and unsupported-Source outcomes create or
  update one active Job Taxonomy Review Item and create no assignment.
- Automatic evaluation writes assignment or review, projection invalidation,
  and outbox rows in the caller's existing enrichment transaction. It never
  calls the human `GovernanceUnitOfWork` and never commits internally.
- Retire or fail closed every `normalize_category`/`governance_override`/
  `_get_or_create_path` production path that can create or authoritatively
  assign legacy taxonomy nodes.

### R4 — Assignment, Unassigned, and review state

- A Job has at most one current Canonical Taxonomy Assignment and at most one
  active Job Taxonomy Review Item. A new evidence version replaces/supersedes
  the current evaluation state deterministically without erasing audit history.
- Unassigned means no current accepted assignment. A Job not yet evaluated may
  be Unassigned without a Review Item; every unresolved evaluated invalid/
  uncertain outcome has an active item with constrained reason(s), evidence,
  recommendations, and `lock_version`. An operator decision of insufficient
  evidence closes that item while leaving the Job Unassigned and retaining its
  review/audit history.
- Local-operator actions are `assign_existing_subcategory` and
  `mark_insufficient_evidence`. Neither action creates, edits, or reparents a
  taxonomy node.
- Decisions require confirmation, expected version, idempotency key, existing
  active revision/target validation, append-only audit, and transactional
  outbox. Exact replay returns the original result; conflicting replay/stale
  state changes nothing.

### R5 — Reads, filters, and downstream projections

- Versioned `/api/v1/job-intelligence` reads expose active tree/revision,
  assigned versus Unassigned Job state, review reasons/refs, stable IDs/codes,
  breadcrumbs, provenance, versions, audit/deep-link IDs, and deterministic
  pagination/counts.
- New versioned Job Intelligence responses and canonical filter builders read
  the assignment Module. Domain or Category filters expand governed
  descendants; values within a field are OR and different fields are AND.
  Legacy `jobs.subcategory_id` remains an explicitly named comparison adapter,
  never a second authority.
- Assignment changes enqueue invalidation for Job Intelligence read models and
  embeddings. This child builds the new read/filter/document contracts and
  fixtures but does not switch existing live product routes or rebuild the live
  embedding index; child 7 owns that cutover. Embedding documents include only
  accepted governed breadcrumbs and exclude fallback paths and review
  recommendations.
- This child exports backend response fixtures for child 6. Full governance UI,
  product-surface terminology cleanup, and dashboard redesign remain child 6.

### R6 — Dry-run rebuild and rollout safety

- Provide a deterministic read-only rebuild inspector over preserved Source Job
  Attributes, raw enrichment/classifier evidence, reviewed mapping release, and
  legacy `jobs.subcategory_id` comparison evidence.
- Report accepted-by-method, review-by-reason, mapping coverage/conflicts,
  legacy disagreement, missing model/mapping provenance, and unrecoverable
  parser evidence. Do not claim legacy fallback rows are governed assignments.
- Add schema and runtime Modules only. Do not migrate live legacy assignments,
  activate a live release, run corpus rebuild, delete old nodes, or switch the
  live contract in this child. Child 7 owns quiescence, snapshot, rebuild,
  reconciliation, cutover, and rollback.

## Acceptance Criteria

- [ ] AC-R1: A validated explicit-code seed publishes an immutable replacement
  release with exactly 25 Domains/63 Categories/198 Subcategories and no
  `General → General` nodes; its active pointer cannot reference partial/
  orphan/duplicate materialization, and rename/reparent tests prove codes do
  not drift.
- [ ] AC-R2: Mapping publication pins published Source Catalog revisions,
  validates exact identity coverage, exclusive disposition cardinality, and
  stable-code targets, reports the 15-ID CTgoodjobs legacy discrepancy without
  promoting it to authority, and passes a deterministic multi-path truth-table
  test matrix.
- [ ] AC-R3: Reviewed mapping and valid constrained-AI outcomes assign only
  existing assignable Subcategories with complete provenance; every invalid/
  fallback/default/create-new/missing-provenance branch produces review and no
  legacy/new node write.
- [ ] AC-R4: PostgreSQL tests prove one current assignment/one active review,
  same-revision FKs, immutable nodes, replacement idempotency, decision stale/
  confirmation/target/replay behavior, and assignment/review/audit/outbox
  atomicity across two Sessions.
- [ ] AC-R5: Versioned Job/API/filter/embedding contracts distinguish assigned
  from Unassigned, use stable governed identity, exclude legacy/fallback
  authority, export real backend fixtures, and architecture tests prove this
  child does not switch existing live product consumers.
- [ ] AC-R6: The dry-run report is deterministic, performs zero writes,
  classifies legacy comparisons honestly, and no live migration/backfill/
  activation/cutover command is exposed by this child.

## Dependencies and out of scope

- Depends on the completed Foundation and Source Job Attributes contracts.
- Governance UI and broad product-surface migration are child 6; destructive
  seed/assignment rebuild and live cutover are child 7.
- Source Catalog discovery/publication, Source Crawl Scope, Company Industry,
  Skill Governance, authentication/RBAC, and live corpus mutation are out of
  scope.

## Notes

- Complex child: planning must converge and receive user activation review
  before `task.py start`.
