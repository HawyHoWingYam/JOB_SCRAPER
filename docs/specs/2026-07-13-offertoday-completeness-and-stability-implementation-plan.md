# OfferToday Completeness and Stability Implementation Plan

**Date:** 2026-07-13

**Status:** Proposed for execution

**Authoritative inputs:**

- `docs/specs/2026-07-13-offertoday-completeness-and-stability-research-spec.md`
- `docs/specs/2026-07-13-offertoday-plan2-census-decision.md`
- 2026-07-13 live UI conclusion: OfferToday's listing pagination is cursor-based; the current stateless `pageSize=50` crawler contract is invalid

## 1. Objective

Implement and prove a cursor-correct OfferToday discovery policy, then use that policy to measure full-site discovery recall, broad-IT coverage, detail completion, recovery, and production stability.

The implementation must keep these questions separate:

1. **Discovery recall:** which distinct canonical OfferToday `jobId` values can be reached repeatedly through a valid listing cursor chain?
2. **Pipeline completion:** which discovered IDs become identity-valid, complete published jobs after detail fetch, parsing, persistence, retry, and recovery?

The immediate implementation tranche is **Phase A and Phase B only**: typed cursor contracts, strict cursor invariants, and the bounded five-variant pagination bake-off. Phases C-H are included below as gated follow-on work, but no later live phase may start merely because its code exists.

## 2. Authoritative Starting Point

### 2.1 Confirmed evidence

- The current crawler independently builds every page with `pageSize=50`.
- OfferToday's current UI uses `pageSize=10` and returns `sessionId`, `supplePage`, `suppleAmount`, and `suppleType` on page 1.
- The UI returns those values on page 2 and subsequent pages; the crawler currently drops them.
- The server returns 10 rows even when the crawler requests 50, so the frozen Plan 2 page-size assumption is false.
- Three full censuses had low count CV but only `0.849-0.869` pairwise Jaccard.
- The fixed cohort's minimum Jaccard was `0.868300`, below the `0.95` gate.
- Cross-page duplication is severe; category `127000` returned 450 rows but only 136-138 distinct IDs per run.
- The accepted 20-ID detail smoke was 20/20, so detail transport is not the first implementation priority.
- `suppleRcdList` and detail context fields remain hypotheses. They must be measured, not treated as confirmed causes.

### 2.2 Current code boundary

| Current area | Current behavior | Required change |
|---|---|---|
| `constants.py::build_offertoday_listing_payload()` | Hard-codes `pageSize=50`; accepts no cursor | Build from an immutable condition plus explicit pagination policy and validated cursor |
| `listing_runner.py::OfferTodayListingTransport` | Returns a raw JSON dictionary | Return or adapt into a typed page result carrying cursor and response-contract evidence |
| `listing_runner.py::OfferTodayListingRunner.run()` | Rebuilds each page independently; runner has no cursor state | Own one condition-local cursor chain and replay the same cursor input on retry |
| `listing_runner.py::ListingPageObservation` | Records rows, `total`, and `hasMore`, but no cursor transition or supplemental cohort | Record hashed cursor transition, requested/effective page size, result and supplemental cohorts separately |
| `offertoday_browser_runtime.py` | Performs request transport and returns parsed JSON; no typed listing result | Remain free of hidden pagination state while exposing typed request/response evidence and browser-context identity |
| `research/live_contracts.py::CensusCandidate` | Locks the rejected Plan 2 v1 controls, including `page_size=50` | Preserve v1 replay; introduce a separate versioned cursor-correct candidate contract |
| `offertoday_research_census.py` | Implements Plan 2 smoke/calibration/pilot/census/fixed-repeat/compare | Add versioned Phase A/B commands without changing the meaning of old commands or artifacts |
| `research/stage_gate.py` | Strictly verifies Plan 2 experiments | Dispatch new experiment versions to new verifiers while retaining old strict replay |

### 2.3 Evidence compatibility requirement

The Plan 2 artifacts and the rejected Plan 2 decision are immutable historical evidence. Do not silently change the meaning of `CensusCandidate`, its hash, its existing experiment names, or the existing strict-replay rules.

The cursor-correct path must use a new contract version, new candidate hash, and new experiment names. Existing v1 fixture tests and locally available Plan 2 artifacts must continue to verify exactly as before.

## 3. Iteration Scope and Phase Gates

| Tranche | Scope | Live execution authorization | Exit required before next tranche |
|---|---|---|---|
| 1 | Phase A: cursor contract and deterministic invariants | No live requests required | Focused tests pass; legacy replay remains valid; production defaults unchanged |
| 2 | Phase B: bounded pagination bake-off | Five variants, three categories, two repeats, max 10 logical pages per condition, zero detail, zero product writes | One candidate passes every Phase B gate; otherwise stop |
| 3 | Phase C: endpoint and partition research | Only after Phase B candidate acceptance | Endpoint-specific cursor contracts and retained partitions pass their gates |
| 4 | Phase D: cursor-correct full-site census | Only after Phase C candidate freeze | Three censuses plus three fixed repeats pass every stability/conservation gate |
| 5 | Phase E-F: broad-IT reference and planner ablation | Only after Phase D reference denominator exists | Precision, false-negative, recall, gap, and efficiency gates pass |
| 6 | Phase G: detail context and 20/100/500 canaries | Each cohort separately authorized after the previous cohort passes | 500-ID detail acceptance passes |
| 7 | Phase H: recovery and production soak | Only after Phase G | Failure injection passes and all three soak runs pass |
| 8 | Production adoption | Separate final change after all evidence is verified | Production defaults changed with rollback guard and full verification |

