# OfferToday Plan 2 Live Census Calibration Design

> Date: 2026-07-11
> Status: Approved direction; written review pending

## Objective

Use the measurement foundation completed in Plan 1 to calibrate a safe live OfferToday listing transport, select evidence-backed endpoint and `rcdType` controls, and produce three reproducible full-site listing censuses across all 31 top-level categories.

Plan 2 begins with one deliberately bounded runtime smoke. At the user's direction, that smoke includes at most two ordered listing requests, page 1 followed only when needed by page 2, and up to 20 sequential detail requests. Those detail requests validate session, transport, response classification, canonical identity, and parser behavior only. They do not persist Jobs or staging rows and do not count as the 100/500 detail canaries reserved for Plan 4.

## Relationship to the Approved Research Design

Plan 1 implemented Phase 0 and Phase 1 of `2026-07-10-offertoday-broad-it-coverage-reliability-research-design.md`. Plan 2 implements Phase 2 only:

1. one-condition runtime smoke;
2. bounded endpoint and `rcdType` calibration;
3. a three-page pilot across all 31 top-level categories;
4. one full-site census to confirmed natural exhaustion;
5. two repeated full-site censuses across a second time window; and
6. a stability and reproducibility decision record for Plan 3.

Plan 2 does not define broad-IT title rules, label positive or negative samples, run planner ablations, drain the detail backlog, or change the production planner. Those remain Plan 3 or Plan 4 work.

## Plan 1 Entry Evidence

The Plan 2 entry gate was satisfied at commit `1d26c05aaa266ea2eb56550903417f6741905d5e`:

- focused Plan 1 suite: 559 passed;
- full backend suite: 657 passed;
- audit/production saved-response equivalence: passed;
- complete conservation fixtures: zero difference;
- gap and identity-conflict fixtures: rejected as designed;
- two quiescent read-only baselines: matching count and inventory hashes;
- no live OfferToday request during Plan 1; and
- production default search space and the 5,000 diagnostic cap remained unchanged.

The last matching read-only baseline contained:

| Metric | Value |
|---|---:|
| Staging rows | 15,697 |
| Distinct staged IDs | 5,573 |
| Published OfferToday Jobs | 2,961 |
| Distinct staged-but-unpublished IDs | 2,612 |
| Snapshot data hash | `1527469841bf0e70273f439b82dbb854b24fc5f6dbb3661f3f1c9f8d0e5cb06c` |
| Inventory data hash | `418d6791e0a20a45ccf5fc274b96640aa130a33d8f062578c63698cd87a6a081` |

These values are provenance for Plan 1, not immutable Plan 2 acceptance data. Every live Plan 2 run captures a new quiescent run-start inventory and compares it with its run-end inventory.

## Task 8 Corrective Amendment Record

Historical failed-run evidence from the first authorized Task 8 smoke: run `fab9d8e1-4c12-4170-a539-c0a6cdbbca93` made one listing request and failed because all ten returned listing rows were valid `jobId`-only rows under the corrected identity contract. It is failed immutable evidence, not an accepted smoke, and it invalidates only the assumption that every accepted row must contain two independently observed raw IDs.

Its artifact at `backend/runtime/offertoday-research/fab9d8e1-4c12-4170-a539-c0a6cdbbca93` remains preserved exactly as captured, with manifest SHA-256 `1928423eed6cfd95e4cd2a3af3eb1d62c2ea6d460b122acb0ca0fefcfb4b548b`.

Historical failed-run evidence from the identity-corrected replacement smoke: run `63b9d32a-5d47-44c9-8904-25a68ee2dee8` made one listing request, accepted 10 valid `jobId_fallback` identities without an identity issue or conflict, froze 10 targets, made zero detail requests, and exited `3` with `insufficient_valid_detail_targets`. Its artifact at `backend/runtime/offertoday-research/63b9d32a-5d47-44c9-8904-25a68ee2dee8` remains preserved exactly as captured, with manifest SHA-256 `a009be467c30b538e31be501cc3bbb38a528b56c2fe7268507df572dda7336d3`. This identity-corrected but target-count-incomplete result triggered the two-page Task 8 amendment.

Neither failed artifact satisfies Task 8. The current corrective contract changes only the listing side of the request budget to at most two ordered requests while retaining up to 20 details, sequential three-second pacing, zero retries, the no-product-write boundary, artifact export and verification, and the smoke review checkpoint. Another live Task 8 smoke requires separate explicit user approval, and Task 9 remains locked.

