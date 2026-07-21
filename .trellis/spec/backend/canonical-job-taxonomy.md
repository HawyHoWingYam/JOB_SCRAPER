# Canonical Job Taxonomy Governance

## Scenario: Govern stable Job Taxonomy assignments without legacy fallback authority

### 1. Scope / Trigger

Use this contract when changing the Canonical Job Taxonomy seed or mapping
manifest, canonical publication/evaluation/decision Modules, AI classifier
preflight, `/api/v1/job-intelligence` taxonomy routes, canonical filters or
embedding documents, the rebuild inspector, or migration constraints.

The replacement Module owns governed Domain → Category → Subcategory identity,
reviewed Source-to-Canonical mappings, accepted assignments, and unresolved
review state. `job_domains`, `job_categories`, `job_subcategories`, and
`jobs.subcategory_id` are legacy comparison evidence until the cutover child;
they are never canonical write/filter/embedding authority.

This child may materialize inactive releases in explicit tests/operator code,
but exposes no live activation, migration, backfill, rebuild-apply, or cutover
command. Live corpus activation and consumer switching belong to the cutover
child.

### 2. Signatures

The publication and evaluation seams are:

```python
CanonicalTaxonomyPublisher.validate(seed, mapping_seed=None) -> ValidationReport
CanonicalTaxonomyPublisher(db).materialize(seed) -> RevisionRef
CanonicalTaxonomyPublisher(db).activate(
    revision,
    expected_lock_version: int,
) -> CanonicalJobTaxonomyActiveRevision
CanonicalTaxonomyPublisher(db).materialize_mapping(
    taxonomy_seed,
    mapping_seed,
) -> RevisionRef
CanonicalTaxonomyPublisher(db).activate_mapping(
    revision,
    expected_lock_version: int,
) -> CanonicalJobTaxonomyActiveMappingRevision

CanonicalTaxonomyPreflight(db).inspect(job) -> CanonicalTaxonomyPreflightResult
CanonicalJobTaxonomy(db).evaluate(
    job_id,
    source_attributes,
    classifier_output=None,
) -> CanonicalEvaluationResult
CanonicalTaxonomyDecisionAdapter(db).decide(command) -> DecisionResult
```

Read contracts are:

```python
CanonicalJobTaxonomy(db).get_active_revision() -> CanonicalRevisionView
CanonicalJobTaxonomy(db).get_tree() -> CanonicalTreeView
CanonicalJobTaxonomy(db).get_job_state(job_id) -> CanonicalJobStateView
CanonicalJobTaxonomy(db).list_review_items(query) -> CanonicalReviewPage
CanonicalJobTaxonomy(db).build_filters(query) -> tuple[SQL predicate, ...]
CanonicalJobTaxonomy(db).build_embedding_document(job_id) -> document | None
CanonicalTaxonomyRebuildInspector(db).inspect(job_ids=None) -> report
```

Versioned HTTP routes are:

```text
GET  /api/v1/job-intelligence/canonical-job-taxonomy/revision
GET  /api/v1/job-intelligence/canonical-job-taxonomy/tree
GET  /api/v1/job-intelligence/jobs/{job_id}/canonical-taxonomy
GET  /api/v1/job-intelligence/governance/job-taxonomy/review-items
GET  /api/v1/job-intelligence/governance/job-taxonomy/review-items/{id}
POST /api/v1/job-intelligence/governance/job-taxonomy/review-items/{id}/decision
```

PostgreSQL integration and migration tests require an explicitly disposable
database whose name ends in `_test`:

```text
JOB_INTELLIGENCE_TEST_DATABASE_URL=postgresql://.../<dedicated_test>
```

Never point this variable, Alembic downgrade/re-upgrade rehearsal, or raw
constraint tests at the live development corpus.

### 3. Contracts

#### Stable seed and release lifecycle

- The committed initial seed contains explicit immutable codes and exactly 25
  Domains, 63 Categories, and 198 assignable Subcategories. Exact `General`
  and `Unknown` fallback nodes are forbidden.
- Codes are manifest identity. Publication never derives them from labels or
  parentage; rename/reparent revisions retain a code only when the author
  carries it explicitly.
- `RevisionStore.publish` may commit the immutable Foundation identity before
  domain materialization. The canonical release remains `materializing` while
  nodes are inserted. A failed transaction may leave only the Foundation
  identity; exact retry reuses it.
