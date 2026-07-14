from __future__ import annotations

import copy
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.scraper.offertoday.category_registry import OFFERTODAY_CATEGORIES_L1
from app.sources.offertoday.listing_contract import (
    OfferTodayListingCursorEvidence,
    OfferTodayListingCursorFieldPresence,
    OfferTodayListingPageEvidenceV2,
    offertoday_endpoint_contract,
)
from app.sources.offertoday.research.dual_cohort import (
    DUAL_COHORT_MAX_ATTEMPTS_PER_PAGE,
    DUAL_COHORT_DISCOVERY_CANDIDATE_EXPERIMENT,
    DUAL_COHORT_CENSUS_EXPERIMENT,
    DUAL_COHORT_COMPARISON_EXPERIMENT,
    DUAL_COHORT_FIXED_REPEAT_EXPERIMENT,
    DUAL_COHORT_FIXED_REPEAT_CATEGORY_IDS,
    RESULT_CONFIRMATION_PAGE_COUNT,
    RESULT_PARTITION_PROBE_EXPERIMENT,
    RESULT_PARTIAL_CENSUS_EXPERIMENT,
    RESULT_PROBE_MAX_PAGES_PER_CONDITION,
    SUPPLEMENTAL_COHORT_COMPARISON_EXPERIMENT,
    SUPPLEMENTAL_MAX_PAGES_PER_SEED,
    SUPPLEMENTAL_SEED_CATEGORY_IDS,
    SUPPLEMENTAL_SEED_PARTITION_IDS,
    ResultPartitionConditionEvidenceV2,
    ResultOnlyDiscoveryScopeV3,
    ResultPartialPhaseDRunV3,
    ResultPartitionProbeExecutionV2,
    ResultPartitionProbePlanV2,
    SupplementalCohortProbeExecutionV1,
    SupplementalCohortProbePlanV1,
    SupplementalSeedConditionEvidenceV1,
    SupplementalGateStateV1,
    DualCohortPhaseDRunV3,
    build_dual_cohort_discovery_candidate_v3,
    compare_dual_cohort_phase_d_runs_v3,
    compare_supplemental_cohort_probes_v1,
    evaluate_result_cohort_terminal,
    freeze_result_partition_policy_v1,
    dual_cohort_candidate_artifact_payload_v3,
    dual_cohort_phase_d_comparison_payload_v3,
    dual_cohort_phase_d_run_artifact_payload_v3,
    supplemental_cohort_comparison_payload_v1,
    result_partial_phase_d_artifact_payload_v3,
    validate_supplemental_cohort_comparison_payload_v1,
    validate_dual_cohort_candidate_artifact_payload_v3,
    validate_dual_cohort_phase_d_comparison_payload_v3,
    validate_dual_cohort_phase_d_run_artifact_payload_v3,
    validate_result_partial_phase_d_artifact_payload_v3,
)
from app.sources.offertoday.research.phase_d import (
    PhaseDConditionEvidence,
    PhaseDPageAttempt,
    PhaseDPageCursorEvidence,
)
from app.sources.offertoday.research.partition_research import top_level_partition
from test_offertoday_phase_d import _baseline_reference, _product_evidence


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _cursor(label: str) -> OfferTodayListingCursorEvidence:
    return OfferTodayListingCursorEvidence(
        cursor_hash=_hash(f"cursor:{label}"),
        session_id_hash=_hash("dual-cohort-session"),
        supple_page=1,
        supple_amount=0,
        supple_type=1,
        effective_page_size=10,
    )


