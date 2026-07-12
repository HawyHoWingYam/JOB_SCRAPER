from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
import scripts.offertoday_research_census as census_cli
from app.services.offertoday_research_staging_service import (
    OfferTodayReconciledListingStagingSink,
    OfferTodayStagingReconciliation,
)
from app.sources.offertoday.listing_runner import (
    ListingConditionOutcome,
    ListingPageObservation,
    ListingRowEvidence,
    ListingRunResult,
    OfferTodayIdentityPair,
    listing_observation_to_payload,
)
from app.sources.offertoday.research.artifacts import (
    ArtifactVerificationResult,
    ResearchProvenance,
    export_research_artifact,
    verify_research_artifact,
)
from app.sources.offertoday.research.baseline import (
    build_baseline_snapshot,
    build_run_start_inventory,
)
from app.sources.offertoday.research.calibration import (
    BoundedConditionResult,
    build_calibration_conditions,
    build_pilot_conditions,
    evaluate_bounded_condition,
    select_calibration_variants,
    summarize_calibration_variants,
)
from app.sources.offertoday.research.contracts import (
    ProductDataSnapshot,
    StagedListingSnapshot,
)
from app.sources.offertoday.research.live_contracts import (
    CensusCandidate,
    DetailSmokeObservation,
    DetailSmokeTarget,
    LiveSmokeExecution,
)
from app.sources.offertoday.research.smoke import (
    build_runtime_smoke_condition,
    evaluate_smoke,
)

RUN_ID = "33333333-3333-3333-3333-333333333333"
CANDIDATE_RUN_ID = "44444444-4444-4444-4444-444444444444"
BASELINE_RUN_1 = "11111111-1111-1111-1111-111111111111"
BASELINE_RUN_2 = "22222222-2222-2222-2222-222222222222"
CURRENT_SMOKE_BUDGET = {"listing": 2, "detail": 20}
CALIBRATION_BUDGET = {
    "listing_logical": 24,
    "listing_attempt_max": 72,
    "detail": 0,
}
PILOT_BUDGET = {
    "listing_logical": 93,
    "listing_attempt_max": 279,
    "detail": 0,
}
CENSUS_BUDGET = {
    "listing_logical": 15500,
    "listing_attempt_max": 46500,
    "detail": 0,
}


def provenance(**kwargs) -> ResearchProvenance:
    return ResearchProvenance(
        commit_sha="fixture-sha",
        working_tree_patch="",
        source_hashes={},
        compose_file_hashes={},
        captured_at=kwargs.get("captured_at", "2026-07-11T00:00:00+00:00"),
        runtime_context=kwargs.get("runtime_context", {}),
        untracked_file_hashes={},
        excluded_tracked_file_hashes={},
        excluded_untracked_file_hashes={},
    )


def baseline_artifact(
    root: Path,
    run_id: str,
    *,
    listings: list[StagedListingSnapshot] | None = None,
) -> Path:
    baseline_listings = listings or []
    snapshot = build_baseline_snapshot(
        listings=baseline_listings,
        jobs=[],
        product_data=ProductDataSnapshot.from_table_hashes(
            staged_rows_hash="a" * 64,
            published_jobs_hash="b" * 64,
            companies_hash="c" * 64,
        ),
    )
    inventory = build_run_start_inventory(listings=baseline_listings, jobs=[])
    return export_research_artifact(
        root=root,
        run_id=run_id,
        metadata={
            "experiment": "foundation-baseline",
            "data_hash": snapshot.data_hash,
        },
        events=[
            {
                "sequence_no": 1,
                "event_type": "research.baseline",
                "payload": {
                    "snapshot": asdict(snapshot),
                    "run_start_inventory": inventory.to_dict(),
                },
            }
        ],
        provenance=provenance(),
    )


def accepted_smoke_artifact(
    root: Path,
    *,
    request_budget: dict[str, int] | None = None,
    smoke_passed: bool = True,
) -> Path:
    smoke_execution = execution()
    events: list[dict] = [
        {
            "sequence_no": 1,
            "event_type": "research.run_started",
            "payload": {
                "experiment": "runtime-smoke",
                "parent_artifact_hash": "c" * 64,
                "request_budget": dict(request_budget or CURRENT_SMOKE_BUDGET),
                "session_mode": "fresh-headless",
            },
        }
    ]
    events.extend(
        {
            "sequence_no": len(events) + 1,
            "event_type": "research.page_attempt",
            "payload": listing_observation_to_payload(observation),
        }
        for observation in smoke_execution.listing_result.observations
    )
    events.append(
        {
            "sequence_no": len(events) + 1,
            "event_type": "research.detail_cohort_frozen",
            "payload": {
                "count": len(smoke_execution.frozen_targets),
                "targets": [
                    target.to_payload() for target in smoke_execution.frozen_targets
                ],
            },
        }
    )
    events.extend(
        {
            "sequence_no": len(events) + 1,
            "event_type": "research.detail_attempt",
            "payload": item.to_payload(),
        }
        for item in smoke_execution.detail_observations
    )
    summary = {
        "status": "completed" if smoke_passed else "failed",
        "smoke_passed": smoke_passed,
        "listing_complete": False,
        "expected_truncation": True,
        "listing_attempt_count": len(smoke_execution.listing_result.observations),
        "attempted_count": len(smoke_execution.detail_observations),
        "frozen_count": len(smoke_execution.frozen_targets),
        "success_count": smoke_execution.decision.success_count,
        "terminal_count": smoke_execution.decision.terminal_count,
        "unattempted_count": smoke_execution.decision.unattempted_count,
        "missing_encrypted_job_id_count": 0,
        "job_id_fallback_count": 0,
        "listing_stop_reason": smoke_execution.listing_result.stop_reason,
        "stop_reason": None if smoke_passed else "fixture_failure",
        "request_budget": dict(request_budget or CURRENT_SMOKE_BUDGET),
        "product_data_unchanged": True,
        "run_start_snapshot_hash": "d" * 64,
        "run_end_snapshot_hash": "d" * 64,
        "run_start_product_data_hash": "f" * 64,
        "run_end_product_data_hash": "f" * 64,
        "run_start_inventory_hash": "e" * 64,
        "run_end_inventory_hash": "e" * 64,
    }
    events.append(
        {
            "sequence_no": len(events) + 1,
            "event_type": "research.run_summary",
            "payload": summary,
        }
    )
    return export_research_artifact(
        root=root,
        run_id=RUN_ID,
        metadata={
            "experiment": "runtime-smoke",
            "crawl_job_id": RUN_ID,
            "crawl_job_status": "completed" if smoke_passed else "failed",
            "parent_artifact_hash": "c" * 64,
            "request_budget": dict(request_budget or CURRENT_SMOKE_BUDGET),
            "smoke_passed": smoke_passed,
        },
        events=events,
        provenance=provenance(),
    )


def listing_result(count: int = 20) -> ListingRunResult:
    condition = build_runtime_smoke_condition()
    pairs = tuple(
        OfferTodayIdentityPair(f"j{index}", f"e{index}", "encryptJobId")
        for index in range(1, count + 1)
    )
    rows = tuple(
        ListingRowEvidence(
            job_id=pair.job_id,
            encrypted_job_id=pair.encrypted_job_id,
            encrypted_job_id_source=pair.encrypted_job_id_source,
            observed_encrypted_job_id=pair.encrypted_job_id,
            title=f"Title {pair.job_id}",
            job_function_codes=("118000",),
            title_language="en",
            api_language="zh_HK",
        )
        for pair in pairs
    )
    if count < CURRENT_SMOKE_BUDGET["detail"]:
        split_at = (count + 1) // 2
        page_evidence = (
            (pairs[:split_at], rows[:split_at]),
            (pairs[split_at:], rows[split_at:]),
        )
        listing_stop_reason = "page_cap"
    else:
        page_evidence = ((pairs, rows),)
        listing_stop_reason = "target_cap"
    observations = tuple(
        ListingPageObservation(
            condition_id=condition.condition_id,
            search_family=condition.search_family,
            category_id=condition.category_id,
            keyword=condition.keyword,
            endpoint=condition.endpoint,
            rcd_type=condition.rcd_type,
            page=page,
            attempt=1,
            request_fingerprint=("d" if page == 1 else "e") * 64,
            classification="success",
            api_code=0,
            reported_total=100,
            has_more=True,
            row_count=len(page_rows),
            missing_job_id_count=0,
            missing_encrypted_job_id_count=0,
            job_id_fallback_count=0,
            id_pairs=page_pairs,
            rows=page_rows,
            identity_issues=(),
            identity_conflicts=(),
            latency_ms=50,
            session_mode="fresh-headless",
            retry_reason=None,
            stop_reason=(listing_stop_reason if page == len(page_evidence) else None),
        )
        for page, (page_pairs, page_rows) in enumerate(page_evidence, start=1)
    )
    return ListingRunResult(
        ordered_job_ids=tuple(item.job_id for item in pairs),
        accepted_job_ids=tuple(item.job_id for item in pairs),
        id_pairs=pairs,
        observations=observations,
        condition_outcomes=(),
        identity_conflicts=(),
        identity_issues=(),
        gaps=(),
        stop_reason=listing_stop_reason,
        is_complete=False,
    )


def execution(
    *,
    detail_classification: str = "success",
    target_count: int = 20,
    listing_stop_reason: str | None = None,
) -> LiveSmokeExecution:
    result = listing_result(target_count)
    if listing_stop_reason is not None:
        hard_stop_observation = replace(
            result.observations[0],
            classification=listing_stop_reason,
            api_code=(1002 if listing_stop_reason == "auth_expired" else None),
            reported_total=None,
            has_more=None,
            row_count=0,
            missing_job_id_count=0,
            missing_encrypted_job_id_count=0,
            job_id_fallback_count=0,
            id_pairs=(),
            rows=(),
            identity_issues=(),
            identity_conflicts=(),
            retry_reason=None,
            stop_reason=listing_stop_reason,
        )
        result = replace(
            result,
            ordered_job_ids=(),
            accepted_job_ids=(),
            id_pairs=(),
            observations=(hard_stop_observation,),
            stop_reason=listing_stop_reason,
        )
        targets: tuple[DetailSmokeTarget, ...] = ()
    else:
        targets = tuple(
            DetailSmokeTarget(index, f"j{index}", f"e{index}")
            for index in range(1, target_count + 1)
        )
    if target_count < 20 or listing_stop_reason is not None:
        observations: tuple[DetailSmokeObservation, ...] = ()
    else:
        attempted_targets = (
            targets if detail_classification == "success" else targets[:1]
        )
        observations = tuple(
            DetailSmokeObservation(
                target=item,
                classification=detail_classification,
                api_code=(1002 if detail_classification == "auth_expired" else 0),
                started_at="2026-07-11T00:00:00+00:00",
                completed_at="2026-07-11T00:00:01+00:00",
                latency_ms=1000,
                identity_valid=detail_classification == "success",
                parsed=detail_classification == "success",
                has_title=detail_classification == "success",
                has_company=detail_classification == "success",
                has_description=detail_classification == "success",
                stop_batch=detail_classification != "success",
            )
            for item in attempted_targets
        )
    decision = evaluate_smoke(
        listing_result=result,
        frozen_targets=targets,
        observations=observations,
    )
    return LiveSmokeExecution(
        listing_result=result,
        frozen_targets=targets,
        detail_observations=observations,
        decision=decision,
        would_stage_rows=0,
        stage_calls=0,
    )


