from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from uuid import UUID

import pytest

from app.scraper.offertoday.category_registry import (
    OFFERTODAY_CATEGORIES_L1,
    OFFERTODAY_CATEGORY_CATALOG_VERSION,
    offertoday_category_catalog_hash,
)
from app.sources.offertoday.listing_contract import (
    OfferTodayListingCursorEvidence,
    OfferTodayListingCursorFieldPresence,
    OfferTodayListingPageEvidenceV2,
    offertoday_endpoint_contract,
)
from app.sources.offertoday.research.live_contracts import (
    DiscoveryPolicyCandidateV2,
)
from app.sources.offertoday.research.phase_d import (
    PHASE_D_CENSUS_EXPERIMENT,
    PHASE_D_FIXED_REPEAT_EXPERIMENT,
    PhaseDConditionEvidence,
    PhaseDPageAttempt,
    PhaseDPageCursorEvidence,
    PhaseDProductEvidence,
    PhaseDRunEvidence,
    PhaseDStagingEvidence,
    build_discovery_policy_candidate_v2,
    compare_phase_d_runs,
    discovery_policy_candidate_artifact_payload,
    phase_d_comparison_payload,
    phase_d_run_artifact_payload,
    validate_discovery_policy_candidate_artifact_payload,
    validate_phase_d_comparison_payload,
    validate_phase_d_run_artifact_payload,
)
from app.sources.offertoday.research.partition_research import (
    PhaseCConditionEvidence,
    PhaseCPageEvidence,
    comparison_payload,
    offertoday_partition_catalog_hash,
    phase_c_request_policy_hash,
    top_level_partition,
)
from app.sources.offertoday.research.partition_stage_gate import (
    PhaseCBaselineReference,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def _candidate(**overrides) -> DiscoveryPolicyCandidateV2:
    contract = offertoday_endpoint_contract("recommend-search-list-v1")
    phase_d_partitions = tuple(
        top_level_partition(category.code)
        for category in OFFERTODAY_CATEGORIES_L1
    )
    values = {
        "candidate_version": 2,
        "endpoint_contract_id": contract.contract_id,
        "endpoint_contract_hash": contract.contract_hash,
        "endpoint": contract.endpoint,
        "rcd_type": None,
        "category_catalog_version": OFFERTODAY_CATEGORY_CATALOG_VERSION,
        "category_catalog_hash": offertoday_category_catalog_hash(),
        "partition_catalog_hash": offertoday_partition_catalog_hash(),
        "phase_d_partitions": phase_d_partitions,
        "retained_partition_ids": tuple(
            partition.partition_id for partition in phase_d_partitions[:2]
        ),
        "retained_condition_hashes": (SHA_A, SHA_B),
        "pagination_mode": "response-cursor",
        "requested_page_size": 10,
        "browser_lifecycle": "condition-local-runtime",
        "request_policy_hash": phase_c_request_policy_hash(contract.contract_id),
        "terminal_policy": "cursor-terminal-empty-confirmation-v1",
        "max_pages_per_condition": 500,
        "require_empty_confirmation": True,
        "max_attempts_per_page": 3,
        "retry_delays_seconds": (5.0, 15.0),
        "page_delay_range_seconds": (3.0, 5.0),
        "session_mode": "saved-session",
        "fixed_repeat_category_ids": (118000, 112000, 127000),
        "phase_b_comparison_artifact_hash": SHA_B,
        "phase_c_comparison_artifact_hash": SHA_C,
        "source_artifact_hash": SHA_D,
        "deferred_issue_ids": (4, 5),
    }
    values.update(overrides)
    return DiscoveryPolicyCandidateV2(**values)


def _phase_c_condition(
    category_code: int,
    job_id: str,
    *,
    terminal_confirmed: bool = True,
) -> PhaseCConditionEvidence:
    contract = offertoday_endpoint_contract("recommend-search-list-v1")
    partition = top_level_partition(category_code)
    pages = (
        PhaseCPageEvidence(
            page=1,
            attempt=1,
            classification="success",
            stop_reason=None,
            logical_request_id=hashlib.sha256(
                f"logical:{category_code}:1".encode()
            ).hexdigest(),
            physical_attempt_id=hashlib.sha256(
                f"physical:{category_code}:1".encode()
            ).hexdigest(),
            result_job_ids=(job_id,),
            supplemental_job_ids=(),
            terminal_signal=True,
            awaiting_empty_confirmation=True,
            contract_error=None,
            reported_total=1,
        ),
        PhaseCPageEvidence(
            page=2,
            attempt=1,
            classification="success",
            stop_reason=(
                "natural_exhaustion" if terminal_confirmed else "page_cap"
            ),
            logical_request_id=hashlib.sha256(
                f"logical:{category_code}:2".encode()
            ).hexdigest(),
            physical_attempt_id=hashlib.sha256(
                f"physical:{category_code}:2".encode()
            ).hexdigest(),
            result_job_ids=(),
            supplemental_job_ids=(),
            terminal_signal=terminal_confirmed,
            awaiting_empty_confirmation=terminal_confirmed,
            contract_error=None,
            reported_total=1,
        ),
    )
    return PhaseCConditionEvidence(
        partition_id=partition.partition_id,
        endpoint_contract_id=contract.contract_id,
        endpoint_contract_hash=contract.contract_hash,
        condition_id=hashlib.sha256(
            f"condition:{category_code}".encode()
        ).hexdigest(),
        stop_reason="natural_exhaustion" if terminal_confirmed else "page_cap",
        is_complete=terminal_confirmed,
        contract_verified=True,
        terminal_confirmed=terminal_confirmed,
        empty_confirmation=terminal_confirmed,
        gap_count=0,
        identity_conflict_count=0,
        identity_issue_count=0,
        conservation_difference=0,
        pages=pages,
    )


def _phase_c_comparison_payload(*, accepted: bool = True) -> dict:
    first_code, second_code = (
        category.code for category in OFFERTODAY_CATEGORIES_L1[:2]
    )
    conditions = (
        _phase_c_condition(first_code, "101", terminal_confirmed=accepted),
        _phase_c_condition(second_code, "202", terminal_confirmed=accepted),
    )
    return comparison_payload(conditions)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _cursor(label: str) -> OfferTodayListingCursorEvidence:
    return OfferTodayListingCursorEvidence(
        cursor_hash=_hash(f"cursor:{label}"),
        session_id_hash=_hash("phase-d-session"),
        supple_page=1,
        supple_amount=0,
        supple_type=0,
        effective_page_size=10,
    )


def _page_attempt(
    *,
    category_id: int,
    page: int,
    cursor_input: OfferTodayListingCursorEvidence | None,
    cursor_output: OfferTodayListingCursorEvidence,
    result_job_ids: tuple[str, ...],
    new_job_id_count: int,
    terminal_signal: bool,
    awaiting_empty_confirmation: bool,
    stop_reason: str | None = None,
    session_continuity: str = "continued",
) -> PhaseDPageAttempt:
    condition_id = _hash(f"condition:{category_id}")
    result_row_count = len(result_job_ids)
    return PhaseDPageAttempt(
        condition_id=condition_id,
        category_id=category_id,
        page=page,
        attempt=1,
        request_fingerprint=_hash(f"request:{category_id}:{page}"),
        classification="success",
        retry_reason=None,
        stop_reason=stop_reason,
        cursor_evidence=PhaseDPageCursorEvidence.from_listing_page_evidence(
            OfferTodayListingPageEvidenceV2(
                protocol_version=2,
            variant_id="phase-c:recommend-search-list-v1",
            repeat_index=1,
            condition_restart_index=0,
            condition_execution_id=_hash(f"execution:{category_id}"),
            logical_request_id=_hash(f"logical:{category_id}:{page}"),
            physical_attempt_id=_hash(f"physical:{category_id}:{page}"),
            browser_context_hash=_hash(f"browser:{category_id}"),
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
                "initial" if cursor_input is None else session_continuity
            ),
            result_row_count=result_row_count,
            supplemental_row_count=0,
            result_job_ids=result_job_ids,
            supplemental_job_ids=(),
            result_identity_pairs=(),
            supplemental_identity_pairs=(),
            cohort_overlap_job_ids=(),
            new_job_id_count=new_job_id_count,
            duplicate_job_id_count=max(0, result_row_count - new_job_id_count),
            zero_new_full_page=(result_row_count >= 10 and new_job_id_count == 0),
            terminal_signal=terminal_signal,
            awaiting_empty_confirmation=awaiting_empty_confirmation,
                contract_error=None,
            )
        ),
    )


