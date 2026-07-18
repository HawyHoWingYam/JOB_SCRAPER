# Current source-attribute dataflow audit

## Purpose

This 2026-07-18 read-only audit records the current Source Classification and
employment data flow before `source-job-attributes` implementation. It
distinguishes evidence that still exists from data already lost through scalar
canonicalization, and identifies the transaction/API seams the new Module must
use.

## JobsDB

- Listing transformation keeps only `classifications[0]` and therefore loses
  later Source Classification paths before canonicalization
  (`backend/app/sources/jobsdb/parsers.py:11-46`, symbol `_transform_job`).
- Detail transformation reads scalar tracking fields
  `classificationId/classification/subClassificationId/subClassification` and
  a scalar work-type label (`backend/app/sources/jobsdb/parsers.py:114-147`,
  symbol `parse_detail_redux_data`).
- Listing canonicalization comma-joins the preserved `work_types` array through
  `_join_work_types`; detail/listing canonical jobs then expose only scalar
  classification and employment members (`backend/app/sources/contracts.py:35-41,82-132`).
- Standalone staging currently writes an empty `listing_payload` while carrying
  only selected catalog classification metadata
  (`backend/scripts/jobsdb_standalone_crawl.py:248-275`). Historical rows from
  this path cannot reconstruct discarded arrays.
- No dedicated raw JobsDB classification/work-type parser fixtures were found;
  the existing browser-detail test covers browser attachment rather than these
  payload contracts (`backend/tests/test_jobsdb_browser_detail_scraper.py`).

Implementation consequence: extract typed evidence before `_transform_job`
discards paths or `_join_work_types` joins labels, and transport it through
staging/canonical events. Dry-run must report older scalar-only rows as
provenance-limited or unrecoverable rather than synthesizing arrays.

## CTgoodjobs

- Employment precedence is `jobContent.workTypes`, then `basicInfo.empTypes`,
  then JSON-LD `employmentType`; `_join_names` comma-joins list members
  (`backend/app/sources/ctgoodjobs/parsers.py:288-298,556-560`).
- The JSON-LD fallback accepts string/array values and currently maps `OTHER`
  to the scalar label `Other` (`backend/app/sources/ctgoodjobs/parsers.py:345-366`).
  The new governed mapping must retain that raw evidence but project no
  Employment Type.
- The Source Classification comes from the published catalog query/crawl
  context and is carried into detail parsing as a single category; current
  catalog nodes are root-only and do not justify inventing subclassifications
  (`backend/scrapy_project/job_scraper_spiders/spiders/ctgoodjobs.py:76-150,193-220`,
  `backend/app/source_catalog/adapters/ctgoodjobs.py:120-150`).
- Catalog/manual-action handling is headed-only and records bounded operational
  evidence; it is not Job attribute evidence
  (`backend/app/source_catalog/adapters/ctgoodjobs.py:168-228`).
- No dedicated CTgoodjobs parser fixture suite was found.

Implementation consequence: preserve all labels from the first available
precedence source without comma joining; tag the category path as weaker
`crawl_context` provenance when it is not present in the detail payload; never
turn child counts or URL structure into a subclassification.

## OfferToday

- Listing/detail parsers retain complete `jobFunctions`, `jobType`,
  `jobTypeDesc`, and `employType` data in normalized/raw payloads
  (`backend/app/sources/offertoday/parsers.py:105-190`).
- `build_offertoday_canonical_job` selects only `job_functions[0]` and
  `children[0]`, causing the current classification loss
  (`backend/app/sources/contracts.py:203-265`).
- Listing request construction separately flattens and de-duplicates all
  function codes (`backend/app/sources/offertoday/listing_runner.py:379-402`),
  proving that request scope behavior and collected-Job evidence are distinct.
- The Source Catalog adapter retains same-code children as non-selectable alias
  evidence rather than duplicate query targets
  (`backend/app/source_catalog/adapters/offertoday.py:57-118`).
- A current synthetic detail fixture demonstrates one root with one child but
  does not exercise multiple roots/children or same-code evidence
  (`backend/tests/test_offertoday_global_detail_backlog.py:404-430`).

Implementation consequence: build one semantic path for each root/child
combination before `[0]` selection, preserve root-only paths, de-duplicate exact
semantic duplicates by first Source order, and retain raw alias evidence in the
raw payload rather than generating duplicate path/query identities.

## Persistence and transaction seam

