# Source Job Attribute Contracts

## Scenario: Preserve and project source-owned Job classifications and employment evidence

### 1. Scope / Trigger

Use this contract when changing JobsDB, CTgoodjobs, or OfferToday parsing;
collected-Job writers; Source Classification or Employment Type persistence;
Job response/filter APIs; the Job Browser filter consumer; or historical rebuild
inspection.

Source Classification Paths belong to one external Source. They are not the
Canonical Job Taxonomy. Employment Type is the governed seven-code attribute;
Work Arrangement and working-day labels remain separate evidence.

### 2. Signatures

The executable Module boundary is:

```python
SourceEvidenceAdapter.extract(payload, *, provenance, ...) -> SourceJobAttributeEvidence
SourceJobAttributes(db).project(job_id, evidence) -> ProjectionResult
SourceJobAttributes(db).get(job_id) -> SourceJobAttributesView
SourceJobAttributes.build_filters(
    source_classification_ids=[...],
    employment_type_codes=[...],
) -> tuple[SQL predicate, ...]
```

Collected writers use:

```python
job, action = JobRepository().upsert_source_job(
    db,
    job_payload_without_legacy_source_attributes,
    auto_commit=False,
)
SourceJobAttributes(db).project(job.id, source_attribute_evidence)
db.commit()
```

Public reads and filters are:

```text
GET  /api/v1/jobs/filters
GET  /api/v1/jobs/search?source_classification_ids=...&employment_type_codes=...
POST /api/v1/jobs/search
python backend/scripts/inspect_source_job_attributes.py --format json|human
```

Historical recovery uses:

```python
SourceJobAttributeRebuildInspector(db).inspect(job_ids=None) -> SourceJobAttributeRebuildReport
SourceJobAttributeRebuildInspector(db).recover(job_ids=None) -> tuple[RecoveredSourceJobAttribute, ...]

SourceCatalogProvenanceRepair(db).inspect(
    source_site, revision_id, job_ids=None, pending_only=True
) -> ProvenanceRepairReport
SourceCatalogProvenanceRepair(db).apply(
    report, expected_revision_id, expected_fingerprint, batch_size=100
) -> ProvenanceRepairApplyResult
SourceJobAttributes(db).repair_catalog_provenance(
    job_id, source_catalog_revision
) -> ProjectionResult
```

Persistence is owned by `job_source_attribute_projections`,
`job_source_classification_paths`,
`job_source_classification_path_nodes`, `job_source_employment_labels`,
`job_employment_types`, and the seven-row `employment_types` registry.

### 3. Contracts

#### Evidence and normalization

- Adapters emit every semantic Source Classification Path and every Source
  Employment Label in source order before scalar canonicalization can discard
  arrays. Array position never implies Primary.
- A Primary path requires an explicit upstream signal and a non-empty
  `primary_basis`. At most one path for a Job may be Primary.
- The governed Employment Type codes are `full_time`, `part_time`,
  `permanent`, `contract`, `temporary`, `internship`, and `freelance`.
  Unknown labels, `Other`, `N, A`, remote/hybrid/on-site, and working-day
  values map to no governed type.
- Malformed employment items are retained only as fixed bounded markers such
  as `<malformed:null>` or `<malformed:array>`. Never serialize the malformed
  object, array contents, cookies, sessions, or secrets into evidence rows.
  Markers have no lookup key, mapping, or governed Employment Type.

#### Transactions and persistence

- Every collected writer calls `upsert_source_job(..., auto_commit=False)` and
  `SourceJobAttributes.project(...)` on the same `Session`, then the outer
  writer commits once. Projection flushes but never commits.
- Exact normalized evidence replay is a no-op and emits no second
  `job.source_attributes_changed` outbox event. Changed evidence replaces the
  projection children and emits one event in the caller's transaction.
- Historical Source Catalog provenance repair is report-first and fail-closed:
  inspection reconstructs the selected immutable revision and validates its
  fingerprint and every stored Source classification identity before any
  write. Apply requires the reviewed revision ID/fingerprint, rechecks the
  active pointer inside each batch, fills only NULL path revision FKs through
  `SourceJobAttributes.repair_catalog_provenance`, and emits one projection
  outbox event per changed Job. Exact replay changes no path and emits no
  duplicate event.