def _phase_d_condition(
    category_id: int,
    *,
    job_ids: tuple[str, ...] | None = None,
    include_zero_new_full_page: bool = False,
    classify_zero_new_full_page: bool = True,
) -> PhaseDConditionEvidence:
    contract = offertoday_endpoint_contract("recommend-search-list-v1")
    first_ids = job_ids or (str(category_id),)
    cursor_1 = _cursor(f"{category_id}:1")
    cursor_2 = _cursor(f"{category_id}:2")
    cursor_3 = _cursor(f"{category_id}:3")
    if include_zero_new_full_page:
        middle_ids = tuple(first_ids[0] for _ in range(10))
        if not classify_zero_new_full_page:
            cursor_2 = cursor_1
    else:
        middle_ids = ()
    pages = (
        _page_attempt(
            category_id=category_id,
            page=1,
            cursor_input=None,
            cursor_output=cursor_1,
            result_job_ids=first_ids,
            new_job_id_count=len(set(first_ids)),
            terminal_signal=False,
            awaiting_empty_confirmation=False,
        ),
        _page_attempt(
            category_id=category_id,
            page=2,
            cursor_input=cursor_1,
            cursor_output=cursor_2,
            result_job_ids=middle_ids,
            new_job_id_count=0,
            terminal_signal=True,
            awaiting_empty_confirmation=True,
        ),
        _page_attempt(
            category_id=category_id,
            page=3,
            cursor_input=cursor_2,
            cursor_output=cursor_3,
            result_job_ids=(),
            new_job_id_count=0,
            terminal_signal=True,
            awaiting_empty_confirmation=True,
            stop_reason="natural_exhaustion",
        ),
    )
    return PhaseDConditionEvidence(
        partition_id=top_level_partition(category_id).partition_id,
        endpoint_contract_id=contract.contract_id,
        endpoint_contract_hash=contract.contract_hash,
        category_id=category_id,
        condition_id=_hash(f"condition:{category_id}"),
        stop_reason="natural_exhaustion",
        is_complete=True,
        gap_count=0,
        identity_conflict_count=0,
        identity_issue_count=0,
        conservation_difference=0,
        pages=pages,
    )


