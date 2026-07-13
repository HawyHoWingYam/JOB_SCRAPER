from __future__ import annotations

import asyncio
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import scripts.offertoday_research_census as census_cli

from app.services.offertoday_research_live_service import (
    OfferTodayResearchLiveService,
)
from app.services.offertoday_research_staging_service import (
    ResearchNoopListingStagingSink,
)
from app.sources.offertoday.listing_contract import (
    OfferTodayListingTransportResult,
)
from app.sources.offertoday.research.artifacts import (
    ResearchProvenance,
    export_research_artifact,
    verify_research_artifact,
)
from app.sources.offertoday.research.pagination_bakeoff import (
    pagination_bakeoff_controls_payload,
    pagination_bakeoff_thresholds_payload,
    pagination_bakeoff_to_payload,
)
from app.sources.offertoday.research.pagination_stage_gate import (
    PAGINATION_BAKEOFF_REQUEST_BUDGET,
    recompute_pagination_bakeoff_summaries,
    verify_pagination_artifact,
)
from app.sources.offertoday.research.stage_gate import verify_live_research_run


_BASELINE_FIRST_HASH = "b" * 64
_BASELINE_PARENT_HASH = "a" * 64
_BASELINE_REPEAT_TWO_FIRST_HASH = "1" * 64
_BASELINE_REPEAT_TWO_PARENT_HASH = "2" * 64
_BASELINE_SNAPSHOT_HASH = "c" * 64
_BASELINE_PRODUCT_DATA_HASH = "d" * 64
_BASELINE_INVENTORY_HASH = "e" * 64


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        self.value += 0.01
        return self.value


class _ObservationSink:
    async def record_page_attempt(self, _observation) -> None:
        return None

    async def record_condition_outcome(self, _outcome) -> None:
        return None


class _Runtime:
    def __init__(self, factory, index: int) -> None:
        self.factory = factory
        self.index = index
        self.browser_context_hash = hashlib.sha256(
            f"pagination-stage-gate-context-{index}".encode()
        ).hexdigest()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def fetch_listing_page(self, payload, *, listing_url=None):
        if self.factory.retry_once and not self.factory.retry_emitted:
            self.factory.retry_emitted = True
            raise ConnectionError("fixture transient")
        category_id = payload["jobFunctionCodes"][0]
        page = payload["page"]
        session_id = payload.get("sessionId") or f"fixture-session-{category_id}"
        rows = (
            [
                {
                    "jobId": f"{category_id}-{payload['pageSize']}",
                    "encryptJobId": f"enc-{category_id}-{payload['pageSize']}",
                    "jobName": "Platform Engineer",
                    "companyName": "Example Technology",
                }
            ]
            if page == 1
            else []
        )
        response = {
            "code": 0,
            "data": {
                "pageSize": 10,
                "sessionId": session_id,
                "supplePage": page,
                "suppleAmount": 0,
                "suppleType": 0,
                "hasMore": False,
                "total": 100,
                "resultList": rows,
                "suppleRcdList": [],
            },
        }
        if self.factory.missing_cursor:
            for field_name in (
                "sessionId",
                "supplePage",
                "suppleAmount",
                "suppleType",
            ):
                response["data"].pop(field_name)
        return OfferTodayListingTransportResult(
            payload=response,
            browser_context_hash=self.browser_context_hash,
        )


class _RuntimeFactory:
    def __init__(self, *, retry_once: bool, missing_cursor: bool = False) -> None:
        self.retry_once = retry_once
        self.missing_cursor = missing_cursor
        self.retry_emitted = False
        self.created = 0

    def __call__(self, *, headed: bool):
        assert headed is False
        self.created += 1
        return _Runtime(self, self.created)


async def _no_sleep(_seconds: float) -> None:
    return None


def _event(sequence_no: int, event_type: str, payload: dict) -> dict:
    return {
        "sequence_no": sequence_no,
        "event_type": event_type,
        "payload": payload,
        "emitted_by": "offertoday-research",
        "created_at": (
            datetime(2026, 7, 13, 0, 0, tzinfo=UTC)
            + timedelta(seconds=sequence_no)
        ).isoformat(),
    }


