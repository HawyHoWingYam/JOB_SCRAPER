# Source job attributes design

## Module Interface

```text
SourceEvidenceAdapter.extract(stored_or_live_payload, crawl_context?) -> SourceJobAttributeEvidence
SourceJobAttributes.project(db, job_id, source_evidence) -> ProjectionResult
SourceJobAttributes.get(job_id) -> SourceJobAttributesView
SourceJobAttributes.build_filters(query) -> SQL predicates
SourceJobAttributes.inspect_rebuild(job_ids) -> RebuildReport
```

Source adapters produce one typed evidence value before current canonical
scalarization can discard arrays; they do not write ORM rows directly. The
Module owns validation, normalization, deterministic hashing, transactional
replacement/idempotency, reads, and filters. `project` flushes but never commits,
so its caller owns the surrounding Job/projection/outbox transaction.

Automated projection reuses Foundation `Provenance`, normalized JSON/hash
helpers, and explicit `OutboxEvent` shape. It deliberately does not use
`GovernanceUnitOfWork`, `DecisionCommand`, `DecisionTransition`, human audit, or
governance idempotency. `source_service` is `source-job-attributes`, not the
Foundation governance default.

## Evidence shape

```text
source_site
classification_paths[]
  nodes[]: source-qualified id, native id?, label, source position, native depth
  source_order
  source_declared_primary + primary_basis?
  source_catalog_revision?: source, revision UUID, fingerprint
  provenance: method, bounded evidence refs, captured time

employment_labels[]
  raw_code?, raw_label?, source_order, provenance

work_arrangements[] and working-day evidence remain separate
```

`SourceCatalogRevisionRef` is a domain-owned value for the independent Source
Catalog table. It is not Foundation `RevisionRef`. When known, its UUID must
resolve to an immutable `source_catalog_revisions` row whose `source_site`
matches the evidence Source; when unknown it is `None` and the read model marks
the path provenance-limited.

An adapter emits all paths/labels present in the best available raw payload.
Empty means “Source provided none,” not an implicit fallback to the crawl
request. CTgoodjobs may use its crawl/detail category context only when it is
explicitly tagged as weaker `crawl_context` provenance. Evidence refs contain
bounded scalar locations/hashes, not duplicated response bodies, cookies,
sessions, or secrets; full raw payload remains in existing raw/staging storage.

## Source adapters

- JobsDB: iterate all `classifications`; preserve classification/subclassification nodes. Preserve every `workTypes` value. Keep `workArrangements` separate.
- CTgoodjobs: preserve the crawl/detail Source Classification path; do not invent a subclassification. Parse all work-type values from the existing precedence chain.
- OfferToday: iterate all `jobFunctions` and all children, de-duplicate identical full paths without losing first source order. Preserve `jobType` code and `jobTypeDesc`/`employType` labels.

No adapter marks Primary unless its upstream contract contains an explicit primary signal. Array position is never such a signal.

During live collection, `CanonicalScrapedJob` carries a serialized
`source_attribute_evidence` member so the ingest event transports complete
arrays alongside transitional legacy scalars. JobsDB/CTgoodjobs parsers and
staging must retain the raw fields needed to build that member; reconstructing
it after `_join_work_types` or `[0]` selection is forbidden.

## Persistence

### Projection anchor

- `job_source_attribute_projections`: one row per Job, Job FK `CASCADE`, Source,
  normalized evidence hash, integer version, captured timestamp.
- `project` locks the Job/anchor, compares the normalized hash, and replaces
  children only when content changed. This makes exact replay a no-op and gives
  concurrent writers one serialization point.

### Classification paths

- `job_source_classification_paths`: UUID, projection/Job FK `CASCADE`, Source,
  nullable Source Catalog revision UUID FK `RESTRICT`, source order, path
  fingerprint, explicit-primary bool/basis, bounded provenance JSON, captured
  timestamp.
- `job_source_classification_path_nodes`: path FK `CASCADE`, source position,
  native depth, source-qualified ID, native ID snapshot, label snapshot.
- Unique Job/path fingerprint and Job/source-order constraints prevent duplicate
  paths; unique node position/identity constraints prevent malformed paths; a
  partial unique Job Primary index prevents conflicting explicit primaries.
- Check constraints require a non-empty primary basis iff Primary is true and
  require each source-qualified node ID to belong to the path Source.
- Node identity/Source, Job/path order, and catalog revision are indexed;
  response order is `(source_order, node position)`.

### Employment

- `employment_types`: seven seeded codes, display labels, and stable ordering.
- `job_source_employment_labels`: projection/Job FK `CASCADE`, Source, source
  order, raw code/label, nullable normalized lookup key, nullable mapped type FK,
  mapping ID, and provenance. A check requires at least a raw code or label.
