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
from app.scraper.offertoday.category_registry import (
    OFFERTODAY_CATEGORIES_L1,
    OFFERTODAY_CATEGORY_CATALOG_VERSION,
    offertoday_category_catalog_hash,
)
from app.services.offertoday_research_live_service import (
    OfferTodayResearchLiveService,
)
from app.services.offertoday_research_staging_service import (
    OfferTodayReconciledListingStagingSink,
    OfferTodayStagingReconciliation,
    ResearchNoopListingStagingSink,
)
from app.sources.offertoday.listing_contract import (
    OfferTodayListingTransportResult,
    offertoday_endpoint_contract,
)
from app.sources.offertoday.listing_runner import (
    ListingConditionOutcome,
    ListingPageObservation,
    ListingRowEvidence,
    ListingRunResult,
    OfferTodayIdentityPair,
    listing_observation_to_payload,
)
from app.sources.offertoday.research.pagination_stage_gate import (
    PAGINATION_BAKEOFF_REQUEST_BUDGET,
    verify_pagination_artifact,
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
    DiscoveryPolicyCandidateV2,
    LiveSmokeExecution,
)
from app.sources.offertoday.research.phase_d import (
    PHASE_D_CENSUS_EXPERIMENT,
    PHASE_D_FIXED_REPEAT_EXPERIMENT,
    discovery_policy_candidate_artifact_payload,
)
from app.sources.offertoday.research.phase_d_stage_gate import (
    phase_d_artifact_events,
    phase_d_metadata,
)
from app.sources.offertoday.research.pagination_bakeoff import (
    pagination_bakeoff_controls_payload,
    pagination_bakeoff_thresholds_payload,
)
from app.sources.offertoday.research.partition_research import (
    ENDPOINT_PROBE_EXPERIMENT,
    OFFERTODAY_PARTITION_CATALOG,
    PARTITION_PROBE_EXPERIMENT,
    PhaseCConditionEvidence,
    PhaseCPageEvidence,
    PhaseCProbeExecution,
    build_endpoint_probe_plan,
    build_partition_probe_plan,
    offertoday_partition_catalog_hash,
    phase_c_request_policy_hash,
    top_level_partition,
)
from app.sources.offertoday.research.partition_stage_gate import (
    PhaseCArtifactReference,
    PhaseCBaselineReference,
    PhaseCNoWriteEvidence,
    build_partition_comparison_artifact_payload,
    build_partition_probe_parent_projection,
    build_phase_c_probe_artifact_payload,
    phase_c_artifact_reference,
    phase_c_artifact_events,
    phase_c_comparison_metadata,
    phase_c_probe_metadata,
)
from app.sources.offertoday.research.smoke import (
    build_runtime_smoke_condition,
    evaluate_smoke,
)
from test_offertoday_dual_cohort import (
    _complete_candidate as _dual_complete_candidate,
    _complete_run as _dual_complete_run,
    _partial_run as _dual_partial_run,
    _partial_scope as _dual_partial_scope,
    _result_policy as _dual_result_policy,
    _supplemental_probe as _dual_supplemental_probe,
)
from test_offertoday_dual_cohort_stage_gate import (
    _export as _export_dual_cohort_fixture,
    _result_probe_payload as _dual_result_probe_payload,
    _supplemental_probe_payload as _dual_supplemental_probe_payload,
)
from test_offertoday_phase_d import (
    _baseline_reference as _dual_baseline_reference,
)
from test_offertoday_research_live_service import (
    DualCohortRuntimeFactory,
    IncrementingClock,
    _phase_c_no_sleep,
)

