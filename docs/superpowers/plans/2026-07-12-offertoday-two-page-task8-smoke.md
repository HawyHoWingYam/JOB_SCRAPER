# OfferToday Two-Page Task 8 Smoke Amendment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Amend only Plan 2 Task 8 so the bounded compatibility smoke can make at most two ordered listing requests, freeze exactly 20 first-seen canonical identities across those pages, and retain the existing 20-detail, no-retry, same-browser, strict-artifact, and zero-product-write controls.

**Architecture:** Keep the shared `OfferTodayListingRunner` as the only paginator. Put the two-listing/20-detail budget in pure smoke constants, make the live service use `max_pages_per_condition=2` plus `unique_job_cap=20`, and extend strict offline replay to validate ordered pages, accumulated identity authority, and budget agreement across metadata, run-start, summary, manifest, and CLI output. Preserve both prior failed smoke artifacts through a fail-only legacy-budget compatibility branch; do not add another live loop or authorize a network request.

**Tech Stack:** Python 3.11+, asyncio, dataclasses, canonical JSON/SHA-256 artifacts, pytest/pytest-asyncio, Ruff, Git.

---

## Execution Boundary

- This plan authorizes documentation, deterministic tests, Python code, compilation, Ruff, Git commits, and offline artifact verification only.
- Do not capture new baselines, open Playwright, construct a live browser runtime from a command, or contact OfferToday while implementing this plan.
- Do not run Plan 2 Tasks 9-15.
- Do not change category `118000`, endpoint `search`, `rcdType=7`, page size 50, fresh-headless mode, detail concurrency 1, the three-second detail delay, response classification, or any retry policy.
- Keep detail attempts capped at 20 with zero retries and no replacement targets.
- Keep the no-op listing staging sink and all run-start/run-end product-data hash checks.
- Preserve these ignored runtime artifacts byte-for-byte:
  - `backend/runtime/offertoday-research/fab9d8e1-4c12-4170-a539-c0a6cdbbca93`, manifest SHA-256 `1928423eed6cfd95e4cd2a3af3eb1d62c2ea6d460b122acb0ca0fefcfb4b548b`;
  - `backend/runtime/offertoday-research/63b9d32a-5d47-44c9-8904-25a68ee2dee8`, manifest SHA-256 `a009be467c30b538e31be501cc3bbb38a528b56c2fe7268507df572dda7336d3`.
- Preserve unrelated dirty hunks, especially `backend/app/scraper/offertoday_browser_runtime.py`, `backend/scripts/offertoday_standalone_crawl.py`, and `backend/tests/test_offertoday_browser_runtime.py`.
- A new two-page replacement smoke remains separately authorization-gated after this plan passes every offline review.

## Triggering Evidence

The identity-corrected replacement run `63b9d32a-5d47-44c9-8904-25a68ee2dee8` proved that the canonical request contained `pageSize=50`, but OfferToday returned 10 valid `jobId_fallback` rows with `hasMore=true`. The command safely froze 10 targets, made zero detail requests, returned exit 3 with `insufficient_valid_detail_targets`, verified its artifact, and left product-data hashes unchanged.

The minimum correction is therefore one optional page-2 request through the existing runner. Page 2 is allowed only after a clean successful page 1 with fewer than 20 accepted canonical IDs and no exhaustion signal.

## Fixed Contract

```text
Listing logical request budget = 2
Listing page order             = page 1, then optional page 2
Listing attempts per page      = 1
Listing retry                  = 0
Listing page delay             = 0
Distinct canonical ID cap      = 20
Detail target count            = 20
Detail logical request budget  = 20
Detail concurrency             = 1
Detail retry                   = 0
Detail inter-request delay     = 3.0 seconds
Session mode                   = fresh-headless
Product-data writes            = 0
```

An accepted listing phase ends with `target_cap`, `is_complete=false`, exactly 20 accepted canonical IDs, and one or two clean successful page attempts. A clean two-page `page_cap` with fewer than 20 targets is expected bounded evidence but fails the smoke with `insufficient_valid_detail_targets` and makes zero detail requests.

## File Map

### Runtime contract and orchestration

- Modify `backend/app/sources/offertoday/research/smoke.py`: shared budgets, bounded listing-result predicate, readiness, and decision semantics.
- Modify `backend/app/services/offertoday_research_live_service.py`: runner stop policy only; keep the detail loop unchanged.
- Modify `backend/tests/test_offertoday_listing_runner.py`: characterize the existing shared runner with two 10-row pages, cross-page duplicates, page-1 cap, and page-2 hard stop.
- Modify `backend/tests/test_offertoday_research_smoke.py`: pure one/two-page readiness and decision tests.
- Modify `backend/tests/test_offertoday_research_live_service.py`: exact service policy and no-detail-on-short-cohort tests.

### Strict replay and CLI budget propagation

- Modify `backend/app/sources/offertoday/research/stage_gate.py`: current/legacy budget modes, ordered page controls, accumulated cross-page authority, run-start/summary consistency, and completed-smoke validation.
- Modify `backend/scripts/offertoday_research_census.py`: use the shared budget in metadata, run-start, summary, manifest, and CLI output.
- Modify `backend/tests/test_offertoday_research_stage_gate.py`: two-page strict replay, tamper rejection, budget agreement, and legacy artifact coverage.
- Modify `backend/tests/test_offertoday_research_census_cli.py`: current budget propagation, exit semantics, and network-free `verify-run` coverage.

