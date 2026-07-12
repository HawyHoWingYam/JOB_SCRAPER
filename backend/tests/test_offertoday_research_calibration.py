from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
from app.scraper.offertoday.category_registry import OFFERTODAY_CATEGORIES_L1
from app.sources.offertoday.listing_runner import (
    ListingConditionOutcome,
    ListingGap,
    ListingIdentityConflict,
    ListingIdentityIssue,
    ListingPageObservation,
    ListingRunResult,
    OfferTodayIdentityPair,
    OfferTodayListingCondition,
)
from app.sources.offertoday.research.calibration import (
    BoundedConditionResult,
    CalibrationVariantSummary,
    build_calibration_conditions,
    build_census_candidate,
    build_pilot_conditions,
    evaluate_bounded_condition,
    select_calibration_variants,
    summarize_calibration_variants,
)
from app.sources.offertoday.research.live_contracts import CensusCandidate
from app.sources.offertoday.response_policy import OfferTodayResponseKind


def _condition() -> OfferTodayListingCondition:
    return OfferTodayListingCondition(
        search_family="plan2_calibration",
        category_id=118000,
        keyword="",
        endpoint="search",
        rcd_type=7,
    )


def _page_observation(
    condition: OfferTodayListingCondition,
    *,
    page: int,
    attempt: int = 1,
    classification: str = "success",
    stop_reason: str | None = None,
) -> ListingPageObservation:
    return ListingPageObservation(
        condition_id=condition.condition_id,
        search_family=condition.search_family,
        category_id=condition.category_id,
        keyword=condition.keyword,
        endpoint=condition.endpoint,
        rcd_type=condition.rcd_type,
        page=page,
        attempt=attempt,
        request_fingerprint=f"{page:064x}",
        classification=classification,
        api_code=0 if classification == "success" else None,
        reported_total=10,
        has_more=True,
        row_count=1 if classification == "success" else 0,
        missing_job_id_count=0,
        missing_encrypted_job_id_count=0,
        job_id_fallback_count=0,
        id_pairs=(),
        rows=(),
        identity_issues=(),
        identity_conflicts=(),
        latency_ms=25,
        session_mode="fresh-headless",
        retry_reason=None,
        stop_reason=stop_reason,
    )


def _listing_result(
    condition: OfferTodayListingCondition,
    *,
    pages_observed: int,
    stop_reason: str,
    is_complete: bool,
    observations: tuple[ListingPageObservation, ...] | None = None,
) -> ListingRunResult:
    if observations is None:
        observations = tuple(
            _page_observation(
                condition,
                page=page,
                stop_reason=(stop_reason if page == pages_observed else None),
            )
            for page in range(1, pages_observed + 1)
        )
    return ListingRunResult(
        ordered_job_ids=(),
        accepted_job_ids=(),
        id_pairs=(),
        observations=observations,
        condition_outcomes=(
            ListingConditionOutcome(
                condition=condition,
                pages_observed=pages_observed,
                stop_reason=stop_reason,
                is_complete=is_complete,
            ),
        ),
        identity_conflicts=(),
        identity_issues=(),
        gaps=(),
        stop_reason=stop_reason,
        is_complete=is_complete,
    )


def test_build_calibration_conditions_returns_exact_locked_matrix() -> None:
    assert build_calibration_conditions() == tuple(
        OfferTodayListingCondition(
            search_family="plan2_calibration",
            category_id=category_id,
            keyword="",
            endpoint=endpoint,
            rcd_type=rcd_type,
        )
        for category_id in (118000, 112000)
        for endpoint in ("search", "browse")
        for rcd_type in (7, None)
    )