def calibration_result(
    condition,
    *,
    hard_stop: str | None = None,
) -> BoundedConditionResult:
    route = "none" if condition.rcd_type is None else str(condition.rcd_type)
    job_ids = tuple(
        f"{condition.category_id}-{condition.endpoint}-{route}-j{page}"
        for page in range(1, 4)
    )
    pairs = tuple(
        OfferTodayIdentityPair(job_id, job_id, "jobId_fallback") for job_id in job_ids
    )
    if hard_stop is None:
        observations = tuple(
            ListingPageObservation(
                condition_id=condition.condition_id,
                search_family=condition.search_family,
                category_id=condition.category_id,
                keyword=condition.keyword,
                endpoint=condition.endpoint,
                rcd_type=condition.rcd_type,
                page=page,
                attempt=1,
                request_fingerprint=f"{page:064x}",
                classification="success",
                api_code=0,
                reported_total=100,
                has_more=True,
                row_count=1,
                missing_job_id_count=0,
                missing_encrypted_job_id_count=1,
                job_id_fallback_count=1,
                id_pairs=(pairs[page - 1],),
                rows=(),
                identity_issues=(),
                identity_conflicts=(),
                latency_ms=page * 10,
                session_mode="fresh-headless",
                retry_reason=None,
                stop_reason=("page_cap" if page == 3 else None),
            )
            for page in range(1, 4)
        )
        pages_observed = 3
        stop_reason = "page_cap"
        accepted_job_ids = job_ids
        result_pairs = pairs
    else:
        observations = (
            ListingPageObservation(
                condition_id=condition.condition_id,
                search_family=condition.search_family,
                category_id=condition.category_id,
                keyword=condition.keyword,
                endpoint=condition.endpoint,
                rcd_type=condition.rcd_type,
                page=1,
                attempt=1,
                request_fingerprint="f" * 64,
                classification=hard_stop,
                api_code=1002 if hard_stop == "auth_expired" else None,
                reported_total=None,
                has_more=None,
                row_count=0,
                missing_job_id_count=0,
                missing_encrypted_job_id_count=0,
                job_id_fallback_count=0,
                id_pairs=(),
                rows=(),
                identity_issues=(),
                identity_conflicts=(),
                latency_ms=10,
                session_mode="fresh-headless",
                retry_reason=None,
                stop_reason=hard_stop,
            ),
        )
        pages_observed = 0
        stop_reason = hard_stop
        accepted_job_ids = ()
        result_pairs = ()
    listing = ListingRunResult(
        ordered_job_ids=accepted_job_ids,
        accepted_job_ids=accepted_job_ids,
        id_pairs=result_pairs,
        observations=observations,
        condition_outcomes=(
            ListingConditionOutcome(
                condition=condition,
                pages_observed=pages_observed,
                stop_reason=stop_reason,
                is_complete=False,
            ),
        ),
        identity_conflicts=(),
        identity_issues=(),
        gaps=(),
        stop_reason=stop_reason,
        is_complete=False,
    )
    return evaluate_bounded_condition(
        condition,
        listing,
        planned_page_limit=3,
    )


def calibration_results() -> tuple[BoundedConditionResult, ...]:
    return tuple(
        calibration_result(condition) for condition in build_calibration_conditions()
    )


def pilot_results() -> tuple[BoundedConditionResult, ...]:
    return tuple(
        calibration_result(condition)
        for condition in build_pilot_conditions("search", None)
    )


def full_census_result() -> ListingRunResult:
    conditions = build_pilot_conditions("search", None)
    observations: list[ListingPageObservation] = []
    outcomes: list[ListingConditionOutcome] = []
    pairs: list[OfferTodayIdentityPair] = []
    for condition in conditions:
        job_id = f"census-{condition.category_id}"
        pair = OfferTodayIdentityPair(job_id, job_id, "jobId_fallback")
        row = ListingRowEvidence(
            job_id=job_id,
            encrypted_job_id=job_id,
            encrypted_job_id_source="jobId_fallback",
            observed_encrypted_job_id=None,
            title=f"Title {job_id}",
            job_function_codes=(str(condition.category_id),),
            title_language="en",
            api_language="zh_HK",
        )
        observations.extend(
            (
                ListingPageObservation(
                    condition_id=condition.condition_id,
                    search_family=condition.search_family,
                    category_id=condition.category_id,
                    keyword=condition.keyword,
                    endpoint=condition.endpoint,
                    rcd_type=condition.rcd_type,
                    page=1,
                    attempt=1,
                    request_fingerprint=hashlib.sha256(
                        f"{condition.condition_id}:1".encode()
                    ).hexdigest(),
                    classification="success",
                    api_code=0,
                    reported_total=1,
                    has_more=False,
                    row_count=1,
                    missing_job_id_count=0,
                    missing_encrypted_job_id_count=1,
                    job_id_fallback_count=1,
                    id_pairs=(pair,),
                    rows=(row,),
                    identity_issues=(),
                    identity_conflicts=(),
                    latency_ms=10,
                    session_mode="fresh-headless",
                    retry_reason=None,
                    stop_reason=None,
                ),
                ListingPageObservation(
                    condition_id=condition.condition_id,
                    search_family=condition.search_family,
                    category_id=condition.category_id,
                    keyword=condition.keyword,
                    endpoint=condition.endpoint,
                    rcd_type=condition.rcd_type,
                    page=2,
                    attempt=1,
                    request_fingerprint=hashlib.sha256(
                        f"{condition.condition_id}:2".encode()
                    ).hexdigest(),
                    classification="success",
                    api_code=0,
                    reported_total=1,
                    has_more=False,
                    row_count=0,
                    missing_job_id_count=0,
                    missing_encrypted_job_id_count=0,
                    job_id_fallback_count=0,
                    id_pairs=(),
                    rows=(),
                    identity_issues=(),
                    identity_conflicts=(),
                    latency_ms=5,
                    session_mode="fresh-headless",
                    retry_reason=None,
                    stop_reason="natural_exhaustion",
                ),
            )
        )
        outcomes.append(
            ListingConditionOutcome(
                condition=condition,
                pages_observed=2,
                stop_reason="natural_exhaustion",
                is_complete=True,
            )
        )
        pairs.append(pair)
    ordered_job_ids = tuple(pair.job_id for pair in pairs)
    return ListingRunResult(
        ordered_job_ids=ordered_job_ids,
        accepted_job_ids=ordered_job_ids,
        id_pairs=tuple(pairs),
        observations=tuple(observations),
        condition_outcomes=tuple(outcomes),
        identity_conflicts=(),
        identity_issues=(),
        gaps=(),
        stop_reason="natural_exhaustion",
        is_complete=True,
    )


def page_cap_census_result() -> ListingRunResult:
    completed = full_census_result()
    first_condition_pages = completed.observations[:2]
    second_page_template = completed.observations[2]
    second_condition_pages = tuple(
        replace(
            second_page_template,
            page=page,
            request_fingerprint=hashlib.sha256(
                f"{second_page_template.condition_id}:{page}".encode()
            ).hexdigest(),
            has_more=True,
            stop_reason="page_cap" if page == 500 else None,
        )
        for page in range(1, 501)
    )
    second_outcome = replace(
        completed.condition_outcomes[1],
        pages_observed=500,
        stop_reason="page_cap",
        is_complete=False,
    )
    accepted_ids = completed.accepted_job_ids[:2]
    return replace(
        completed,
        ordered_job_ids=accepted_ids,
        accepted_job_ids=accepted_ids,
        id_pairs=completed.id_pairs[:2],
        observations=(*first_condition_pages, *second_condition_pages),
        condition_outcomes=(completed.condition_outcomes[0], second_outcome),
        stop_reason="page_cap",
        is_complete=False,
    )


def one_condition_census_result() -> ListingRunResult:
    completed = full_census_result()
    accepted_ids = completed.accepted_job_ids[:1]
    return replace(
        completed,
        ordered_job_ids=accepted_ids,
        accepted_job_ids=accepted_ids,
        id_pairs=completed.id_pairs[:1],
        observations=completed.observations[:2],
        condition_outcomes=completed.condition_outcomes[:1],
        stop_reason="condition_incomplete",
        is_complete=False,
    )