- `job_employment_types`: composite Job/type PK with deterministic provenance
  references to the label rows that produced it.
- Mapping registries are domain-owned, explicit per Source, and deterministic.
  The union of mapped label results produces the projection. Unknown labels stay
  only in evidence rows; there is no `unknown`/`other` governed row.

## Projection replacement

For one Job, project in one transaction:

1. Normalize and validate all evidence.
2. Flush/lock the Job and projection anchor, then compare the normalized evidence
   hash to the current projection.
3. Return the current view with `changed=false` on exact replay.
4. On change, replace path/node and employment child rows, update the anchor
   hash/version, and enqueue one `job.source_attributes_changed` outbox row with
   `auto_commit=false`.
5. Preserve historical/raw evidence through Job raw data, staging payloads, and
   the later immutable migration snapshot; runtime tables represent current
   source evidence.
6. Let the outer writer commit Job, projection, and outbox once. Any validation,
   constraint, serialization, or enqueue failure rolls back all effects.

All authoritative Job writers—stream ingest, standalone/detail persistence,
repair, and future backfill—must call this seam. New writer payloads omit legacy
source classification/subclassification/`employment_type` updates. Legacy
columns are queried only by compatibility/rebuild readers until child 7.

## Read/API contracts

Job list/detail responses add `source_classification_paths[]` and
`employment_types[]`. Detail/evidence responses additionally include ordered
`source_employment_labels[]`; ordinary list responses omit verbose provenance.
Missing evidence is represented by empty arrays. A path view contains ordered
nodes, `is_primary`, `primary_basis`, source order, nullable catalog revision,
and `provenance_limited`.

Filter input uses arrays:

- `source_classification_ids[]` matches any path node by source-qualified identity.
- `employment_type_codes[]` matches any governed type code.
- OR within a field; AND across source classification/employment/other fields.

The structured POST body uses JSON arrays; GET uses repeated query parameters.
Empty/missing arrays apply no predicate. Unknown Employment Type codes fail
validation rather than becoming raw strings. Source identity remains part of
every classification option; display names are never option keys.

`GET /jobs/filters` returns Employment Type `{code,label,order}` options and
source classification `{id,label,source,path}` options derived from current
projections. A temporary scalar `employment_type` request adapter may normalize
one recognized legacy display label into `employment_type_codes=[code]`, but it
must share the new predicate and be marked deprecated; comma splitting and
direct `Job.employment_type == value` are removed from authoritative search.

## Compatibility and rebuild

- Expand schema first; authoritative runtime writes go through the Module.
- Legacy scalar fields remain unchanged/read-only until cutover.
- The inspector chooses evidence deterministically from the newest usable
  detail/listing staging payload and `Job.raw_data`; legacy columns are weaker
  comparison evidence only and never reconstruct missing arrays.
- Dry-run reports per Source: evidence-source distribution, path-count
  distribution, recoverable multi-path rows, explicit-primary evidence,
  employment mappings, unknown/malformed labels, legacy disagreement, missing
  catalog revision, provenance limitation, and already-unrecoverable rows.
- This child's CLI has no apply/live-write flag. It emits a deterministic
  machine-readable report plus human summary and proves the inspected database
  did not change.
- Historical missing Source Catalog Revision is allowed and visible; later linking is a separate reviewed backfill.

## Testing and indexes

- Fixture tests first reproduce existing JobsDB/OfferToday `[0]` truncation and
  JobsDB/CTgoodjobs comma joining, then cover multi-path/multi-child/duplicate
  aliases and multi-label employment for every Source.
- PostgreSQL tests cover source/catalog matching, uniqueness, Primary checks,
  concurrent/exact replacement idempotency, Job/projection/outbox atomicity,
  filter semantics, revision delete restriction, and Job deletion cascade.
- Architecture tests forbid worker imports/injection of Foundation decision
  Interfaces and forbid adapter ORM writes.
- Writer contract tests inventory every source-attribute write path and fail if
  a new path bypasses the Module or updates legacy attribute scalars.
- Indexes: path node ID/source, Job/path order, employment type/Job, raw normalized label/source.
- API schema fixtures are exported for product-surface consumer tests.

## Rollout and rollback

- Apply/rehearse the migration only on disposable PostgreSQL in this child;
  never migrate or rebuild the live corpus.
- Application rollback stops new projection calls and lets old code ignore the
  additive tables. Do not delete populated projection/evidence tables or Source
  Catalog references.
- Child 7 owns quiescence, immutable legacy snapshot, live backfill/apply,
  reconciliation, contract switch, rollback rehearsal, and eventual legacy
  cleanup.