Tasks for later tranches may be implemented behind explicit research-only entry points, but they must not auto-start, alter defaults, or consume a live request budget before the preceding gate passes.

## 4. Cross-Cutting Safety and Evidence Invariants

1. Preserve runtime artifacts under `backend/runtime/offertoday-research/`; do not commit them.
2. Every live command requires exactly two distinct, matching database baseline artifacts and rechecks the current database before opening a browser.
3. Phase B is no-detail and no-product-write. It must use `ResearchNoopListingStagingSink` and prove the Job, Company, and staging snapshots are unchanged.
4. Phase C remains no-product-write. Phase D may create deduplicated staging rows only after its candidate is frozen; it must not publish Jobs or mutate Companies.
5. Do not use `data.total` as a denominator, stop condition, or acceptance signal. Record it only as drift diagnostics.
6. All recall, overlap, stability, detail, and publication metrics use distinct canonical `jobId` values.
7. A cursor is owned by exactly one `(run, repeat, variant, condition, browser context)` chain.
8. Never reuse a cursor across category, keyword, endpoint, `rcdType`, variant, browser context, or resumed process. The sole Phase B exception is the explicitly named `ui-cursor-restart` experiment, where cross-context cursor transfer is the variable under test; it must be marked experimental and cannot leak into another variant or production fallback.
9. Retry the same page with the exact same input cursor and request fingerprint. If a new cursor chain is required, restart the condition from page 1.
10. Do not checkpoint mid-condition. The durable checkpoint is the last completed condition boundary.
11. No raw `sessionId`, cookie, CSRF token, authorization value, or browser-profile path may appear in events, manifests, summaries, errors, or patches. Persist hashes or redacted presence/continuity fields only.
12. Stop immediately on auth expiry, WAF challenge, IP block, identity mismatch, cursor contract violation, unresolved listing gap, or non-zero conservation difference.
13. A cursor contract failure must occur before any page rows are sent to a staging sink.
14. Supplemental rows remain a distinct evidence cohort until Phase C explicitly classifies their role. Do not silently merge them into product staging.
15. Production defaults in `constants.py`, `offertoday_standalone_crawl.py`, Compose, and environment files stay unchanged until the final adoption task.

## 5. Target Design

### 5.1 Versioned listing contracts

Add a focused contract module, preferably `backend/app/sources/offertoday/listing_contract.py`, and keep identity resolution in the existing identity module.

The minimum immutable types are:

```python
@dataclass(frozen=True, slots=True)
class OfferTodayListingCursor:
    session_id: str
    supple_page: int
    supple_amount: int
    supple_type: int
    effective_page_size: int


@dataclass(frozen=True, slots=True)
class OfferTodayListingRequestPolicy:
    protocol_version: int
    pagination_mode: Literal["stateless-control", "response-cursor"]
    requested_page_size: int
    browser_lifecycle: Literal[
        "shared-variant-runtime",
        "condition-local-runtime",
        "restart-each-page",
    ]


@dataclass(frozen=True, slots=True)
class OfferTodayListingPageResult:
    raw_payload: Mapping[str, Any]
    result_rows: tuple[Mapping[str, Any], ...]
    supplemental_rows: tuple[Mapping[str, Any], ...]
    cursor: OfferTodayListingCursor | None
    has_more: bool | None
    reported_total: int | None
    response_page_size: int | None
```

Contract rules:

- Exact integers reject booleans, floats, negative values, and numeric strings.
- Cursor mode page 1 must return all endpoint-required cursor fields.
- Cursor mode page `N+1` is built from the frozen base condition and page `N` cursor; no base dictionary is mutated.
- Cursor mode rejects unexplained `sessionId` rollover and effective page-size changes inside one chain.
- Any row-capacity or target-budget evidence uses the validated effective response page size, never the stale requested value of 50. Logical request budgets remain page-based.
- Stateless mode is available only when explicitly selected as the named control.
- `resultList` and `suppleRcdList` are validated, copied, identity-resolved, counted, and deduplicated separately.
- The in-memory cursor may contain the raw session ID. Its evidence serializer may expose only a SHA-256, presence flags, exact non-sensitive scalar fields, and continuity results.

Do not add the new fields to the existing v1 `CensusCandidate`. Introduce a new `DiscoveryCandidateV2` (final name may follow code review) with a canonical `candidate_version=2` payload and hash.

### 5.2 Cursor state machine

For each condition, the runner follows this state transition:

```text
frozen condition + request policy + page 1 + no cursor
  -> classified typed page result
  -> validate response contract
  -> record cursor transition and row cohorts
  -> page 2 built with page-1 cursor
  -> ...
  -> endpoint terminal signal
  -> empty confirmation under the same valid chain
  -> completed condition boundary
```

Retry semantics:

- A transient retry reuses the same page number, input cursor, browser context, payload hash, and logical-request ID.
- The attempt number and physical-request ID change.
- A response from a failed attempt never advances the chain.
- Browser loss invalidates the in-memory cursor. The condition is restarted from page 1 in a new browser context and prior IDs are deduplicated; it is not continued at page `N`.
- Phase B's `ui-cursor-restart` variant is a deliberate experiment: the browser restarts between pages while the server cursor is carried forward. Any rejection is recorded as variant evidence, not retried into another variant.

### 5.3 Observation schema