def ordered_id_hash(values) -> str:
    canonical = json.dumps(
        list(dict.fromkeys(values)),
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


@pytest.mark.parametrize(
    ("gate", "expected_reason"),
    (
        ("gap", "unresolved_gaps"),
        ("identity_issue", "identity_issue"),
        ("identity_conflict", "identity_conflict"),
        ("deferred_conflict", "identity_conflict"),
        ("conservation", "conservation_difference"),
        ("amplification", "staging_amplification"),
    ),
)
def test_full_census_analysis_reports_the_exact_failing_gate(
    gate,
    expected_reason,
) -> None:
    result = full_census_result()
    reconciliation = CensusStagingSink(result).reconciliation
    if gate == "gap":
        result = replace(result, gaps=(SimpleNamespace(),))
    elif gate == "identity_issue":
        result = replace(result, identity_issues=(SimpleNamespace(),))
    elif gate == "identity_conflict":
        result = replace(result, identity_conflicts=(SimpleNamespace(),))
    elif gate == "deferred_conflict":
        reconciliation = replace(
            reconciliation,
            deferred_identity_conflict_ids=(result.accepted_job_ids[0],),
        )
    elif gate == "conservation":
        reconciliation = replace(
            reconciliation,
            published_source_job_ids=result.accepted_job_ids[1:],
        )
    elif gate == "amplification":
        reconciliation = replace(
            reconciliation,
            rows_created=2,
            published_source_job_ids=result.accepted_job_ids[1:],
            created_source_job_ids=(result.accepted_job_ids[0],),
        )

    analysis = census_cli._analyze_census(
        result=result,
        conditions=build_pilot_conditions("search", None),
        events_before_summary=[],
        reconciliation=reconciliation,
    )

    assert analysis["accepted"] is False
    assert analysis["failure_reason"] == expected_reason


def naturally_exhausted_calibration_result(
    condition,
    *,
    pages_observed: int = 2,
) -> BoundedConditionResult:
    bounded = calibration_result(condition)
    observations = bounded.listing_result.observations[:pages_observed]
    observations = (
        *observations[:-1],
        replace(
            observations[-1],
            has_more=False,
            stop_reason="natural_exhaustion",
        ),
    )
    outcome = ListingConditionOutcome(
        condition=condition,
        pages_observed=pages_observed,
        stop_reason="natural_exhaustion",
        is_complete=True,
    )
    accepted_ids = bounded.listing_result.accepted_job_ids[:pages_observed]
    listing = replace(
        bounded.listing_result,
        ordered_job_ids=accepted_ids,
        accepted_job_ids=accepted_ids,
        id_pairs=bounded.listing_result.id_pairs[:pages_observed],
        observations=observations,
        condition_outcomes=(outcome,),
        stop_reason="natural_exhaustion",
        is_complete=True,
    )
    return evaluate_bounded_condition(
        condition,
        listing,
        planned_page_limit=3,
    )


def _summary_state():
    product_data = ProductDataSnapshot.from_table_hashes(
        staged_rows_hash="a" * 64,
        published_jobs_hash="b" * 64,
        companies_hash="c" * 64,
    )
    snapshot = build_baseline_snapshot(
        listings=[],
        jobs=[],
        product_data=product_data,
    )
    inventory = build_run_start_inventory(listings=[], jobs=[])
    return snapshot, inventory


def test_build_summary_uses_execution_listing_identity_counts() -> None:
    run = execution()
    page = replace(
        run.listing_result.observations[0],
        missing_encrypted_job_id_count=20,
        job_id_fallback_count=20,
    )
    run = replace(
        run,
        listing_result=replace(run.listing_result, observations=(page,)),
    )
    snapshot, inventory = _summary_state()

    summary = census_cli._build_summary(
        status="completed",
        start_snapshot=snapshot,
        start_inventory=inventory,
        end_snapshot=snapshot,
        end_inventory=inventory,
        execution=run,
        events_before_summary=[],
        failure_reason=None,
        request_budget=CURRENT_SMOKE_BUDGET,
    )

    assert summary["missing_encrypted_job_id_count"] == 20
    assert summary["job_id_fallback_count"] == 20


def test_build_summary_preserves_persisted_page_counts_after_unexpected_error() -> None:
    snapshot, inventory = _summary_state()
    events = [
        {
            "event_type": "research.page_attempt",
            "payload": {
                "missing_encrypted_job_id_count": 4,
                "job_id_fallback_count": 3,
            },
        }
    ]

    summary = census_cli._build_summary(
        status="failed",
        start_snapshot=snapshot,
        start_inventory=inventory,
        end_snapshot=snapshot,
        end_inventory=inventory,
        execution=None,
        events_before_summary=events,
        failure_reason="unexpected_live_smoke_error:RuntimeError",
        request_budget=CURRENT_SMOKE_BUDGET,
    )

    assert summary["missing_encrypted_job_id_count"] == 4
    assert summary["job_id_fallback_count"] == 3


def test_build_summary_records_zero_identity_counts_before_listing() -> None:
    snapshot, inventory = _summary_state()

    summary = census_cli._build_summary(
        status="failed",
        start_snapshot=snapshot,
        start_inventory=inventory,
        end_snapshot=snapshot,
        end_inventory=inventory,
        execution=None,
        events_before_summary=[],
        failure_reason="unexpected_live_smoke_error:RuntimeError",
        request_budget=CURRENT_SMOKE_BUDGET,
    )

    assert summary["missing_encrypted_job_id_count"] == 0
    assert summary["job_id_fallback_count"] == 0


def test_build_summary_stores_a_request_budget_copy() -> None:
    snapshot, inventory = _summary_state()
    request_budget = dict(CURRENT_SMOKE_BUDGET)

    summary = census_cli._build_summary(
        status="failed",
        start_snapshot=snapshot,
        start_inventory=inventory,
        end_snapshot=snapshot,
        end_inventory=inventory,
        execution=None,
        events_before_summary=[],
        failure_reason="unexpected_live_smoke_error:RuntimeError",
        request_budget=request_budget,
    )
    request_budget["listing"] = 99

    assert summary["request_budget"] == CURRENT_SMOKE_BUDGET


class FakeSession:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.closed = False

    def close(self) -> None:
        self.log.append("db_close")
        self.closed = True


class FakeRepository:
    def __init__(
        self,
        state,
        *,
        drift: bool = False,
        product_drift: bool = False,
        end_snapshot_error: BaseException | None = None,
        event_load_errors: list[BaseException] | None = None,
    ) -> None:
        self.state = state
        self.drift = drift
        self.product_drift = product_drift
        self.end_snapshot_error = end_snapshot_error
        self.event_load_errors = list(event_load_errors or [])
        self.staged_reads = 0
        self.product_reads = 0

    def list_staged_snapshots(self, db):
        self.staged_reads += 1
        self.state.log.append(f"staged_snapshot_{self.staged_reads}")
        if self.end_snapshot_error is not None and self.staged_reads > 1:
            raise self.end_snapshot_error
        if self.drift and self.staged_reads > 1:
            from app.sources.offertoday.research.contracts import StagedListingSnapshot

            return [StagedListingSnapshot("row", "j1", "pending", None, RUN_ID)]
        return []

    def list_published_snapshots(self, db):
        self.state.log.append("published_snapshot")
        return []

    def capture_product_data_snapshot(self, db):
        self.product_reads += 1
        self.state.log.append(f"product_snapshot_{self.product_reads}")
        return ProductDataSnapshot.from_table_hashes(
            staged_rows_hash="a" * 64,
            published_jobs_hash=(
                "d" * 64 if self.product_drift and self.product_reads > 1 else "b" * 64
            ),
            companies_hash="c" * 64,
        )

    def list_research_events(self, db, crawl_job_id):
        self.state.log.append("load_events")
        if self.event_load_errors:
            raise self.event_load_errors.pop(0)
        assert str(crawl_job_id) == RUN_ID
        return list(self.state.events)


class State:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.events: list[SimpleNamespace] = []
        self.finished: list[dict] = []
        self.runtime_kwargs: list[dict] = []
        self.finish_errors: list[BaseException] = []
        self.created_metadata = None
        self.calibration_conditions = None
        self.staging_sink = None

    def append_event(self, event_type: str, payload: dict) -> None:
        self.events.append(
            SimpleNamespace(
                sequence_no=len(self.events) + 1,
                event_type=event_type,
                payload=payload,
                emitted_by="offertoday-research",
                created_at=datetime(2026, 7, 11, tzinfo=UTC),
            )
        )


class FakeObservationService:
    def __init__(self, db, state: State) -> None:
        self.db = db
        self.state = state
        self.crawl_job_id = None

    def create_run(self, metadata, *, run_start_inventory):
        self.state.log.append("create_run")
        self.state.created_metadata = metadata
        self.crawl_job_id = UUID(metadata.run_id)
        return self.crawl_job_id

    def record_event(self, event_type: str, payload: dict) -> None:
        self.state.append_event(event_type, payload)

    def record_detail_attempt(self, payload: dict) -> None:
        self.state.append_event("research.detail_attempt", payload)

    def finish_run(self, **kwargs) -> None:
        self.state.log.append("finish_run")
        if self.state.finish_errors:
            raise self.state.finish_errors.pop(0)
        self.state.finished.append(kwargs)
        self.state.append_event("research.run_summary", kwargs["summary"])


class FakeRuntime:
    def __init__(self, state: State, **kwargs) -> None:
        self.state = state
        self.state.runtime_kwargs.append(kwargs)

    async def __aenter__(self):
        self.state.log.append("browser_open")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.state.log.append("browser_close")
        return None


class FakeLiveService:
    def __init__(
        self,
        state: State,
        result: LiveSmokeExecution | BaseException,
    ) -> None:
        self.state = state
        self.result = result

    async def run_smoke(self, *, runtime, observation_service):
        self.state.log.append("network")
        assert observation_service.crawl_job_id == UUID(RUN_ID)
        result = (
            self.result.listing_result
            if isinstance(self.result, LiveSmokeExecution)
            else listing_result()
        )
        for observation in result.observations:
            observation_service.record_event(
                "research.page_attempt",
                listing_observation_to_payload(observation),
            )
        if isinstance(self.result, BaseException):
            raise self.result
        observation_service.record_event(
            "research.detail_cohort_frozen",
            {
                "count": len(self.result.frozen_targets),
                "targets": [
                    target.to_payload() for target in self.result.frozen_targets
                ],
            },
        )
        for item in self.result.detail_observations:
            observation_service.record_detail_attempt(item.to_payload())
        return self.result


class FakeCalibrationLiveService:
    def __init__(
        self,
        state: State,
        result: (
            tuple[BoundedConditionResult, ...]
            | "CalibrationFailureAfter"
            | BaseException
        ),
        *,
        stage_first_row: bool = False,
    ) -> None:
        self.state = state
        self.result = result
        self.stage_first_row = stage_first_row

    async def run_bounded_conditions(
        self,
        *,
        runtime,
        observation_service,
        conditions,
        staging_sink=None,
    ):
        self.state.log.append("network")
        self.state.calibration_conditions = tuple(conditions)
        self.state.staging_sink = staging_sink
        assert observation_service.crawl_job_id == UUID(RUN_ID)
        if self.stage_first_row:
            await staging_sink.stage_page(
                condition=conditions[0],
                page=1,
                rows=[
                    {
                        "job_id": "pilot-created",
                        "encrypted_job_id": "pilot-created",
                        "encrypted_job_id_source": "jobId_fallback",
                        "raw_data": {"jobId": "pilot-created"},
                    }
                ],
            )
        if isinstance(self.result, BaseException):
            raise self.result
        bounded_results = (
            self.result.results
            if isinstance(self.result, CalibrationFailureAfter)
            else self.result
        )
        for bounded_result in bounded_results:
            for observation in bounded_result.listing_result.observations:
                observation_service.record_event(
                    "research.page_attempt",
                    listing_observation_to_payload(observation),
                )
            outcome = bounded_result.listing_result.condition_outcomes[0]
            observation_service.record_event(
                (
                    "research.condition_completed"
                    if outcome.is_complete
                    else "research.condition_incomplete"
                ),
                listing_observation_to_payload(outcome),
            )
        if isinstance(self.result, CalibrationFailureAfter):
            raise self.result.error
        return bounded_results


class FakeCensusLiveService:
    def __init__(
        self,
        state: State,
        result: ListingRunResult | "CensusFailureAfter" | BaseException,
    ) -> None:
        self.state = state
        self.result = result

    async def run_census(
        self,
        *,
        runtime,
        observation_service,
        candidate,
        staging_sink,
    ) -> ListingRunResult:
        self.state.log.append("network")
        self.state.census_candidate = candidate
        self.state.staging_sink = staging_sink
        assert observation_service.crawl_job_id == UUID(RUN_ID)
        evidence_result = (
            self.result.result
            if isinstance(self.result, CensusFailureAfter)
            else self.result
        )
        if isinstance(evidence_result, BaseException):
            raise evidence_result
        for observation in evidence_result.observations:
            observation_service.record_event(
                "research.page_attempt",
                listing_observation_to_payload(observation),
            )
        for outcome in evidence_result.condition_outcomes:
            observation_service.record_event(
                (
                    "research.condition_completed"
                    if outcome.is_complete
                    else "research.condition_incomplete"
                ),
                listing_observation_to_payload(outcome),
            )
        if isinstance(self.result, CensusFailureAfter):
            raise self.result.error
        return evidence_result


class CensusStagingSink:
    def __init__(self, result: ListingRunResult) -> None:
        self.reconciliation = OfferTodayStagingReconciliation(
            rows_seen=len(result.accepted_job_ids),
            rows_created=0,
            published_source_job_ids=result.accepted_job_ids,
            preexisting_staged_source_job_ids=(),
            created_source_job_ids=(),
            deferred_identity_conflict_ids=(),
        )


class FakePilotCrawlRuntime:
    def stage_listing_batch(self, **_kwargs):
        raise AssertionError("pilot fixture did not provide listing rows to stage")

    def defer_listing_identity_conflict(self, **_kwargs):
        raise AssertionError("accepted pilot fixture deferred an identity conflict")


class CreatingPilotCrawlRuntime:
    def stage_listing_batch(self, **kwargs):
        source_job_ids = tuple(
            payload["source_job_id"] for payload in kwargs["payloads"]
        )
        return SimpleNamespace(
            rows_staged=len(source_job_ids),
            rows_created=len(source_job_ids),
            skipped_existing=0,
            created_source_job_ids=source_job_ids,
            preexisting_staged_source_job_ids=(),
            published_source_job_ids=(),
            job_ids_seen=len(source_job_ids),
        )

    def defer_listing_identity_conflict(self, **_kwargs):
        raise AssertionError("accepted pilot fixture deferred an identity conflict")


class AmplifiedPilotStagingSink:
    def __init__(self, **_kwargs) -> None:
        self.reconciliation = OfferTodayStagingReconciliation(
            rows_seen=1,
            rows_created=2,
            published_source_job_ids=(),
            preexisting_staged_source_job_ids=(),
            created_source_job_ids=("only-one-id",),
            deferred_identity_conflict_ids=(),
        )


class CalibrationFailureAfter:
    def __init__(
        self,
        results: tuple[BoundedConditionResult, ...],
        error: BaseException,
    ) -> None:
        self.results = results
        self.error = error


class CensusFailureAfter:
    def __init__(self, result: ListingRunResult, error: BaseException) -> None:
        self.result = result
        self.error = error


def invoke_smoke(
    tmp_path: Path,
    *,
    result: LiveSmokeExecution | BaseException | None = None,
    drift: bool = False,
    product_drift: bool = False,
    end_snapshot_error: BaseException | None = None,
    event_load_errors: list[BaseException] | None = None,
    artifact_verifier=verify_research_artifact,
    state: State | None = None,
):
    state = state or State()
    baselines = tmp_path / "baselines"
    first = baseline_artifact(baselines, BASELINE_RUN_1)
    second = baseline_artifact(baselines, BASELINE_RUN_2)
    session = FakeSession(state.log)
    repository = FakeRepository(
        state,
        drift=drift,
        product_drift=product_drift,
        end_snapshot_error=end_snapshot_error,
        event_load_errors=event_load_errors,
    )

    def exporter(**kwargs):
        state.log.append("artifact_export")
        return export_research_artifact(**kwargs)

    exit_code = census_cli.main(
        [
            "smoke",
            "--baseline-artifact",
            str(first),
            "--baseline-artifact",
            str(second),
            "--run-id",
            RUN_ID,
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
        ],
        session_factory=lambda: session,
        repository=repository,
        runtime_factory=lambda **kwargs: FakeRuntime(state, **kwargs),
        service_factory=lambda: FakeLiveService(state, result or execution()),
        observation_service_factory=lambda db: FakeObservationService(db, state),
        provenance_provider=provenance,
        artifact_exporter=exporter,
        artifact_verifier=artifact_verifier,
    )
    return exit_code, state, session, tmp_path / "runs" / RUN_ID


def invoke_calibrate(
    tmp_path: Path,
    *,
    result: (
        tuple[BoundedConditionResult, ...]
        | CalibrationFailureAfter
        | BaseException
        | None
    ) = None,
    drift: bool = False,
    product_drift: bool = False,
    artifact_verifier=verify_research_artifact,
    state: State | None = None,
):
    state = state or State()
    smoke = accepted_smoke_artifact(tmp_path / "smoke")
    assert census_cli.verify_live_research_run(smoke).valid is True
    baselines = tmp_path / "baselines"
    first = baseline_artifact(baselines, BASELINE_RUN_1)
    second = baseline_artifact(baselines, BASELINE_RUN_2)
    session = FakeSession(state.log)
    repository = FakeRepository(
        state,
        drift=drift,
        product_drift=product_drift,
    )

    def exporter(**kwargs):
        state.log.append("artifact_export")
        return export_research_artifact(**kwargs)

    exit_code = census_cli.main(
        [
            "calibrate",
            "--smoke-artifact",
            str(smoke),
            "--baseline-artifact",
            str(first),
            "--baseline-artifact",
            str(second),
            "--run-id",
            RUN_ID,
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
        ],
        session_factory=lambda: session,
        repository=repository,
        runtime_factory=lambda **kwargs: FakeRuntime(state, **kwargs),
        service_factory=lambda: FakeCalibrationLiveService(
            state,
            result or calibration_results(),
        ),
        observation_service_factory=lambda db: FakeObservationService(db, state),
        provenance_provider=provenance,
        artifact_exporter=exporter,
        artifact_verifier=artifact_verifier,
    )
    return exit_code, state, session, tmp_path / "runs" / RUN_ID


def invoke_pilot(
    tmp_path: Path,
    *,
    result: tuple[BoundedConditionResult, ...] | BaseException | None = None,
    variant_rank: int = 2,
    artifact_verifier=verify_research_artifact,
    staging_sink_factory=OfferTodayReconciledListingStagingSink,
    crawl_runtime_factory=FakePilotCrawlRuntime,
    stage_first_row: bool = False,
    drift: bool = False,
    end_snapshot_error: BaseException | None = None,
    state: State | None = None,
):
    state = state or State()
    calibration_exit, _calibration_state, _session, calibration = invoke_calibrate(
        tmp_path / "calibration"
    )
    assert calibration_exit == census_cli.EXIT_OK
    baselines = tmp_path / "baselines"
    first = baseline_artifact(baselines, BASELINE_RUN_1)
    second = baseline_artifact(baselines, BASELINE_RUN_2)
    session = FakeSession(state.log)
    repository = FakeRepository(
        state,
        drift=drift,
        end_snapshot_error=end_snapshot_error,
    )

    def exporter(**kwargs):
        state.log.append("artifact_export")
        return export_research_artifact(**kwargs)

    exit_code = census_cli.main(
        [
            "pilot",
            "--calibration-artifact",
            str(calibration),
            "--baseline-artifact",
            str(first),
            "--baseline-artifact",
            str(second),
            "--variant-rank",
            str(variant_rank),
            "--run-id",
            RUN_ID,
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
        ],
        session_factory=lambda: session,
        repository=repository,
        runtime_factory=lambda **kwargs: FakeRuntime(state, **kwargs),
        service_factory=lambda: FakeCalibrationLiveService(
            state,
            result or pilot_results(),
            stage_first_row=stage_first_row,
        ),
        observation_service_factory=lambda db: FakeObservationService(db, state),
        crawl_runtime_factory=crawl_runtime_factory,
        staging_sink_factory=staging_sink_factory,
        provenance_provider=provenance,
        artifact_exporter=exporter,
        artifact_verifier=artifact_verifier,
    )
    return exit_code, state, session, tmp_path / "runs" / RUN_ID


def invoke_freeze_candidate(
    tmp_path: Path,
    *,
    pilot_result: tuple[BoundedConditionResult, ...] | None = None,
):
    pilot_exit, _state, _session, pilot = invoke_pilot(
        tmp_path / "evidence",
        result=pilot_result,
    )
    calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        calls.append("live_dependency")
        raise AssertionError("freeze-candidate constructed a live dependency")

    artifact_root = tmp_path / "candidate-runs"
    exit_code = census_cli.main(
        [
            "freeze-candidate",
            "--pilot-artifact",
            str(pilot),
            "--run-id",
            CANDIDATE_RUN_ID,
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(artifact_root),
        ],
        session_factory=forbidden,
        repository=forbidden,
        runtime_factory=forbidden,
        service_factory=forbidden,
        observation_service_factory=forbidden,
        crawl_runtime_factory=forbidden,
        staging_sink_factory=forbidden,
        provenance_provider=provenance,
    )
    return (
        exit_code,
        pilot_exit,
        calls,
        pilot,
        artifact_root / CANDIDATE_RUN_ID,
    )


def invoke_census(
    tmp_path: Path,
    *,
    result: ListingRunResult | CensusFailureAfter | BaseException | None = None,
    state: State | None = None,
):
    state = state or State()
    census_result = result or full_census_result()
    evidence_result = (
        census_result.result
        if isinstance(census_result, CensusFailureAfter)
        else census_result
    )
    if isinstance(evidence_result, BaseException):
        evidence_result = full_census_result()
    candidate_exit, pilot_exit, calls, _pilot, candidate_artifact = (
        invoke_freeze_candidate(tmp_path / "candidate-evidence")
    )
    assert candidate_exit == census_cli.EXIT_OK
    assert pilot_exit == census_cli.EXIT_OK
    assert calls == []
    baselines = tmp_path / "baselines"
    first = baseline_artifact(baselines, BASELINE_RUN_1)
    second = baseline_artifact(baselines, BASELINE_RUN_2)
    session = FakeSession(state.log)
    repository = FakeRepository(state)
    staging_sink = CensusStagingSink(evidence_result)

    def exporter(**kwargs):
        state.log.append("artifact_export")
        return export_research_artifact(**kwargs)

    exit_code = census_cli.main(
        [
            "census",
            "--candidate-artifact",
            str(candidate_artifact),
            "--baseline-artifact",
            str(first),
            "--baseline-artifact",
            str(second),
            "--run-id",
            RUN_ID,
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
        ],
        session_factory=lambda: session,
        repository=repository,
        runtime_factory=lambda **kwargs: FakeRuntime(state, **kwargs),
        service_factory=lambda: FakeCensusLiveService(state, census_result),
        observation_service_factory=lambda db: FakeObservationService(db, state),
        crawl_runtime_factory=FakePilotCrawlRuntime,
        staging_sink_factory=lambda **_kwargs: staging_sink,
        provenance_provider=provenance,
        artifact_exporter=exporter,
    )
    return (
        exit_code,
        state,
        session,
        tmp_path / "runs" / RUN_ID,
        candidate_artifact,
        census_result,
    )


def test_parser_exposes_only_locked_live_inputs_and_offline_verify() -> None:
    parser = census_cli.build_parser()
    smoke = parser.parse_args(
        [
            "smoke",
            "--baseline-artifact",
            "first",
            "--baseline-artifact",
            "second",
        ]
    )
    calibrate = parser.parse_args(
        [
            "calibrate",
            "--smoke-artifact",
            "smoke",
            "--baseline-artifact",
            "first",
            "--baseline-artifact",
            "second",
        ]
    )
    pilot = parser.parse_args(
        [
            "pilot",
            "--calibration-artifact",
            "calibration",
            "--baseline-artifact",
            "first",
            "--baseline-artifact",
            "second",
            "--variant-rank",
            "2",
        ]
    )
    census = parser.parse_args(
        [
            "census",
            "--candidate-artifact",
            "candidate",
            "--baseline-artifact",
            "first",
            "--baseline-artifact",
            "second",
        ]
    )
    verify = parser.parse_args(["verify-run", "--artifact", "run"])
    freeze = parser.parse_args(["freeze-candidate", "--pilot-artifact", "pilot"])

    assert smoke.command == "smoke"
    assert smoke.baseline_artifact == [Path("first"), Path("second")]
    assert calibrate.command == "calibrate"
    assert calibrate.smoke_artifact == Path("smoke")
    assert calibrate.baseline_artifact == [Path("first"), Path("second")]
    assert pilot.command == "pilot"
    assert pilot.calibration_artifact == Path("calibration")
    assert pilot.baseline_artifact == [Path("first"), Path("second")]
    assert pilot.variant_rank == 2
    assert census.command == "census"
    assert census.candidate_artifact == Path("candidate")
    assert census.baseline_artifact == [Path("first"), Path("second")]
    assert verify.command == "verify-run"
    assert freeze.command == "freeze-candidate"
    assert freeze.pilot_artifact == Path("pilot")
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "smoke",
                "--baseline-artifact",
                "first",
                "--baseline-artifact",
                "second",
                "--detail-limit",
                "1",
            ]
        )
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "freeze-candidate",
                "--pilot-artifact",
                "pilot",
                "--endpoint",
                "browse",
            ]
        )
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "census",
                "--candidate-artifact",
                "candidate",
                "--baseline-artifact",
                "first",
                "--baseline-artifact",
                "second",
                "--max-pages-per-condition",
                "1",
            ]
        )
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "calibrate",
                "--smoke-artifact",
                "smoke",
                "--baseline-artifact",
                "first",
                "--baseline-artifact",
                "second",
                "--endpoint",
                "browse",
            ]
        )