def _variant(
    endpoint: str,
    rcd_type: int | None,
    *,
    accepted: bool = True,
    logical_pages: int = 3,
    attempts: int = 3,
    valid_rows: int = 10,
    distinct_ids: int = 10,
    missing_ids: int = 0,
    conflicts: int = 0,
    median_latency_ms: float = 100.0,
    failure_count: int = 0,
    job_ids: tuple[str, ...] | None = None,
) -> CalibrationVariantSummary:
    ids = job_ids or tuple(f"j{index}" for index in range(1, distinct_ids + 1))
    return CalibrationVariantSummary(
        endpoint=endpoint,
        rcd_type=rcd_type,
        accepted=accepted,
        logical_pages=logical_pages,
        attempts=attempts,
        valid_rows=valid_rows,
        distinct_ids=distinct_ids,
        missing_ids=missing_ids,
        conflicts=conflicts,
        median_latency_ms=median_latency_ms,
        failure_count=failure_count,
        job_ids=ids,
        unique_ids=(),
    )


def _candidate(**overrides) -> CensusCandidate:
    values = {
        "endpoint": "search",
        "rcd_type": None,
        "category_ids": tuple(category.code for category in OFFERTODAY_CATEGORIES_L1),
        "page_size": 50,
        "max_pages_per_condition": 500,
        "require_empty_confirmation": True,
        "max_attempts_per_page": 3,
        "retry_delays_seconds": (5.0, 15.0),
        "page_delay_range_seconds": (3.0, 5.0),
        "session_mode": "fresh-headless",
        "fixed_repeat_category_ids": (118000, 112000, 127000),
        "source_artifact_hash": "a" * 64,
        "rejected_variants": (
            {
                "endpoint": "search",
                "rcd_type": 7,
                "accepted": True,
                "failure_count": 0,
                "missing_ids": 60,
                "conflicts": 0,
                "logical_pages": 6,
                "attempts": 6,
                "median_latency_ms": 200.0,
            },
        ),
    }
    values.update(overrides)
    return CensusCandidate(**values)


def test_census_candidate_hashes_sorted_compact_canonical_json() -> None:
    candidate = _candidate()
    canonical_payload = {
        "category_ids": [category.code for category in OFFERTODAY_CATEGORIES_L1],
        "endpoint": "search",
        "fixed_repeat_category_ids": [118000, 112000, 127000],
        "max_attempts_per_page": 3,
        "max_pages_per_condition": 500,
        "page_delay_range_seconds": [3.0, 5.0],
        "page_size": 50,
        "rcd_type": None,
        "rejected_variants": [dict(candidate.rejected_variants[0])],
        "require_empty_confirmation": True,
        "retry_delays_seconds": [5.0, 15.0],
        "session_mode": "fresh-headless",
        "source_artifact_hash": "a" * 64,
    }
    expected = hashlib.sha256(
        json.dumps(
            canonical_payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()

    assert candidate.candidate_hash == expected
    assert candidate.to_payload() == {
        **canonical_payload,
        "candidate_hash": expected,
    }


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("endpoint", "invalid"),
        ("rcd_type", True),
        ("category_ids", (118000,)),
        ("page_size", 49),
        ("page_size", 50.0),
        ("max_pages_per_condition", 499),
        ("max_pages_per_condition", 500.0),
        ("require_empty_confirmation", False),
        ("require_empty_confirmation", 1),
        ("max_attempts_per_page", 2),
        ("max_attempts_per_page", 3.0),
        ("retry_delays_seconds", (5.0,)),
        ("page_delay_range_seconds", (3.0, 4.0)),
        ("session_mode", "headed"),
        ("fixed_repeat_category_ids", (118000, 112000)),
        ("source_artifact_hash", "not-a-hash"),
    ),
)
def test_census_candidate_rejects_controls_outside_the_locked_contract(
    field_name: str,
    value: object,
) -> None:
    with pytest.raises(ValueError, match=field_name):
        _candidate(**{field_name: value})


def test_build_census_candidate_preserves_the_pilot_selected_variant() -> None:
    ranked = (
        _variant(
            "browse",
            None,
            logical_pages=2,
            attempts=2,
            valid_rows=0,
            distinct_ids=0,
            job_ids=(),
        ),
        _variant("search", None, distinct_ids=46),
        _variant("search", 7, accepted=False, failure_count=1),
    )

    candidate = build_census_candidate(
        selected_endpoint="search",
        selected_rcd_type=None,
        ranked_variants=ranked,
        source_artifact_hash="b" * 64,
    )

    assert candidate.endpoint == "search"
    assert candidate.rcd_type is None
    assert [item["endpoint"] for item in candidate.rejected_variants] == [
        "browse",
        "search",
    ]
    assert candidate.rejected_variants[0]["valid_rows"] == 0
    assert candidate.rejected_variants[1]["failure_count"] == 1