Extend the v2 page observation without changing v1 event interpretation. Record at least:

- `protocol_version`, `variant_id`, `repeat_index`, and a condition-execution hash;
- logical request ID, physical attempt ID, page, and attempt;
- request fingerprint and browser-context hash;
- pagination mode and browser lifecycle;
- requested page size, response page size, and effective page size;
- cursor-input hash, cursor-output hash, cursor-field presence, and session continuity result;
- result-row count, supplemental-row count, each cohort's canonical IDs/identity pairs, and their overlap;
- new canonical IDs, duplicates against earlier pages, and zero-new-page classification;
- `hasMore`, diagnostic `total`, terminal signal, empty-confirmation state, latency, retry reason, and stop reason.

The run summary must derive metrics from replayed page events, not trust counters supplied by the live runner.

### 5.4 Browser runtime ownership

`OfferTodayBrowserRuntime` remains responsible for HTTP/browser transport, cookies, CSRF forwarding, and one browser-context identity. It must not store the current category, page number, or listing cursor.

The research service owns runtime lifecycles:

- `shared-variant-runtime`: one fresh runtime for the variant repeat; cursor state remains condition-local;
- `condition-local-runtime`: one fresh runtime for one condition and all its pages;
- `restart-each-page`: a fresh runtime for every logical page.

The runtime exposes only a generated context identifier whose hash is persisted. Do not derive it from a profile path, cookie, or CDP endpoint.

### 5.5 Legacy replay and new experiment versions

Retain existing strict verifiers for:

- `runtime-smoke`;
- `listing-calibration`;
- `category-pilot`;
- `census-candidate`;
- `full-census`;
- `fixed-condition-repeat`; and
- `census-stability-comparison`.

Add new experiment names instead of changing old ones, for example:

- `cursor-pagination-bakeoff-v2`;
- `cursor-pagination-comparison-v2`;
- `discovery-candidate-v2`;
- `endpoint-partition-probe-v2`;
- `full-census-v2`;
- `fixed-condition-repeat-v2`;
- `census-stability-comparison-v2`;
- `it-reference-validation-v2`;
- `planner-ablation-v2`;
- `detail-context-canary-v2`; and
- `production-soak-v2`.

`verify_live_research_run()` dispatches by exact experiment name and version. Unknown versions fail closed.

## 6. Implementation Tasks

### Task 1: Freeze legacy replay before introducing v2

**Files:**

- `backend/app/sources/offertoday/research/live_contracts.py`
- `backend/app/sources/offertoday/research/stage_gate.py`
- `backend/tests/test_offertoday_research_calibration.py`
- `backend/tests/test_offertoday_research_stage_gate.py`
- `backend/tests/test_offertoday_research_census_cli.py`

**Implementation:**

1. Add explicit tests proving the current v1 candidate canonical payload and hash remain byte-for-byte stable.
2. Add verifier-routing tests for every existing experiment name.
3. Where the locally ignored Plan 2 artifacts exist, run generic verification and strict replay against the primary artifact index from the decision document before and after the v2 work.
4. Introduce an explicit version boundary for new contracts; do not relax v1 parsing to accept v2 fields.
5. Add a regression test that a v2 artifact cannot be parsed as v1 and vice versa.

**Gate:** v1 fixtures and locally available immutable artifacts produce the same validity, issues, and candidate hashes as before. No production file changes.

### Task 2: Add typed cursor, request-policy, and page-result contracts

**Files:**

- Create `backend/app/sources/offertoday/listing_contract.py`
- `backend/app/sources/offertoday/constants.py`
- Create `backend/tests/test_offertoday_listing_contract.py`
- `backend/tests/test_offertoday_search_space.py`

**Implementation:**

1. Implement exact scalar validators for `sessionId`, supplemental cursor fields, response `pageSize`, `hasMore`, and diagnostic `total`.
2. Make `build_offertoday_listing_payload()` accept an explicit requested page size and optional validated cursor while preserving its current default behavior for production callers.
3. Build every payload from new data; never mutate the caller's base condition or prior payload.
4. Parse `resultList` and `suppleRcdList` into separate immutable cohorts.
5. Add cursor evidence serialization that hashes `sessionId` and rejects accidental raw serialization.
6. Add a `DiscoveryCandidateV2` canonical payload containing endpoint contract version, pagination mode, page size, browser lifecycle, terminal policy, fixed categories, pacing, and source artifact hash.

**Tests:**

- Page 1 without required cursor fields fails cursor mode.
- Page 2 contains the exact page-1 cursor values.
- Boolean, float, negative, blank, and malformed cursor values fail.
- Response `pageSize=10` is the effective evidence value when 50 was requested.
- A later response page-size change fails the chain.
- Base conditions and earlier payloads remain unchanged.
- Supplemental rows are copied, counted, and deduplicated separately.
- Durable evidence contains no raw session ID.

**Gate:** contract tests pass and the existing production payload tests still prove unchanged defaults.

### Task 3: Implement the condition-local cursor state machine

**Files:**

- `backend/app/sources/offertoday/listing_runner.py`
- `backend/app/sources/offertoday/parsers.py`
- `backend/app/sources/offertoday/research/conservation.py`
- `backend/tests/test_offertoday_listing_runner.py`
- `backend/tests/test_offertoday_research_conservation.py`

**Implementation:**