@pytest.mark.parametrize(
    "override",
    (
        ("--endpoint", "browse"),
        ("--rcd-type", "7"),
        ("--category-id", "118000"),
        ("--page-size", "10"),
        ("--max-pages-per-condition", "1"),
        ("--max-attempts-per-page", "1"),
        ("--retry-delays-seconds", "0"),
        ("--page-delay-range-seconds", "0,0"),
    ),
)
def test_census_parser_rejects_every_mutable_candidate_override(override) -> None:
    with pytest.raises(SystemExit):
        census_cli.build_parser().parse_args(
            [
                "census",
                "--candidate-artifact",
                "candidate",
                "--baseline-artifact",
                "first",
                "--baseline-artifact",
                "second",
                *override,
            ]
        )


def test_census_requires_exactly_two_baselines_before_dependencies(tmp_path) -> None:
    calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        calls.append("dependency")
        raise AssertionError("census constructed a dependency before validation")

    result = census_cli.main(
        [
            "census",
            "--candidate-artifact",
            str(tmp_path / "missing-candidate"),
            "--baseline-artifact",
            str(tmp_path / "only-one-baseline"),
        ],
        session_factory=forbidden,
        repository=forbidden,
        runtime_factory=forbidden,
        service_factory=forbidden,
    )

    assert result == census_cli.EXIT_USAGE
    assert calls == []


