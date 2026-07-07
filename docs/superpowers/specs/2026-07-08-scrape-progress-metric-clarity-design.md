# Scrape Progress Metric Clarity Design

Date: 2026-07-08
Status: Approved in chat, pending user review of this written spec
Primary files:
- `frontend/src/components/scraper/ScrapeProgressPanel.jsx`
- `frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`

## Overall Objective

Make the scrape progress panel clearly distinguish between:

- the total number of unique job IDs discovered during listing
- the subset of those IDs that actually enter the detail queue
- the number of detail rows completed so far

The main operator pain to remove is the current ambiguity where phase 1 and phase 2 can show different denominators without explaining why they differ.

## Iteration Scope

This iteration is a frontend presentation change for the scrape progress panel.

In scope:
- clearer metric labels for phase 1 (`Collecting IDs`)
- clearer metric labels for phase 2 (`Scraping Details`)
- consistent fallback rules for denominator selection
- focused Vitest updates for the new wording and ordering

Out of scope:
- changing the panel layout to a new multi-section design
- changing backend API contracts
- changing non-scraper progress surfaces

## Current Problem

The panel currently exposes the right raw ideas, but the display vocabulary is muddy:

- `job_ids_collected` and `detail_target_rows` are different counts, but they are not surfaced as two named concepts with a stable relationship.
- `Detail crawled` and `Current target` can appear to disagree when one uses the detail queue denominator and the other falls back to all discovered IDs.
- operators must infer the meaning of `Skipped existing` rather than reading a clear queue story from the cards.

## Design Summary

Keep the existing progress card layout and only change the metric composition and wording.

### Phase 1: Collecting IDs

The panel should present two primary numbers first, then supporting context.

Metric card order:
1. `IDs found: <job_ids_collected>`
2. `Detail queue: <detail_target_rows>` when present, otherwise `<listings_staged>`
3. `Pages: <current_page>/<total_pages>`
4. `Skipped existing: <jobs_skipped_existing>` only when greater than zero

Intent:
- `IDs found` means every unique job ID discovered during listing.
- `Detail queue` means the subset of IDs that will move into detail crawling.
- `Skipped existing` explains why `Detail queue` may be smaller than `IDs found`.

### Phase 2: Scraping Details

The panel should treat the detail queue as the primary denominator.

Metric card order:
1. `Detail crawled: <jobs_scraped>/<detail queue>`
2. `IDs found: <job_ids_collected>`
3. `Skipped existing: <detail_skipped_existing_rows || jobs_skipped_existing>` only when greater than zero
4. `Current row: <detail row index>/<detail queue>`

Intent:
- the operator sees one dominant progress line tied to the actual detail workload
- the listing-stage total stays visible for context but is no longer confused with the detail denominator

## Data Mapping

The frontend should keep using current progress fields and not require a new backend contract.

Preferred field mapping:
- `IDs found` -> `job_ids_collected`
- `Detail queue` -> `detail_target_rows`, fallback to `listings_staged`
- `Skipped existing` in phase 1 -> `jobs_skipped_existing`
- `Skipped existing` in phase 2 -> `detail_skipped_existing_rows`, fallback to `jobs_skipped_existing`
- `Detail crawled` numerator -> `jobs_scraped`
- `Current row` numerator -> `detail_job_index`, fallback to `jobs_scraped`

## Denominator and Fallback Rules

The denominator rules must be explicit and stable.

### Phase 1

- `Detail queue` should prefer `detail_target_rows` when the backend provides it.
- If `detail_target_rows` is missing, the panel should fall back to `listings_staged`.
- `IDs found` should never be relabeled as queue size.

### Phase 2

- `Detail crawled` must use the detail queue denominator, not total discovered IDs.
- `Current row` should prefer the same detail queue denominator used by `Detail crawled`.
- If `detail_target_rows` is unavailable, the panel may fall back to `detail_job_total`.
- If both are unavailable, the final fallback is `total_jobs`.

This ordering prevents displays such as `70/728 details crawled` next to `Current row: 70/1286`.

## Implementation Details

Implement this as a small refactor inside `ScrapeProgressPanel.jsx`.

Recommended changes:
- add a dedicated `buildListingRunMetricLines(...)` helper for phase 1
- keep `buildDetailRunMetricLines(...)`, but update wording and line ordering
- rename `Current target` to `Current row`
- derive one shared `detailQueueTotal` value near the top of `ProgressItem` and reuse it for both phase 1 and phase 2 displays

The change should stay local to the progress panel and avoid unrelated component cleanup.

## Error Handling and Incomplete Data

The panel should degrade gracefully when some progress metrics are absent.

- Hide `Skipped existing` when the count is zero or missing.
- If the queue denominator is missing, still show the numerator-only count rather than a misleading ratio.
- Preserve current behavior for manual-action, backlog, ingest, and AI states unless the new shared denominator logic can be reused without altering their semantics.

## Testing and Verification

Update `frontend/src/components/scraper/ScrapeProgressPanel.test.jsx` with focused assertions.

Required coverage:
1. phase 1 listing run shows `IDs found`, `Detail queue`, `Pages`, and `Skipped existing` in the new wording
2. phase 2 detail run shows `Detail crawled` against the detail queue denominator
3. phase 2 detail run shows `Current row` instead of `Current target`
4. fallback case where `detail_job_total` is missing still keeps `Current row` aligned to `detail_target_rows`
5. existing non-detail states continue to render without regressions in wording unrelated to this change

Verification commands for implementation:
- `cd frontend && npm test -- ScrapeProgressPanel.test.jsx`
- `cd frontend && npm run build`

## Implementation Steps

1. Refactor metric-line construction in `ScrapeProgressPanel.jsx`
2. Introduce stable queue-total fallback logic
3. Update phase 1 labels and ordering
4. Update phase 2 labels and ordering
5. Revise and expand `ScrapeProgressPanel.test.jsx`
6. Run targeted Vitest and frontend build verification

## Risks

- small wording changes can break brittle text-based tests
- fallback changes can accidentally affect backlog or completed-detail displays if the shared total is threaded too broadly

Mitigation:
- keep the queue-total logic scoped to listing and detail-run rendering paths
- add tests for both the normal and fallback cases

## Success Criteria

An operator can look at the panel and immediately answer:

- how many unique IDs were discovered
- how many of those became detail work
- how many detail rows are completed
- why the detail denominator is smaller than the listing total