### Normative documentation

- Modify `docs/superpowers/specs/2026-07-12-offertoday-two-page-task8-smoke-design.md`.
- Modify `docs/superpowers/specs/2026-07-11-offertoday-plan2-live-census-calibration-design.md`.
- Modify `docs/superpowers/plans/2026-07-11-offertoday-plan2-live-census-calibration.md`.
- Modify `docs/superpowers/specs/2026-07-11-offertoday-jobid-only-identity-compatibility-design.md`.
- Modify `docs/superpowers/plans/2026-07-11-offertoday-jobid-only-identity-compatibility.md`.

---

### Task 1: Lock the Two-Page Runtime Contract in Pure Smoke Logic

**Files:**
- Modify: `backend/app/sources/offertoday/research/smoke.py`
- Modify: `backend/app/services/offertoday_research_live_service.py`
- Test: `backend/tests/test_offertoday_listing_runner.py`
- Test: `backend/tests/test_offertoday_research_smoke.py`
- Test: `backend/tests/test_offertoday_research_live_service.py`

- [ ] **Step 1: Add a passing shared-runner characterization before changing smoke code**

Add a runner test that proves the existing paginator already owns the required behavior. Build page 1 with `j01` through `j10`, page 2 with `j11` through `j20`, and an unused page-3 scripted response. Run with `max_pages=2`, `max_attempts=1`, `unique_job_cap=20`, and `require_empty_confirmation=False`.

```python
@pytest.mark.asyncio
async def test_two_page_target_cap_collects_twenty_and_never_requests_page_three():
    page_1 = [_listing_row(f"j{index:02d}", None) for index in range(1, 11)]
    page_2 = [_listing_row(f"j{index:02d}", None) for index in range(11, 21)]
    for row in (*page_1, *page_2):
        row.pop("encryptJobId")
    transport = ScriptedTransport(
        _listing_response(page_1, has_more=True, total=260),
        _listing_response(page_2, has_more=True, total=260),
        _listing_response([_listing_row("j21", None)], has_more=False, total=260),
    )

    result, observations, _staging, _sleep = await _run(
        transport,
        max_pages=2,
        max_attempts=1,
        unique_job_cap=20,
        require_empty_confirmation=False,
    )

    assert [request[0]["page"] for request in transport.requests] == [1, 2]
    assert result.accepted_job_ids == tuple(f"j{index:02d}" for index in range(1, 21))
    assert [pair.encrypted_job_id_source for pair in result.id_pairs] == [
        "jobId_fallback"
    ] * 20
    assert [item.stop_reason for item in observations.observations] == [None, "target_cap"]
    assert result.stop_reason == "target_cap"
    assert result.is_complete is False
```

Run:

```powershell
python -m pytest -q backend/tests/test_offertoday_listing_runner.py -k "two_page_target_cap"
```

Expected: PASS before production edits. This is a characterization of the shared runner, not a new paginator implementation.

- [ ] **Step 2: Write failing pure smoke contract tests**

In `test_offertoday_research_smoke.py`, extend `listing_result()` so callers can pass a one- or two-page observation tuple and `target_cap`. Add a helper that splits the final authoritative pairs across two observations while keeping page order explicit.

```python
def two_page_listing_result(*, count: int = 20) -> ListingRunResult:
    pairs = tuple(pair(f"j{index}", f"e{index}") for index in range(1, count + 1))
    first = pairs[:10]
    second = pairs[10:]
    return listing_result(
        id_pairs=pairs,
        accepted_job_ids=tuple(item.job_id for item in pairs),
        observations=(
            page_observation(page=1, id_pairs=first, row_count=len(first), stop_reason=None),
            page_observation(
                page=2,
                request_fingerprint="b" * 64,
                id_pairs=second,
                row_count=len(second),
                stop_reason=("target_cap" if count >= 20 else "page_cap"),
            ),
        ),
        stop_reason=("target_cap" if count >= 20 else "page_cap"),
    )
```

Add these assertions:

```python
def test_listing_ready_accepts_clean_one_or_two_page_target_cap():
    one_page = replace(
        listing_result(),
        stop_reason="target_cap",
        observations=(page_observation(stop_reason="target_cap"),),
    )
    two_page = two_page_listing_result()

    assert listing_ready_for_detail_smoke(
        one_page, freeze_detail_smoke_cohort(one_page, limit=20)
    ) is True
    assert listing_ready_for_detail_smoke(
        two_page, freeze_detail_smoke_cohort(two_page, limit=20)
    ) is True


@pytest.mark.parametrize(
    "observations",
    (
        (page_observation(page=2, stop_reason="target_cap"),),
        (
            page_observation(page=1),
            page_observation(page=1, request_fingerprint="b" * 64, stop_reason="target_cap"),
        ),
        (
            page_observation(page=1),
            page_observation(page=2, attempt=2, request_fingerprint="b" * 64, stop_reason="target_cap"),
        ),
    ),
)
def test_listing_ready_rejects_out_of_order_duplicate_or_retried_pages(observations):
    result = replace(listing_result(), observations=observations, stop_reason="target_cap")
    assert listing_ready_for_detail_smoke(
        result, freeze_detail_smoke_cohort(result, limit=20)
    ) is False


def test_two_page_short_cohort_fails_without_relabeling_listing_as_hard_failure():
    result = two_page_listing_result(count=19)
    targets = freeze_detail_smoke_cohort(result, limit=20)

    decision = evaluate_smoke(
        listing_result=result,
        frozen_targets=targets,
        observations=(),
    )

    assert decision.smoke_passed is False
    assert decision.stop_reason == "insufficient_valid_detail_targets"
    assert decision.expected_truncation is True
    assert decision.attempted_count == 0
```