def test_freeze_candidate_is_offline_and_preserves_pilot_selected_controls(
    tmp_path,
    capsys,
) -> None:
    exit_code, pilot_exit, calls, pilot, artifact = invoke_freeze_candidate(tmp_path)
    output = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert pilot_exit == census_cli.EXIT_OK
    assert exit_code == census_cli.EXIT_OK
    assert calls == []
    candidate_payload = json.loads(
        (artifact / "candidate.json").read_text(encoding="utf-8")
    )
    candidate = CensusCandidate(
        endpoint=candidate_payload["endpoint"],
        rcd_type=candidate_payload["rcd_type"],
        category_ids=tuple(candidate_payload["category_ids"]),
        page_size=candidate_payload["page_size"],
        max_pages_per_condition=candidate_payload["max_pages_per_condition"],
        require_empty_confirmation=candidate_payload["require_empty_confirmation"],
        max_attempts_per_page=candidate_payload["max_attempts_per_page"],
        retry_delays_seconds=tuple(candidate_payload["retry_delays_seconds"]),
        page_delay_range_seconds=tuple(candidate_payload["page_delay_range_seconds"]),
        session_mode=candidate_payload["session_mode"],
        fixed_repeat_category_ids=tuple(candidate_payload["fixed_repeat_category_ids"]),
        source_artifact_hash=candidate_payload["source_artifact_hash"],
        rejected_variants=tuple(candidate_payload["rejected_variants"]),
    )
    assert candidate_payload["candidate_hash"] == candidate.candidate_hash
    assert candidate.endpoint == "search"
    assert candidate.rcd_type is None
    assert len(candidate.category_ids) == 31
    assert len(candidate.rejected_variants) == 3
    assert all(
        {
            "accepted",
            "attempts",
            "conflicts",
            "failure_count",
            "logical_pages",
            "median_latency_ms",
            "missing_ids",
            "rejection_reason",
        }.issubset(item)
        for item in candidate.rejected_variants
    )
    assert (
        candidate.source_artifact_hash
        == hashlib.sha256((pilot / "manifest.json").read_bytes()).hexdigest()
    )
    assert output == {
        "artifact": str(artifact.resolve()),
        "candidate_hash": candidate.candidate_hash,
        "endpoint": "search",
        "rcd_type": None,
        "run_id": CANDIDATE_RUN_ID,
    }
    assert verify_research_artifact(artifact).valid is True
    assert census_cli.verify_live_research_run(artifact).valid is True


def test_census_candidate_loader_requires_verified_frozen_artifact(tmp_path) -> None:
    exit_code, pilot_exit, calls, _pilot, artifact = invoke_freeze_candidate(tmp_path)

    assert exit_code == census_cli.EXIT_OK
    assert pilot_exit == census_cli.EXIT_OK
    assert calls == []
    evidence = census_cli._require_census_candidate_artifact(artifact)
    payload = json.loads((artifact / "candidate.json").read_text(encoding="utf-8"))

    assert evidence.candidate == CensusCandidate.from_payload(payload)
    assert evidence.candidate_hash == payload["candidate_hash"]
    assert (
        evidence.parent_artifact_hash
        == hashlib.sha256((artifact / "manifest.json").read_bytes()).hexdigest()
    )
    assert evidence.candidate_run_id == CANDIDATE_RUN_ID


def test_census_accepts_only_complete_natural_exhaustion_and_hashes_ids(
    tmp_path,
    capsys,
) -> None:
    exit_code, state, session, artifact, candidate_artifact, result = invoke_census(
        tmp_path
    )
    output = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
    events = census_cli._read_jsonl(artifact / "observations.jsonl")
    summaries = [
        event["payload"]
        for event in events
        if event["event_type"] == "research.run_summary"
    ]

    assert exit_code == census_cli.EXIT_OK
    assert session.closed is True
    assert state.runtime_kwargs == [{"headed": False}]
    assert state.log.index("browser_open") < state.log.index("network")
    assert state.log.index("network") < state.log.index("browser_close")
    assert isinstance(state.census_candidate, CensusCandidate)
    assert state.staging_sink.reconciliation.staging_amplification_ratio == 0.0
    assert len(summaries) == 1
    summary = summaries[0]
    candidate_payload = json.loads(
        (candidate_artifact / "candidate.json").read_text(encoding="utf-8")
    )
    assert summary["census_passed"] is True
    assert summary["condition_count"] == 31
    assert summary["natural_exhaustion_count"] == 31
    assert summary["unresolved_gaps"] == 0
    assert summary["identity_issue_count"] == 0
    assert summary["identity_conflict_count"] == 0
    assert summary["conservation_difference"] == 0
    assert summary["staging_amplification_ratio"] == 0.0
    assert summary["detail_attempt_count"] == 0
    assert summary["request_budget"] == CENSUS_BUDGET
    assert summary["candidate_hash"] == candidate_payload["candidate_hash"]
    assert summary["ordered_job_id_hash"] == ordered_id_hash(result.accepted_job_ids)
    assert summary["unique_job_count"] == len(result.accepted_job_ids)
    assert len(summary["condition_outcomes"]) == 31
    assert all(
        outcome["ordered_job_id_hash"]
        == ordered_id_hash((f"census-{outcome['category_id']}",))
        for outcome in summary["condition_outcomes"]
    )
    assert not any(event["event_type"] == "research.detail_attempt" for event in events)
    assert manifest["metadata"] == {
        **manifest["metadata"],
        "experiment": "full-census",
        "crawl_job_status": "completed",
        "candidate_hash": candidate_payload["candidate_hash"],
        "census_passed": True,
        "request_budget": CENSUS_BUDGET,
    }
    assert output["census_passed"] is True
    assert output["condition_count"] == 31
    assert output["natural_exhaustion_count"] == 31
    assert output["detail_attempt_count"] == 0
    assert output["request_budget"] == CENSUS_BUDGET
    assert verify_research_artifact(artifact).valid is True
    assert census_cli.verify_live_research_run(artifact).valid is True


def test_census_page_cap_is_incomplete_and_preserves_partial_artifact(
    tmp_path,
    capsys,
) -> None:
    exit_code, _state, _session, artifact, _candidate, _result = invoke_census(
        tmp_path,
        result=page_cap_census_result(),
    )
    output = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
    events = census_cli._read_jsonl(artifact / "observations.jsonl")
    summary = next(
        event["payload"]
        for event in events
        if event["event_type"] == "research.run_summary"
    )

    assert exit_code == census_cli.EXIT_INCOMPLETE
    assert manifest["metadata"]["crawl_job_status"] == "failed"
    assert manifest["metadata"]["census_passed"] is False
    assert summary["status"] == "failed"
    assert summary["census_passed"] is False
    assert summary["condition_count"] == 2
    assert summary["natural_exhaustion_count"] == 1
    assert summary["stop_reason"] == "page_cap"
    assert summary["condition_outcomes"][-1]["stop_reason"] == "page_cap"
    assert summary["condition_outcomes"][-1]["is_complete"] is False
    assert summary["listing_logical_count"] == 502
    assert summary["detail_attempt_count"] == 0
    assert output["census_passed"] is False
    assert output["exit_code"] == census_cli.EXIT_INCOMPLETE
    assert verify_research_artifact(artifact).valid is True
    assert census_cli.verify_live_research_run(artifact).valid is True


def test_census_strict_replay_rejects_page_cap_labeled_complete(
    tmp_path,
) -> None:
    _exit_code, _state, _session, artifact, _candidate, _result = invoke_census(
        tmp_path / "source",
        result=page_cap_census_result(),
    )
    manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
    events = census_cli._read_jsonl(artifact / "observations.jsonl")
    incomplete = next(
        event
        for event in reversed(events)
        if event["event_type"] == "research.condition_incomplete"
    )
    incomplete["event_type"] = "research.condition_completed"
    incomplete["payload"]["is_complete"] = True
    summary = next(
        event["payload"]
        for event in events
        if event["event_type"] == "research.run_summary"
    )
    summary["natural_exhaustion_count"] = 2
    summary["condition_outcomes"][-1]["is_complete"] = True
    tampered = export_research_artifact(
        root=tmp_path / "tampered",
        run_id=RUN_ID,
        metadata=manifest["metadata"],
        events=events,
        provenance=provenance(),
    )

    assert verify_research_artifact(tampered).valid is True
    verification = census_cli.verify_live_research_run(tampered)
    assert verification.valid is False
    assert "invalid_census_condition_semantics" in verification.issues


def test_unexpected_census_failure_preserves_partial_hashes_and_replays(
    tmp_path,
) -> None:
    partial = one_condition_census_result()
    error = RuntimeError("boom")

    with pytest.raises(RuntimeError) as captured:
        invoke_census(
            tmp_path,
            result=CensusFailureAfter(partial, error),
        )

    artifact = tmp_path / "runs" / RUN_ID
    events = census_cli._read_jsonl(artifact / "observations.jsonl")
    summary = next(
        event["payload"]
        for event in events
        if event["event_type"] == "research.run_summary"
    )
    assert captured.value is error
    assert summary["status"] == "failed"
    assert summary["census_passed"] is False
    assert summary["stop_reason"] == "unexpected_full_census_error:RuntimeError"
    assert summary["condition_count"] == 1
    assert summary["natural_exhaustion_count"] == 1
    assert summary["ordered_job_id_hash"] == ordered_id_hash(partial.accepted_job_ids)
    assert summary["unique_job_count"] == 1
    assert summary["condition_outcomes"][0]["is_complete"] is True
    assert verify_research_artifact(artifact).valid is True
    assert census_cli.verify_live_research_run(artifact).valid is True


def test_freeze_candidate_rejects_an_incomplete_pilot_before_dependencies(
    tmp_path,
) -> None:
    exit_code, pilot_exit, calls, _pilot, artifact = invoke_freeze_candidate(
        tmp_path,
        pilot_result=pilot_results()[:-1],
    )

    assert pilot_exit == census_cli.EXIT_INCOMPLETE
    assert exit_code == census_cli.EXIT_EVIDENCE_FAILURE
    assert calls == []
    assert artifact.exists() is False