def _phase_d_run(
    *,
    experiment: str,
    run_index: int,
    captured_at: str,
    window_id: str,
    uuid_int: int,
    extra_first_condition_ids: tuple[str, ...] = (),
) -> PhaseDRunEvidence:
    category_ids = (
        tuple(category.code for category in OFFERTODAY_CATEGORIES_L1)
        if experiment == PHASE_D_CENSUS_EXPERIMENT
        else (118000, 112000, 127000)
    )
    conditions = tuple(
        _phase_d_condition(
            category_id,
            job_ids=(
                (str(category_id), *extra_first_condition_ids)
                if index == 0
                else (str(category_id),)
            ),
        )
        for index, category_id in enumerate(category_ids)
    )
    return PhaseDRunEvidence(
        experiment=experiment,
        run_id=str(UUID(int=uuid_int)),
        run_index=run_index,
        window_id=window_id,
        captured_at=captured_at,
        candidate_hash=SHA_A,
        candidate_artifact_hash=SHA_B,
        duration_seconds=60.0,
        conditions=conditions,
        detail_attempts=0,
        product_writes=0,
        jobs_unchanged=True,
        companies_unchanged=True,
        staging_conservation_difference=0,
        unclassified_failures=0,
    )


def _phase_d_runs():
    censuses = (
        _phase_d_run(
            experiment=PHASE_D_CENSUS_EXPERIMENT,
            run_index=1,
            captured_at="2026-07-13T00:00:00+00:00",
            window_id="census-window-a",
            uuid_int=101,
            extra_first_condition_ids=("only-run-1",),
        ),
        _phase_d_run(
            experiment=PHASE_D_CENSUS_EXPERIMENT,
            run_index=2,
            captured_at="2026-07-13T00:30:00+00:00",
            window_id="census-window-a",
            uuid_int=102,
            extra_first_condition_ids=("seen-twice",),
        ),
        _phase_d_run(
            experiment=PHASE_D_CENSUS_EXPERIMENT,
            run_index=3,
            captured_at="2026-07-13T07:00:00+00:00",
            window_id="census-window-b",
            uuid_int=103,
            extra_first_condition_ids=("seen-twice",),
        ),
    )
    fixed = tuple(
        _phase_d_run(
            experiment=PHASE_D_FIXED_REPEAT_EXPERIMENT,
            run_index=index,
            captured_at=f"2026-07-13T08:{(index - 1) * 10:02d}:00+00:00",
            window_id="fixed-window-a",
            uuid_int=200 + index,
        )
        for index in (1, 2, 3)
    )
    return censuses, fixed


