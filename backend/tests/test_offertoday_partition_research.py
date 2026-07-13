from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from scripts.generate_offertoday_category_catalog import _normalize_node
from app.scraper.offertoday.category_registry import (
    OFFERTODAY_CATEGORIES_L1,
    iter_offertoday_category_nodes,
    iter_offertoday_leaf_categories,
    offertoday_category_catalog_hash,
)
from app.sources.offertoday.listing_contract import offertoday_endpoint_contract
from app.sources.offertoday.research.partition_research import (
    ENDPOINT_PROBE_EXPERIMENT,
    HIGH_VALUE_PARTITION_OVERRIDES_V1,
    OFFERTODAY_PARTITION_CATALOG,
    PARTITION_COMPARISON_EXPERIMENT,
    PARTITION_CONTRIBUTION_THRESHOLD,
    PARTITION_PROBE_EXPERIMENT,
    EndpointProbePlan,
    HighValuePartitionOverride,
    OfferTodayPartitionDefinition,
    PartitionProbePlan,
    PhaseCConditionEvidence,
    PhaseCPageEvidence,
    PhaseCProbeExecution,
    PhaseCRequestBudget,
    build_endpoint_probe_plan,
    build_partition_probe_plan,
    canonical_phase_c_hash,
    compare_partition_conditions,
    comparison_payload,
    offertoday_partition,
    offertoday_partition_catalog_hash,
    phase_c_probe_execution_from_payload,
    partition_probe_policy_hash,
    request_policy_for_contract,
    top_level_partition,
    validate_comparison_payload,
)


SEARCH_CONTRACT_ID = "recommend-search-list-v1"
BROWSE_CONTRACT_ID = "recommend-list-envelope-v1"
CATEGORY_CATALOG_HASH = (
    "933ed9121f4ba07e257079d060be687a8e4913e587c8185dd824695ea4a8d104"
)
PARTITION_CATALOG_HASH = (
    "1cdac415ea498646598e7210b0aa26fee3490ac296aad85f79a40e1371acecb2"
)
ENDPOINT_PLAN_HASH = (
    "67776bbeb333740a6837e4f3ab50c4894fd6db733ca4ba60af789edd3fc6236f"
)


