from __future__ import annotations

from dataclasses import replace

import pytest

from app.sources.offertoday.listing_runner import (
    ListingGap,
    ListingIdentityConflict,
    ListingIdentityIssue,
    ListingPageObservation,
    ListingRunResult,
    OfferTodayIdentityPair,
    OfferTodayListingCondition,
)
from app.sources.offertoday.research.live_contracts import (
    DetailSmokeObservation,
    DetailSmokeTarget,
)
from app.sources.offertoday.research.smoke import (
    build_runtime_smoke_condition,
    evaluate_smoke,
    freeze_detail_smoke_cohort,
    listing_ready_for_detail_smoke,
)
from app.sources.offertoday.response_policy import OfferTodayResponseKind


def pair(job_id: str, encrypted_job_id: str) -> OfferTodayIdentityPair:
    return OfferTodayIdentityPair(
        job_id=job_id,
        encrypted_job_id=encrypted_job_id,
    )


def page_observation(**changes) -> ListingPageObservation:
    values = {
        "condition_id": build_runtime_smoke_condition().condition_id,
        "search_family": "runtime_smoke",
        "category_id": 118000,
        "keyword": "",
        "endpoint": "search",
        "rcd_type": 7,
        "page": 1,
        "attempt": 1,
        "request_fingerprint": "a" * 64,
        "classification": "success",
        "api_code": 0,
        "reported_total": 100,
        "has_more": True,
        "row_count": 20,
        "missing_job_id_count": 0,
        "missing_encrypted_job_id_count": 0,
        "id_pairs": (),
        "rows": (),
        "identity_issues": (),
        "identity_conflicts": (),
        "latency_ms": 50,
        "session_mode": "fresh-headless",
        "retry_reason": None,
        "stop_reason": None,
    }
    values.update(changes)
    return ListingPageObservation(**values)


def listing_result(
    *,
    ordered_job_ids: tuple[str, ...] | None = None,
    accepted_job_ids: tuple[str, ...] | None = None,
    id_pairs: tuple[OfferTodayIdentityPair, ...] | None = None,
    observations: tuple[ListingPageObservation, ...] | None = None,
    identity_conflicts: tuple[ListingIdentityConflict, ...] = (),
    identity_issues: tuple[ListingIdentityIssue, ...] = (),
    gaps: tuple[ListingGap, ...] = (),
    stop_reason: str = "page_cap",
    is_complete: bool = False,
) -> ListingRunResult:
    default_pairs = tuple(pair(f"j{index}", f"e{index}") for index in range(1, 21))
    chosen_pairs = default_pairs if id_pairs is None else id_pairs
    chosen_ids = tuple(item.job_id for item in chosen_pairs)
    return ListingRunResult(
        ordered_job_ids=(chosen_ids if ordered_job_ids is None else ordered_job_ids),
        accepted_job_ids=(chosen_ids if accepted_job_ids is None else accepted_job_ids),
        id_pairs=chosen_pairs,
        observations=(
            (page_observation(id_pairs=chosen_pairs),)
            if observations is None
            else observations
        ),
        condition_outcomes=(),
        identity_conflicts=identity_conflicts,
        identity_issues=identity_issues,
        gaps=gaps,
        stop_reason=stop_reason,
        is_complete=is_complete,
    )


def target(position: int) -> DetailSmokeTarget:
    return DetailSmokeTarget(
        position=position,
        job_id=f"j{position}",
        encrypted_job_id=f"e{position}",
    )


def detail_observation(
    item: DetailSmokeTarget,
    *,
    classification: str = "success",
    api_code: int | None = 0,
    stop_batch: bool = False,
    **changes,
) -> DetailSmokeObservation:
    values = {
        "target": item,
        "classification": classification,
        "api_code": api_code,
        "started_at": "2026-07-11T00:00:00+00:00",
        "completed_at": "2026-07-11T00:00:01+00:00",
        "latency_ms": 1000,
        "identity_valid": classification == "success",
        "parsed": classification == "success",
        "has_title": classification == "success",
        "has_company": classification == "success",
        "has_description": classification == "success",
        "stop_batch": stop_batch,
    }
    values.update(changes)
    return DetailSmokeObservation(**values)


def frozen_targets(count: int = 20) -> tuple[DetailSmokeTarget, ...]:
    return tuple(target(index) for index in range(1, count + 1))


def test_smoke_condition_is_the_locked_compatibility_control() -> None:
    assert build_runtime_smoke_condition() == OfferTodayListingCondition(
        search_family="runtime_smoke",
        category_id=118000,
        keyword="",
        endpoint="search",
        rcd_type=7,
    )


def test_freeze_detail_cohort_is_distinct_first_seen_and_accepted_only() -> None:
    result = listing_result(
        ordered_job_ids=("j1", "j2", "j3"),
        accepted_job_ids=("j1", "j3"),
        id_pairs=(
            pair("j1", "e1"),
            pair("j2", "e2"),
            pair("j1", "e1-duplicate"),
            pair("", "missing-job"),
            pair("j-missing-encrypted", ""),
            pair("j3", "e3"),
        ),
    )

    assert freeze_detail_smoke_cohort(result, limit=20) == (
        DetailSmokeTarget(position=1, job_id="j1", encrypted_job_id="e1"),
        DetailSmokeTarget(position=2, job_id="j3", encrypted_job_id="e3"),
    )


def test_freeze_detail_cohort_returns_all_available_when_fewer_than_limit() -> None:
    result = listing_result(
        ordered_job_ids=("j1", "j2"),
        accepted_job_ids=("j1", "j2"),
        id_pairs=(pair("j1", "e1"), pair("j2", "e2")),
    )

    assert freeze_detail_smoke_cohort(result, limit=20) == (target(1), target(2))


