from __future__ import annotations

from app.sources.offertoday.detail_identity import OfferTodayDetailIdentity
from app.sources.offertoday.listing_runner import (
    ListingRunResult,
    OfferTodayListingCondition,
)
from app.sources.offertoday.research.live_contracts import (
    DetailSmokeObservation,
    DetailSmokeTarget,
    SmokeDecision,
)


SMOKE_LISTING_REQUEST_LIMIT = 2
SMOKE_DETAIL_TARGET_COUNT = 20

_SMOKE_FAILURE_KINDS = {
    "auth_expired",
    "waf_challenge",
    "ip_blocked",
    "transient_transport",
    "invalid_payload",
    "id_mismatch",
}


def runtime_smoke_request_budget() -> dict[str, int]:
    return {
        "listing": SMOKE_LISTING_REQUEST_LIMIT,
        "detail": SMOKE_DETAIL_TARGET_COUNT,
    }


def build_runtime_smoke_condition() -> OfferTodayListingCondition:
    return OfferTodayListingCondition(
        search_family="runtime_smoke",
        category_id=118000,
        keyword="",
        endpoint="search",
        rcd_type=7,
    )


def freeze_detail_smoke_cohort(
    listing_result: ListingRunResult,
    *,
    limit: int,
) -> tuple[DetailSmokeTarget, ...]:
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive exact integer")

    validated_identities = tuple(
        OfferTodayDetailIdentity(
            job_id=identity.job_id,
            encrypted_job_id=identity.encrypted_job_id,
            encrypted_job_id_source=identity.encrypted_job_id_source,
        )
        for identity in listing_result.id_pairs
    )
    accepted_job_ids = set(listing_result.accepted_job_ids)
    seen_job_ids: set[str] = set()
    targets: list[DetailSmokeTarget] = []
    for identity in validated_identities:
        job_id = identity.job_id
        if job_id not in accepted_job_ids or job_id in seen_job_ids:
            continue
        seen_job_ids.add(job_id)
        targets.append(
            DetailSmokeTarget(
                position=len(targets) + 1,
                job_id=job_id,
                encrypted_job_id=identity.encrypted_job_id,
                encrypted_job_id_source=identity.encrypted_job_id_source,
            )
        )
        if len(targets) == limit:
            break
    return tuple(targets)


def _is_clean_bounded_listing_end(listing_result: ListingRunResult) -> bool:
    listing_attempts = listing_result.observations
    if not 1 <= len(listing_attempts) <= SMOKE_LISTING_REQUEST_LIMIT:
        return False

    if tuple(item.page for item in listing_attempts) != tuple(
        range(1, len(listing_attempts) + 1)
    ):
        return False

    return (
        all(
            item.attempt == 1
            and item.classification == "success"
            and item.search_family == "runtime_smoke"
            and item.category_id == 118000
            and item.keyword == ""
            and item.endpoint == "search"
            and item.rcd_type == 7
            and item.session_mode == "fresh-headless"
            for item in listing_attempts
        )
        and all(
            item.row_count > 0 and item.has_more is not False
            for item in listing_attempts
        )
        and all(item.stop_reason is None for item in listing_attempts[:-1])
        and listing_attempts[-1].stop_reason == listing_result.stop_reason
        and listing_result.stop_reason in {"target_cap", "page_cap"}
        and (
            listing_result.stop_reason != "page_cap"
            or len(listing_attempts) == SMOKE_LISTING_REQUEST_LIMIT
        )
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


def listing_ready_for_detail_smoke(
    listing_result: ListingRunResult,
    frozen_targets: tuple[DetailSmokeTarget, ...],
) -> bool:
    return (
        _is_expected_listing_truncation(listing_result)
        and len(frozen_targets) == SMOKE_DETAIL_TARGET_COUNT
    )


def _failed_decision(
    *,
    reason: str,
    expected_truncation: bool,
    frozen: tuple[DetailSmokeTarget, ...],
    observations: tuple[DetailSmokeObservation, ...],
) -> SmokeDecision:
    attempted_count = len(observations)
    return SmokeDecision(
        smoke_passed=False,
        stop_reason=reason,
        expected_truncation=expected_truncation,
        frozen_count=len(frozen),
        attempted_count=attempted_count,
        terminal_count=sum(
            item.classification == "terminal_unavailable" for item in observations
        ),
        success_count=sum(item.classification == "success" for item in observations),
        unattempted_count=max(0, len(frozen) - attempted_count),
    )


def evaluate_smoke(
    *,
    listing_result: ListingRunResult,
    frozen_targets: tuple[DetailSmokeTarget, ...],
    observations: tuple[DetailSmokeObservation, ...],
    required_target_count: int = SMOKE_DETAIL_TARGET_COUNT,
) -> SmokeDecision:
    if type(required_target_count) is not int or required_target_count < 1:
        raise ValueError("required_target_count must be a positive exact integer")

    clean_bounded_listing_end = _is_clean_bounded_listing_end(listing_result)
    if not clean_bounded_listing_end:
        return _failed_decision(
            reason=f"listing_{listing_result.stop_reason}",
            expected_truncation=False,
            frozen=frozen_targets,
            observations=observations,
        )
    if len(frozen_targets) != required_target_count:
        return _failed_decision(
            reason="insufficient_valid_detail_targets",
            expected_truncation=True,
            frozen=frozen_targets,
            observations=observations,
        )
    expected_truncation = _is_expected_listing_truncation(listing_result)
    if not expected_truncation:
        return _failed_decision(
            reason=f"listing_{listing_result.stop_reason}",
            expected_truncation=False,
            frozen=frozen_targets,
            observations=observations,
        )

    expected_prefix = frozen_targets[: len(observations)]
    if tuple(item.target for item in observations) != expected_prefix:
        return _failed_decision(
            reason="detail_attempt_order_mismatch",
            expected_truncation=True,
            frozen=frozen_targets,
            observations=observations,
        )

    for item in observations:
        if item.classification in _SMOKE_FAILURE_KINDS:
            return _failed_decision(
                reason=item.classification,
                expected_truncation=True,
                frozen=frozen_targets,
                observations=observations,
            )
        if item.classification == "success" and not all(
            (
                item.identity_valid,
                item.parsed,
                item.has_title,
                item.has_company,
                item.has_description,
            )
        ):
            return _failed_decision(
                reason="incomplete_success_detail",
                expected_truncation=True,
                frozen=frozen_targets,
                observations=observations,
            )
        if item.classification not in {"success", "terminal_unavailable"}:
            return _failed_decision(
                reason=f"unexpected_detail_kind:{item.classification}",
                expected_truncation=True,
                frozen=frozen_targets,
                observations=observations,
            )
        if (
            item.classification == "terminal_unavailable"
            and item.api_code != 2520
        ):
            return _failed_decision(
                reason="invalid_terminal_unavailable",
                expected_truncation=True,
                frozen=frozen_targets,
                observations=observations,
            )

    if len(observations) != required_target_count:
        reason = (
            observations[-1].classification
            if observations and observations[-1].stop_batch
            else "unattempted_without_batch_stop"
        )
        return _failed_decision(
            reason=reason,
            expected_truncation=True,
            frozen=frozen_targets,
            observations=observations,
        )

    terminal_count = sum(
        item.classification == "terminal_unavailable" for item in observations
    )
    success_count = sum(item.classification == "success" for item in observations)
    return SmokeDecision(
        smoke_passed=True,
        stop_reason=None,
        expected_truncation=True,
        frozen_count=len(frozen_targets),
        attempted_count=len(observations),
        terminal_count=terminal_count,
        success_count=success_count,
        unattempted_count=0,
    )
