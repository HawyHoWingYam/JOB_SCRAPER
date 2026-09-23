# Prevent isolated crawl failures from aborting recoverable work

## Goal

Prevent two verified, Source-specific local failures from aborting otherwise
recoverable Crawl Job work:

1. An OfferToday listing Query Target reaches the Source's page-46 collection
   boundary without verified exhaustion.
2. A CTgoodjobs detail item carries valid multi-location evidence that cannot be
   persisted through the current Company/Job location contract.

In both cases, preserve valid output, record the incomplete or failed unit
truthfully, and continue later work that remains safe. Do not introduce a
generic catch-and-continue policy across Sources.

## Background

### OfferToday listing evidence

- Crawl Job `be3345a6-903a-4105-9d05-8f9cd4d2a202` failed after 2,300 observed
  pages. Keyword `infrastructure` returned ten rows with `hasMore=true` on page
  45, then API `code=0`, an empty cohort, stable `pageSize=10`, and no response
  cursor quartet on page 46. The parser reason was `incomplete_cursor`.
- Crawl Job `3fec72a9-b91f-4486-8f34-608ec3ab2e3b` independently failed on
  keyword `Kafka` with the same page-45/page-46 transition.
- Across the two runs, 24 targets reached page 46. Twenty-two had already
  entered terminal confirmation and completed successfully; only the two
  targets still contributing rows on page 45 failed.
- An empty page cannot prove exhaustion: `infrastructure` returned an empty
  `hasMore=false` page at page 3 and resumed with ten rows at page 4.
- Historical Crawl Job `3c2d5886-9d06-48f1-8d7f-ef481072b315` recorded
  page-46 exhaustion, and earlier production research observed 45-request
  cohorts. The evidence indicates a Source-owned 45-page collection window,
  subject to one bounded verification probe before implementation.

### CTgoodjobs detail evidence

- Crawl Job `451cfe7e-9afd-4b71-b59d-9797b29db9dc` froze 1,518 detail targets.
  Item one completed; item two, source job `10221752`, failed during persistence;
  the remaining 1,516 rows were safely released from `running` to `pending`.
- PostgreSQL raised `StringDataRightTruncation` while updating
  `companies.location VARCHAR(255)` for `AURELION LIMITED` (`00166538`). The
  existing value is already 252 characters; the new job's joined location list
  is longer than 255 characters.
- CTgoodjobs parses every `jobContent.jobLocations[].name` into the Job location.
  Shared ingest then copies that Job fact into both `Job.location` and
  `Company.location`. A job's possible work locations are not a company-level
  address and must not overwrite Company facts.
- `Job.location` is also `VARCHAR(255)`, so only suppressing the Company update
  would move the same failure to Job persistence.
- The transaction rolled back completely: `10221752` has no published Job, the
  existing Company was not partially updated, and the listing remains failed
  and retryable after a fix.

## Requirements

### Shared containment requirements

- R1. Keep the two Source mechanisms independent. OfferToday cursor/window
  classification must not govern CTgoodjobs persistence, and CTgoodjobs item
  handling must not weaken OfferToday cursor validation.
- R2. A local target/item failure may continue only when its transaction and
  ownership boundary are known to be isolated. Cancellation, manual action,
  browser/session loss requiring operator action, database connection failure,
  transaction corruption, and unknown programming errors retain their existing
  stop behavior.
- R3. Preserve committed listings, published Jobs, ordered events, and
  machine-readable failure evidence. Never convert incomplete work into natural
  exhaustion or silent success.
- R4. JobsDB behavior is out of scope and must remain unchanged.

### OfferToday listing requirements

- O1. Replay both production failures and perform one bounded OfferToday-only
  probe before making page 46 an executable Source-window contract.
- O2. Preserve the invariant that one empty response does not prove exhaustion.
- O3. Classify only the exact verified boundary shape: production cursor policy,
  page 46, prior non-terminal page with identity growth, current API-success
  empty cohorts, all four cursor fields absent, and stable page size.
- O4. Record the primitive `incomplete_cursor` evidence and derive an
  OfferToday-only `source_collection_window` target stop reason. Do not treat it
  as `natural_exhaustion`.
- O5. Mark only the affected Query Target partial, preserve its accepted IDs and
  staged listings, continue later frozen OfferToday Query Targets, and settle
  the overall listing run as `partial_coverage`.
- O6. Partial cursor tuples, early cursor absence, non-empty missing-cursor
  responses, page-size drift, session rollover, identity issues, and endpoint
  violations remain hard contract anomalies.
