# OfferToday Completeness and Stability Research Specification

**Date:** 2026-07-13
**Status:** Proposed after Plan 2 evidence review
**Scope:** OfferToday listing discovery, canonical ID coverage, detail retrieval, and production soak
**Production defaults:** Remain unchanged until every acceptance gate in this specification passes

## 1. Objective

Determine and implement the most complete and stable practical OfferToday crawl policy without using raw API totals, gross row counts, or a single successful run as proof of completeness.

The work must answer two separate questions:

1. **Discovery recall:** Which canonical OfferToday `jobId` values can the crawler repeatedly reach?
2. **Pipeline completion:** Which discovered IDs become complete, identity-valid published jobs after detail fetch, parsing, persistence, retry, and recovery?

The target is broad Hong Kong IT coverage, but the discovery reference remains a full-site census across all 31 top-level OfferToday categories. This prevents an IT-only planner from defining its own denominator.

## 2. Confirmed Current Findings

### 2.1 Listing pagination is not following the current site contract

The current crawler constructs every page independently with:

```json
{
  "page": 2,
  "pageSize": 50,
  "jobFunctionCodes": [118000]
}
```

Live browser observation of OfferToday's own search UI on 2026-07-13 showed:

```json
{
  "page": 1,
  "pageSize": 10
}
```

The page-1 response supplied `sessionId`, `supplePage`, `suppleAmount`, and `suppleType`. The UI sent all four values back on page 2:

```json
{
  "page": 2,
  "pageSize": 10,
  "sessionId": "<page-1 sessionId>",
  "supplePage": 0,
  "suppleAmount": 0,
  "suppleType": 0
}
```

The crawler currently drops these response-derived cursor fields. The server also ignores or caps the requested `pageSize=50` and returns 10 rows. Therefore the frozen `page_size=50` research assumption is false for the current endpoint.

### 2.2 Existing census completion does not prove listing completeness

Three accepted full-census runs produced stable counts but unstable sets:

| Run | Distinct IDs | Requests | Duration (s) |
|---|---:|---:|---:|
| `02786783-a668-425d-8c36-a2b785355244` | 5,563 | 1,382 | 5,828.264 |
| `62a9ad89-d80a-4ff2-a253-885d5912409c` | 5,581 | 1,382 | 5,857.461 |
| `d34a5cc8-2a82-46c0-82df-5f8fa1420361` | 5,599 | 1,382 | 5,875.690 |

The unique-count coefficient of variation was only `0.002633`, but pairwise Jaccard values were `0.866979`, `0.849238`, and `0.868940`. The union contained 6,190 IDs while only 4,946 appeared in all three runs.

The short-window fixed cohort failed the stability gate more directly:

| Run | Distinct IDs | Requests |
|---|---:|---:|
| `23be391e-8961-44ea-9a1a-f7ff5776d2e4` | 611 | 138 |
| `83b62928-7161-40ea-9f75-000921183ec6` | 609 | 138 |
| `f51583ec-5cc4-4c2f-86bb-b017ed4a1845` | 608 | 138 |

The fixed union contained 671 IDs, only 548 appeared in all three runs, and the minimum pairwise Jaccard was `0.868300`, below the required `0.95`.

### 2.3 Cross-page duplication is severe

For each fixed category, the runner received 45 non-empty pages of 10 rows and one empty confirmation page. Yet the distinct yield was much lower:

| Category | Raw rows per run | Distinct range | Duplicate rows range |
|---|---:|---:|---:|
| `118000` | 450 | 237-239 | 211-213 |
| `112000` | 450 | 234-236 | 214-216 |
| `127000` | 450 | 136-138 | 312-314 |

For category `118000`, page 3 repeated 8 of page 2's 10 IDs. Page 22 contributed zero new IDs. API `total` also changed inside one pagination sequence. An empty page therefore proves only that this recommendation sequence ended; it does not prove that all eligible jobs were enumerated.

### 2.4 Detail identity and state handling are substantially hardened

The current detail pipeline already has the following desirable properties:

- canonical business identity is `jobId`;
- explicit `encryptJobId` and `jobId_fallback` provenance remain distinct;
- detail candidates are grouped by canonical `jobId` before `detail_limit` is applied;
- duplicate staging rows become one network target and transition together;
- request/response ID mismatch stops publication and the batch;
- code `2520` is terminal and not automatically retried;
- auth expiry, WAF, and IP block stop the batch without marking unattempted rows failed;
- successful Job persistence and listing completion share one transaction;
- complete title, company, and description are required before success.