def _build_events(payload: dict, *, stage_calls: int, would_stage_rows: int):
    events = [
        _event(
            1,
            "research.run_started",
            {
                "experiment": "cursor-pagination-bakeoff-v2",
                "repeat_index": payload["repeat_index"],
                "order_seed": payload["order_seed"],
                "condition_count": 15,
                "request_budget": dict(PAGINATION_BAKEOFF_REQUEST_BUDGET),
                "endpoint": "search",
                "rcd_type": None,
                "category_ids": [118000, 112000, 127000],
                "controls": pagination_bakeoff_controls_payload(),
                "thresholds": pagination_bakeoff_thresholds_payload(),
            },
        )
    ]
    sequence = 2
    for execution in payload["executions"]:
        for observation in execution["observations"]:
            events.append(_event(sequence, "research.page_attempt", observation))
            sequence += 1
        first = execution["observations"][0]
        events.append(
            _event(
                sequence,
                (
                    "research.condition_completed"
                    if execution["is_complete"]
                    else "research.condition_incomplete"
                ),
                {
                    "condition": {
                        "search_family": first["search_family"],
                        "category_id": first["category_id"],
                        "keyword": first["keyword"],
                        "endpoint": first["endpoint"],
                        "rcd_type": first["rcd_type"],
                    },
                    "pages_observed": sum(
                        item["classification"] == "success"
                        for item in execution["observations"]
                    ),
                    "stop_reason": execution["stop_reason"],
                    "is_complete": execution["is_complete"],
                },
            )
        )
        sequence += 1
    page_payloads = [
        observation
        for execution in payload["executions"]
        for observation in execution["observations"]
    ]
    logical_count = len(
        {
            item["cursor_evidence"]["logical_request_id"]
            for item in page_payloads
        }
    )
    summary = {
        "bakeoff_completed": payload["status"] == "completed",
        "failure_reason": payload["failure_reason"],
        "repeat_index": payload["repeat_index"],
        "order_seed": payload["order_seed"],
        "request_budget": dict(PAGINATION_BAKEOFF_REQUEST_BUDGET),
        "logical_listing_requests": logical_count,
        "physical_listing_attempts": len(page_payloads),
        "detail_attempts": 0,
        "product_writes": 0,
        "product_data_unchanged": True,
        "run_start_snapshot_hash": _BASELINE_SNAPSHOT_HASH,
        "run_end_snapshot_hash": _BASELINE_SNAPSHOT_HASH,
        "run_start_product_data_hash": _BASELINE_PRODUCT_DATA_HASH,
        "run_end_product_data_hash": _BASELINE_PRODUCT_DATA_HASH,
        "run_start_inventory_hash": _BASELINE_INVENTORY_HASH,
        "run_end_inventory_hash": _BASELINE_INVENTORY_HASH,
        "would_stage_rows": would_stage_rows,
        "stage_calls": stage_calls,
        "variant_summaries": payload["variant_summaries"],
        "bakeoff_payload_hash": hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest(),
    }
    events.append(_event(sequence, "research.run_summary", summary))
    return events