def test_pilot_predecessor_selects_only_a_verified_selected_variant(
    tmp_path,
) -> None:
    exit_code, _state, _session, calibration = invoke_calibrate(
        tmp_path / "calibration"
    )
    assert exit_code == census_cli.EXIT_OK

    selected = census_cli._require_accepted_calibration_variant(
        calibration,
        variant_rank=2,
    )

    assert selected.endpoint == "search"
    assert selected.rcd_type is None
    assert selected.variant_rank == 2
    assert len(selected.parent_artifact_hash) == 64
    with pytest.raises(ValueError, match="selected variant rank"):
        census_cli._require_accepted_calibration_variant(
            calibration,
            variant_rank=3,
        )


def test_calibrate_requires_exactly_two_baselines_before_dependencies(
    tmp_path,
    capsys,
) -> None:
    smoke = accepted_smoke_artifact(tmp_path / "smoke")
    baseline = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_1)

    def forbidden(*args, **kwargs):
        raise AssertionError("calibrate constructed a dependency before validation")

    result = census_cli.main(
        [
            "calibrate",
            "--smoke-artifact",
            str(smoke),
            "--baseline-artifact",
            str(baseline),
            "--run-id",
            RUN_ID,
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
        ],
        session_factory=forbidden,
        runtime_factory=forbidden,
        service_factory=forbidden,
    )

    assert result == census_cli.EXIT_USAGE
    assert (
        "calibrate requires exactly two baseline artifacts" in capsys.readouterr().err
    )


@pytest.mark.parametrize(
    "smoke_kwargs",
    (
        {"smoke_passed": False},
        {"request_budget": {"listing": 1, "detail": 20}},
    ),
)
def test_calibrate_rejects_unaccepted_smoke_before_dependencies(
    tmp_path,
    smoke_kwargs,
) -> None:
    smoke = accepted_smoke_artifact(tmp_path / "smoke", **smoke_kwargs)
    baselines = tmp_path / "baselines"
    first = baseline_artifact(baselines, BASELINE_RUN_1)
    second = baseline_artifact(baselines, BASELINE_RUN_2)

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid predecessor constructed a live dependency")

    result = census_cli.main(
        [
            "calibrate",
            "--smoke-artifact",
            str(smoke),
            "--baseline-artifact",
            str(first),
            "--baseline-artifact",
            str(second),
            "--run-id",
            RUN_ID,
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
        ],
        session_factory=forbidden,
        runtime_factory=forbidden,
        service_factory=forbidden,
    )

    assert result == census_cli.EXIT_EVIDENCE_FAILURE


def test_smoke_requires_exactly_two_baselines_before_dependencies(tmp_path) -> None:
    first = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_1)
    calls: list[str] = []

    result = census_cli.main(
        ["smoke", "--baseline-artifact", str(first)],
        session_factory=lambda: calls.append("session"),
        runtime_factory=lambda **kwargs: calls.append("runtime"),
    )

    assert result == census_cli.EXIT_USAGE
    assert calls == []


def test_current_database_drift_from_matching_baselines_stops_before_browser(
    tmp_path,
) -> None:
    baseline_row = StagedListingSnapshot(
        row_id="row-1",
        source_job_id="j1",
        detail_status="pending",
        published_job_id=None,
        crawl_job_id="crawl-1",
    )
    baselines = tmp_path / "baselines"
    first = baseline_artifact(
        baselines,
        BASELINE_RUN_1,
        listings=[baseline_row],
    )
    second = baseline_artifact(
        baselines,
        BASELINE_RUN_2,
        listings=[baseline_row],
    )
    state = State()
    runtime_calls: list[dict] = []

    result = census_cli.main(
        [
            "smoke",
            "--baseline-artifact",
            str(first),
            "--baseline-artifact",
            str(second),
            "--run-id",
            RUN_ID,
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
        ],
        session_factory=lambda: FakeSession(state.log),
        repository=FakeRepository(state),
        runtime_factory=lambda **kwargs: runtime_calls.append(kwargs),
    )

    assert result == census_cli.EXIT_EVIDENCE_FAILURE
    assert runtime_calls == []
    assert "browser_open" not in state.log


def test_job_id_fallback_rows_drift_stops_before_browser_or_live_dependencies(
    tmp_path,
    monkeypatch,
) -> None:
    baselines = tmp_path / "baselines"
    first = baseline_artifact(baselines, BASELINE_RUN_1)
    second = baseline_artifact(baselines, BASELINE_RUN_2)
    baseline_snapshot = build_baseline_snapshot(
        listings=[],
        jobs=[],
        product_data=ProductDataSnapshot.from_table_hashes(
            staged_rows_hash="a" * 64,
            published_jobs_hash="b" * 64,
            companies_hash="c" * 64,
        ),
    )
    inventory = build_run_start_inventory(listings=[], jobs=[])
    drifted_snapshot = replace(
        baseline_snapshot,
        job_id_fallback_rows=1,
    )
    monkeypatch.setattr(
        census_cli,
        "_capture_snapshot",
        lambda _repository, _db: (drifted_snapshot, inventory),
    )
    state = State()
    session = FakeSession(state.log)

    result = census_cli.main(
        [
            "smoke",
            "--baseline-artifact",
            str(first),
            "--baseline-artifact",
            str(second),
            "--run-id",
            RUN_ID,
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
        ],
        session_factory=lambda: session,
        repository=FakeRepository(state),
        runtime_factory=lambda **kwargs: FakeRuntime(state, **kwargs),
        service_factory=lambda: FakeLiveService(state, execution()),
        observation_service_factory=lambda db: FakeObservationService(db, state),
        provenance_provider=provenance,
    )

    assert state.runtime_kwargs == []
    assert "browser_open" not in state.log
    assert "network" not in state.log
    assert result == census_cli.EXIT_EVIDENCE_FAILURE