def _product_evidence() -> PhaseDProductEvidence:
    return PhaseDProductEvidence(
        start_snapshot_hash=SHA_A,
        end_snapshot_hash=SHA_A,
        start_inventory_hash=SHA_B,
        end_inventory_hash=SHA_B,
        start_staged_rows_hash=SHA_A,
        end_staged_rows_hash=SHA_A,
        start_published_jobs_hash=SHA_B,
        end_published_jobs_hash=SHA_B,
        start_companies_hash=SHA_C,
        end_companies_hash=SHA_C,
        start_product_data_hash=SHA_D,
        end_product_data_hash=SHA_D,
        detail_attempts=0,
        product_writes=0,
        staging=PhaseDStagingEvidence(
            staging_mode="noop",
            rows_seen=0,
            rows_created=0,
            published_source_job_ids=(),
            preexisting_staged_source_job_ids=(),
            created_source_job_ids=(),
            deferred_identity_conflict_ids=(),
            would_stage_rows=93,
            stage_calls=93,
        ),
    )


def _baseline_reference() -> PhaseCBaselineReference:
    return PhaseCBaselineReference(
        artifact_hashes=(SHA_C, SHA_D),
        run_ids=(str(UUID(int=501)), str(UUID(int=502))),
        snapshot_hash=SHA_A,
        inventory_hash=SHA_B,
    )