def _export_bakeoff(
    tmp_path: Path,
    *,
    retry_once: bool = False,
    missing_cursor: bool = False,
    repeat_index: int = 1,
    mutate_payload=None,
    mutate_events=None,
    mutate_metadata=None,
) -> Path:
    runtime_factory = _RuntimeFactory(
        retry_once=retry_once,
        missing_cursor=missing_cursor,
    )
    staging_sink = ResearchNoopListingStagingSink()
    execution = asyncio.run(
        OfferTodayResearchLiveService(
            sleep=_no_sleep,
            clock=_Clock(),
        ).run_pagination_bakeoff(
            runtime_factory=runtime_factory,
            observation_service=_ObservationSink(),
            repeat_index=repeat_index,
            order_seed=20260713,
            staging_sink=staging_sink,
        )
    )
    payload = pagination_bakeoff_to_payload(execution)
    if mutate_payload is not None:
        mutate_payload(payload)
    expected_stage_calls = sum(
        1
        for item in payload["executions"]
        if item["is_complete"]
        for observation in item["observations"]
        if observation["classification"] == "success" and observation["rows"]
    )
    expected_would_stage_rows = sum(
        len(observation["rows"])
        for item in payload["executions"]
        if item["is_complete"]
        for observation in item["observations"]
        if observation["classification"] == "success"
    )
    events = _build_events(
        payload,
        stage_calls=expected_stage_calls,
        would_stage_rows=expected_would_stage_rows,
    )
    if mutate_events is not None:
        mutate_events(events)
    run_id = str(uuid4())
    crawl_job_status = (
        "completed" if payload["status"] == "completed" else "failed"
    )
    if repeat_index == 1:
        baseline_hashes = [_BASELINE_FIRST_HASH, _BASELINE_PARENT_HASH]
        baseline_run_ids = [
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ]
    else:
        baseline_hashes = [
            _BASELINE_REPEAT_TWO_FIRST_HASH,
            _BASELINE_REPEAT_TWO_PARENT_HASH,
        ]
        baseline_run_ids = [
            "33333333-3333-3333-3333-333333333333",
            "44444444-4444-4444-4444-444444444444",
        ]
    parent_artifact_hash = baseline_hashes[-1]
    metadata = {
        "experiment": "cursor-pagination-bakeoff-v2",
        "crawl_job_id": run_id,
        "crawl_job_status": crawl_job_status,
        "parent_artifact_hash": parent_artifact_hash,
        "baseline_artifact_hash": parent_artifact_hash,
        "baseline_artifact_hashes": baseline_hashes,
        "baseline_run_ids": baseline_run_ids,
        "baseline_snapshot_hash": _BASELINE_SNAPSHOT_HASH,
        "baseline_inventory_hash": _BASELINE_INVENTORY_HASH,
        "repeat_index": repeat_index,
        "order_seed": 20260713,
        "request_budget": dict(PAGINATION_BAKEOFF_REQUEST_BUDGET),
        "product_data_unchanged": True,
        "planner_version": "fixture",
    }
    if mutate_metadata is not None:
        mutate_metadata(metadata)
    return export_research_artifact(
        root=tmp_path / "artifacts",
        run_id=run_id,
        metadata=metadata,
        events=events,
        provenance=ResearchProvenance(
            commit_sha="fixture",
            working_tree_patch="",
            source_hashes={},
            compose_file_hashes={},
            captured_at="2026-07-13T00:00:00+00:00",
            runtime_context={"command": "pagination-bakeoff"},
            untracked_file_hashes={},
            excluded_tracked_file_hashes={},
            excluded_untracked_file_hashes={},
        ),
        json_files={"bakeoff.json": payload},
    )


def _freeze_one_candidate(payload: dict) -> None:
    for execution in payload["executions"]:
        observation = next(
            item
            for item in execution["observations"]
            if item["classification"] == "success" and item["row_count"]
        )
        variant_id = execution["variant_id"]
        category_id = execution["category_id"]
        if variant_id == "stateless-current":
            job_ids = tuple(
                f"{category_id}-control-{index % 5}" for index in range(10)
            )
        elif variant_id == "ui-cursor":
            job_ids = tuple(
                f"{category_id}-candidate-{index}" for index in range(10)
            )
        else:
            job_ids = (f"{category_id}-{variant_id}-low-yield",) * 10
        identity_pairs = [
            {
                "job_id": job_id,
                "encrypted_job_id": f"enc-{job_id}",
                "encrypted_job_id_source": "encryptJobId",
            }
            for job_id in job_ids
        ]
        row_template = observation["rows"][0]
        observation["rows"] = [
            {
                **deepcopy(row_template),
                "job_id": job_id,
                "encrypted_job_id": f"enc-{job_id}",
                "observed_encrypted_job_id": f"enc-{job_id}",
            }
            for job_id in job_ids
        ]
        observation["id_pairs"] = list(
            {
                (item["job_id"], item["encrypted_job_id"]): item
                for item in identity_pairs
            }.values()
        )
        observation["row_count"] = len(job_ids)
        evidence = observation["cursor_evidence"]
        evidence["result_row_count"] = len(job_ids)
        evidence["result_job_ids"] = list(job_ids)
        evidence["result_identity_pairs"] = identity_pairs
        evidence["new_job_id_count"] = len(set(job_ids))
        evidence["duplicate_job_id_count"] = len(job_ids) - len(set(job_ids))
        evidence["zero_new_full_page"] = False
    payload["variant_summaries"] = recompute_pagination_bakeoff_summaries(
        payload
    )


