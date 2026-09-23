# Make OfferToday listing coverage adaptive and verifiable

## Goal

Make OfferToday listing collection produce an evidence-backed, source-scalable
coverage result instead of treating a fixed keyword sweep or an unstable
`hasMore` signal as proof that a Source Classification has been exhausted.

Operators must be able to distinguish a complete run, a safely recovered run,
and a partial run whose source coverage could not be established.

## Background

- Listing run `6cbf1c14-03fa-4769-a99b-cd026eaa13f0` completed 36 OfferToday
  Information Technology query conditions and 1,620 page attempts, but 16,200
  returned job-ID occurrences collapsed to 644 distinct IDs (96.02% duplicate).
- All 644 distinct listings were staged as detail-pending; the run did not fail
  or hit its authored page cap.
- Several conditions returned stalled cohorts. The `4` condition issued 45
  distinct request fingerprints but returned one distinct ten-ID cohort before
  reporting `hasMore=false`.
- Two later live replays using the production request shape produced 50 distinct
  IDs across five pages for `4`, `A`, and an empty keyword. The failure is
  therefore session/source-state dependent rather than a consistently
  reproducible cursor-serialization defect.
- OfferToday response totals varied sharply within a single cursor chain, and
  the response cursor's `supplePage`, `suppleAmount`, and `suppleType` remained
  zero. Source-reported totals are not a trustworthy completion oracle.
- The current production query plan expands every selected classification into
  the fixed single-character set `A-Z` plus `0-9`. These queries are not
  disjoint source partitions and do not scale as a manually governed list for
  every future classification.
- Runtime-plan listing runs currently accept a non-empty page with
  `hasMore=false` as natural exhaustion without requiring an empty-page
  confirmation.
- The OfferToday adapter currently discovers classifications from a bundled
  `category_registry.json`; its generator reads a historical Git blob and never
  contacts OfferToday. It cannot notice a live child addition or removal.
- Complete Source Classification Registry synchronization currently deactivates
  missing top-level rows only. Missing child rows remain active, so automatic
  child retirement requires an explicit contract change.

## Requirements

- Coverage planning must scale to OfferToday classifications beyond Information
  Technology without requiring a manually maintained keyword list per
  classification.
- Operators author scope only with the top-level OfferToday Source
  Classifications they care about; internal child-classification partitions are
  not additional operator selections or dashboard interests.
- The current OfferToday child classifications must be discovered and activated
  automatically without code edits or per-child operator maintenance. New
  children participate in future runs, removed children stop receiving new work,
  and historical run evidence retains the frozen classification snapshot it
  used.
- Each run must freeze its resolved child-classification partitions before
  collection begins so a source taxonomy change cannot mutate work already in
  progress.
- A resolved listing plan combines three bounded routes: the selected top-level
  classification without a keyword, each current child classification without
  a keyword, and supplemental keyword queries paired only with the selected
  top-level classification. It must never form the child-classification by
  keyword Cartesian product.
- Supplemental keywords are maintained by operators as a Source Classification
  Keyword Pack owned by one top-level OfferToday classification. The product
  must not generate or silently expand this pack at runtime.
- Operators must be able to download a keyword pack as CSV, edit it outside the
  product, validate and upload the CSV, and see actionable row-level errors
  without partially applying an invalid file.
- One CSV import/export surface manages the keyword packs for all OfferToday
  top-level classifications. Every row carries a stable source-qualified
  classification identity; display labels are informative and never replace
  identity-based validation.
- CSV export includes read-only evidence from the keyword's latest completed
  execution: newly contributed distinct IDs, duplicate ratio, and run time.
  Import accepts these round-trip columns but cannot overwrite runtime evidence.
- The initial CSV import contract is a safe merge/upsert: rows present in the
  file are created or updated, omitted existing rows remain unchanged, and an
  operator disables a keyword with `enabled=false`. Entries are not physically
  deleted through CSV import.
- Keyword identity is case-insensitive after whitespace normalization. The
  operator's stored spelling is preserved for display and source requests, but
  case-only variants such as `Java` and `java` cannot coexist in one
  classification pack.