def test_discovery_policy_candidate_v2_round_trips_canonical_payload() -> None:
    candidate = _candidate()

    payload = candidate.to_payload()
    canonical_payload = dict(payload)
    canonical_payload.pop("candidate_hash")
    expected_hash = hashlib.sha256(
        json.dumps(
            canonical_payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    assert payload["candidate_hash"] == expected_hash
    assert len(payload["phase_d_partitions"]) == 31
    assert payload["deferred_issue_ids"] == [4, 5]
    assert DiscoveryPolicyCandidateV2.from_payload(payload) == candidate


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("candidate_version", True, "candidate_version"),
        ("endpoint", "browse", "endpoint does not match"),
        ("pagination_mode", "stateless-control", "pagination_mode"),
        ("requested_page_size", 50, "requested_page_size"),
        ("browser_lifecycle", "shared-variant-runtime", "browser_lifecycle"),
        ("max_pages_per_condition", 10, "max_pages_per_condition"),
        ("require_empty_confirmation", False, "require_empty_confirmation"),
        ("session_mode", "fresh-headless", "session_mode"),
        ("fixed_repeat_category_ids", (118000,), "fixed_repeat_category_ids"),
        ("deferred_issue_ids", (), "deferred_issue_ids"),
    ],
)
def test_discovery_policy_candidate_v2_rejects_unfrozen_controls(
    field_name: str,
    value,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _candidate(**{field_name: value})


def test_discovery_policy_candidate_v2_requires_all_top_level_partitions() -> None:
    with pytest.raises(ValueError, match="all top-level partitions"):
        _candidate(phase_d_partitions=_candidate().phase_d_partitions[:-1])


def test_discovery_policy_candidate_v2_requires_retained_catalog_order() -> None:
    candidate = _candidate()

    with pytest.raises(ValueError, match="catalog order"):
        _candidate(
            retained_partition_ids=tuple(reversed(candidate.retained_partition_ids)),
            retained_condition_hashes=tuple(
                reversed(candidate.retained_condition_hashes)
            ),
        )


def test_discovery_policy_candidate_v2_rejects_unverified_endpoint() -> None:
    browse = offertoday_endpoint_contract("recommend-list-envelope-v1")

    with pytest.raises(ValueError, match="verified cursor/terminal"):
        _candidate(
            endpoint_contract_id=browse.contract_id,
            endpoint_contract_hash=browse.contract_hash,
            endpoint=browse.endpoint,
            request_policy_hash=phase_c_request_policy_hash(browse.contract_id),
        )


def test_discovery_policy_candidate_v2_rejects_hash_and_shape_tampering() -> None:
    payload = _candidate().to_payload()
    payload["candidate_hash"] = "f" * 64

    with pytest.raises(ValueError, match="candidate_hash"):
        DiscoveryPolicyCandidateV2.from_payload(payload)

    payload = _candidate().to_payload()
    payload["unexpected"] = True
    with pytest.raises(ValueError, match="fields do not match"):
        DiscoveryPolicyCandidateV2.from_payload(payload)


def test_build_discovery_policy_candidate_v2_from_phase_c_decision() -> None:
    comparison = _phase_c_comparison_payload()

    candidate = build_discovery_policy_candidate_v2(
        comparison_payload=comparison,
        endpoint_contract_id="recommend-search-list-v1",
        phase_b_comparison_artifact_hash=SHA_B,
        phase_c_comparison_artifact_hash=SHA_C,
    )

    assert candidate.retained_partition_ids == tuple(
        top_level_partition(category.code).partition_id
        for category in OFFERTODAY_CATEGORIES_L1[:2]
    )
    assert len(candidate.phase_d_partitions) == 31
    assert candidate.phase_b_comparison_artifact_hash == SHA_B
    assert candidate.phase_c_comparison_artifact_hash == SHA_C


def test_build_discovery_policy_candidate_v2_rejects_phase_c_rejection() -> None:
    with pytest.raises(ValueError, match="did not retain"):
        build_discovery_policy_candidate_v2(
            comparison_payload=_phase_c_comparison_payload(accepted=False),
            endpoint_contract_id="recommend-search-list-v1",
            phase_b_comparison_artifact_hash=SHA_B,
            phase_c_comparison_artifact_hash=SHA_C,
        )


def test_discovery_policy_candidate_artifact_round_trip_and_tamper() -> None:
    candidate = _candidate()
    payload = discovery_policy_candidate_artifact_payload(candidate)

    assert validate_discovery_policy_candidate_artifact_payload(payload) == candidate

    payload["source_artifact_hash"] = SHA_A
    with pytest.raises(ValueError, match="does not replay"):
        validate_discovery_policy_candidate_artifact_payload(payload)


def test_phase_d_condition_classifies_replayable_zero_new_full_page() -> None:
    condition = _phase_d_condition(
        118000,
        include_zero_new_full_page=True,
    )

    assert condition.accepted is True
    assert condition.cursor_confirmed_exhaustion is True
    assert condition.unclassified_zero_new_full_pages == 0
    assert [item.classification for item in condition.zero_new_full_pages] == [
        "recommendation-repeat-with-cursor-progress-v1"
    ]
    assert PhaseDConditionEvidence.from_payload(condition.to_payload()) == condition


def test_phase_d_condition_rejects_zero_new_page_without_cursor_progress() -> None:
    condition = _phase_d_condition(
        118000,
        include_zero_new_full_page=True,
        classify_zero_new_full_page=False,
    )

    assert condition.accepted is False
    assert condition.unclassified_zero_new_full_pages == 1
    assert condition.zero_new_full_pages[0].classification is None


def test_phase_d_run_round_trips_complete_condition_cohort() -> None:
    run = _phase_d_run(
        experiment=PHASE_D_FIXED_REPEAT_EXPERIMENT,
        run_index=3,
        captured_at="2026-07-13T08:20:00+00:00",
        window_id="fixed-window-a",
        uuid_int=303,
    )

    assert run.accepted is True
    assert tuple(condition.category_id for condition in run.conditions) == (
        118000,
        112000,
        127000,
    )
    assert PhaseDRunEvidence.from_payload(run.to_payload()) == run


def test_compare_phase_d_runs_freezes_frequency_reference_and_holdouts() -> None:
    censuses, fixed = _phase_d_runs()

    comparison = compare_phase_d_runs(
        censuses,
        fixed,
        active_holdout_ids=("active-holdout",),
    )

    assert comparison.decision.accepted is True
    assert comparison.census_window_span_seconds == 25_200.0
    assert comparison.fixed_window_span_seconds == 1_200.0
    assert comparison.fixed_cohort_jaccard == 1.0
    assert "seen-twice" in comparison.stable_reference_ids
    assert "active-holdout" in comparison.stable_reference_ids
    assert "only-run-1" not in comparison.stable_reference_ids
    assert "only-run-1" in comparison.diagnostic_union_ids


def test_compare_phase_d_runs_rejects_short_census_window() -> None:
    censuses, fixed = _phase_d_runs()
    short_censuses = (
        censuses[0],
        censuses[1],
        replace(
            censuses[2],
            captured_at="2026-07-13T02:00:00+00:00",
        ),
    )

    comparison = compare_phase_d_runs(short_censuses, fixed)

    assert comparison.decision.accepted is False
    assert "census_window_separation" in comparison.decision.failing_gates


def test_phase_d_comparison_payload_replays_and_rejects_tampering() -> None:
    censuses, fixed = _phase_d_runs()
    payload = phase_d_comparison_payload(
        censuses,
        fixed,
        active_holdout_ids=("active-holdout",),
    )

    comparison = validate_phase_d_comparison_payload(payload)
    assert comparison.decision.accepted is True
    assert payload["stable_reference_frozen"] is True

    payload["comparison"]["stable_reference_ids"].append("tampered")
    payload["comparison_hash"] = hashlib.sha256(
        json.dumps(
            payload["comparison"],
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    with pytest.raises(ValueError, match="does not replay"):
        validate_phase_d_comparison_payload(payload)


def test_phase_d_product_and_staging_evidence_round_trip() -> None:
    product = _product_evidence()

    assert product.accepted is True
    assert PhaseDProductEvidence.from_payload(product.to_payload()) == product


def test_phase_d_product_evidence_preserves_missing_end_snapshot() -> None:
    product = replace(
        _product_evidence(),
        end_snapshot_hash=None,
        end_inventory_hash=None,
        end_staged_rows_hash=None,
        end_published_jobs_hash=None,
        end_companies_hash=None,
        end_product_data_hash=None,
    )
    payload = product.to_payload()

    assert payload["end_snapshot_captured"] is False
    assert payload["accepted"] is False
    assert PhaseDProductEvidence.from_payload(payload) == product
    assert PhaseDStagingEvidence.from_payload(
        product.staging.to_payload()
    ) == product.staging


def test_phase_d_run_artifact_binds_candidate_controls_and_product() -> None:
    candidate = _candidate()
    run = replace(
        _phase_d_run(
            experiment=PHASE_D_FIXED_REPEAT_EXPERIMENT,
            run_index=1,
            captured_at="2026-07-13T08:00:00+00:00",
            window_id="fixed-window-a",
            uuid_int=401,
        ),
        candidate_hash=candidate.candidate_hash,
    )
    product = _product_evidence()

    payload = phase_d_run_artifact_payload(
        run=run,
        candidate=candidate,
        baseline=_baseline_reference(),
        product=product,
    )
    replayed = validate_phase_d_run_artifact_payload(payload)

    assert replayed == (run, candidate, _baseline_reference(), product)
    assert payload["accepted"] is True


def test_phase_d_run_artifact_rejects_candidate_control_drift() -> None:
    candidate = _candidate()
    run = replace(
        _phase_d_run(
            experiment=PHASE_D_FIXED_REPEAT_EXPERIMENT,
            run_index=1,
            captured_at="2026-07-13T08:00:00+00:00",
            window_id="fixed-window-a",
            uuid_int=402,
        ),
        candidate_hash=candidate.candidate_hash,
    )
    first = run.conditions[0]
    drifted_page = replace(
        first.pages[0],
        cursor_evidence=replace(
            first.pages[0].cursor_evidence,
            variant_id="phase-d-unfrozen",
        ),
    )
    drifted_run = replace(
        run,
        conditions=(replace(first, pages=(drifted_page, *first.pages[1:])), *run.conditions[1:]),
    )

    with pytest.raises(ValueError, match="page controls"):
        phase_d_run_artifact_payload(
            run=drifted_run,
            candidate=candidate,
            baseline=_baseline_reference(),
            product=_product_evidence(),
        )
