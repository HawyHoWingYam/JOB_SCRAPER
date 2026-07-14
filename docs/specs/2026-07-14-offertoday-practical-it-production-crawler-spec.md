# OfferToday Practical IT Production Crawler Specification

**Date:** 2026-07-14

**Status:** Implemented; deterministic backend verification passed

**Supersedes:** The Phase D-H census, supplemental-cohort successor, stability-denominator, canary, soak, and gated production-adoption route documented on 2026-07-13.

## 1. Decision

OfferToday production crawling will optimize for useful daily IT coverage instead
of attempting to prove a mathematical full-site denominator.

Each full production crawl will:

1. enumerate the configured IT category, keyword, and hybrid conditions with the
   current response-derived cursor contract;
2. retain every validated canonical `resultList` `jobId` reached before natural
   exhaustion or the per-condition safety cap;
3. skip published jobs whose OfferToday detail is already complete;
4. skip canonical IDs with a recorded OfferToday code `2520`
   `terminal_unavailable` outcome;
5. fetch detail exactly once for each new ID and each existing incomplete or
   failed ID; and
6. finish as `completed` when one or more conditions hit only the normal page
   cap, while reporting the crawl as partial.

The phrase "all IT IDs" in product and operational language means the distinct
canonical result cohort practically reachable in one run from the frozen IT
category + keyword + hybrid search space. It is not a claim that OfferToday has
exposed a stable or complete site-wide denominator.

## 2. Superseded Research Route

The following are no longer implementation or production gates:

- full-site non-IT census;
- three full censuses plus three fixed repeats;
- supplemental reachability/stability successor experiments;
- stable-reference-denominator construction;
- Phase E/F IT labeling and planner ablation;
- 20/100/500 research canaries;
- Phase H fault-injection and three-run soak; and
- candidate-hash-gated production adoption.

The existing research implementation, CLIs, schemas, strict replay code, tests,
task plans, and local runtime artifacts remain available for historical replay.
They are frozen as a research-only compatibility surface: this production task
does not add new phases or make production depend on them.

Proven production primitives remain shared and intact:

- typed listing cursor parsing and exact scalar validation;
- endpoint/request/response validation used by production;
- condition-local cursor behavior and retry safety;
- OfferToday identity authority and conflict detection;
- response classification for auth, WAF, IP, terminal, and retry cases;
- the production listing staging sink, after it is moved out of its
  research-named module; and
- the current detail pipeline and transaction boundary.

## 3. Pre-Implementation Checkout Gaps (Resolved)

The current production path does not yet implement this specification:

- `offertoday_standalone_crawl.py` calls `OfferTodayListingRunner` without a
  request policy or result-cohort terminal policy.
- Production therefore sends stateless page-number requests with effective
  defaults `pageSize=50` and `rcdType=7`.
- IT category conditions use the browse endpoint, while keyword/hybrid
  conditions use the search endpoint.
- The default IT run stops at 5,000 unique IDs.
- A page cap stops the whole run and marks it failed instead of retaining the
  validated prefix and continuing to the next condition.
- Cursor-mode staging is buffered until a condition is naturally complete,
  rather than committing each validated production batch.
- `stage_listing_batch()` skips every already-published OfferToday Job and every
  historically staged canonical ID, regardless of whether the published Job is
  complete. That can remove incomplete old jobs from the repair cohort.
- Existing metrics do not distinguish complete-existing, terminal-unavailable,
  new-detail, repair-detail, or capped-condition counts.

## 4. Frozen Production Search Space

### 4.1 Included conditions

The default production IT crawl uses, in deterministic order:

1. the official OfferToday IT root and its registered child categories;
2. the checked-in default IT keyword pack; and
3. the checked-in IT hybrid keyword pack against the IT root.

Explicit user keyword crawls remain supported, but they are not silently mixed
with the default pack.

### 4.2 Request contract

Every production IT category, keyword, hybrid, and explicit-keyword condition
uses:

- endpoint `/wapi/geek/recommend/search/list`;
- `rcdType` omitted;
- requested `pageSize=10`;
- `page=1,2,...`;
- response-derived `sessionId`, `supplePage`, `suppleAmount`, and `suppleType`
  on page 2 and later; and
- one condition-local cursor chain.

Page 1 carries no cursor. Page `N+1` is built from the immutable condition plus
the exact validated cursor returned by page `N`. A cursor is never reused across
conditions, endpoints, browser contexts, or process resumptions.

The old browse/`rcdType=7` defaults may remain inside the preserved research
replay path. Every production or new diagnostic caller must select its endpoint
and request policy explicitly; production must not inherit those defaults.