- O7. Do not automatically restart a fresh session at a deterministic Source
  window unless new evidence proves restart can obtain deeper verifiable
  coverage without looping or replaying the same 45-page cohort.

### CTgoodjobs detail requirements

- C1. Treat `jobContent.jobLocations[]` as Job-owned Source evidence. Preserve
  the complete ordered location list in raw/source evidence.
- C2. Do not create or update `Company.location` from a CTgoodjobs Job location.
  Company location may change only from explicit company-level evidence.
- C3. Persist a CTgoodjobs Job's complete normalized multi-location display
  value without silent truncation. Define `Job.location` as `TEXT` in the
  current schema and deploy it through the repository's empty-sandbox cutover
  contract; do not add an in-place migration path.
- C4. A deterministic item-scoped ingest/persistence rejection must roll back
  that item's transaction, mark its listing failed with a stable reason, update
  progress metrics, and continue the remaining Backlog Snapshot.
- C5. Unknown `DetailPersistenceError`, database connectivity/availability
  failures, invalid transaction state, cancellation, and manual action remain
  fail-fast. The implementation must not broadly catch all SQLAlchemy or Python
  exceptions and continue.
- C6. Record a safe machine-readable reason such as
  `persistence_value_too_long`, including field and limit metadata without
  logging the full oversized value.
- C7. After the contract fix, retrying source job `10221752` must publish it,
  retain its full Job location evidence, leave `AURELION LIMITED.location`
  unchanged, and allow later detail items to run.

## Acceptance Criteria

### OfferToday

- [ ] A deterministic replay catches both page-45/page-46 production failures.
- [ ] A bounded probe confirms or falsifies the fixed boundary before production
      classification changes; a falsification returns planning to diagnosis.
- [ ] The exact verified boundary marks one target
      `source_collection_window`/partial and runs the next target.
- [ ] Final status is `partial_coverage`, with all prior valid output retained
      and no claim of evidence-bounded completion.
- [ ] Early/partial/non-empty cursor absence, page-size drift, session rollover,
      endpoint violations, and identity defects remain hard failures.
- [ ] Existing two-empty confirmation, terminal cursor reuse, stall recovery,
      page-cap, cancellation, and OfferToday projection tests pass.

### CTgoodjobs

- [ ] A fixture containing more than 255 characters across ordered
      `jobLocations` reproduces the pre-fix persistence failure.
- [ ] The complete ordered location value is persisted on the Job and retained
      in raw/source evidence without truncation.
- [ ] CTgoodjobs Job ingest neither creates nor overwrites Company.location from
      Job location; an existing Company location remains unchanged.
- [ ] An expected item-scoped rejection rolls back and marks only that listing
      failed, then the following detail item completes.
- [ ] A simulated database connection failure, invalid transaction, cancellation,
      manual action, and unknown persistence error still stop the run.
- [ ] Retrying `10221752` publishes a Job, leaves `AURELION LIMITED.location`
      unchanged, and does not strand later snapshot rows in `running`.
- [ ] Empty-schema bootstrap uses `TEXT` for Job location and a long-value
      round trip preserves the complete value.

### Cross-workstream

- [ ] The final diff contains no JobsDB behavior change.
- [ ] Focused Source tests, bootstrap/schema tests, lint/type/compile gates, and the
      complete backend suite pass.
- [ ] Operator projections distinguish OfferToday partial coverage from
      CTgoodjobs item failures and do not collapse either into a misleading
      generic infrastructure summary.

## Out of Scope

- JobsDB listing, detail, persistence, and recovery semantics.
- OfferToday keyword catalog, taxonomy expansion, Page Depth, or Run Page Cap
  tuning.
- Treating an OfferToday empty page as natural exhaustion.
- Browser request deadlines and stale execution heartbeat handling owned by
  `08-12-prevent-hung-offertoday-listing-executions`.
- Bulk correction of historical CTgoodjobs Company.location values already
  derived from old Job locations; this task prevents new corruption and records
  the need for a separate audited cleanup if required.
- A general multi-valued geographic taxonomy or location association model.

## Product Decisions

- OfferToday uses partial-and-continue at the verified Source window: preserve
  the target, continue later targets, and finish as `partial_coverage`.
- CTgoodjobs keeps valid full multi-location Job evidence, does not project it
  onto Company.location, and isolates only explicitly classified item-scoped
  failures so later detail items can continue.