def _request_id(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _page(
    *,
    label: str,
    page: int,
    job_ids: tuple[str, ...] = (),
    reported_total: int | None = None,
    terminal_signal: bool = False,
) -> PhaseCPageEvidence:
    return PhaseCPageEvidence(
        page=page,
        attempt=1,
        classification="success",
        stop_reason="natural_exhaustion" if terminal_signal else None,
        logical_request_id=_request_id(f"logical:{label}:{page}"),
        physical_attempt_id=_request_id(f"physical:{label}:{page}"),
        result_job_ids=job_ids,
        supplemental_job_ids=(),
        terminal_signal=terminal_signal,
        awaiting_empty_confirmation=False,
        contract_error=None,
        reported_total=reported_total,
    )


def _condition(
    partition_index: int,
    *,
    job_ids: tuple[str, ...],
    endpoint_contract_id: str = SEARCH_CONTRACT_ID,
    complete: bool = True,
    contract_verified: bool = True,
    terminal_confirmed: bool = True,
    empty_confirmation: bool = True,
    gap_count: int = 0,
    identity_conflict_count: int = 0,
    identity_issue_count: int = 0,
    conservation_difference: int = 0,
    reported_total: int | None = None,
    page_count: int = 1,
) -> PhaseCConditionEvidence:
    partition = OFFERTODAY_PARTITION_CATALOG[partition_index]
    contract = offertoday_endpoint_contract(endpoint_contract_id)
    pages = tuple(
        _page(
            label=f"{partition_index}:{index}",
            page=index,
            job_ids=(job_ids if index == 1 else ()),
            reported_total=reported_total,
            terminal_signal=(empty_confirmation and index == page_count),
        )
        for index in range(1, page_count + 1)
    )
    return PhaseCConditionEvidence(
        partition_id=partition.partition_id,
        endpoint_contract_id=endpoint_contract_id,
        endpoint_contract_hash=contract.contract_hash,
        condition_id=_request_id(f"condition:{partition_index}"),
        stop_reason="natural_exhaustion" if complete else "page_cap",
        is_complete=complete,
        contract_verified=contract_verified,
        terminal_confirmed=terminal_confirmed,
        empty_confirmation=empty_confirmation,
        gap_count=gap_count,
        identity_conflict_count=identity_conflict_count,
        identity_issue_count=identity_issue_count,
        conservation_difference=conservation_difference,
        pages=pages,
    )


def test_official_category_and_partition_catalogs_are_frozen() -> None:
    nodes = tuple(iter_offertoday_category_nodes())
    leaves = tuple(iter_offertoday_leaf_categories())
    aliases = tuple(
        child
        for root in OFFERTODAY_CATEGORIES_L1
        for child in root.children
        if child.code == root.code
    )

    assert len(OFFERTODAY_CATEGORIES_L1) == 31
    assert len(nodes) == 493
    assert sum(len(root.children) for root in OFFERTODAY_CATEGORIES_L1) == 462
    assert len(aliases) == 31
    assert len(leaves) == 431
    assert offertoday_category_catalog_hash() == CATEGORY_CATALOG_HASH

    assert len(OFFERTODAY_PARTITION_CATALOG) == 31 + 431
    assert [item.category_code for item in OFFERTODAY_PARTITION_CATALOG[:31]] == [
        item.code for item in OFFERTODAY_CATEGORIES_L1
    ]
    assert [item.category_code for item in OFFERTODAY_PARTITION_CATALOG[31:]] == [
        item.code for item in leaves
    ]
    assert not {item.code for item in aliases} - {
        item.category_code for item in OFFERTODAY_PARTITION_CATALOG[:31]
    }
    assert len({item.category_code for item in OFFERTODAY_PARTITION_CATALOG}) == 462
    assert offertoday_partition_catalog_hash() == PARTITION_CATALOG_HASH


def test_catalog_generator_normalizes_the_anomalous_root_without_changing_children() -> (
    None
):
    normalized = _normalize_node(
        {
            "code": "999000",
            "name": "Other",
            "parentCode": "999000",
            "level": "1",
            "children": [
                {
                    "code": "999999",
                    "name": "Other",
                    "parentCode": "999000",
                    "level": "2",
                }
            ],
        },
        root=True,
    )

    assert normalized == {
        "code": 999000,
        "name": "Other",
        "parent_code": 0,
        "level": 1,
        "children": [
            {
                "code": 999999,
                "name": "Other",
                "parent_code": 999000,
                "level": 2,
                "children": [],
            }
        ],
    }


def test_partition_identity_round_trips_and_rejects_alias_shape() -> None:
    partition = OFFERTODAY_PARTITION_CATALOG[-1]
    assert OfferTodayPartitionDefinition.from_payload(partition.to_payload()) == partition
    assert offertoday_partition(partition.partition_id) == partition

    with pytest.raises(ValueError, match="same-code aliases"):
        OfferTodayPartitionDefinition(
            schema_version=1,
            kind="leaf_category",
            category_code=118000,
            name="All Information Technology",
            parent_code=118000,
            level=2,
        )

    tampered = partition.to_payload()
    tampered["query_filters"] = {"jobFunctionCodes": [118000]}
    with pytest.raises(ValueError, match="query filters"):
        OfferTodayPartitionDefinition.from_payload(tampered)


@pytest.mark.parametrize("invalid", (True, 1.0, "1", None))
def test_phase_c_budget_rejects_nonexact_integers(invalid: object) -> None:
    with pytest.raises(ValueError, match="listing_logical"):
        PhaseCRequestBudget(listing_logical=invalid, listing_attempt_max=3)  # type: ignore[arg-type]


def test_endpoint_probe_plan_has_exact_frozen_contracts_and_budget() -> None:
    plan = build_endpoint_probe_plan()

    assert isinstance(plan, EndpointProbePlan)
    assert plan.contract_ids == (SEARCH_CONTRACT_ID, BROWSE_CONTRACT_ID)
    assert plan.budget == PhaseCRequestBudget(
        listing_logical=6,
        listing_attempt_max=18,
        detail=0,
        product_writes=0,
    )
    assert plan.plan_hash == ENDPOINT_PLAN_HASH
    assert EndpointProbePlan.from_payload(plan.to_payload()) == plan
    assert plan.to_payload()["rcd_type"] is None


def test_phase_c_request_policy_is_explicit_and_keeps_rcd_type_omitted() -> None:
    search = request_policy_for_contract(SEARCH_CONTRACT_ID)
    browse = request_policy_for_contract(BROWSE_CONTRACT_ID)

    assert search.endpoint_contract_id == SEARCH_CONTRACT_ID
    assert search.pagination_mode == "response-cursor"
    assert browse.endpoint_contract_id == BROWSE_CONTRACT_ID
    assert browse.pagination_mode == "stateless-control"
    assert search.requested_page_size == browse.requested_page_size == 10


@pytest.mark.parametrize("max_pages", (0, 11, True, 1.0, "1"))
def test_partition_probe_plan_rejects_out_of_range_page_budgets(
    max_pages: object,
) -> None:
    with pytest.raises(ValueError, match="range 1..10"):
        build_partition_probe_plan(
            endpoint_contract_id=SEARCH_CONTRACT_ID,
            partition_ids=(OFFERTODAY_PARTITION_CATALOG[0].partition_id,),
            max_pages_per_condition=max_pages,  # type: ignore[arg-type]
        )


def test_partition_probe_plan_requires_explicit_distinct_bounded_inputs() -> None:
    first = OFFERTODAY_PARTITION_CATALOG[0].partition_id
    second = OFFERTODAY_PARTITION_CATALOG[1].partition_id
    plan = build_partition_probe_plan(
        endpoint_contract_id=SEARCH_CONTRACT_ID,
        partition_ids=(second, first),
        max_pages_per_condition=10,
    )

    assert isinstance(plan, PartitionProbePlan)
    assert plan.partition_ids == (first, second)
    assert plan.budget == PhaseCRequestBudget(
        listing_logical=20,
        listing_attempt_max=60,
        detail=0,
        product_writes=0,
    )
    assert PartitionProbePlan.from_payload(plan.to_payload()) == plan
    assert len(partition_probe_policy_hash(plan)) == 64

    with pytest.raises(ValueError, match="explicit and distinct"):
        build_partition_probe_plan(
            endpoint_contract_id=SEARCH_CONTRACT_ID,
            partition_ids=(first, first),
            max_pages_per_condition=1,
        )
    with pytest.raises(ValueError, match="between 1 and 31"):
        build_partition_probe_plan(
            endpoint_contract_id=SEARCH_CONTRACT_ID,
            partition_ids=(),
            max_pages_per_condition=1,
        )
    with pytest.raises(ValueError, match="between 1 and 31"):
        build_partition_probe_plan(
            endpoint_contract_id=SEARCH_CONTRACT_ID,
            partition_ids=tuple(item.partition_id for item in OFFERTODAY_PARTITION_CATALOG[:32]),
            max_pages_per_condition=1,
        )
    with pytest.raises(ValueError, match="unknown OfferToday partition"):
        build_partition_probe_plan(
            endpoint_contract_id=SEARCH_CONTRACT_ID,
            partition_ids=("f" * 64,),
            max_pages_per_condition=1,
        )


def test_probe_execution_round_trips_rejected_or_partial_evidence() -> None:
    plan = build_endpoint_probe_plan()
    search = _condition(17, job_ids=("1",), page_count=2)
    browse = _condition(
        17,
        job_ids=("2",),
        endpoint_contract_id=BROWSE_CONTRACT_ID,
        complete=False,
        contract_verified=False,
        terminal_confirmed=False,
        empty_confirmation=False,
    )
    execution = PhaseCProbeExecution(
        experiment=ENDPOINT_PROBE_EXPERIMENT,
        plan=plan,
        conditions=(search, browse),
    )

    assert execution.accepted is False
    assert execution.logical_requests == 3
    assert execution.physical_attempts == 3
    assert execution.to_payload()["candidate_frozen"] is False
    assert phase_c_probe_execution_from_payload(execution.to_payload()) == execution

    partial = PhaseCProbeExecution(
        experiment=ENDPOINT_PROBE_EXPERIMENT,
        plan=plan,
        conditions=(search,),
        failure_reason="hard_stop:auth_expired",
    )
    assert phase_c_probe_execution_from_payload(partial.to_payload()) == partial


def test_probe_execution_rejects_condition_order_and_budget_overrun() -> None:
    partitions = tuple(item.partition_id for item in OFFERTODAY_PARTITION_CATALOG[:2])
    plan = build_partition_probe_plan(
        endpoint_contract_id=SEARCH_CONTRACT_ID,
        partition_ids=partitions,
        max_pages_per_condition=1,
    )
    first = _condition(0, job_ids=("1",))
    second = _condition(1, job_ids=("2",))

    with pytest.raises(ValueError, match="execution order"):
        PhaseCProbeExecution(
            experiment=PARTITION_PROBE_EXPERIMENT,
            plan=plan,
            conditions=(second, first),
        )
    with pytest.raises(ValueError, match="logical request budget exceeded"):
        PhaseCProbeExecution(
            experiment=PARTITION_PROBE_EXPERIMENT,
            plan=plan,
            conditions=(
                replace(
                    first,
                    pages=(
                        *first.pages,
                        _page(label="extra", page=2, job_ids=("3",)),
                    ),
                ),
                second,
            ),
        )


def test_partition_comparison_retains_exact_point_five_percent_contribution() -> None:
    first_ids = tuple(str(index) for index in range(1, 200))
    conditions = (
        _condition(0, job_ids=first_ids, page_count=2),
        _condition(1, job_ids=("200",), page_count=2),
    )

    comparison = compare_partition_conditions(conditions)

    second = comparison.contributions[1]
    assert PARTITION_CONTRIBUTION_THRESHOLD == 0.005
    assert second.contribution_ratio == 1 / 200
    assert second.retained is True
    assert second.rejection_reasons == ()
    assert second.logical_request_cost_per_unique_id == 2.0
    assert second.physical_attempt_cost_per_unique_id == 2.0
    assert comparison.accepted is True
    assert comparison.to_payload()["candidate_frozen"] is False


def test_partition_comparison_rejects_below_threshold_without_override() -> None:
    conditions = (
        _condition(0, job_ids=tuple(str(index) for index in range(1, 201)), page_count=2),
        _condition(1, job_ids=("201",), page_count=2),
    )

    comparison = compare_partition_conditions(conditions)

    second = comparison.contributions[1]
    assert second.contribution_ratio == 1 / 201
    assert second.retained is False
    assert "insufficient_unique_contribution" in second.rejection_reasons
    assert HIGH_VALUE_PARTITION_OVERRIDES_V1 == ()


def test_high_value_override_only_bypasses_numeric_gate() -> None:
    conditions = (
        _condition(0, job_ids=tuple(str(index) for index in range(1, 201)), page_count=2),
        _condition(1, job_ids=("201",), page_count=2),
        _condition(
            2,
            job_ids=("202",),
            complete=False,
            terminal_confirmed=False,
            empty_confirmation=False,
        ),
    )
    numeric_override = HighValuePartitionOverride(
        partition_id=conditions[1].partition_id,
        rationale="Code-reviewed high-value coverage exception.",
    )
    hard_gate_override = HighValuePartitionOverride(
        partition_id=conditions[2].partition_id,
        rationale="Does not waive terminal evidence.",
    )

    comparison = compare_partition_conditions(
        conditions,
        high_value_overrides=(numeric_override, hard_gate_override),
    )

    assert comparison.contributions[1].retained is True
    assert comparison.contributions[2].retained is False
    assert "terminal_not_confirmed" in comparison.contributions[2].rejection_reasons
    with pytest.raises(ValueError, match="nonblank"):
        HighValuePartitionOverride(
            partition_id=conditions[1].partition_id,
            rationale="",
        )


def test_total_and_last_100_saturation_are_diagnostic_only() -> None:
    condition = _condition(
        0,
        job_ids=tuple(str(index) for index in range(100)),
        complete=False,
        terminal_confirmed=False,
        empty_confirmation=False,
        reported_total=10_000_000,
        page_count=100,
    )

    contribution = compare_partition_conditions((condition,)).contributions[0]

    assert contribution.last_100_new_ids == 100
    assert contribution.last_100_ratio == 1.0
    assert contribution.retained is False
    assert "terminal_not_confirmed" in contribution.rejection_reasons
    assert "missing_empty_confirmation" in contribution.rejection_reasons
    assert all(page.reported_total == 10_000_000 for page in condition.pages)


@pytest.mark.parametrize(
    ("changes", "reason"),
    (
        ({"gap_count": 1}, "unresolved_gap"),
        ({"identity_conflict_count": 1}, "identity_conflict"),
        ({"identity_issue_count": 1}, "identity_issue"),
        ({"conservation_difference": 1}, "conservation_difference"),
    ),
)
def test_partition_comparison_hard_gates_are_independent(
    changes: dict[str, int],
    reason: str,
) -> None:
    condition = replace(
        _condition(0, job_ids=("1",), page_count=2),
        **changes,
    )

    contribution = compare_partition_conditions((condition,)).contributions[0]

    assert contribution.retained is False
    assert reason in contribution.rejection_reasons


def test_comparison_payload_replays_metrics_and_rejects_semantic_tampering() -> None:
    conditions = (
        _condition(0, job_ids=("1", "2"), page_count=2),
        _condition(1, job_ids=("2", "3"), page_count=2),
    )
    payload = comparison_payload(conditions)

    decision = validate_comparison_payload(payload)

    assert payload["experiment"] == PARTITION_COMPARISON_EXPERIMENT
    assert payload["partition_catalog_hash"] == PARTITION_CATALOG_HASH
    assert payload["input_set_hash"] == canonical_phase_c_hash(payload["inputs"])
    assert decision.reference_union_ids == ("1", "2", "3")
    assert decision.contributions[1].overlap_ids == ("2",)

    tampered = comparison_payload(conditions)
    tampered["decision"]["accepted"] = False
    with pytest.raises(ValueError, match="decision does not replay"):
        validate_comparison_payload(tampered)


def test_top_level_partition_requires_an_official_root() -> None:
    assert top_level_partition(118000).category_code == 118000
    with pytest.raises(ValueError, match="unknown OfferToday top-level"):
        top_level_partition(118001)