def _page(
    *,
    category_id: int,
    page: int,
    cursor_input: OfferTodayListingCursorEvidence | None,
    cursor_output: OfferTodayListingCursorEvidence,
    result_ids: tuple[str, ...] = (),
    supplemental_ids: tuple[str, ...] = (),
    terminal_signal: bool = False,
    awaiting_empty_confirmation: bool = False,
    stop_reason: str | None = None,
    restart_index: int = 0,
    classification: str = "success",
    contract_error: str | None = None,
) -> PhaseDPageAttempt:
    condition_id = _hash(f"condition:{category_id}")
    overlap = tuple(sorted(set(result_ids) & set(supplemental_ids)))
    all_ids = (*result_ids, *supplemental_ids)
    return PhaseDPageAttempt(
        condition_id=condition_id,
        category_id=category_id,
        page=page,
        attempt=1,
        request_fingerprint=_hash(
            f"request:{category_id}:{restart_index}:{page}"
        ),
        classification=classification,
        retry_reason=None,
        stop_reason=stop_reason,
        cursor_evidence=PhaseDPageCursorEvidence.from_listing_page_evidence(
            OfferTodayListingPageEvidenceV2(
                protocol_version=2,
                variant_id="phase-c:recommend-search-list-v1",
                repeat_index=1,
                condition_restart_index=restart_index,
                condition_execution_id=_hash(
                    f"execution:{category_id}:{restart_index}"
                ),
                logical_request_id=_hash(
                    f"logical:{category_id}:{restart_index}:{page}"
                ),
                physical_attempt_id=_hash(
                    f"physical:{category_id}:{restart_index}:{page}"
                ),
                browser_context_hash=_hash(f"browser:{category_id}:{restart_index}"),
                pagination_mode="response-cursor",
                browser_lifecycle="condition-local-runtime",
                requested_page_size=10,
                response_page_size=10,
                effective_page_size=10,
                cursor_input=cursor_input,
                cursor_output=cursor_output,
                response_cursor_fields=OfferTodayListingCursorFieldPresence(
                    session_id=True,
                    supple_page=True,
                    supple_amount=True,
                    supple_type=True,
                    page_size=True,
                ),
                session_continuity=(
                    "initial" if cursor_input is None else "continued"
                ),
                result_row_count=len(result_ids),
                supplemental_row_count=len(supplemental_ids),
                result_job_ids=result_ids,
                supplemental_job_ids=supplemental_ids,
                result_identity_pairs=(),
                supplemental_identity_pairs=(),
                cohort_overlap_job_ids=overlap,
                new_job_id_count=len(set(all_ids)),
                duplicate_job_id_count=len(all_ids) - len(set(all_ids)),
                zero_new_full_page=False,
                terminal_signal=terminal_signal,
                awaiting_empty_confirmation=awaiting_empty_confirmation,
                contract_error=contract_error,
            )
        ),
    )


def _result_condition(
    category_id: int = 118000,
    *,
    result_ids: tuple[str, ...] | None = None,
    second_cursor_input: OfferTodayListingCursorEvidence | None = None,
    include_second_confirmation: bool = True,
    stop_reason: str = "result_cohort_exhaustion",
    is_complete: bool = True,
) -> PhaseDConditionEvidence:
    contract = offertoday_endpoint_contract("recommend-search-list-v1")
    first = _cursor(f"{category_id}:1")
    second = _cursor(f"{category_id}:2")
    third = _cursor(f"{category_id}:3")
    pages = [
        _page(
            category_id=category_id,
            page=1,
            cursor_input=None,
            cursor_output=first,
            result_ids=(
                (f"result-{category_id}",)
                if result_ids is None
                else result_ids
            ),
            supplemental_ids=("supplemental-overlap",),
        ),
        _page(
            category_id=category_id,
            page=2,
            cursor_input=(
                first if second_cursor_input is None else second_cursor_input
            ),
            cursor_output=second,
            supplemental_ids=("supplemental-overlap", "supplemental-a"),
        ),
    ]
    if include_second_confirmation:
        pages.append(
            _page(
                category_id=category_id,
                page=3,
                cursor_input=second,
                cursor_output=third,
                supplemental_ids=("supplemental-b",),
                stop_reason=(
                    "result_cohort_exhaustion" if is_complete else stop_reason
                ),
            )
        )
    return PhaseDConditionEvidence(
        partition_id=top_level_partition(category_id).partition_id,
        endpoint_contract_id=contract.contract_id,
        endpoint_contract_hash=contract.contract_hash,
        category_id=category_id,
        condition_id=_hash(f"condition:{category_id}"),
        stop_reason=stop_reason,
        is_complete=is_complete,
        gap_count=0,
        identity_conflict_count=0,
        identity_issue_count=0,
        conservation_difference=0,
        pages=tuple(pages),
    )


