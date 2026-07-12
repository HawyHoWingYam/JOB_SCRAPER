# OfferToday Two-Page Task 8 Smoke Amendment Design

> Date: 2026-07-12
> Status: Approved for implementation
> Scope: Corrective amendment to Plan 2 Task 8 only
> Implementation plan: `docs/superpowers/plans/2026-07-12-offertoday-two-page-task8-smoke.md`

## Objective

Allow the bounded OfferToday Task 8 compatibility smoke to collect its original
20-target detail cohort when the `search` endpoint returns only 10 rows per
response despite a verified `pageSize=50` request.

The amendment raises the Task 8 listing budget from one request to at most two
requests. It does not weaken the 20-target detail cohort, identity rules,
response classification, no-retry rule, same-browser requirement, artifact
integrity, or zero-product-write boundary.

This design does not authorize another live request. Deterministic code,
tests, documentation, offline verification, and review must pass before one
new two-page replacement smoke can be proposed for separate authorization.

## Relationship to Existing Plan 2 Documents

This design amends the Task 8 listing-budget requirements in:

- `docs/superpowers/specs/2026-07-11-offertoday-plan2-live-census-calibration-design.md`;
- `docs/superpowers/plans/2026-07-11-offertoday-plan2-live-census-calibration.md`;
- `docs/superpowers/specs/2026-07-11-offertoday-jobid-only-identity-compatibility-design.md`; and
- `docs/superpowers/plans/2026-07-11-offertoday-jobid-only-identity-compatibility.md`.

It supersedes only the one-listing-request and page-1-only Task 8 assumptions.
All identity, database, artifact, review, and Task 9 gates remain in force.

## Triggering Evidence

### Identity-Corrected Replacement Smoke

The separately authorized replacement smoke produced:

- run ID `63b9d32a-5d47-44c9-8904-25a68ee2dee8`;
- artifact `backend/runtime/offertoday-research/63b9d32a-5d47-44c9-8904-25a68ee2dee8`;
- manifest SHA-256 `a009be467c30b538e31be501cc3bbb38a528b56c2fe7268507df572dda7336d3`;
- category `118000`, endpoint `search`, `rcdType=7`, page 1;
- API code `0`, classification `success`, 10 rows, reported total `260`, and `hasMore=true`;
- 10 valid `jobId_fallback` identities with no identity issues or conflicts;
- a frozen cohort of 10 targets and zero detail requests; and
- exit code `3` with stop reason `insufficient_valid_detail_targets`.

Strict offline replay and artifact verification passed. Two independent
post-smoke baselines matched the run-end snapshot, inventory, and product-data
hashes, proving that the failed smoke made no product-data change.

### Request Construction Proof

The page-attempt event recorded request fingerprint
`266bb2e09fb2977afa672e81da91679b6ac4f5193e3e74438968361c3cbd5cc5`.
Recomputing the fingerprint from the current canonical request builder produced
the same value and proved that the request contained:

```json
{
  "jobFunctionCodes": [118000],
  "keyword": "",
  "page": 1,
  "pageSize": 50,
  "rcdType": 7
}
```

The short page is therefore observed upstream behavior, not a local page-size
construction error. Because the response reported `hasMore=true`, requesting
page 2 is the smallest change that preserves the original 20-target cohort.

## Considered Approaches

### Option A: Accept the 10 Available Page-1 Targets

This preserves the original one-listing budget but halves the diagnostic detail
cohort. It was not selected because the user chose to retain 20 targets.

### Option B: Request At Most Two Listing Pages

This raises the listing budget by one request while preserving the original
20-target detail cohort. It reuses the shared listing runner and its existing
pagination, classification, identity, and evidence paths. This is the selected
approach.

### Option C: Change the Request Parameter or Endpoint

The recorded request already contains `pageSize=50`, and the endpoint returned
a valid success response. Guessing another parameter or endpoint would expand
the experiment and weaken the compatibility control. This option is rejected.

## Decision

Adopt Option B with the following exact contract:

1. The Task 8 listing request budget is at most two logical requests.
2. Page 1 is always requested first with the existing category, endpoint,
   `rcdType`, page size, session mode, and payload.
3. Page 2 is requested only when page 1 succeeds, the response does not signal
   exhaustion (`hasMore` is not false), fewer than 20 distinct accepted
   canonical IDs have been collected, and no hard-stop, gap, identity issue,
   or identity conflict exists.
4. The shared listing runner, not a new live-loop implementation, owns page 2.
5. The runner stops as soon as 20 distinct accepted canonical IDs are available
   or after page 2, whichever comes first. It never requests page 3.
6. The frozen cohort is the first 20 accepted provenance-bearing identities in
   first-seen cross-page order, deduplicated by canonical `jobId`.
7. No detail request starts until listing collection has ended and exactly 20
   frozen targets exist.
8. If two pages still yield fewer than 20 valid distinct targets, the smoke
   stops with `insufficient_valid_detail_targets` and makes zero detail requests.
9. Listing and detail retries remain zero. A page-1 or page-2 hard stop ends the
   smoke immediately and makes no detail request.
10. The same fresh-headless browser instance performs both listing requests and
    every detail request.

## Runtime Architecture

### Shared Listing Runner

`OfferTodayResearchLiveService.run_smoke()` continues to call one
`OfferTodayListingRunner` with one runtime transport and one condition. Its
bounded policies change to:

```python
ListingStopPolicy(
    max_pages_per_condition=2,
    unique_job_cap=20,
    require_empty_confirmation=False,
)

ListingRetryPolicy(
    max_attempts_per_page=1,
    retry_delays_seconds=(),
    page_delay_seconds=0.0,
)
```

`unique_job_cap=20` avoids page 2 if page 1 ever supplies 20 accepted IDs.
`max_pages_per_condition=2` is the independent defense that prevents page 3
when duplicates or unusable rows keep the distinct count below 20.

No new paginator, transport wrapper, retry loop, or browser lifecycle is added.

### Cohort Readiness

The smoke-readiness predicate accepts only bounded listing results with:

- one or two ordered page attempts beginning at page 1;
- attempt number 1 and classification `success` for every accepted page;
- no gaps, identity issues, or identity conflicts;
- exactly 20 frozen targets; and
- stop reason `target_cap`, caused by the 20-ID cap while the listing remains
  intentionally incomplete.

The live evidence currently reports `hasMore=true`, so an incomplete bounded
stop remains part of the compatibility control. A naturally exhausted result is
recorded but does not silently redefine this smoke's acceptance contract.

### Request and Artifact Budgets

Every runtime contract, run-start event, artifact metadata record, summary,
offline verifier, and CLI output must agree on:

```json
{
  "request_budget": {
    "listing": 2,
    "detail": 20
  }
}
```

The artifact must record every page attempt independently, including page,
attempt, request fingerprint, row and identity evidence, classification,
latency, and stop reason. The frozen cohort remains a separate event emitted
only after the bounded listing run ends.

Strict replay rejects:

- more than two listing attempts;
- a page other than 1 followed optionally by 2;
- duplicate or out-of-order page attempts;
- any listing retry;
- detail evidence before the cohort is frozen;
- a cohort that is not the first 20 authoritative cross-page identities; or
- metadata, run-start, summary, and observed-count disagreement.

### Detail Execution

The existing detail contract is unchanged:

- exactly 20 frozen targets for an accepted listing phase;
- sequential concurrency 1;
- three seconds between completed non-stopping attempts;
- no retries and no replacement target after a terminal or failed attempt;
- code `2520` remains `terminal_unavailable` without stopping the batch; and
- auth, WAF, IP block, transport, invalid payload, and identity mismatch retain
  their current stop behavior.

### Product-Data Boundary

The no-op research staging sink remains mandatory. The smoke may write only the
tagged research crawl job, ordered research events, and ignored runtime artifact.
It must not write staging, Job, Company, repair, publication, or enrichment
state. Matching run-start/run-end hashes and two independent post-smoke
baselines remain required.

