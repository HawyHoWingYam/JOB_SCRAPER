from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from app.sources.offertoday.research.artifacts import (
    ResearchProvenance,
    export_research_artifact,
    verify_research_artifact,
)
from app.sources.offertoday.research.dual_cohort import (
    DUAL_COHORT_CENSUS_EXPERIMENT,
    DUAL_COHORT_COMPARISON_EXPERIMENT,
    DUAL_COHORT_DISCOVERY_CANDIDATE_EXPERIMENT,
    DUAL_COHORT_FIXED_REPEAT_EXPERIMENT,
    RESULT_PARTITION_POLICY_EXPERIMENT,
    RESULT_PARTITION_PROBE_EXPERIMENT,
    RESULT_PARTIAL_CENSUS_EXPERIMENT,
    dual_cohort_phase_d_run_artifact_payload_v3,
    SUPPLEMENTAL_COHORT_COMPARISON_EXPERIMENT,
    SUPPLEMENTAL_COHORT_PROBE_EXPERIMENT,
    ResultPartitionConditionEvidenceV2,
    ResultPartitionProbeExecutionV2,
    ResultPartitionProbePlanV2,
    build_dual_cohort_discovery_candidate_v3,
    canonical_dual_cohort_hash,
    dual_cohort_candidate_artifact_payload_v3,
    freeze_result_partition_policy_v1,
    result_partition_policy_artifact_payload_v1,
    result_partial_phase_d_artifact_payload_v3,
    supplemental_cohort_comparison_payload_v1,
)
from app.sources.offertoday.research.dual_cohort_stage_gate import (
    build_dual_cohort_probe_artifact_payload,
    build_dual_cohort_phase_d_comparison_artifact_payload_v3,
    dual_cohort_phase_d_artifact_reference_v3,
    dual_cohort_artifact_events,
    dual_cohort_metadata,
    validate_dual_cohort_phase_d_comparison_artifact_payload_v3,
    verify_dual_cohort_artifact,
)
from app.sources.offertoday.research.partition_research import top_level_partition
from app.sources.offertoday.research.partition_stage_gate import (
    PhaseCArtifactReference,
    PhaseCNoWriteEvidence,
)
from app.sources.offertoday.research.stage_gate import verify_live_research_run
from test_offertoday_dual_cohort import (
    _complete_candidate,
    _complete_run,
    _hash,
    _result_condition,
    _result_policy,
    _partial_run,
    _partial_scope,
    _supplemental_probe,
)
from test_offertoday_phase_d import _baseline_reference


CAPTURED_AT = "2026-07-14T02:00:00+00:00"


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


def _result_probe_payload() -> dict:
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
    return build_dual_cohort_probe_artifact_payload(
        execution=execution,
        parent=PhaseCArtifactReference(
            experiment="endpoint-contract-probe-v1",
            run_id=str(uuid4()),
            manifest_hash=_hash("endpoint-parent-manifest"),
            payload_hash=_hash("endpoint-parent-payload"),
            accepted=True,
        ),
        baseline=_baseline_reference(),
        no_write=_no_write(),
    )


def _no_write() -> PhaseCNoWriteEvidence:
    baseline = _baseline_reference()
    return PhaseCNoWriteEvidence(
        start_snapshot_hash=baseline.snapshot_hash,
        end_snapshot_hash=baseline.snapshot_hash,
        start_product_data_hash=_hash("product"),
        end_product_data_hash=_hash("product"),
        start_inventory_hash=baseline.inventory_hash,
        end_inventory_hash=baseline.inventory_hash,
        stage_calls=0,
        would_stage_rows=0,
    )


def _supplemental_probe_payload(probe) -> dict:
    return build_dual_cohort_probe_artifact_payload(
        execution=probe,
        parent=PhaseCArtifactReference(
            experiment=RESULT_PARTITION_POLICY_EXPERIMENT,
            run_id=str(uuid4()),
            manifest_hash=_hash("result-policy-parent-manifest"),
            payload_hash=_hash("result-policy-parent-payload"),
            accepted=True,
        ),
        baseline=_baseline_reference(),
        no_write=_no_write(),
    )