The accepted bounded smoke fetched 20 distinct targets and recorded 20 successes with title, company, description, and valid identity for all 20. This is useful transport evidence, but it is not a 99% detail acceptance sample.

### 2.5 Detail request context remains an open hypothesis

The crawler calls detail with only `id` and `encryptJobId`. The site's UI also sends listing-derived `sessionId`, `lid`, `curIndex`, and sometimes `encryptExpectId`/`markId`.

Current detail smoke success proves these fields are not always required. It does not prove they have no effect on stability, recommendation attribution, rate limits, or blocked sessions. This must be tested as an explicit variant rather than assumed.

### 2.6 Supplemental listing rows are currently ignored

The current listing parser reads only `data.resultList`. The live response schema also contains `data.suppleRcdList` and supplemental cursor fields. In the bounded unfiltered UI observation performed for this review, `suppleRcdList` was empty on pages 1 through 9, so this review did not prove an actual missed-ID cohort from that field. Other categories, keywords, exhaustion states, or recommendation modes may populate it. The research runner must record and classify it separately before deciding whether those rows belong in the canonical discovery union.

## 3. Safety and Evidence Rules

1. Preserve runtime artifacts under `backend/runtime/offertoday-research/`; do not commit them.
2. Do not change production defaults until the final soak gate passes.
3. Every live stage begins with two matching database baselines.
4. Every listing request and response records a replayable cursor transition with sensitive values hashed or redacted where appropriate.
5. A response-derived cursor is scoped to exactly one condition and one browser context. Never reuse it across categories, keywords, endpoints, sessions, or resumed processes unless a resume experiment explicitly proves that behavior.
6. Treat `data.total` as diagnostic only. It is not a completeness denominator.
7. A condition is accepted only after an endpoint-specific terminal signal and empty confirmation under the same valid cursor chain.
8. A response `pageSize` different from the request must be recorded as contract evidence. The runner must use the accepted response contract, not silently pretend 50 rows were requested and returned.
9. Stop immediately on auth expiry, WAF challenge, IP block, ID mismatch, cursor contract violation, unresolved gap, or non-zero conservation difference.
10. Use distinct canonical IDs for every recall, detail, and publication metric.

## 4. Phase A: Freeze and Test the Cursor Contract

### A1. Add typed cursor evidence

Introduce a typed per-condition state such as:

```python
@dataclass(frozen=True, slots=True)
class OfferTodayListingCursor:
    session_id: str
    supple_page: int
    supple_amount: int
    supple_type: int
    effective_page_size: int
```

The listing transport result must expose:

- `sessionId`;
- `supplePage`;
- `suppleAmount`;
- `suppleType`;
- response `pageSize`;
- `hasMore`;
- `total` as diagnostic metadata only; and
- the exact result and supplemental ID cohorts separately.

Do not mutate the base condition payload in place. Build page `N+1` from the frozen condition plus the validated cursor from page `N`.

### A2. Add strict cursor invariants

Fail the condition when:

- page 1 succeeds but has no usable `sessionId` for an endpoint that requires it;
- page `N+1` returns a different `sessionId` without an explicitly accepted rollover rule;
- a cursor field is boolean, non-integral, negative, or otherwise malformed;
- `pageSize` changes unexpectedly inside one chain;
- the runner attempts page 2 without the page-1 cursor;
- a retry creates a new chain without restarting the condition from page 1; or
- resume tries to continue an expired in-memory cursor without a validated checkpoint protocol.

### A3. Deterministic tests

Add tests for:

- page 1 without cursor fields;
- page 2 carrying exact page-1 cursor values;
- cursor isolation across two conditions;
- retry replay using the same cursor input;
- session rollover rejection;
- response `pageSize=10` overriding the old assumed 50 for evidence and budgets;
- supplemental rows counted and deduplicated explicitly;
- cursor values redacted or hashed in durable events; and
- no production staging change when a cursor contract fails.

### A4. Exit gate

- Cursor fixtures pass.
- Old stateless pagination remains available only as a named research control, never as the production candidate.
- Production defaults remain unchanged.

## 5. Phase B: Bounded Pagination Bake-Off

Run a no-detail, no-product-write bake-off on categories `(118000, 112000, 127000)`.

### B1. Variants