RUN_ID = "33333333-3333-3333-3333-333333333333"
CANDIDATE_RUN_ID = "44444444-4444-4444-4444-444444444444"
COMPARISON_RUN_ID = "55555555-5555-5555-5555-555555555555"
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
FIXED_REPEAT_BUDGET = {
    "listing_logical": 1500,
    "listing_attempt_max": 4500,
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


def _saved_session_state(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "saved-session.json"
    cookie_value = hashlib.sha256(str(path.resolve()).encode()).hexdigest()
    path.write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "fixture-session",
                        "value": cookie_value,
                        "domain": ".offertoday.com",
                        "path": "/",
                        "expires": -1,
                        "httpOnly": True,
                        "secure": True,
                        "sameSite": "Lax",
                    }
                ],
                "origins": [],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def _artifact_text(artifact_dir: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(artifact_dir.iterdir())
        if path.is_file()
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


def fixed_repeat_result() -> ListingRunResult:
    completed = full_census_result()
    fixed_category_ids = (118000, 112000, 127000)
    outcomes_by_category = {
        outcome.condition.category_id: outcome
        for outcome in completed.condition_outcomes
    }
    observations_by_category: dict[int, list[ListingPageObservation]] = {}
    pairs_by_job_id = {pair.job_id: pair for pair in completed.id_pairs}
    for observation in completed.observations:
        observations_by_category.setdefault(observation.category_id, []).append(
            observation
        )
    outcomes = tuple(
        outcomes_by_category[category_id] for category_id in fixed_category_ids
    )
    observations = tuple(
        observation
        for category_id in fixed_category_ids
        for observation in observations_by_category[category_id]
    )
    ordered_job_ids = tuple(
        f"census-{category_id}" for category_id in fixed_category_ids
    )
    return replace(
        completed,
        ordered_job_ids=ordered_job_ids,
        accepted_job_ids=ordered_job_ids,
        id_pairs=tuple(pairs_by_job_id[job_id] for job_id in ordered_job_ids),
        observations=observations,
        condition_outcomes=outcomes,
    )


def fixed_repeat_page_cap_result() -> ListingRunResult:
    completed = fixed_repeat_result()
    third_category = 127000
    retained_observations = tuple(
        observation
        for observation in completed.observations
        if observation.category_id != third_category
    )
    third_template = next(
        observation
        for observation in completed.observations
        if observation.category_id == third_category and observation.page == 1
    )
    third_observations = tuple(
        replace(
            third_template,
            page=page,
            request_fingerprint=hashlib.sha256(
                f"{third_template.condition_id}:{page}".encode()
            ).hexdigest(),
            has_more=True,
            stop_reason="page_cap" if page == 500 else None,
        )
        for page in range(1, 501)
    )
    outcomes = (
        *completed.condition_outcomes[:2],
        replace(
            completed.condition_outcomes[2],
            pages_observed=500,
            stop_reason="page_cap",
            is_complete=False,
        ),
    )
    return replace(
        completed,
        observations=(*retained_observations, *third_observations),
        condition_outcomes=outcomes,
        stop_reason="page_cap",
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
        assert str(crawl_job_id) == self.state.expected_run_id
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
        self.pagination_requests: list[dict] = []
        self.expected_run_id = RUN_ID

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

    async def record_page_attempt(self, observation) -> None:
        self.state.append_event(
            "research.page_attempt",
            listing_observation_to_payload(observation),
        )

    async def record_condition_outcome(self, outcome) -> None:
        self.state.append_event(
            (
                "research.condition_completed"
                if outcome.is_complete
                else "research.condition_incomplete"
            ),
            listing_observation_to_payload(outcome),
        )

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


class FakePaginationRuntime:
    def __init__(
        self,
        state: State,
        *,
        missing_cursor: bool = False,
        unexpected_on_request: int | None = None,
        **kwargs,
    ) -> None:
        self.state = state
        self.missing_cursor = missing_cursor
        self.unexpected_on_request = unexpected_on_request
        self.state.runtime_kwargs.append(kwargs)
        self.runtime_index = len(self.state.runtime_kwargs)
        self.browser_context_hash = hashlib.sha256(
            f"pagination-context-{self.runtime_index}".encode()
        ).hexdigest()

    async def __aenter__(self):
        self.state.log.append("browser_open")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.state.log.append("browser_close")
        return None

    async def fetch_listing_page(self, payload, *, listing_url=None):
        if self.unexpected_on_request == len(self.state.pagination_requests) + 1:
            raise RuntimeError("secret runtime failure details")
        self.state.log.append("network")
        self.state.pagination_requests.append(dict(payload))
        category_id = payload["jobFunctionCodes"][0]
        page = payload["page"]
        session_id = payload.get("sessionId") or f"session-{category_id}"
        response_data = {
            "pageSize": 10,
            "sessionId": session_id,
            "supplePage": page,
            "suppleAmount": 0,
            "suppleType": 0,
            "hasMore": False,
            "total": 100,
            "resultList": (
                [
                    {
                        "jobId": f"{category_id}-{payload['pageSize']}",
                        "encryptJobId": (
                            f"enc-{category_id}-{payload['pageSize']}"
                        ),
                        "jobName": "Platform Engineer",
                        "companyName": "Example Technology",
                    }
                ]
                if page == 1
                else []
            ),
            "suppleRcdList": [],
        }
        if self.missing_cursor:
            for field_name in (
                "sessionId",
                "supplePage",
                "suppleAmount",
                "suppleType",
            ):
                response_data.pop(field_name)
        return OfferTodayListingTransportResult(
            payload={"code": 0, "data": response_data},
            browser_context_hash=self.browser_context_hash,
        )


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

    async def run_fixed_repeat(
        self,
        *,
        runtime,
        observation_service,
        candidate,
        staging_sink,
    ) -> ListingRunResult:
        return await self.run_census(
            runtime=runtime,
            observation_service=observation_service,
            candidate=candidate,
            staging_sink=staging_sink,
        )


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


def invoke_fixed_repeat(
    tmp_path: Path,
    *,
    repeat_index: int = 1,
    result: ListingRunResult | CensusFailureAfter | BaseException | None = None,
):
    state = State()
    repeat_result = result or fixed_repeat_result()
    evidence_result = (
        repeat_result.result
        if isinstance(repeat_result, CensusFailureAfter)
        else repeat_result
    )
    if isinstance(evidence_result, BaseException):
        evidence_result = fixed_repeat_result()
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
            "repeat-fixed",
            "--candidate-artifact",
            str(candidate_artifact),
            "--baseline-artifact",
            str(first),
            "--baseline-artifact",
            str(second),
            "--repeat-index",
            str(repeat_index),
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
        service_factory=lambda: FakeCensusLiveService(state, repeat_result),
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
        repeat_result,
    )


def clone_stability_artifact(
    source: Path,
    root: Path,
    *,
    run_id: str,
    captured_at: str,
    repeat_index: int | None = None,
    candidate_hash: str | None = None,
) -> Path:
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    metadata = dict(manifest["metadata"])
    metadata["crawl_job_id"] = run_id
    events = json.loads(
        json.dumps(census_cli._read_jsonl(source / "observations.jsonl"))
    )
    if repeat_index is not None:
        metadata["repeat_index"] = repeat_index
    if candidate_hash is not None:
        metadata["candidate_hash"] = candidate_hash
    for event in events:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        if repeat_index is not None and event.get("event_type") in {
            "research.run_started",
            "research.run_summary",
        }:
            payload["repeat_index"] = repeat_index
        if candidate_hash is not None and "candidate_hash" in payload:
            payload["candidate_hash"] = candidate_hash
    return export_research_artifact(
        root=root,
        run_id=run_id,
        metadata=metadata,
        events=events,
        provenance=provenance(captured_at=captured_at),
    )


def stability_input_artifacts(
    tmp_path: Path,
    *,
    census_times: tuple[str, str, str] = (
        "2026-07-11T00:00:00+00:00",
        "2026-07-11T06:00:00+00:00",
        "2026-07-11T06:10:00+00:00",
    ),
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    census_exit, _state, _session, census_source, _candidate, _result = invoke_census(
        tmp_path / "census-source"
    )
    repeat_exit, _state, _session, repeat_source, _candidate, _result = (
        invoke_fixed_repeat(tmp_path / "fixed-source")
    )
    assert census_exit == census_cli.EXIT_OK
    assert repeat_exit == census_cli.EXIT_OK
    census_candidate_hash = json.loads(
        (census_source / "manifest.json").read_text(encoding="utf-8")
    )["metadata"]["candidate_hash"]
    census_artifacts = tuple(
        clone_stability_artifact(
            census_source,
            tmp_path / "census-inputs",
            run_id=f"10000000-0000-0000-0000-00000000000{index}",
            captured_at=captured_at,
        )
        for index, captured_at in enumerate(census_times, 1)
    )
    fixed_artifacts = tuple(
        clone_stability_artifact(
            repeat_source,
            tmp_path / "fixed-inputs",
            run_id=f"20000000-0000-0000-0000-00000000000{index}",
            captured_at=f"2026-07-11T06:{20 + index:02d}:00+00:00",
            repeat_index=index,
            candidate_hash=census_candidate_hash,
        )
        for index in range(1, 4)
    )
    return census_artifacts, fixed_artifacts


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
    repeat_fixed = parser.parse_args(
        [
            "repeat-fixed",
            "--candidate-artifact",
            "candidate",
            "--baseline-artifact",
            "first",
            "--baseline-artifact",
            "second",
            "--repeat-index",
            "2",
        ]
    )
    compare = parser.parse_args(
        [
            "compare",
            "--census-artifact",
            "c1",
            "--census-artifact",
            "c2",
            "--census-artifact",
            "c3",
            "--fixed-repeat-artifact",
            "f1",
            "--fixed-repeat-artifact",
            "f2",
            "--fixed-repeat-artifact",
            "f3",
        ]
    )
    verify = parser.parse_args(["verify-run", "--artifact", "run"])
    freeze = parser.parse_args(["freeze-candidate", "--pilot-artifact", "pilot"])
    first_partition_id = OFFERTODAY_PARTITION_CATALOG[0].partition_id
    probe_endpoints = parser.parse_args(
        [
            "probe-endpoints",
            "--phase-b-comparison-artifact",
            "phase-b",
            "--endpoint-contract-id",
            "recommend-search-list-v1",
            "--endpoint-contract-id",
            "recommend-list-envelope-v1",
            "--baseline-artifact",
            "first",
            "--baseline-artifact",
            "second",
            "--confirm-live-research",
            "--auth-state",
            "saved-session.json",
        ]
    )
    probe_partitions = parser.parse_args(
        [
            "probe-partitions",
            "--endpoint-probe-artifact",
            "endpoint-probe",
            "--endpoint-contract-id",
            "recommend-search-list-v1",
            "--partition-id",
            first_partition_id,
            "--max-pages-per-condition",
            "10",
            "--baseline-artifact",
            "first",
            "--baseline-artifact",
            "second",
            "--confirm-live-research",
            "--auth-state",
            "saved-session.json",
        ]
    )
    compare_partitions = parser.parse_args(
        [
            "compare-partitions",
            "--partition-probe-artifact",
            "partition-probe",
        ]
    )
    freeze_policy = parser.parse_args(
        [
            "freeze-discovery-policy",
            "--phase-b-comparison-artifact",
            "phase-b",
            "--endpoint-probe-artifact",
            "endpoint",
            "--partition-probe-artifact",
            "partition",
            "--partition-comparison-artifact",
            "comparison",
        ]
    )
    census_v2 = parser.parse_args(
        [
            "census-v2",
            "--candidate-artifact",
            "candidate-v2",
            "--baseline-artifact",
            "first",
            "--baseline-artifact",
            "second",
            "--run-index",
            "1",
            "--window-id",
            "window-a",
            "--staging-mode",
            "noop",
            "--confirm-live-research",
            "--auth-state",
            "saved-session.json",
        ]
    )
    compare_v2 = parser.parse_args(
        [
            "compare-stability-v2",
            "--census-artifact",
            "c1",
            "--census-artifact",
            "c2",
            "--census-artifact",
            "c3",
            "--fixed-repeat-artifact",
            "f1",
            "--fixed-repeat-artifact",
            "f2",
            "--fixed-repeat-artifact",
            "f3",
        ]
    )

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
    assert repeat_fixed.command == "repeat-fixed"
    assert repeat_fixed.candidate_artifact == Path("candidate")
    assert repeat_fixed.baseline_artifact == [Path("first"), Path("second")]
    assert repeat_fixed.repeat_index == 2
    assert compare.command == "compare"
    assert compare.census_artifact == [Path("c1"), Path("c2"), Path("c3")]
    assert compare.fixed_repeat_artifact == [Path("f1"), Path("f2"), Path("f3")]
    assert verify.command == "verify-run"
    assert freeze.command == "freeze-candidate"
    assert freeze.pilot_artifact == Path("pilot")
    assert probe_endpoints.command == "probe-endpoints"
    assert probe_endpoints.confirm_live_research is True
    assert probe_endpoints.auth_state == Path("saved-session.json")
    assert probe_endpoints.endpoint_contract_id == [
        "recommend-search-list-v1",
        "recommend-list-envelope-v1",
    ]
    assert probe_partitions.command == "probe-partitions"
    assert probe_partitions.auth_state == Path("saved-session.json")
    assert probe_partitions.partition_id == [first_partition_id]
    assert probe_partitions.max_pages_per_condition == 10
    assert compare_partitions.command == "compare-partitions"
    assert compare_partitions.partition_probe_artifact == [Path("partition-probe")]
    assert freeze_policy.command == "freeze-discovery-policy"
    assert freeze_policy.partition_probe_artifact == [Path("partition")]
    assert census_v2.command == "census-v2"
    assert census_v2.run_index == 1
    assert census_v2.window_id == "window-a"
    assert census_v2.confirm_live_research is True
    assert census_v2.auth_state == Path("saved-session.json")
    assert compare_v2.command == "compare-stability-v2"
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


def test_repeat_fixed_accepts_only_frozen_three_condition_exhaustion(
    tmp_path,
    capsys,
) -> None:
    exit_code, state, session, artifact, candidate_artifact, result = (
        invoke_fixed_repeat(tmp_path, repeat_index=2)
    )
    output = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
    events = census_cli._read_jsonl(artifact / "observations.jsonl")
    summary = next(
        event["payload"]
        for event in events
        if event["event_type"] == "research.run_summary"
    )
    candidate_payload = json.loads(
        (candidate_artifact / "candidate.json").read_text(encoding="utf-8")
    )

    assert exit_code == census_cli.EXIT_OK
    assert session.closed is True
    assert state.runtime_kwargs == [{"headed": False}]
    assert summary["fixed_repeat_passed"] is True
    assert summary["repeat_index"] == 2
    assert summary["condition_count"] == 3
    assert summary["natural_exhaustion_count"] == 3
    assert summary["request_budget"] == FIXED_REPEAT_BUDGET
    assert summary["candidate_hash"] == candidate_payload["candidate_hash"]
    assert summary["detail_attempt_count"] == 0
    assert summary["ordered_job_id_hash"] == ordered_id_hash(result.accepted_job_ids)
    assert [item["category_id"] for item in summary["condition_outcomes"]] == [
        118000,
        112000,
        127000,
    ]
    assert manifest["metadata"]["experiment"] == "fixed-condition-repeat"
    assert manifest["metadata"]["crawl_job_status"] == "completed"
    assert manifest["metadata"]["fixed_repeat_passed"] is True
    assert manifest["metadata"]["repeat_index"] == 2
    assert output["fixed_repeat_passed"] is True
    assert output["condition_count"] == 3
    assert output["natural_exhaustion_count"] == 3
    assert output["request_budget"] == FIXED_REPEAT_BUDGET
    assert verify_research_artifact(artifact).valid is True
    assert census_cli.verify_live_research_run(artifact).valid is True


def test_repeat_fixed_page_cap_is_incomplete_and_still_verifies(
    tmp_path,
    capsys,
) -> None:
    exit_code, _state, _session, artifact, _candidate, _result = invoke_fixed_repeat(
        tmp_path, result=fixed_repeat_page_cap_result()
    )
    output = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    events = census_cli._read_jsonl(artifact / "observations.jsonl")
    summary = events[-1]["payload"]

    assert exit_code == census_cli.EXIT_INCOMPLETE
    assert output["fixed_repeat_passed"] is False
    assert summary["fixed_repeat_passed"] is False
    assert summary["stop_reason"] == "page_cap"
    assert census_cli.verify_live_research_run(artifact).valid is True


def test_repeat_fixed_unexpected_error_preserves_partial_verified_artifact(
    tmp_path,
) -> None:
    error = RuntimeError("secret upstream text")
    artifact = tmp_path / "runs" / RUN_ID

    with pytest.raises(RuntimeError) as raised:
        invoke_fixed_repeat(tmp_path, result=error)

    assert raised.value is error
    events = census_cli._read_jsonl(artifact / "observations.jsonl")
    summary = events[-1]["payload"]
    assert summary["fixed_repeat_passed"] is False
    assert summary["stop_reason"] == (
        "unexpected_fixed_condition_repeat_error:RuntimeError"
    )
    assert "secret upstream text" not in json.dumps(events)
    assert census_cli.verify_live_research_run(artifact).valid is True


def test_compare_recomputes_six_artifacts_without_live_dependencies(
    tmp_path,
    capsys,
) -> None:
    census_artifacts, fixed_artifacts = stability_input_artifacts(tmp_path)
    live_calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        live_calls.append("live_dependency")
        raise AssertionError("compare constructed a live dependency")

    arguments = [
        "compare",
        "--run-id",
        COMPARISON_RUN_ID,
        "--repo-root",
        str(Path.cwd()),
        "--artifact-root",
        str(tmp_path / "comparison-runs"),
    ]
    for artifact in census_artifacts:
        arguments.extend(("--census-artifact", str(artifact)))
    for artifact in fixed_artifacts:
        arguments.extend(("--fixed-repeat-artifact", str(artifact)))

    exit_code = census_cli.main(
        arguments,
        session_factory=forbidden,
        repository=forbidden,
        runtime_factory=forbidden,
        service_factory=forbidden,
        observation_service_factory=forbidden,
        crawl_runtime_factory=forbidden,
        staging_sink_factory=forbidden,
        provenance_provider=provenance,
    )

    output = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    artifact = tmp_path / "comparison-runs" / COMPARISON_RUN_ID
    manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
    events = census_cli._read_jsonl(artifact / "observations.jsonl")
    summary = events[-1]["payload"]

    assert exit_code == census_cli.EXIT_OK
    assert live_calls == []
    assert manifest["metadata"]["experiment"] == "census-stability-comparison"
    assert manifest["metadata"]["plan3_entry_accepted"] is True
    assert manifest["metadata"]["candidate_hash"] == summary["candidate_hash"]
    assert summary["comparison_completed"] is True
    assert summary["census_window_span_seconds"] == 22_200.0
    assert summary["fixed_window_span_seconds"] == 120.0
    assert summary["fixed_cohort_jaccard"] == 1.0
    assert summary["unique_count_cv"] == 0.0
    assert summary["failing_gates"] == []
    assert len(summary["census_runs"]) == 3
    assert len(summary["fixed_repeat_runs"]) == 3
    assert output["plan3_entry_accepted"] is True
    assert output["failing_gates"] == []
    assert verify_research_artifact(artifact).valid is True
    assert census_cli.verify_live_research_run(artifact).valid is True

    tampered_events = json.loads(json.dumps(events))
    tampered_events[-1]["payload"]["fixed_cohort_jaccard"] = 0.5
    tampered = export_research_artifact(
        root=tmp_path / "tampered-comparison",
        run_id=COMPARISON_RUN_ID,
        metadata=manifest["metadata"],
        events=tampered_events,
        provenance=provenance(),
    )
    tampered_check = census_cli.verify_live_research_run(tampered)
    assert tampered_check.valid is False
    assert "comparison_fixed_cohort_jaccard_mismatch" in tampered_check.issues


def test_compare_rejects_a_single_census_window_before_export(tmp_path) -> None:
    census_artifacts, fixed_artifacts = stability_input_artifacts(
        tmp_path,
        census_times=(
            "2026-07-11T00:00:00+00:00",
            "2026-07-11T01:00:00+00:00",
            "2026-07-11T02:00:00+00:00",
        ),
    )

    with pytest.raises(ValueError, match="at least six hours"):
        census_cli._load_stability_inputs(census_artifacts, fixed_artifacts)


def test_compare_rejects_candidate_hash_drift(tmp_path) -> None:
    census_artifacts, fixed_artifacts = stability_input_artifacts(tmp_path)
    drifted = clone_stability_artifact(
        census_artifacts[-1],
        tmp_path / "candidate-drift",
        run_id="30000000-0000-0000-0000-000000000001",
        captured_at="2026-07-11T06:10:00+00:00",
        candidate_hash="f" * 64,
    )

    with pytest.raises(ValueError, match="one candidate hash"):
        census_cli._load_stability_inputs(
            (*census_artifacts[:-1], drifted),
            fixed_artifacts,
        )


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


def test_pagination_bakeoff_current_database_drift_stops_before_browser(
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

    result = census_cli.main(
        [
            "pagination-bakeoff",
            "--repeat-index",
            "1",
            "--order-seed",
            "20260713",
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
        runtime_factory=lambda **kwargs: FakePaginationRuntime(state, **kwargs),
    )

    assert result == census_cli.EXIT_EVIDENCE_FAILURE
    assert state.runtime_kwargs == []
    assert "browser_open" not in state.log
    assert "network" not in state.log


def test_pagination_bakeoff_live_command_persists_exact_budget_and_strict_artifact(
    tmp_path,
    capsys,
) -> None:
    baselines = tmp_path / "baselines"
    first = baseline_artifact(baselines, BASELINE_RUN_1)
    second = baseline_artifact(baselines, BASELINE_RUN_2)
    state = State()

    async def no_sleep(_seconds: float) -> None:
        return None

    result = census_cli.main(
        [
            "pagination-bakeoff",
            "--repeat-index",
            "1",
            "--order-seed",
            "20260713",
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
        runtime_factory=lambda **kwargs: FakePaginationRuntime(state, **kwargs),
        service_factory=lambda: OfferTodayResearchLiveService(sleep=no_sleep),
        observation_service_factory=lambda db: FakeObservationService(db, state),
        provenance_provider=provenance,
    )
    output = json.loads(capsys.readouterr().out)
    artifact = Path(output["artifact"])
    manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
    payload = json.loads((artifact / "bakeoff.json").read_text(encoding="utf-8"))
    summary = state.finished[-1]["summary"]

    assert result == census_cli.EXIT_OK
    assert output["exit_code"] == census_cli.EXIT_OK
    assert output["logical_listing_requests"] == 30
    assert output["physical_listing_attempts"] == 30
    assert state.created_metadata.request_budget == PAGINATION_BAKEOFF_REQUEST_BUDGET
    assert manifest["metadata"]["request_budget"] == (
        PAGINATION_BAKEOFF_REQUEST_BUDGET
    )
    assert summary["request_budget"] == PAGINATION_BAKEOFF_REQUEST_BUDGET
    assert summary["detail_attempts"] == 0
    assert summary["product_writes"] == 0
    assert summary["product_data_unchanged"] is True
    assert payload["controls"] == pagination_bakeoff_controls_payload()
    assert payload["thresholds"] == pagination_bakeoff_thresholds_payload()
    assert verify_pagination_artifact(artifact).valid is True


def test_pagination_bakeoff_hard_stop_exports_valid_partial_artifact(
    tmp_path,
    capsys,
) -> None:
    baselines = tmp_path / "baselines"
    first = baseline_artifact(baselines, BASELINE_RUN_1)
    second = baseline_artifact(baselines, BASELINE_RUN_2)
    state = State()

    async def no_sleep(_seconds: float) -> None:
        return None

    result = census_cli.main(
        [
            "pagination-bakeoff",
            "--repeat-index",
            "1",
            "--order-seed",
            "20260713",
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
        runtime_factory=lambda **kwargs: FakePaginationRuntime(
            state,
            missing_cursor=True,
            **kwargs,
        ),
        service_factory=lambda: OfferTodayResearchLiveService(sleep=no_sleep),
        observation_service_factory=lambda db: FakeObservationService(db, state),
        provenance_provider=provenance,
    )
    output = json.loads(capsys.readouterr().out)
    artifact = Path(output["artifact"])
    payload = json.loads((artifact / "bakeoff.json").read_text(encoding="utf-8"))

    assert result == census_cli.EXIT_HARD_STOP
    assert output["exit_code"] == census_cli.EXIT_HARD_STOP
    assert output["failure_reason"] == "hard_stop:cursor_contract_violation"
    assert payload["status"] == "failed"
    assert 0 < len(payload["executions"]) < len(payload["order"])
    assert state.finished[-1]["status"] == "failed"
    assert verify_pagination_artifact(artifact).valid is True


def test_pagination_bakeoff_unexpected_error_exports_type_only_partial_artifact(
    tmp_path,
    capsys,
) -> None:
    baselines = tmp_path / "baselines"
    first = baseline_artifact(baselines, BASELINE_RUN_1)
    second = baseline_artifact(baselines, BASELINE_RUN_2)
    state = State()

    async def no_sleep(_seconds: float) -> None:
        return None

    result = census_cli.main(
        [
            "pagination-bakeoff",
            "--repeat-index",
            "1",
            "--order-seed",
            "20260713",
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
        runtime_factory=lambda **kwargs: FakePaginationRuntime(
            state,
            unexpected_on_request=5,
            **kwargs,
        ),
        service_factory=lambda: OfferTodayResearchLiveService(sleep=no_sleep),
        observation_service_factory=lambda db: FakeObservationService(db, state),
        provenance_provider=provenance,
    )
    output = json.loads(capsys.readouterr().out)
    artifact = Path(output["artifact"])
    payload = json.loads((artifact / "bakeoff.json").read_text(encoding="utf-8"))

    assert result == census_cli.EXIT_HARD_STOP
    assert output["exit_code"] == census_cli.EXIT_HARD_STOP
    assert output["failure_reason"] == (
        "unexpected_pagination_bakeoff_error:RuntimeError"
    )
    assert "secret runtime failure details" not in json.dumps(output)
    assert payload["status"] == "failed"
    assert 0 < len(payload["executions"]) < len(payload["order"])
    assert verify_pagination_artifact(artifact).valid is True


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
    assert "probe-endpoints" in help_result.stdout
    assert "probe-partitions" in help_result.stdout
    assert "compare-partitions" in help_result.stdout
    assert guard_result.returncode == 0, guard_result.stderr


def test_live_script_bootstraps_backend_before_app_imports() -> None:
    source = Path(census_cli.__file__).read_text(encoding="utf-8")

    assert source.index("BACKEND =") < source.index("from app.")
    assert "offertoday_endpoint_probe" not in source


def _phase_c_page(
    *,
    label: str,
    page: int,
    job_ids: tuple[str, ...],
    terminal_signal: bool,
) -> PhaseCPageEvidence:
    return PhaseCPageEvidence(
        page=page,
        attempt=1,
        classification="success",
        stop_reason="natural_exhaustion" if terminal_signal else None,
        logical_request_id=hashlib.sha256(f"logical:{label}:{page}".encode()).hexdigest(),
        physical_attempt_id=hashlib.sha256(
            f"physical:{label}:{page}".encode()
        ).hexdigest(),
        result_job_ids=job_ids,
        supplemental_job_ids=(),
        terminal_signal=terminal_signal,
        awaiting_empty_confirmation=False,
        contract_error=None,
        reported_total=1_000_000,
    )


def _phase_c_condition(
    *,
    partition_id: str,
    endpoint_contract_id: str,
    label: str,
    accepted: bool,
) -> PhaseCConditionEvidence:
    contract = offertoday_endpoint_contract(endpoint_contract_id)
    if accepted:
        pages = (
            _phase_c_page(
                label=label,
                page=1,
                job_ids=(f"job-{label}",),
                terminal_signal=False,
            ),
            _phase_c_page(
                label=label,
                page=2,
                job_ids=(),
                terminal_signal=True,
            ),
        )
    else:
        pages = (
            _phase_c_page(
                label=label,
                page=1,
                job_ids=(f"job-{label}",),
                terminal_signal=False,
            ),
        )
    contract_verified = accepted and contract.cursor_verified and contract.terminal_verified
    return PhaseCConditionEvidence(
        partition_id=partition_id,
        endpoint_contract_id=endpoint_contract_id,
        endpoint_contract_hash=contract.contract_hash,
        condition_id=hashlib.sha256(f"condition:{label}".encode()).hexdigest(),
        stop_reason="natural_exhaustion" if accepted else "page_cap",
        is_complete=accepted,
        contract_verified=contract_verified,
        terminal_confirmed=contract_verified,
        empty_confirmation=accepted,
        gap_count=0,
        identity_conflict_count=0,
        identity_issue_count=0,
        conservation_difference=0,
        pages=pages,
    )


def _phase_c_endpoint_execution(plan) -> PhaseCProbeExecution:
    partition_id = top_level_partition(plan.category_code).partition_id
    search_condition = replace(
        _phase_c_condition(
            partition_id=partition_id,
            endpoint_contract_id="recommend-search-list-v1",
            label="endpoint-search",
            accepted=False,
        ),
        contract_verified=True,
        pages=tuple(
            _phase_c_page(
                label="endpoint-search",
                page=page,
                job_ids=(f"job-endpoint-search-{page}",),
                terminal_signal=False,
            )
            for page in range(1, plan.max_pages_per_contract + 1)
        ),
    )
    browse_condition = replace(
        _phase_c_condition(
            partition_id=partition_id,
            endpoint_contract_id="recommend-list-envelope-v1",
            label="endpoint-browse",
            accepted=False,
        ),
        pages=tuple(
            _phase_c_page(
                label="endpoint-browse",
                page=page,
                job_ids=(f"job-endpoint-browse-{page}",),
                terminal_signal=False,
            )
            for page in range(1, plan.max_pages_per_contract + 1)
        ),
    )
    return PhaseCProbeExecution(
        experiment=ENDPOINT_PROBE_EXPERIMENT,
        plan=plan,
        conditions=(search_condition, browse_condition),
    )


def _phase_c_partition_execution(
    plan,
    *,
    accepted: bool = True,
) -> PhaseCProbeExecution:
    return PhaseCProbeExecution(
        experiment=PARTITION_PROBE_EXPERIMENT,
        plan=plan,
        conditions=tuple(
            _phase_c_condition(
                partition_id=partition_id,
                endpoint_contract_id=plan.endpoint_contract_id,
                label=f"partition-{index}",
                accepted=accepted,
            )
            for index, partition_id in enumerate(plan.partition_ids, start=1)
        ),
    )


class FakePhaseCLiveService:
    def __init__(self, state: State, *, accepted_partitions: bool = True) -> None:
        self.state = state
        self.accepted_partitions = accepted_partitions

    async def run_endpoint_probe(
        self,
        *,
        runtime_factory,
        observation_service,
        plan,
        staging_sink,
    ) -> PhaseCProbeExecution:
        runtime_factory(headed=False)
        self.state.log.append("network")
        self.state.staging_sink = staging_sink
        self.state.phase_c_plan = plan
        assert observation_service.crawl_job_id == UUID(RUN_ID)
        return _phase_c_endpoint_execution(plan)

    async def run_partition_probe(
        self,
        *,
        runtime_factory,
        observation_service,
        plan,
        staging_sink,
    ) -> PhaseCProbeExecution:
        runtime_factory(headed=False)
        self.state.log.append("network")
        self.state.staging_sink = staging_sink
        self.state.phase_c_plan = plan
        assert observation_service.crawl_job_id == UUID(RUN_ID)
        return _phase_c_partition_execution(
            plan,
            accepted=self.accepted_partitions,
        )


def _phase_b_reference() -> PhaseCArtifactReference:
    return PhaseCArtifactReference(
        experiment="cursor-pagination-comparison-v2",
        run_id="77777777-7777-7777-7777-777777777777",
        manifest_hash="7" * 64,
        payload_hash="8" * 64,
        accepted=False,
    )


def _endpoint_probe_reference() -> PhaseCArtifactReference:
    return PhaseCArtifactReference(
        experiment=ENDPOINT_PROBE_EXPERIMENT,
        run_id="88888888-8888-8888-8888-888888888888",
        manifest_hash="9" * 64,
        payload_hash="0" * 64,
        accepted=False,
    )


def test_phase_c_parser_requires_confirmation_auth_state_and_partition_selection() -> (
    None
):
    parser = census_cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "probe-endpoints",
                "--phase-b-comparison-artifact",
                "phase-b",
                "--endpoint-contract-id",
                "recommend-search-list-v1",
                "--endpoint-contract-id",
                "recommend-list-envelope-v1",
                "--baseline-artifact",
                "first",
                "--baseline-artifact",
                "second",
                "--auth-state",
                "saved-session.json",
            ]
        )
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "probe-partitions",
                "--endpoint-probe-artifact",
                "endpoint",
                "--endpoint-contract-id",
                "recommend-search-list-v1",
                "--max-pages-per-condition",
                "3",
                "--baseline-artifact",
                "first",
                "--baseline-artifact",
                "second",
                "--confirm-live-research",
                "--auth-state",
                "saved-session.json",
            ]
        )
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "probe-endpoints",
                "--phase-b-comparison-artifact",
                "phase-b",
                "--endpoint-contract-id",
                "recommend-search-list-v1",
                "--endpoint-contract-id",
                "recommend-list-envelope-v1",
                "--baseline-artifact",
                "first",
                "--baseline-artifact",
                "second",
                "--confirm-live-research",
            ]
        )


@pytest.mark.parametrize(
    "argv",
    (
        [
            "probe-endpoints",
            "--phase-b-comparison-artifact",
            "phase-b",
            "--endpoint-contract-id",
            "recommend-search-list-v1",
            "--endpoint-contract-id",
            "recommend-list-envelope-v1",
            "--baseline-artifact",
            "first",
            "--baseline-artifact",
            "second",
            "--confirm-live-research",
        ],
        [
            "census-v2",
            "--candidate-artifact",
            "candidate",
            "--baseline-artifact",
            "first",
            "--baseline-artifact",
            "second",
            "--run-index",
            "1",
            "--window-id",
            "window-a",
            "--staging-mode",
            "noop",
            "--confirm-live-research",
        ],
    ),
)
def test_saved_session_live_commands_require_auth_state_before_dependencies(
    argv: list[str],
) -> None:
    calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        calls.append("dependency")
        raise AssertionError("missing auth state constructed a dependency")

    with pytest.raises(SystemExit) as exc_info:
        census_cli.main(
            argv,
            session_factory=forbidden,
            repository=forbidden,
            runtime_factory=forbidden,
            service_factory=forbidden,
            observation_service_factory=forbidden,
            crawl_runtime_factory=forbidden,
            staging_sink_factory=forbidden,
        )

    assert exc_info.value.code == census_cli.EXIT_USAGE
    assert calls == []


@pytest.mark.parametrize(
    "argv",
    (
        [
            "probe-endpoints",
            "--phase-b-comparison-artifact",
            "phase-b",
            "--endpoint-contract-id",
            "recommend-search-list-v1",
            "--endpoint-contract-id",
            "recommend-list-envelope-v1",
            "--baseline-artifact",
            "first",
            "--baseline-artifact",
            "second",
            "--confirm-live-research",
        ],
        [
            "repeat-fixed-v2",
            "--candidate-artifact",
            "candidate",
            "--baseline-artifact",
            "first",
            "--baseline-artifact",
            "second",
            "--run-index",
            "1",
            "--window-id",
            "window-a",
            "--staging-mode",
            "noop",
            "--confirm-live-research",
        ],
    ),
)
def test_saved_session_live_commands_reject_invalid_state_before_dependencies(
    tmp_path: Path,
    capsys,
    argv: list[str],
) -> None:
    calls: list[str] = []
    invalid_state = tmp_path / "invalid-session.json"
    invalid_state.write_text('{"cookies": []}', encoding="utf-8")

    def forbidden(*_args, **_kwargs):
        calls.append("dependency")
        raise AssertionError("invalid auth state constructed a dependency")

    result = census_cli.main(
        [*argv, "--auth-state", str(invalid_state)],
        session_factory=forbidden,
        repository=forbidden,
        runtime_factory=forbidden,
        service_factory=forbidden,
        observation_service_factory=forbidden,
        crawl_runtime_factory=forbidden,
        staging_sink_factory=forbidden,
    )

    error = json.loads(capsys.readouterr().err)
    assert result == census_cli.EXIT_EVIDENCE_FAILURE
    assert error == {
        "error": "auth state must be a readable valid Playwright storage-state JSON file"
    }
    assert str(invalid_state) not in json.dumps(error)
    assert calls == []


def test_saved_session_runtime_binding_rechecks_validated_bytes(tmp_path: Path) -> None:
    auth_state = _saved_session_state(tmp_path / "auth")
    saved_session = census_cli._require_saved_session_state(auth_state)
    runtime_calls: list[dict] = []
    runtime_factory = census_cli._bind_saved_session_runtime_factory(
        lambda **kwargs: runtime_calls.append(kwargs),
        saved_session,
    )
    changed_payload = json.loads(auth_state.read_text(encoding="utf-8"))
    changed_payload["cookies"][0]["value"] = "changed-after-validation"
    auth_state.write_text(json.dumps(changed_payload), encoding="utf-8")

    with pytest.raises(ValueError, match="auth state changed after validation"):
        runtime_factory(headed=False)

    assert runtime_calls == []


def test_probe_endpoints_requires_two_baselines_before_any_dependency(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    auth_state = _saved_session_state(tmp_path / "auth")

    def forbidden(*_args, **_kwargs):
        calls.append("dependency")
        raise AssertionError("Phase C constructed a dependency before baseline count")

    result = census_cli.main(
        [
            "probe-endpoints",
            "--phase-b-comparison-artifact",
            str(tmp_path / "missing-parent"),
            "--endpoint-contract-id",
            "recommend-search-list-v1",
            "--endpoint-contract-id",
            "recommend-list-envelope-v1",
            "--baseline-artifact",
            str(tmp_path / "only-one"),
            "--confirm-live-research",
            "--auth-state",
            str(auth_state),
        ],
        session_factory=forbidden,
        repository=forbidden,
        runtime_factory=forbidden,
        service_factory=forbidden,
        observation_service_factory=forbidden,
    )

    assert result == census_cli.EXIT_USAGE
    assert calls == []


def test_probe_endpoints_invalid_parent_is_evidence_failure_not_usage(
    tmp_path: Path,
) -> None:
    auth_state = _saved_session_state(tmp_path / "auth")
    result = census_cli.main(
        [
            "probe-endpoints",
            "--phase-b-comparison-artifact",
            str(tmp_path / "missing-parent"),
            "--endpoint-contract-id",
            "recommend-search-list-v1",
            "--endpoint-contract-id",
            "recommend-list-envelope-v1",
            "--baseline-artifact",
            str(tmp_path / "missing-baseline-one"),
            "--baseline-artifact",
            str(tmp_path / "missing-baseline-two"),
            "--confirm-live-research",
            "--auth-state",
            str(auth_state),
        ]
    )

    assert result == census_cli.EXIT_EVIDENCE_FAILURE


def test_probe_endpoints_exports_strict_inconclusive_no_write_artifact(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    baselines = tmp_path / "baselines"
    first = baseline_artifact(baselines, BASELINE_RUN_1)
    second = baseline_artifact(baselines, BASELINE_RUN_2)
    auth_state = _saved_session_state(tmp_path / "auth")
    state = State()
    runtime_calls: list[dict] = []
    monkeypatch.setattr(
        census_cli,
        "_phase_b_comparison_reference",
        lambda _path: _phase_b_reference(),
    )

    result = census_cli.main(
        [
            "probe-endpoints",
            "--phase-b-comparison-artifact",
            str(tmp_path / "phase-b"),
            "--endpoint-contract-id",
            "recommend-search-list-v1",
            "--endpoint-contract-id",
            "recommend-list-envelope-v1",
            "--baseline-artifact",
            str(first),
            "--baseline-artifact",
            str(second),
            "--confirm-live-research",
            "--auth-state",
            str(auth_state),
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
        service_factory=lambda: FakePhaseCLiveService(state),
        observation_service_factory=lambda db: FakeObservationService(db, state),
        provenance_provider=provenance,
    )
    output = json.loads(capsys.readouterr().out)
    artifact = Path(output["artifact"])
    payload = json.loads((artifact / "endpoint-probe.json").read_text())

    assert result == census_cli.EXIT_INCOMPLETE
    assert output["accepted"] is False
    assert output["candidate_frozen"] is False
    assert payload["execution"]["accepted"] is False
    assert payload["no_write"]["product_data_unchanged"] is True
    assert payload["no_write"]["product_writes"] == 0
    assert payload["no_write"]["detail_attempts"] == 0
    assert state.created_metadata.request_budget == {
        "listing_logical": 6,
        "listing_attempt_max": 18,
        "detail": 0,
        "product_writes": 0,
    }
    assert isinstance(state.staging_sink, ResearchNoopListingStagingSink)
    assert state.log.index("product_snapshot_1") < state.log.index("network")
    assert runtime_calls == [
        {"auth_state_path": str(auth_state.resolve()), "headed": False}
    ]
    manifest = json.loads((artifact / "manifest.json").read_text())
    artifact_text = _artifact_text(artifact)
    cookie_value = json.loads(auth_state.read_text())["cookies"][0]["value"]
    assert manifest["provenance"]["runtime_context"]["session_state_sha256"] == (
        hashlib.sha256(auth_state.read_bytes()).hexdigest()
    )
    assert str(auth_state.resolve()) not in artifact_text
    assert cookie_value not in artifact_text
    assert census_cli.verify_live_research_run(artifact).valid is True


def test_probe_partitions_accepts_explicit_inputs_and_strict_replays(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    baselines = tmp_path / "baselines"
    first = baseline_artifact(baselines, BASELINE_RUN_1)
    second = baseline_artifact(baselines, BASELINE_RUN_2)
    auth_state = _saved_session_state(tmp_path / "auth")
    state = State()
    partition_ids = [
        OFFERTODAY_PARTITION_CATALOG[0].partition_id,
        OFFERTODAY_PARTITION_CATALOG[1].partition_id,
    ]
    monkeypatch.setattr(
        census_cli,
        "phase_c_artifact_reference",
        lambda _path: _endpoint_probe_reference(),
    )

    result = census_cli.main(
        [
            "probe-partitions",
            "--endpoint-probe-artifact",
            str(tmp_path / "endpoint-parent"),
            "--endpoint-contract-id",
            "recommend-search-list-v1",
            "--partition-id",
            partition_ids[1],
            "--partition-id",
            partition_ids[0],
            "--max-pages-per-condition",
            "3",
            "--baseline-artifact",
            str(first),
            "--baseline-artifact",
            str(second),
            "--confirm-live-research",
            "--auth-state",
            str(auth_state),
            "--run-id",
            RUN_ID,
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
        ],
        session_factory=lambda: FakeSession(state.log),
        repository=FakeRepository(state),
        runtime_factory=lambda **_kwargs: None,
        service_factory=lambda: FakePhaseCLiveService(state),
        observation_service_factory=lambda db: FakeObservationService(db, state),
        provenance_provider=provenance,
    )
    output = json.loads(capsys.readouterr().out)
    artifact = Path(output["artifact"])
    payload = json.loads((artifact / "partition-probe.json").read_text())

    assert result == census_cli.EXIT_OK
    assert output["accepted"] is True
    assert payload["execution"]["plan"]["partition_ids"] == partition_ids
    assert payload["candidate_frozen"] is False
    assert census_cli.verify_live_research_run(artifact).valid is True


def test_probe_endpoint_current_database_drift_stops_before_service_or_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    baseline_row = StagedListingSnapshot(
        row_id="row-1",
        source_job_id="j1",
        detail_status="pending",
        published_job_id=None,
        crawl_job_id="crawl-1",
    )
    baselines = tmp_path / "baselines"
    first = baseline_artifact(baselines, BASELINE_RUN_1, listings=[baseline_row])
    second = baseline_artifact(baselines, BASELINE_RUN_2, listings=[baseline_row])
    state = State()
    calls: list[str] = []
    auth_state = _saved_session_state(tmp_path / "auth")
    monkeypatch.setattr(
        census_cli,
        "_phase_b_comparison_reference",
        lambda _path: _phase_b_reference(),
    )

    result = census_cli.main(
        [
            "probe-endpoints",
            "--phase-b-comparison-artifact",
            str(tmp_path / "phase-b"),
            "--endpoint-contract-id",
            "recommend-search-list-v1",
            "--endpoint-contract-id",
            "recommend-list-envelope-v1",
            "--baseline-artifact",
            str(first),
            "--baseline-artifact",
            str(second),
            "--confirm-live-research",
            "--auth-state",
            str(auth_state),
            "--run-id",
            RUN_ID,
            "--repo-root",
            str(Path.cwd()),
        ],
        session_factory=lambda: FakeSession(state.log),
        repository=FakeRepository(state),
        runtime_factory=lambda **_kwargs: calls.append("runtime"),
        service_factory=lambda: calls.append("service"),
    )

    assert result == census_cli.EXIT_EVIDENCE_FAILURE
    assert calls == []
    assert "network" not in state.log
    assert state.created_metadata is None


def _export_partition_probe_fixture(
    root: Path,
    *,
    run_id: str,
    partition_index: int,
    accepted: bool,
    parent_reference: PhaseCArtifactReference | None = None,
) -> Path:
    partition_id = OFFERTODAY_PARTITION_CATALOG[partition_index].partition_id
    plan = build_partition_probe_plan(
        endpoint_contract_id="recommend-search-list-v1",
        partition_ids=(partition_id,),
        max_pages_per_condition=3,
    )
    execution = _phase_c_partition_execution(plan, accepted=accepted)
    baseline = PhaseCBaselineReference(
        artifact_hashes=("a" * 64, "b" * 64),
        run_ids=(BASELINE_RUN_1, BASELINE_RUN_2),
        snapshot_hash="c" * 64,
        inventory_hash="d" * 64,
    )
    no_write = PhaseCNoWriteEvidence(
        start_snapshot_hash=baseline.snapshot_hash,
        end_snapshot_hash=baseline.snapshot_hash,
        start_product_data_hash="e" * 64,
        end_product_data_hash="e" * 64,
        start_inventory_hash=baseline.inventory_hash,
        end_inventory_hash=baseline.inventory_hash,
        stage_calls=0,
        would_stage_rows=0,
    )
    payload = build_phase_c_probe_artifact_payload(
        execution=execution,
        parent=parent_reference or _endpoint_probe_reference(),
        baseline=baseline,
        no_write=no_write,
    )
    return export_research_artifact(
        root=root,
        run_id=run_id,
        metadata=phase_c_probe_metadata(
            payload,
            run_id=run_id,
            planner_version="fixture",
        ),
        events=phase_c_artifact_events(
            payload,
            created_at="2026-07-13T12:00:00+00:00",
        ),
        provenance=provenance(),
        json_files={"partition-probe.json": payload},
    )


@pytest.mark.parametrize(
    ("accepted_parents", "expected_exit"),
    ((True, census_cli.EXIT_OK), (False, census_cli.EXIT_INCOMPLETE)),
)
def test_compare_partitions_is_offline_strict_and_never_freezes_candidate(
    tmp_path: Path,
    capsys,
    accepted_parents: bool,
    expected_exit: int,
) -> None:
    parents_root = tmp_path / "parents"
    first = _export_partition_probe_fixture(
        parents_root,
        run_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        partition_index=0,
        accepted=accepted_parents,
    )
    second = _export_partition_probe_fixture(
        parents_root,
        run_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        partition_index=1,
        accepted=accepted_parents,
    )
    dependency_calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        dependency_calls.append("called")
        raise AssertionError("offline comparison touched a live dependency")

    result = census_cli.main(
        [
            "compare-partitions",
            "--partition-probe-artifact",
            str(second),
            "--partition-probe-artifact",
            str(first),
            "--run-id",
            COMPARISON_RUN_ID,
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
        ],
        session_factory=forbidden,
        repository=forbidden,
        runtime_factory=forbidden,
        service_factory=forbidden,
        observation_service_factory=forbidden,
        provenance_provider=provenance,
    )
    output = json.loads(capsys.readouterr().out)
    artifact = Path(output["artifact"])
    payload_text = (artifact / "partition-comparison.json").read_text()

    assert result == expected_exit
    assert output["exit_code"] == expected_exit
    assert output["candidate_frozen"] is False
    assert dependency_calls == []
    assert "selected_policy" not in payload_text
    assert "candidate_hash" not in payload_text
    assert census_cli.verify_live_research_run(artifact).valid is True


def _phase_d_candidate() -> DiscoveryPolicyCandidateV2:
    contract = offertoday_endpoint_contract("recommend-search-list-v1")
    partitions = tuple(
        top_level_partition(category.code)
        for category in OFFERTODAY_CATEGORIES_L1
    )
    return DiscoveryPolicyCandidateV2(
        candidate_version=2,
        endpoint_contract_id=contract.contract_id,
        endpoint_contract_hash=contract.contract_hash,
        endpoint=contract.endpoint,
        rcd_type=None,
        category_catalog_version=OFFERTODAY_CATEGORY_CATALOG_VERSION,
        category_catalog_hash=offertoday_category_catalog_hash(),
        partition_catalog_hash=offertoday_partition_catalog_hash(),
        phase_d_partitions=partitions,
        retained_partition_ids=tuple(
            partition.partition_id for partition in partitions[:2]
        ),
        retained_condition_hashes=("a" * 64, "b" * 64),
        pagination_mode="response-cursor",
        requested_page_size=10,
        browser_lifecycle="condition-local-runtime",
        request_policy_hash=phase_c_request_policy_hash(contract.contract_id),
        terminal_policy="cursor-terminal-empty-confirmation-v1",
        max_pages_per_condition=500,
        require_empty_confirmation=True,
        max_attempts_per_page=3,
        retry_delays_seconds=(5.0, 15.0),
        page_delay_range_seconds=(3.0, 5.0),
        session_mode="saved-session",
        fixed_repeat_category_ids=(118000, 112000, 127000),
        phase_b_comparison_artifact_hash="c" * 64,
        phase_c_comparison_artifact_hash="d" * 64,
        source_artifact_hash="e" * 64,
        deferred_issue_ids=(4, 5),
    )


def _export_phase_d_candidate_fixture(root: Path) -> Path:
    candidate = _phase_d_candidate()
    payload = discovery_policy_candidate_artifact_payload(candidate)
    captured_at = "2026-07-13T00:00:00+00:00"
    return export_research_artifact(
        root=root,
        run_id=CANDIDATE_RUN_ID,
        metadata=phase_d_metadata(
            payload,
            run_id=CANDIDATE_RUN_ID,
            planner_version="fixture",
        ),
        events=phase_d_artifact_events(payload, created_at=captured_at),
        provenance=provenance(captured_at=captured_at),
        json_files={"discovery-policy.json": payload},
    )


def _export_endpoint_probe_fixture(
    root: Path,
    *,
    parent: PhaseCArtifactReference,
    run_id: str,
) -> Path:
    plan = build_endpoint_probe_plan()
    execution = _phase_c_endpoint_execution(plan)
    baseline = PhaseCBaselineReference(
        artifact_hashes=("a" * 64, "b" * 64),
        run_ids=(BASELINE_RUN_1, BASELINE_RUN_2),
        snapshot_hash="c" * 64,
        inventory_hash="d" * 64,
    )
    no_write = PhaseCNoWriteEvidence(
        start_snapshot_hash=baseline.snapshot_hash,
        end_snapshot_hash=baseline.snapshot_hash,
        start_product_data_hash="e" * 64,
        end_product_data_hash="e" * 64,
        start_inventory_hash=baseline.inventory_hash,
        end_inventory_hash=baseline.inventory_hash,
        stage_calls=0,
        would_stage_rows=0,
    )
    payload = build_phase_c_probe_artifact_payload(
        execution=execution,
        parent=parent,
        baseline=baseline,
        no_write=no_write,
    )
    captured_at = "2026-07-13T00:00:00+00:00"
    return export_research_artifact(
        root=root,
        run_id=run_id,
        metadata=phase_c_probe_metadata(
            payload,
            run_id=run_id,
            planner_version="fixture",
        ),
        events=phase_c_artifact_events(payload, created_at=captured_at),
        provenance=provenance(captured_at=captured_at),
        json_files={"endpoint-probe.json": payload},
    )


def _export_partition_comparison_fixture(
    root: Path,
    *,
    parents: tuple[Path, ...],
    run_id: str,
) -> Path:
    projected = []
    for artifact_dir in parents:
        reference = phase_c_artifact_reference(artifact_dir)
        payload = json.loads(
            (artifact_dir / "partition-probe.json").read_text(encoding="utf-8")
        )
        projected.append(
            build_partition_probe_parent_projection(
                reference=reference,
                probe_payload=payload,
            )
        )
    payload = build_partition_comparison_artifact_payload(projected)
    captured_at = "2026-07-13T00:00:00+00:00"
    return export_research_artifact(
        root=root,
        run_id=run_id,
        metadata=phase_c_comparison_metadata(
            payload,
            run_id=run_id,
            planner_version="fixture",
        ),
        events=phase_c_artifact_events(payload, created_at=captured_at),
        provenance=provenance(captured_at=captured_at),
        json_files={"partition-comparison.json": payload},
    )


def _phase_d_lineage_fixtures(tmp_path: Path):
    phase_b = _phase_b_reference()
    endpoint = _export_endpoint_probe_fixture(
        tmp_path / "phase-c",
        parent=phase_b,
        run_id="99999999-9999-9999-9999-999999999999",
    )
    endpoint_reference = phase_c_artifact_reference(endpoint)
    first = _export_partition_probe_fixture(
        tmp_path / "phase-c",
        run_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        partition_index=0,
        accepted=True,
        parent_reference=endpoint_reference,
    )
    second = _export_partition_probe_fixture(
        tmp_path / "phase-c",
        run_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        partition_index=1,
        accepted=True,
        parent_reference=endpoint_reference,
    )
    comparison = _export_partition_comparison_fixture(
        tmp_path / "phase-c",
        parents=(first, second),
        run_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
    )
    return phase_b, endpoint, first, second, comparison


def test_freeze_discovery_policy_requires_and_preserves_complete_lineage(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    phase_b, endpoint, first, second, comparison = _phase_d_lineage_fixtures(
        tmp_path
    )
    monkeypatch.setattr(
        census_cli,
        "_phase_b_comparison_reference",
        lambda _path: phase_b,
    )
    dependency_calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        dependency_calls.append("called")
        raise AssertionError("offline policy freeze touched a live dependency")

    result = census_cli.main(
        [
            "freeze-discovery-policy",
            "--phase-b-comparison-artifact",
            str(tmp_path / "phase-b"),
            "--endpoint-probe-artifact",
            str(endpoint),
            "--partition-probe-artifact",
            str(second),
            "--partition-probe-artifact",
            str(first),
            "--partition-comparison-artifact",
            str(comparison),
            "--run-id",
            CANDIDATE_RUN_ID,
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
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
    output = json.loads(capsys.readouterr().out)
    artifact = Path(output["artifact"])
    payload = json.loads((artifact / "discovery-policy.json").read_text())
    endpoint_payload = json.loads((endpoint / "endpoint-probe.json").read_text())
    selected_endpoint = next(
        condition
        for condition in endpoint_payload["execution"]["conditions"]
        if condition["endpoint_contract_id"] == "recommend-search-list-v1"
    )
    comparison_manifest_hash = hashlib.sha256(
        (comparison / "manifest.json").read_bytes()
    ).hexdigest()

    assert result == census_cli.EXIT_OK
    assert dependency_calls == []
    assert endpoint_payload["execution"]["accepted"] is False
    assert selected_endpoint["contract_verified"] is True
    assert selected_endpoint["stop_reason"] == "page_cap"
    assert selected_endpoint["is_complete"] is False
    assert len(selected_endpoint["pages"]) == 3
    assert payload["candidate"]["phase_b_comparison_artifact_hash"] == (
        phase_b.manifest_hash
    )
    assert payload["candidate"]["phase_c_comparison_artifact_hash"] == (
        comparison_manifest_hash
    )
    assert payload["candidate"]["endpoint_contract_id"] == (
        "recommend-search-list-v1"
    )
    assert payload["candidate"]["deferred_issue_ids"] == [4, 5]
    assert census_cli.verify_live_research_run(artifact).valid is True


def test_freeze_discovery_policy_rejects_a_partition_probe_from_another_endpoint_parent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    phase_b, endpoint, _, _, _ = _phase_d_lineage_fixtures(tmp_path)
    wrong_parent_probe = _export_partition_probe_fixture(
        tmp_path / "wrong-lineage",
        run_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
        partition_index=0,
        accepted=True,
    )
    comparison = _export_partition_comparison_fixture(
        tmp_path / "wrong-lineage",
        parents=(wrong_parent_probe,),
        run_id="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
    )
    monkeypatch.setattr(
        census_cli,
        "_phase_b_comparison_reference",
        lambda _path: phase_b,
    )

    result = census_cli.main(
        [
            "freeze-discovery-policy",
            "--phase-b-comparison-artifact",
            str(tmp_path / "phase-b"),
            "--endpoint-probe-artifact",
            str(endpoint),
            "--partition-probe-artifact",
            str(wrong_parent_probe),
            "--partition-comparison-artifact",
            str(comparison),
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
        ]
    )

    assert result == census_cli.EXIT_EVIDENCE_FAILURE
    assert not (tmp_path / "runs").exists()


def test_phase_d_live_requires_baselines_and_write_confirmation_before_dependencies(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    auth_state = _saved_session_state(tmp_path / "auth")

    def forbidden(*_args, **_kwargs):
        calls.append("dependency")
        raise AssertionError("Phase D constructed a dependency before usage gates")

    one_baseline = census_cli.main(
        [
            "census-v2",
            "--candidate-artifact",
            str(tmp_path / "missing-candidate"),
            "--baseline-artifact",
            str(tmp_path / "only-one"),
            "--run-index",
            "1",
            "--window-id",
            "window-a",
            "--staging-mode",
            "noop",
            "--confirm-live-research",
            "--auth-state",
            str(auth_state),
        ],
        session_factory=forbidden,
        repository=forbidden,
        runtime_factory=forbidden,
        service_factory=forbidden,
    )
    missing_write_confirmation = census_cli.main(
        [
            "repeat-fixed-v2",
            "--candidate-artifact",
            str(tmp_path / "missing-candidate"),
            "--baseline-artifact",
            str(tmp_path / "first"),
            "--baseline-artifact",
            str(tmp_path / "second"),
            "--run-index",
            "1",
            "--window-id",
            "window-a",
            "--staging-mode",
            "reconciled",
            "--confirm-live-research",
            "--auth-state",
            str(auth_state),
        ],
        session_factory=forbidden,
        repository=forbidden,
        runtime_factory=forbidden,
        service_factory=forbidden,
    )

    assert one_baseline == census_cli.EXIT_USAGE
    assert missing_write_confirmation == census_cli.EXIT_USAGE
    assert calls == []


def test_phase_d_live_rejects_the_wrong_candidate_version_before_dependencies(
    tmp_path: Path,
) -> None:
    first = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_1)
    second = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_2)
    auth_state = _saved_session_state(tmp_path / "auth")
    calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        calls.append("dependency")
        raise AssertionError("wrong Phase D parent constructed a live dependency")

    result = census_cli.main(
        [
            "repeat-fixed-v2",
            "--candidate-artifact",
            str(first),
            "--baseline-artifact",
            str(first),
            "--baseline-artifact",
            str(second),
            "--run-index",
            "1",
            "--window-id",
            "fixed-window",
            "--staging-mode",
            "noop",
            "--confirm-live-research",
            "--auth-state",
            str(auth_state),
        ],
        session_factory=forbidden,
        repository=forbidden,
        runtime_factory=forbidden,
        service_factory=forbidden,
    )

    assert result == census_cli.EXIT_EVIDENCE_FAILURE
    assert calls == []


def test_phase_d_current_database_drift_stops_before_live_dependencies(
    tmp_path: Path,
) -> None:
    candidate = _export_phase_d_candidate_fixture(tmp_path / "candidate")
    baseline_row = StagedListingSnapshot(
        row_id="row-1",
        source_job_id="j1",
        detail_status="pending",
        published_job_id=None,
        crawl_job_id="crawl-1",
    )
    first = baseline_artifact(
        tmp_path / "baselines",
        BASELINE_RUN_1,
        listings=[baseline_row],
    )
    second = baseline_artifact(
        tmp_path / "baselines",
        BASELINE_RUN_2,
        listings=[baseline_row],
    )
    state = State()
    calls: list[str] = []
    auth_state = _saved_session_state(tmp_path / "auth")

    def forbidden(*_args, **_kwargs):
        calls.append("dependency")
        raise AssertionError("Phase D crossed the current database gate")

    result = census_cli.main(
        [
            "repeat-fixed-v2",
            "--candidate-artifact",
            str(candidate),
            "--baseline-artifact",
            str(first),
            "--baseline-artifact",
            str(second),
            "--run-index",
            "1",
            "--window-id",
            "fixed-window",
            "--staging-mode",
            "noop",
            "--confirm-live-research",
            "--auth-state",
            str(auth_state),
            "--run-id",
            RUN_ID,
            "--repo-root",
            str(Path.cwd()),
        ],
        session_factory=lambda: FakeSession(state.log),
        repository=FakeRepository(state),
        runtime_factory=forbidden,
        service_factory=forbidden,
        observation_service_factory=forbidden,
        crawl_runtime_factory=forbidden,
        staging_sink_factory=forbidden,
    )

    assert result == census_cli.EXIT_EVIDENCE_FAILURE
    assert calls == []
    assert state.created_metadata is None
    assert "network" not in state.log


async def _phase_d_no_sleep(_seconds: float) -> None:
    return None


@pytest.mark.parametrize(
    ("command", "expected_experiment", "expected_conditions"),
    (
        ("census-v2", PHASE_D_CENSUS_EXPERIMENT, 31),
        ("repeat-fixed-v2", PHASE_D_FIXED_REPEAT_EXPERIMENT, 3),
    ),
)
def test_phase_d_live_commands_export_strict_noop_artifacts(
    tmp_path: Path,
    capsys,
    command: str,
    expected_experiment: str,
    expected_conditions: int,
) -> None:
    candidate = _export_phase_d_candidate_fixture(tmp_path / "candidate")
    first = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_1)
    second = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_2)
    auth_state = _saved_session_state(tmp_path / "auth")
    state = State()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("no-op Phase D run touched a write dependency")

    result = census_cli.main(
        [
            command,
            "--candidate-artifact",
            str(candidate),
            "--baseline-artifact",
            str(first),
            "--baseline-artifact",
            str(second),
            "--run-index",
            "1",
            "--window-id",
            "window-a",
            "--staging-mode",
            "noop",
            "--confirm-live-research",
            "--auth-state",
            str(auth_state),
            "--run-id",
            RUN_ID,
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
        ],
        session_factory=lambda: FakeSession(state.log),
        repository=FakeRepository(state),
        runtime_factory=lambda **kwargs: FakePaginationRuntime(state, **kwargs),
        service_factory=lambda: OfferTodayResearchLiveService(
            sleep=_phase_d_no_sleep
        ),
        observation_service_factory=lambda db: FakeObservationService(db, state),
        crawl_runtime_factory=forbidden,
        staging_sink_factory=forbidden,
        provenance_provider=provenance,
    )
    output = json.loads(capsys.readouterr().out)
    artifact = Path(output["artifact"])
    payload = json.loads((artifact / "phase-d-run.json").read_text())

    assert result == census_cli.EXIT_OK
    assert output["accepted"] is True
    assert output["experiment"] == expected_experiment
    assert output["completed_condition_count"] == expected_conditions
    assert len(payload["run"]["conditions"]) == expected_conditions
    assert payload["product"]["staging"]["staging_mode"] == "noop"
    assert payload["product"]["detail_attempts"] == 0
    assert payload["product"]["product_writes"] == 0
    assert state.created_metadata.request_budget == {
        "listing_logical": expected_conditions * 500,
        "listing_attempt_max": expected_conditions * 1_500,
        "detail": 0,
        "product_writes": 0,
    }
    assert len(state.runtime_kwargs) == expected_conditions
    assert all(
        runtime_kwargs == {
            "auth_state_path": str(auth_state.resolve()),
            "headed": False,
        }
        for runtime_kwargs in state.runtime_kwargs
    )
    manifest = json.loads((artifact / "manifest.json").read_text())
    artifact_text = _artifact_text(artifact)
    cookie_value = json.loads(auth_state.read_text())["cookies"][0]["value"]
    assert manifest["provenance"]["runtime_context"]["session_state_sha256"] == (
        hashlib.sha256(auth_state.read_bytes()).hexdigest()
    )
    assert str(auth_state.resolve()) not in artifact_text
    assert cookie_value not in artifact_text
    assert census_cli.verify_live_research_run(artifact).valid is True


def _invoke_phase_d_live_fixture(
    *,
    command: str,
    run_id: str,
    run_index: int,
    window_id: str,
    captured_at: datetime,
    candidate: Path,
    baselines: tuple[Path, Path],
    artifact_root: Path,
    capsys,
    monkeypatch,
    service_factory=None,
    expected_exit: int = census_cli.EXIT_OK,
) -> Path:
    state = State()
    state.expected_run_id = run_id
    auth_state = _saved_session_state(artifact_root.parent / "auth")
    monkeypatch.setattr(census_cli, "utc_now", lambda: captured_at)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("no-op Phase D fixture touched a write dependency")

    result = census_cli.main(
        [
            command,
            "--candidate-artifact",
            str(candidate),
            "--baseline-artifact",
            str(baselines[0]),
            "--baseline-artifact",
            str(baselines[1]),
            "--run-index",
            str(run_index),
            "--window-id",
            window_id,
            "--staging-mode",
            "noop",
            "--confirm-live-research",
            "--auth-state",
            str(auth_state),
            "--run-id",
            run_id,
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(artifact_root),
        ],
        session_factory=lambda: FakeSession(state.log),
        repository=FakeRepository(state),
        runtime_factory=lambda **kwargs: FakePaginationRuntime(state, **kwargs),
        service_factory=(
            service_factory
            or (lambda: OfferTodayResearchLiveService(sleep=_phase_d_no_sleep))
        ),
        observation_service_factory=lambda db: FakeObservationService(db, state),
        crawl_runtime_factory=forbidden,
        staging_sink_factory=forbidden,
        provenance_provider=provenance,
    )
    output = json.loads(capsys.readouterr().out)

    assert result == expected_exit
    return Path(output["artifact"])


def test_compare_stability_v2_is_strict_offline_and_freezes_reference(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    candidate = _export_phase_d_candidate_fixture(tmp_path / "candidate")
    baselines = (
        baseline_artifact(tmp_path / "baselines", BASELINE_RUN_1),
        baseline_artifact(tmp_path / "baselines", BASELINE_RUN_2),
    )
    census_times = (
        datetime(2026, 7, 13, 0, 0, tzinfo=UTC),
        datetime(2026, 7, 13, 6, 0, tzinfo=UTC),
        datetime(2026, 7, 13, 12, 0, tzinfo=UTC),
    )
    fixed_times = (
        datetime(2026, 7, 13, 13, 0, tzinfo=UTC),
        datetime(2026, 7, 13, 13, 10, tzinfo=UTC),
        datetime(2026, 7, 13, 13, 20, tzinfo=UTC),
    )
    census_artifacts = tuple(
        _invoke_phase_d_live_fixture(
            command="census-v2",
            run_id=f"01000000-0000-0000-0000-{index:012d}",
            run_index=index,
            window_id=("census-window-a" if index == 1 else "census-window-b"),
            captured_at=census_times[index - 1],
            candidate=candidate,
            baselines=baselines,
            artifact_root=tmp_path / "parents",
            capsys=capsys,
            monkeypatch=monkeypatch,
        )
        for index in (1, 2, 3)
    )
    fixed_artifacts = tuple(
        _invoke_phase_d_live_fixture(
            command="repeat-fixed-v2",
            run_id=f"02000000-0000-0000-0000-{index:012d}",
            run_index=index,
            window_id="fixed-window-a",
            captured_at=fixed_times[index - 1],
            candidate=candidate,
            baselines=baselines,
            artifact_root=tmp_path / "parents",
            capsys=capsys,
            monkeypatch=monkeypatch,
        )
        for index in (1, 2, 3)
    )
    dependency_calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        dependency_calls.append("called")
        raise AssertionError("offline Phase D comparison touched a live dependency")

    argv = ["compare-stability-v2"]
    for artifact in census_artifacts:
        argv.extend(("--census-artifact", str(artifact)))
    for artifact in fixed_artifacts:
        argv.extend(("--fixed-repeat-artifact", str(artifact)))
    argv.extend(
        (
            "--active-holdout-id",
            "confirmed-active-holdout",
            "--run-id",
            COMPARISON_RUN_ID,
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "comparison"),
        )
    )
    result = census_cli.main(
        argv,
        session_factory=forbidden,
        repository=forbidden,
        runtime_factory=forbidden,
        service_factory=forbidden,
        observation_service_factory=forbidden,
        crawl_runtime_factory=forbidden,
        staging_sink_factory=forbidden,
        provenance_provider=provenance,
    )
    output = json.loads(capsys.readouterr().out)
    artifact = Path(output["artifact"])
    payload = json.loads((artifact / "phase-d-comparison.json").read_text())

    assert result == census_cli.EXIT_OK
    assert output["accepted"] is True
    assert output["fixed_cohort_jaccard"] == 1.0
    assert output["unique_count_cv"] == 0.0
    assert output["stable_reference_count"] == 32
    assert payload["stable_reference_frozen"] is True
    assert dependency_calls == []
    assert census_cli.verify_live_research_run(artifact).valid is True

    rejected_fixed = _invoke_phase_d_live_fixture(
        command="repeat-fixed-v2",
        run_id="02000000-0000-0000-0000-000000000004",
        run_index=1,
        window_id="fixed-window-a",
        captured_at=fixed_times[0],
        candidate=candidate,
        baselines=baselines,
        artifact_root=tmp_path / "rejected-parent",
        capsys=capsys,
        monkeypatch=monkeypatch,
        service_factory=ConservationRejectingPhaseDService,
        expected_exit=census_cli.EXIT_INCOMPLETE,
    )
    rejected_argv = ["compare-stability-v2"]
    for parent in census_artifacts:
        rejected_argv.extend(("--census-artifact", str(parent)))
    for parent in (rejected_fixed, *fixed_artifacts[1:]):
        rejected_argv.extend(("--fixed-repeat-artifact", str(parent)))
    rejected_result = census_cli.main(
        rejected_argv,
        session_factory=forbidden,
        repository=forbidden,
        runtime_factory=forbidden,
        service_factory=forbidden,
        observation_service_factory=forbidden,
        crawl_runtime_factory=forbidden,
        staging_sink_factory=forbidden,
    )

    assert rejected_result == census_cli.EXIT_EVIDENCE_FAILURE
    assert dependency_calls == []


def test_compare_stability_v2_rejects_wrong_versions_without_live_dependencies(
    tmp_path: Path,
) -> None:
    candidate = _export_phase_d_candidate_fixture(tmp_path / "candidate")
    calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        calls.append("dependency")
        raise AssertionError("wrong comparison parent touched a live dependency")

    result = census_cli.main(
        [
            "compare-stability-v2",
            "--census-artifact",
            str(candidate),
            "--census-artifact",
            str(candidate),
            "--census-artifact",
            str(candidate),
            "--fixed-repeat-artifact",
            str(candidate),
            "--fixed-repeat-artifact",
            str(candidate),
            "--fixed-repeat-artifact",
            str(candidate),
            "--repo-root",
            str(Path.cwd()),
        ],
        session_factory=forbidden,
        repository=forbidden,
        runtime_factory=forbidden,
        service_factory=forbidden,
        observation_service_factory=forbidden,
        crawl_runtime_factory=forbidden,
        staging_sink_factory=forbidden,
    )

    assert result == census_cli.EXIT_EVIDENCE_FAILURE
    assert calls == []


class ConservationRejectingPhaseDService:
    def __init__(self) -> None:
        self.inner = OfferTodayResearchLiveService(sleep=_phase_d_no_sleep)

    async def run_fixed_repeat_v2(self, **kwargs):
        execution = await self.inner.run_fixed_repeat_v2(**kwargs)
        first = replace(execution.results[0], accepted_job_ids=())
        return replace(execution, results=(first, *execution.results[1:]))


def test_phase_d_valid_rejection_and_hard_stop_keep_strict_artifacts(
    tmp_path: Path,
    capsys,
) -> None:
    candidate = _export_phase_d_candidate_fixture(tmp_path / "candidate")
    first = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_1)
    second = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_2)
    auth_state = _saved_session_state(tmp_path / "auth")

    def run(service_factory, runtime_factory, run_id: str):
        state = State()
        state.expected_run_id = run_id
        result = census_cli.main(
            [
                "repeat-fixed-v2",
                "--candidate-artifact",
                str(candidate),
                "--baseline-artifact",
                str(first),
                "--baseline-artifact",
                str(second),
                "--run-index",
                "1",
                "--window-id",
                "fixed-window",
                "--staging-mode",
                "noop",
                "--confirm-live-research",
                "--auth-state",
                str(auth_state),
                "--run-id",
                run_id,
                "--repo-root",
                str(Path.cwd()),
                "--artifact-root",
                str(tmp_path / "runs"),
            ],
            session_factory=lambda: FakeSession(state.log),
            repository=FakeRepository(state),
            runtime_factory=lambda **kwargs: runtime_factory(state, **kwargs),
            service_factory=service_factory,
            observation_service_factory=lambda db: FakeObservationService(db, state),
            provenance_provider=provenance,
        )
        output = json.loads(capsys.readouterr().out)
        return result, output

    incomplete_result, incomplete = run(
        ConservationRejectingPhaseDService,
        FakePaginationRuntime,
        "03000000-0000-0000-0000-000000000001",
    )
    hard_stop_result, hard_stop = run(
        lambda: OfferTodayResearchLiveService(sleep=_phase_d_no_sleep),
        lambda state, **kwargs: FakePaginationRuntime(
            state,
            missing_cursor=True,
            **kwargs,
        ),
        "03000000-0000-0000-0000-000000000002",
    )

    assert incomplete_result == census_cli.EXIT_INCOMPLETE
    assert incomplete["accepted"] is False
    assert incomplete["failure_reason"] is None
    assert hard_stop_result == census_cli.EXIT_HARD_STOP
    assert hard_stop["accepted"] is False
    assert hard_stop["failure_reason"].startswith("hard_stop:")
    for output in (incomplete, hard_stop):
        assert census_cli.verify_live_research_run(Path(output["artifact"])).valid


def test_phase_d_product_drift_exports_strict_evidence_and_exits_five(
    tmp_path: Path,
    capsys,
) -> None:
    candidate = _export_phase_d_candidate_fixture(tmp_path / "candidate")
    first = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_1)
    second = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_2)
    auth_state = _saved_session_state(tmp_path / "auth")
    state = State()

    result = census_cli.main(
        [
            "repeat-fixed-v2",
            "--candidate-artifact",
            str(candidate),
            "--baseline-artifact",
            str(first),
            "--baseline-artifact",
            str(second),
            "--run-index",
            "1",
            "--window-id",
            "fixed-window",
            "--staging-mode",
            "noop",
            "--confirm-live-research",
            "--auth-state",
            str(auth_state),
            "--run-id",
            RUN_ID,
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
        ],
        session_factory=lambda: FakeSession(state.log),
        repository=FakeRepository(state, product_drift=True),
        runtime_factory=lambda **kwargs: FakePaginationRuntime(state, **kwargs),
        service_factory=lambda: OfferTodayResearchLiveService(
            sleep=_phase_d_no_sleep
        ),
        observation_service_factory=lambda db: FakeObservationService(db, state),
        provenance_provider=provenance,
    )
    output = json.loads(capsys.readouterr().out)
    artifact = Path(output["artifact"])
    payload = json.loads((artifact / "phase-d-run.json").read_text())

    assert result == census_cli.EXIT_EVIDENCE_FAILURE
    assert payload["product"]["jobs_unchanged"] is False
    assert payload["accepted"] is False
    assert census_cli.verify_live_research_run(artifact).valid is True


class PhaseDReconciledRepository(FakeRepository):
    source_job_ids = ("118000-10", "112000-10", "127000-10")

    def list_staged_snapshots(self, db):
        self.staged_reads += 1
        self.state.log.append(f"staged_snapshot_{self.staged_reads}")
        if self.staged_reads == 1:
            return []
        return [
            StagedListingSnapshot(
                row_id=f"row-{index}",
                source_job_id=source_job_id,
                detail_status="pending",
                published_job_id=None,
                crawl_job_id=RUN_ID,
            )
            for index, source_job_id in enumerate(self.source_job_ids, start=1)
        ]

    def capture_product_data_snapshot(self, db):
        self.product_reads += 1
        self.state.log.append(f"product_snapshot_{self.product_reads}")
        return ProductDataSnapshot.from_table_hashes(
            staged_rows_hash=("a" * 64 if self.product_reads == 1 else "f" * 64),
            published_jobs_hash="b" * 64,
            companies_hash="c" * 64,
        )


def test_repeat_fixed_v2_reconciles_listing_only_staging_with_confirmation(
    tmp_path: Path,
    capsys,
) -> None:
    candidate = _export_phase_d_candidate_fixture(tmp_path / "candidate")
    first = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_1)
    second = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_2)
    auth_state = _saved_session_state(tmp_path / "auth")
    state = State()

    result = census_cli.main(
        [
            "repeat-fixed-v2",
            "--candidate-artifact",
            str(candidate),
            "--baseline-artifact",
            str(first),
            "--baseline-artifact",
            str(second),
            "--run-index",
            "1",
            "--window-id",
            "fixed-window",
            "--staging-mode",
            "reconciled",
            "--confirm-live-research",
            "--confirm-staging-writes",
            "--auth-state",
            str(auth_state),
            "--run-id",
            RUN_ID,
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
        ],
        session_factory=lambda: FakeSession(state.log),
        repository=PhaseDReconciledRepository(state),
        runtime_factory=lambda **kwargs: FakePaginationRuntime(state, **kwargs),
        service_factory=lambda: OfferTodayResearchLiveService(
            sleep=_phase_d_no_sleep
        ),
        observation_service_factory=lambda db: FakeObservationService(db, state),
        crawl_runtime_factory=CreatingPilotCrawlRuntime,
        provenance_provider=provenance,
    )
    output = json.loads(capsys.readouterr().out)
    artifact = Path(output["artifact"])
    payload = json.loads((artifact / "phase-d-run.json").read_text())
    staging = payload["product"]["staging"]

    assert result == census_cli.EXIT_OK
    assert output["accepted"] is True
    assert staging["staging_mode"] == "reconciled"
    assert staging["rows_created"] == 3
    assert staging["created_source_job_ids"] == sorted(
        PhaseDReconciledRepository.source_job_ids
    )
    assert staging["stage_calls"] == 3
    assert payload["run"]["staging_conservation_difference"] == 0
    assert payload["product"]["jobs_unchanged"] is True
    assert payload["product"]["companies_unchanged"] is True
    assert census_cli.verify_live_research_run(artifact).valid is True