def _supplemental_condition(
    category_id: int,
    *,
    supplemental_ids: tuple[str, ...] = ("supplemental-a", "supplemental-b"),
    accepted: bool = True,
) -> PhaseDConditionEvidence:
    contract = offertoday_endpoint_contract("recommend-search-list-v1")
    first = _cursor(f"supp:{category_id}:1")
    second = _cursor(f"supp:{category_id}:2")
    third = _cursor(f"supp:{category_id}:3")
    pages = (
        _page(
            category_id=category_id,
            page=1,
            cursor_input=None,
            cursor_output=first,
            result_ids=(f"result-{category_id}",),
            supplemental_ids=supplemental_ids,
        ),
        _page(
            category_id=category_id,
            page=2,
            cursor_input=first,
            cursor_output=second,
            supplemental_ids=supplemental_ids,
            terminal_signal=True,
            awaiting_empty_confirmation=True,
        ),
        _page(
            category_id=category_id,
            page=3,
            cursor_input=second,
            cursor_output=third,
            terminal_signal=True,
            awaiting_empty_confirmation=True,
            stop_reason=("natural_exhaustion" if accepted else "page_cap"),
        ),
    )
    return PhaseDConditionEvidence(
        partition_id=top_level_partition(category_id).partition_id,
        endpoint_contract_id=contract.contract_id,
        endpoint_contract_hash=contract.contract_hash,
        category_id=category_id,
        condition_id=_hash(f"condition:{category_id}"),
        stop_reason="natural_exhaustion" if accepted else "page_cap",
        is_complete=accepted,
        gap_count=0,
        identity_conflict_count=0,
        identity_issue_count=0,
        conservation_difference=0,
        pages=pages,
    )


def _supplemental_probe(
    run_index: int,
    *,
    accepted: bool = True,
    supplemental_ids: tuple[str, ...] = ("supplemental-a", "supplemental-b"),
) -> SupplementalCohortProbeExecutionV1:
    plan = SupplementalCohortProbePlanV1(
        endpoint_contract_id="recommend-search-list-v1"
    )
    conditions = tuple(
        SupplementalSeedConditionEvidenceV1(
            seed_partition_id=top_level_partition(category_id).partition_id,
            condition=_supplemental_condition(
                category_id,
                supplemental_ids=supplemental_ids,
                accepted=accepted,
            ),
        )
        for category_id in SUPPLEMENTAL_SEED_CATEGORY_IDS
    )
    return SupplementalCohortProbeExecutionV1(
        run_id=str(UUID(int=run_index)),
        run_index=run_index,
        captured_at=(
            datetime(2026, 7, 14, tzinfo=UTC) + timedelta(minutes=run_index)
        ).isoformat(),
        plan=plan,
        conditions=conditions,
    )


def _result_policy():
    plan = ResultPartitionProbePlanV2(
        endpoint_contract_id="recommend-search-list-v1",
        partition_ids=(top_level_partition(118000).partition_id,),
    )
    execution = ResultPartitionProbeExecutionV2(
        plan=plan,
        conditions=(
            ResultPartitionConditionEvidenceV2.from_condition(
                _result_condition()
            ),
        ),
    )
    return freeze_result_partition_policy_v1(
        execution,
        source_probe_artifact_hash=_hash("result-policy-source"),
    )


def _partial_scope() -> ResultOnlyDiscoveryScopeV3:
    return ResultOnlyDiscoveryScopeV3(
        result_policy=_result_policy(),
        result_policy_artifact_hash=_hash("result-policy-artifact"),
        supplemental_gate=SupplementalGateStateV1(
            status="missing",
            artifact_hash=None,
            comparison_hash=None,
            failing_gates=("supplemental_evidence_missing",),
        ),
        phase_b_comparison_artifact_hash=_hash("phase-b-comparison"),
    )