Run:

```powershell
python -m pytest -q backend/tests/test_offertoday_research_smoke.py -k "listing_ready or two_page_short"
```

Expected: FAIL because readiness requires one page with `page_cap`, and a short page-2 result is currently evaluated as `listing_page_cap`.

- [ ] **Step 3: Write failing live-service policy tests**

Update `test_run_smoke_uses_exact_listing_budget_and_no_session_preflight()` to expect:

```python
assert call["stop_policy"] == ListingStopPolicy(
    max_pages_per_condition=2,
    unique_job_cap=20,
    require_empty_confirmation=False,
)
```

Add one service test with `two_page_listing_result(count=19)` and assert the detail scraper is never constructed, no detail attempt is recorded, and the decision reason is `insufficient_valid_detail_targets`.

Run:

```powershell
python -m pytest -q backend/tests/test_offertoday_research_live_service.py -k "exact_listing_budget or short_cohort"
```

Expected: FAIL because the service still passes a one-page/no-cap stop policy.

- [ ] **Step 4: Add shared immutable smoke-budget primitives**

In `smoke.py`, define exact integer constants and a fresh-dict helper:

```python
SMOKE_LISTING_REQUEST_LIMIT = 2
SMOKE_DETAIL_TARGET_COUNT = 20


def runtime_smoke_request_budget() -> dict[str, int]:
    return {
        "listing": SMOKE_LISTING_REQUEST_LIMIT,
        "detail": SMOKE_DETAIL_TARGET_COUNT,
    }
```

Keep callers from mutating shared state by returning a new dictionary each time. Add a test that mutates one returned value and proves a second call still returns `{"listing": 2, "detail": 20}`.

- [ ] **Step 5: Implement bounded one/two-page listing semantics**

Replace the one-page helper with two pure predicates. The first validates the ordered clean bounded result; the second additionally requires the 20-ID target stop.

```python
def _is_clean_bounded_listing_end(listing_result: ListingRunResult) -> bool:
    attempts = listing_result.observations
    if not 1 <= len(attempts) <= SMOKE_LISTING_REQUEST_LIMIT:
        return False
    if tuple(item.page for item in attempts) != tuple(range(1, len(attempts) + 1)):
        return False
    if any(
        item.attempt != 1
        or item.classification != "success"
        or item.search_family != "runtime_smoke"
        or item.category_id != 118000
        or item.keyword != ""
        or item.endpoint != "search"
        or item.rcd_type != 7
        or item.session_mode != "fresh-headless"
        for item in attempts
    ):
        return False
    if any(item.stop_reason is not None for item in attempts[:-1]):
        return False
    if attempts[-1].stop_reason != listing_result.stop_reason:
        return False
    return (
        listing_result.stop_reason in {"target_cap", "page_cap"}
        and listing_result.is_complete is False
        and not listing_result.gaps
        and not listing_result.identity_issues
        and not listing_result.identity_conflicts
    )


def _is_expected_listing_truncation(listing_result: ListingRunResult) -> bool:
    return (
        _is_clean_bounded_listing_end(listing_result)
        and listing_result.stop_reason == "target_cap"
    )
```

In `evaluate_smoke()`, calculate `clean_bounded_end` first. Return `listing_<reason>` when it is false. Check the exact frozen count second so a clean two-page `page_cap` becomes `insufficient_valid_detail_targets`. Then require `_is_expected_listing_truncation()` before detail-order and outcome evaluation. Keep every existing detail classification branch unchanged.

- [ ] **Step 6: Change only the service's listing stop policy**

Import `SMOKE_DETAIL_TARGET_COUNT` and `SMOKE_LISTING_REQUEST_LIMIT` into the live service. Use:

```python
stop_policy=ListingStopPolicy(
    max_pages_per_condition=SMOKE_LISTING_REQUEST_LIMIT,
    unique_job_cap=SMOKE_DETAIL_TARGET_COUNT,
    require_empty_confirmation=False,
)
```

Replace the literal cohort limit with `SMOKE_DETAIL_TARGET_COUNT`. Do not change the retry policy, detail loop, same-runtime fetcher, sleep placement, or no-op sink.

- [ ] **Step 7: Run the Task 1 focused suite and verify GREEN**

```powershell
python -m pytest -q `
  backend/tests/test_offertoday_listing_runner.py `
  backend/tests/test_offertoday_research_smoke.py `
  backend/tests/test_offertoday_research_live_service.py
