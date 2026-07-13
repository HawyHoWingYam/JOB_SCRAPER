from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from app.sources.offertoday.listing_contract import (
    OfferTodayListingCursorFieldPresence,
    OfferTodayListingPageEvidenceV2,
)
from app.sources.offertoday.listing_runner import (
    ListingConditionOutcome,
    ListingPageObservation,
    ListingRunResult,
    OfferTodayListingCondition,
)
from app.sources.offertoday.research.pagination_bakeoff import (
    BAKEOFF_CATEGORY_IDS,
    BAKEOFF_VARIANTS,
    PaginationBakeoffRepeat,
    PaginationConditionExecution,
    bakeoff_variant,
    build_bakeoff_order,
    compare_bakeoff_payloads,
    compare_bakeoff_repeats,
    pagination_bakeoff_controls_payload,
    pagination_bakeoff_thresholds_payload,
    pagination_bakeoff_to_payload,
    summarize_repeat,
    summarize_variant,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _execution(
    *,
    repeat_index: int,
    variant_id: str,
    category_id: int,
    category_order: int,
    ids: tuple[str, ...],
    raw_rows: int | None = None,
    duplicate_rows: int = 0,
    contract_error: str | None = None,
    zero_new_full_page: bool = False,
    complete: bool = True,
    condition_restart_index: int = 0,
) -> PaginationConditionExecution:
    variant = bakeoff_variant(variant_id)
    condition = OfferTodayListingCondition(
        search_family="cursor_pagination_bakeoff_v2",
        category_id=category_id,
        keyword="",
        endpoint="search",
        rcd_type=None,
    )
    row_count = len(ids) if raw_rows is None else raw_rows
    evidence = OfferTodayListingPageEvidenceV2(
        protocol_version=2,
        variant_id=variant_id,
        repeat_index=repeat_index,
        condition_restart_index=condition_restart_index,
        condition_execution_id=_sha(
            f"condition:{repeat_index}:{variant_id}:{category_id}"
        ),
        logical_request_id=_sha(
            f"logical:{repeat_index}:{variant_id}:{category_id}:1"
        ),
        physical_attempt_id=_sha(
            f"physical:{repeat_index}:{variant_id}:{category_id}:1:1"
        ),
        browser_context_hash=_sha(
            f"context:{repeat_index}:{variant_id}:{category_id}"
        ),
        pagination_mode=variant.pagination_mode,
        browser_lifecycle=variant.browser_lifecycle,
        requested_page_size=variant.requested_page_size,
        response_page_size=10,
        effective_page_size=10,
        cursor_input=None,
        cursor_output=None,
        response_cursor_fields=OfferTodayListingCursorFieldPresence(
            session_id=variant.pagination_mode == "response-cursor",
            supple_page=variant.pagination_mode == "response-cursor",
            supple_amount=variant.pagination_mode == "response-cursor",
            supple_type=variant.pagination_mode == "response-cursor",
            page_size=True,
        ),
        session_continuity=(
            "not_applicable"
            if variant.pagination_mode == "stateless-control"
            else "unavailable" if contract_error else "initial"
        ),
        result_row_count=row_count,
        supplemental_row_count=0,
        result_job_ids=ids,
        supplemental_job_ids=(),
        result_identity_pairs=(),
        supplemental_identity_pairs=(),
        cohort_overlap_job_ids=(),
        new_job_id_count=len(set(ids)),
        duplicate_job_id_count=duplicate_rows,
        zero_new_full_page=zero_new_full_page,
        terminal_signal=False,
        awaiting_empty_confirmation=False,
        contract_error=contract_error,
    )
    classification = "cursor_contract_violation" if contract_error else "success"
    is_complete = complete and contract_error is None
    stop_reason = (
        "natural_exhaustion"
        if is_complete
        else "cursor_contract_violation" if contract_error else "page_cap"
    )
    observation = ListingPageObservation(
        condition_id=condition.condition_id,
        search_family=condition.search_family,
        category_id=category_id,
        keyword="",
        endpoint="search",
        rcd_type=None,
        page=1,
        attempt=1,
        request_fingerprint=_sha(
            f"request:{repeat_index}:{variant_id}:{category_id}"
        ),
        classification=classification,
        api_code=0,
        reported_total=999,
        has_more=True,
        row_count=row_count,
        missing_job_id_count=0,
        missing_encrypted_job_id_count=0,
        job_id_fallback_count=0,
        id_pairs=(),
        rows=(),
        identity_issues=(),
        identity_conflicts=(),
        latency_ms=100,
        session_mode="fresh-headless",
        retry_reason=None,
        stop_reason=stop_reason,
        cursor_evidence=evidence,
    )
    outcome = ListingConditionOutcome(
        condition=condition,
        pages_observed=0 if contract_error else 1,
        stop_reason=stop_reason,
        is_complete=is_complete,
    )
    result = ListingRunResult(
        ordered_job_ids=tuple(dict.fromkeys(ids)),
        accepted_job_ids=tuple(dict.fromkeys(ids)) if not contract_error else (),
        id_pairs=(),
        observations=(observation,),
        condition_outcomes=(outcome,),
        identity_conflicts=(),
        identity_issues=(),
        gaps=(),
        stop_reason=outcome.stop_reason,
        is_complete=is_complete,
    )
    return PaginationConditionExecution(
        repeat_index=repeat_index,
        variant_id=variant_id,
        category_id=category_id,
        category_order=category_order,
        result=result,
    )


def _repeat(
    repeat_index: int,
    *,
    order_seed: int = 20260713,
    candidate_ids_by_category: dict[int, tuple[str, ...]] | None = None,
    candidate_contract_error: str | None = None,
    candidate_zero_new: bool = False,
    candidate_incomplete: bool = False,
    candidate_restart_index: int = 0,
    passing_variant_ids: tuple[str, ...] = ("ui-cursor",),
) -> PaginationBakeoffRepeat:
    order = build_bakeoff_order(
        repeat_index=repeat_index,
        order_seed=order_seed,
    )
    candidate_ids_by_category = candidate_ids_by_category or {
        category_id: tuple(
            f"{category_id}-candidate-{index}" for index in range(10)
        )
        for category_id in BAKEOFF_CATEGORY_IDS
    }
    executions = []
    for entry in order:
        if entry.variant_id == "stateless-current":
            ids = tuple(
                f"{entry.category_id}-control-{index % 5}" for index in range(10)
            )
            executions.append(
                _execution(
                    repeat_index=repeat_index,
                    variant_id=entry.variant_id,
                    category_id=entry.category_id,
                    category_order=entry.category_order,
                    ids=ids,
                    raw_rows=10,
                    duplicate_rows=5,
                )
            )
        elif entry.variant_id in passing_variant_ids:
            executions.append(
                _execution(
                    repeat_index=repeat_index,
                    variant_id=entry.variant_id,
                    category_id=entry.category_id,
                    category_order=entry.category_order,
                    ids=candidate_ids_by_category[entry.category_id],
                    raw_rows=10,
                    duplicate_rows=0,
                    contract_error=candidate_contract_error,
                    zero_new_full_page=candidate_zero_new,
                    complete=not candidate_incomplete,
                    condition_restart_index=candidate_restart_index,
                )
            )
        else:
            executions.append(
                _execution(
                    repeat_index=repeat_index,
                    variant_id=entry.variant_id,
                    category_id=entry.category_id,
                    category_order=entry.category_order,
                    ids=(),
                    raw_rows=0,
                    contract_error="fixture_rejected_variant",
                )
            )
    return PaginationBakeoffRepeat(
        repeat_index=repeat_index,
        order_seed=order_seed,
        order=order,
        executions=tuple(executions),
    )


def test_bakeoff_order_is_deterministic_complete_and_category_randomized() -> None:
    first = build_bakeoff_order(repeat_index=1, order_seed=20260713)
    repeated = build_bakeoff_order(repeat_index=1, order_seed=20260713)
    second_repeat = build_bakeoff_order(repeat_index=2, order_seed=20260713)

    assert first == repeated
    assert first != second_repeat
    assert len(first) == len(BAKEOFF_CATEGORY_IDS) * len(BAKEOFF_VARIANTS)
    for category_id in BAKEOFF_CATEGORY_IDS:
        category_entries = [item for item in first if item.category_id == category_id]
        assert {item.variant_id for item in category_entries} == {
            item.variant_id for item in BAKEOFF_VARIANTS
        }
        assert [item.category_order for item in category_entries] == [1, 2, 3, 4, 5]


def test_bakeoff_payload_persists_exact_frozen_controls_and_thresholds() -> None:
    payload = pagination_bakeoff_to_payload(_repeat(1))

    assert payload["controls"] == pagination_bakeoff_controls_payload() == {
        "protocol_version": 2,
        "endpoint": "search",
        "endpoint_path": "/wapi/geek/recommend/search/list",
        "rcd_type": None,
        "category_ids": [118000, 112000, 127000],
        "max_logical_pages_per_condition": 10,
        "max_attempts_per_page": 2,
        "require_empty_confirmation": True,
        "retry_delays_seconds": [5.0],
        "page_delay_range_seconds": [3.0, 5.0],
        "terminal_policy": "cursor-terminal-empty-confirmation-v1",
        "session_mode": "fresh-headless",
        "variants": [
            {
                "variant_id": "stateless-current",
                "pagination_mode": "stateless-control",
                "requested_page_size": 50,
                "browser_lifecycle": "shared-variant-runtime",
            },
            {
                "variant_id": "ui-cursor",
                "pagination_mode": "response-cursor",
                "requested_page_size": 10,
                "browser_lifecycle": "shared-variant-runtime",
            },
            {
                "variant_id": "ui-cursor-50",
                "pagination_mode": "response-cursor",
                "requested_page_size": 50,
                "browser_lifecycle": "shared-variant-runtime",
            },
            {
                "variant_id": "ui-cursor-restart",
                "pagination_mode": "response-cursor",
                "requested_page_size": 10,
                "browser_lifecycle": "restart-each-page",
            },
            {
                "variant_id": "ui-cursor-same-browser",
                "pagination_mode": "response-cursor",
                "requested_page_size": 10,
                "browser_lifecycle": "condition-local-runtime",
            },
        ],
    }
    assert payload["thresholds"] == pagination_bakeoff_thresholds_payload() == {
        "duplicate_absolute_reduction": 0.10,
        "duplicate_relative_reduction": 0.20,
        "minimum_jaccard": 0.95,
        "maximum_request_cost_multiplier": 2,
    }


@pytest.mark.parametrize(
    ("repeat_index", "order_seed"),
    ((0, 1), (3, 1), (1.0, 1), (1, "seed")),
)
def test_bakeoff_order_rejects_unfrozen_scalar_types(repeat_index, order_seed) -> None:
    with pytest.raises(ValueError):
        build_bakeoff_order(repeat_index=repeat_index, order_seed=order_seed)


def test_repeat_summary_reports_duplicates_cost_and_unique_contribution() -> None:
    summary = {item.variant_id: item for item in summarize_repeat(_repeat(1))}

    assert summary["stateless-current"].duplicate_rate == 0.5
    assert len(summary["stateless-current"].distinct_all_ids) == 15
    assert summary["ui-cursor"].duplicate_rate == 0
    assert len(summary["ui-cursor"].distinct_all_ids) == 30
    assert len(summary["ui-cursor"].unique_contribution_ids) == 30
    assert summary["ui-cursor"].requests_per_distinct_id == 0.1


def test_variant_summary_computes_condition_level_page_size_and_total_drift() -> None:
    execution = _execution(
        repeat_index=1,
        variant_id="stateless-current",
        category_id=118000,
        category_order=1,
        ids=("job-1",),
    )
    first = execution.result.observations[0]
    second = replace(
        first,
        page=2,
        request_fingerprint=_sha("request:stateless-current:118000:2"),
        reported_total=1000,
        cursor_evidence=replace(
            first.cursor_evidence,
            logical_request_id=_sha("logical:stateless-current:118000:2"),
            physical_attempt_id=_sha("physical:stateless-current:118000:2:1"),
            response_page_size=11,
            effective_page_size=11,
        ),
    )
    execution = replace(
        execution,
        result=replace(execution.result, observations=(first, second)),
    )

    summary = summarize_variant("stateless-current", (execution,))

    assert summary.response_page_sizes == (10, 11)
    assert summary.reported_totals == (999, 1000)
    assert summary.response_page_size_drift_conditions == 1
    assert summary.reported_total_drift_conditions == 1


def test_comparison_accepts_stable_higher_union_materially_lower_duplicate_candidate() -> None:
    decision = compare_bakeoff_repeats(_repeat(1), _repeat(2))

    assert decision.accepted is True
    assert decision.selected_variant_id == "ui-cursor"
    selected = next(
        item for item in decision.comparisons if item.variant_id == "ui-cursor"
    )
    assert selected.accepted is True
    assert selected.rejection_reasons == ()
    assert selected.minimum_condition_jaccard == 1.0
    assert selected.duplicate_absolute_reduction == 0.5
    assert selected.duplicate_relative_reduction == 1.0


def test_comparison_rejects_cursor_violation() -> None:
    decision = compare_bakeoff_repeats(
        _repeat(1, candidate_contract_error="incomplete_cursor"),
        _repeat(2, candidate_contract_error="incomplete_cursor"),
    )
    selected = next(
        item for item in decision.comparisons if item.variant_id == "ui-cursor"
    )

    assert decision.accepted is False
    assert "cursor_violation" in selected.rejection_reasons
    assert "unclassified_failure" in selected.rejection_reasons


def test_comparison_rejects_short_window_jaccard_below_gate() -> None:
    changed = {
        category_id: tuple(
            f"{category_id}-changed-{index}" for index in range(10)
        )
        for category_id in BAKEOFF_CATEGORY_IDS
    }
    decision = compare_bakeoff_repeats(
        _repeat(1),
        _repeat(2, candidate_ids_by_category=changed),
    )
    candidate = next(
        item for item in decision.comparisons if item.variant_id == "ui-cursor"
    )

    assert decision.accepted is False
    assert candidate.minimum_condition_jaccard == 0
    assert "condition_jaccard" in candidate.rejection_reasons


def test_comparison_rejects_unclassified_zero_new_full_page() -> None:
    decision = compare_bakeoff_repeats(
        _repeat(1, candidate_zero_new=True),
        _repeat(2, candidate_zero_new=True),
    )
    candidate = next(
        item for item in decision.comparisons if item.variant_id == "ui-cursor"
    )

    assert decision.accepted is False
    assert "unclassified_zero_new_full_page" in candidate.rejection_reasons


def test_comparison_allows_classified_zero_new_restart_replay() -> None:
    decision = compare_bakeoff_repeats(
        _repeat(1, candidate_zero_new=True, candidate_restart_index=1),
        _repeat(2, candidate_zero_new=True, candidate_restart_index=1),
    )
    candidate = next(
        item for item in decision.comparisons if item.variant_id == "ui-cursor"
    )

    assert decision.accepted is True
    assert candidate.accepted is True
    assert "unclassified_zero_new_full_page" not in candidate.rejection_reasons


def test_comparison_rejects_condition_without_confirmed_exhaustion() -> None:
    decision = compare_bakeoff_repeats(
        _repeat(1, candidate_incomplete=True),
        _repeat(2, candidate_incomplete=True),
    )
    candidate = next(
        item for item in decision.comparisons if item.variant_id == "ui-cursor"
    )

    assert decision.accepted is False
    assert "unresolved_gap" in candidate.rejection_reasons


def test_comparison_rejects_repeat_or_seed_mismatch() -> None:
    with pytest.raises(ValueError, match="repeat indices"):
        compare_bakeoff_repeats(_repeat(1), _repeat(1))
    with pytest.raises(ValueError, match="order seed"):
        compare_bakeoff_repeats(_repeat(1), _repeat(2, order_seed=7))


@pytest.mark.parametrize(
    ("summary_field", "rejection_reason"),
    (
        ("cursor_violations", "cursor_violation"),
        ("unresolved_gaps", "unresolved_gap"),
        ("identity_issues", "identity_issue"),
        ("identity_conflicts", "identity_conflict"),
        ("conservation_difference", "conservation_difference"),
        ("unclassified_failures", "unclassified_failure"),
        ("zero_new_full_pages", "unclassified_zero_new_full_page"),
    ),
)
def test_comparison_rejects_each_integrity_gate(
    summary_field: str,
    rejection_reason: str,
) -> None:
    first = pagination_bakeoff_to_payload(_repeat(1))
    second = pagination_bakeoff_to_payload(_repeat(2))
    candidate = next(
        item
        for item in first["variant_summaries"]
        if item["variant_id"] == "ui-cursor"
    )
    candidate[summary_field] = 1

    decision = compare_bakeoff_payloads(first, second)
    comparison = next(
        item for item in decision.comparisons if item.variant_id == "ui-cursor"
    )

    assert decision.accepted is False
    assert rejection_reason in comparison.rejection_reasons


def test_comparison_rejects_both_frozen_duplicate_reduction_gates() -> None:
    first = pagination_bakeoff_to_payload(_repeat(1))
    second = pagination_bakeoff_to_payload(_repeat(2))
    for payload in (first, second):
        candidate = next(
            item
            for item in payload["variant_summaries"]
            if item["variant_id"] == "ui-cursor"
        )
        candidate["duplicate_rows"] = 14

    decision = compare_bakeoff_payloads(first, second)
    comparison = next(
        item for item in decision.comparisons if item.variant_id == "ui-cursor"
    )

    assert decision.accepted is False
    assert "duplicate_absolute_reduction" in comparison.rejection_reasons
    assert "duplicate_relative_reduction" in comparison.rejection_reasons


def test_comparison_rejects_union_below_control() -> None:
    first = pagination_bakeoff_to_payload(_repeat(1))
    second = pagination_bakeoff_to_payload(_repeat(2))
    for payload in (first, second):
        candidate = next(
            item
            for item in payload["variant_summaries"]
            if item["variant_id"] == "ui-cursor"
        )
        candidate["distinct_all_ids"] = ["candidate-only-one"]

    decision = compare_bakeoff_payloads(first, second)
    comparison = next(
        item for item in decision.comparisons if item.variant_id == "ui-cursor"
    )

    assert decision.accepted is False
    assert "distinct_union_below_control" in comparison.rejection_reasons


def test_comparison_rejects_request_cost_above_twice_control() -> None:
    first = pagination_bakeoff_to_payload(_repeat(1))
    second = pagination_bakeoff_to_payload(_repeat(2))
    for payload in (first, second):
        candidate = next(
            item
            for item in payload["variant_summaries"]
            if item["variant_id"] == "ui-cursor"
        )
        candidate["logical_pages"] = 7

    decision = compare_bakeoff_payloads(first, second)
    comparison = next(
        item for item in decision.comparisons if item.variant_id == "ui-cursor"
    )

    assert decision.accepted is False
    assert "request_cost_above_2x" in comparison.rejection_reasons


def test_comparison_is_input_order_independent() -> None:
    first = _repeat(1)
    second = _repeat(2)

    assert compare_bakeoff_repeats(first, second) == compare_bakeoff_repeats(
        second,
        first,
    )


def test_comparison_rejects_multiple_passing_variants() -> None:
    passing_variants = ("ui-cursor", "ui-cursor-same-browser")

    decision = compare_bakeoff_repeats(
        _repeat(1, passing_variant_ids=passing_variants),
        _repeat(2, passing_variant_ids=passing_variants),
    )

    assert decision.accepted is False
    assert decision.selected_variant_id is None
    assert [item.variant_id for item in decision.comparisons if item.accepted] == [
        "ui-cursor",
        "ui-cursor-same-browser",
    ]


def test_comparison_returns_no_candidate_when_every_variant_is_rejected() -> None:
    decision = compare_bakeoff_repeats(
        _repeat(1, passing_variant_ids=()),
        _repeat(2, passing_variant_ids=()),
    )

    assert decision.accepted is False
    assert decision.selected_variant_id is None
    assert not any(item.accepted for item in decision.comparisons)


@pytest.mark.parametrize(
    "failure_reason",
    (
        "secret exception message",
        "hard_stop:auth_expired",
        "unexpected_pagination_bakeoff_error:Runtime Error",
    ),
)
def test_failed_repeat_rejects_unbounded_or_mismatched_failure_reasons(
    failure_reason: str,
) -> None:
    with pytest.raises(ValueError, match="failure reason"):
        replace(_repeat(1), failure_reason=failure_reason)