@pytest.mark.parametrize(
    ("preferred", "other"),
    (
        (
            _variant("search", 7),
            _variant("browse", 7, accepted=False),
        ),
        (
            _variant("search", 7, failure_count=0),
            _variant("browse", 7, failure_count=1),
        ),
        (
            _variant("search", 7, missing_ids=0, conflicts=0),
            _variant("browse", 7, missing_ids=1, conflicts=0),
        ),
        (
            _variant("search", 7, distinct_ids=11),
            _variant("browse", 7, distinct_ids=10),
        ),
        (
            _variant("search", 7, attempts=3),
            _variant("browse", 7, attempts=4),
        ),
        (
            _variant("search", 7, median_latency_ms=99.0),
            _variant("browse", 7, median_latency_ms=100.0),
        ),
        (
            _variant("search", 7),
            _variant("browse", None),
        ),
    ),
)
def test_calibration_selection_uses_exact_ranking_order(
    preferred: CalibrationVariantSummary,
    other: CalibrationVariantSummary,
) -> None:
    selection = select_calibration_variants((other, preferred), limit=2)

    assert selection.ranked_variants[0].endpoint == preferred.endpoint
    assert selection.ranked_variants[0].rcd_type == preferred.rcd_type


def test_calibration_selection_rejects_when_no_variant_is_accepted() -> None:
    with pytest.raises(ValueError, match="no accepted calibration variants"):
        select_calibration_variants(
            (
                _variant("search", 7, accepted=False),
                _variant("browse", None, accepted=False),
            ),
            limit=2,
        )


def test_calibration_selection_rejects_request_amplification_below_two_points() -> None:
    baseline_ids = tuple(f"j{index}" for index in range(1, 51))
    amplified_ids = (*baseline_ids, "j51")
    baseline = _variant(
        "search",
        7,
        logical_pages=2,
        distinct_ids=50,
        job_ids=baseline_ids,
    )
    amplified = _variant(
        "browse",
        7,
        logical_pages=5,
        distinct_ids=51,
        job_ids=amplified_ids,
    )

    selection = select_calibration_variants((amplified, baseline), limit=2)

    amplified_result = next(
        item for item in selection.ranked_variants if item.endpoint == "browse"
    )
    assert amplified_result.accepted is False
    assert amplified_result.rejection_reason == "request_amplification"
    assert amplified_result.amplification_compared_endpoint == "search"
    assert amplified_result.amplification_compared_rcd_type == 7
    assert amplified_result.amplification_union_size == 51
    assert amplified_result.amplification_delta_id_count == 1
    assert amplified_result.amplification_delta_percentage_points == pytest.approx(
        100 / 51
    )
    assert amplified_result.unique_ids == ("j51",)
    assert selection.selected_variants == (selection.ranked_variants[0],)


def test_calibration_selection_keeps_exact_two_point_coverage_gain() -> None:
    baseline_ids = tuple(f"j{index}" for index in range(1, 50))
    amplified_ids = (*baseline_ids, "j50")
    selection = select_calibration_variants(
        (
            _variant(
                "search",
                7,
                logical_pages=2,
                distinct_ids=49,
                job_ids=baseline_ids,
            ),
            _variant(
                "browse",
                7,
                logical_pages=5,
                distinct_ids=50,
                job_ids=amplified_ids,
            ),
        ),
        limit=2,
    )

    assert len(selection.selected_variants) == 2
    assert all(item.accepted for item in selection.selected_variants)