1. Pass an explicit request policy to the runner; keep a compatibility path for named v1/stateless calls.
2. Scope cursor state to one condition execution. Clear it before the next condition.
3. Use page 1 without a cursor; use the prior successful page's cursor for page 2 onward.
4. Hold cursor advancement until classification, cursor validation, identity analysis, and observation construction all succeed.
5. Replay the same input cursor and request fingerprint on retry.
6. Reject unexplained rollover, missing cursor, cross-condition cursor use, effective page-size drift, and resume-at-page-`N` without a live validated chain.
7. Record result and supplemental identity cohorts separately. Do not stage supplemental rows in Phase A/B.
8. Require endpoint terminal signal followed by empty confirmation under the same valid cursor chain.
9. Stop before staging on cursor violation, identity issue, identity conflict, or unresolved gap.
10. Classify a full page with zero new IDs; do not silently treat it as progress or exhaustion.

**Tests:**

- Two interleaved conditions cannot see one another's cursor.
- A retry uses one logical page and multiple physical attempts with identical cursor input.
- A new cursor returned by a failed attempt is ignored.
- Session rollover fails and leaves staging untouched.
- Browser-loss recovery restarts at page 1 and deduplicates earlier IDs.
- Empty confirmation must use the same chain.
- A non-empty confirmation page is a contract anomaly.
- Result/supplement overlap and cross-page duplicates conserve exactly.

**Gate:** all runner/conservation tests pass with zero staging calls on every contract-failure fixture.

### Task 4: Add typed browser transport and controllable runtime lifecycles

**Files:**

- `backend/app/scraper/offertoday_browser_runtime.py`
- `backend/app/services/offertoday_research_live_service.py`
- `backend/tests/test_offertoday_browser_runtime.py`
- `backend/tests/test_offertoday_research_live_service.py`

**Implementation:**

1. Add a typed listing-page transport adapter while retaining `fetch_listing_json()` for legacy/session-health callers.
2. Return successful HTTP metadata and parsed response ownership without storing cursor state on the runtime.
3. Generate a non-sensitive in-memory browser-context identifier when a runtime starts; persist only its hash.
4. Let the live service create runtimes at variant, condition, or page boundaries according to policy.
5. Ensure all runtime instances close on success, rejection, retry exhaustion, and exceptions.
6. Preserve CSRF and cookie forwarding and the existing auth/WAF/IP classification behavior.

**Tests:**

- Runtime rejects unsupported listing URLs.
- Context hashes change on restart and remain stable within one context.
- Restart-each-page actually closes and recreates the runtime.
- Cursor values are request data, not runtime attributes.
- Cleanup occurs on page-2 contract failure and transport exceptions.

**Gate:** runtime and service tests pass; session health behavior remains unchanged.

### Task 5: Extend v2 observations, artifacts, conservation, and strict replay

**Files:**

- `backend/app/sources/offertoday/listing_runner.py`
- `backend/app/services/offertoday_research_observation_service.py`
- `backend/app/sources/offertoday/research/artifacts.py`
- `backend/app/sources/offertoday/research/conservation.py`
- `backend/app/sources/offertoday/research/stage_gate.py`
- `backend/tests/test_offertoday_research_observation_service.py`
- `backend/tests/test_offertoday_research_artifacts.py`
- `backend/tests/test_offertoday_research_conservation.py`
- `backend/tests/test_offertoday_research_stage_gate.py`

**Implementation:**

1. Add v2 page-attempt and condition-boundary schemas with cursor transition and cohort fields from Section 5.3.
2. Keep raw secrets out of database events before artifact export; artifact redaction is a second defense, not the first.
3. Replay logical/physical request counts, cursor continuity, distinct IDs, duplicates, marginal IDs, result/supplement overlap, and conservation from events.
4. Add strict v2 checks for exact event ordering, retry semantics, per-condition cursor isolation, request budgets, no-write evidence, and terminal status.
5. Add negative fixtures for forged hashes, changed cursor inputs, missing attempts, duplicate sequence numbers, and leaked raw session IDs.

**Gate:** generic hash verification and v2 strict replay both reject every tampered fixture and accept only fully replayable fixtures; v1 replay still passes.

### Task 6: Implement the bounded pagination bake-off model and decision engine

**Files:**

- Create `backend/app/sources/offertoday/research/pagination_bakeoff.py`
- `backend/app/sources/offertoday/research/live_contracts.py`
- `backend/app/services/offertoday_research_live_service.py`
- Create `backend/tests/test_offertoday_pagination_bakeoff.py`
- `backend/tests/test_offertoday_research_live_service.py`

**Freeze these variants:**

The endpoint is frozen to `/wapi/geek/recommend/search/list` and `rcdType` is omitted for all five Phase B variants. Only pagination and browser-lifecycle controls may differ. Because the research specification names both a generic `ui-cursor` and `ui-cursor-same-browser` variant, this plan makes their runtime ownership explicit: the generic variant shares one runtime across its three conditions, while the same-browser variant dedicates one runtime to exactly one condition chain.

| Variant | Cursor | Requested size | Browser lifecycle |
|---|---|---:|---|
| `stateless-current` | None | 50 | Shared runtime; named research control only |
| `ui-cursor` | Response-derived | 10 | One runtime shared across the variant, cursor isolated per condition |
| `ui-cursor-50` | Response-derived | 50 | One runtime shared across the variant, cursor isolated per condition |
| `ui-cursor-restart` | Response-derived | 10 | Restart browser between pages |
| `ui-cursor-same-browser` | Response-derived | 10 | One fresh runtime dedicated to one condition chain |

**Implementation:**