def _complete_candidate():
    probes = tuple(_supplemental_probe(index) for index in (1, 2, 3))
    supplemental_payload = supplemental_cohort_comparison_payload_v1(probes)
    result_policy = _result_policy()
    candidate = build_dual_cohort_discovery_candidate_v3(
        result_policy=result_policy,
        result_policy_artifact_hash=_hash("result-policy-artifact"),
        supplemental_comparison_payload=supplemental_payload,
        supplemental_comparison_artifact_hash=_hash(
            "supplemental-comparison-artifact"
        ),
        phase_b_comparison_artifact_hash=_hash("phase-b-comparison"),
    )
    return candidate, result_policy, supplemental_payload


def _partial_run() -> ResultPartialPhaseDRunV3:
    scope = _partial_scope()
    conditions = tuple(
        ResultPartitionConditionEvidenceV2.from_condition(
            _result_condition(category.code)
        )
        for category in OFFERTODAY_CATEGORIES_L1
    )
    return ResultPartialPhaseDRunV3(
        experiment=RESULT_PARTIAL_CENSUS_EXPERIMENT,
        run_id=str(UUID(int=701)),
        run_index=1,
        window_id="partial-window-1",
        captured_at="2026-07-14T02:00:00+00:00",
        scope_hash=scope.scope_hash,
        duration_seconds=30.0,
        conditions=conditions,
        product=_product_evidence(),
    )


def _complete_run(
    *,
    experiment: str,
    run_index: int,
    captured_at: str,
    window_id: str,
    uuid_int: int,
    first_result_ids: tuple[str, ...] | None = None,
) -> DualCohortPhaseDRunV3:
    candidate, _, _ = _complete_candidate()
    category_ids = (
        tuple(category.code for category in OFFERTODAY_CATEGORIES_L1)
        if experiment == DUAL_COHORT_CENSUS_EXPERIMENT
        else DUAL_COHORT_FIXED_REPEAT_CATEGORY_IDS
    )
    return DualCohortPhaseDRunV3(
        experiment=experiment,
        run_id=str(UUID(int=uuid_int)),
        run_index=run_index,
        window_id=window_id,
        captured_at=captured_at,
        candidate_hash=candidate.candidate_hash,
        candidate_artifact_hash=_hash("dual-cohort-candidate-artifact"),
        duration_seconds=60.0,
        result_conditions=tuple(
            ResultPartitionConditionEvidenceV2.from_condition(
                _result_condition(
                    category_id,
                    result_ids=(first_result_ids if index == 0 else None),
                )
            )
            for index, category_id in enumerate(category_ids)
        ),
        supplemental_condition=SupplementalSeedConditionEvidenceV1(
            seed_partition_id=SUPPLEMENTAL_SEED_PARTITION_IDS[0],
            condition=_supplemental_condition(
                SUPPLEMENTAL_SEED_CATEGORY_IDS[0]
            ),
        ),
        product=_product_evidence(),
    )


def test_result_terminal_uses_two_cursor_continuous_result_empty_pages() -> None:
    condition = _result_condition()
    decision = evaluate_result_cohort_terminal(condition.pages)

    assert decision.result_exhausted is True
    assert decision.cursor_continuity_verified is True
    assert len(decision.confirmation_logical_request_ids) == (
        RESULT_CONFIRMATION_PAGE_COUNT
    )
    assert decision.result_job_ids == ("result-118000",)
    assert decision.supplemental_job_ids == (
        "supplemental-a",
        "supplemental-b",
        "supplemental-overlap",
    )
    assert ResultPartitionConditionEvidenceV2.from_condition(condition).accepted