def _file_name(experiment: str) -> str:
    return {
        DUAL_COHORT_DISCOVERY_CANDIDATE_EXPERIMENT: (
            "dual-cohort-discovery-policy.json"
        ),
        RESULT_PARTIAL_CENSUS_EXPERIMENT: "dual-cohort-phase-d-run.json",
        DUAL_COHORT_CENSUS_EXPERIMENT: "dual-cohort-phase-d-run.json",
        DUAL_COHORT_FIXED_REPEAT_EXPERIMENT: "dual-cohort-phase-d-run.json",
        DUAL_COHORT_COMPARISON_EXPERIMENT: (
            "dual-cohort-phase-d-comparison.json"
        ),
        RESULT_PARTITION_PROBE_EXPERIMENT: "result-partition-probe.json",
        RESULT_PARTITION_POLICY_EXPERIMENT: "result-partition-policy.json",
        SUPPLEMENTAL_COHORT_PROBE_EXPERIMENT: "supplemental-cohort-probe.json",
        SUPPLEMENTAL_COHORT_COMPARISON_EXPERIMENT: (
            "supplemental-cohort-comparison.json"
        ),
    }[experiment]


def _export(
    root: Path,
    payload: dict,
    *,
    run_id: str | None = None,
    metadata: dict | None = None,
    events: list[dict] | None = None,
    provenance: ResearchProvenance | None = None,
) -> Path:
    artifact_run_id = run_id or str(uuid4())
    return export_research_artifact(
        root=root,
        run_id=artifact_run_id,
        metadata=metadata
        or dual_cohort_metadata(
            payload,
            run_id=artifact_run_id,
            planner_version="fixture",
        ),
        events=events
        or dual_cohort_artifact_events(payload, created_at=CAPTURED_AT),
        provenance=provenance or _provenance(),
        json_files={_file_name(payload["experiment"]): payload},
    )


def _assert_all_verifiers_accept(artifact: Path, experiment: str) -> None:
    assert verify_research_artifact(artifact).valid is True
    assert verify_dual_cohort_artifact(artifact).valid is True
    routed = verify_live_research_run(artifact)
    assert routed.valid is True
    assert routed.experiment == experiment


def test_result_probe_and_policy_pass_direct_and_routed_replay(
    tmp_path: Path,
) -> None:
    probe_payload = _result_probe_payload()
    probe_artifact = _export(tmp_path, probe_payload)
    _assert_all_verifiers_accept(
        probe_artifact,
        RESULT_PARTITION_PROBE_EXPERIMENT,
    )

    execution = ResultPartitionProbeExecutionV2.from_payload(
        probe_payload["execution"]
    )
    policy = freeze_result_partition_policy_v1(
        execution,
        source_probe_artifact_hash=_hash("strict-result-probe"),
    )
    policy_payload = result_partition_policy_artifact_payload_v1(policy)
    policy_artifact = _export(tmp_path, policy_payload)
    _assert_all_verifiers_accept(
        policy_artifact,
        RESULT_PARTITION_POLICY_EXPERIMENT,
    )


def test_probe_wrapper_rejects_no_write_state_that_does_not_match_baseline() -> (
    None
):
    execution = ResultPartitionProbeExecutionV2.from_payload(
        _result_probe_payload()["execution"]
    )
    mismatched = replace(
        _no_write(),
        start_snapshot_hash=_hash("different-snapshot"),
        end_snapshot_hash=_hash("different-snapshot"),
    )

    with pytest.raises(ValueError, match="start state must match"):
        build_dual_cohort_probe_artifact_payload(
            execution=execution,
            parent=PhaseCArtifactReference(
                experiment="endpoint-contract-probe-v1",
                run_id=str(uuid4()),
                manifest_hash=_hash("endpoint-parent-manifest"),
                payload_hash=_hash("endpoint-parent-payload"),
                accepted=True,
            ),
            baseline=_baseline_reference(),
            no_write=mismatched,
        )