1. Freeze categories `(118000, 112000, 127000)` and two repeat indices.
2. Cap every `(repeat, variant, category)` at 10 logical pages.
3. Permit at most one retry for a transient transport failure; all cursor or hard-stop failures are non-retryable.
4. Use zero detail requests and the no-op staging sink.
5. Pre-register a deterministic random seed and randomize variant order independently per category/repeat before any response is read.
6. Compute distinct IDs, raw/supplement rows, duplicate rate, marginal IDs, earlier-page overlap, same-page cross-repeat Jaccard, cursor violations, page-size/total drift, request and time cost, and unique union contribution.
7. Operationalize “material duplicate reduction” before live execution as both at least 10 percentage points absolute and at least 20% relative reduction versus `stateless-current`; record the frozen rule in the artifact. If this threshold is amended, the amendment must precede all live bake-off artifacts.
8. Select no candidate unless it has:
   - zero cursor violations, unresolved gaps, identity conflicts, and conservation difference;
   - the frozen material duplicate reduction;
   - distinct-ID union greater than or equal to the control at no more than 2x logical request cost;
   - minimum same-condition short-window Jaccard `>= 0.95`; and
   - no unclassified zero-new full page.

**Gate:** deterministic decision tests cover pass, each individual rejection reason, ties, order independence, and no-candidate outcomes.

### Task 7: Add Phase B live and offline CLI commands

**Files:**

- `backend/scripts/offertoday_research_census.py`
- `backend/app/services/offertoday_research_live_service.py`
- `backend/app/sources/offertoday/research/stage_gate.py`
- `backend/tests/test_offertoday_research_census_cli.py`

**Commands to add:**

```text
pagination-bakeoff --repeat-index {1|2} --order-seed <frozen-int>
compare-pagination --bakeoff-artifact <repeat-1> --bakeoff-artifact <repeat-2>
freeze-discovery-candidate --comparison-artifact <accepted-comparison>
```

**Implementation:**

1. Each live repeat requires exactly two matching baseline artifacts and current-database equality.
2. Freeze a request budget of 150 logical listing pages, at most 300 physical attempts, zero detail attempts, and zero product writes per repeat.
3. Persist the exact randomized order, candidate controls, code/provenance hashes, start/end snapshots, and no-write evidence.
4. `compare-pagination` is offline and refuses unverified or mismatched parents.
5. `freeze-discovery-candidate` is offline and runs only when comparison accepted exactly one candidate.
6. Return distinct exit codes for accepted, valid-but-rejected, hard stop, and invalid evidence.
7. Do not reuse the old `calibrate`, `freeze-candidate`, or Plan 2 candidate semantics.

**Gate:** CLI tests prove pre-browser validation, exact budgets, offline command isolation, immutable artifacts, strict replay, and fail-closed candidate freezing.

### Task 8: Phase A/B deterministic verification and live review gate

**Deterministic verification:**

```powershell
python -m pytest -q `
  backend/tests/test_offertoday_listing_contract.py `
  backend/tests/test_offertoday_listing_runner.py `
  backend/tests/test_offertoday_browser_runtime.py `
  backend/tests/test_offertoday_pagination_bakeoff.py `
  backend/tests/test_offertoday_research_live_service.py `
  backend/tests/test_offertoday_research_observation_service.py `
  backend/tests/test_offertoday_research_artifacts.py `
  backend/tests/test_offertoday_research_conservation.py `
  backend/tests/test_offertoday_research_stage_gate.py `
  backend/tests/test_offertoday_research_census_cli.py

python -m pytest -q backend/tests
git diff --check
```

**Live sequence after deterministic review:**

```powershell
# Capture two fresh matching baselines before repeat 1.
python backend/scripts/offertoday_research.py baseline
python backend/scripts/offertoday_research.py baseline

python backend/scripts/offertoday_research_census.py pagination-bakeoff `
  --repeat-index 1 `
  --order-seed <frozen-seed> `
  --baseline-artifact <baseline-1> `
  --baseline-artifact <baseline-2>

python backend/scripts/offertoday_research_census.py verify-run `
  --artifact <repeat-1-artifact>

# Recapture two matching baselines before repeat 2.
python backend/scripts/offertoday_research.py baseline
python backend/scripts/offertoday_research.py baseline

python backend/scripts/offertoday_research_census.py pagination-bakeoff `
  --repeat-index 2 `
  --order-seed <frozen-seed> `
  --baseline-artifact <baseline-3> `
  --baseline-artifact <baseline-4>

python backend/scripts/offertoday_research_census.py verify-run `
  --artifact <repeat-2-artifact>

python backend/scripts/offertoday_research_census.py compare-pagination `
  --bakeoff-artifact <repeat-1-artifact> `
  --bakeoff-artifact <repeat-2-artifact>

python backend/scripts/offertoday_research_census.py verify-run `
  --artifact <comparison-artifact>