- `Job` stores four legacy Source classification scalar columns, one scalar
  `employment_type`, and `raw_data` JSON
  (`backend/app/models/job.py:41-44,72-75,92-93`).
- `RunIngestWorker._build_job_data` copies those scalar fields and `raw_data`
  directly into the Job upsert (`backend/app/workers/run_ingest_worker.py:397-424`).
- `JobRepository.upsert_source_job(..., auto_commit=False)` flushes into the
  caller's Session; the ingest worker enqueues `event_outbox` with the same
  Session and commits once (`backend/app/repositories/job_repository.py:24-65`,
  `backend/app/workers/run_ingest_worker.py:100-125,210-226`,
  `backend/app/repositories/event_outbox_repository.py:11-43`).
- Staging retains `listing_payload` and nullable `detail_payload`; the table is
  uniquely keyed per crawl/source/job and cascades with its Crawl Job
  (`backend/app/models/crawl_job_listing.py:13-67`,
  `backend/alembic/versions/20260520_120000_add_crawl_job_listings.py`).
- OfferToday detail persistence merges listing/detail raw data, while JobsDB
  detail repair currently updates the legacy scalar attributes and raw data
  (`backend/app/services/offertoday_detail_pipeline.py:440-469,498-515`,
  `backend/app/services/jobsdb_detail_repair_service.py:43-62`).

Implementation consequence: the new projector can share the existing Session
and outbox transaction, must not commit internally, and needs a writer inventory
guard covering stream ingest, detail/standalone persistence, repair, and later
backfill. New paths stop updating legacy attribute scalars.

## Read and filter seam

- Job create/response schemas inherit scalar Source classification and
  `employment_type` fields (`backend/app/schemas/job.py:7-23,55-82`).
- Structured search accepts scalar `employment_type` and applies direct column
  equality (`backend/app/schemas/job_search.py:13-32`,
  `backend/app/api/jobs.py:331-344,809`).
- Existing taxonomy array predicates use SQL `IN`, which already implements OR
  within one selected field; successive filters are ANDed
  (`backend/app/api/jobs.py:366-450,483-496`).
- `/jobs/filters` derives distinct values from the scalar employment column
  (`backend/app/api/jobs.py:128-136,892-924`).
- Frontend Job Browser state and `FilterPanel` currently use a single
  `employment_type` selection (`frontend/src/components/FilterPanel.jsx:131-137`,
  `frontend/src/utils/jobBrowserQueryUtils.js:4,80-100`).

Implementation consequence: add array response fields and code/ID option
objects; implement `source_classification_ids[]` and
`employment_type_codes[]` through relation predicates; route any temporary
single-label adapter through the same code predicate rather than retaining a
second scalar-equality authority.

## Foundation and Source Catalog boundary

- Foundation `Provenance` and `OutboxEvent` are reusable values
  (`backend/app/job_intelligence/foundation/contracts.py:71-106,148-156`).
- `GovernanceUnitOfWork` is explicitly for one human decision and enforces
  confirmation/local actor/idempotency/version/audit semantics
  (`backend/app/job_intelligence/foundation/decisions.py:33-127`). Background
  workers must not import or receive it
  (`backend/docs/job-intelligence-foundation.md:18-42`).
- `SourceCatalogRevision` is an independent immutable table with its own Source,
  sequence, fingerprint, payload, and restricted predecessor/candidate links
  (`backend/app/models/source_catalog.py:101-132`). It is not a
  `governance_revisions`/Foundation `RevisionRef`.

Implementation consequence: Source Attributes uses a domain-owned nullable
`SourceCatalogRevisionRef` and FK when catalog identity is known, plus
Foundation `Provenance` for method/evidence/capture metadata. Automated
projection uses normalized evidence hashing for replay, not human decision audit
or governance idempotency records.

## Planning conclusions

1. The child can start without changing the accepted product decisions.
2. Evidence extraction must move ahead of current scalar parsers/canonical
   builders; reconstructing after loss is not valid.
3. A one-row-per-Job projection anchor supplies locking, aggregate evidence
   identity, versioning, and exact-replay suppression.
4. PostgreSQL Interface tests must cover Job/projection/outbox atomicity,
   Source/catalog matching, Primary constraints, replacement replay/concurrency,
   relation filters, and cascades/restrictions.
5. Rebuild in this child is inspection-only and must classify unrecoverable
   history. Live migration/cutover remains child 7.