### 4.3 Natural result-cohort termination

`resultList` is the only production discovery and detail-admission cohort.

A condition reaches natural result exhaustion only after two consecutive
successful pages that:

- have an empty `resultList`;
- remain on the same validated cursor/session chain;
- carry a valid cursor transition from the preceding page; and
- have no response, identity, cursor, endpoint, or gap error.

`hasMore`, `total`, marginal saturation, or one empty result page cannot replace
the two-page rule.

### 4.4 Supplemental observations

`suppleRcdList` is parsed, best-effort identity-classified, deduplicated, and
reported separately. Supplemental IDs:

- do not enter the accepted IT ID union;
- do not enter staging;
- do not enter the detail queue;
- do not prevent two valid empty-`resultList` confirmations; and
- do not have a separate stability or reachability research gate.

Malformed or conflicting supplemental identity evidence is observation-only:
count it and exclude the affected supplemental ID from distinct/overlap sets,
but do not stop the condition or run. Result-cohort identity issues and
conflicts remain hard stops.

Metrics must expose supplemental row count, distinct supplemental IDs, and
overlap with the result cohort so the trade-off remains visible.

## 5. Stop and Partial Semantics

### 5.1 Safety cap

`max_pages` is a per-condition logical-page safety cap. Its production default
is `100`. The 5,000-unique-ID stop is removed.

`ListingStopPolicy` owns an explicit `page_cap_behavior`:

- `reject` remains the default for any surviving non-production caller during
  the transition; and
- `retain-and-continue` is mandatory for the production crawler.

When production hits the cap:

1. keep every previously validated result ID and committed staging row;
2. record the condition with `stop_reason="page_cap"` and `is_partial=true`;
3. do not claim natural exhaustion;
4. continue with the next IT condition using a fresh cursor; and
5. set the run-level `listing_partial=true`.

After all remaining conditions finish or cap normally, a full crawl proceeds to
detail and ultimately finishes `completed`.

### 5.2 Hard stops

The run stops immediately and does not begin detail when any of these occurs:

- auth expiry, WAF challenge, or IP block;
- endpoint, response, page-size, cursor, or session contract violation;
- unresolved transport gap after the frozen retry policy;
- current-page or cross-page result-cohort identity issue/conflict;
- historical canonical identity conflict discovered during batch
  classification; or
- persistence/conservation failure while staging a validated batch.

Auth/WAF/IP states use the existing manual-action/session-recovery path.
Identity conflicts use manual identity audit. Other contract, gap, or
persistence failures use `failed`. A hard-stopped crawl may retain earlier
committed validated batches for diagnostics and future repair, but those rows do
not authorize detail in the failed run.

## 6. Validated-Batch Staging Contract

Each successful result page is handled as one transaction after response,
cursor, endpoint, and identity validation.

### 6.1 Canonical batch classification

Canonical result IDs are deduplicated before database access. The batch uses:

- exactly one bulk published-Job lookup for the batch;
- one bulk historical staging/outcome lookup when needed; and
- no per-ID existence query.

The classifier partitions every canonical ID into exactly one outcome, in this
precedence order:

1. `identity_conflict` — current or historical identity evidence conflicts;
   hard-stop before detail admission.
2. `terminal_unavailable` — a recorded OfferToday code `2520` terminal outcome;
   skip and count.
3. `complete_existing` — a published Job passes
   `is_complete_offertoday_job()`; skip and count.
4. `repair` — a published Job exists but is incomplete, or eligible historical
   detail state is failed/incomplete; create or update one current-crawl pending
   staging row and count one repair target.
5. `new` — no published Job exists and no blocking terminal/conflict evidence
   exists; create one current-crawl pending staging row and count one new target.

The same canonical ID appearing on later pages or conditions does not create a
second current-crawl row or detail target.

### 6.2 Persistence

New and repair rows are written immediately after their batch passes all
validation. Current-crawl uniqueness remains
`(crawl_job_id, source_site, source_job_id)`.

The staging payload records `detail_target_kind` as `new` or `repair` so detail
selection, resumed detail execution, and metrics can reconstruct the target
class without a new database column. A schema migration is therefore not
planned. If implementation proves that JSON metadata cannot meet a required
query or recovery invariant, the task must amend this specification before
adding a column.

The production OfferToday path ignores the old broad `skip_existing` meaning:
only complete published Jobs and recorded terminal IDs are skipped. Existing
incomplete Jobs remain eligible for repair.

## 7. Detail Admission and Execution

Detail target loading starts only after every listing condition has one of:

- natural result exhaustion; or
- the allowed production page-cap partial outcome.

Any hard stop prevents detail loading in that run.