```

**Review gate:**

- If no variant passes, stop. Inspect endpoint contracts in a new bounded Phase C design amendment; do not run a census.
- If one variant passes, independently recompute the decision, verify its comparison artifact, then freeze the v2 discovery candidate.
- Production defaults remain unchanged either way.

### Task 9: Phase C endpoint-specific contracts and partition catalog

**Starts only after Task 8 accepts a cursor candidate.**

**Files:**

- `backend/app/sources/offertoday/listing_contract.py`
- `backend/app/sources/offertoday/search_space.py`
- Create `backend/app/sources/offertoday/research/partition_research.py`
- `backend/app/scraper/offertoday/category_registry.py`
- `backend/tests/test_offertoday_search_space.py`
- Create `backend/tests/test_offertoday_partition_research.py`

**Implementation:**

1. Model `/recommend/search/list` and `/recommend/list` as separate endpoint contracts; never assume identical cursor or terminal fields.
2. Freeze `rcdType` omitted and only evidence-backed values per endpoint.
3. Generate top-level and official leaf-category partitions from registry fields `code`, `name`, `parent_code`, `level`, and `children`.
4. Add date/publish-time, language, or location partitions only after a bounded contract probe proves support.
5. Keep endpoint discovery separate from cursor discovery and keep Phase C no-write.
6. Retain a partition only if it adds at least `0.5%` active reference IDs or a documented high-value cohort unavailable through cheaper conditions.
7. Record the last-100-request marginal curve as an efficiency metric, never as an exhaustion replacement.

**Gate:** every retained endpoint/partition has a valid contract, cursor-confirmed terminal state, empty confirmation, zero gaps/conflicts/conservation difference, and verified unique contribution.

### Task 10: Phase C live orchestration and discovery-candidate freeze

**Files:**

- `backend/scripts/offertoday_research_census.py`
- `backend/app/services/offertoday_research_live_service.py`
- `backend/app/sources/offertoday/research/stage_gate.py`
- `backend/tests/test_offertoday_research_census_cli.py`

**Implementation:**

1. Add separately budgeted `probe-endpoints`, `probe-partitions`, `compare-partitions`, and `freeze-discovery-policy` commands.
2. Require two baselines per live probe and generic plus strict verification before comparison.
3. Freeze exact condition order, endpoint adapter version, partition definitions, cursor policy, pacing, terminal policy, and source artifact hashes into `DiscoveryCandidateV2`.
4. Fail candidate freezing if any retained condition is supported only by `total`, page cap, or marginal saturation without valid cursor exhaustion.

**Gate:** one immutable candidate artifact is accepted; otherwise stop before Phase D.

### Task 11: Phase D cursor-correct census and fixed repeats

**Files:**

- `backend/app/sources/offertoday/research/live_contracts.py`
- `backend/app/sources/offertoday/research/stability.py`
- `backend/app/services/offertoday_research_live_service.py`
- `backend/scripts/offertoday_research_census.py`
- `backend/tests/test_offertoday_research_stability.py`
- `backend/tests/test_offertoday_research_census_cli.py`

**Implementation:**

1. Add v2 census and fixed-repeat commands that accept only the frozen v2 candidate.
2. Run all 31 top-level categories under the accepted endpoint/cursor/partition policy.
3. Preserve exact candidate hash across three full censuses and three fixed repeats.
4. Place the three censuses in at least two windows separated by six hours; do not use a blocking sleep.
5. Run the fixed categories `(118000, 112000, 127000)` three times in one short window.
6. Permit deduplicated listing staging only in this gated phase; keep Jobs and Companies unchanged and verify reconciliation/conservation.
7. Record exact union, intersection, added/removed cohorts, per-page marginal IDs, and all zero-new full pages.
8. Classify a zero-new full page only with explicit recommendation/supplement evidence proving that it does not mask recall.

**Acceptance:**

- valid cursor-confirmed exhaustion for every condition;
- fixed-cohort minimum Jaccard `>= 0.95`;
- unique-count CV `<= 0.05`;
- unresolved gaps, identity conflicts, conservation difference, unclassified failures, and unexplained rollovers all equal zero; and
- no unclassified full page with zero new IDs.

**Gate:** the stable reference denominator is frozen as IDs seen in at least two time-aligned census runs plus independently confirmed active holdout IDs. The full union remains diagnostic only.

### Task 12: Phase E broad-IT reference construction and validation

**Files:**

- Create `backend/app/sources/offertoday/research/it_reference.py`
- `backend/app/sources/offertoday/search_space.py`
- `backend/app/services/offertoday_research_live_service.py`
- Create `backend/tests/test_offertoday_it_reference.py`
- `backend/tests/test_offertoday_research_census_cli.py`

**Implementation:**

1. Accept official category `118000` and its official descendants.
2. Apply versioned deterministic technical-title rules to all other categories.
3. Keep ambiguous titles unresolved until a controlled detail fetch; never silently count them as IT.
4. Freeze predicted-positive and predicted-negative samples, their IDs, strata, and hashes before labels are read.
5. Use at least 200 rows in each cohort, proportionally stratified by category, language, and evidence rule, capped at 500 per validation cycle.
6. Store labels and adjudication provenance in immutable supplemental artifact JSON, not production schema.
7. Compute Wilson intervals from frozen counts.

**Acceptance:**

- predicted-positive Wilson 95% lower bound `>= 0.90`;
- predicted-negative one-sided 95% false-negative upper bound `<= 0.02`; and
- unresolved candidates excluded from the accepted IT denominator.

### Task 13: Phase F planner ablation and exact miss analysis

**Files:**

- Create `backend/app/sources/offertoday/research/planner_ablation.py`
- `backend/app/sources/offertoday/search_space.py`
- `backend/scripts/offertoday_research_census.py`
- Create `backend/tests/test_offertoday_planner_ablation.py`

**Implementation:**

1. Freeze the five planner families: category only; keyword only; category plus keyword; category plus keyword plus hybrid; measured best family set with low-yield conditions removed.
2. Evaluate every planner against the same time-aligned Phase D reference windows and holdout set.
3. Report exact misses by official category, title pattern, language, age, and query family.
4. Report sampled precision, duplicates, requests, seconds per new reference ID, and holdout-only discoveries.
5. Reject any candidate that doubles request cost without at least two percentage points of recall improvement.

**Acceptance:** recall proxy `>= 0.98`, Phase E precision passes, unresolved gaps equal zero, and the efficiency rule passes.

**Gate:** freeze one planner artifact; do not change production defaults.

### Task 14: Phase G typed detail context and 20-ID transport bake-off

**Files:**

- `backend/app/sources/offertoday/listing_contract.py`
- `backend/app/scraper/offertoday_browser_runtime.py`
- `backend/app/scraper/offertoday_browser_detail_scraper.py`
- `backend/app/services/offertoday_research_live_service.py`
- `backend/tests/test_offertoday_browser_runtime.py`
- `backend/tests/test_offertoday_canonical_and_identity.py`
- `backend/tests/test_offertoday_research_live_service.py`

**Implementation:**

1. Add a frozen `OfferTodayDetailRequestContext` with optional listing-derived `sessionId`, `lid`, `curIndex`, `encryptExpectId`, and `markId` plus explicit provenance.
2. Capture context from the exact listing observation that supplied the canonical ID; do not reconstruct or cross-assign it.
3. Build detail query strings with a URL encoder and omit absent fields.
4. Freeze one distinct 20-ID cohort before running any variant.
5. Compare minimal identifiers; listing session plus identifiers; full UI context when present; and fresh-headless, storage-state, and reusable-browser transports.
6. Keep this transport comparison no-write and preserve identity validation.
7. Record deterministic start/completion timestamps, latency, request identity hash, response identity hash, context provenance hash, and stop classification for every attempt.
8. Retain only fields or modes with measured success/stability benefit or proven contract necessity.

**Gate:** strict replay verifies all request variants, identities, context provenance, and no-write evidence. No assumption that fuller context is better.

### Task 15: Phase G 100-ID and 500-ID persistence canaries

**Files:**

- `backend/app/services/offertoday_detail_pipeline.py`
- `backend/app/services/crawl_job_runtime.py`
- `backend/scripts/offertoday_standalone_crawl.py`
- `backend/app/sources/offertoday/research/conservation.py`
- `backend/tests/test_offertoday_detail_pipeline.py`
- `backend/tests/test_crawl_job_runtime.py`
- `backend/tests/test_offertoday_standalone_crawl.py`

**Implementation:**

1. Freeze stratified 100-ID and 500-ID cohorts separately from the accepted Phase E reference.
2. Start each live canary with two matching baselines and a dedicated listing/detail crawl-job ownership chain.
3. Use the real detail pipeline and real transaction boundary for controlled persistence canaries.
4. Group duplicate staging rows by canonical `jobId` before applying the cohort limit.
5. Count structured code `2520` as terminal unavailable and exclude only that cohort from the availability-adjusted denominator.
6. Keep every other failure in the denominator; report original and adjusted denominators together and report the terminal-unavailable rate against the original denominator.
7. Replay listing/detail conservation, persistence evidence, and recovery status from events and database state.

**Acceptance for each frozen cohort:**

- availability-adjusted success `>= 0.99`;
- title, company, and cleaned description completeness each `>= 0.98` among successes;
- identity-mismatch published rows, repeated network targets, terminal retries, unattempted-to-failed transitions, orphan running rows, and Job/listing transaction splits all equal zero.

**Gate:** run 100 first; run 500 only after 100 passes. Do not drain the full broad-IT backlog until 500 passes.

### Task 16: Phase H deterministic recovery and fault injection

**Files:**

- `backend/app/sources/offertoday/listing_runner.py`
- `backend/app/services/offertoday_detail_pipeline.py`
- `backend/app/services/crawl_job_runtime.py`
- `backend/scripts/offertoday_standalone_crawl.py`
- `backend/tests/test_offertoday_listing_runner.py`
- `backend/tests/test_offertoday_detail_pipeline.py`
- `backend/tests/test_crawl_job_runtime.py`
- `backend/tests/test_offertoday_standalone_crawl.py`

**Inject and verify:**

- process stop after detail becomes `running`;
- persistence failure between Company, Job, and listing transitions;
- timeout, non-JSON, 429/5xx, auth expiry, WAF, IP block, and identity mismatch;
- browser loss during a listing cursor chain; and
- resume from the last durable condition boundary.

**Implementation rules:**

- Restart a disrupted listing condition at page 1 in a new browser and deduplicate by canonical ID.
- Never resume a mid-condition cursor unless a separate experiment has proven cross-process/browser durability.
- Recover orphan `running` detail rows according to the existing ownership and attempt rules.
- Keep terminal and hard-stop classifications unchanged.

**Gate:** every injected failure has an exact expected status, event sequence, retry count, database outcome, and conservation result.

### Task 17: Phase H three-run production-paced soak

**Files:**

- `backend/app/sources/offertoday/research/live_contracts.py`
- `backend/app/sources/offertoday/research/stage_gate.py`
- `backend/app/services/offertoday_research_live_service.py`
- `backend/scripts/offertoday_research_census.py`
- `backend/scripts/offertoday_standalone_crawl.py`
- `backend/tests/test_offertoday_research_stage_gate.py`
- `backend/tests/test_offertoday_standalone_crawl.py`

**Implementation:**

1. Freeze the accepted discovery policy, planner, detail context, pacing, and recovery controls into one soak candidate hash.
2. Run the final candidate three times with production pacing.
3. Drain each run's distinct broad-IT backlog through its owned detail crawl.
4. Verify discovery, precision, detail, stability, conservation, recovery, and efficiency gates independently for all three runs.
5. Reject the soak if one run depends on unioning evidence from another run to pass its own pipeline gates.

**Gate:** all three artifacts pass generic hash verification and strict replay, and every gate passes on every run.

### Task 18: Production adoption and rollback guard

**Starts only after Task 17 passes and receives an explicit production-adoption review.**

**Files:**

- `backend/app/sources/offertoday/constants.py`
- `backend/app/sources/offertoday/listing_runner.py`
- `backend/scripts/offertoday_standalone_crawl.py`
- focused production-default guard tests
- Compose/environment files only if the accepted runtime mode requires a documented setting

**Implementation:**

1. Change the production listing default from the v1 stateless policy to the exact accepted v2 candidate.
2. Keep the v1 stateless path available only as an explicit research control, not a fallback.
3. Store the accepted candidate hash/version in crawl request and progress evidence.
4. Add a fail-closed configuration guard so unknown policy versions cannot silently revert to stateless pagination.
5. Document a rollback that restores the previous production policy without deleting artifacts or rewriting crawl history.

**Gate:** focused tests, the complete backend suite, production-default guards, `git diff --check`, and one bounded post-adoption smoke all pass.

## 7. Verification Matrix

### 7.1 Required focused deterministic suite

The final focused command must include the specification's existing files plus the new contract/experiment tests:

```powershell
python -m pytest -q `
  backend/tests/test_offertoday_listing_contract.py `
  backend/tests/test_offertoday_listing_runner.py `
  backend/tests/test_offertoday_browser_runtime.py `
  backend/tests/test_offertoday_pagination_bakeoff.py `
  backend/tests/test_offertoday_research_live_service.py `
  backend/tests/test_offertoday_research_census_cli.py `
  backend/tests/test_offertoday_research_stability.py `
  backend/tests/test_offertoday_research_stage_gate.py `
  backend/tests/test_offertoday_research_artifacts.py `
  backend/tests/test_offertoday_research_conservation.py `
  backend/tests/test_offertoday_detail_pipeline.py `
  backend/tests/test_offertoday_canonical_and_identity.py `
  backend/tests/test_crawl_job_runtime.py `
  backend/tests/test_offertoday_standalone_crawl.py
