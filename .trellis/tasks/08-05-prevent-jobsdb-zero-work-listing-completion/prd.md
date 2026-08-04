# Prevent JobsDB zero-work listing completion

## Goal

Ensure a JobsDB One-off listing Run cannot report successful completion after
unstable source pagination prevents it from processing any advertised listing
work. Preserve legitimate successful no-work completion only when the Source
authoritatively reports an empty classification.

## Background

- Production Crawl Job `57324f0b-7564-43f0-a2b1-029e07434e01` targeted one
  JobsDB Source Classification with a page depth and run page cap of 200.
- The first page probe advertised enough results for 123 pages. Reverse
  pagination then processed pages 123 and 122, both empty, and exited before
  processing the already-fetched first page.
- The run completed in about 2.9 seconds with zero collected Job IDs, zero raw
  Job IDs, zero staged listings, and zero published Jobs skipped.
- Repeated live requests for the same classification returned `totalCount`
  values of 3791, 3870, and 3914. The Source therefore cannot be assumed to
  provide a stable result count across requests.
- A minimized runtime reproduction requests pages `[1, 123, 122]`, stages two
  empty pages, discards the non-empty cached first page, and returns a successful
  result with no Job IDs.
- GitHub issue: https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/52

## Requirements

### R1. Preserve confirmed first-page work

When the initial JobsDB page probe returns Job identities, those identities
must be processed exactly once even if a later computed tail page is empty.

### R2. Treat advertised work with zero evidence as inconsistent

An initial `totalCount > 0` followed by a completed listing attempt with zero
raw Job identities, zero staged listings, and zero published Jobs skipped must
not produce a successful `listing_completed` / `crawl.completed` outcome. The
Crawl Job must become `failed` with a `crawl.failed` event and bounded evidence
that identifies the inconsistent JobsDB pagination. This is not a manual-action
condition because no operator browser or session intervention is required.

### R3. Preserve authoritative empty completion

An initial `totalCount == 0` remains a legitimate successful no-work outcome.

### R4. Keep reviewed workload bounds

Recovery from an empty or drifting tail must not exceed the frozen page depth
or aggregate run page cap. It must continue to use the frozen JobsDB Query
Target and must not add hidden Source Classifications.

### R5. Preserve listing identity semantics

Published Jobs remain excluded from listing staging. A run that observes only
published identities may complete successfully when the observed raw and
skipped counts truthfully demonstrate that work.

### R6. Record diagnosable evidence

Task events and final state must distinguish authoritative empty scope from
inconsistent pagination so an operator can understand why the run did not
complete successfully and can retry through the existing failed-run flow.

## Acceptance Criteria

- [x] AC1: Given a non-empty first page whose advertised count computes a tail
  page that later returns empty, the first-page Job identities are still
  processed exactly once.
- [x] AC2: A run with `totalCount > 0` cannot finish successfully when collected,
  raw, staged, and skipped identity evidence are all zero.
- [x] AC3: A stable multi-page response remains bounded by the frozen page depth
  and run page cap and does not duplicate staged identities.
- [x] AC4: `totalCount == 0` still completes successfully with zero work.
- [x] AC5: A page containing only already-published identities completes with
  truthful non-zero raw/skipped metrics and no new staging rows.
- [x] AC6: Regression tests reproduce the observed `[1, 123, 122]` failure shape
  and prove the corrected completion outcome.
- [x] AC7: Crawl Task Details expose `failed` plus bounded pagination evidence
  for unresolved inconsistency; the run does not enter manual-action state.

## Out of Scope

- Changing JobsDB detail crawling or browser-profile recovery.
- Changing CTGoodJobs or OfferToday pagination.
- Re-running or mutating historical Crawl Job
  `57324f0b-7564-43f0-a2b1-029e07434e01`.
- Removing the cross-source rule that listing discovery skips published Jobs.
