from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from app.scraper.offertoday.category_registry import (
    OFFERTODAY_CATEGORIES_L1,
    OFFERTODAY_CATEGORY_CATALOG_VERSION,
    offertoday_category_catalog_hash,
)
from app.sources.offertoday.listing_contract import offertoday_endpoint_contract
from app.sources.offertoday.research.artifacts import (
    ResearchProvenance,
    export_research_artifact,
    verify_research_artifact,
)
from app.sources.offertoday.research.live_contracts import (
    DiscoveryPolicyCandidateV2,
)
from app.sources.offertoday.research.phase_d import (
    PHASE_D_COMPARISON_EXPERIMENT,
    discovery_policy_candidate_artifact_payload,
    phase_d_run_artifact_payload,
)
from app.sources.offertoday.research.phase_d_stage_gate import (
    build_phase_d_comparison_artifact_payload,
    phase_d_artifact_events,
    phase_d_artifact_reference,
    phase_d_metadata,
    verify_phase_d_artifact,
)
from app.sources.offertoday.research.partition_research import (
    offertoday_partition_catalog_hash,
    phase_c_request_policy_hash,
    top_level_partition,
)
from app.sources.offertoday.research.stage_gate import verify_live_research_run
from test_offertoday_phase_d import (
    _baseline_reference,
    _candidate as _complete_candidate,
    _phase_d_run,
    _phase_d_runs,
    _product_evidence,
)


CAPTURED_AT = "2026-07-13T12:00:00+00:00"


def _candidate() -> DiscoveryPolicyCandidateV2:
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
        retained_partition_ids=(partitions[0].partition_id,),
        retained_condition_hashes=("a" * 64,),
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
        phase_b_comparison_artifact_hash="b" * 64,
        phase_c_comparison_artifact_hash="c" * 64,
        source_artifact_hash="d" * 64,
        deferred_issue_ids=(4, 5),
    )


def _provenance() -> ResearchProvenance:
    return ResearchProvenance(
        commit_sha="fixture",
        working_tree_patch="",
        source_hashes={},
        compose_file_hashes={},
        captured_at=CAPTURED_AT,
        runtime_context={"session_mode": "offline-fixture"},
        untracked_file_hashes={},
        excluded_tracked_file_hashes={},
        excluded_untracked_file_hashes={},
    )


def _export_candidate(
    root: Path,
    *,
    payload: dict | None = None,
    metadata: dict | None = None,
    events: list[dict] | None = None,
) -> Path:
    run_id = str(uuid4())
    payload = payload or discovery_policy_candidate_artifact_payload(_candidate())
    metadata = metadata or phase_d_metadata(
        payload,
        run_id=run_id,
        planner_version="fixture",
    )
    events = events or phase_d_artifact_events(payload, created_at=CAPTURED_AT)
    return export_research_artifact(
        root=root,
        run_id=run_id,
        metadata=metadata,
        events=events,
        provenance=_provenance(),
        json_files={"discovery-policy.json": payload},
    )


def _export_phase_d_payload(
    root: Path,
    payload: dict,
    *,
    run_id: str,
) -> Path:
    file_name = (
        "phase-d-comparison.json"
        if payload["experiment"] == PHASE_D_COMPARISON_EXPERIMENT
        else "phase-d-run.json"
    )
    return export_research_artifact(
        root=root,
        run_id=run_id,
        metadata=phase_d_metadata(
            payload,
            run_id=run_id,
            planner_version="fixture",
        ),
        events=phase_d_artifact_events(payload, created_at=CAPTURED_AT),
        provenance=_provenance(),
        json_files={file_name: payload},
    )
def test_phase_d_candidate_passes_generic_direct_and_routed_replay(
    tmp_path: Path,
) -> None:
    artifact = _export_candidate(tmp_path)

    assert verify_research_artifact(artifact).valid is True
    assert verify_phase_d_artifact(artifact).valid is True
    routed = verify_live_research_run(artifact)
    assert routed.valid is True
    assert routed.experiment == "discovery-policy-candidate-v2"


