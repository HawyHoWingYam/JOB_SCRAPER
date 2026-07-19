# Canonical job taxonomy governance design

## Module boundary

```text
CanonicalTaxonomyPublisher.validate(seed, mapping_seed) -> ValidationReport
CanonicalTaxonomyPublisher.materialize(validated_release) -> ReleaseRef
CanonicalJobTaxonomy.evaluate(db, job_id, evidence, classifier_output?) -> EvaluationResult
CanonicalJobTaxonomy.get_job_state(job_id) -> TaxonomyStateView
CanonicalJobTaxonomy.build_filters(query) -> SQL predicates
CanonicalJobTaxonomy.inspect_rebuild(job_ids?) -> RebuildReport
CanonicalTaxonomyDecisionAdapter.decide(DecisionCommand) -> DecisionResult
```

The automated `evaluate` seam accepts evidence and returns one complete state
transition but never commits. The decision adapter is the only human mutation
seam and delegates transaction/audit/idempotency/concurrency to Foundation.
Neither seam creates taxonomy nodes.

## Authority and replacement-table decision

The existing `job_domains`, `job_categories`, `job_subcategories`, and
`jobs.subcategory_id` are legacy evidence. They remain untouched because all
live nodes are AI-created, Job FKs bind their UUIDs, name-only uniqueness is not
revision-safe, and existing cascade/delete behavior is incompatible with
immutable governed history.

The Canonical Module owns additive tables:

- `canonical_job_taxonomy_active_revisions`: singleton active pointer with
  compare-and-swap version/fingerprint;
- `canonical_job_domains`: revision, stable code, label snapshot, source order;
- `canonical_job_categories`: same-revision Domain FK, stable code, label/order;
- `canonical_job_subcategories`: same-revision Category FK, stable code,
  label/order, explicit `is_assignable`;
- `canonical_job_taxonomy_mapping_revisions`: immutable reviewed mapping release
  identity bound to one taxonomy revision;
- `canonical_job_taxonomy_mapping_coverages`: one pinned immutable Source
  Catalog revision per covered Source, including revision ID/sequence,
  fingerprint, and mapping-eligible identity set hash/count;
- `source_job_taxonomy_mappings`: mapping revision, Source-qualified
  classification ID, exclusive disposition, evidence/provenance, and coverage
  FK;
- `source_job_taxonomy_mapping_targets`: mapping and canonical Subcategory FK,
  role `deterministic` or `allowed`;
- `canonical_job_taxonomy_active_mapping_revisions`: active reviewed mapping
  pointer;
- `job_taxonomy_assignments`: one current row per Job, canonical Subcategory/
  taxonomy revision, method, mapping/model/evidence provenance, version;
- `job_taxonomy_review_items`: durable review history with one partial-unique
  active row per Job, constrained status/reasons, evidence/recommendations,
  version, decision/audit reference.

Composite FKs prove every Domain→Category→Subcategory relation belongs to the
same taxonomy revision. Mapping targets prove the mapping and node revision
match. Active assignment targets are `RESTRICT`; Job deletion cascades current
assignment/review projections but governance audit retains snapshots.

## Seed manifest and stable codes

`job_category_taxonomy.json` becomes an explicit-code manifest with 25 Domains,
63 Categories, and 198 assignable Subcategories. The conversion removes every
exact `General` Category and its `General` leaf; it does not represent the 25
fallback paths as non-assignable compatibility/navigation nodes. Category and
Subcategory string values become objects with `code`, `label`, `order`, and
where relevant `is_assignable`. Bootstrap tooling may generate the initial code
from the normalized full path once; the committed result becomes authority.
Publication never generates codes, and later label/parent changes must carry
the previous code explicitly or intentionally create a new concept.

The normalized revision hash covers node codes, parent codes, labels,
assignability, and order. Validation accumulates and deterministically sorts all
count mismatch, duplicate code, duplicate sibling label, orphan parent, invalid
assignability, exact `General`/`Unknown` fallback node, and mapping-reference
errors before any write. Legacy default paths ending in `General → General`
remain diagnostics only and fail as mapping targets.

Foundation `RevisionStore.publish` commits revision identity independently.
The domain publisher therefore materializes nodes as inactive and flips the
canonical active pointer only after one domain transaction validates exact
counts/content hash/FKs. A failed materialization leaves at most an inactive
revision identity; exact retry resumes it and no reader treats it as authority.