def _provenance_provider(**kwargs) -> ResearchProvenance:
    return ResearchProvenance(
        commit_sha="fixture",
        working_tree_patch="",
        source_hashes={},
        compose_file_hashes={},
        captured_at=kwargs["captured_at"],
        runtime_context=kwargs["runtime_context"],
        untracked_file_hashes={},
        excluded_tracked_file_hashes={},
        excluded_untracked_file_hashes={},
    )


def test_pagination_bakeoff_artifact_accepts_full_replay_and_dispatch(tmp_path) -> None:
    artifact = _export_bakeoff(tmp_path, retry_once=True)

    result = verify_pagination_artifact(artifact)
    dispatched = verify_live_research_run(artifact)

    assert result.valid is True
    assert result.issues == ()
    assert dispatched.valid is True
    assert dispatched.experiment == "cursor-pagination-bakeoff-v2"


@pytest.mark.parametrize("field_name", ("controls", "thresholds"))
def test_pagination_bakeoff_rejects_frozen_control_or_threshold_drift(
    tmp_path,
    field_name: str,
) -> None:
    def mutate(payload):
        if field_name == "controls":
            payload["controls"]["variants"][0]["requested_page_size"] = 10
        else:
            payload["thresholds"]["minimum_jaccard"] = 0.90

    artifact = _export_bakeoff(tmp_path, mutate_payload=mutate)

    assert verify_research_artifact(artifact).valid is True
    result = verify_pagination_artifact(artifact)
    assert result.valid is False
    assert "invalid_bakeoff_payload:ValueError" in result.issues


def test_failed_pagination_bakeoff_preserves_a_strict_replayable_prefix(
    tmp_path,
    capsys,
) -> None:
    artifact = _export_bakeoff(tmp_path / "failed", missing_cursor=True)
    payload = json.loads((artifact / "bakeoff.json").read_text(encoding="utf-8"))
    manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))

    generic = verify_research_artifact(artifact)
    strict = verify_pagination_artifact(artifact)
    dispatched = verify_live_research_run(artifact)

    assert payload["status"] == "failed"
    assert payload["failure_reason"] == "hard_stop:cursor_contract_violation"
    assert 0 < len(payload["executions"]) < len(payload["order"])
    assert payload["executions"][-1]["stop_reason"] == "cursor_contract_violation"
    assert manifest["metadata"]["crawl_job_status"] == "failed"
    assert generic.valid is True
    assert strict.valid is True
    assert dispatched.valid is True

    complete = _export_bakeoff(tmp_path / "complete", repeat_index=2)
    exit_code = census_cli.main(
        [
            "compare-pagination",
            "--bakeoff-artifact",
            str(artifact),
            "--bakeoff-artifact",
            str(complete),
            "--artifact-root",
            str(tmp_path / "comparison"),
            "--run-id",
            str(uuid4()),
        ],
        provenance_provider=_provenance_provider,
    )

    assert exit_code == census_cli.EXIT_EVIDENCE_FAILURE
    assert "comparison requires completed bake-off artifacts" in (
        capsys.readouterr().err
    )


def test_pagination_bakeoff_rejects_changed_retry_cursor_input(tmp_path) -> None:
    def mutate(payload):
        observations = payload["executions"][0]["observations"]
        assert observations[0]["retry_reason"] == "transient_transport"
        observations[1]["cursor_evidence"]["cursor_input"] = {
            "cursor_hash": "a" * 64,
            "session_id_hash": "b" * 64,
            "supple_page": 0,
            "supple_amount": 0,
            "supple_type": 0,
            "effective_page_size": 10,
        }

    artifact = _export_bakeoff(
        tmp_path,
        retry_once=True,
        mutate_payload=mutate,
    )

    result = verify_pagination_artifact(artifact)

    assert result.valid is False
    assert "retry_request_changed" in result.issues


def test_pagination_bakeoff_rejects_forged_derived_counts(tmp_path) -> None:
    def mutate(payload):
        success = payload["executions"][0]["observations"][0]
        success["cursor_evidence"]["duplicate_job_id_count"] += 1

    artifact = _export_bakeoff(tmp_path, mutate_payload=mutate)

    result = verify_pagination_artifact(artifact)

    assert result.valid is False
    assert "duplicate_job_id_count_mismatch" in result.issues