def test_result_terminal_rejects_single_confirmation_and_page_cap() -> None:
    condition = _result_condition(
        include_second_confirmation=False,
        stop_reason="page_cap",
        is_complete=False,
    )
    value = ResultPartitionConditionEvidenceV2.from_condition(condition)

    assert value.terminal.result_exhausted is False
    assert "two_result_empty_confirmation_pages" in value.terminal.failing_gates
    assert value.accepted is False


def test_result_terminal_rejects_cursor_discontinuity() -> None:
    condition = _result_condition(second_cursor_input=_cursor("wrong-input"))
    decision = evaluate_result_cohort_terminal(condition.pages)

    assert decision.result_exhausted is False
    assert "cursor_continuity" in decision.failing_gates


def test_result_probe_round_trips_and_freezes_only_when_accepted() -> None:
    condition = ResultPartitionConditionEvidenceV2.from_condition(
        _result_condition()
    )
    plan = ResultPartitionProbePlanV2(
        endpoint_contract_id="recommend-search-list-v1",
        partition_ids=(top_level_partition(118000).partition_id,),
    )
    execution = ResultPartitionProbeExecutionV2(
        plan=plan,
        conditions=(condition,),
    )

    assert execution.accepted is True
    assert execution.to_payload()["experiment"] == RESULT_PARTITION_PROBE_EXPERIMENT
    assert ResultPartitionProbeExecutionV2.from_payload(
        execution.to_payload()
    ) == execution
    policy = freeze_result_partition_policy_v1(
        execution,
        source_probe_artifact_hash=_hash("result-probe-artifact"),
    )
    assert policy.policy_hash == policy.to_payload()["policy_hash"]

    rejected = ResultPartitionProbeExecutionV2(
        plan=plan,
        conditions=(
            ResultPartitionConditionEvidenceV2.from_condition(
                _result_condition(
                    include_second_confirmation=False,
                    stop_reason="page_cap",
                    is_complete=False,
                )
            ),
        ),
    )
    with pytest.raises(ValueError, match="accepted probe"):
        freeze_result_partition_policy_v1(
            rejected,
            source_probe_artifact_hash=_hash("rejected-result-probe"),
        )


def test_result_probe_budget_is_exact_and_not_user_widenable() -> None:
    plan = ResultPartitionProbePlanV2(
        endpoint_contract_id="recommend-search-list-v1",
        partition_ids=(top_level_partition(118000).partition_id,),
    )

    assert plan.max_pages_per_condition == RESULT_PROBE_MAX_PAGES_PER_CONDITION
    assert plan.max_attempts_per_page == DUAL_COHORT_MAX_ATTEMPTS_PER_PAGE
    with pytest.raises(ValueError, match="page budget"):
        ResultPartitionProbePlanV2(
            endpoint_contract_id="recommend-search-list-v1",
            partition_ids=plan.partition_ids,
            max_pages_per_condition=11,
        )


def test_supplemental_plan_freezes_three_seeds_and_bounded_budget() -> None:
    plan = SupplementalCohortProbePlanV1(
        endpoint_contract_id="recommend-search-list-v1"
    )

    assert plan.seed_partition_ids == SUPPLEMENTAL_SEED_PARTITION_IDS
    assert plan.max_pages_per_seed == SUPPLEMENTAL_MAX_PAGES_PER_SEED
    assert plan.listing_logical_budget == 30
    assert plan.listing_attempt_budget == 90
    with pytest.raises(ValueError, match="frozen catalog set"):
        SupplementalCohortProbePlanV1(
            endpoint_contract_id="recommend-search-list-v1",
            seed_partition_ids=tuple(reversed(SUPPLEMENTAL_SEED_PARTITION_IDS)),
        )