@pytest.mark.parametrize("limit", [True, 0, -1])
def test_freeze_detail_cohort_rejects_invalid_limit(limit) -> None:
    with pytest.raises(ValueError, match="positive exact integer"):
        freeze_detail_smoke_cohort(listing_result(), limit=limit)


def test_listing_ready_requires_one_clean_successful_page_cap() -> None:
    result = listing_result()
    targets = freeze_detail_smoke_cohort(result, limit=20)

    assert listing_ready_for_detail_smoke(result, targets) is True

    conflict = ListingIdentityConflict(
        job_ids=("j1",),
        encrypted_job_ids=("e1", "e2"),
        reason="one_job_id_to_multiple_encrypted_ids",
    )
    assert (
        listing_ready_for_detail_smoke(
            replace(result, identity_conflicts=(conflict,)),
            targets,
        )
        is False
    )


def test_evaluate_smoke_accepts_twenty_successes() -> None:
    targets = frozen_targets()
    observations = tuple(detail_observation(item) for item in targets)

    decision = evaluate_smoke(
        listing_result=listing_result(),
        frozen_targets=targets,
        observations=observations,
    )

    assert decision.smoke_passed is True
    assert decision.stop_reason is None
    assert decision.expected_truncation is True
    assert decision.frozen_count == 20
    assert decision.attempted_count == 20
    assert decision.success_count == 20
    assert decision.terminal_count == 0
    assert decision.unattempted_count == 0


def test_evaluate_smoke_accepts_terminal_unavailable_without_replacement() -> None:
    targets = frozen_targets()
    observations = tuple(
        detail_observation(
            item,
            classification="terminal_unavailable" if item.position == 7 else "success",
            api_code=2520 if item.position == 7 else 0,
        )
        for item in targets
    )

    decision = evaluate_smoke(
        listing_result=listing_result(),
        frozen_targets=targets,
        observations=observations,
    )

    assert decision.smoke_passed is True
    assert decision.success_count == 19
    assert decision.terminal_count == 1


def test_evaluate_smoke_rejects_fewer_than_twenty_frozen_targets() -> None:
    targets = frozen_targets(19)

    decision = evaluate_smoke(
        listing_result=listing_result(
            id_pairs=tuple(pair(item.job_id, item.encrypted_job_id) for item in targets)
        ),
        frozen_targets=targets,
        observations=(),
    )

    assert decision.smoke_passed is False
    assert decision.stop_reason == "insufficient_valid_detail_targets"
    assert decision.unattempted_count == 19


@pytest.mark.parametrize(
    "classification",
    [
        "auth_expired",
        "waf_challenge",
        "ip_blocked",
        "transient_transport",
        "invalid_payload",
        "id_mismatch",
    ],
)
def test_evaluate_smoke_rejects_hard_and_nonterminal_failures(
    classification: str,
) -> None:
    targets = frozen_targets()
    observations = (
        detail_observation(
            targets[0],
            classification=classification,
            api_code=1002 if classification == "auth_expired" else None,
            stop_batch=True,
        ),
    )

    decision = evaluate_smoke(
        listing_result=listing_result(),
        frozen_targets=targets,
        observations=observations,
    )

    assert decision.smoke_passed is False
    assert decision.stop_reason == classification
    assert decision.attempted_count == 1
    assert decision.unattempted_count == 19


def test_evaluate_smoke_rejects_unattempted_targets_without_batch_stop() -> None:
    targets = frozen_targets()

    decision = evaluate_smoke(
        listing_result=listing_result(),
        frozen_targets=targets,
        observations=(detail_observation(targets[0]),),
    )

    assert decision.smoke_passed is False
    assert decision.stop_reason == "unattempted_without_batch_stop"


def test_evaluate_smoke_rejects_attempt_order_mismatch() -> None:
    targets = frozen_targets()

    decision = evaluate_smoke(
        listing_result=listing_result(),
        frozen_targets=targets,
        observations=(detail_observation(targets[1]),),
    )

    assert decision.stop_reason == "detail_attempt_order_mismatch"


def test_evaluate_smoke_rejects_listing_gap_before_detail_results() -> None:
    gap = ListingGap(
        condition_id=build_runtime_smoke_condition().condition_id,
        page=1,
        attempts=1,
        last_kind=OfferTodayResponseKind.TRANSIENT_TRANSPORT,
    )

    decision = evaluate_smoke(
        listing_result=listing_result(gaps=(gap,), stop_reason="attempts_exhausted"),
        frozen_targets=frozen_targets(),
        observations=(),
    )

    assert decision.smoke_passed is False
    assert decision.stop_reason == "listing_attempts_exhausted"
    assert decision.expected_truncation is False


@pytest.mark.parametrize(
    "missing_flag",
    ["identity_valid", "parsed", "has_title", "has_company", "has_description"],
)
def test_evaluate_smoke_rejects_incomplete_success_detail(
    missing_flag: str,
) -> None:
    targets = frozen_targets()
    observations = tuple(
        detail_observation(item, **({missing_flag: False} if item.position == 1 else {}))
        for item in targets
    )

    decision = evaluate_smoke(
        listing_result=listing_result(),
        frozen_targets=targets,
        observations=observations,
    )

    assert decision.smoke_passed is False
    assert decision.stop_reason == "incomplete_success_detail"


def test_detail_target_payload_contains_raw_ids_and_deterministic_hashes() -> None:
    payload = target(1).to_payload()

    assert payload["position"] == 1
    assert payload["job_id"] == "j1"
    assert payload["encrypted_job_id"] == "e1"
    assert len(payload["job_id_hash"]) == 64
    assert len(payload["encrypted_job_id_hash"]) == 64