@pytest.mark.parametrize(
    "field_name",
    ("response_page_size_drift_conditions", "reported_total_drift_conditions"),
)
def test_pagination_bakeoff_rejects_forged_drift_metrics(
    tmp_path,
    field_name: str,
) -> None:
    def mutate(payload):
        payload["variant_summaries"][0][field_name] += 1

    artifact = _export_bakeoff(tmp_path, mutate_payload=mutate)

    result = verify_pagination_artifact(artifact)

    assert result.valid is False
    assert "variant_summary_mismatch" in result.issues


@pytest.mark.parametrize(
    ("field_name", "value", "expected_issue"),
    (
        ("session_continuity", "continued", "session_continuity_mismatch"),
        ("effective_page_size", 11, "effective_page_size_mismatch"),
    ),
)
def test_pagination_bakeoff_rejects_forged_cursor_derivations(
    tmp_path,
    field_name: str,
    value: object,
    expected_issue: str,
) -> None:
    def mutate(payload):
        success = next(
            observation
            for execution in payload["executions"]
            for observation in execution["observations"]
            if observation["classification"] == "success"
        )
        success["cursor_evidence"][field_name] = value

    artifact = _export_bakeoff(tmp_path, mutate_payload=mutate)

    result = verify_pagination_artifact(artifact)

    assert result.valid is False
    assert expected_issue in result.issues


@pytest.mark.parametrize(
    ("field_name", "value", "expected_issue"),
    (
        ("repeat_index", True, "invalid_execution_scalars"),
        ("gap_count", -1, "invalid_gap_count"),
    ),
)
def test_pagination_bakeoff_rejects_inexact_execution_scalars(
    tmp_path,
    field_name: str,
    value: object,
    expected_issue: str,
) -> None:
    def mutate(payload):
        payload["executions"][0][field_name] = value

    artifact = _export_bakeoff(tmp_path, mutate_payload=mutate)

    result = verify_pagination_artifact(artifact)

    assert result.valid is False
    assert expected_issue in result.issues


def test_pagination_bakeoff_rejects_row_and_cohort_id_drift(tmp_path) -> None:
    def mutate(payload):
        success = next(
            observation
            for execution in payload["executions"]
            for observation in execution["observations"]
            if observation["classification"] == "success"
            and observation["rows"]
        )
        success["rows"][0]["job_id"] = "forged-job-id"

    artifact = _export_bakeoff(tmp_path, mutate_payload=mutate)

    result = verify_pagination_artifact(artifact)

    assert result.valid is False
    assert "result_job_id_evidence_mismatch" in result.issues


def test_pagination_bakeoff_rejects_missing_attempt(tmp_path) -> None:
    def mutate(payload):
        observations = payload["executions"][0]["observations"]
        assert observations[0]["retry_reason"] == "transient_transport"
        del observations[0]

    artifact = _export_bakeoff(
        tmp_path,
        retry_once=True,
        mutate_payload=mutate,
    )

    result = verify_pagination_artifact(artifact)

    assert result.valid is False
    assert "condition_did_not_start_at_page_one" in result.issues


def test_pagination_bakeoff_rejects_duplicate_event_sequence(tmp_path) -> None:
    def mutate(events):
        events[1]["sequence_no"] = events[0]["sequence_no"]

    artifact = _export_bakeoff(tmp_path, mutate_events=mutate)

    result = verify_pagination_artifact(artifact)

    assert result.valid is False
    assert "invalid_event_sequence" in result.issues


def test_pagination_bakeoff_rejects_raw_session_leak(tmp_path) -> None:
    def mutate(payload):
        payload["executions"][0]["observations"][0]["cursor_evidence"][
            "sessionId"
        ] = "raw-session-secret"

    artifact = _export_bakeoff(tmp_path, mutate_payload=mutate)

    result = verify_pagination_artifact(artifact)

    assert result.valid is False
    assert "raw_cursor_session_leak" in result.issues