@pytest.mark.parametrize("failure_stage", ("end_snapshot", "finalization"))
def test_phase_d_post_run_failures_preserve_sanitized_strict_prefix(
    tmp_path: Path,
    capsys,
    failure_stage: str,
) -> None:
    candidate = _export_phase_d_candidate_fixture(tmp_path / "candidate")
    first = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_1)
    second = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_2)
    auth_state = _saved_session_state(tmp_path / "auth")
    state = State()
    repository = FakeRepository(
        state,
        end_snapshot_error=(
            RuntimeError("secret end snapshot detail")
            if failure_stage == "end_snapshot"
            else None
        ),
    )
    if failure_stage == "finalization":
        state.finish_errors.append(RuntimeError("secret finalization detail"))

    result = census_cli.main(
        [
            "repeat-fixed-v2",
            "--candidate-artifact",
            str(candidate),
            "--baseline-artifact",
            str(first),
            "--baseline-artifact",
            str(second),
            "--run-index",
            "1",
            "--window-id",
            "fixed-window",
            "--staging-mode",
            "noop",
            "--confirm-live-research",
            "--auth-state",
            str(auth_state),
            "--run-id",
            RUN_ID,
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
        ],
        session_factory=lambda: FakeSession(state.log),
        repository=repository,
        runtime_factory=lambda **kwargs: FakePaginationRuntime(state, **kwargs),
        service_factory=lambda: OfferTodayResearchLiveService(
            sleep=_phase_d_no_sleep
        ),
        observation_service_factory=lambda db: FakeObservationService(db, state),
        provenance_provider=provenance,
    )
    output = json.loads(capsys.readouterr().out)
    artifact = Path(output["artifact"])
    payload_text = (artifact / "phase-d-run.json").read_text()
    payload = json.loads(payload_text)

    assert result == census_cli.EXIT_EVIDENCE_FAILURE
    assert output["accepted"] is False
    assert output["failure_reason"] == (
        "unexpected_phase_d_census_error:RuntimeError"
    )
    assert payload["run"]["failure_reason"] == output["failure_reason"]
    assert payload["run"]["unclassified_failures"] == 1
    assert "secret end snapshot detail" not in payload_text
    assert "secret finalization detail" not in payload_text
    if failure_stage == "end_snapshot":
        assert payload["product"]["end_snapshot_captured"] is False
    else:
        assert payload["product"]["end_snapshot_captured"] is True
    assert census_cli.verify_live_research_run(artifact).valid is True


