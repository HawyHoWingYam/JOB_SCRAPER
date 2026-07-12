from __future__ import annotations

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
    OfferTodayListingCondition,
)
from app.sources.offertoday.research.calibration import (
    BoundedConditionResult,
    build_calibration_conditions,
    build_pilot_conditions,
    evaluate_bounded_condition,
)
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
