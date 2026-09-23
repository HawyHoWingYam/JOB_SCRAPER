# Design: Prevent isolated crawl failures from aborting recoverable work

## Architecture

This task implements one operational principle through two Source-specific
boundaries:

```text
OfferToday listing page anomaly
    -> exact Source-window predicate
    -> partial Query Target
    -> continue later Query Targets
    -> listing run partial_coverage

CTgoodjobs detail persistence input
    -> correct Job/Company fact ownership
    -> isolated transaction per detail item
    -> expected item rejection recorded
    -> continue later detail items
    -> systemic persistence failure still stops the run
```

There is no shared “swallow errors” abstraction. The shared behavior is limited
to truthful evidence and continuation after a proven isolation boundary.

## Workstream A: OfferToday Listing Collection Window

### Evidence gate

Replay the persisted evidence for Crawl Jobs
`be3345a6-903a-4105-9d05-8f9cd4d2a202` and
`3fec72a9-b91f-4486-8f34-608ec3ab2e3b`, then run one bounded OfferToday-only
probe through the production request policy. Record rows, `hasMore`, page size,
cursor-field presence, session/cursor hashes, and identity growth at pages
45-46. Do not publish duplicate Jobs from the probe.

If the probe does not confirm the fixed boundary, stop implementation and
return to diagnosis. Do not force the observed responses through this design.

### Exact boundary predicate

Add one OfferToday production policy constant for the verified logical
collection-window page, currently page 46. Derive
`source_collection_window` only when:

- production response-cursor policy is active;
- logical page equals the verified window page;
- the previous accepted page was non-terminal and contributed result IDs;
- the current response is API-success with empty result and supplemental
  cohorts;
- `sessionId`, `supplePage`, `suppleAmount`, and `suppleType` are all absent;
- `pageSize` is present and unchanged;
- no endpoint, identity, session, or cursor-field conflict exists.

Keep `incomplete_cursor` as the primitive parser evidence. The runner records
both the primitive reason and the Source-window derivation. Partial tuples and
all non-matching shapes remain contract violations.

### Partial-and-continue

Use the runner's existing partial-target continuation mechanism already used by
bounded stall handling:

1. Retain pages 1-45, accepted IDs, staged listings, and observations.
2. Emit a partial condition outcome with
   `stop_reason=source_collection_window`.
3. Continue the next frozen OfferToday Query Target within the reviewed budget.
4. Aggregate any partial target into final `partial_coverage`.

Do not restart automatically at the deterministic window and do not call the
target exhausted.

## Workstream B: CTgoodjobs Detail Persistence

### Correct fact ownership

The CTgoodjobs parser continues to extract the ordered
`jobContent.jobLocations[]` list. The canonical Job keeps:

- the complete joined display string in `location`;
- the complete original structured values in `raw_data` and existing Source
  evidence.

CTgoodjobs persistence must build Company data from company-owned facts only:
source identity and name, plus an explicit company location only if a future
company-level adapter supplies it. It must omit Job location from Company
upsert, causing an existing Company.location to remain unchanged.

Keep this adapter/source boundary explicit; do not change JobsDB Company
mapping as part of this task.

### Job location storage

Change the current-schema definition of `jobs.location` from `VARCHAR(255)` to
`TEXT`. The API type remains an optional string. This repository deliberately
has no migration runtime: deployment follows the documented sandbox cutover
contract (`stop -> export -> clear -> deploy -> bootstrap -> import -> verify
-> start`) instead of altering a non-empty database in place.

`companies.location` remains `VARCHAR(255)` because CTgoodjobs Job location no
longer writes to it. A broader Company-location redesign is outside this task.

### Item-scoped versus systemic failures

Each CTgoodjobs detail item already owns a separate database session and
transaction. Preserve that boundary and refine exception classification:

- Expected canonical validation failures and explicitly recognized
  deterministic data rejections are item-scoped: roll back, mark the listing
  failed with a stable safe reason, increment progress, and continue.
- `OperationalError`, connection invalidation, database unavailability,
  rollback/transaction failure, cancellation, manual action, unknown
  `DetailPersistenceError`, and programming exceptions remain run-stopping.

Do not infer “item-scoped” merely because PostgreSQL raised a `DataError`.
Prefer validating known field/storage contracts before flush. If a database
exception must be classified, require an exact SQLSTATE plus a healthy rollback
and preserve the original exception as internal evidence.

The known long-location fixture should succeed after the TEXT migration; an
independent deterministic invalid-item fixture proves continuation without
using the fixed production item as a permanent failure.

### Run outcome and observability

Item failure evidence contains source job ID, listing ID, safe reason, field,
limit/value length when applicable, and transaction outcome. It must not include
the complete oversized value.

When the loop completes, existing detail summary counters remain authoritative:
completed, failed, unavailable, and manual action counts. The task projection
must show item failures without labeling a successfully settled run as a
database infrastructure outage. Systemic persistence failure still marks the
run failed.

## Cross-Workstream Compatibility

- No JobsDB behavior changes.
- OfferToday does not use CTgoodjobs persistence classification.
- CTgoodjobs does not use OfferToday partial-target reasons.
- Existing cancellation and manual-action semantics remain stop boundaries.
- Committed output is never rolled back across target/item boundaries.
- Task projection may share display vocabulary, but it must retain the Source,
  phase, affected-unit, and reason distinctions.

## Main Files

### OfferToday

- `backend/app/sources/offertoday/listing_contract.py`
- `backend/app/sources/offertoday/listing_runner.py`
- `backend/scripts/offertoday_standalone_crawl.py`
- OfferToday runner and task-projection tests

### CTgoodjobs

- `backend/scripts/ctgoodjobs_standalone_crawl.py`
- `backend/app/sources/contracts.py` or a focused CTgoodjobs persistence mapper
- `backend/app/workers/run_ingest_worker.py` only if the Source boundary remains
  explicit and JobsDB behavior is unchanged
- `backend/app/models/job.py`
- current-schema ORM definition and empty-bootstrap coverage for
  `jobs.location TEXT`
- CTgoodjobs parser/persistence/runtime tests

### Shared projection/spec documentation

- existing crawl task snapshot/issue projection boundary
- `.trellis/spec/backend/offertoday-production-crawl.md`
- relevant backend ingest/error-handling spec selected during pre-development

## Rollback

- OfferToday: disable the exact Source-window reclassification and restore
  fail-fast `cursor_contract_violation`; never replace it with false exhaustion.
- CTgoodjobs behavior: restore fail-fast for deterministic item persistence
  errors while retaining evidence already written.
- Schema: follow the database bootstrap/cutover contract; do not add Alembic,
  a schema-history table, or an in-place compatibility path.