DUAL_COHORT_LIVE_COMMANDS = (
    "probe-result-partitions-v2",
    "probe-supplemental-cohort-v1",
    "census-result-partial-v3",
    "repeat-fixed-result-partial-v3",
    "census-dual-cohort-v3",
    "repeat-fixed-dual-cohort-v3",
)


def _dual_cohort_cli_argv(
    command: str,
    *,
    auth_state: str = "saved-session.json",
    baseline_count: int = 2,
) -> list[str]:
    baselines = [
        argument
        for index in range(baseline_count)
        for argument in ("--baseline-artifact", f"baseline-{index + 1}")
    ]
    live_tail = [
        *baselines,
        "--confirm-live-research",
        "--auth-state",
        auth_state,
    ]
    if command == "probe-result-partitions-v2":
        return [
            command,
            "--endpoint-probe-artifact",
            "endpoint-probe",
            "--endpoint-contract-id",
            "recommend-search-list-v1",
            "--partition-id",
            OFFERTODAY_PARTITION_CATALOG[0].partition_id,
            *live_tail,
        ]
    if command == "probe-supplemental-cohort-v1":
        return [
            command,
            "--result-policy-artifact",
            "result-policy",
            "--endpoint-contract-id",
            "recommend-search-list-v1",
            "--run-index",
            "1",
            *live_tail,
        ]
    if command == "freeze-result-partition-policy-v1":
        return [command, "--result-probe-artifact", "result-probe"]
    if command == "compare-supplemental-cohort-v1":
        return [
            command,
            "--supplemental-probe-artifact",
            "supplemental-1",
            "--supplemental-probe-artifact",
            "supplemental-2",
            "--supplemental-probe-artifact",
            "supplemental-3",
        ]
    if command == "freeze-dual-cohort-policy-v3":
        return [
            command,
            "--phase-b-comparison-artifact",
            "phase-b",
            "--result-policy-artifact",
            "result-policy",
            "--supplemental-comparison-artifact",
            "supplemental-comparison",
        ]
    if command in {
        "census-result-partial-v3",
        "repeat-fixed-result-partial-v3",
    }:
        return [
            command,
            "--phase-b-comparison-artifact",
            "phase-b",
            "--result-policy-artifact",
            "result-policy",
            "--run-index",
            "1",
            "--window-id",
            "window-a",
            "--staging-mode",
            "noop",
            *live_tail,
        ]
    if command in {"census-dual-cohort-v3", "repeat-fixed-dual-cohort-v3"}:
        return [
            command,
            "--candidate-artifact",
            "dual-candidate",
            "--run-index",
            "1",
            "--window-id",
            "window-a",
            "--staging-mode",
            "noop",
            *live_tail,
        ]
    if command == "compare-stability-dual-cohort-v3":
        return [
            command,
            *[
                argument
                for prefix in ("census", "fixed-repeat")
                for index in range(1, 4)
                for argument in (f"--{prefix}-artifact", f"{prefix}-{index}")
            ],
        ]
    raise AssertionError(f"unsupported dual-cohort test command: {command}")