- A PostgreSQL path-row lock query that uses `with_for_update()` must use
  `selectinload()` for nullable child/revision relationships. `joinedload()`
  creates an outer join that PostgreSQL rejects as a lock target.
- Collected payloads must omit legacy `employment_type` and scalar Source
  classification/subclassification keys. `create_job` and `upsert_job` are
  retired generic repository writers; `POST /api/v1/jobs` returns
  `410/COLLECTED_JOB_CREATE_RETIRED`. `POST /api/v1/jobs/manual` remains the
  explicit manual-only path.
- A Job owns one Source. Node IDs use `<source>:<opaque-token>`. Known Source
  Catalog revisions must belong to that Source and use `ON DELETE RESTRICT`;
  historical unknown revisions stay nullable and visible as
  `provenance_limited=true`. Deleting a Job cascades its projection.

#### Reads, filters, and compatibility

- Job responses expose `source_classification_paths[]` and
  `employment_types[]`; detail responses additionally expose ordered
  `source_employment_labels[]`. Missing evidence is `[]`, never a fabricated
  scalar or path.
- `source_classification_ids[]` and `employment_type_codes[]` use OR within
  each field and AND across fields. Display labels are not authoritative keys.
  `GET /jobs/filters` returns Employment Types as `{code,label,order}`.
- `FilterPanel` accepts both the current object option and a legacy string
  option. Its current single-select compatibility seam submits the label
  through the deprecated `employment_type` adapter, which immediately
  translates a recognized label into `employment_type_codes`. New product
  surfaces should submit codes directly and must not create another
  label-equality predicate.

#### Read-only rebuild inspection

- The inspector selects the newest usable staging detail payload, then staging
  listing payload, then `Job.raw_data`; legacy scalars are comparison evidence
  only and never reconstruct discarded arrays.
- Staging lookup deduplicates `(source_site, source_job_id)` keys in stable Job
  order and queries them in batches of at most 100 composite keys. Batch results
  are merged before the existing per-key freshness/UUID tie-break selection.
  Never emit one whole-corpus composite `IN` statement: PostgreSQL can raise
  `StatementTooComplex` before any evidence is inspected.
- Each per-Source report includes recoverable Job/path/label totals, mapped and
  unknown labels, explicit Primary paths, evidence-source and path-count
  distributions, ambiguity, legacy conflicts, missing revisions,
  provenance-limited Jobs, malformed Jobs, and an unrecoverable-cause
  distribution.
- Unrecoverable causes are `malformed_source_attribute_evidence`,
  `parser_discarded_to_legacy_scalars`, or `no_preserved_evidence`.
  `unrecoverable_jobs` and `provenance_limited_jobs` intentionally overlap.
  Marker evidence increments `malformed_jobs` but not
  `unknown_employment_labels`; ordinary unmapped strings still increment the
  unknown count.
- The CLI has no apply/execute mode, performs zero writes, and emits
  deterministic JSON or human output.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Adapter evidence Source differs from the Job | Reject before projection writes |
| Known catalog revision belongs to another Source | `ValueError`; roll back Job/projection/outbox |
| Primary has no non-empty basis or evidence has multiple Primaries | `ValueError`; no partial writes |
| Collected payload contains any legacy Source Job Attribute key | `ValueError` before database access |
| Authoritative ingest has no typed `source_attribute_evidence` | `InvalidIngestPayloadError(reason="missing_source_attribute_evidence")` |
| Generic `POST /api/v1/jobs` is called | HTTP 410 with `COLLECTED_JOB_CREATE_RETIRED` |
| Unknown Employment Type code or unrecognized legacy label filter | HTTP/Pydantic 422 validation failure |
| Exact evidence replay | `changed=false`; no duplicate outbox row |
| Provenance repair revision/source/fingerprint mismatch or active-pointer drift | Reject the inspection/apply; never rewrite an existing non-NULL path binding |
| Provenance repair sees an uncovered or incompatible identity/path | Report the stable blocker and keep the affected Job excluded |
| Provenance repair exact replay | `changed_jobs=0` for already-bound paths; no duplicate projection event |
| Malformed bounded label marker | Retain evidence, map no type, count malformed but not unknown |
| Historical evidence has no catalog revision | Keep the path queryable with `provenance_limited=true` |
| Historical lookup exceeds 100 distinct Source keys | Issue multiple bounded read-only staging SELECTs and merge to the same deterministic report/recovery result |