The detail cohort contains exactly one target per distinct current-crawl
staging ID classified as `new` or `repair`. Complete-existing,
terminal-unavailable, supplemental-only, duplicate, and identity-conflict IDs
produce zero detail requests.

The existing detail identity validation, retry policy, code `2520` handling,
transactional Job/listing completion, and manual-action behavior remain in
force. This task does not change the detail HTTP API contract.

## 8. Status, Events, and Metrics

A no-hard-stop production crawl ends `completed`, including a page-cap-partial
crawl. Its metrics must include:

- `listing_partial`;
- `listing_condition_count`;
- `listing_natural_condition_count`;
- `listing_capped_condition_count`;
- `listing_capped_condition_ids`;
- `distinct_it_result_ids`;
- `supplemental_rows_observed`;
- `distinct_supplemental_ids`;
- `supplemental_result_overlap_count`;
- `supplemental_identity_issue_count`;
- `complete_existing_skipped`;
- `terminal_unavailable_skipped`;
- `new_detail_targets`;
- `repair_detail_targets`;
- `detail_success`;
- `detail_failure`; and
- the existing terminal/manual/identity detail outcome counters.

The metrics are stored in the existing `CrawlJob.metrics` JSON object. No model
or API schema migration is required.

Event ordering for a full crawl is:

```text
listing page/condition events
  -> all conditions natural or capped
  -> listing_completed
  -> detail cohort frozen
  -> detail progress/outcomes
  -> crawl.completed
```

`listing_completed` reports the partial flag and capped-condition summary.
Hard-stop events occur instead of `listing_completed` and no detail-cohort event
may follow them.

## 9. Historical Research Preservation and Production Isolation

Move the production reconciliation sink and payload builder from
`offertoday_research_staging_service.py` to a production-named listing staging
service so the daily crawler has no research-module dependency.

Preserve the existing historical replay surface, including:

- OfferToday research package and artifact/stage-gate implementations;
- research live, observation, and repository services;
- research census/baseline CLIs;
- Phase A-H, pagination, partition, census, dual-cohort, artifact, schema, and
  strict-replay tests;
- superseded research specs and Trellis plans; and
- ignored local `backend/runtime/offertoday-research` artifacts.

Production modules must not import this preserved research surface. Research
replay may continue to import shared listing contract, runner, response policy,
browser runtime, identity, completeness, search-space, staging, and detail
primitives. This task fixes stale references and restores accidentally deleted
historical documents, but does not redesign, delete, or expand the research
stack and does not send live research requests.

## 10. Acceptance Criteria

- [ ] Every default IT category, keyword, and hybrid condition uses search,
      omitted `rcdType`, page size 10, and a response-derived condition-local
      cursor.
- [ ] Page 2 carries exactly the four cursor fields returned by page 1, and no
      cursor crosses a condition boundary.
- [ ] Two cursor-continuous empty `resultList` pages end a condition even when
      supplemental rows are observed.
- [ ] Supplemental rows are observable but never staged or detailed.
- [ ] Supplemental identity issues/conflicts are counted and excluded but do
      not stop the result-cohort crawl.
- [ ] The default IT unique-ID cap is absent; the per-condition cap defaults to
      100.
- [ ] Page cap retains validated IDs, continues later conditions, permits detail
      after listing finishes, and completes the crawl with
      `listing_partial=true`.
- [ ] Auth/WAF/IP, cursor/endpoint/page, identity, unresolved-gap, and staging
      failures stop immediately and cannot be converted into partial success.
- [ ] Each page performs one bulk existing-Job lookup and no per-ID existence
      lookup.
- [ ] Complete old, terminal 2520, new, repair, duplicate, and identity-conflict
      IDs are partitioned deterministically.
- [ ] New and repair IDs each produce one detail target; all skipped cohorts
      produce zero requests.
- [ ] Detail loading occurs only after all listing conditions are natural or
      allowed-partial.
- [ ] Required metrics and event ordering are exact and replayable from the
      production crawl state.
- [ ] Historical research code, tests, schemas, strict verifier, specs, and
      runtime artifacts remain replayable, while production imports no
      research-only module.
- [ ] Focused OfferToday tests, complete backend tests, Ruff, Python compilation,
      and `git diff --check` pass.

## 11. Out of Scope

- mathematical full-site completeness claims;
- non-IT census or reference denominator work;
- admitting supplemental rows to production detail;
- shadow, canary, soak, or candidate-hash rollout gates;
- frontend, Compose, or detail API changes; and
- a database migration unless a separately documented implementation blocker
  proves it necessary; and
- deletion, redesign, or further expansion of the historical research stack.