@pytest.mark.parametrize(
    "command",
    (
        "probe-result-partitions-v2",
        "probe-supplemental-cohort-v1",
        "freeze-result-partition-policy-v1",
        "compare-supplemental-cohort-v1",
        "freeze-dual-cohort-policy-v3",
        "census-result-partial-v3",
        "repeat-fixed-result-partial-v3",
        "census-dual-cohort-v3",
        "repeat-fixed-dual-cohort-v3",
        "compare-stability-dual-cohort-v3",
    ),
)
def test_parser_exposes_every_exact_dual_cohort_command(command: str) -> None:
    args = census_cli.build_parser().parse_args(_dual_cohort_cli_argv(command))

    assert args.command == command


@pytest.mark.parametrize(
    "alias",
    (
        "probe-result-partitions-v3",
        "freeze-dual-cohort-policy",
        "dual-cohort-census-v3",
        "compare-stability-dual-cohort-v4",
    ),
)
def test_parser_rejects_dual_cohort_aliases_and_future_versions(alias: str) -> None:
    with pytest.raises(SystemExit):
        census_cli.build_parser().parse_args([alias])


@pytest.mark.parametrize(
    ("command", "helper_name", "uses_live_dependencies", "uses_crawl_runtime"),
    (
        (
            "probe-result-partitions-v2",
            "_dual_cohort_probe_command",
            True,
            False,
        ),
        (
            "probe-supplemental-cohort-v1",
            "_dual_cohort_probe_command",
            True,
            False,
        ),
        (
            "freeze-result-partition-policy-v1",
            "_freeze_result_partition_policy_command",
            False,
            False,
        ),
        (
            "compare-supplemental-cohort-v1",
            "_compare_supplemental_cohort_command",
            False,
            False,
        ),
        (
            "freeze-dual-cohort-policy-v3",
            "_freeze_dual_cohort_policy_command",
            False,
            False,
        ),
        (
            "census-result-partial-v3",
            "_dual_cohort_phase_d_live_command",
            True,
            True,
        ),
        (
            "repeat-fixed-result-partial-v3",
            "_dual_cohort_phase_d_live_command",
            True,
            True,
        ),
        (
            "census-dual-cohort-v3",
            "_dual_cohort_phase_d_live_command",
            True,
            True,
        ),
        (
            "repeat-fixed-dual-cohort-v3",
            "_dual_cohort_phase_d_live_command",
            True,
            True,
        ),
        (
            "compare-stability-dual-cohort-v3",
            "_compare_dual_cohort_phase_d_command",
            False,
            False,
        ),
    ),
)
def test_main_dispatches_every_dual_cohort_command_without_fallthrough(
    monkeypatch,
    command: str,
    helper_name: str,
    uses_live_dependencies: bool,
    uses_crawl_runtime: bool,
) -> None:
    calls: list[tuple[str, dict]] = []

    def dispatched(args, **kwargs):
        calls.append((args.command, kwargs))
        return 73

    monkeypatch.setattr(census_cli, helper_name, dispatched)

    result = census_cli.main(_dual_cohort_cli_argv(command))

    assert result == 73
    assert len(calls) == 1
    dispatched_command, kwargs = calls[0]
    assert dispatched_command == command
    assert ("session_factory" in kwargs) is uses_live_dependencies
    assert ("runtime_factory" in kwargs) is uses_live_dependencies
    assert ("crawl_runtime_factory" in kwargs) is uses_crawl_runtime