```

Expected: all pass. The shared runner requests pages `[1, 2]` only, one-page 20-ID results do not request page 2, two-page short results make zero details, and successful detail execution remains 20 attempts with 19 delays.

- [ ] **Step 8: Commit Task 1**

```powershell
git add backend/app/sources/offertoday/research/smoke.py backend/app/services/offertoday_research_live_service.py backend/tests/test_offertoday_listing_runner.py
git add -f backend/tests/test_offertoday_research_smoke.py backend/tests/test_offertoday_research_live_service.py
git diff --cached --check
git commit -m "fix(offertoday): bound task 8 smoke to two listing pages"
```

---

### Task 2: Make CLI Evidence and Strict Replay Two-Page Aware

**Files:**
- Modify: `backend/app/sources/offertoday/research/stage_gate.py`
- Modify: `backend/scripts/offertoday_research_census.py`
- Test: `backend/tests/test_offertoday_research_stage_gate.py`
- Test: `backend/tests/test_offertoday_research_census_cli.py`

- [ ] **Step 1: Extend artifact builders and write failing current-budget tests**

Change the current test artifact default to `{"listing": 2, "detail": 20}`. Keep an explicit `LEGACY_SMOKE_BUDGET = {"listing": 1, "detail": 20}` for old failed fixtures only. Extend `_live_events()` to accept `listing_pages: tuple[int, ...]`, split targets/rows by page, and emit each page before `research.detail_cohort_frozen`.

Add a current completed two-page test and retain a current completed one-page
`target_cap` test:

```python
@pytest.mark.parametrize("listing_pages", ((1,), (1, 2)))
def test_verify_live_run_accepts_current_completed_smoke_page_shapes(
    tmp_path,
    listing_pages,
):
    events = _live_events(listing_pages=listing_pages)
    artifact = _export_live(
        tmp_path,
        events=events,
        request_budget={"listing": 2, "detail": 20},
    )

    result = verify_live_research_run(artifact)

    assert result.valid is True
    assert result.issues == ()
```

Add one parameterized sequence/attempt rejection test:

```python
@pytest.mark.parametrize(
    ("listing_pages", "attempt", "expected_issue"),
    (
        ((1, 2, 3), 1, "listing_request_budget_exceeded:3>2"),
        ((2,), 1, "invalid_runtime_smoke_page_sequence"),
        ((1, 1), 1, "invalid_runtime_smoke_page_sequence"),
        ((1, 2), 2, "invalid_runtime_smoke_listing_attempt"),
    ),
)
def test_verify_live_run_rejects_invalid_page_sequence_or_retry(
    tmp_path,
    listing_pages,
    attempt,
    expected_issue,
):
    events = _live_events(listing_pages=listing_pages)
    if attempt != 1:
        page_events = [
            event for event in events if event["event_type"] == "research.page_attempt"
        ]
        page_events[-1]["payload"]["attempt"] = attempt
    artifact = _export_live(
        tmp_path,
        events=events,
        request_budget={"listing": 2, "detail": 20},
    )

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert expected_issue in result.issues
```

Add two separate page-2 entry tests. In one, set page 1 `stop_reason` to
`target_cap`; in the other, set page 1 `has_more` to `False`. Re-export each
artifact and require `invalid_runtime_smoke_page_two_entry`.

For every tamper case, re-export the artifact so the manifest hash is internally valid; the expected failure must come from strict semantic replay.

Run:

```powershell
python -m pytest -q backend/tests/test_offertoday_research_stage_gate.py -k "two_page or page_three or out_of_order or retry_attempt or after_page_one"
```

Expected: FAIL because the verifier requires budget 1 and page 1 only.

- [ ] **Step 2: Write failing accumulated-authority replay tests**

Add a two-page artifact with 10 identities on each page. Assert the frozen cohort is the first 20 canonical IDs in cross-page order. Then add these independent variants:

1. page 2 repeats five page-1 canonical IDs and adds only five new IDs; the frozen cohort contains 15 IDs and the failed summary reason is `insufficient_valid_detail_targets`;
2. page 1 records fallback for `j1`, page 2 observes explicit `enc-j1`, and the final frozen target uses the promoted explicit triple at `j1`'s original position;
3. page 1 records explicit `enc-j1`, page 2 observes fallback for `j1`, and page-2 `id_pairs` plus the frozen cohort retain the explicit triple;
4. tampering only the promoted route, source, order, or frozen position yields `page_identity_authority_mismatch` or `detail_cohort_identity_mismatch`.

Run:

```powershell
python -m pytest -q backend/tests/test_offertoday_research_stage_gate.py -k "cross_page or promoted or no_downgrade or cohort_identity"
```

Expected: FAIL because current replay validates each page in isolation and deduplicates exact triples rather than canonical IDs with accumulated authority.

- [ ] **Step 3: Write failing budget-agreement and legacy-compatibility tests**

Require the current budget in all five evidence surfaces:

```text
manifest.metadata.request_budget
research.run_started.payload.request_budget
research.run_summary.payload.request_budget
CLI terminal JSON request_budget
observed page/detail counts
```

Add independent tamper tests for manifest, run-start, and summary budget disagreement. Add a test that a completed artifact with the legacy one-listing budget is rejected. Add direct offline tests for both immutable failed artifact paths and assert `valid is True`.

Run:

```powershell
python -m pytest -q backend/tests/test_offertoday_research_stage_gate.py backend/tests/test_offertoday_research_census_cli.py -k "request_budget or immutable_failed or legacy_budget"
```

Expected: FAIL because the current constant is still one listing, summary/CLI output omit the budget, and no fail-only legacy mode exists.

- [ ] **Step 4: Use shared current and explicit fail-only legacy budgets**

Import `SMOKE_LISTING_REQUEST_LIMIT` and `runtime_smoke_request_budget` into `stage_gate.py`. Replace the one-page control with common immutable fields:

```python
_LEGACY_RUNTIME_SMOKE_REQUEST_BUDGET = {"listing": 1, "detail": 20}
_RUNTIME_SMOKE_PAGE_CONTROL = {
    "search_family": "runtime_smoke",
    "category_id": 118000,
    "keyword": "",
    "endpoint": "search",
    "rcd_type": 7,
    "session_mode": "fresh-headless",
}
```

In `verify_live_research_run()`, derive:

```python
current_budget = runtime_smoke_request_budget()
legacy_failed_budget = (
    request_budget == _LEGACY_RUNTIME_SMOKE_REQUEST_BUDGET
    and metadata.get("crawl_job_status") == "failed"
    and metadata.get("smoke_passed") is False
)
if request_budget != current_budget and not legacy_failed_budget:
    issues.append("invalid_runtime_smoke_request_budget")