def test_supplemental_comparison_accepts_stable_nonempty_unique_cohort() -> None:
    probes = tuple(_supplemental_probe(index) for index in (1, 2, 3))
    comparison = compare_supplemental_cohort_probes_v1(probes)

    assert comparison.decision.accepted is True
    assert comparison.cross_seed_min_jaccard == 1.0
    assert comparison.cross_run_min_jaccard == 1.0
    assert comparison.stable_supplemental_ids == (
        "supplemental-a",
        "supplemental-b",
    )
    assert comparison.unique_contribution_ids == comparison.stable_supplemental_ids
    assert comparison.policy_hash == comparison.to_payload()["policy_hash"]

    payload = supplemental_cohort_comparison_payload_v1(probes)
    assert payload["experiment"] == SUPPLEMENTAL_COHORT_COMPARISON_EXPERIMENT
    assert payload["policy_frozen"] is True
    assert validate_supplemental_cohort_comparison_payload_v1(payload) == comparison


def test_supplemental_comparison_preserves_valid_rejection() -> None:
    probes = tuple(
        _supplemental_probe(index, accepted=False) for index in (1, 2, 3)
    )
    payload = supplemental_cohort_comparison_payload_v1(probes)
    comparison = validate_supplemental_cohort_comparison_payload_v1(payload)

    assert payload["policy_frozen"] is False
    assert comparison.decision.accepted is False
    assert "all_three_probes_accepted" in comparison.decision.failing_gates


def test_supplemental_comparison_rejects_rehashed_semantic_tampering() -> None:
    probes = tuple(_supplemental_probe(index) for index in (1, 2, 3))
    payload = supplemental_cohort_comparison_payload_v1(probes)
    tampered = copy.deepcopy(payload)
    tampered["comparison"]["stable_supplemental_ids"].append("forged")
    tampered["comparison"]["stable_supplemental_hash"] = _hash("forged-set")
    tampered["comparison_hash"] = _hash("rehashed-forged-comparison")

    with pytest.raises(ValueError, match="does not replay"):
        validate_supplemental_cohort_comparison_payload_v1(tampered)


def test_result_only_scope_is_typed_partial_and_never_downstream_eligible() -> None:
    gate = SupplementalGateStateV1(
        status="missing",
        artifact_hash=None,
        comparison_hash=None,
        failing_gates=("supplemental_evidence_missing",),
    )
    scope = ResultOnlyDiscoveryScopeV3(
        result_policy=_result_policy(),
        result_policy_artifact_hash=_hash("result-policy-artifact"),
        supplemental_gate=gate,
        phase_b_comparison_artifact_hash=_hash("phase-b-comparison"),
    )

    assert scope.to_payload()["complete_candidate"] is False
    assert scope.to_payload()["downstream_eligible"] is False
    assert ResultOnlyDiscoveryScopeV3.from_payload(scope.to_payload()) == scope
    with pytest.raises(ValueError, match="missing supplemental gate"):
        SupplementalGateStateV1(
            status="missing",
            artifact_hash=_hash("forged-parent"),
            comparison_hash=None,
            failing_gates=("supplemental_evidence_missing",),
        )


def test_dual_cohort_candidate_binds_both_policy_hashes_and_replays() -> None:
    probes = tuple(_supplemental_probe(index) for index in (1, 2, 3))
    supplemental_payload = supplemental_cohort_comparison_payload_v1(probes)
    result_policy = _result_policy()
    candidate = build_dual_cohort_discovery_candidate_v3(
        result_policy=result_policy,
        result_policy_artifact_hash=_hash("result-policy-artifact"),
        supplemental_comparison_payload=supplemental_payload,
        supplemental_comparison_artifact_hash=_hash(
            "supplemental-comparison-artifact"
        ),
        phase_b_comparison_artifact_hash=_hash("phase-b-comparison"),
    )
    payload = dual_cohort_candidate_artifact_payload_v3(
        candidate=candidate,
        result_policy=result_policy,
        supplemental_comparison_payload=supplemental_payload,
    )

    assert payload["experiment"] == DUAL_COHORT_DISCOVERY_CANDIDATE_EXPERIMENT
    assert payload["downstream_eligible"] is True
    assert candidate.result_partition_policy_hash == result_policy.policy_hash
    assert candidate.supplemental_cohort_policy_hash == (
        validate_supplemental_cohort_comparison_payload_v1(
            supplemental_payload
        ).policy_hash
    )
    assert validate_dual_cohort_candidate_artifact_payload_v3(payload) == candidate