@pytest.mark.parametrize("command", DUAL_COHORT_LIVE_COMMANDS)
def test_dual_cohort_live_commands_reject_invalid_auth_before_dependencies(
    tmp_path: Path,
    capsys,
    command: str,
) -> None:
    invalid_state = tmp_path / "invalid-session.json"
    invalid_state.write_text('{"cookies": []}', encoding="utf-8")
    dependency_calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        dependency_calls.append("called")
        raise AssertionError("invalid dual-cohort auth constructed a dependency")

    result = census_cli.main(
        _dual_cohort_cli_argv(command, auth_state=str(invalid_state)),
        session_factory=forbidden,
        repository=forbidden,
        runtime_factory=forbidden,
        service_factory=forbidden,
        observation_service_factory=forbidden,
        crawl_runtime_factory=forbidden,
        staging_sink_factory=forbidden,
    )

    error = json.loads(capsys.readouterr().err)
    assert result == census_cli.EXIT_EVIDENCE_FAILURE
    assert error == {
        "error": "auth state must be a readable valid Playwright storage-state JSON file"
    }
    assert str(invalid_state) not in json.dumps(error)
    assert dependency_calls == []


@pytest.mark.parametrize("command", DUAL_COHORT_LIVE_COMMANDS)
def test_dual_cohort_live_commands_require_exactly_two_baselines_before_dependencies(
    command: str,
) -> None:
    dependency_calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        dependency_calls.append("called")
        raise AssertionError("invalid baseline count constructed a dependency")

    result = census_cli.main(
        _dual_cohort_cli_argv(command, baseline_count=1),
        session_factory=forbidden,
        repository=forbidden,
        runtime_factory=forbidden,
        service_factory=forbidden,
        observation_service_factory=forbidden,
        crawl_runtime_factory=forbidden,
        staging_sink_factory=forbidden,
    )

    assert result == census_cli.EXIT_USAGE
    assert dependency_calls == []