listing_budget = int(request_budget.get("listing", 0)) if isinstance(request_budget, dict) else 0
detail_budget = int(request_budget.get("detail", 0)) if isinstance(request_budget, dict) else 0
```

Never allow `legacy_failed_budget` to satisfy a completed smoke. Require one or two page attempts for the current budget and at most one page attempt for the legacy budget.

- [ ] **Step 5: Validate ordered page controls and legal page-2 entry**

In `_analyze_runtime_smoke_events()`, validate page sequence separately from common controls:

```python
page_payloads = [
    event.get("payload") if isinstance(event.get("payload"), dict) else {}
    for event in page_events
]
observed_pages = [payload.get("page") for payload in page_payloads]
if observed_pages != list(range(1, len(page_payloads) + 1)):
    issues.append("invalid_runtime_smoke_page_sequence")
if any(payload.get("attempt") != 1 for payload in page_payloads):
    issues.append("invalid_runtime_smoke_listing_attempt")
```

Reject more than `SMOKE_LISTING_REQUEST_LIMIT` page events. When page 2 exists, require page 1 classification `success`, stop reason `None`, `has_more is not False`, no page identity issues/conflicts, and fewer than 20 accumulated authoritative canonical IDs after page 1. Keep `target_cap` and `page_cap` out of `first_listing_failure`; all auth/WAF/IP/identity/gap reasons remain failures.

- [ ] **Step 6: Replay page authority cumulatively**

Change `_canonical_page_authority()` to receive prior committed row identities and return the current page's canonical rows as well as its authoritative pairs. Keep its existing pair/row parsing, count validation, and issue collection. Replace the authority block and return statement with:

```python
def _canonical_page_authority(
    payload: dict[str, Any],
    issues: list[str],
    *,
    prior_identities: tuple[OfferTodayDetailIdentity, ...] = (),
) -> tuple[
    list[OfferTodayDetailIdentity],
    list[OfferTodayDetailIdentity],
    int,
    int,
]:
    authority_index = build_offertoday_identity_authority_index(
        (*prior_identities, *canonical_rows)
    )
    page_first_seen_job_ids: list[str] = []
    page_seen_job_ids: set[str] = set()
    for identity in canonical_rows:
        if identity.job_id not in page_seen_job_ids:
            page_seen_job_ids.add(identity.job_id)
            page_first_seen_job_ids.append(identity.job_id)
    authoritative_rows = [
        authority_index.authoritative_identity_by_job[job_id]
        for job_id in page_first_seen_job_ids
        if job_id in authority_index.authoritative_identity_by_job
        and job_id not in authority_index.conflict_reason_by_job
    ]
    canonical_pair_triples = [
        (
            identity.job_id,
            identity.encrypted_job_id,
            identity.encrypted_job_id_source,
        )
        for identity in canonical_pairs
    ]
    authoritative_row_triples = [
        (
            identity.job_id,
            identity.encrypted_job_id,
            identity.encrypted_job_id_source,
        )
        for identity in authoritative_rows
    ]
    if (
        not identity_evidence_valid
        or canonical_pair_triples != authoritative_row_triples
        or (
            payload.get("classification") == "success"
            and bool(authority_index.conflict_reason_by_job)
        )
    ):
        issues.append("page_identity_authority_mismatch")
    return authoritative_rows, canonical_rows, raw_missing_count, fallback_count