def test_dual_cohort_candidate_rejects_unaccepted_supplemental_parent() -> None:
    probes = tuple(
        _supplemental_probe(index, accepted=False) for index in (1, 2, 3)
    )
    supplemental_payload = supplemental_cohort_comparison_payload_v1(probes)

    with pytest.raises(ValueError, match="accepted supplemental evidence"):
        build_dual_cohort_discovery_candidate_v3(
            result_policy=_result_policy(),
            result_policy_artifact_hash=_hash("result-policy-artifact"),
            supplemental_comparison_payload=supplemental_payload,
            supplemental_comparison_artifact_hash=_hash(
                "supplemental-comparison-artifact"
            ),
            phase_b_comparison_artifact_hash=_hash("phase-b-comparison"),
        )


def test_result_partial_run_is_replayable_but_complete_loader_rejects_it() -> None:
    scope = _partial_scope()
    run = _partial_run()
    payload = result_partial_phase_d_artifact_payload_v3(
        run=run,
        scope=scope,
        baseline=_baseline_reference(),
    )

    assert run.partial_research_complete is True
    assert payload["accepted"] is False
    assert payload["stable_reference_frozen"] is False
    assert payload["downstream_eligible"] is False
    assert validate_result_partial_phase_d_artifact_payload_v3(payload)[0] == run
    with pytest.raises(ValueError, match="complete dual-cohort run artifact"):
        validate_dual_cohort_phase_d_run_artifact_payload_v3(payload)


def test_complete_dual_cohort_run_binds_both_cohorts_and_replays() -> None:
    candidate, _, _ = _complete_candidate()
    run = _complete_run(
        experiment=DUAL_COHORT_CENSUS_EXPERIMENT,
        run_index=1,
        captured_at="2026-07-14T00:00:00+00:00",
        window_id="census-window-a",
        uuid_int=801,
    )
    payload = dual_cohort_phase_d_run_artifact_payload_v3(
        run=run,
        candidate=candidate,
        baseline=_baseline_reference(),
    )

    assert run.accepted is True
    assert run.result_job_ids
    assert run.supplemental_job_ids == (
        "supplemental-a",
        "supplemental-b",
    )
    assert payload["accepted"] is True
    assert payload["downstream_eligible"] is True
    assert validate_dual_cohort_phase_d_run_artifact_payload_v3(payload)[0] == run


def test_complete_dual_cohort_comparison_freezes_combined_denominator() -> None:
    censuses = (
        _complete_run(
            experiment=DUAL_COHORT_CENSUS_EXPERIMENT,
            run_index=1,
            captured_at="2026-07-14T00:00:00+00:00",
            window_id="census-window-a",
            uuid_int=811,
        ),
        _complete_run(
            experiment=DUAL_COHORT_CENSUS_EXPERIMENT,
            run_index=2,
            captured_at="2026-07-14T06:00:00+00:00",
            window_id="census-window-b",
            uuid_int=812,
        ),
        _complete_run(
            experiment=DUAL_COHORT_CENSUS_EXPERIMENT,
            run_index=3,
            captured_at="2026-07-14T06:10:00+00:00",
            window_id="census-window-b",
            uuid_int=813,
        ),
    )
    fixed = tuple(
        _complete_run(
            experiment=DUAL_COHORT_FIXED_REPEAT_EXPERIMENT,
            run_index=index,
            captured_at=f"2026-07-14T07:0{index}:00+00:00",
            window_id="fixed-window-a",
            uuid_int=820 + index,
        )
        for index in (1, 2, 3)
    )
    comparison = compare_dual_cohort_phase_d_runs_v3(censuses, fixed)
    payload = dual_cohort_phase_d_comparison_payload_v3(censuses, fixed)

    assert comparison.decision.accepted is True
    assert comparison.stable_result_ids
    assert comparison.stable_supplemental_ids == (
        "supplemental-a",
        "supplemental-b",
    )
    assert set(comparison.stable_reference_ids) == (
        set(comparison.stable_result_ids)
        | set(comparison.stable_supplemental_ids)
    )
    assert payload["experiment"] == DUAL_COHORT_COMPARISON_EXPERIMENT
    assert payload["stable_reference_frozen"] is True
    assert validate_dual_cohort_phase_d_comparison_payload_v3(payload) == comparison