- PostgreSQL permits taxonomy/mapping content INSERT only while its release is
  `materializing`. Transition to `ready` recomputes real row counts and requires
  them to equal both expected and recorded materialized counts. Ready content
  cannot be inserted, updated, or deleted.
- Active taxonomy and mapping pointers use compare-and-swap lock versions,
  reference only matching ready releases, and cannot be deleted to reset the
  CAS version. Same-revision composite FKs and unique constraints reject
  orphan/duplicate hierarchy and mapping rows.

#### Reviewed mapping authority

- One mapping release pins one published immutable Source Catalog revision per
  covered Source by revision ID, sequence, fingerprint, identity-set hash, and
  identity count. Materialization reconstructs the persisted catalog and fails
  closed on publication absence, fingerprint drift, or missing/extra identity
  coverage.
- Every mapping-eligible Source classification has exactly one disposition:
  `deterministic`, `allowed_slice`, `excluded`, or `unmapped`.
  `deterministic` has one target, `allowed_slice` has one or more targets, and
  `excluded`/`unmapped` have none. Targets are existing assignable stable codes
  in the pinned taxonomy revision.
- Legacy `default_path`, proposed-domain constants, labels, and static
  registries are evidence only. The 15 CTgoodjobs proposal-only IDs remain an
  explicit warning; when those identities are present in the pinned active
  Source Catalog they receive explicit `unmapped` entries and block automation.
- Hierarchical Source catalogs require an explicit entry for every non-alias
  classification identity. OfferToday child entries may inherit the reviewed
  parent root disposition and target slice only when the inherited slice is
  unchanged and the entry records the parent identity as review evidence.
- For all preserved paths: any missing/excluded/unmapped entry blocks
  automation; deterministic targets must converge; allowed targets form a
  canonical-order union; a convergent deterministic target must belong to that
  union when it is non-empty; AI can select only inside a non-empty union.
  Reversing path order never changes the policy outcome.

#### Assignment, review, and transaction ownership

- `evaluate` flushes but never commits. It writes an accepted assignment or an
  active review plus `job.canonical_taxonomy_changed` through the caller's
  transaction with outbox `auto_commit=False`.
- An accepted assignment points to one existing assignable Subcategory and
  records taxonomy revision, method, optional mapping revision/mapping IDs,
  Source evidence refs/hash, optional complete model provenance, capture time,
  version, and full breadcrumb.
- A Job has at most one current assignment and one active review. Changed
  evidence supersedes prior history; exact evidence/outcome replay is a no-op
  and emits no duplicate event.
- Blocking, invalid, fallback/default, `create_new`, missing-provenance,
  unknown-target, and out-of-slice outcomes create/update review and create no
  assignment or legacy/new taxonomy node.
- `AIEnrichmentService` is the outer transaction owner for automatic
  enrichment. Human `assign_existing_subcategory` and
  `mark_insufficient_evidence` actions use Foundation
  `GovernanceUnitOfWork`, confirmation, expected version, idempotency, audit,
  and transactional outbox.
- `JobCategoryNormalizer`, `JobTaxonomyRegistry`, governance override, and
  `_get_or_create_path` are retired fail-closed seams with no production call
  sites.

#### Reads, filters, embeddings, and rebuild

- Job state is explicitly `assigned` or `unassigned`; unevaluated Unassigned
  may have no review, while unresolved evaluated outcomes expose stable review
  reasons and deep-link IDs.
- Canonical filters join current `job_taxonomy_assignments`. Values within one
  field are OR, different fields are AND, and Domain/Category codes expand
  descendants inside the active revision. `jobs.subcategory_id` is excluded.
- Embedding documents require a current accepted assignment, contain only
  governed codes/labels/breadcrumb/revision/method, and exclude legacy
  fallback text and review recommendations.
- The rebuild inspector is deterministic and read-only. JSON and human output
  include accepted method, review status/reason, mapping coverage/conflicts,
  legacy comparison, classifier/mapping provenance, Source Attribute rebuild,
  and unrecoverable parser evidence. Its CLI rejects apply/execute/activate
  modes.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Seed count/code/order/parent/assignability/fallback invalid | Deterministic validation issues; no domain writes |