```

The page's declared `id_pairs` must equal the accumulated authority for canonical jobs observed on that page. In `_analyze_runtime_smoke_events()`, commit `canonical_rows` only for a clean successful page. Preserve first-seen canonical-job order across committed pages, build one final authority index, and derive `expected_frozen_targets` from the first 20 authoritative canonical IDs. This must promote fallback to one explicit route without moving the canonical job and must prevent a later fallback downgrade.

- [ ] **Step 7: Tighten current completed-smoke validation**

For a current completed smoke require:

```text
manifest status completed
manifest and summary smoke_passed true
current request budget 2/20
one or two ordered listing pages
every listing attempt number 1 and classification success
final listing stop reason target_cap
listing_complete false and expected_truncation true
exactly 20 frozen and 20 attempted details
zero unclassified/detail failures
summary stop_reason null
matching no-write hashes
```

Use the analyzer's ordered page payloads rather than assuming `page_events[0]` is the only page. A clean two-page `page_cap` with fewer than 20 is a valid failed artifact only when its summary reason is `insufficient_valid_detail_targets` and it contains zero detail attempts.

- [ ] **Step 8: Propagate the shared budget through the CLI**

Import `runtime_smoke_request_budget` after backend bootstrap. In `main()`, create one local value before `create_run()`:

```python
request_budget = runtime_smoke_request_budget()
```

Use a fresh copy in `ResearchMetadata`, `research.run_started`, terminal summary, artifact metadata, and printed CLI JSON. Extend `_build_summary()` with a required `request_budget: dict[str, int]` keyword and serialize `"request_budget": dict(request_budget)`.

The terminal JSON becomes:

```python
{
    "artifact": str(artifact_dir),
    "run_id": run_id,
    "exit_code": exit_code,
    "smoke_passed": bool(summary.get("smoke_passed")),
    "request_budget": dict(request_budget),
    "missing_encrypted_job_id_count": int(
        summary.get("missing_encrypted_job_id_count", 0)
    ),
    "job_id_fallback_count": int(summary.get("job_id_fallback_count", 0)),
}
```

Thread the same budget through best-effort finalization so partial artifacts cannot silently revert to a different budget.

- [ ] **Step 9: Run the Task 2 focused suite and verify GREEN**

```powershell
python -m pytest -q `
  backend/tests/test_offertoday_research_stage_gate.py `
  backend/tests/test_offertoday_research_census_cli.py `
  backend/tests/test_offertoday_research_smoke.py `
  backend/tests/test_offertoday_research_live_service.py