def test_pagination_bakeoff_rejects_false_empty_confirmation_state(tmp_path) -> None:
    def mutate(payload):
        final = payload["executions"][0]["observations"][-1]
        final["cursor_evidence"]["awaiting_empty_confirmation"] = False

    artifact = _export_bakeoff(tmp_path, mutate_payload=mutate)

    result = verify_pagination_artifact(artifact)

    assert result.valid is False
    assert "empty_confirmation_state_mismatch" in result.issues


def test_pagination_bakeoff_rejects_mismatched_baseline_parent_evidence(
    tmp_path,
) -> None:
    def mutate(metadata):
        metadata["baseline_artifact_hashes"][-1] = "f" * 64

    artifact = _export_bakeoff(tmp_path, mutate_metadata=mutate)

    result = verify_pagination_artifact(artifact)

    assert result.valid is False
    assert "invalid_bakeoff_baseline_evidence" in result.issues


def test_pagination_bakeoff_rejects_changed_end_snapshot_hash(tmp_path) -> None:
    def mutate(events):
        summary = next(
            event["payload"]
            for event in events
            if event["event_type"] == "research.run_summary"
        )
        summary["run_end_snapshot_hash"] = "f" * 64

    artifact = _export_bakeoff(tmp_path, mutate_events=mutate)

    result = verify_pagination_artifact(artifact)

    assert result.valid is False
    assert "invalid_bakeoff_summary" in result.issues


def test_pagination_bakeoff_rejects_forged_staging_counts(tmp_path) -> None:
    def mutate(events):
        summary = next(
            event["payload"]
            for event in events
            if event["event_type"] == "research.run_summary"
        )
        summary["stage_calls"] += 1

    artifact = _export_bakeoff(tmp_path, mutate_events=mutate)

    result = verify_pagination_artifact(artifact)

    assert result.valid is False
    assert "invalid_bakeoff_summary" in result.issues


def test_generic_hash_tampering_still_fails_before_strict_replay(tmp_path) -> None:
    artifact = _export_bakeoff(tmp_path)
    bakeoff_path = artifact / "bakeoff.json"
    bakeoff_path.write_text(
        bakeoff_path.read_text(encoding="utf-8") + " ",
        encoding="utf-8",
    )

    generic = verify_research_artifact(artifact)
    strict = verify_pagination_artifact(artifact)

    assert generic.valid is False
    assert strict.valid is False
    assert "mismatched_artifact_file:bakeoff.json" in strict.issues


def test_compare_and_freeze_commands_are_offline_and_strictly_replayable(
    tmp_path,
    capsys,
) -> None:
    repeat_one = _export_bakeoff(
        tmp_path / "repeat-one",
        repeat_index=1,
        mutate_payload=_freeze_one_candidate,
    )
    repeat_two = _export_bakeoff(
        tmp_path / "repeat-two",
        repeat_index=2,
        mutate_payload=_freeze_one_candidate,
    )

    def forbidden_dependency(*_args, **_kwargs):
        raise AssertionError("offline command touched a live dependency")

    compare_exit = census_cli.main(
        [
            "compare-pagination",
            "--bakeoff-artifact",
            str(repeat_one),
            "--bakeoff-artifact",
            str(repeat_two),
            "--artifact-root",
            str(tmp_path / "comparison"),
            "--run-id",
            str(uuid4()),
        ],
        session_factory=forbidden_dependency,
        runtime_factory=forbidden_dependency,
        service_factory=forbidden_dependency,
        observation_service_factory=forbidden_dependency,
        provenance_provider=_provenance_provider,
    )
    comparison_output = json.loads(capsys.readouterr().out)
    comparison_artifact = Path(comparison_output["artifact"])

    assert compare_exit == census_cli.EXIT_OK
    assert comparison_output["selected_variant_id"] == "ui-cursor"
    assert verify_pagination_artifact(comparison_artifact).valid is True

    freeze_exit = census_cli.main(
        [
            "freeze-discovery-candidate",
            "--comparison-artifact",
            str(comparison_artifact),
            "--artifact-root",
            str(tmp_path / "candidate"),
            "--run-id",
            str(uuid4()),
        ],
        session_factory=forbidden_dependency,
        runtime_factory=forbidden_dependency,
        service_factory=forbidden_dependency,
        observation_service_factory=forbidden_dependency,
        provenance_provider=_provenance_provider,
    )
    candidate_output = json.loads(capsys.readouterr().out)
    candidate_artifact = Path(candidate_output["artifact"])

    assert freeze_exit == census_cli.EXIT_OK
    assert candidate_output["selected_variant_id"] == "ui-cursor"
    assert verify_pagination_artifact(candidate_artifact).valid is True