- CSV upload is a non-mutating preview step. It reports the complete validated
  diff, row errors, resulting enabled counts, and reviewed crawl-workload impact;
  only an explicit confirmation atomically updates the ordinary current keyword
  catalog.
- Keyword catalog management lives on a dedicated global OfferToday Keyword
  Packs operator page with CSV export/import, preview/confirm, per-classification
  enabled counts, last update time, and latest contribution evidence. Crawl
  authoring only reads and links to the ordinary current catalog.
- The first release exposes no per-row keyword mutation controls. The management
  table is read-only/filterable, and every catalog mutation uses the CSV
  preview-and-confirm path.
- The keyword catalog has no user-visible versions, historical snapshots, or
  restore operation. A lightweight mutation log records operator, timestamp,
  CSV content hash, and added/updated/disabled counts without retaining a
  restorable copy of prior catalog contents.
- A top-level classification may have at most 150 enabled keywords. Disabled
  historical entries do not count toward this limit; a preview that would
  exceed it cannot be confirmed.
- Initial data seeds the existing 127 distinct curated IT terms into the
  `offertoday:118000` pack as enabled entries. The `A-Z`/`0-9` sweep is not
  migrated, and every other OfferToday top-level classification starts with an
  empty pack.
- Keyword Query Targets use the run's ordinary authored Page Depth and receive
  no smaller keyword-specific depth cap. The reviewed workload must expose the
  exact keyword-count multiplication and require an aggregate Run Page Cap that
  covers every planned top-level, child, and keyword target.
- Scheduled automations resolve the latest verified child snapshot and latest
  current keyword catalog before dispatch. If the expanded workload exceeds
  the automation's saved Run Page Cap, dispatch is blocked for operator review;
  the system never raises the saved cap silently.
- A confirmed run must freeze the exact keyword-pack contents it reviewed so a
  later CSV upload cannot mutate an existing dispatch plan or historical run.
- A failed OfferToday taxonomy refresh must fall back to the last successfully
  verified classification snapshot and warn that the resolved scope may be
  stale. Dispatch is blocked only when no verified snapshot has ever been
  stored.
- Preparing a one-off crawl preview must attempt a bounded live OfferToday
  taxonomy refresh before resolving child partitions and workload. The reviewed
  snapshot fingerprint prevents confirmation after a newer refresh changes the
  previewed scope.
- The system must preserve the operator's authored Source Classification scope
  throughout every collection and recovery attempt.
- Repeated or non-advancing listing cohorts must be detected as source/session
  degradation rather than counted as useful page progress.
- A Query Target becomes stalled when the Source reports `hasMore=true` while
  three consecutive successful pages contribute no new listing identities.
- A recoverable degraded condition must be retried through a fresh source
  session without duplicating staged listing identities.
- A stalled Query Target receives one automatic fresh-session recovery. If it
  stalls again, that target is partial, its valid listings are retained, and
  collection continues for the remaining targets.
- A run must not claim complete exhaustion from a non-empty terminal page alone.
- `hasMore=false` on a non-empty page begins terminal confirmation rather than
  ending the Query Target. Natural exhaustion requires two consecutive empty
  pages; failure to obtain them before the page cap makes the target partial.
- Completion must be based on recorded coverage evidence and explicit policy;
  unstable source totals must remain diagnostic evidence only.
- A run has Evidence-Bounded Coverage only when every planned collection route
  has stopped contributing new listing identities under the recorded policy;
  reaching an expected numeric job count is not a completion condition.
- When coverage cannot be established within bounded work, the run must retain
  collected listings and report a partial outcome with a machine-readable
  reason.
- Any planned native-classification or keyword Query Target that remains partial
  makes the overall run partial. The operator projection separately reports
  native coverage and keyword-supplement completion so valid collected listings
  are not mistaken for a total failure.
- Run evidence must expose per-condition pages, distinct-ID growth, duplicate
  ratio, recovery attempts, terminal evidence, and the contribution of each
  collection strategy.
- Existing published Job identity and Detail Backlog semantics must remain
  unchanged.

## Acceptance Criteria

- [ ] A run with repeated non-advancing cohorts is detected before consuming the
      remaining authored page allowance on those cohorts.
- [ ] A detected degraded condition receives bounded fresh-session recovery and
      records its outcome.