## Approved Decisions

1. Keep `backend/scripts/offertoday_research.py` offline-only. Live research gets a separate entry point and never weakens the Plan 1 import/network guard.
2. Use the shared `OfferTodayBrowserRuntime`, `OfferTodayListingRunner`, response classifier, provenance-aware identity contract, research observation service, and artifact exporter. No live command may implement a second pagination or classification loop.
3. Run every live stage explicitly. A successful smoke does not automatically start calibration, pilot, or census work.
4. Treat the first smoke parameters as a compatibility control, not a selected production recommendation: category `118000`, endpoint `search/list`, `rcdType=7`, page 1 followed only when required by page 2, page size 50.
5. Use fresh headless mode for the first smoke because the current workspace has no storage-state file and no reusable CDP listener. Do not fall back silently to another session mode.
6. Freeze the first 20 distinct valid `(jobId, resolved_route_id, encrypted_job_id_source)` triples before the first detail request. Duplicate canonical IDs and rows missing a valid canonical `jobId` do not consume the limit; a missing raw `encryptJobId` uses `jobId_fallback` and remains independently counted as an observation.
7. Fetch the frozen detail cohort sequentially with concurrency 1 and a recorded three-second inter-request delay. The initial smoke never retries a listing or detail request.
8. Do not write `crawl_job_listings`, Job, Company, repair, or publication state during the smoke. Only the tagged research crawl job, ordered research events, and ignored runtime artifact may be written.
9. Code `2520` is recorded as `terminal_unavailable` and does not stop the remaining smoke cohort. Auth expiry, WAF, IP block, identity mismatch, and any other batch-stop classification stop immediately.
10. The 20-detail result is diagnostic. It cannot satisfy the Plan 4 99-percent availability-adjusted detail gate or replace the 100/500 canaries.
11. Pilot and full census discovery may use the production staging sink only after smoke and calibration gates pass. Global ID reconciliation must create no more than one staging row per newly seen canonical ID; query provenance stays in events.
12. Plan 2 never changes production endpoint, keywords, `rcdType`, pacing, or unique-ID target. It emits a recommendation for later review.

## Scope

### In Scope

- A live-only Plan 2 research CLI with explicit `smoke`, `calibrate`, `pilot`, `census`, `compare`, and `verify-run` commands.
- At most two ordered listing requests plus a 20-detail smoke using one browser session.
- Explicit session, endpoint, `rcdType`, paging, retry, and pacing metadata.
- Saved-response replay for every live command.
- Research crawl-job events and reproducible JSON/JSONL artifacts for successful, failed, stopped, and partial runs.
- A small endpoint/`rcdType` calibration matrix.
- A three-page pilot over all canonical top-level categories.
- Three full-site censuses with no global unique-ID cap.
- Per-run set hashes, request cost, gaps, identity evidence, stability metrics, and a Plan 3 handoff decision.

### Out of Scope

- Broad-IT title-rule selection or manual labeling.
- Planner family ablation or production keyword changes.
- Publishing details from the smoke cohort.
- Repairing smoke failures.
- The formal 100/500 detail canaries, fault injection, backlog drain, or production soak.
- Automatic production configuration changes.
- Deleting historical staging, crawl-job, or research rows.

## Architecture

### 1. Separate Live Research Entry Point

Add `backend/scripts/offertoday_research_census.py` as the only live Plan 2 command surface. It may import browser and listing-runtime modules. The existing `backend/scripts/offertoday_research.py` remains offline-only and continues to expose only `baseline`, `conservation`, `export-run`, and `verify-artifact`.

The live script is a thin dependency-wiring layer. Argument parsing, stage contracts, smoke evaluation, candidate freezing, comparison, and acceptance decisions live under `backend/app/sources/offertoday/research/` so they remain fixture-testable without Playwright or a database.

### 2. Stage-Gated Orchestration

Each command executes exactly one stage:

```text
Plan 1 gate
  -> smoke
  -> calibrate
  -> pilot
  -> freeze candidate
  -> census run 1
  -> census runs 2 and 3
  -> compare / Plan 3 entry decision
```

Every command requires explicit input artifacts from the preceding stage and verifies them before opening a browser. A command refuses to run when the predecessor is missing, invalid, failed, or contains a stop condition.

