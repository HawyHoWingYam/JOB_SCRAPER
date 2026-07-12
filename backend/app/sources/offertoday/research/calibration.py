from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from statistics import median
from typing import Sequence

from app.scraper.offertoday.category_registry import OFFERTODAY_CATEGORIES_L1
from app.sources.offertoday.listing_runner import (
    ListingRunResult,
    OfferTodayListingCondition,
)
from app.sources.offertoday.research.live_contracts import CensusCandidate

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


@dataclass(frozen=True, slots=True)
class CalibrationVariantSummary:
    endpoint: str
    rcd_type: int | None
    accepted: bool
    logical_pages: int
    attempts: int
    valid_rows: int
    distinct_ids: int
    missing_ids: int
    conflicts: int
    median_latency_ms: float
    failure_count: int
    job_ids: tuple[str, ...]
    unique_ids: tuple[str, ...]
    rejection_reason: str | None = None
    amplification_compared_endpoint: str | None = None
    amplification_compared_rcd_type: int | None = None
    amplification_union_size: int | None = None
    amplification_delta_id_count: int | None = None
    amplification_delta_percentage_points: float | None = None


@dataclass(frozen=True, slots=True)
class CalibrationSelection:
    ranked_variants: tuple[CalibrationVariantSummary, ...]
    selected_variants: tuple[CalibrationVariantSummary, ...]
    union_size: int


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


def build_census_candidate(
    *,
    selected_endpoint: str,
    selected_rcd_type: int | None,
    ranked_variants: Sequence[CalibrationVariantSummary],
    source_artifact_hash: str,
) -> CensusCandidate:
    matching = tuple(
        item
        for item in ranked_variants
        if item.endpoint == selected_endpoint and item.rcd_type == selected_rcd_type
    )
    if len(matching) != 1 or not matching[0].accepted:
        raise ValueError("pilot-selected variant must be accepted calibration evidence")
    rejected_variants = tuple(
        asdict(item) for item in ranked_variants if item is not matching[0]
    )
    return CensusCandidate(
        endpoint=selected_endpoint,
        rcd_type=selected_rcd_type,
        category_ids=tuple(category.code for category in OFFERTODAY_CATEGORIES_L1),
        page_size=50,
        max_pages_per_condition=500,
        require_empty_confirmation=True,
        max_attempts_per_page=3,
        retry_delays_seconds=(5.0, 15.0),
        page_delay_range_seconds=(3.0, 5.0),
        session_mode="fresh-headless",
        fixed_repeat_category_ids=(118000, 112000, 127000),
        source_artifact_hash=source_artifact_hash,
        rejected_variants=rejected_variants,
    )


def _variant_control_order(endpoint: str, rcd_type: int | None) -> tuple[int, int]:
    endpoint_order = {"search": 0, "browse": 1}
    rcd_type_order = {7: 0, None: 1}
    return (
        endpoint_order.get(endpoint, len(endpoint_order)),
        rcd_type_order.get(rcd_type, len(rcd_type_order)),
    )


def _variant_order(value: CalibrationVariantSummary) -> tuple[int, int]:
    return _variant_control_order(value.endpoint, value.rcd_type)


def _ranking_key(value: CalibrationVariantSummary) -> tuple:
    endpoint_order, rcd_type_order = _variant_order(value)
    return (
        not value.accepted,
        value.failure_count,
        value.missing_ids + value.conflicts,
        -value.distinct_ids,
        value.attempts,
        value.median_latency_ms,
        endpoint_order,
        rcd_type_order,
    )