def test_summarize_calibration_variants_reports_exact_observed_metrics() -> None:
    conditions = tuple(
        condition
        for condition in build_calibration_conditions()
        if condition.endpoint == "search" and condition.rcd_type == 7
    )
    bounded_results: list[BoundedConditionResult] = []
    job_ids_by_category = {
        118000: ("shared", "it-only"),
        112000: ("shared", "engineering-only"),
    }
    for index, condition in enumerate(conditions, start=1):
        job_ids = job_ids_by_category[condition.category_id]
        pairs = tuple(
            OfferTodayIdentityPair(job_id, job_id, "jobId_fallback")
            for job_id in job_ids
        )
        listing_result = _listing_result(
            condition,
            pages_observed=3,
            stop_reason="page_cap",
            is_complete=False,
        )
        observations = tuple(
            replace(
                observation,
                latency_ms=page * 10,
                row_count=(len(pairs) if page == 1 else 0),
                id_pairs=(pairs if page == 1 else ()),
                missing_encrypted_job_id_count=(index if page == 1 else 0),
                job_id_fallback_count=(len(pairs) if page == 1 else 0),
            )
            for page, observation in enumerate(
                listing_result.observations,
                start=1,
            )
        )
        listing_result = replace(
            listing_result,
            ordered_job_ids=job_ids,
            accepted_job_ids=job_ids,
            id_pairs=pairs,
            observations=observations,
        )
        bounded_results.append(
            evaluate_bounded_condition(
                condition,
                listing_result,
                planned_page_limit=3,
            )
        )

    summaries = summarize_calibration_variants(tuple(bounded_results))

    assert summaries == (
        CalibrationVariantSummary(
            endpoint="search",
            rcd_type=7,
            accepted=True,
            logical_pages=6,
            attempts=6,
            valid_rows=4,
            distinct_ids=3,
            missing_ids=3,
            conflicts=0,
            median_latency_ms=20.0,
            failure_count=0,
            job_ids=("shared", "it-only", "engineering-only"),
            unique_ids=(),
        ),
    )


@pytest.mark.parametrize(
    ("endpoint", "rcd_type"),
    (("search", 7), ("search", None), ("browse", 7), ("browse", None)),
)
def test_build_pilot_conditions_uses_all_canonical_categories_in_registry_order(
    endpoint: str,
    rcd_type: int | None,
) -> None:
    conditions = build_pilot_conditions(endpoint, rcd_type)

    assert len(conditions) == 31
    assert tuple(item.category_id for item in conditions) == tuple(
        category.code for category in OFFERTODAY_CATEGORIES_L1
    )
    assert all(
        item
        == OfferTodayListingCondition(
            search_family="plan2_pilot",
            category_id=item.category_id,
            keyword="",
            endpoint=endpoint,
            rcd_type=rcd_type,
        )
        for item in conditions
    )


@pytest.mark.parametrize("endpoint", ("", "list", "SEARCH", None))
def test_build_pilot_conditions_rejects_unknown_endpoints(endpoint: object) -> None:
    with pytest.raises(ValueError, match="endpoint"):
        build_pilot_conditions(endpoint, 7)  # type: ignore[arg-type]


@pytest.mark.parametrize("rcd_type", (True, 7.0, "7"))
def test_build_pilot_conditions_rejects_non_exact_integer_rcd_type(
    rcd_type: object,
) -> None:
    with pytest.raises(ValueError, match="rcd_type"):
        build_pilot_conditions("search", rcd_type)  # type: ignore[arg-type]


def test_bounded_condition_accepts_natural_exhaustion_within_limit() -> None:
    condition = _condition()
    listing_result = _listing_result(
        condition,
        pages_observed=2,
        stop_reason="natural_exhaustion",
        is_complete=True,
    )

    result = evaluate_bounded_condition(
        condition,
        listing_result,
        planned_page_limit=3,
    )

    assert result == BoundedConditionResult(
        condition=condition,
        listing_result=listing_result,
        planned_page_limit=3,
        pages_observed=2,
        accepted=True,
        rejection_reason=None,
    )


def test_bounded_condition_accepts_page_cap_after_every_planned_page() -> None:
    condition = _condition()
    listing_result = _listing_result(
        condition,
        pages_observed=3,
        stop_reason="page_cap",
        is_complete=False,
    )

    result = evaluate_bounded_condition(
        condition,
        listing_result,
        planned_page_limit=3,
    )

    assert result.accepted is True
    assert result.rejection_reason is None
    assert result.pages_observed == 3