def test_supplemental_probe_and_comparison_pass_strict_replay(
    tmp_path: Path,
) -> None:
    probes = tuple(_supplemental_probe(index) for index in (1, 2, 3))
    for probe in probes:
        artifact = _export(
            tmp_path,
            _supplemental_probe_payload(probe),
            run_id=probe.run_id,
        )
        _assert_all_verifiers_accept(
            artifact,
            SUPPLEMENTAL_COHORT_PROBE_EXPERIMENT,
        )

    comparison_payload = supplemental_cohort_comparison_payload_v1(probes)
    comparison_artifact = _export(tmp_path, comparison_payload)
    _assert_all_verifiers_accept(
        comparison_artifact,
        SUPPLEMENTAL_COHORT_COMPARISON_EXPERIMENT,
    )


def test_dual_cohort_candidate_passes_strict_replay(tmp_path: Path) -> None:
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

    artifact = _export(tmp_path, payload)
    _assert_all_verifiers_accept(
        artifact,
        DUAL_COHORT_DISCOVERY_CANDIDATE_EXPERIMENT,
    )


def test_partial_and_complete_phase_d_runs_use_distinct_strict_contracts(
    tmp_path: Path,
) -> None:
    partial = _partial_run()
    partial_payload = result_partial_phase_d_artifact_payload_v3(
        run=partial,
        scope=_partial_scope(),
        baseline=_baseline_reference(),
    )
    partial_artifact = _export(
        tmp_path,
        partial_payload,
        run_id=partial.run_id,
    )
    _assert_all_verifiers_accept(
        partial_artifact,
        RESULT_PARTIAL_CENSUS_EXPERIMENT,
    )
    assert partial_payload["accepted"] is False
    assert partial_payload["downstream_eligible"] is False
    with pytest.raises(ValueError, match="complete dual-cohort run"):
        dual_cohort_phase_d_artifact_reference_v3(partial_artifact)

    candidate, _, _ = _complete_candidate()
    complete = _complete_run(
        experiment=DUAL_COHORT_CENSUS_EXPERIMENT,
        run_index=1,
        captured_at="2026-07-14T00:00:00+00:00",
        window_id="census-window-a",
        uuid_int=901,
    )
    complete_payload = dual_cohort_phase_d_run_artifact_payload_v3(
        run=complete,
        candidate=candidate,
        baseline=_baseline_reference(),
    )
    complete_artifact = _export(
        tmp_path,
        complete_payload,
        run_id=complete.run_id,
    )
    _assert_all_verifiers_accept(
        complete_artifact,
        DUAL_COHORT_CENSUS_EXPERIMENT,
    )
    assert complete_payload["accepted"] is True
    assert complete_payload["downstream_eligible"] is True