### 3. Shared Browser and Listing Semantics

The live orchestrator opens one `OfferTodayBrowserRuntime` for a stage and injects it into `OfferTodayListingRunner`. It does not perform a separate preflight API request before the page-1 smoke listing request; that first classified listing response is the smoke session-health evidence. This preserves the at-most-two-listing-request budget.

The smoke listing runner uses:

```text
conditions                  = one category 118000 condition
endpoint                    = search
rcdType                     = 7 compatibility control
max_pages_per_condition     = 2
unique_job_cap              = 20
require_empty_confirmation  = false
max_attempts_per_page       = 1
page_delay_seconds          = 0
staging sink                = no-op evidence sink
session mode                = fresh-headless
```

A clean listing phase requests page 1 first and page 2 only when page 1 succeeds, does not signal exhaustion, and leaves the accepted distinct canonical-ID count below 20. It stops at `target_cap` as soon as 20 first-seen distinct canonical IDs are available, remains `is_complete=false`, and never requests page 3. A clean two-page `page_cap` with fewer than 20 targets is bounded incomplete evidence: it exits `3` with `insufficient_valid_detail_targets` and makes zero detail requests.

For this `runtime-smoke` experiment only, crawl-job status `completed` means the bounded experiment executed and its smoke gate passed; it does not mean the listing condition naturally exhausted. The run summary must therefore persist `listing_complete=false`, `expected_truncation=true`, and `smoke_passed=true` together. Census experiments may never use this exception: a census with `page_cap` remains incomplete or failed.

### 4. Detail Smoke Adapter

After the listing result is recorded, a pure selector freezes the first 20 first-seen distinct valid provenance-bearing identities from `ListingRunResult.id_pairs`, restricted to `ListingRunResult.accepted_job_ids`. The live layer injects `runtime.fetch_detail_json` into `OfferTodayBrowserDetailScraper`, preserving shared response classification, strict identity validation, parser cleanup, and typed `OfferTodayDetailFetchResult` behavior without starting a second browser.

For each target, the adapter records:

- zero-based and one-based cohort position;
- canonical `jobId`, resolved route, and `encrypted_job_id_source`, with hashes plus the non-secret identifiers required for replay;
- request start/end timestamps and latency;
- response classification and exact API code;
- whether identity validation passed;
- whether canonical parsing passed;
- title/company/cleaned-description non-empty flags for successful details;
- whether the outcome stopped the batch; and
- whether later frozen targets remained unattempted.

Raw cookies, CSRF tokens, authorization headers, browser profile contents, and storage-state content are never included.

### 5. Research Ledger and Artifacts

Every live stage creates a tagged `crawl_job` before the first network request:

```json
{
  "research": {
    "plan": 2,
    "run_id": "uuid",
    "experiment": "runtime-smoke",
    "variant": "search-rcdtype-7-fresh-headless",
    "planner_version": "git-sha",
    "parent_artifact_hash": "plan-1-or-prior-stage-hash",
    "request_budget": {
      "listing": 2,
      "detail": 20
    }
  }
}
```

Ordered events include:

- `research.run_started`;
- existing `research.page_attempt` and condition outcome events;
- `research.detail_cohort_frozen`;
- `research.detail_attempt`;
- `research.run_stopped` when applicable; and
- `research.run_summary`.

Strict evidence validation requires one or two ordered listing page attempts beginning at page 1, attempt number 1 for every page, a current request budget of listing `2` and detail `20`, and a frozen cohort containing the first 20 authoritative canonical IDs across the bounded result. Page 3, any listing retry, or any page attempt after `research.detail_cohort_frozen` is an evidence failure.

The artifact exporter runs in `finally`, so a browser exception, hard stop, Ctrl-C, or evidence-validation failure still produces partial observations, provenance, and a content-hash manifest. Artifact verification is mandatory before the command exits successfully.

### 6. Database Boundaries

The smoke writes only its tagged crawl job and research events. Its no-op staging sink asserts that zero listing rows, Jobs, and Companies were persisted. Run-start and run-end database snapshots must have identical staging and published-job counts and hashes.

The later pilot and census stages use global reconciliation before staging:

```text
valid distinct discovered IDs
= already published
+ preexisting staged-unpublished
+ newly staged once
+ deferred identity conflicts
```