def test_compare_command_returns_valid_rejection_without_live_dependencies(
    tmp_path,
    capsys,
) -> None:
    repeat_one = _export_bakeoff(tmp_path / "repeat-one", repeat_index=1)
    repeat_two = _export_bakeoff(tmp_path / "repeat-two", repeat_index=2)

    def forbidden_dependency(*_args, **_kwargs):
        raise AssertionError("offline command touched a live dependency")

    exit_code = census_cli.main(
        [
            "compare-pagination",
            "--bakeoff-artifact",
            str(repeat_one),
            "--bakeoff-artifact",
            str(repeat_two),
            "--artifact-root",
            str(tmp_path / "comparison"),
            "--run-id",
            str(uuid4()),
        ],
        session_factory=forbidden_dependency,
        runtime_factory=forbidden_dependency,
        service_factory=forbidden_dependency,
        observation_service_factory=forbidden_dependency,
        provenance_provider=_provenance_provider,
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == census_cli.EXIT_INCOMPLETE
    assert output["pagination_passed"] is False
    assert verify_pagination_artifact(Path(output["artifact"])).valid is True


@pytest.mark.parametrize(
    ("mode", "expected_error"),
    (
        ("state", "baseline state does not match"),
        ("reused", "four distinct baseline artifacts"),
    ),
)
def test_compare_command_refuses_mismatched_or_reused_baseline_parents(
    tmp_path,
    capsys,
    mode: str,
    expected_error: str,
) -> None:
    repeat_one = _export_bakeoff(tmp_path / "repeat-one", repeat_index=1)

    def mutate_metadata(metadata):
        if mode == "state":
            metadata["baseline_snapshot_hash"] = "f" * 64
        else:
            metadata["parent_artifact_hash"] = _BASELINE_PARENT_HASH
            metadata["baseline_artifact_hash"] = _BASELINE_PARENT_HASH
            metadata["baseline_artifact_hashes"] = [
                _BASELINE_FIRST_HASH,
                _BASELINE_PARENT_HASH,
            ]

    def mutate_events(events):
        if mode != "state":
            return
        summary = next(
            event["payload"]
            for event in events
            if event["event_type"] == "research.run_summary"
        )
        summary["run_start_snapshot_hash"] = "f" * 64
        summary["run_end_snapshot_hash"] = "f" * 64

    repeat_two = _export_bakeoff(
        tmp_path / "repeat-two",
        repeat_index=2,
        mutate_metadata=mutate_metadata,
        mutate_events=mutate_events,
    )
    assert verify_pagination_artifact(repeat_one).valid is True
    assert verify_pagination_artifact(repeat_two).valid is True

    exit_code = census_cli.main(
        [
            "compare-pagination",
            "--bakeoff-artifact",
            str(repeat_one),
            "--bakeoff-artifact",
            str(repeat_two),
            "--artifact-root",
            str(tmp_path / "comparison"),
            "--run-id",
            str(uuid4()),
        ],
        provenance_provider=_provenance_provider,
    )

    assert exit_code == census_cli.EXIT_EVIDENCE_FAILURE
    assert expected_error in capsys.readouterr().err


def test_pagination_live_command_rejects_wrong_baseline_count_before_dependencies(
    tmp_path,
    capsys,
) -> None:
    def forbidden_dependency(*_args, **_kwargs):
        raise AssertionError("live dependency should not be reached")

    exit_code = census_cli.main(
        [
            "pagination-bakeoff",
            "--repeat-index",
            "1",
            "--order-seed",
            "20260713",
            "--baseline-artifact",
            str(tmp_path / "only-one"),
        ],
        session_factory=forbidden_dependency,
        runtime_factory=forbidden_dependency,
        service_factory=forbidden_dependency,
        observation_service_factory=forbidden_dependency,
        provenance_provider=forbidden_dependency,
    )

    assert exit_code == census_cli.EXIT_USAGE
    assert "exactly two baseline" in capsys.readouterr().err
