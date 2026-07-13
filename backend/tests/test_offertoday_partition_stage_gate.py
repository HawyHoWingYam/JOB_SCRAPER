from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from app.sources.offertoday.listing_contract import offertoday_endpoint_contract
from app.sources.offertoday.research.artifacts import (
    ResearchProvenance,
    export_research_artifact,
    verify_research_artifact,
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
    canonical_phase_c_hash,
    top_level_partition,
)
from app.sources.offertoday.research.partition_stage_gate import (
    PhaseCArtifactReference,
    PhaseCBaselineReference,
    PhaseCNoWriteEvidence,
    build_partition_comparison_artifact_payload,
    build_partition_probe_parent_projection,
    build_phase_c_probe_artifact_payload,
    phase_c_artifact_events,
    phase_c_comparison_metadata,
    phase_c_probe_metadata,
    verify_phase_c_artifact,
)
from app.sources.offertoday.research.stage_gate import verify_live_research_run


SEARCH_CONTRACT_ID = "recommend-search-list-v1"
BROWSE_CONTRACT_ID = "recommend-list-envelope-v1"
CAPTURED_AT = "2026-07-13T12:00:00+00:00"
BASELINE = PhaseCBaselineReference(
    artifact_hashes=("a" * 64, "b" * 64),
    run_ids=(
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ),
    snapshot_hash="c" * 64,
    inventory_hash="d" * 64,
)
NO_WRITE = PhaseCNoWriteEvidence(
    start_snapshot_hash=BASELINE.snapshot_hash,
    end_snapshot_hash=BASELINE.snapshot_hash,
    start_product_data_hash="e" * 64,
    end_product_data_hash="e" * 64,
    start_inventory_hash=BASELINE.inventory_hash,
    end_inventory_hash=BASELINE.inventory_hash,
    stage_calls=2,
    would_stage_rows=7,
)
PHASE_B_PARENT = PhaseCArtifactReference(
    experiment="cursor-pagination-comparison-v2",
    run_id="33333333-3333-3333-3333-333333333333",
    manifest_hash="f" * 64,
    payload_hash="0" * 64,
    accepted=False,
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


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _condition(
    *,
    partition_id: str,
    endpoint_contract_id: str,
    job_ids: tuple[str, ...],
    complete: bool = True,
    contract_verified: bool = True,
    terminal_confirmed: bool = True,
    empty_confirmation: bool = True,
) -> PhaseCConditionEvidence:
    contract = offertoday_endpoint_contract(endpoint_contract_id)
    pages = (
        PhaseCPageEvidence(
            page=1,
            attempt=1,
            classification="success",
            stop_reason=None,
            logical_request_id=_sha(f"logical:{partition_id}:{endpoint_contract_id}:1"),
            physical_attempt_id=_sha(f"physical:{partition_id}:{endpoint_contract_id}:1"),
            result_job_ids=job_ids,
            supplemental_job_ids=(),
            terminal_signal=False,
            awaiting_empty_confirmation=True,
            contract_error=None,
            reported_total=999_999,
        ),
        PhaseCPageEvidence(
            page=2,
            attempt=1,
            classification="success",
            stop_reason="natural_exhaustion" if complete else "page_cap",
            logical_request_id=_sha(f"logical:{partition_id}:{endpoint_contract_id}:2"),
            physical_attempt_id=_sha(f"physical:{partition_id}:{endpoint_contract_id}:2"),
            result_job_ids=(),
            supplemental_job_ids=(),
            terminal_signal=empty_confirmation,
            awaiting_empty_confirmation=False,
            contract_error=None,
            reported_total=999_999,
        ),
    )
    return PhaseCConditionEvidence(
        partition_id=partition_id,
        endpoint_contract_id=endpoint_contract_id,
        endpoint_contract_hash=contract.contract_hash,
        condition_id=_sha(f"condition:{partition_id}:{endpoint_contract_id}"),
        stop_reason="natural_exhaustion" if complete else "page_cap",
        is_complete=complete,
        contract_verified=contract_verified,
        terminal_confirmed=terminal_confirmed,
        empty_confirmation=empty_confirmation,
        gap_count=0,
        identity_conflict_count=0,
        identity_issue_count=0,
        conservation_difference=0,
        pages=pages,
    )


def _endpoint_payload() -> dict:
    plan = build_endpoint_probe_plan()
    partition_id = top_level_partition(plan.category_code).partition_id
    execution = PhaseCProbeExecution(
        experiment=ENDPOINT_PROBE_EXPERIMENT,
        plan=plan,
        conditions=(
            _condition(
                partition_id=partition_id,
                endpoint_contract_id=SEARCH_CONTRACT_ID,
                job_ids=("1", "2"),
            ),
            _condition(
                partition_id=partition_id,
                endpoint_contract_id=BROWSE_CONTRACT_ID,
                job_ids=("2", "3"),
                complete=False,
                contract_verified=False,
                terminal_confirmed=False,
                empty_confirmation=False,
            ),
        ),
    )
    return build_phase_c_probe_artifact_payload(
        execution=execution,
        parent=PHASE_B_PARENT,
        baseline=BASELINE,
        no_write=NO_WRITE,
    )


def _partition_payload(
    partition_index: int,
    *,
    job_ids: tuple[str, ...],
    max_pages_per_condition: int = 3,
) -> dict:
    partition_id = OFFERTODAY_PARTITION_CATALOG[partition_index].partition_id
    plan = build_partition_probe_plan(
        endpoint_contract_id=SEARCH_CONTRACT_ID,
        partition_ids=(partition_id,),
        max_pages_per_condition=max_pages_per_condition,
    )
    execution = PhaseCProbeExecution(
        experiment=PARTITION_PROBE_EXPERIMENT,
        plan=plan,
        conditions=(
            _condition(
                partition_id=partition_id,
                endpoint_contract_id=SEARCH_CONTRACT_ID,
                job_ids=job_ids,
            ),
        ),
    )
    endpoint_parent = PhaseCArtifactReference(
        experiment=ENDPOINT_PROBE_EXPERIMENT,
        run_id="44444444-4444-4444-4444-444444444444",
        manifest_hash="1" * 64,
        payload_hash="2" * 64,
        accepted=False,
    )
    return build_phase_c_probe_artifact_payload(
        execution=execution,
        parent=endpoint_parent,
        baseline=BASELINE,
        no_write=NO_WRITE,
    )


def _comparison_payload(*, reverse_parents: bool = False) -> dict:
    first_payload = _partition_payload(0, job_ids=("1", "2"))
    second_payload = _partition_payload(1, job_ids=("2", "3"))
    first_reference = PhaseCArtifactReference(
        experiment=PARTITION_PROBE_EXPERIMENT,
        run_id="55555555-5555-5555-5555-555555555555",
        manifest_hash="3" * 64,
        payload_hash=canonical_phase_c_hash(first_payload),
        accepted=True,
    )
    second_reference = PhaseCArtifactReference(
        experiment=PARTITION_PROBE_EXPERIMENT,
        run_id="66666666-6666-6666-6666-666666666666",
        manifest_hash="4" * 64,
        payload_hash=canonical_phase_c_hash(second_payload),
        accepted=True,
    )
    first = build_partition_probe_parent_projection(
        reference=first_reference,
        probe_payload=first_payload,
    )
    second = build_partition_probe_parent_projection(
        reference=second_reference,
        probe_payload=second_payload,
    )
    parents = (second, first) if reverse_parents else (first, second)
    return build_partition_comparison_artifact_payload(parents)


def _export_payload(
    root: Path,
    payload: dict,
    *,
    run_id: str | None = None,
    metadata: dict | None = None,
    events: list[dict] | None = None,
) -> Path:
    run_id = run_id or str(uuid4())
    experiment = payload["experiment"]
    if experiment == ENDPOINT_PROBE_EXPERIMENT:
        file_name = "endpoint-probe.json"
        metadata = metadata or phase_c_probe_metadata(
            payload,
            run_id=run_id,
            planner_version="fixture",
        )
    elif experiment == PARTITION_PROBE_EXPERIMENT:
        file_name = "partition-probe.json"
        metadata = metadata or phase_c_probe_metadata(
            payload,
            run_id=run_id,
            planner_version="fixture",
        )
    else:
        file_name = "partition-comparison.json"
        metadata = metadata or phase_c_comparison_metadata(
            payload,
            run_id=run_id,
            planner_version="fixture",
        )
    events = events or phase_c_artifact_events(payload, created_at=CAPTURED_AT)
    return export_research_artifact(
        root=root,
        run_id=run_id,
        metadata=metadata,
        events=events,
        provenance=_provenance(),
        json_files={file_name: payload},
    )


@pytest.mark.parametrize(
    "payload_factory",
    (_endpoint_payload, lambda: _partition_payload(0, job_ids=("1",)), _comparison_payload),
)
def test_phase_c_artifacts_pass_generic_and_exact_strict_replay(
    tmp_path: Path,
    payload_factory,
) -> None:
    artifact = _export_payload(tmp_path, payload_factory())

    generic = verify_research_artifact(artifact)
    direct = verify_phase_c_artifact(artifact)
    routed = verify_live_research_run(artifact)

    assert generic.valid is True
    assert direct.valid is True
    assert routed.valid is True
    assert routed.experiment == payload_factory()["experiment"]


def test_valid_rejected_endpoint_probe_remains_strict_valid(tmp_path: Path) -> None:
    payload = _endpoint_payload()
    assert payload["execution"]["accepted"] is False

    artifact = _export_payload(tmp_path, payload)

    assert verify_live_research_run(artifact).valid is True


def test_comparison_normalizes_interleaved_parent_order_to_catalog_order(
    tmp_path: Path,
) -> None:
    payload = _comparison_payload(reverse_parents=True)

    assert [
        item["partition_id"] for item in payload["comparison"]["inputs"]
    ] == [
        OFFERTODAY_PARTITION_CATALOG[0].partition_id,
        OFFERTODAY_PARTITION_CATALOG[1].partition_id,
    ]
    assert verify_live_research_run(_export_payload(tmp_path, payload)).valid is True


def test_unknown_next_phase_c_version_fails_closed(tmp_path: Path) -> None:
    artifact = export_research_artifact(
        root=tmp_path,
        run_id=str(uuid4()),
        metadata={"experiment": "partition-probe-v2"},
        events=[],
        provenance=_provenance(),
    )

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "unsupported_live_experiment" in result.issues


def test_rehashed_semantic_tamper_fails_strict_replay(tmp_path: Path) -> None:
    payload = _comparison_payload()
    run_id = str(uuid4())
    metadata = phase_c_comparison_metadata(
        payload,
        run_id=run_id,
        planner_version="fixture",
    )
    events = phase_c_artifact_events(payload, created_at=CAPTURED_AT)
    tampered = deepcopy(payload)
    tampered["comparison"]["decision"]["accepted"] = False

    artifact = _export_payload(
        tmp_path,
        tampered,
        run_id=run_id,
        metadata=metadata,
        events=events,
    )

    assert verify_research_artifact(artifact).valid is True
    assert verify_live_research_run(artifact).valid is False


@pytest.mark.parametrize("mutation", ("missing", "extra"))
def test_missing_or_extra_phase_c_payload_fields_fail_closed_after_reexport(
    tmp_path: Path,
    mutation: str,
) -> None:
    payload = _endpoint_payload()
    run_id = str(uuid4())
    metadata = phase_c_probe_metadata(
        payload,
        run_id=run_id,
        planner_version="fixture",
    )
    events = phase_c_artifact_events(payload, created_at=CAPTURED_AT)
    tampered = deepcopy(payload)
    if mutation == "missing":
        tampered.pop("candidate_frozen")
    else:
        tampered["unexpected"] = False

    artifact = _export_payload(
        tmp_path,
        tampered,
        run_id=run_id,
        metadata=metadata,
        events=events,
    )

    assert verify_research_artifact(artifact).valid is True
    assert verify_phase_c_artifact(artifact).valid is False


def test_event_or_no_write_drift_fails_after_reexport(tmp_path: Path) -> None:
    payload = _endpoint_payload()
    run_id = str(uuid4())
    metadata = phase_c_probe_metadata(
        payload,
        run_id=run_id,
        planner_version="fixture",
    )
    events = phase_c_artifact_events(payload, created_at=CAPTURED_AT)
    events[-1]["payload"]["product_writes"] = 1

    artifact = _export_payload(
        tmp_path,
        payload,
        run_id=run_id,
        metadata=metadata,
        events=events,
    )

    assert verify_research_artifact(artifact).valid is True
    assert verify_phase_c_artifact(artifact).valid is False


@pytest.mark.parametrize(
    ("forbidden_key", "forbidden_value"),
    (
        ("cursor", "raw-cursor-value"),
        ("sessionId", "raw-session-value"),
        ("profile_path", "C:/secret/browser-profile"),
        ("cdp_endpoint", "http://127.0.0.1:9222"),
    ),
)
def test_raw_session_cursor_and_credential_fields_are_rejected(
    tmp_path: Path,
    forbidden_key: str,
    forbidden_value: str,
) -> None:
    payload = _endpoint_payload()
    run_id = str(uuid4())
    metadata = phase_c_probe_metadata(
        payload,
        run_id=run_id,
        planner_version="fixture",
    )
    events = phase_c_artifact_events(payload, created_at=CAPTURED_AT)
    events[1]["payload"][forbidden_key] = forbidden_value

    artifact = _export_payload(
        tmp_path,
        payload,
        run_id=run_id,
        metadata=metadata,
        events=events,
    )

    assert verify_research_artifact(artifact).valid is True
    assert verify_phase_c_artifact(artifact).valid is False


@pytest.mark.parametrize(
    ("secret_key", "secret_value"),
    (
        ("cookie", "raw-cookie-value"),
        ("csrf-token", "raw-csrf-value"),
        ("authorization", "Bearer abcdefghijklmnop"),
    ),
)
def test_generic_export_redacts_known_credential_fields_before_replay(
    tmp_path: Path,
    secret_key: str,
    secret_value: str,
) -> None:
    payload = _endpoint_payload()
    events = phase_c_artifact_events(payload, created_at=CAPTURED_AT)
    events[1]["payload"][secret_key] = secret_value

    artifact = _export_payload(tmp_path, payload, events=events)
    observation_text = (artifact / "observations.jsonl").read_text(encoding="utf-8")

    assert secret_value not in observation_text
    assert verify_phase_c_artifact(artifact).valid is True


def test_comparison_rejects_parent_reuse_and_policy_mismatch() -> None:
    first_payload = _partition_payload(0, job_ids=("1",))
    first_reference = PhaseCArtifactReference(
        experiment=PARTITION_PROBE_EXPERIMENT,
        run_id="77777777-7777-7777-7777-777777777777",
        manifest_hash="5" * 64,
        payload_hash=canonical_phase_c_hash(first_payload),
        accepted=True,
    )
    first = build_partition_probe_parent_projection(
        reference=first_reference,
        probe_payload=first_payload,
    )

    with pytest.raises(ValueError, match="run IDs must be distinct"):
        build_partition_comparison_artifact_payload((first, first))

    second_payload = _partition_payload(
        1,
        job_ids=("2",),
        max_pages_per_condition=4,
    )
    second = build_partition_probe_parent_projection(
        reference=PhaseCArtifactReference(
            experiment=PARTITION_PROBE_EXPERIMENT,
            run_id="88888888-8888-8888-8888-888888888888",
            manifest_hash="6" * 64,
            payload_hash=canonical_phase_c_hash(second_payload),
            accepted=True,
        ),
        probe_payload=second_payload,
    )
    with pytest.raises(ValueError, match="policy_hash mismatch"):
        build_partition_comparison_artifact_payload((first, second))