```

Add phase-specific test modules to this command as they are created.

### 7.2 Full deterministic verification

```powershell
python -m pytest -q backend/tests
git diff --check
```

### 7.3 Artifact verification

Every artifact used as an input must pass both checks:

```powershell
python backend/scripts/offertoday_research.py verify-artifact `
  --artifact <artifact-path>

python backend/scripts/offertoday_research_census.py verify-run `
  --artifact <artifact-path>
```

An artifact that passes generic hashes but fails experiment-specific replay is unusable evidence.

### 7.4 Live stop checklist

Before each live command, confirm:

- two distinct matching baselines;
- current database still equals the baseline;
- frozen command, budget, seed, policy hash, and source hash;
- expected browser mode is available;
- artifact root is ignored and writable; and
- no previous unverified artifact is being used as a parent.

Stop the current run immediately on:

- auth expiry, WAF, or IP block;
- cursor violation or unexplained rollover;
- browser loss not handled by restart-from-page-1 semantics;
- identity mismatch or identity conflict;
- unresolved gap;
- non-zero conservation difference;
- leaked raw cursor/session evidence; or
- request-budget overrun.

## 8. Deliverables by Gate

| Gate | Required durable deliverables |
|---|---|
| Phase A | Typed contracts, runner/runtime tests, v2 observation schema, legacy replay proof |
| Phase B | Two verified bake-off artifacts, verified comparison, independent recomputation, accepted v2 candidate or explicit no-candidate decision |
| Phase C | Endpoint-contract artifacts, partition contribution report, frozen discovery policy |
| Phase D | Three census and three fixed-repeat artifacts, stability comparison, stable reference denominator |
| Phase E | Versioned broad-IT rules, frozen samples/labels, Wilson interval report |
| Phase F | Five-planner ablation, exact miss cohorts, frozen planner candidate |
| Phase G | 20/100/500 canary artifacts, detail-context decision, persistence/conservation report |
| Phase H | Fault-injection evidence, three production-paced soak artifacts, all-gates decision |
| Adoption | Production-default diff, guard tests, rollback note, bounded post-adoption smoke |

## 9. Completion Definition

This plan is fully implemented only when:

1. Listing pagination follows a validated response-derived cursor contract.
2. The accepted discovery denominator comes from cursor-correct repeated evidence, not `total`, row sums, page caps, or one run.
3. Broad-IT precision, false-negative, and planner recall gates pass against that independent denominator.
4. The 500-ID detail canary and all transaction/recovery gates pass.
5. Three production-paced discovery-plus-detail soak runs each pass every gate.
6. Generic artifact verification and strict replay pass for every input and decision artifact.
7. Production defaults are changed only in the final adoption task and remain tied to the accepted candidate hash.
8. Existing Plan 2 artifacts remain replayable as rejected v1 evidence.
9. Runtime artifacts remain ignored and uncommitted, and unrelated worktree changes remain untouched.

Until all nine conditions are proven, OfferToday completeness remains a research result rather than a production claim.