```

Expected: all pass. Current completed artifacts require 2/20 metadata even when only one listing request is consumed, legacy 1/20 is accepted only for failed artifacts, page 3/retries/order tampering fail, and `verify-run` constructs no browser or database dependency.

- [ ] **Step 10: Verify both immutable artifacts before committing**

```powershell
$artifacts = @(
  @{ Path = 'backend/runtime/offertoday-research/fab9d8e1-4c12-4170-a539-c0a6cdbbca93'; Hash = '1928423eed6cfd95e4cd2a3af3eb1d62c2ea6d460b122acb0ca0fefcfb4b548b' },
  @{ Path = 'backend/runtime/offertoday-research/63b9d32a-5d47-44c9-8904-25a68ee2dee8'; Hash = 'a009be467c30b538e31be501cc3bbb38a528b56c2fe7268507df572dda7336d3' }
)
foreach ($item in $artifacts) {
  $before = (Get-FileHash (Join-Path $item.Path 'manifest.json') -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($before -ne $item.Hash) { throw "immutable artifact hash mismatch before replay" }
  python backend/scripts/offertoday_research_census.py verify-run --artifact $item.Path
  if ($LASTEXITCODE -ne 0) { throw "immutable artifact failed strict replay" }
  $after = (Get-FileHash (Join-Path $item.Path 'manifest.json') -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($after -ne $item.Hash) { throw "immutable artifact changed during replay" }
}
```

Expected: both print `"valid": true`; hashes match before and after.

- [ ] **Step 11: Commit Task 2**

```powershell
git add backend/app/sources/offertoday/research/stage_gate.py backend/scripts/offertoday_research_census.py
git add -f backend/tests/test_offertoday_research_stage_gate.py backend/tests/test_offertoday_research_census_cli.py
git diff --cached --check
git commit -m "fix(offertoday): verify two-page smoke evidence"
```

---

### Task 3: Amend Every Normative Task 8 Reference

**Files:**
- Modify: `docs/superpowers/specs/2026-07-12-offertoday-two-page-task8-smoke-design.md`
- Modify: `docs/superpowers/specs/2026-07-11-offertoday-plan2-live-census-calibration-design.md`
- Modify: `docs/superpowers/plans/2026-07-11-offertoday-plan2-live-census-calibration.md`
- Modify: `docs/superpowers/specs/2026-07-11-offertoday-jobid-only-identity-compatibility-design.md`
- Modify: `docs/superpowers/plans/2026-07-11-offertoday-jobid-only-identity-compatibility.md`

- [ ] **Step 1: Mark the amendment design implementation-ready**

Set:

```markdown
> Status: Approved for implementation
> Scope: Corrective amendment to Plan 2 Task 8 only
> Implementation plan: `docs/superpowers/plans/2026-07-12-offertoday-two-page-task8-smoke.md`
```

Do not change the recorded facts, run IDs, request fingerprint, output counts, or immutable hashes for either failed smoke.

- [ ] **Step 2: Update current Plan 2 Task 8 contracts**

In the live census design and implementation plan, make these exact semantic replacements only in current/future normative text:

1. one listing request becomes at most two ordered listing requests;
2. page-1-only collection becomes page 1 followed by optional page 2;
3. the listing stop policy becomes max pages 2 plus unique canonical ID cap 20;
4. the request budget becomes listing 2/detail 20 in metadata, tests, CLI snippets, Task 8 count checks, and the verification matrix;
5. acceptance requires 20 first-seen distinct canonical IDs across the bounded result and `target_cap`;
6. fewer than 20 after page 2 remains exit 3 with zero details;
7. page 3, retries, or page attempts after cohort freeze are evidence failures;
8. both failed artifacts remain immutable evidence and neither satisfies Task 8;
9. another live run remains separately authorization-gated; and
10. Task 9 remains locked.

Retain historically dated statements that the first and second failed runs each made one listing request. Label them as historical evidence rather than silently rewriting them.

- [ ] **Step 3: Update compatibility-plan handoff wording**

In the compatibility design and plan, replace only the obsolete future proposal of `one listing request` with `at most two ordered listing requests`. Record run `63b9d32a-5d47-44c9-8904-25a68ee2dee8` as the identity-corrected but target-count-incomplete evidence that triggered this amendment. Keep all identity implementation requirements and completed commit descriptions unchanged.

- [ ] **Step 4: Run documentation consistency checks**

```powershell
rg -n "request_budget.*listing.*1|one listing request|exactly one listing|page-1-only|page 1 only" `
  docs/superpowers/specs/2026-07-12-offertoday-two-page-task8-smoke-design.md `
  docs/superpowers/specs/2026-07-11-offertoday-plan2-live-census-calibration-design.md `
  docs/superpowers/plans/2026-07-11-offertoday-plan2-live-census-calibration.md `
  docs/superpowers/specs/2026-07-11-offertoday-jobid-only-identity-compatibility-design.md `
  docs/superpowers/plans/2026-07-11-offertoday-jobid-only-identity-compatibility.md
```

Expected: any remaining match is explicitly attached to one of the two historical failed runs or explains the superseded contract. There must be no current/future one-page instruction.

Also run:

```powershell
rg -n "listing.?2|at most two|optional page 2|target_cap|63b9d32a-5d47-44c9-8904-25a68ee2dee8|Task 9 remains locked" `
  docs/superpowers/specs/2026-07-12-offertoday-two-page-task8-smoke-design.md `
  docs/superpowers/specs/2026-07-11-offertoday-plan2-live-census-calibration-design.md `
  docs/superpowers/plans/2026-07-11-offertoday-plan2-live-census-calibration.md
```

Expected: current budget, page order, second failed artifact, target stop, and Task 9 lock are all present.

- [ ] **Step 5: Commit Task 3**

```powershell
git add -f `
  docs/superpowers/specs/2026-07-12-offertoday-two-page-task8-smoke-design.md `
  docs/superpowers/plans/2026-07-12-offertoday-two-page-task8-smoke.md `
  docs/superpowers/specs/2026-07-11-offertoday-plan2-live-census-calibration-design.md `
  docs/superpowers/plans/2026-07-11-offertoday-plan2-live-census-calibration.md `
  docs/superpowers/specs/2026-07-11-offertoday-jobid-only-identity-compatibility-design.md `
  docs/superpowers/plans/2026-07-11-offertoday-jobid-only-identity-compatibility.md
git diff --cached --check
git commit -m "docs(offertoday): amend task 8 for two listing pages"
```

---

### Task 4: Close the Offline Review Gate and Stop Before Live Execution

**Files:**
- Verification only. Modify source/tests only for a reproduced defect and follow a new RED-GREEN cycle.

- [ ] **Step 1: Run the complete smoke-focused selector**

```powershell
python -m pytest -q `
  backend/tests/test_offertoday_research_stage_gate.py `
  backend/tests/test_offertoday_research_smoke.py `
  backend/tests/test_offertoday_research_live_service.py `
  backend/tests/test_offertoday_research_census_cli.py `
  backend/tests/test_offertoday_research_observation_service.py `
  backend/tests/test_offertoday_research_staging_service.py `
  backend/tests/test_offertoday_research_artifacts.py `
  backend/tests/test_offertoday_research_cli.py `
  backend/tests/test_offertoday_listing_runner.py `
  backend/tests/test_offertoday_browser_runtime.py `
  backend/tests/test_offertoday_canonical_and_identity.py
```

Expected: all pass with no xfail for two-page ordering, request budgets, accumulated identity authority, no-write behavior, partial artifacts, or exception propagation.

- [ ] **Step 2: Run the complete Plan 1 regression selector**

```powershell
python -m pytest -q `
  backend/tests/test_offertoday_response_policy.py `
  backend/tests/test_offertoday_search_space.py `
  backend/tests/test_offertoday_listing_runner.py `
  backend/tests/test_offertoday_research_observation_service.py `
  backend/tests/test_offertoday_research_artifacts.py `
  backend/tests/test_offertoday_research_baseline.py `
  backend/tests/test_offertoday_research_conservation.py `
  backend/tests/test_offertoday_research_cli.py `
  backend/tests/test_offertoday_detail_pipeline.py `
  backend/tests/test_offertoday_standalone_crawl.py `
  backend/tests/test_offertoday_browser_runtime.py `
  backend/tests/test_offertoday_canonical_and_identity.py `
  backend/tests/test_crawl_job_runtime.py `
  backend/tests/test_startup_recovery_service.py `
  backend/tests/test_offertoday_coverage_audit.py
```

Expected: all pass. Record exact counts.

- [ ] **Step 3: Compile and lint changed Python paths**

```powershell
python -m compileall -q `
  backend/app/sources/offertoday/research/smoke.py `
  backend/app/sources/offertoday/research/stage_gate.py `
  backend/app/services/offertoday_research_live_service.py `
  backend/scripts/offertoday_research_census.py

python -m ruff check `
  backend/app/sources/offertoday/research/smoke.py `
  backend/app/sources/offertoday/research/stage_gate.py `
  backend/app/services/offertoday_research_live_service.py `
  backend/scripts/offertoday_research_census.py `
  backend/tests/test_offertoday_listing_runner.py `
  backend/tests/test_offertoday_research_smoke.py `
  backend/tests/test_offertoday_research_live_service.py `
  backend/tests/test_offertoday_research_stage_gate.py `
  backend/tests/test_offertoday_research_census_cli.py
```

Expected: both exit 0.

- [ ] **Step 4: Re-verify immutable evidence and no-scope-creep invariants**

Repeat Task 2 Step 10, then run:

```powershell
git diff --check refs/codex/offertoday-plan2-base..HEAD
git diff --name-only refs/codex/offertoday-plan2-base..HEAD -- `
  backend/alembic backend/app/models docker-compose.yml docker-compose.dev.yml .env .env.example
git status --short --branch
```

Expected: both artifacts remain valid and hash-identical; no migration/model/Compose/env file is committed in this range; unrelated dirty work remains visible.

- [ ] **Step 5: Run spec compliance review**

Review against every acceptance criterion in `docs/superpowers/specs/2026-07-12-offertoday-two-page-task8-smoke-design.md`. The reviewer must inspect actual code and tests and explicitly confirm:

- page 1 then optional page 2, never page 3;
- no listing or detail retry;
- canonical-ID cross-page deduplication and authority promotion/no-downgrade;
- exactly 20 frozen targets before detail request 1;
- 20 sequential details and 19 three-second delays on success;
- metadata/run-start/summary/manifest/CLI budget agreement;
- strict tamper rejection and fail-only legacy replay;
- both immutable failed artifacts remain valid;
- same browser and no product-data writes; and
- no live request or Task 9 work.

Fix every spec gap through a new failing test, rerun affected tests, and repeat review until compliant.

- [ ] **Step 6: Run code-quality review**

Review only after spec compliance. Fix every Critical/Important issue, rerun affected tests, and re-review. Explicitly inspect whether stage-gate authority replay reuses the shared resolver/index without inventing another identity policy and whether legacy compatibility can ever authorize a completed smoke.

- [ ] **Step 7: Run final verification after the last review fix**

Re-run Steps 1-4 after the final code change. Do not rely on earlier green output.

- [ ] **Step 8: Stop and request one separately authorized live smoke**

Report:

- implementation and documentation commit IDs;
- exact smoke-focused and Plan 1 pass counts;
- compile/Ruff results;
- both immutable artifact verification results and hashes;
- committed-range and dirty-worktree evidence;
- confirmation that no OfferToday request occurred during implementation; and
- proposed live budget: at most two ordered listing requests plus at most 20 sequential detail requests, no retries, same fresh-headless browser, and zero product-data writes.

Do not capture baselines or execute the replacement smoke until the user explicitly approves exactly one run.

---

## Verification Matrix

| Requirement | Required evidence |
|---|---|
| Page 2 is the smallest bounded change | Shared-runner two-page characterization and live-service policy test |
| Page 3 can never occur | `max_pages_per_condition=2` plus strict replay page-sequence tamper test |
| Page 1 with 20 IDs stops early | `unique_job_cap=20` runner and service tests |
| Cross-page duplicates do not inflate the cohort | Runner, pure freeze, and strict replay duplicate tests |
| Promotion/no-downgrade remains authoritative | Cross-page explicit/fallback replay tests |
| Short two-page result makes zero details | Pure decision and live-service tests |
| Successful run makes 20 ordered details | Existing detail-loop test retained with two-page listing result |
| Listing/detail retries remain zero | Exact policy test and attempt-number replay checks |
| Every evidence layer agrees on 2/20 | Metadata, run-start, summary, manifest, CLI tamper tests |
| Old failed evidence remains valid | Offline verify-run plus exact before/after manifest hashes for both runs |
| Legacy budget cannot pass | Completed legacy-budget rejection test |
| Same browser remains in use | Injected runtime fetcher identity test |
| Product data remains unchanged | No-op sink tests and run-start/run-end snapshot/product/inventory hashes |
| Task 9 remains locked | Documentation checks and absence of calibration/stability source files |

## Commit Sequence

1. `fix(offertoday): bound task 8 smoke to two listing pages`
2. `fix(offertoday): verify two-page smoke evidence`
3. `docs(offertoday): amend task 8 for two listing pages`

Do not squash these checkpoints. Do not commit runtime artifacts.