def test_complete_comparison_preserves_valid_rejection_when_count_cv_exceeds_one() -> (
    None
):
    censuses = (
        _complete_run(
            experiment=DUAL_COHORT_CENSUS_EXPERIMENT,
            run_index=1,
            captured_at="2026-07-14T00:00:00+00:00",
            window_id="census-window-a",
            uuid_int=851,
        ),
        _complete_run(
            experiment=DUAL_COHORT_CENSUS_EXPERIMENT,
            run_index=2,
            captured_at="2026-07-14T06:00:00+00:00",
            window_id="census-window-b",
            uuid_int=852,
        ),
        _complete_run(
            experiment=DUAL_COHORT_CENSUS_EXPERIMENT,
            run_index=3,
            captured_at="2026-07-14T06:10:00+00:00",
            window_id="census-window-b",
            uuid_int=853,
            first_result_ids=tuple(
                f"high-variance-{index:04d}" for index in range(1_000)
            ),
        ),
    )
    fixed = tuple(
        _complete_run(
            experiment=DUAL_COHORT_FIXED_REPEAT_EXPERIMENT,
            run_index=index,
            captured_at=f"2026-07-14T07:0{index}:00+00:00",
            window_id="fixed-window-a",
            uuid_int=860 + index,
        )
        for index in (1, 2, 3)
    )

    comparison = compare_dual_cohort_phase_d_runs_v3(censuses, fixed)
    payload = dual_cohort_phase_d_comparison_payload_v3(censuses, fixed)

    assert comparison.combined_unique_count_cv > 1.0
    assert comparison.decision.accepted is False
    assert "combined_unique_count_cv" in comparison.decision.failing_gates
    assert payload["stable_reference_frozen"] is False
    assert validate_dual_cohort_phase_d_comparison_payload_v3(payload) == comparison


def test_complete_comparison_rejects_partial_parent_type() -> None:
    partial = _partial_run()
    with pytest.raises(ValueError, match="census parent experiment"):
        compare_dual_cohort_phase_d_runs_v3(
            (partial, partial, partial),  # type: ignore[arg-type]
            (partial, partial, partial),  # type: ignore[arg-type]
        )


def test_complete_comparison_rejects_rehashed_denominator_tamper() -> None:
    censuses = tuple(
        _complete_run(
            experiment=DUAL_COHORT_CENSUS_EXPERIMENT,
            run_index=index,
            captured_at=(
                "2026-07-14T00:00:00+00:00"
                if index == 1
                else f"2026-07-14T06:0{index}:00+00:00"
            ),
            window_id=("census-window-a" if index == 1 else "census-window-b"),
            uuid_int=830 + index,
        )
        for index in (1, 2, 3)
    )
    fixed = tuple(
        _complete_run(
            experiment=DUAL_COHORT_FIXED_REPEAT_EXPERIMENT,
            run_index=index,
            captured_at=f"2026-07-14T07:0{index}:00+00:00",
            window_id="fixed-window-a",
            uuid_int=840 + index,
        )
        for index in (1, 2, 3)
    )
    payload = dual_cohort_phase_d_comparison_payload_v3(censuses, fixed)
    tampered = copy.deepcopy(payload)
    tampered["comparison"]["stable_reference_ids"].append("forged")
    tampered["comparison"]["stable_reference_hash"] = _hash("forged")
    tampered["comparison_hash"] = _hash("rehashed")

    with pytest.raises(ValueError, match="does not replay"):
        validate_dual_cohort_phase_d_comparison_payload_v3(tampered)