## Failure and Stop Semantics

The existing exit-code mapping remains unchanged:

- exit `0`: accepted smoke; continue only to artifact and database verification;
- exit `3`: bounded smoke incomplete, including fewer than 20 valid targets;
- exit `4`: auth, WAF, IP, or identity hard stop; and
- exit `5`: evidence or artifact failure.

No outcome automatically starts another live command. Any failed or partial run
must export and verify its artifact before a new decision. Another live smoke
requires separate explicit user authorization after deterministic review.

## Immutable Evidence

The following failed artifacts remain immutable and must continue to verify
offline:

- `fab9d8e1-4c12-4170-a539-c0a6cdbbca93`, manifest SHA-256
  `1928423eed6cfd95e4cd2a3af3eb1d62c2ea6d460b122acb0ca0fefcfb4b548b`;
- `63b9d32a-5d47-44c9-8904-25a68ee2dee8`, manifest SHA-256
  `a009be467c30b538e31be501cc3bbb38a528b56c2fe7268507df572dda7336d3`.

Neither artifact satisfies Task 8. The first proves the obsolete two-raw-ID
assumption; the second proves the one-listing/20-target budget mismatch after
identity correction.

## Deterministic Test Design

Implementation follows red-green-refactor. Required regressions include:

1. page 1 with 10 accepted IDs plus page 2 with 10 new IDs makes two listing
   requests and freezes 20 targets in first-seen order;
2. duplicates across pages are deduplicated by canonical `jobId`;
3. fewer than 20 distinct targets after page 2 makes zero detail requests and
   returns `insufficient_valid_detail_targets`;
4. page 1 with 20 accepted IDs does not request page 2;
5. a page-1 hard stop does not request page 2 or any detail;
6. a page-2 hard stop makes no detail request;
7. successful two-page collection still makes exactly 20 sequential detail
   attempts with 19 three-second delays;
8. metadata, run-start, artifact, and verifier budgets all require listing `2`
   and detail `20`;
9. strict replay accepts ordered pages 1 and 2 and rejects page 3, retries,
   ordering changes, count tampering, or cohort tampering;
10. both existing failed artifacts continue to verify offline; and
11. snapshot, inventory, and product-data no-write assertions remain unchanged.

## Documentation Amendments

The implementation plan must update current normative references from:

- one listing request to at most two;
- page-1-only collection to ordered pages 1 then optionally 2;
- at least 20 IDs on page 1 to at least 20 distinct IDs across the bounded
  listing result; and
- exactly one page-attempt artifact to one or two bounded page attempts.

Historical descriptions of the two failed runs remain unchanged and explicitly
dated as evidence. Task 8 remains unaccepted and Task 9 remains locked until a
new two-page smoke exits 0, verifies, and its report is accepted by the user.

## Out of Scope

- Changing category `118000`, endpoint `search`, `rcdType=7`, or `pageSize=50`.
- Adding listing or detail retries.
- Adding a third listing page.
- Changing listing or detail response classification.
- Changing identity resolution, authority, or detail ownership rules.
- Changing detail concurrency or three-second pacing.
- Database migrations, model changes, or historical rewrites.
- Starting calibration, pilot, census, or any Plan 2 Task 9-15 work.
- Automatically executing another live smoke.

## Acceptance Criteria

The amendment is ready for a new authorization request only when:

1. the runtime makes at most two ordered listing requests and never page 3;
2. 20 targets are frozen in first-seen cross-page canonical-ID order;
3. duplicates, unusable identities, and conflicts cannot inflate the cohort;
4. fewer than 20 targets after page 2 makes zero detail requests;
5. request budgets and observed counts replay strictly offline;
6. both failed artifacts remain immutable and valid;
7. no retry, response-policy, identity, pacing, or product-write control weakens;
8. focused and Plan 1 deterministic verification passes;
9. unrelated dirty-worktree changes remain untouched; and
10. no live request or Task 9 work occurs without its separate gate.