## Mapping release and multi-path policy

Mapping authority is separate from Source evidence and Crawl Scope. Each entry
has one disposition:

- `deterministic`: one existing assignable Subcategory target;
- `allowed_slice`: one or more existing assignable targets available to
  constrained AI;
- `excluded`: explicitly unsupported for automated canonical assignment;
- `unmapped`: preserved evidence that requires review.

The disposition is mutually exclusive. A `deterministic` entry has exactly one
`deterministic` target row and no `allowed` rows; an `allowed_slice` entry has
one or more unique `allowed` rows and no deterministic row; `excluded` and
`unmapped` have no target rows. All targets are assignable stable codes in the
mapping release's pinned taxonomy revision and sort by canonical node order.

Each mapping coverage resolves an immutable published Source Catalog revision
and stores its revision UUID, sequence, fingerprint, and the deterministic
hash/count of every source-qualified identity that can be emitted as a Source
Classification Path. Publication recomputes the catalog fingerprint and exact
identity set, rejects missing/extra/duplicate mapping entries, and fails with
`CATALOG_NOT_PUBLISHED` when a covered Source has no published revision. Before
an active mapping pointer flip, compare-and-swap validation proves those
catalog revisions are still the active Source revisions; a catalog change
therefore requires reviewed mapping republication rather than a runtime guess.

Initial authoring tooling may compare legacy fixtures and report that
`CTGOODJOBS_CATEGORY_MAPPINGS` mentions 15 IDs absent from the 12 CTgoodjobs
entries in `job_source_taxonomy_mapping.json`, but neither constant defines
coverage. Only a pinned Source Catalog snapshot does. Legacy `default_path` and
`proposed_internal_domain` fields remain review evidence and are never promoted
automatically.

For all Source Classification Paths on one Job:

1. collect mapping entries by source-qualified node identity in source order;
2. if any identity is missing or has `excluded`/`unmapped` disposition, create
   review before considering an automatic outcome;
3. if deterministic targets disagree, create `conflicting_mapping` review;
4. union and de-duplicate all allowed-slice targets by canonical order;
5. if one convergent deterministic target exists, accept it only when the
   allowed union is empty or contains that target; otherwise create conflict
   review;
6. with no deterministic target, accept an AI target only when a non-empty
   allowed union contains it; otherwise create review.

No path order implies stronger canonical authority.

| Complete path evidence | Automatic outcome |
| --- | --- |
| Convergent deterministic only | Assign `reviewed_mapping` |
| Convergent deterministic + compatible allowed union | Assign `reviewed_mapping` |
| Conflicting deterministic or incompatible allowed union | Review conflict |
| Allowed slices only, valid in-union AI target | Assign `constrained_ai` |
| Allowed slices only, missing/invalid/out-of-union AI target | Review |
| Any missing, `excluded`, or `unmapped` entry | Review |
| No Source Classification Paths | Review |

## Evaluation state machine

`evaluate` validates the active taxonomy/mapping revisions and a normalized
evidence hash before mutation.

```text
unassigned(not evaluated; no review item)
  -> assigned(reviewed_mapping | constrained_ai)
  -> unassigned(evaluated; review pending)

assigned
  -> exact replay (no-op)
  -> replacement assignment
  -> unassigned(evaluated; new evidence invalidates old assignment, review pending)

unassigned(evaluated; review pending)
  -> exact replay (no-op)
  -> updated/superseding review
  -> assigned(new valid evidence or operator decision)
  -> unassigned(insufficient evidence decided; no active review)

unassigned(insufficient evidence decided; no active review)
  -> exact decision replay (no-op)
  -> assigned(new valid evidence)
  -> unassigned(evaluated; new review pending)
```

There is at most one current assignment and one active review item. Automatic
evaluation owns no human audit event; it stores typed provenance and enqueues a
bounded projection/embedding invalidation event in the caller's transaction.
Exact evidence/outcome replay emits no duplicate event.

Fallback/default, `create_new`, out-of-slice, invalid target, missing model/
mapping provenance, conflicting deterministic mapping, excluded/unmapped
Source evidence, and malformed classifier output are explicit review reasons.
They never invoke legacy `_get_or_create_path`.

## Human decisions

The domain transition passed to `GovernanceUnitOfWork` owns:

- subject: active `job_taxonomy_review_item`;
- actions: `assign_existing_subcategory`, `mark_insufficient_evidence`;
- target validation: active assignable Subcategory from the current taxonomy
  revision;