def test_complete_dual_cohort_comparison_passes_strict_replay(
    tmp_path: Path,
) -> None:
    censuses = (
        _complete_run(
            experiment=DUAL_COHORT_CENSUS_EXPERIMENT,
            run_index=1,
            captured_at="2026-07-14T00:00:00+00:00",
            window_id="census-window-a",
            uuid_int=911,
        ),
        _complete_run(
            experiment=DUAL_COHORT_CENSUS_EXPERIMENT,
            run_index=2,
            captured_at="2026-07-14T06:00:00+00:00",
            window_id="census-window-b",
            uuid_int=912,
        ),
        _complete_run(
            experiment=DUAL_COHORT_CENSUS_EXPERIMENT,
            run_index=3,
            captured_at="2026-07-14T06:10:00+00:00",
            window_id="census-window-b",
            uuid_int=913,
        ),
    )
    fixed = tuple(
        _complete_run(
            experiment=DUAL_COHORT_FIXED_REPEAT_EXPERIMENT,
            run_index=index,
            captured_at=f"2026-07-14T07:0{index}:00+00:00",
            window_id="fixed-window-a",
            uuid_int=920 + index,
        )
        for index in (1, 2, 3)
    )
    candidate, _, _ = _complete_candidate()
    parents = []
    for run in (*censuses, *fixed):
        run_payload = dual_cohort_phase_d_run_artifact_payload_v3(
            run=run,
            candidate=candidate,
            baseline=_baseline_reference(),
        )
        run_artifact = _export(
            tmp_path,
            run_payload,
            run_id=run.run_id,
        )
        parents.append(
            (
                dual_cohort_phase_d_artifact_reference_v3(run_artifact),
                run_payload,
            )
        )
    payload = build_dual_cohort_phase_d_comparison_artifact_payload_v3(
        parents
    )
    artifact = _export(tmp_path, payload)

    _assert_all_verifiers_accept(
        artifact,
        DUAL_COHORT_COMPARISON_EXPERIMENT,
    )
    assert payload["stable_reference_frozen"] is True

    tampered = copy.deepcopy(payload)
    tampered["parents"][0]["payload_hash"] = _hash("forged-parent-payload")
    tampered["parent_set_hash"] = canonical_dual_cohort_hash(
        tampered["parents"]
    )
    with pytest.raises(ValueError, match="parent/run evidence mismatch"):
        validate_dual_cohort_phase_d_comparison_artifact_payload_v3(tampered)


def test_result_probe_rejects_rehashed_semantic_tamper(
    tmp_path: Path,
) -> None:
    original = _result_probe_payload()
    run_id = str(uuid4())
    metadata = dual_cohort_metadata(
        original,
        run_id=run_id,
        planner_version="fixture",
    )
    events = dual_cohort_artifact_events(original, created_at=CAPTURED_AT)
    tampered = copy.deepcopy(original)
    tampered["execution"]["conditions"][0]["terminal"][
        "result_exhausted"
    ] = False
    tampered["execution"]["conditions"][0]["terminal"]["failing_gates"] = [
        "forged_gate"
    ]
    tampered["execution"]["conditions"][0]["accepted"] = False
    tampered["execution"]["accepted"] = False
    tampered["accepted"] = False

    artifact = _export(
        tmp_path,
        tampered,
        run_id=run_id,
        metadata=metadata,
        events=events,
    )

    assert verify_research_artifact(artifact).valid is True
    assert verify_dual_cohort_artifact(artifact).valid is False
    assert verify_live_research_run(artifact).valid is False


def test_supplemental_comparison_rejects_rehashed_semantic_tamper(
    tmp_path: Path,
) -> None:
    probes = tuple(_supplemental_probe(index) for index in (1, 2, 3))
    original = supplemental_cohort_comparison_payload_v1(probes)
    run_id = str(uuid4())
    metadata = dual_cohort_metadata(
        original,
        run_id=run_id,
        planner_version="fixture",
    )
    events = dual_cohort_artifact_events(original, created_at=CAPTURED_AT)
    tampered = copy.deepcopy(original)
    tampered["comparison"]["stable_supplemental_ids"].append("forged")
    tampered["comparison"]["stable_supplemental_hash"] = _hash("forged")
    tampered["comparison_hash"] = _hash("rehashed")

    artifact = _export(
        tmp_path,
        tampered,
        run_id=run_id,
        metadata=metadata,
        events=events,
    )

    assert verify_research_artifact(artifact).valid is True
    assert verify_dual_cohort_artifact(artifact).valid is False
    assert verify_live_research_run(artifact).valid is False


def test_strict_replay_rejects_saved_session_path_in_provenance(
    tmp_path: Path,
) -> None:
    payload = result_partition_policy_artifact_payload_v1(_result_policy())
    artifact = _export(
        tmp_path,
        payload,
        provenance=replace(
            _provenance(),
            runtime_context={
                "session_mode": "saved-session",
                "auth_state_path": "C:/secret/saved-session.json",
            },
        ),
    )

    assert verify_research_artifact(artifact).valid is True
    assert verify_dual_cohort_artifact(artifact).valid is False
    assert verify_live_research_run(artifact).valid is False