def test_phase_d_candidate_rejects_rehashed_semantic_tamper(
    tmp_path: Path,
) -> None:
    original = discovery_policy_candidate_artifact_payload(_candidate())
    metadata_run_id = str(uuid4())
    metadata = phase_d_metadata(
        original,
        run_id=metadata_run_id,
        planner_version="fixture",
    )
    events = phase_d_artifact_events(original, created_at=CAPTURED_AT)
    tampered = deepcopy(original)
    tampered["candidate"]["max_pages_per_condition"] = 10

    artifact = export_research_artifact(
        root=tmp_path,
        run_id=metadata_run_id,
        metadata=metadata,
        events=events,
        provenance=_provenance(),
        json_files={"discovery-policy.json": tampered},
    )

    assert verify_research_artifact(artifact).valid is True
    assert verify_phase_d_artifact(artifact).valid is False
    assert verify_live_research_run(artifact).valid is False


def test_unknown_phase_d_next_version_fails_closed(tmp_path: Path) -> None:
    run_id = str(uuid4())
    artifact = export_research_artifact(
        root=tmp_path,
        run_id=run_id,
        metadata={
            "experiment": "discovery-policy-candidate-v3",
            "crawl_job_id": run_id,
        },
        events=[
            {
                "sequence_no": 1,
                "event_type": "research.candidate_frozen",
                "payload": {},
                "emitted_by": "offertoday-research",
                "created_at": CAPTURED_AT,
            }
        ],
        provenance=_provenance(),
        json_files={"discovery-policy.json": {}},
    )

    assert verify_research_artifact(artifact).valid is True
    verification = verify_live_research_run(artifact)
    assert verification.valid is False
    assert "unsupported_live_experiment" in verification.issues


def test_phase_d_run_passes_generic_direct_and_routed_replay(
    tmp_path: Path,
) -> None:
    candidate = _complete_candidate()
    run = replace(
        _phase_d_run(
            experiment="cursor-fixed-repeat-v2",
            run_index=1,
            captured_at=CAPTURED_AT,
            window_id="fixed-window-a",
            uuid_int=601,
        ),
        candidate_hash=candidate.candidate_hash,
    )
    payload = phase_d_run_artifact_payload(
        run=run,
        candidate=candidate,
        baseline=_baseline_reference(),
        product=_product_evidence(),
    )
    artifact = _export_phase_d_payload(
        tmp_path,
        payload,
        run_id=run.run_id,
    )

    assert verify_research_artifact(artifact).valid is True
    assert verify_phase_d_artifact(artifact).valid is True
    assert verify_live_research_run(artifact).valid is True


def test_phase_d_comparison_replays_six_strict_parent_projections(
    tmp_path: Path,
) -> None:
    candidate = _complete_candidate()
    censuses, fixed = _phase_d_runs()
    parent_inputs = []
    for run in (*censuses, *fixed):
        bound_run = replace(run, candidate_hash=candidate.candidate_hash)
        run_payload = phase_d_run_artifact_payload(
            run=bound_run,
            candidate=candidate,
            baseline=_baseline_reference(),
            product=_product_evidence(),
        )
        artifact = _export_phase_d_payload(
            tmp_path,
            run_payload,
            run_id=bound_run.run_id,
        )
        parent_inputs.append(
            (phase_d_artifact_reference(artifact), run_payload)
        )

    comparison_payload = build_phase_d_comparison_artifact_payload(
        parent_inputs,
        active_holdout_ids=("active-holdout",),
    )
    comparison_run_id = str(uuid4())
    comparison_artifact = _export_phase_d_payload(
        tmp_path,
        comparison_payload,
        run_id=comparison_run_id,
    )

    assert verify_research_artifact(comparison_artifact).valid is True
    assert verify_phase_d_artifact(comparison_artifact).valid is True
    assert verify_live_research_run(comparison_artifact).valid is True