- [ ] Three consecutive no-growth pages with `hasMore=true` trigger exactly one
      fresh-session recovery; a repeated stall marks only that target partial
      and does not prevent later targets from running.
- [ ] A non-empty page carrying `hasMore=false` cannot by itself establish
      natural exhaustion.
- [ ] Natural exhaustion is recorded only after two consecutive empty pages;
      reaching the page cap without that confirmation records a partial target.
- [ ] A run that cannot establish coverage completes as partial, retains all
      valid staged listings, and identifies the incomplete conditions.
- [ ] If one keyword remains partial after recovery, overall status is partial
      while the projection can still report native coverage completed and the
      exact completed/partial keyword counts.
- [ ] Operators can explain the difference between observed cards, distinct
      listing identities, newly contributed identities, and published Jobs from
      persisted run evidence.
- [ ] The query-planning mechanism can be applied to a non-IT OfferToday Source
      Classification without adding a new hand-authored keyword pack.
- [ ] An operator can continue selecting only a top-level OfferToday
      classification while newly discovered active children are included in a
      subsequent run and removed children are excluded without rewriting
      historical run scope.
- [ ] The resolved plan contains one top-level route, one route per active
      child, and only top-level-plus-keyword supplemental routes; no child route
      is multiplied by the keyword set.
- [ ] An operator can round-trip a top-level classification's keyword pack
      through CSV export and import without changing its normalized contents.
- [ ] A single exported CSV can represent keyword entries across all active
      OfferToday top-level classifications without relying on classification
      labels as identities.
- [ ] CSV export reports the latest completed execution contribution for each
      keyword, and re-uploading those read-only columns cannot alter persisted
      run evidence.
- [ ] Invalid CSV rows produce row-level errors and leave the current keyword
      pack unchanged.
- [ ] Upload preview is non-mutating and confirmation atomically applies the
      exact reviewed diff; stale or already-consumed previews cannot be applied.
- [ ] The global management page owns all keyword mutation, while crawl preview
      shows the frozen keyword count, catalog update time, workload impact, and
      a link to management without accepting file uploads itself.
- [ ] Keyword rows cannot be created, edited, or disabled directly in the first
      release's UI; CSV confirmation is the only mutation path.
- [ ] Applying CSV records one non-restorable mutation-log entry with actor,
      time, content hash, and change counts; no keyword catalog version or old
      catalog snapshot is created.
- [ ] CSV preview reports enabled counts per classification and blocks
      confirmation above 150 while preserving any number of disabled historical
      entries.
- [ ] Initial bootstrap produces exactly the reviewed 127 enabled IT keywords,
      no alphanumeric sweep entries, and empty packs for other top-level
      OfferToday classifications.
- [ ] Run preview separately reports native-classification and keyword maximum
      pages, their total, and budget validity; dispatch requires explicit review
      and cannot exceed the confirmed aggregate Run Page Cap.
- [ ] A scheduled automation adopts current taxonomy/keyword inputs only when
      they fit its saved budget; otherwise it reports review-required and emits
      no crawl task until the operator saves a sufficient cap.
- [ ] Uploading a valid subset updates only those source-classification and
      keyword identities; omitted entries are unchanged and disabled entries
      are excluded from future plans without erasing history.
- [ ] Exact and case-only duplicate keyword identities are rejected within one
      classification while exported spelling round-trips unchanged.
- [ ] A keyword-pack update affects only future dispatch plans; existing plans
      and historical runs retain their frozen keywords.
- [ ] A temporary taxonomy-refresh failure uses the last verified snapshot and
      records a stale-snapshot warning; a source with no verified snapshot is
      not dispatched.
- [ ] One-off preview attempts taxonomy refresh, reports fresh versus stale
      snapshot provenance, and rejects confirmation when the reviewed snapshot
      has changed.
- [ ] Tests cover healthy pagination, repeated-cohort detection, session
      recovery, terminal confirmation, bounded partial completion, and
      cross-condition deduplication.

## Constraints

- OfferToday is an unstable external source; the product must not promise an
  unknowable absolute inventory count such as "all 2,000-3,000 jobs."
- Collection and recovery must remain bounded and cancellable.
- Existing source-owned classification terminology in `CONTEXT.md` remains
  authoritative.