Repeated conditions and repeated censuses must not create additional rows for an already known canonical ID. Run-local staging amplification must remain at or below 1.01. No detail worker is launched by a Plan 2 command.

## Live Stage Design

### Stage 0: Revalidate the Foundation

Before each live stage:

1. verify the parent artifact;
2. record HEAD, dirty tracked/untracked evidence, source hashes, Compose hashes, and runtime mode;
3. run the Plan 1 focused contract selector;
4. capture a new quiescent database baseline twice and require matching hashes; and
5. confirm no other OfferToday research process is active.

Any mismatch stops before opening a browser.

### Stage 1: At Most Two Ordered Listings Plus 20 Details

Request budget:

| Request | Maximum |
|---|---:|
| Search-page navigation | 1 |
| Listing API | 2 |
| Detail API | 20 |
| Listing retries | 0 |
| Detail retries | 0 |

The detail cohort is frozen before detail request 1. Requests run sequentially with a three-second delay between completed attempts. The command does not compensate for a terminal or failed target by adding a replacement; the denominator remains the frozen cohort.

Smoke acceptance requires:

- one or two ordered listing attempts, page 1 followed optionally by page 2, each with attempt number 1 and classification `success`;
- at least 20 first-seen distinct valid provenance-bearing resolved identities across the bounded listing result;
- listing stop reason `target_cap` at the 20-ID cap;
- zero listing identity issues or conflicts;
- exactly 20 frozen targets;
- all 20 targets attempted unless a recorded batch-stop outcome occurs;
- every non-terminal attempted detail classified `success` with matched identity and a canonical parsed payload;
- any code-2520 target classified only as `terminal_unavailable`;
- zero auth, WAF, IP-block, transient, invalid-payload, or ID-mismatch outcomes;
- zero database staging/Job/Company delta; and
- a verified artifact.

If page 2 ends with fewer than 20 valid distinct canonical IDs, the command exits `3` with `insufficient_valid_detail_targets` and makes zero detail requests. Page 3, any listing retry, or any page attempt after cohort freeze fails evidence validation.

The diagnostic availability-adjusted success rate is reported, but it is not a production acceptance statistic.

### Stage 2: Endpoint and `rcdType` Calibration

Calibration runs only after the smoke passes. It uses two representative top-level categories: IT root `118000` and the existing non-IT control `112000`. The bounded matrix is:

```text
2 categories
x 2 endpoints (search, browse)
x 2 rcdType controls (7, omitted)
x 3 pages
= 24 logical page requests before bounded retries
```

Each logical page permits at most three attempts with recorded backoff. The comparison reports valid rows, distinct IDs, missing identifiers, mapping conflicts, reported totals, `hasMore`, latency, failures, and IDs unique to each variant. It does not infer completeness from API totals.

Only variants with zero hidden gaps, zero identity conflicts, and valid authenticated responses advance.

### Stage 3: Three-Page 31-Category Pilot

Use the strongest one or two calibration variants across the canonical 31 top-level categories. Each category is limited to pages 1-3. The pilot remains incomplete by design and records `page_cap`; it is accepted as a pilot only when every planned page is successfully observed and there are no unresolved gaps or batch-stop classifications.

The pilot determines:

- endpoint and `rcdType` candidate;
- conservative pacing and retry budget;
- longest authenticated success streak;
- category-specific anomalies;
- projected full-census request cost; and
- whether the run-local staging guard can be maintained.

### Stage 4: Freeze the Census Candidate

The chosen candidate is written as an immutable JSON contract containing:

- endpoint and `rcdType`;
- all 31 ordered category conditions;
- page size;
- retry limits and delays;
- pacing range;
- session mode;
- natural-exhaustion and empty-confirmation rules;
- source and parent-artifact hashes; and
- rejected alternatives with evidence.

No full census starts without this verified contract.

### Stage 5: Full Census Run 1

Run all 31 conditions with:

- no global unique-ID cap;
- confirmed natural exhaustion;
- one successful empty confirmation page;
- conservative recorded pacing;
- bounded same-page retries; and
- immediate batch stop on every approved stop condition.

The run is complete only when all 31 conditions are naturally exhausted, gaps and identity conflicts are zero, conservation difference is zero, and the artifact verifies.

### Stage 6: Repeated Censuses and Stability

Repeat the frozen candidate twice across at least one additional time window. Also repeat a fixed subset of conditions three times in a short window to distinguish ranking instability from inventory churn.