def select_calibration_variants(
    variants: Sequence[CalibrationVariantSummary],
    *,
    limit: int,
) -> CalibrationSelection:
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive exact integer")
    if not variants or not any(item.accepted for item in variants):
        raise ValueError("no accepted calibration variants")

    id_sets = [set(item.job_ids) for item in variants]
    union_ids = set().union(*id_sets)
    annotated = [
        replace(
            item,
            unique_ids=tuple(
                job_id
                for job_id in item.job_ids
                if all(
                    job_id not in other
                    for index, other in enumerate(id_sets)
                    if index != item_index
                )
            ),
        )
        for item_index, item in enumerate(variants)
    ]

    accepted_for_comparison = tuple(item for item in annotated if item.accepted)
    for candidate_index, candidate in enumerate(annotated):
        if not candidate.accepted:
            continue
        comparison_candidates = sorted(
            (
                item
                for item in accepted_for_comparison
                if item is not candidate
                and candidate.logical_pages > 2 * item.logical_pages
            ),
            key=lambda item: (item.logical_pages, *_variant_order(item)),
        )
        for comparison in comparison_candidates:
            delta_id_count = len(set(candidate.job_ids)) - len(set(comparison.job_ids))
            delta_percentage_points = (
                delta_id_count * 100 / len(union_ids) if union_ids else 0.0
            )
            if delta_percentage_points < 2.0:
                annotated[candidate_index] = replace(
                    candidate,
                    accepted=False,
                    rejection_reason="request_amplification",
                    amplification_compared_endpoint=comparison.endpoint,
                    amplification_compared_rcd_type=comparison.rcd_type,
                    amplification_union_size=len(union_ids),
                    amplification_delta_id_count=delta_id_count,
                    amplification_delta_percentage_points=delta_percentage_points,
                )
                break

    ranked = tuple(sorted(annotated, key=_ranking_key))
    selected = tuple(item for item in ranked if item.accepted)[:limit]
    if not selected:
        raise ValueError("no accepted calibration variants")
    return CalibrationSelection(
        ranked_variants=ranked,
        selected_variants=selected,
        union_size=len(union_ids),
    )


def summarize_calibration_variants(
    results: Sequence[BoundedConditionResult],
) -> tuple[CalibrationVariantSummary, ...]:
    grouped: dict[tuple[str, int | None], list[BoundedConditionResult]] = {}
    for result in results:
        key = (result.condition.endpoint, result.condition.rcd_type)
        grouped.setdefault(key, []).append(result)

    summaries: list[CalibrationVariantSummary] = []
    ordered_keys = sorted(
        grouped,
        key=lambda key: _variant_control_order(*key),
    )
    for endpoint, rcd_type in ordered_keys:
        variant_results = grouped[(endpoint, rcd_type)]
        observations = tuple(
            observation
            for result in variant_results
            for observation in result.listing_result.observations
        )
        ordered_job_ids: list[str] = []
        seen_job_ids: set[str] = set()
        for result in variant_results:
            for job_id in result.listing_result.accepted_job_ids:
                if job_id not in seen_job_ids:
                    seen_job_ids.add(job_id)
                    ordered_job_ids.append(job_id)
        rejection_reason = next(
            (
                result.rejection_reason
                for result in variant_results
                if result.rejection_reason is not None
            ),
            None,
        )
        summaries.append(
            CalibrationVariantSummary(
                endpoint=endpoint,
                rcd_type=rcd_type,
                accepted=all(result.accepted for result in variant_results),
                logical_pages=sum(result.pages_observed for result in variant_results),
                attempts=len(observations),
                valid_rows=sum(
                    len(observation.id_pairs)
                    for observation in observations
                    if observation.classification == "success"
                ),
                distinct_ids=len(ordered_job_ids),
                missing_ids=sum(
                    observation.missing_job_id_count
                    + observation.missing_encrypted_job_id_count
                    for observation in observations
                ),
                conflicts=sum(
                    len(result.listing_result.identity_conflicts)
                    for result in variant_results
                ),
                median_latency_ms=(
                    float(median(item.latency_ms for item in observations))
                    if observations
                    else 0.0
                ),
                failure_count=sum(
                    observation.classification != "success"
                    for observation in observations
                ),
                job_ids=tuple(ordered_job_ids),
                unique_ids=(),
                rejection_reason=rejection_reason,
            )
        )
    return tuple(summaries)


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
        or outcome.pages_observed < 0
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
    if outcome.pages_observed < 1:
        return result(accepted=False, reason="condition_outcome_mismatch")

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