def test_dual_cohort_offline_policy_chain_is_strict_and_uses_no_live_dependencies(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    dependency_calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        dependency_calls.append("called")
        raise AssertionError("offline dual-cohort command touched a live dependency")

    result_probe = _export_dual_cohort_fixture(
        tmp_path / "parents",
        _dual_result_probe_payload(),
    )
    freeze_result = census_cli.main(
        [
            "freeze-result-partition-policy-v1",
            "--result-probe-artifact",
            str(result_probe),
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
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
    result_policy_output = json.loads(capsys.readouterr().out)
    result_policy_artifact = Path(result_policy_output["artifact"])

    supplemental_artifacts = []
    for run_index in (1, 2, 3):
        probe = _dual_supplemental_probe(run_index)
        supplemental_artifacts.append(
            _export_dual_cohort_fixture(
                tmp_path / "parents",
                _dual_supplemental_probe_payload(probe),
                run_id=probe.run_id,
            )
        )
    compare_supplemental = census_cli.main(
        [
            "compare-supplemental-cohort-v1",
            *[
                argument
                for artifact in supplemental_artifacts
                for argument in (
                    "--supplemental-probe-artifact",
                    str(artifact),
                )
            ],
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
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
    supplemental_output = json.loads(capsys.readouterr().out)
    supplemental_comparison_artifact = Path(supplemental_output["artifact"])

    monkeypatch.setattr(
        census_cli,
        "_phase_b_comparison_reference",
        lambda _path: _phase_b_reference(),
    )
    freeze_candidate = census_cli.main(
        [
            "freeze-dual-cohort-policy-v3",
            "--phase-b-comparison-artifact",
            "phase-b",
            "--result-policy-artifact",
            str(result_policy_artifact),
            "--supplemental-comparison-artifact",
            str(supplemental_comparison_artifact),
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
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
    candidate_output = json.loads(capsys.readouterr().out)
    candidate_artifact = Path(candidate_output["artifact"])
    candidate_payload = json.loads(
        (candidate_artifact / "dual-cohort-discovery-policy.json").read_text(
            encoding="utf-8"
        )
    )

    assert freeze_result == census_cli.EXIT_OK
    assert compare_supplemental == census_cli.EXIT_OK
    assert freeze_candidate == census_cli.EXIT_OK
    assert dependency_calls == []
    assert census_cli.verify_live_research_run(result_policy_artifact).valid
    assert census_cli.verify_live_research_run(
        supplemental_comparison_artifact
    ).valid
    assert census_cli.verify_live_research_run(candidate_artifact).valid
    assert candidate_payload["candidate"][
        "result_partition_policy_artifact_hash"
    ] == census_cli._manifest_hash(result_policy_artifact)
    assert candidate_payload["candidate"][
        "supplemental_comparison_artifact_hash"
    ] == census_cli._manifest_hash(supplemental_comparison_artifact)


def test_supplemental_comparison_requires_exactly_three_parents_before_dependencies(
    tmp_path: Path,
) -> None:
    dependency_calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        dependency_calls.append("called")
        raise AssertionError("invalid parent count touched a dependency")

    result = census_cli.main(
        [
            "compare-supplemental-cohort-v1",
            "--supplemental-probe-artifact",
            str(tmp_path / "first"),
            "--supplemental-probe-artifact",
            str(tmp_path / "second"),
        ],
        session_factory=forbidden,
        repository=forbidden,
        runtime_factory=forbidden,
        service_factory=forbidden,
        observation_service_factory=forbidden,
        crawl_runtime_factory=forbidden,
        staging_sink_factory=forbidden,
    )

    assert result == census_cli.EXIT_USAGE
    assert dependency_calls == []


def test_rejected_supplemental_comparison_cannot_freeze_candidate(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    result_probe = _export_dual_cohort_fixture(
        tmp_path / "parents",
        _dual_result_probe_payload(),
    )
    assert census_cli.main(
        [
            "freeze-result-partition-policy-v1",
            "--result-probe-artifact",
            str(result_probe),
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
        ],
        provenance_provider=provenance,
    ) == census_cli.EXIT_OK
    result_policy_artifact = Path(json.loads(capsys.readouterr().out)["artifact"])
    rejected_artifacts = []
    for run_index in (1, 2, 3):
        probe = _dual_supplemental_probe(run_index, accepted=False)
        rejected_artifacts.append(
            _export_dual_cohort_fixture(
                tmp_path / "parents",
                _dual_supplemental_probe_payload(probe),
                run_id=probe.run_id,
            )
        )
    assert census_cli.main(
        [
            "compare-supplemental-cohort-v1",
            *[
                argument
                for artifact in rejected_artifacts
                for argument in (
                    "--supplemental-probe-artifact",
                    str(artifact),
                )
            ],
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
        ],
        provenance_provider=provenance,
    ) == census_cli.EXIT_INCOMPLETE
    comparison_artifact = Path(json.loads(capsys.readouterr().out)["artifact"])
    monkeypatch.setattr(
        census_cli,
        "_phase_b_comparison_reference",
        lambda _path: _phase_b_reference(),
    )

    result = census_cli.main(
        [
            "freeze-dual-cohort-policy-v3",
            "--phase-b-comparison-artifact",
            "phase-b",
            "--result-policy-artifact",
            str(result_policy_artifact),
            "--supplemental-comparison-artifact",
            str(comparison_artifact),
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "candidate"),
        ],
        provenance_provider=provenance,
    )
    error = json.loads(capsys.readouterr().err)

    assert result == census_cli.EXIT_EVIDENCE_FAILURE
    assert error == {"error": "supplemental comparison is valid but rejected"}
    assert not (tmp_path / "candidate").exists()


def test_partial_phase_d_artifact_cannot_enter_complete_cli_comparison(
    tmp_path: Path,
    capsys,
) -> None:
    partial = _dual_partial_run()
    partial_payload = census_cli.result_partial_phase_d_artifact_payload_v3(
        run=partial,
        scope=_dual_partial_scope(),
        baseline=_dual_baseline_reference(),
    )
    partial_artifact = _export_dual_cohort_fixture(
        tmp_path / "parents",
        partial_payload,
        run_id=partial.run_id,
    )
    dependency_calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        dependency_calls.append("called")
        raise AssertionError("offline comparison touched a live dependency")

    result = census_cli.main(
        [
            "compare-stability-dual-cohort-v3",
            "--census-artifact",
            str(partial_artifact),
            "--census-artifact",
            str(tmp_path / "missing-census-2"),
            "--census-artifact",
            str(tmp_path / "missing-census-3"),
            "--fixed-repeat-artifact",
            str(tmp_path / "missing-fixed-1"),
            "--fixed-repeat-artifact",
            str(tmp_path / "missing-fixed-2"),
            "--fixed-repeat-artifact",
            str(tmp_path / "missing-fixed-3"),
        ],
        session_factory=forbidden,
        repository=forbidden,
        runtime_factory=forbidden,
        service_factory=forbidden,
        observation_service_factory=forbidden,
        crawl_runtime_factory=forbidden,
        staging_sink_factory=forbidden,
    )
    error = json.loads(capsys.readouterr().err)

    assert result == census_cli.EXIT_EVIDENCE_FAILURE
    assert "complete dual-cohort run" in error["error"]
    assert dependency_calls == []


def test_complete_dual_cohort_live_command_rejects_partial_parent_before_dependencies(
    tmp_path: Path,
) -> None:
    partial = _dual_partial_run()
    partial_payload = census_cli.result_partial_phase_d_artifact_payload_v3(
        run=partial,
        scope=_dual_partial_scope(),
        baseline=_dual_baseline_reference(),
    )
    partial_artifact = _export_dual_cohort_fixture(
        tmp_path / "parents",
        partial_payload,
        run_id=partial.run_id,
    )
    first = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_1)
    second = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_2)
    auth_state = _saved_session_state(tmp_path / "auth")
    dependency_calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        dependency_calls.append("called")
        raise AssertionError("partial parent constructed a live dependency")

    result = census_cli.main(
        [
            "repeat-fixed-dual-cohort-v3",
            "--candidate-artifact",
            str(partial_artifact),
            "--baseline-artifact",
            str(first),
            "--baseline-artifact",
            str(second),
            "--run-index",
            "1",
            "--window-id",
            "fixed-window-a",
            "--staging-mode",
            "noop",
            "--confirm-live-research",
            "--auth-state",
            str(auth_state),
        ],
        session_factory=forbidden,
        repository=forbidden,
        runtime_factory=forbidden,
        service_factory=forbidden,
        observation_service_factory=forbidden,
        crawl_runtime_factory=forbidden,
        staging_sink_factory=forbidden,
    )

    assert result == census_cli.EXIT_EVIDENCE_FAILURE
    assert dependency_calls == []


def test_complete_dual_cohort_comparison_cli_is_strict_and_offline(
    tmp_path: Path,
    capsys,
) -> None:
    candidate, _, _ = _dual_complete_candidate()
    censuses = (
        _dual_complete_run(
            experiment=census_cli.DUAL_COHORT_CENSUS_EXPERIMENT,
            run_index=1,
            captured_at="2026-07-14T00:00:00+00:00",
            window_id="census-window-a",
            uuid_int=961,
        ),
        _dual_complete_run(
            experiment=census_cli.DUAL_COHORT_CENSUS_EXPERIMENT,
            run_index=2,
            captured_at="2026-07-14T06:00:00+00:00",
            window_id="census-window-b",
            uuid_int=962,
        ),
        _dual_complete_run(
            experiment=census_cli.DUAL_COHORT_CENSUS_EXPERIMENT,
            run_index=3,
            captured_at="2026-07-14T06:10:00+00:00",
            window_id="census-window-b",
            uuid_int=963,
        ),
    )
    fixed = tuple(
        _dual_complete_run(
            experiment=census_cli.DUAL_COHORT_FIXED_REPEAT_EXPERIMENT,
            run_index=index,
            captured_at=f"2026-07-14T07:0{index}:00+00:00",
            window_id="fixed-window-a",
            uuid_int=970 + index,
        )
        for index in (1, 2, 3)
    )
    census_artifacts = []
    fixed_artifacts = []
    for run in (*censuses, *fixed):
        payload = census_cli.dual_cohort_phase_d_run_artifact_payload_v3(
            run=run,
            candidate=candidate,
            baseline=_dual_baseline_reference(),
        )
        artifact = _export_dual_cohort_fixture(
            tmp_path / "parents",
            payload,
            run_id=run.run_id,
        )
        target = (
            census_artifacts
            if run.experiment == census_cli.DUAL_COHORT_CENSUS_EXPERIMENT
            else fixed_artifacts
        )
        target.append(artifact)
    dependency_calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        dependency_calls.append("called")
        raise AssertionError("offline comparison touched a live dependency")

    result = census_cli.main(
        [
            "compare-stability-dual-cohort-v3",
            *[
                argument
                for prefix, artifacts in (
                    ("census", census_artifacts),
                    ("fixed-repeat", fixed_artifacts),
                )
                for artifact in artifacts
                for argument in (f"--{prefix}-artifact", str(artifact))
            ],
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
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
    output = json.loads(capsys.readouterr().out)
    artifact = Path(output["artifact"])

    assert result == census_cli.EXIT_OK
    assert output["accepted"] is True
    assert output["stable_reference_count"] > 0
    assert dependency_calls == []
    assert census_cli.verify_live_research_run(artifact).valid


def test_result_probe_and_partial_phase_d_bind_saved_session_and_no_write(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    first = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_1)
    second = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_2)
    auth_state = _saved_session_state(tmp_path / "auth")
    endpoint_probe = _export_endpoint_probe_fixture(
        tmp_path / "parents",
        parent=_phase_b_reference(),
        run_id="88888888-8888-8888-8888-888888888881",
    )
    probe_state = State()
    probe_runtimes = DualCohortRuntimeFactory(result_runtime_count=1)
    probe_runtime_bindings: list[dict] = []
    technical_writing_partition_id = (
        "2efc511e63bedcdec8da0689fe67d16c022abe932a973ecc3aa7c42f2dc9472c"
    )

    def probe_runtime_factory(**kwargs):
        probe_runtime_bindings.append(dict(kwargs))
        return probe_runtimes(headed=kwargs["headed"])

    result_probe_exit = census_cli.main(
        [
            "probe-result-partitions-v2",
            "--endpoint-probe-artifact",
            str(endpoint_probe),
            "--endpoint-contract-id",
            "recommend-search-list-v1",
            "--partition-id",
            technical_writing_partition_id,
            "--baseline-artifact",
            str(first),
            "--baseline-artifact",
            str(second),
            "--confirm-live-research",
            "--auth-state",
            str(auth_state),
            "--run-id",
            "88888888-8888-8888-8888-888888888882",
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
        ],
        session_factory=lambda: FakeSession(probe_state.log),
        repository=FakeRepository(probe_state),
        runtime_factory=probe_runtime_factory,
        service_factory=lambda: OfferTodayResearchLiveService(
            sleep=_phase_c_no_sleep,
            clock=IncrementingClock(),
        ),
        observation_service_factory=lambda db: FakeObservationService(
            db,
            probe_state,
        ),
        provenance_provider=provenance,
    )
    probe_capture = capsys.readouterr()
    assert result_probe_exit == census_cli.EXIT_OK, probe_capture.err
    probe_output = json.loads(probe_capture.out)
    result_probe_artifact = Path(probe_output["artifact"])
    result_probe_payload = json.loads(
        (result_probe_artifact / "result-partition-probe.json").read_text(
            encoding="utf-8"
        )
    )

    assert probe_output["accepted"] is True
    assert result_probe_payload["no_write"]["detail_attempts"] == 0
    assert result_probe_payload["no_write"]["product_writes"] == 0
    assert result_probe_payload["execution"]["conditions"][0]["condition"][
        "partition_id"
    ] == technical_writing_partition_id
    assert probe_runtimes.created[0].requests[0][0]["jobFunctionCodes"] == [118018]
    assert census_cli.verify_live_research_run(result_probe_artifact).valid

    freeze_result_exit = census_cli.main(
        [
            "freeze-result-partition-policy-v1",
            "--result-probe-artifact",
            str(result_probe_artifact),
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
        ],
        provenance_provider=provenance,
    )
    result_policy_output = json.loads(capsys.readouterr().out)
    result_policy_artifact = Path(result_policy_output["artifact"])
    assert freeze_result_exit == census_cli.EXIT_OK

    monkeypatch.setattr(
        census_cli,
        "_phase_b_comparison_reference",
        lambda _path: _phase_b_reference(),
    )
    partial_state = State()
    partial_runtimes = DualCohortRuntimeFactory(result_runtime_count=3)
    partial_runtime_bindings: list[dict] = []

    def partial_runtime_factory(**kwargs):
        partial_runtime_bindings.append(dict(kwargs))
        return partial_runtimes(headed=kwargs["headed"])

    partial_exit = census_cli.main(
        [
            "repeat-fixed-result-partial-v3",
            "--phase-b-comparison-artifact",
            "phase-b",
            "--result-policy-artifact",
            str(result_policy_artifact),
            "--baseline-artifact",
            str(first),
            "--baseline-artifact",
            str(second),
            "--run-index",
            "1",
            "--window-id",
            "partial-window-a",
            "--staging-mode",
            "noop",
            "--confirm-live-research",
            "--auth-state",
            str(auth_state),
            "--run-id",
            RUN_ID,
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
        ],
        session_factory=lambda: FakeSession(partial_state.log),
        repository=FakeRepository(partial_state),
        runtime_factory=partial_runtime_factory,
        service_factory=lambda: OfferTodayResearchLiveService(
            sleep=_phase_c_no_sleep,
            clock=IncrementingClock(),
        ),
        observation_service_factory=lambda db: FakeObservationService(
            db,
            partial_state,
        ),
        crawl_runtime_factory=lambda: (_ for _ in ()).throw(
            AssertionError("noop partial run constructed a crawl runtime")
        ),
        provenance_provider=provenance,
    )
    partial_output = json.loads(capsys.readouterr().out)
    partial_artifact = Path(partial_output["artifact"])
    partial_payload = json.loads(
        (partial_artifact / "dual-cohort-phase-d-run.json").read_text(
            encoding="utf-8"
        )
    )
    artifact_text = _artifact_text(partial_artifact)
    cookie_value = json.loads(auth_state.read_text(encoding="utf-8"))["cookies"][
        0
    ]["value"]
    expected_sha = hashlib.sha256(auth_state.read_bytes()).hexdigest()

    assert partial_exit == census_cli.EXIT_INCOMPLETE
    assert partial_output["accepted"] is False
    assert partial_output["downstream_eligible"] is False
    assert partial_output["partial_research_complete"] is True
    assert partial_payload["stable_reference_frozen"] is False
    assert partial_payload["run"]["product"]["detail_attempts"] == 0
    assert partial_payload["run"]["product"]["product_writes"] == 0
    assert census_cli.verify_live_research_run(partial_artifact).valid
    assert probe_runtime_bindings and partial_runtime_bindings
    assert all(
        binding["auth_state_path"] == str(auth_state.resolve())
        for binding in (*probe_runtime_bindings, *partial_runtime_bindings)
    )
    manifest = json.loads(
        (partial_artifact / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["provenance"]["runtime_context"][
        "session_state_sha256"
    ] == expected_sha
    assert str(auth_state.resolve()) not in artifact_text
    assert cookie_value not in artifact_text


def test_supplemental_probe_binds_result_policy_baselines_and_no_write(
    tmp_path: Path,
    capsys,
) -> None:
    policy_payload = census_cli.result_partition_policy_artifact_payload_v1(
        _dual_result_policy()
    )
    policy_artifact = _export_dual_cohort_fixture(
        tmp_path / "parents",
        policy_payload,
    )
    first = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_1)
    second = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_2)
    auth_state = _saved_session_state(tmp_path / "auth")
    state = State()
    runtimes = DualCohortRuntimeFactory(result_runtime_count=0)
    runtime_bindings: list[dict] = []

    def runtime_factory(**kwargs):
        runtime_bindings.append(dict(kwargs))
        return runtimes(headed=kwargs["headed"])

    result = census_cli.main(
        [
            "probe-supplemental-cohort-v1",
            "--result-policy-artifact",
            str(policy_artifact),
            "--endpoint-contract-id",
            "recommend-search-list-v1",
            "--run-index",
            "1",
            "--baseline-artifact",
            str(first),
            "--baseline-artifact",
            str(second),
            "--confirm-live-research",
            "--auth-state",
            str(auth_state),
            "--run-id",
            RUN_ID,
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
        ],
        session_factory=lambda: FakeSession(state.log),
        repository=FakeRepository(state),
        runtime_factory=runtime_factory,
        service_factory=lambda: OfferTodayResearchLiveService(
            sleep=_phase_c_no_sleep,
            clock=IncrementingClock(),
        ),
        observation_service_factory=lambda db: FakeObservationService(db, state),
        provenance_provider=provenance,
    )
    output = json.loads(capsys.readouterr().out)
    artifact = Path(output["artifact"])
    payload = json.loads(
        (artifact / "supplemental-cohort-probe.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (artifact / "manifest.json").read_text(encoding="utf-8")
    )

    assert result == census_cli.EXIT_OK
    assert output["accepted"] is True
    assert payload["parent"]["manifest_hash"] == census_cli._manifest_hash(
        policy_artifact
    )
    assert set(payload["baseline"]["artifact_hashes"]) == {
        census_cli._manifest_hash(first),
        census_cli._manifest_hash(second),
    }
    assert payload["no_write"]["detail_attempts"] == 0
    assert payload["no_write"]["product_writes"] == 0
    assert payload["no_write"]["product_data_unchanged"] is True
    assert len(runtime_bindings) == 3
    assert all(
        binding == {
            "auth_state_path": str(auth_state.resolve()),
            "headed": False,
        }
        for binding in runtime_bindings
    )
    assert manifest["provenance"]["runtime_context"][
        "session_state_sha256"
    ] == hashlib.sha256(auth_state.read_bytes()).hexdigest()
    assert census_cli.verify_live_research_run(artifact).valid


def test_complete_dual_cohort_fixed_cli_exports_strict_no_write_artifact(
    tmp_path: Path,
    capsys,
) -> None:
    candidate, result_policy, supplemental_payload = _dual_complete_candidate()
    candidate_payload = census_cli.dual_cohort_candidate_artifact_payload_v3(
        candidate=candidate,
        result_policy=result_policy,
        supplemental_comparison_payload=supplemental_payload,
    )
    candidate_artifact = _export_dual_cohort_fixture(
        tmp_path / "parents",
        candidate_payload,
    )
    first = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_1)
    second = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_2)
    auth_state = _saved_session_state(tmp_path / "auth")
    state = State()
    runtimes = DualCohortRuntimeFactory(result_runtime_count=3)
    runtime_bindings: list[dict] = []

    def runtime_factory(**kwargs):
        runtime_bindings.append(dict(kwargs))
        return runtimes(headed=kwargs["headed"])

    result = census_cli.main(
        [
            "repeat-fixed-dual-cohort-v3",
            "--candidate-artifact",
            str(candidate_artifact),
            "--baseline-artifact",
            str(first),
            "--baseline-artifact",
            str(second),
            "--run-index",
            "1",
            "--window-id",
            "fixed-window-a",
            "--staging-mode",
            "noop",
            "--confirm-live-research",
            "--auth-state",
            str(auth_state),
            "--run-id",
            RUN_ID,
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
        ],
        session_factory=lambda: FakeSession(state.log),
        repository=FakeRepository(state),
        runtime_factory=runtime_factory,
        service_factory=lambda: OfferTodayResearchLiveService(
            sleep=_phase_c_no_sleep,
            clock=IncrementingClock(),
        ),
        observation_service_factory=lambda db: FakeObservationService(db, state),
        crawl_runtime_factory=lambda: (_ for _ in ()).throw(
            AssertionError("noop complete run constructed a crawl runtime")
        ),
        provenance_provider=provenance,
    )
    output = json.loads(capsys.readouterr().out)
    artifact = Path(output["artifact"])
    payload = json.loads(
        (artifact / "dual-cohort-phase-d-run.json").read_text(encoding="utf-8")
    )
    run = payload["run"]

    assert result == census_cli.EXIT_OK
    assert output["accepted"] is True
    assert output["downstream_eligible"] is True
    assert len(run["result_conditions"]) == 3
    assert run["supplemental_condition"] is not None
    assert run["product"]["detail_attempts"] == 0
    assert run["product"]["product_writes"] == 0
    assert run["product"]["jobs_unchanged"] is True
    assert run["product"]["companies_unchanged"] is True
    assert state.created_metadata.request_budget == {
        "listing_logical": 2_000,
        "listing_attempt_max": 6_000,
        "detail": 0,
        "product_writes": 0,
    }
    assert len(runtime_bindings) == 4
    assert all(
        binding == {
            "auth_state_path": str(auth_state.resolve()),
            "headed": False,
        }
        for binding in runtime_bindings
    )
    assert census_cli.verify_live_research_run(artifact).valid


@pytest.mark.parametrize("failure_stage", ("end_snapshot", "finalization"))
def test_dual_cohort_post_run_failures_preserve_sanitized_strict_prefix(
    tmp_path: Path,
    capsys,
    monkeypatch,
    failure_stage: str,
) -> None:
    policy_payload = census_cli.result_partition_policy_artifact_payload_v1(
        _dual_result_policy()
    )
    policy_artifact = _export_dual_cohort_fixture(
        tmp_path / "parents",
        policy_payload,
    )
    first = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_1)
    second = baseline_artifact(tmp_path / "baselines", BASELINE_RUN_2)
    auth_state = _saved_session_state(tmp_path / "auth")
    monkeypatch.setattr(
        census_cli,
        "_phase_b_comparison_reference",
        lambda _path: _phase_b_reference(),
    )
    state = State()
    repository = FakeRepository(
        state,
        end_snapshot_error=(
            RuntimeError("secret dual end snapshot detail")
            if failure_stage == "end_snapshot"
            else None
        ),
    )
    if failure_stage == "finalization":
        state.finish_errors.append(RuntimeError("secret dual finalization detail"))
    runtimes = DualCohortRuntimeFactory(result_runtime_count=3)

    def runtime_factory(**kwargs):
        return runtimes(headed=kwargs["headed"])

    result = census_cli.main(
        [
            "repeat-fixed-result-partial-v3",
            "--phase-b-comparison-artifact",
            "phase-b",
            "--result-policy-artifact",
            str(policy_artifact),
            "--baseline-artifact",
            str(first),
            "--baseline-artifact",
            str(second),
            "--run-index",
            "1",
            "--window-id",
            "partial-window-a",
            "--staging-mode",
            "noop",
            "--confirm-live-research",
            "--auth-state",
            str(auth_state),
            "--run-id",
            RUN_ID,
            "--repo-root",
            str(Path.cwd()),
            "--artifact-root",
            str(tmp_path / "runs"),
        ],
        session_factory=lambda: FakeSession(state.log),
        repository=repository,
        runtime_factory=runtime_factory,
        service_factory=lambda: OfferTodayResearchLiveService(
            sleep=_phase_c_no_sleep,
            clock=IncrementingClock(),
        ),
        observation_service_factory=lambda db: FakeObservationService(db, state),
        provenance_provider=provenance,
    )
    output = json.loads(capsys.readouterr().out)
    artifact = Path(output["artifact"])
    payload_text = (artifact / "dual-cohort-phase-d-run.json").read_text(
        encoding="utf-8"
    )
    payload = json.loads(payload_text)

    assert result == census_cli.EXIT_EVIDENCE_FAILURE
    assert output["accepted"] is False
    assert output["failure_reason"] == (
        "unexpected_dual_cohort_phase_d_error:RuntimeError"
    )
    assert payload["run"]["failure_reason"] == output["failure_reason"]
    assert "secret dual end snapshot detail" not in payload_text
    assert "secret dual finalization detail" not in payload_text
    assert payload["run"]["product"]["end_snapshot_captured"] is (
        failure_stage != "end_snapshot"
    )
    assert census_cli.verify_live_research_run(artifact).valid
