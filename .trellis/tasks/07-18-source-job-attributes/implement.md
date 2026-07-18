# Source job attributes implementation plan

## Dependencies

- Requires the completed/archived `07-18-job-intelligence-foundation`
  contracts. Reuse provenance/hash/outbox values, but never use its human
  decision UoW for automated projection.
- Load the independent Source Catalog identity contract; a known revision is a
  nullable Source Catalog FK/value, never a Foundation `RevisionRef`, and
  historical unknown revisions remain supported.

## Ordered checklist

1. Load `trellis-before-dev`; read the parent and archived Foundation artifacts,
   backend/frontend spec indexes, database/worker/API/error/logging/type-safety
   guidelines, and Source Catalog runtime contract.
2. Inventory every live/staging/repair writer and every Job response/filter
   consumer. Add architecture guards so later writers cannot bypass the Module
   or import Foundation decision Interfaces.
3. Add failing per-Source fixtures that reproduce current JobsDB/OfferToday
   `[0]` truncation and JobsDB/CTgoodjobs scalar joining, then specify complete
   classification/employment evidence including missing/malformed cases.
4. Define typed evidence, `SourceCatalogRevisionRef`, projection/read values,
   stable Employment Type codes/mapping registry, and the deep
   `SourceJobAttributes` Interface. Keep adapters persistence-free.
5. Add the successor Alembic migration, ORM models, bounded provenance fields,
   constraints, partial unique indexes, Source Catalog `RESTRICT` FK, projection
   anchor, and idempotent seven-code seed. Register models without startup seed
   or live migration side effects.
6. Implement JobsDB, CTgoodjobs, and OfferToday evidence adapters before scalar
   canonicalization. Carry serialized evidence through canonical/staging/ingest
   events while preserving Work Arrangement/working days outside Employment
   Types.
7. Implement normalized-hash projection replacement. Lock the Job/anchor,
   replace children only on change, enqueue one bounded
   `job.source_attributes_changed` event with `auto_commit=false`, and never
   commit inside the Module.
8. Integrate every authoritative collected-Job writer in its existing outer
   transaction. Remove new writes to legacy classification/subclassification/
   employment scalars; keep those columns available only to compatibility and
   rebuild readers.
9. Add list/detail arrays, ordered evidence detail, stable filter options,
   `source_classification_ids[]`/`employment_type_codes[]` predicates, and the
   deprecated single-label adapter implemented through the same new predicate.
   Export real backend response fixtures for child 6.
10. Implement the read-only rebuild inspector over staging/raw/legacy evidence.
    Emit deterministic JSON/human reports for recovered, ambiguous, unknown,
    conflicting, provenance-limited, and unrecoverable rows; expose no apply
    mode and assert zero writes.
11. Run targeted source/unit/API/PostgreSQL tests, direct-SQL constraint and
    migration upgrade/downgrade rehearsal on a disposable database, targeted
    static checks on changed files, then the repository's full backend test
    strategy. Fix all task-relevant findings before Phase 3.
12. Run `trellis-check` full-scope, review/capture new executable contracts with
    `trellis-update-spec`, then follow the Trellis commit/archive/journal flow.

## Validation

```bash
cd backend && pytest -q tests/test_source_job_attribute_adapters.py tests/test_source_job_attributes.py tests/test_source_job_attribute_api.py
cd backend && ruff check <changed-python-files> && black --check <changed-python-files> && mypy <changed-typed-modules>
cd backend && alembic heads
cd backend && pytest -q
cd frontend && npm test -- --run
python3 ./.trellis/scripts/task.py validate 07-18-source-job-attributes
git diff --check
```

Run migration upgrade/downgrade and rebuild inspection only against a disposable
PostgreSQL database. This child has no live rebuild/apply mode; live execution
belongs to child 7. If one-shot full-suite collection repeats the documented
baseline block, run every backend test file in isolation against the disposable
database and record both the collection symptom and aggregate pass/fail totals.

## Risk and rollback points

- Do not infer Source primary or fabricate missing CTgoodjobs subclassifications.
- Do not pass a Source Catalog revision through Foundation `RevisionRef` or use
  `GovernanceUnitOfWork` for automated projections.
- Do not make Source Catalog revision non-null for historical evidence.
- Do not drop or overwrite legacy scalars before cutover reconciliation.
- Do not claim legacy scalars recover arrays that older parsers discarded.
- Roll back runtime reads to the legacy adapter if needed while leaving additive
  projection/evidence tables intact for diagnosis; never downgrade populated
  tables or touch the live corpus in this child.