- version: review item's `lock_version`;
- effects: assignment/review state, bounded evidence refs, projection result,
  and assignment/embedding invalidation outbox events.

Successful assignment resolves the active review. Insufficient evidence closes
the item without creating an assignment. Taxonomy revision proposals are a
separate future workflow; an item cannot edit nodes.

## Writer integration and retired legacy seam

`AIEnrichmentService` continues to own the outer transaction. It passes Source
Job Attributes plus normalized classifier/model evidence to `evaluate`, then
commits assignment/review/outbox with the rest of accepted enrichment.

Production calls to `JobCategoryNormalizer.normalize_category`,
`resolve_taxonomy_decision`, `governance_override`, and `_get_or_create_path`
are removed or changed to fail closed. `jobs.subcategory_id` is never written by
new code. The old three tables and UUID remain readable only by a named legacy
comparison adapter and rebuild inspector until child 7.

## Read/API/filter contracts

New versioned routes live below `/api/v1/job-intelligence`:

```text
GET  /canonical-job-taxonomy/revision
GET  /canonical-job-taxonomy/tree
GET  /jobs/{job_id}/canonical-taxonomy
GET  /governance/job-taxonomy/review-items
GET  /governance/job-taxonomy/review-items/{id}
POST /governance/job-taxonomy/review-items/{id}/decision
```

Job state is either `{state:"assigned", assignment:{...}}` or
`{state:"unassigned", reasons:[], review_item_refs:[]}`. Tree and assignment
views expose stable IDs/codes, labels, breadcrumbs, revision, assignability,
method/provenance, version, and deep-link IDs. The initial tree contains the
25/63/198 governed counts and never exposes removed `General → General` nodes.

The Module exports opt-in canonical filter builders that join
`job_taxonomy_assignments`; Subcategory codes/IDs match directly, while
Category/Domain filters expand descendants inside the pinned active revision.
The new versioned Job Intelligence routes and fixtures exercise those builders.
Existing live Job API/filter consumers remain on their compatibility contract
until child 7 performs the coordinated authority switch; raw labels and
`jobs.subcategory_id` never become an independent canonical predicate.

## Embedding and outbox

The Module exports an embedding-document projection in which accepted
assignment breadcrumbs enter together with revision and method metadata
suitable for diagnostics. Review recommendations, legacy assignments, and
non-assignable/fallback nodes are excluded. This child enqueues invalidation and
tests the document contract; child 7 switches/rebuilds the live embedding index.

Assignment creation/replacement/removal and operator decisions enqueue bounded
events through existing `event_outbox` with `auto_commit=False`. Failure to
enqueue rolls back the current state transition; downstream embedding work is
retryable from the outbox.

## Rebuild inspector and rollout

The child exposes only a read-only inspector. It pins taxonomy and mapping
revision hashes, bulk-loads Source Job Attributes/raw classifier evidence and
legacy comparison rows, and deterministically reports:

- assignments by `reviewed_mapping` and `constrained_ai`;
- review counts by constrained reason;
- Source mapping coverage, missing dispositions, and conflicts;
- legacy agreement/disagreement and auto-created/fallback history;
- missing model/mapping provenance and unrecoverable evidence.

No apply/execute/live-activation flag exists. Application rollback ignores the
additive tables and resumes legacy reads; populated immutable/audit data is not
downgraded or deleted. Child 7 owns live backup, quiescence, activation,
backfill, reconciliation, contract switch, and rollback rehearsal.

## Important trade-offs

- Replacement tables cost an additional read adapter but prevent AI-created
  legacy UUIDs/cascade rules from becoming governed identity.
- Removing the 25 `General → General` paths gives up compatibility navigation
  through those fallback nodes; explicit Unassigned/review state and the named
  legacy comparison adapter preserve the useful diagnostic information without
  granting fallback authority.
- Separate taxonomy and mapping releases allow mapping review without relabeling
  taxonomy nodes, while assignments retain both provenance dimensions.
- Pinning mapping coverage to immutable Source Catalog revisions makes catalog
  drift explicit without turning canonical mapping into Crawl Scope authority.
- One active review item per Job makes Unassigned state stable; constrained
  reasons are accumulated instead of creating competing queues.
- An inactive orphan Foundation revision identity is acceptable; a partially
  materialized/active Canonical Taxonomy release is not.