The Plan 3 entry report includes:

- per-run and union set hashes;
- time-aligned and full-union ID counts;
- fixed-cohort Jaccard;
- unique-count coefficient of variation;
- exact added/removed cohorts;
- requests and seconds per new ID;
- all gaps, retries, and stop conditions; and
- a reproducible command manifest.

## Stop and Failure Semantics

Stop the active stage immediately for:

- `auth_expired` / code 1002;
- WAF challenge;
- `ip_blocked` / code -1000035;
- any request/response ID mismatch or mapping collision;
- three consecutive transport or API failures outside the initial no-retry smoke;
- unresolved page-failure rate above 1 percent;
- non-zero conservation difference;
- staging amplification above 1.01;
- artifact verification failure; or
- operator cancellation.

For the 20-detail smoke:

- `terminal_unavailable` / code 2520 is recorded and the next frozen target proceeds;
- any batch-stop classification leaves later targets explicitly `unattempted`;
- an unexpected programmer/config/filesystem exception records a sanitized type-only failure, closes the browser, exports partial evidence, and re-raises;
- no failed target is retried; and
- no replacement target is appended.

Rollback means stopping new requests and preserving tagged evidence. It never deletes rows or rewrites history.

## Testing and Verification

### Deterministic Tests

Plan 2 must add fixture-driven coverage for:

- CLI command separation and offline-CLI import guards;
- stage predecessor and artifact validation;
- exact smoke condition and request budgets;
- ordered page 1 followed optionally by page 2, with page 3 and retry rejection;
- first-seen distinct-before-20 provenance-aware cohort freezing across the bounded result;
- fewer-than-20 valid resolved identities after page 2 with zero detail requests;
- `target_cap` acceptance at exactly 20 canonical IDs;
- duplicate canonical IDs, `jobId_fallback` rows, and unusable identity rows;
- sequential detail ordering and pacing;
- success, 2520, auth, WAF, IP block, transient, invalid payload, and ID mismatch outcomes;
- batch-stop unattempted accounting;
- zero smoke persistence;
- partial artifact export on exception and cancellation;
- endpoint/`rcdType` matrix ordering;
- 31-category pilot ordering;
- natural exhaustion and empty confirmation;
- cross-run set comparison and stability metrics;
- staging amplification boundaries; and
- refusal to mutate production defaults.

All network tests use saved responses or injected transports. Deterministic tests never launch Playwright.

### Live Verification Order

1. verify Plan 1 artifacts and recapture the baseline;
2. run the at-most-two-listing/20-detail smoke once after separate authorization;
3. verify its artifact and database no-write invariant;
4. stop for review if any smoke gate fails;
5. run calibration only after an accepted smoke;
6. run the 31-category pilot only after calibration review;
7. run one full census only after candidate freeze; and
8. repeat censuses only after the first full run verifies.

No later stage starts automatically.

## Acceptance Criteria

Plan 2 is complete only when:

1. the live CLI and pure research services pass all deterministic tests;
2. the at-most-two-listing/20-detail smoke meets its diagnostic gate with 20 first-seen canonical IDs and `target_cap`, then produces a verified artifact;
3. endpoint and `rcdType` selection is backed by saved live evidence;
4. the 31-category pilot has every planned page observed without a hidden gap;
5. three full censuses naturally exhaust all conditions;
6. every accepted run has zero unresolved gaps, zero identity conflicts, zero conservation difference, and zero unclassified failures;
7. fixed-cohort Jaccard is at least 0.95;
8. unique-count coefficient of variation is at most 5 percent;
9. all run and union set hashes reproduce from JSONL; and
10. production defaults remain unchanged.

## Deliverables

- Plan 2 live-research design and implementation plan;
- live-only stage-gated research CLI;
- verified at-most-two-listing/20-detail smoke artifact;
- endpoint and `rcdType` calibration report;
- 31-category pilot report;
- frozen census candidate contract;
- three full-census artifacts;
- stability and cost comparison report; and
- Plan 3 entry decision with exact failing gates or accepted parameters.

## Production Decision Boundary

Plan 2 produces evidence and a candidate recommendation. It does not change the default OfferToday planner. Any production change remains blocked until Plans 3 and 4 also satisfy discovery, precision, detail-quality, stability, conservation, and efficiency gates.