def test_bounded_condition_allows_retryable_attempt_before_successful_page() -> None:
    condition = _condition()
    observations = (
        _page_observation(
            condition,
            page=1,
            attempt=1,
            classification="transient_transport",
        ),
        _page_observation(
            condition,
            page=1,
            attempt=2,
            stop_reason="page_cap",
        ),
    )
    listing_result = _listing_result(
        condition,
        pages_observed=1,
        stop_reason="page_cap",
        is_complete=False,
        observations=observations,
    )

    result = evaluate_bounded_condition(
        condition,
        listing_result,
        planned_page_limit=1,
    )

    assert result.accepted is True
    assert result.rejection_reason is None


def test_bounded_condition_rejects_page_cap_before_planned_limit() -> None:
    condition = _condition()
    result = evaluate_bounded_condition(
        condition,
        _listing_result(
            condition,
            pages_observed=2,
            stop_reason="page_cap",
            is_complete=False,
        ),
        planned_page_limit=3,
    )

    assert result.accepted is False
    assert result.rejection_reason == "planned_pages_not_observed"


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    (
        ("gap", "listing_gap"),
        ("identity_issue", "identity_issue"),
        ("identity_conflict", "identity_conflict"),
        ("batch_stop", "batch_stop:auth_expired"),
    ),
)
def test_bounded_condition_rejects_gaps_identity_defects_or_batch_stops(
    mutation: str,
    expected_reason: str,
) -> None:
    condition = _condition()
    listing_result = _listing_result(
        condition,
        pages_observed=3,
        stop_reason="page_cap",
        is_complete=False,
    )
    if mutation == "gap":
        listing_result = replace(
            listing_result,
            gaps=(
                ListingGap(
                    condition_id=condition.condition_id,
                    page=2,
                    attempts=3,
                    last_kind=OfferTodayResponseKind.TRANSIENT_TRANSPORT,
                ),
            ),
        )
    elif mutation == "identity_issue":
        listing_result = replace(
            listing_result,
            identity_issues=(
                ListingIdentityIssue(
                    job_id="j1",
                    encrypted_job_id=None,
                    reason="missing_encrypted_job_id",
                ),
            ),
        )
    elif mutation == "identity_conflict":
        listing_result = replace(
            listing_result,
            identity_conflicts=(
                ListingIdentityConflict(
                    job_ids=("j1",),
                    encrypted_job_ids=("e1", "e2"),
                    reason="one_to_many",
                ),
            ),
        )
    else:
        listing_result = replace(
            listing_result,
            observations=(
                _page_observation(
                    condition,
                    page=1,
                    classification="auth_expired",
                    stop_reason="auth_expired",
                ),
                *listing_result.observations,
            ),
        )

    result = evaluate_bounded_condition(
        condition,
        listing_result,
        planned_page_limit=3,
    )

    assert result.accepted is False
    assert result.rejection_reason == expected_reason


def test_bounded_condition_preserves_first_page_batch_stop_with_zero_pages() -> None:
    condition = _condition()
    listing_result = _listing_result(
        condition,
        pages_observed=0,
        stop_reason="auth_expired",
        is_complete=False,
        observations=(
            _page_observation(
                condition,
                page=1,
                classification="auth_expired",
                stop_reason="auth_expired",
            ),
        ),
    )

    result = evaluate_bounded_condition(
        condition,
        listing_result,
        planned_page_limit=3,
    )

    assert result.accepted is False
    assert result.rejection_reason == "batch_stop:auth_expired"


@pytest.mark.parametrize("planned_page_limit", (0, -1, True, 1.5))
def test_bounded_condition_requires_a_positive_exact_integer_page_limit(
    planned_page_limit: object,
) -> None:
    condition = _condition()
    listing_result = _listing_result(
        condition,
        pages_observed=1,
        stop_reason="natural_exhaustion",
        is_complete=True,
    )

    with pytest.raises(ValueError, match="planned_page_limit"):
        evaluate_bounded_condition(
            condition,
            listing_result,
            planned_page_limit=planned_page_limit,  # type: ignore[arg-type]
        )