def test_verify_run_is_network_and_database_free(tmp_path) -> None:
    events = [
        {
            "sequence_no": 1,
            "event_type": "research.run_started",
            "payload": {"request_budget": dict(CURRENT_SMOKE_BUDGET)},
        },
        {
            "sequence_no": 2,
            "event_type": "research.page_attempt",
            "payload": listing_observation_to_payload(listing_result().observations[0]),
        },
        {
            "sequence_no": 3,
            "event_type": "research.detail_cohort_frozen",
            "payload": {
                "count": 20,
                "targets": [
                    DetailSmokeTarget(
                        position, f"j{position}", f"e{position}"
                    ).to_payload()
                    for position in range(1, 21)
                ],
            },
        },
    ]
    events.extend(
        {
            "sequence_no": position + 3,
            "event_type": "research.detail_attempt",
            "payload": {
                "target": DetailSmokeTarget(
                    position,
                    f"j{position}",
                    f"e{position}",
                ).to_payload(),
                "classification": "success",
                "api_code": 0,
                "identity_valid": True,
                "parsed": True,
                "has_title": True,
                "has_company": True,
                "has_description": True,
                "stop_batch": False,
            },
        }
        for position in range(1, 21)
    )
    events.append(
        {
            "sequence_no": 24,
            "event_type": "research.run_summary",
            "payload": {
                "status": "completed",
                "smoke_passed": True,
                "listing_complete": False,
                "expected_truncation": True,
                "listing_attempt_count": 1,
                "attempted_count": 20,
                "frozen_count": 20,
                "success_count": 20,
                "terminal_count": 0,
                "unattempted_count": 0,
                "missing_encrypted_job_id_count": 0,
                "job_id_fallback_count": 0,
                "listing_stop_reason": "target_cap",
                "stop_reason": None,
                "request_budget": dict(CURRENT_SMOKE_BUDGET),
                "product_data_unchanged": True,
                "run_start_snapshot_hash": "d" * 64,
                "run_end_snapshot_hash": "d" * 64,
                "run_start_product_data_hash": "f" * 64,
                "run_end_product_data_hash": "f" * 64,
                "run_start_inventory_hash": "e" * 64,
                "run_end_inventory_hash": "e" * 64,
            },
        }
    )
    artifact = export_research_artifact(
        root=tmp_path,
        run_id=RUN_ID,
        metadata={
            "experiment": "runtime-smoke",
            "crawl_job_id": RUN_ID,
            "crawl_job_status": "completed",
            "parent_artifact_hash": "c" * 64,
            "request_budget": dict(CURRENT_SMOKE_BUDGET),
            "smoke_passed": True,
        },
        events=events,
        provenance=provenance(),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("verify-run constructed a live dependency")

    result = census_cli.main(
        ["verify-run", "--artifact", str(artifact)],
        session_factory=forbidden,
        runtime_factory=forbidden,
        service_factory=forbidden,
    )

    assert result == census_cli.EXIT_OK


@pytest.mark.parametrize(
    "relative_path",
    [
        ("backend/runtime/offertoday-research/" "fab9d8e1-4c12-4170-a539-c0a6cdbbca93"),
        ("backend/runtime/offertoday-research/" "63b9d32a-5d47-44c9-8904-25a68ee2dee8"),
    ],
)
def test_verify_run_keeps_each_immutable_failed_artifact_offline(
    relative_path: str,
) -> None:
    artifact = Path(relative_path)
    if not (artifact / "manifest.json").is_file():
        pytest.skip("immutable failed smoke artifact is unavailable")

    def forbidden(*args, **kwargs):
        raise AssertionError("verify-run constructed a live dependency")

    result = census_cli.main(
        ["verify-run", "--artifact", str(artifact)],
        session_factory=forbidden,
        runtime_factory=forbidden,
        service_factory=forbidden,
    )

    assert result == census_cli.EXIT_OK


def test_successful_smoke_lifecycle_and_artifact(tmp_path, capsys) -> None:
    exit_code, state, session, artifact = invoke_smoke(tmp_path)
    output = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert exit_code == census_cli.EXIT_OK
    assert session.closed is True
    assert state.runtime_kwargs == [{"headed": False}]
    assert state.log.index("staged_snapshot_1") < state.log.index("browser_open")
    assert state.log.index("create_run") < state.log.index("network")
    assert state.log.index("browser_close") < state.log.index("artifact_export")
    assert state.log.index("db_close") < state.log.index("artifact_export")
    assert state.finished[0]["status"] == "completed"
    assert state.finished[0]["summary"]["smoke_passed"] is True
    assert state.finished[0]["summary"]["listing_complete"] is False
    assert state.finished[0]["summary"]["expected_truncation"] is True
    assert state.finished[0]["summary"]["missing_encrypted_job_id_count"] == 0
    assert state.finished[0]["summary"]["job_id_fallback_count"] == 0
    assert state.created_metadata.request_budget == CURRENT_SMOKE_BUDGET
    assert state.finished[0]["summary"]["request_budget"] == CURRENT_SMOKE_BUDGET
    assert output["request_budget"] == CURRENT_SMOKE_BUDGET
    assert output["missing_encrypted_job_id_count"] == 0
    assert output["job_id_fallback_count"] == 0
    assert (
        state.finished[0]["summary"]["run_start_snapshot_hash"]
        == state.finished[0]["summary"]["run_end_snapshot_hash"]
    )
    assert (
        state.finished[0]["summary"]["run_start_inventory_hash"]
        == state.finished[0]["summary"]["run_end_inventory_hash"]
    )
    assert set(output) == {
        "artifact",
        "run_id",
        "exit_code",
        "smoke_passed",
        "request_budget",
        "missing_encrypted_job_id_count",
        "job_id_fallback_count",
    }
    manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (artifact / "observations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    run_started = next(
        event for event in events if event["event_type"] == "research.run_started"
    )
    run_summary = next(
        event for event in events if event["event_type"] == "research.run_summary"
    )
    assert manifest["metadata"]["request_budget"] == CURRENT_SMOKE_BUDGET
    assert run_started["payload"]["request_budget"] == CURRENT_SMOKE_BUDGET
    assert run_summary["payload"]["request_budget"] == CURRENT_SMOKE_BUDGET
    assert verify_research_artifact(artifact).valid is True


def test_successful_calibration_lifecycle_and_artifact(tmp_path, capsys) -> None:
    results = calibration_results()
    expected_summaries = summarize_calibration_variants(results)
    expected_selection = select_calibration_variants(expected_summaries, limit=2)

    exit_code, state, session, artifact = invoke_calibrate(
        tmp_path,
        result=results,
    )
    output = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert exit_code == census_cli.EXIT_OK
    assert session.closed is True
    assert state.runtime_kwargs == [{"headed": False}]
    assert state.calibration_conditions == build_calibration_conditions()
    assert state.log.index("staged_snapshot_1") < state.log.index("browser_open")
    assert state.log.index("create_run") < state.log.index("network")
    assert state.log.index("browser_close") < state.log.index("artifact_export")
    assert state.log.index("db_close") < state.log.index("artifact_export")
    assert state.created_metadata.experiment == "listing-calibration"
    assert state.created_metadata.request_budget == CALIBRATION_BUDGET
    summary = state.finished[0]["summary"]
    assert state.finished[0]["status"] == "completed"
    assert summary["calibration_passed"] is True
    assert summary["condition_count"] == 8
    assert summary["accepted_condition_count"] == 8
    assert summary["listing_logical_count"] == 24
    assert summary["listing_attempt_count"] == 24
    assert summary["detail_attempt_count"] == 0
    assert summary["request_budget"] == CALIBRATION_BUDGET
    assert summary["variant_summaries"] == [asdict(item) for item in expected_summaries]
    assert summary["selection"] == asdict(expected_selection)
    assert summary["product_data_unchanged"] is True
    assert output == {
        "artifact": str(artifact),
        "run_id": RUN_ID,
        "exit_code": census_cli.EXIT_OK,
        "calibration_passed": True,
        "request_budget": CALIBRATION_BUDGET,
        "condition_count": 8,
        "listing_logical_count": 24,
        "listing_attempt_count": 24,
        "detail_attempt_count": 0,
    }
    manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (artifact / "observations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert manifest["metadata"]["experiment"] == "listing-calibration"
    assert manifest["metadata"]["calibration_passed"] is True
    assert manifest["metadata"]["request_budget"] == CALIBRATION_BUDGET
    assert sum(event["event_type"] == "research.page_attempt" for event in events) == 24
    assert (
        sum(
            event["event_type"]
            in {
                "research.condition_completed",
                "research.condition_incomplete",
            }
            for event in events
        )
        == 8
    )
    assert (
        sum(event["event_type"] == "research.detail_attempt" for event in events) == 0
    )
    expected_selection_event = json.loads(
        json.dumps(
            {
                "variant_summaries": [asdict(item) for item in expected_summaries],
                "selection": asdict(expected_selection),
            }
        )
    )
    assert [
        event
        for event in events
        if event["event_type"] == "research.calibration_selection"
    ][0]["payload"] == expected_selection_event
    assert verify_research_artifact(artifact).valid is True
    assert census_cli.verify_live_research_run(artifact).valid is True


def test_successful_calibration_accepts_natural_exhaustion_below_page_budget(
    tmp_path,
) -> None:
    conditions = build_calibration_conditions()
    results = tuple(
        (
            naturally_exhausted_calibration_result(condition)
            if index < 4
            else calibration_result(condition)
        )
        for index, condition in enumerate(conditions)
    )
    assert sum(result.pages_observed for result in results) == 20
    assert all(result.accepted for result in results)

    exit_code, state, _session, artifact = invoke_calibrate(
        tmp_path,
        result=results,
    )

    assert exit_code == census_cli.EXIT_OK
    assert state.finished[0]["summary"]["calibration_passed"] is True
    assert state.finished[0]["summary"]["listing_logical_count"] == 20
    assert census_cli.verify_live_research_run(artifact).valid is True


def test_successful_pilot_lifecycle_uses_ranked_variant_and_31_categories(
    tmp_path,
    capsys,
) -> None:
    exit_code, state, session, artifact = invoke_pilot(tmp_path, variant_rank=2)
    output = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert exit_code == census_cli.EXIT_OK
    assert session.closed is True
    assert state.runtime_kwargs == [{"headed": False}]
    assert state.calibration_conditions == build_pilot_conditions("search", None)
    assert isinstance(state.staging_sink, OfferTodayReconciledListingStagingSink)
    assert state.created_metadata.experiment == "category-pilot"
    assert state.created_metadata.request_budget == PILOT_BUDGET
    summary = state.finished[0]["summary"]
    assert state.finished[0]["status"] == "completed"
    assert summary["pilot_passed"] is True
    assert summary["planned_condition_count"] == 31
    assert summary["condition_count"] == 31
    assert summary["accepted_condition_count"] == 31
    assert summary["planned_listing_logical_count"] == 93
    assert summary["listing_logical_count"] == 93
    assert summary["listing_attempt_count"] == 93
    assert summary["detail_attempt_count"] == 0
    assert summary["variant_rank"] == 2
    assert summary["endpoint"] == "search"
    assert summary["rcd_type"] is None
    assert summary["reconciliation"] == {
        "rows_seen": 0,
        "rows_created": 0,
        "published_source_job_ids": [],
        "preexisting_staged_source_job_ids": [],
        "created_source_job_ids": [],
        "deferred_identity_conflict_ids": [],
        "distinct_newly_staged": 0,
        "staging_amplification_ratio": 0.0,
        "staging_amplification_within_limit": True,
    }
    assert summary["conservation_difference"] == 0
    assert summary["published_jobs_unchanged"] is True
    assert summary["companies_unchanged"] is True
    assert output == {
        "artifact": str(artifact),
        "run_id": RUN_ID,
        "exit_code": census_cli.EXIT_OK,
        "pilot_passed": True,
        "request_budget": PILOT_BUDGET,
        "condition_count": 31,
        "listing_logical_count": 93,
        "listing_attempt_count": 93,
        "detail_attempt_count": 0,
        "rows_created": 0,
        "conservation_difference": 0,
    }
    manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["metadata"]["experiment"] == "category-pilot"
    assert manifest["metadata"]["pilot_passed"] is True
    assert manifest["metadata"]["variant_rank"] == 2
    assert census_cli.verify_live_research_run(artifact).valid is True


def test_successful_pilot_accepts_natural_exhaustion_below_page_budget(
    tmp_path,
) -> None:
    results = tuple(
        naturally_exhausted_calibration_result(condition)
        for condition in build_pilot_conditions("search", None)
    )
    assert sum(result.pages_observed for result in results) == 62

    exit_code, state, _session, artifact = invoke_pilot(
        tmp_path,
        result=results,
    )

    assert exit_code == census_cli.EXIT_OK
    assert state.finished[0]["summary"]["pilot_passed"] is True
    assert state.finished[0]["summary"]["listing_logical_count"] == 62
    assert census_cli.verify_live_research_run(artifact).valid is True


def test_successful_pilot_reconciles_created_rows_with_snapshot_delta(
    tmp_path,
) -> None:
    exit_code, state, _session, artifact = invoke_pilot(
        tmp_path,
        crawl_runtime_factory=CreatingPilotCrawlRuntime,
        stage_first_row=True,
        drift=True,
    )

    assert exit_code == census_cli.EXIT_OK
    summary = state.finished[0]["summary"]
    assert summary["pilot_passed"] is True
    assert summary["reconciliation"]["rows_seen"] == 1
    assert summary["reconciliation"]["rows_created"] == 1
    assert summary["reconciliation"]["created_source_job_ids"] == ["pilot-created"]
    assert summary["staged_rows_delta"] == 1
    assert summary["conservation_difference"] == 0
    assert census_cli.verify_live_research_run(artifact).valid is True


@pytest.mark.parametrize(
    ("result", "expected_exit", "expected_reason"),
    (
        (
            pilot_results()[:-1],
            census_cli.EXIT_INCOMPLETE,
            "pilot_condition_matrix_mismatch",
        ),
        (
            (*pilot_results()[:-1], pilot_results()[0]),
            census_cli.EXIT_INCOMPLETE,
            "pilot_condition_matrix_mismatch",
        ),
        (
            (
                replace(
                    pilot_results()[0],
                    accepted=False,
                    rejection_reason="listing_gap",
                ),
            ),
            census_cli.EXIT_INCOMPLETE,
            "listing_gap",
        ),
        (
            (
                calibration_result(
                    build_pilot_conditions("search", None)[0],
                    hard_stop="auth_expired",
                ),
            ),
            census_cli.EXIT_HARD_STOP,
            "auth_expired",
        ),
        (
            (
                replace(
                    pilot_results()[0],
                    accepted=False,
                    rejection_reason="identity_issue",
                ),
            ),
            census_cli.EXIT_INCOMPLETE,
            "identity_issue",
        ),
    ),
)
def test_pilot_rejects_missing_duplicate_gap_hard_stop_or_identity_issue(
    tmp_path,
    result: tuple[BoundedConditionResult, ...],
    expected_exit: int,
    expected_reason: str,
) -> None:
    exit_code, state, _session, artifact = invoke_pilot(
        tmp_path,
        result=result,
    )

    assert exit_code == expected_exit
    assert state.finished[0]["summary"]["pilot_passed"] is False
    assert state.finished[0]["summary"]["stop_reason"] == expected_reason
    assert census_cli.verify_live_research_run(artifact).valid is True


def test_pilot_rejects_staging_amplification_as_evidence_failure(tmp_path) -> None:
    exit_code, state, _session, artifact = invoke_pilot(
        tmp_path,
        staging_sink_factory=AmplifiedPilotStagingSink,
    )

    assert exit_code == census_cli.EXIT_EVIDENCE_FAILURE
    summary = state.finished[0]["summary"]
    assert summary["pilot_passed"] is False
    assert summary["stop_reason"] == "staging_amplification"
    assert summary["reconciliation"]["staging_amplification_within_limit"] is False
    assert census_cli.verify_live_research_run(artifact).valid is True


def test_pilot_unexpected_error_exports_type_only_partial_artifact(tmp_path) -> None:
    error = RuntimeError("secret pilot transport text")
    partial = (pilot_results()[0],)

    with pytest.raises(RuntimeError) as captured:
        invoke_pilot(
            tmp_path,
            result=CalibrationFailureAfter(partial, error),
        )

    artifact = tmp_path / "runs" / RUN_ID
    assert captured.value is error
    assert verify_research_artifact(artifact).valid is True
    assert census_cli.verify_live_research_run(artifact).valid is True
    events_text = (artifact / "observations.jsonl").read_text(encoding="utf-8")
    assert "secret pilot transport text" not in events_text
    events = [json.loads(line) for line in events_text.splitlines() if line.strip()]
    summary = events[-1]["payload"]
    assert summary["status"] == "failed"
    assert summary["pilot_passed"] is False
    assert summary["condition_count"] == 1
    assert summary["listing_logical_count"] == 3
    assert summary["stop_reason"] == "unexpected_category_pilot_error:RuntimeError"


def test_pilot_run_end_snapshot_error_exports_verifiable_partial_artifact(
    tmp_path,
) -> None:
    error = RuntimeError("secret pilot snapshot text")

    with pytest.raises(RuntimeError) as captured:
        invoke_pilot(tmp_path, end_snapshot_error=error)

    artifact = tmp_path / "runs" / RUN_ID
    assert captured.value is error
    assert verify_research_artifact(artifact).valid is True
    assert census_cli.verify_live_research_run(artifact).valid is True
    events_text = (artifact / "observations.jsonl").read_text(encoding="utf-8")
    assert "secret pilot snapshot text" not in events_text
    summary = json.loads(events_text.splitlines()[-1])["payload"]
    assert summary["status"] == "failed"
    assert summary["pilot_passed"] is False
    assert summary["stop_reason"] == "unexpected_category_pilot_error:RuntimeError"


@pytest.mark.parametrize(
    ("result", "expected_exit", "expected_reason"),
    (
        (
            (
                replace(
                    calibration_results()[0],
                    accepted=False,
                    rejection_reason="planned_pages_not_observed",
                ),
            ),
            census_cli.EXIT_INCOMPLETE,
            "planned_pages_not_observed",
        ),
        (
            (
                calibration_result(
                    build_calibration_conditions()[0],
                    hard_stop="auth_expired",
                ),
            ),
            census_cli.EXIT_HARD_STOP,
            "auth_expired",
        ),
    ),
)
def test_calibration_maps_incomplete_and_hard_stop_exit_codes(
    tmp_path,
    result: tuple[BoundedConditionResult, ...],
    expected_exit: int,
    expected_reason: str,
) -> None:
    exit_code, state, _session, artifact = invoke_calibrate(
        tmp_path,
        result=result,
    )

    assert exit_code == expected_exit
    assert len(state.calibration_conditions) == 8
    assert state.finished[0]["status"] == "failed"
    assert state.finished[0]["summary"]["calibration_passed"] is False
    assert state.finished[0]["summary"]["stop_reason"] == expected_reason
    assert state.finished[0]["summary"]["condition_count"] == 1
    assert census_cli.verify_live_research_run(artifact).valid is True


@pytest.mark.parametrize(
    ("drift", "product_drift"),
    ((True, False), (False, True)),
)
def test_calibration_product_data_drift_is_an_evidence_failure(
    tmp_path,
    drift: bool,
    product_drift: bool,
) -> None:
    exit_code, state, _session, artifact = invoke_calibrate(
        tmp_path,
        drift=drift,
        product_drift=product_drift,
    )

    assert exit_code == census_cli.EXIT_EVIDENCE_FAILURE
    summary = state.finished[0]["summary"]
    assert summary["calibration_passed"] is False
    assert summary["product_data_unchanged"] is False
    assert summary["stop_reason"] == "product_data_changed"
    assert census_cli.verify_live_research_run(artifact).valid is True


def test_calibration_unexpected_error_exports_type_only_partial_artifact(
    tmp_path,
) -> None:
    error = RuntimeError("secret calibration transport text")
    partial = (calibration_results()[0],)

    with pytest.raises(RuntimeError) as captured:
        invoke_calibrate(
            tmp_path,
            result=CalibrationFailureAfter(partial, error),
        )

    artifact = tmp_path / "runs" / RUN_ID
    assert captured.value is error
    assert verify_research_artifact(artifact).valid is True
    verification = census_cli.verify_live_research_run(artifact)
    assert verification.valid is True
    events_text = (artifact / "observations.jsonl").read_text(encoding="utf-8")
    assert "secret calibration transport text" not in events_text
    events = [json.loads(line) for line in events_text.splitlines() if line.strip()]
    summary = events[-1]["payload"]
    assert summary["status"] == "failed"
    assert summary["calibration_passed"] is False
    assert summary["condition_count"] == 1
    assert summary["listing_logical_count"] == 3
    assert summary["listing_attempt_count"] == 3
    assert summary["stop_reason"] == "unexpected_listing_calibration_error:RuntimeError"


def test_calibration_verify_run_is_network_and_database_free(tmp_path) -> None:
    exit_code, _state, _session, artifact = invoke_calibrate(tmp_path)
    assert exit_code == census_cli.EXIT_OK

    def forbidden(*_args, **_kwargs):
        raise AssertionError("verify-run constructed a live dependency")

    result = census_cli.main(
        ["verify-run", "--artifact", str(artifact)],
        session_factory=forbidden,
        repository=forbidden,
        runtime_factory=forbidden,
        service_factory=forbidden,
        observation_service_factory=forbidden,
    )

    assert result == census_cli.EXIT_OK


def test_calibration_verify_run_rejects_reexported_stop_reason_drift(
    tmp_path,
) -> None:
    hard_stop = calibration_result(
        build_calibration_conditions()[0],
        hard_stop="auth_expired",
    )
    exit_code, _state, _session, artifact = invoke_calibrate(
        tmp_path,
        result=(hard_stop,),
    )
    assert exit_code == census_cli.EXIT_HARD_STOP
    manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (artifact / "observations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    stopped = next(
        event for event in events if event["event_type"] == "research.run_stopped"
    )
    stopped["payload"]["reason"] = "auth_expired:secret-upstream-text"
    reexported = export_research_artifact(
        root=tmp_path / "reexported",
        run_id=RUN_ID,
        metadata=manifest["metadata"],
        events=events,
        provenance=provenance(),
    )

    verification = census_cli.verify_live_research_run(reexported)

    assert verification.valid is False
    assert "run_stopped_summary_reason_mismatch" in verification.issues


@pytest.mark.parametrize(
    ("result", "expected_exit"),
    [
        (execution(target_count=19), census_cli.EXIT_INCOMPLETE),
        (
            execution(detail_classification="auth_expired"),
            census_cli.EXIT_HARD_STOP,
        ),
    ],
)
def test_smoke_maps_incomplete_and_hard_stop_exit_codes(
    tmp_path,
    result: LiveSmokeExecution,
    expected_exit: int,
) -> None:
    exit_code, state, _session, artifact = invoke_smoke(tmp_path, result=result)

    assert exit_code == expected_exit
    assert state.finished[0]["status"] == "failed"
    assert verify_research_artifact(artifact).valid is True


@pytest.mark.parametrize(
    "listing_stop_reason",
    ["auth_expired", "waf_challenge", "ip_blocked", "id_mismatch"],
)
def test_smoke_maps_listing_hard_stops_to_exit_four(
    tmp_path,
    listing_stop_reason: str,
) -> None:
    result = execution(listing_stop_reason=listing_stop_reason)
    assert result.decision.stop_reason == f"listing_{listing_stop_reason}"

    exit_code, state, _session, artifact = invoke_smoke(tmp_path, result=result)

    assert exit_code == census_cli.EXIT_HARD_STOP
    assert state.finished[0]["status"] == "failed"
    assert verify_research_artifact(artifact).valid is True


def test_product_data_drift_is_an_evidence_failure(tmp_path) -> None:
    exit_code, state, _session, artifact = invoke_smoke(tmp_path, drift=True)

    assert exit_code == census_cli.EXIT_EVIDENCE_FAILURE
    assert state.finished[0]["status"] == "failed"
    assert state.finished[0]["summary"]["product_data_unchanged"] is False
    assert verify_research_artifact(artifact).valid is True


def test_product_content_drift_is_an_evidence_failure(tmp_path) -> None:
    exit_code, state, _session, artifact = invoke_smoke(
        tmp_path,
        product_drift=True,
    )

    assert exit_code == census_cli.EXIT_EVIDENCE_FAILURE
    assert state.finished[0]["status"] == "failed"
    assert state.finished[0]["summary"]["product_data_unchanged"] is False
    assert (
        state.finished[0]["summary"]["run_start_product_data_hash"]
        != state.finished[0]["summary"]["run_end_product_data_hash"]
    )
    assert verify_research_artifact(artifact).valid is True


def test_artifact_verification_failure_maps_to_exit_five(tmp_path) -> None:
    def invalid(_path):
        return ArtifactVerificationResult(False, (), ("manifest.json",))

    exit_code, _state, _session, _artifact = invoke_smoke(
        tmp_path,
        artifact_verifier=invalid,
    )

    assert exit_code == census_cli.EXIT_EVIDENCE_FAILURE


@pytest.mark.parametrize(
    "error",
    [TypeError("sensitive payload"), KeyboardInterrupt()],
)
def test_unexpected_base_exception_exports_partial_evidence_then_reraises_same_object(
    tmp_path,
    error: BaseException,
) -> None:
    with pytest.raises(type(error)) as exc_info:
        invoke_smoke(tmp_path, result=error)

    assert exc_info.value is error
    artifact = tmp_path / "runs" / RUN_ID
    assert verify_research_artifact(artifact).valid is True


def test_run_end_snapshot_exception_finalizes_type_only_partial_evidence(
    tmp_path,
) -> None:
    error = RuntimeError("sensitive database details")
    state = State()

    with pytest.raises(RuntimeError) as exc_info:
        invoke_smoke(
            tmp_path,
            end_snapshot_error=error,
            state=state,
        )

    assert exc_info.value is error
    assert state.log.index("browser_close") < state.log.index("finish_run")
    assert state.finished[-1]["status"] == "failed"
    assert (
        state.finished[-1]["error_message"]
        == "unexpected_live_smoke_error:RuntimeError"
    )
    assert "sensitive database details" not in str(state.finished[-1])
    artifact = tmp_path / "runs" / RUN_ID
    verification = census_cli.verify_live_research_run(artifact)
    assert verification.valid is True, verification.issues


@pytest.mark.parametrize("failure_point", ["finish", "event_load"])
def test_post_browser_finalization_failure_retries_type_only_failed_summary(
    tmp_path,
    failure_point: str,
) -> None:
    error = RuntimeError(f"sensitive {failure_point} details")
    state = State()
    if failure_point == "finish":
        state.finish_errors.append(error)
        event_load_errors = None
    else:
        event_load_errors = [error]

    with pytest.raises(RuntimeError) as exc_info:
        invoke_smoke(
            tmp_path,
            event_load_errors=event_load_errors,
            state=state,
        )

    assert exc_info.value is error
    assert state.finished[-1]["status"] == "failed"
    assert (
        state.finished[-1]["error_message"]
        == "unexpected_live_smoke_error:RuntimeError"
    )
    assert f"sensitive {failure_point} details" not in str(state.finished[-1])
    artifact = tmp_path / "runs" / RUN_ID
    verification = census_cli.verify_live_research_run(artifact)
    assert verification.valid is True, verification.issues


def test_help_dispatches_and_offline_cli_does_not_import_live_browser_modules() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "backend")
    help_result = subprocess.run(
        [sys.executable, "backend/scripts/offertoday_research_census.py", "--help"],
        cwd=Path.cwd(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    guard_result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import scripts.offertoday_research; "
                "assert 'scripts.offertoday_research_census' not in sys.modules; "
                "assert 'app.scraper.offertoday_browser_runtime' not in sys.modules"
            ),
        ],
        cwd=Path.cwd(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert help_result.returncode == 0, help_result.stderr
    assert "smoke" in help_result.stdout
    assert "verify-run" in help_result.stdout
    assert guard_result.returncode == 0, guard_result.stderr


def test_live_script_bootstraps_backend_before_app_imports() -> None:
    source = Path(census_cli.__file__).read_text(encoding="utf-8")

    assert source.index("BACKEND =") < source.index("from app.")