### 5. Good / Base / Bad Cases

- **Good:** a JobsDB listing with two classifications and `Full-time` plus
  `Permanent` persists both paths, both raw labels, two governed codes, and one
  outbox event in the Job transaction.
- **Base:** CTgoodjobs has one crawl-context root path and no explicit Primary;
  it remains a valid root-only path with nullable catalog history.
- **Good:** rebuild finds a newer malformed detail payload and an older usable
  detail payload. It reports the Job recoverable and malformed, records
  `staging_detail_payload`, and performs no writes.
- **Good:** a 17,596-Job dry run issues bounded composite-key staging lookups,
  preserves every core/raw fingerprint, and produces the same deterministic
  evidence result as a smaller input.
- **Bad:** a writer comma-joins employment labels or selects
  `classifications[0]` before evidence extraction. Historical arrays become
  unrecoverable.
- **Bad:** a UI sends a display label into a new direct SQL equality filter.
  This creates a second filter authority beside governed codes.

### 6. Tests Required

- `test_source_job_attribute_adapters.py`: complete per-Source arrays, bounded
  malformed markers, governed mappings, and Work Arrangement separation.
- `test_source_job_attributes.py`: PostgreSQL replacement/replay/concurrency,
  outbox rollback, Primary/source/catalog constraints, `RESTRICT`/`CASCADE`,
  OR-within/AND-across filters, API views, deterministic rebuild counters, and
  a forced small-batch assertion that checks bounded parameter counts plus
  cross-batch/cross-Source evidence merging. Provenance repair tests must also
  assert complete/unknown identity coverage, revision drift fencing, bounded
  batches, exact replay idempotence, and one outbox event per changed Job.
- `test_source_job_attribute_ingest.py` and
  `test_source_job_attribute_architecture.py`: every collected writer is
  inventoried, projects before commit, cannot use human-governance Interfaces,
  and cannot use retired generic/legacy writes.
- `test_source_job_attribute_api.py` plus the exported detail fixture: stable
  filter/request/response contracts and the retired generic POST error.
- `test_source_job_attribute_migration.py` plus a disposable-PostgreSQL
  upgrade/downgrade/re-upgrade rehearsal: tables, constraints, indexes, and
  idempotent seven-code seeds. Never run this rehearsal against the live
  corpus.
- `FilterPanel.test.jsx` and `JobDetailModal.test.jsx`: structured option
  compatibility and backend fixture consumption.
- `integration/test_job_intelligence_rebuild.py`: preserve the documented
  17,596-Job PostgreSQL dry-run scale test; do not shrink or mock away the
  database statement-shape regression.

### 7. Wrong vs Correct

#### Wrong

```python
job, _ = repository.upsert_job(db, {"employment_type": "Full-time"})
db.commit()
```

This bypasses source identity, projection replacement, bounded evidence, and
the projection outbox event.

#### Correct

```python
job, _ = repository.upsert_source_job(
    db,
    collected_payload_without_legacy_attributes,
    auto_commit=False,
)
SourceJobAttributes(db).project(job.id, source_attribute_evidence)
db.commit()
```

The caller owns one atomic Job/projection/outbox transaction and exact replay
remains idempotent.

#### Correct: locked provenance repair

```python
report = SourceCatalogProvenanceRepair(db).inspect(
    source_site="offertoday",
    revision_id=published_revision_id,
)
SourceCatalogProvenanceRepair(db).apply(
    report,
    expected_revision_id=published_revision_id,
    expected_fingerprint=report.revision_fingerprint,
)
```

The repair command is report-only by default. It must not infer the active
revision or bypass canonical taxonomy preflight.

#### Wrong: one whole-corpus staging lookup

```python
query.filter(tuple_(source, source_job_id).in_(all_source_keys)).all()
```

This creates an expression and parameter set proportional to the entire corpus;
PostgreSQL can exhaust parser stack depth before returning any row.

#### Correct: stable bounded composite-key batches

```python
source_keys = tuple(dict.fromkeys(source_keys_in_job_order))
for start in range(0, len(source_keys), 100):
    rows.extend(load_staging_rows(source_keys[start : start + 100]))
```

Stable de-duplication prevents redundant queries, every statement has a fixed
upper bound, and the existing per-key freshness selection keeps report and
recovery semantics deterministic.