| Same Foundation release key/hash replay | Reuse original revision; exact materialization retry is safe |
| Ready transition counts differ from actual rows | PostgreSQL rejects transition; no active pointer |
| INSERT/UPDATE/DELETE content after ready | PostgreSQL immutability error |
| Active pointer targets materializing/orphan/hash-mismatched release | Reject before pointer mutation |
| Active pointer CAS version is stale or pointer DELETE attempted | Activation conflict / PostgreSQL rejection |
| Covered Source has no published catalog | `CATALOG_NOT_PUBLISHED` |
| Persisted catalog payload fingerprint differs from revision | `CATALOG_FINGERPRINT_MISMATCH` |
| Mapping identities are missing or extra | `CANONICAL_MAPPING_COVERAGE_MISMATCH` with stable sets |
| Deterministic targets conflict or disagree with allowed union | Review `conflicting_mapping`; no assignment |
| Any path is excluded/unmapped/missing | Stable review reason; no LLM assignment |
| AI output is fallback/default or `create_new` | Review `fallback_output` / `create_new_forbidden` |
| AI provenance incomplete, target unknown, or outside allowed union | Stable review reason; no assignment |
| Exact evaluation replay | Same result/version; no duplicate assignment/review/outbox |
| Decision unconfirmed/stale/invalid target/conflicting replay | Stable governance error; no partial writes |
| Rebuild CLI receives `--apply`, `--execute`, or `--activate` | Argument error; zero writes |

### 5. Good / Base / Bad Cases

- **Good:** two deterministic Source paths converge on one stable code; the
  evaluator records both mapping IDs and one reviewed-mapping assignment.
- **Good:** a deterministic target plus an allowed slice assigns only when the
  target belongs to the union, independent of path order.
- **Base:** a Job has not been evaluated. It is Unassigned with no fabricated
  reason or review item.
- **Base:** an operator marks insufficient evidence. The active review closes,
  audit/outbox persist atomically, and the Job remains Unassigned.
- **Bad:** treating `default_path`, `General`, a legacy UUID, or the first Source
  path as an automatic target.
- **Bad:** adding a node after a release is ready, committing inside
  `evaluate`, or passing `GovernanceUnitOfWork` to an enrichment worker.

### 6. Tests Required

- `test_canonical_job_taxonomy_governance.py`: explicit 25/63/198 seed,
  fallback absence, failed materialization rollback/exact retry, rename and
  reparent stable codes, exact catalog fingerprint/coverage, complete
  multi-path truth table with forward/reverse order, assignment/review replay
  and replacement, invalid classifier branches, outbox rollback, two-Session
  evaluation, operator audit/idempotency, AI preflight, and zero-write rebuild.
- `test_canonical_job_taxonomy_migration.py`: static local-column/FK/unique
  inspection plus real Alembic-applied PostgreSQL upgrade/downgrade/re-upgrade;
  ready count guards, content INSERT/UPDATE/DELETE immutability, partial/orphan/
  duplicate active pointer rejection, same-revision FK rejection, one-current/
  one-active partial unique indexes, and all ten triggers.
- `test_canonical_job_taxonomy_api.py`: versioned typed reads, assigned versus
  Unassigned, stable pagination, OR/AND descendant filters, canonical-only
  embeddings, decision failure/atomicity, real route-response fixture JSON
  roundtrip, committed backend fixture roundtrip, and no live-consumer switch.
- `test_job_taxonomy_registry.py` and architecture assertions: retired seams
  fail closed and no production legacy node writer remains.
- Run PostgreSQL tests only with `JOB_INTELLIGENCE_TEST_DATABASE_URL` pointing
  to a dedicated `*_test` database. Because combined collection can leave
  incompatible fixture schemas, run backend test files individually when the
  documented collection interaction appears.

### 7. Wrong vs Correct

#### Wrong

```python
normalized = legacy_normalizer.normalize_category(classifier_output)
job.subcategory_id = normalized.subcategory_id
db.commit()
```

This can create/fallback to mutable legacy nodes, loses mapping/model/evidence
provenance, and commits outside assignment/review/outbox policy.

#### Correct

```python
source_view = SourceJobAttributes(db).get(job.id)
context = CanonicalJobTaxonomy(db).build_classifier_context(source_view)
classifier_output = (
    None if context.blocking_reasons else run_constrained_classifier(context)
)
result = CanonicalJobTaxonomy(db).evaluate(
    job.id,
    source_view,
    classifier_output,
)
# The outer enrichment transaction commits Job fields, canonical state,
# and outbox together.
db.commit()
```

The classifier sees only governed allowed targets, `evaluate` remains
flush-only, and every accepted or unresolved outcome retains reproducible
provenance.