1. `stateless-current`: current payload, no cursor, requested page size 50.
2. `ui-cursor`: page size 10, response-derived cursor and supplemental fields.
3. `ui-cursor-50`: cursor fields with requested page size 50, to determine whether size is ignored or changes ranking.
4. `ui-cursor-restart`: restart the browser between pages to test whether server cursor alone is sufficient.
5. `ui-cursor-same-browser`: one browser and one condition-local chain, the expected candidate.

Endpoint and `rcdType` remain fixed during this first bake-off. Do not combine endpoint discovery with cursor discovery.

### B2. Budget

- at most 10 logical pages per category per variant;
- one retry only for transient transport failure;
- zero detail requests;
- randomized variant order across categories;
- two independent repeats in one short window.

### B3. Metrics

- distinct IDs;
- raw and supplemental rows;
- duplicate rate within and across pages;
- new IDs per page;
- overlap with earlier pages;
- same-page replay Jaccard;
- cursor continuity violations;
- response `pageSize` and total drift;
- requests and seconds per distinct ID; and
- union contribution unique to each variant.

### B4. Exit gate

The candidate must:

- have zero cursor violations and unresolved gaps;
- reduce cross-page duplicate rate materially relative to `stateless-current`;
- produce a higher or equal distinct-ID union at no more than 2x request cost;
- achieve same-condition short-window Jaccard at least `0.95`; and
- preserve zero identity and conservation differences.

If no variant passes, stop and inspect alternate endpoint contracts before another full census.

## 6. Phase C: Endpoint and Partition Research

Only after a cursor candidate passes Phase B, compare:

- `/wapi/geek/recommend/search/list` with `rcdType` omitted and evidence-backed values;
- `/wapi/geek/recommend/list` using its own response schema and cursor contract;
- top-level category partitions;
- official leaf-category partitions;
- deterministic date/publish-time partitions if the API demonstrably supports them; and
- language or location partitions only when they add IDs not reachable from category enumeration.

The goal is not to maximize summed totals. It is to find a set of query partitions whose union is stable and whose overlap can be audited.

### C1. Partition acceptance

A partition is retained only when it contributes either:

- at least `0.5%` new active reference IDs; or
- a documented high-value cohort unavailable from cheaper conditions.

### C2. Saturation evidence

For every retained condition, report the marginal new-ID curve. The last 100 successful requests adding less than `0.5%` is an efficiency signal, not a replacement for valid cursor exhaustion.

## 7. Phase D: Repeat the Full-Site Census

Run the accepted cursor/endpoint policy across all 31 top-level categories.

### D1. Required runs

- three accepted full censuses;
- at least two time windows separated by six hours;
- three fixed-condition repeats in one short window;
- identical candidate hash across all six runs; and
- exact union/intersection and added/removed cohorts.

### D2. Acceptance gates

- every condition has valid cursor-confirmed exhaustion;
- fixed-cohort minimum Jaccard `>= 0.95`;
- unique-count CV `<= 0.05`;
- unresolved gaps `= 0`;
- identity conflicts `= 0`;
- conservation difference `= 0`;
- unclassified failures `= 0`;
- no unexplained `sessionId` rollover; and
- no page with a full row set but zero new IDs unless explicitly classified as a recommendation/supplement behavior and shown not to hide recall.

The stable reference denominator is IDs seen in at least two time-aligned census runs plus independently confirmed active holdout IDs. The full union remains a diagnostic.

## 8. Phase E: Build the Broad IT Reference Set

1. Accept official IT category `118000` and its official descendants.
2. Apply deterministic technical-title rules to the other categories.
3. Send ambiguous titles to controlled detail fetch, not directly to acceptance.
4. Freeze independent predicted-positive and predicted-negative validation samples before labels are read.
5. Use at least 200 rows per validation cohort, proportionally stratified by category, language, and evidence rule, with a maximum of 500 per validation cycle.

Acceptance:

- predicted-positive Wilson 95% lower bound `>= 0.90`;
- predicted-negative one-sided 95% false-negative upper bound `<= 0.02`; and
- no unresolved candidate silently counted as IT.

## 9. Phase F: Planner Ablation and Miss Analysis

Compare these planners against the same time-aligned reference windows:

1. category only;
2. keyword only;
3. category plus keyword;
4. category plus keyword plus hybrid;
5. measured best family set with low-yield conditions removed.

For every planner report:

- recall proxy;
- exact missed IDs;
- misses by official category, title pattern, language, age, and query family;
- sampled precision;
- duplicate rate;
- requests and seconds per new reference ID; and
- holdout-only discoveries.

Acceptance:

- recall proxy `>= 0.98`;
- precision gate from Phase E passes;
- unresolved listing gaps `= 0`; and
- a candidate doubling request cost must improve recall by at least two percentage points.

## 10. Phase G: Detail Context Bake-Off and Canaries

### G1. Context variants

On one frozen, distinct 20-ID cohort, compare:

1. `id + encryptJobId` only;
2. listing `sessionId + id + encryptJobId`;
3. full UI context: `sessionId + lid + curIndex + encryptExpectId/markId` when those fields are present;
4. fresh headless, storage-state, and reusable-browser transport modes.

Do not infer that full UI context is better. Retain only fields that improve success/stability or are required by the current contract.

### G2. Canary expansion

1. 20-ID transport comparison.
2. 100-ID stratified canary.
3. 500-ID stratified canary.
4. Full distinct broad-IT backlog only after the 500-ID gate passes.

### G3. Detail acceptance

For a frozen eligible cohort:

- availability-adjusted success `>= 0.99`, excluding only structured code `2520` from the adjusted denominator;
- terminal-unavailable rate reported against the original denominator;
- title, company, and cleaned description completeness `>= 0.98` each among successes;
- response/request identity mismatch published rows `= 0`;
- repeated requests for one canonical ID within a run `= 0`;
- terminal automatic retry rate `= 0`;
- unattempted rows changed to failed `= 0`;
- orphan `running` rows after recovery `= 0`; and
- Job/listing transaction splits `= 0`.

## 11. Phase H: Recovery and Production Soak

Inject and verify:

- process stop after marking detail `running`;
- persistence failure between Company, Job, and listing transitions;
- timeout, non-JSON, 429/5xx, auth expiry, WAF, IP block, and ID mismatch;
- browser loss during a listing cursor chain; and
- resume from the last durable condition boundary.

Do not checkpoint and resume a cursor mid-condition unless the server contract is proven durable across process/browser restart. The conservative recovery rule is to restart the affected condition from page 1 and deduplicate by canonical ID.

Run the final candidate three times with production pacing and drain each distinct detail backlog.

Production adoption requires every discovery, precision, detail, stability, conservation, recovery, and efficiency gate to pass on all three soak runs.

## 12. Required Implementation Areas

Likely files, subject to code review before edits:

- `backend/app/sources/offertoday/constants.py`
- `backend/app/sources/offertoday/listing_runner.py`
- `backend/app/sources/offertoday/research/live_contracts.py`
- `backend/app/services/offertoday_research_live_service.py`
- `backend/app/scraper/offertoday_browser_runtime.py`
- `backend/app/services/offertoday_detail_pipeline.py`
- `backend/scripts/offertoday_research_census.py`
- `backend/scripts/offertoday_standalone_crawl.py`
- focused OfferToday research, runner, runtime, detail, and crawl-runtime tests

Prefer a transport result object carrying response metadata over mutating request dictionaries or adding hidden state to `OfferTodayBrowserRuntime`.

## 13. Verification Commands

Focused deterministic verification:

```powershell
python -m pytest -q `
  backend/tests/test_offertoday_listing_runner.py `
  backend/tests/test_offertoday_browser_runtime.py `
  backend/tests/test_offertoday_research_live_service.py `
  backend/tests/test_offertoday_research_census_cli.py `
  backend/tests/test_offertoday_research_stability.py `
  backend/tests/test_offertoday_detail_pipeline.py `
  backend/tests/test_offertoday_canonical_and_identity.py `
  backend/tests/test_crawl_job_runtime.py `
  backend/tests/test_offertoday_standalone_crawl.py
```

Full verification:

```powershell
python -m pytest -q backend/tests
git diff --check
```

Every live artifact must pass both generic hash verification and experiment-specific strict replay before its metrics are used.

## 14. Decision Rule

The current Plan 2 candidate is rejected for production completeness claims because its fixed-cohort Jaccard is `0.868300`, and live UI evidence confirms that it omits the listing cursor contract.

The next implementation priority is cursor-correct listing pagination and its bounded bake-off. Keyword expansion, higher page caps, more concurrency, and full detail backlog processing must wait. Increasing those now would spend more requests on an invalid pagination protocol and could increase counts without improving recall.
