# OfferToday taxonomy handling design

## 1. Boundary and causal model

AI enrichment operates on persisted `jobs` rows. It does not call OfferToday.
The stored `source_classification_id` is an internal source prior used to build
the allowed taxonomy context for the LLM and to validate the final category
decision. The relevant flow is:

```text
stored job metadata
  -> source taxonomy policy lookup
  -> supported item: local taxonomy slice -> LLM -> final category resolution
  -> unsupported item: excluded with reason; no LLM call
```

The source taxonomy policy therefore belongs at the enrichment boundary, not in
the OfferToday transport or browser runtime.

## 2. Source taxonomy policy

Keep the authoritative 31-root catalog in
`backend/app/scraper/offertoday/category_catalog_v1.json` and use exact keys of
the form `offertoday:<root_code>`.

Extend the local source taxonomy policy so every catalog root has one explicit
handling rule:

- `mapped`: has `allowed_domains`, `default_path`, and optional
  `subcategory_hints`; every referenced internal node must exist in
  `job_category_taxonomy.json`.
- `excluded`: has a stable operator-facing reason explaining that no defensible
  internal destination exists yet.

Do not silently map ambiguous roots to an unrelated internal domain. The initial
excluded set is expected to include roots such as Farming, Government, Natural
Energy, Self Employment, Sport, and Other; the exact set is validated against
the catalog and documented in the policy data.

`JobTaxonomyRegistry` should expose a non-throwing handling/preflight result for
candidate selection. Existing `get_allowed_slice()` and
`get_base_default_path()` remain strict for mapped enrichment paths, but missing
or explicitly excluded entries become a typed unsupported result at preflight
instead of an opaque worker exception.

## 3. Enrichment run preflight and persistence

Preflight the selected pending candidates before dispatching an enrichment run.
The current `limit` continues to cap the selected candidate cohort; exclusions
reduce the number actually sent to workers rather than causing the service to
fetch extra candidates implicitly.

Persist excluded jobs as first-class run items:

- `status = "excluded"`
- no AI start or completion timestamp
- the existing item reason field carries the stable exclusion explanation
- `EnrichmentRun.excluded_items` stores the aggregate count

`total_items` remains the selected cohort size. `pending_items` counts only
supported jobs waiting for workers. `completed_items`, `failed_items`,
`cancelled_items`, and `excluded_items` are mutually exclusive terminal buckets.
The worker queue must contain only `pending` items, so excluded rows cannot
consume concurrency or terminate a worker early.

Run outcomes:

- supported work with no failures and no exclusions: `completed`
- supported work with exclusions but no worker failures: `completed_with_exclusions`
- any real worker failure: `completed_with_failures`, with excluded count shown
  separately
- all selected items excluded: persist the exclusion report as a terminal
  `completed_with_exclusions` run and do not publish a worker request

`retry-failed` continues to select only `status = "failed"`; excluded jobs are
not retried as if they had reached the provider.

## 4. API and UI contract

`POST /ai/pending/preview` returns the existing match/limit fields plus:

- supported/effective item count
- excluded item count
- grouped exclusion details by source classification ID/name and count

`POST /ai/runs` returns the same exclusion summary as part of the created run
projection. If all candidates are excluded, it returns an explicit
no-supported-items result without publishing an execution event.

Run serialization and item serialization expose `excluded_items` and
`status = "excluded"`. The AI enrichment console:

- shows `Excluded` alongside succeeded, failed, and cancelled counts;
- calculates settled progress using all terminal buckets, while keeping
  excluded items out of success/failure metrics;
- shows the grouped reason/details for excluded items in preview and terminal
  run summaries;
- does not offer retry for excluded items.

Add `completed_with_exclusions` to backend/frontend terminal-status sets and
give it a warning/attention presentation distinct from provider failure.

## 5. Compatibility and migration

- Add `enrichment_runs.excluded_items INTEGER NOT NULL DEFAULT 0` with a
  migration; existing rows backfill to zero.
- `enrichment_run_items.status` is already a string column, so `excluded` needs
  no schema enum migration.
- Existing JobsDB and CTgoodjobs mappings remain unchanged.
- Company enrichment remains outside this task.
- No OfferToday network, browser, or crawler behavior changes are required.

## 6. Rollback and operational safety

Mapping data can be reverted independently, but code and migration must be
deployed together before creating excluded run items. A rollback to code that
does not understand `excluded` should only happen after active/terminal runs
using the new status have been drained or a compatibility reader is deployed.

The provider's empty JSON responses remain visible as ordinary failed items;
this change must not relabel provider failures as taxonomy exclusions.
