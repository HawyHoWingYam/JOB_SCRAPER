from __future__ import annotations

from dataclasses import dataclass

from app.scraper.offertoday.category_registry import OFFERTODAY_CATEGORIES_L1
from app.sources.offertoday.listing_runner import (
    ListingRunResult,
    OfferTodayListingCondition,
)


_CALIBRATION_CATEGORY_IDS = (118000, 112000)
_CALIBRATION_ENDPOINTS = ("search", "browse")
_CALIBRATION_RCD_TYPES = (7, None)
_BATCH_STOP_CLASSIFICATIONS = {
    "auth_expired",
    "waf_challenge",
    "ip_blocked",
    "id_mismatch",
}


@dataclass(frozen=True, slots=True)
class BoundedConditionResult:
    condition: OfferTodayListingCondition
    listing_result: ListingRunResult
    planned_page_limit: int
    pages_observed: int
    accepted: bool
    rejection_reason: str | None


def build_calibration_conditions() -> tuple[OfferTodayListingCondition, ...]:
    return tuple(
        OfferTodayListingCondition(
            search_family="plan2_calibration",
            category_id=category_id,
            keyword="",
            endpoint=endpoint,
            rcd_type=rcd_type,
        )
        for category_id in _CALIBRATION_CATEGORY_IDS
        for endpoint in _CALIBRATION_ENDPOINTS
        for rcd_type in _CALIBRATION_RCD_TYPES
    )


def build_pilot_conditions(
    endpoint: str,
    rcd_type: int | None,
) -> tuple[OfferTodayListingCondition, ...]:
    if endpoint not in _CALIBRATION_ENDPOINTS:
        raise ValueError("endpoint must be 'search' or 'browse'")
    if rcd_type is not None and type(rcd_type) is not int:
        raise ValueError("rcd_type must be an int or None")
    return tuple(
        OfferTodayListingCondition(
            search_family="plan2_pilot",
            category_id=category.code,
            keyword="",
            endpoint=endpoint,
            rcd_type=rcd_type,
        )
        for category in OFFERTODAY_CATEGORIES_L1
    )


def evaluate_bounded_condition(
    condition: OfferTodayListingCondition,
    listing_result: ListingRunResult,
    *,
    planned_page_limit: int,
) -> BoundedConditionResult:
    if type(planned_page_limit) is not int or planned_page_limit < 1:
        raise ValueError("planned_page_limit must be a positive exact integer")

    outcomes = listing_result.condition_outcomes
    pages_observed = outcomes[0].pages_observed if len(outcomes) == 1 else 0

    def result(*, accepted: bool, reason: str | None) -> BoundedConditionResult:
        return BoundedConditionResult(
            condition=condition,
            listing_result=listing_result,
            planned_page_limit=planned_page_limit,
            pages_observed=pages_observed,
            accepted=accepted,
            rejection_reason=reason,
        )

    if len(outcomes) != 1 or outcomes[0].condition != condition:
        return result(accepted=False, reason="condition_outcome_mismatch")

    outcome = outcomes[0]
    if (
        type(outcome.pages_observed) is not int
        or outcome.pages_observed < 1
        or outcome.pages_observed > planned_page_limit
        or outcome.stop_reason != listing_result.stop_reason
        or outcome.is_complete is not listing_result.is_complete
    ):
        return result(accepted=False, reason="condition_outcome_mismatch")
    if listing_result.gaps:
        return result(accepted=False, reason="listing_gap")
    if listing_result.identity_issues:
        return result(accepted=False, reason="identity_issue")
    if listing_result.identity_conflicts:
        return result(accepted=False, reason="identity_conflict")

    observations = listing_result.observations
    if any(item.condition_id != condition.condition_id for item in observations):
        return result(accepted=False, reason="condition_observation_mismatch")
    batch_stop = next(
        (
            item.classification
            for item in observations
            if item.classification in _BATCH_STOP_CLASSIFICATIONS
        ),
        None,
    )
    if batch_stop is not None:
        return result(accepted=False, reason=f"batch_stop:{batch_stop}")

    successful_observations = tuple(
        item for item in observations if item.classification == "success"
    )
    if tuple(item.page for item in successful_observations) != tuple(
        range(1, pages_observed + 1)
    ):
        return result(accepted=False, reason="successful_page_sequence_mismatch")
    if successful_observations[-1].stop_reason != listing_result.stop_reason:
        return result(accepted=False, reason="terminal_page_mismatch")

    if listing_result.stop_reason == "natural_exhaustion":
        if listing_result.is_complete is True:
            return result(accepted=True, reason=None)
        return result(accepted=False, reason="natural_exhaustion_incomplete")

    if listing_result.stop_reason == "page_cap":
        if pages_observed != planned_page_limit:
            return result(accepted=False, reason="planned_pages_not_observed")
        if listing_result.is_complete is False:
            return result(accepted=True, reason=None)
        return result(accepted=False, reason="page_cap_marked_complete")

    return result(
        accepted=False,
        reason=f"bounded_stop:{listing_result.stop_reason}",
    )
