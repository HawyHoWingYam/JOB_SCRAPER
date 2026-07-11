from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.sources.offertoday.research.artifacts import (
    ResearchProvenance,
    export_research_artifact,
)
from app.sources.offertoday.research.stage_gate import (
    load_baseline_artifact,
    require_matching_baselines,
    verify_live_research_run,
)


SNAPSHOT_HASH = "a" * 64
INVENTORY_HASH = "b" * 64
RUN_ID_1 = "11111111-1111-1111-1111-111111111111"
RUN_ID_2 = "22222222-2222-2222-2222-222222222222"
BASELINE_COUNTS = {
    "staged_rows": 100,
    "distinct_staged_ids": 80,
    "published_jobs": 40,
    "distinct_staged_unpublished_ids": 40,
    "pending_rows": 25,
    "duplicate_staging_rows": 20,
}


def _provenance() -> ResearchProvenance:
    return ResearchProvenance(
        commit_sha="fixture-sha",
        working_tree_patch="",
        source_hashes={},
        compose_file_hashes={},
        captured_at="2026-07-11T00:00:00+00:00",
        runtime_context={"session_mode": "offline-fixture"},
        untracked_file_hashes={},
        excluded_tracked_file_hashes={},
        excluded_untracked_file_hashes={},
    )


def _baseline_event(
    *,
    snapshot_hash: str = SNAPSHOT_HASH,
    inventory_hash: str = INVENTORY_HASH,
    count_changes: dict[str, int] | None = None,
) -> dict:
    snapshot = {**BASELINE_COUNTS, **(count_changes or {})}
    snapshot["data_hash"] = snapshot_hash
    return {
        "sequence_no": 1,
        "event_type": "research.baseline",
        "payload": {
            "snapshot": snapshot,
            "run_start_inventory": {"data_hash": inventory_hash},
        },
    }


def _export(
    root: Path,
    *,
    run_id: str,
    events: list[dict] | None = None,
    snapshot_hash: str = SNAPSHOT_HASH,
    inventory_hash: str = INVENTORY_HASH,
    count_changes: dict[str, int] | None = None,
    metadata: dict | None = None,
) -> Path:
    if events is None:
        events = [
            _baseline_event(
                snapshot_hash=snapshot_hash,
                inventory_hash=inventory_hash,
                count_changes=count_changes,
            )
        ]
    return export_research_artifact(
        root=root,
        run_id=run_id,
        metadata=(
            {"experiment": "foundation-baseline", "data_hash": snapshot_hash}
            if metadata is None
            else metadata
        ),
        events=events,
        provenance=_provenance(),
    )


def test_matching_baselines_require_distinct_runs_with_identical_evidence(
    tmp_path,
) -> None:
    first_dir = _export(tmp_path, run_id=RUN_ID_1)
    second_dir = _export(tmp_path, run_id=RUN_ID_2)

    gate = require_matching_baselines(first_dir, second_dir)

    assert gate.first.run_id == RUN_ID_1
    assert gate.second.run_id == RUN_ID_2
    assert gate.first.snapshot_hash == gate.second.snapshot_hash == SNAPSHOT_HASH
    assert gate.first.inventory_hash == gate.second.inventory_hash == INVENTORY_HASH
    assert gate.first.counts == gate.second.counts == tuple(BASELINE_COUNTS.items())
    assert gate.parent_artifact_hash == hashlib.sha256(
        (second_dir / "manifest.json").read_bytes()
    ).hexdigest()


def test_load_baseline_artifact_rejects_tampered_artifact(tmp_path) -> None:
    artifact_dir = _export(tmp_path, run_id=RUN_ID_1)
    with (artifact_dir / "observations.jsonl").open("ab") as handle:
        handle.write(b"{}\n")

    with pytest.raises(ValueError, match="invalid baseline artifact"):
        load_baseline_artifact(artifact_dir)


def test_matching_baselines_reject_same_run_twice(tmp_path) -> None:
    artifact_dir = _export(tmp_path, run_id=RUN_ID_1)

    with pytest.raises(ValueError, match="two distinct run IDs"):
        require_matching_baselines(artifact_dir, artifact_dir)


@pytest.mark.parametrize(
    ("second_options", "message"),
    [
        ({"count_changes": {"staged_rows": 101}}, "count evidence"),
        ({"snapshot_hash": "c" * 64}, "snapshot hashes"),
        ({"inventory_hash": "d" * 64}, "inventory hashes"),
    ],
)
def test_matching_baselines_reject_drift(
    tmp_path,
    second_options: dict,
    message: str,
) -> None:
    first_dir = _export(tmp_path, run_id=RUN_ID_1)
    second_dir = _export(tmp_path, run_id=RUN_ID_2, **second_options)

    with pytest.raises(ValueError, match=message):
        require_matching_baselines(first_dir, second_dir)


def test_load_baseline_artifact_requires_one_baseline_event(tmp_path) -> None:
    artifact_dir = _export(tmp_path, run_id=RUN_ID_1, events=[])

    with pytest.raises(ValueError, match="exactly one research.baseline"):
        load_baseline_artifact(artifact_dir)


def test_load_baseline_artifact_rejects_multiple_baseline_events(tmp_path) -> None:
    artifact_dir = _export(
        tmp_path,
        run_id=RUN_ID_1,
        events=[_baseline_event(), _baseline_event()],
    )

    with pytest.raises(ValueError, match="exactly one research.baseline"):
        load_baseline_artifact(artifact_dir)


@pytest.mark.parametrize(
    "metadata",
    [
        {"experiment": "runtime-smoke", "data_hash": SNAPSHOT_HASH},
        {"experiment": "foundation-baseline", "data_hash": "f" * 64},
        {},
    ],
)
def test_load_baseline_artifact_binds_foundation_metadata_to_snapshot(
    tmp_path,
    metadata: dict,
) -> None:
    artifact_dir = _export(
        tmp_path,
        run_id=RUN_ID_1,
        metadata=metadata,
    )

    with pytest.raises(ValueError, match="foundation-baseline metadata"):
        load_baseline_artifact(artifact_dir)


def _live_events(
    *,
    listing_attempts: int = 1,
    detail_attempts: int = 20,
    status: str = "completed",
    smoke_passed: bool = True,
    failure_reason: str | None = None,
) -> list[dict]:
    targets = [
        {
            "position": position,
            "job_id": f"j{position}",
            "encrypted_job_id": f"e{position}",
            "job_id_hash": hashlib.sha256(f"j{position}".encode()).hexdigest(),
            "encrypted_job_id_hash": hashlib.sha256(
                f"e{position}".encode()
            ).hexdigest(),
        }
        for position in range(1, 21)
    ]
    events: list[dict] = [
        {
            "sequence_no": 1,
            "event_type": "research.run_started",
            "payload": {"experiment": "runtime-smoke"},
        }
    ]
    for _ in range(listing_attempts):
        events.append(
            {
                "sequence_no": len(events) + 1,
                "event_type": "research.page_attempt",
                "payload": {
                    "search_family": "runtime_smoke",
                    "category_id": 118000,
                    "keyword": "",
                    "endpoint": "search",
                    "rcd_type": 7,
                    "page": 1,
                    "attempt": 1,
                    "classification": "success",
                    "session_mode": "fresh-headless",
                },
            }
        )
    events.append(
        {
            "sequence_no": len(events) + 1,
            "event_type": "research.detail_cohort_frozen",
            "payload": {"count": 20, "targets": targets},
        }
    )
    for position in range(1, detail_attempts + 1):
        events.append(
            {
                "sequence_no": len(events) + 1,
                "event_type": "research.detail_attempt",
                "payload": {
                    "target": targets[position - 1],
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
        )
    if not smoke_passed:
        failure_reason = failure_reason or "unattempted_without_batch_stop"
        events.append(
            {
                "sequence_no": len(events) + 1,
                "event_type": "research.run_stopped",
                "payload": {"reason": failure_reason},
            }
        )
    events.append(
        {
            "sequence_no": len(events) + 1,
            "event_type": "research.run_summary",
            "payload": {
                "smoke_passed": smoke_passed,
                "listing_complete": False,
                "expected_truncation": True,
                "listing_attempt_count": listing_attempts,
                "attempted_count": detail_attempts,
                "frozen_count": 20,
                "success_count": detail_attempts,
                "terminal_count": 0,
                "unattempted_count": 20 - detail_attempts,
                "stop_reason": None if smoke_passed else failure_reason,
                "product_data_unchanged": True,
                "run_start_snapshot_hash": "d" * 64,
                "run_end_snapshot_hash": "d" * 64,
                "run_start_product_data_hash": "f" * 64,
                "run_end_product_data_hash": "f" * 64,
                "run_start_inventory_hash": "e" * 64,
                "run_end_inventory_hash": "e" * 64,
                "status": status,
            },
        }
    )
    return events


def _export_live(
    root: Path,
    *,
    run_id: str = RUN_ID_1,
    events: list[dict] | None = None,
    status: str = "completed",
    smoke_passed: bool = True,
    parent_artifact_hash: str = "c" * 64,
    request_budget: dict[str, int] | None = None,
) -> Path:
    return export_research_artifact(
        root=root,
        run_id=run_id,
        metadata={
            "experiment": "runtime-smoke",
            "crawl_job_id": run_id,
            "crawl_job_status": status,
            "parent_artifact_hash": parent_artifact_hash,
            "request_budget": request_budget or {"listing": 1, "detail": 20},
            "smoke_passed": smoke_passed,
        },
        events=(
            _live_events(status=status, smoke_passed=smoke_passed)
            if events is None
            else events
        ),
        provenance=_provenance(),
    )


def test_verify_live_run_accepts_consistent_completed_smoke(tmp_path) -> None:
    artifact = _export_live(tmp_path)

    result = verify_live_research_run(artifact)

    assert result.valid is True
    assert result.issues == ()
    assert result.experiment == "runtime-smoke"
    assert result.run_id == RUN_ID_1
    assert result.to_payload() == {
        "valid": True,
        "issues": [],
        "experiment": "runtime-smoke",
        "run_id": RUN_ID_1,
    }


def test_verify_live_run_accepts_consistent_failed_partial_smoke(tmp_path) -> None:
    events = _live_events(
        listing_attempts=1,
        detail_attempts=1,
        status="failed",
        smoke_passed=False,
    )
    artifact = _export_live(
        tmp_path,
        events=events,
        status="failed",
        smoke_passed=False,
    )

    result = verify_live_research_run(artifact)

    assert result.valid is True
    assert result.issues == ()


@pytest.mark.parametrize(
    ("mutate_events", "metadata_changes", "expected_issue"),
    [
        (
            lambda events: [*events, {"sequence_no": 99, "event_type": "research.extra", "payload": {}}],
            {},
            "event_after_terminal_summary",
        ),
        (
            lambda events: [*events, events[-1]],
            {},
            "terminal_summary_count:2",
        ),
        (
            lambda events: _live_events(listing_attempts=2),
            {},
            "listing_request_budget_exceeded:2>1",
        ),
        (
            lambda events: events,
            {"status": "failed", "smoke_passed": True},
            "completed_smoke_status_mismatch",
        ),
        (
            lambda events: events,
            {"parent_artifact_hash": "not-a-hash"},
            "invalid_parent_artifact_hash",
        ),
    ],
)
def test_verify_live_run_rejects_inconsistent_evidence(
    tmp_path,
    mutate_events,
    metadata_changes: dict,
    expected_issue: str,
) -> None:
    events = mutate_events(_live_events())
    artifact = _export_live(
        tmp_path,
        events=events,
        status=metadata_changes.get("status", "completed"),
        smoke_passed=metadata_changes.get("smoke_passed", True),
        parent_artifact_hash=metadata_changes.get(
            "parent_artifact_hash", "c" * 64
        ),
    )

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert expected_issue in result.issues


@pytest.mark.parametrize(
    "request_budget",
    [
        {"listing": 2, "detail": 20},
        {"listing": 1, "detail": 19},
        {"listing": 1, "detail": 20, "extra": 0},
    ],
)
def test_verify_live_run_requires_exact_locked_smoke_budget(
    tmp_path,
    request_budget: dict[str, int],
) -> None:
    artifact = _export_live(tmp_path, request_budget=request_budget)

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "invalid_runtime_smoke_request_budget" in result.issues


def test_verify_live_run_rejects_empty_terminal_summary(tmp_path) -> None:
    events = _live_events()
    events[-1]["payload"] = {}
    artifact = _export_live(tmp_path, events=events)

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "invalid_terminal_summary_payload" in result.issues


def test_verify_live_run_rejects_detail_target_order_mismatch(tmp_path) -> None:
    events = _live_events()
    first_detail = next(
        event
        for event in events
        if event["event_type"] == "research.detail_attempt"
    )
    first_detail["payload"]["target"] = dict(
        events[2]["payload"]["targets"][1]
    )
    artifact = _export_live(tmp_path, events=events)

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "detail_attempt_target_order_mismatch" in result.issues


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("search_family", "default_it"),
        ("category_id", 112000),
        ("keyword", "developer"),
        ("endpoint", "browse"),
        ("rcd_type", None),
        ("session_mode", "reuse-open-browser"),
    ],
)
def test_verify_live_run_binds_exact_runtime_smoke_page_controls(
    tmp_path,
    field_name: str,
    invalid_value,
) -> None:
    events = _live_events()
    page_event = next(
        event
        for event in events
        if event["event_type"] == "research.page_attempt"
    )
    page_event["payload"][field_name] = invalid_value
    artifact = _export_live(tmp_path, events=events)

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "invalid_runtime_smoke_page_control" in result.issues


def test_verify_live_run_requires_page_attempt_before_cohort_freeze(tmp_path) -> None:
    events = _live_events()
    events[1], events[2] = events[2], events[1]
    for sequence_no, event in enumerate(events, start=1):
        event["sequence_no"] = sequence_no
    artifact = _export_live(tmp_path, events=events)

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "page_attempt_after_cohort_freeze" in result.issues


def test_verify_live_run_accepts_2520_then_continued_cohort(tmp_path) -> None:
    events = _live_events()
    seventh = [
        event
        for event in events
        if event["event_type"] == "research.detail_attempt"
    ][6]
    seventh["payload"].update(
        {
            "classification": "terminal_unavailable",
            "api_code": 2520,
            "identity_valid": False,
            "parsed": False,
            "has_title": False,
            "has_company": False,
            "has_description": False,
            "stop_batch": False,
        }
    )
    events[-1]["payload"].update({"success_count": 19, "terminal_count": 1})
    artifact = _export_live(tmp_path, events=events)

    result = verify_live_research_run(artifact)

    assert result.valid is True
    assert result.issues == ()


def test_verify_live_run_rejects_terminal_unavailable_without_code_2520(
    tmp_path,
) -> None:
    events = _live_events()
    detail = next(
        event
        for event in events
        if event["event_type"] == "research.detail_attempt"
    )
    detail["payload"].update(
        {"classification": "terminal_unavailable", "api_code": 0}
    )
    events[-1]["payload"].update({"success_count": 19, "terminal_count": 1})
    artifact = _export_live(tmp_path, events=events)

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "terminal_unavailable_code_mismatch" in result.issues


def test_verify_live_run_rejects_attempt_after_batch_stop(tmp_path) -> None:
    events = _live_events(status="failed", smoke_passed=False)
    first_detail = next(
        event
        for event in events
        if event["event_type"] == "research.detail_attempt"
    )
    first_detail["payload"].update(
        {
            "classification": "auth_expired",
            "api_code": 1002,
            "identity_valid": False,
            "parsed": False,
            "has_title": False,
            "has_company": False,
            "has_description": False,
            "stop_batch": True,
        }
    )
    events[-1]["payload"].update(
        {
            "success_count": 19,
            "terminal_count": 0,
            "unattempted_count": 0,
            "stop_reason": "auth_expired",
        }
    )
    artifact = _export_live(
        tmp_path,
        events=events,
        status="failed",
        smoke_passed=False,
    )

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "detail_attempt_after_batch_stop" in result.issues


def test_verify_live_run_rejects_summary_counter_mismatch(tmp_path) -> None:
    events = _live_events()
    events[-1]["payload"]["success_count"] = 19
    artifact = _export_live(tmp_path, events=events)

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "success_count_mismatch" in result.issues


def test_verify_live_run_rejects_completed_product_content_hash_drift(
    tmp_path,
) -> None:
    events = _live_events()
    events[-1]["payload"]["run_end_product_data_hash"] = "a" * 64
    artifact = _export_live(tmp_path, events=events)

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "completed_smoke_status_mismatch" in result.issues


@pytest.mark.parametrize("classification", ["transient_transport", "invalid_payload"])
def test_verify_live_run_rejects_unrelated_detail_failure_reason(
    tmp_path,
    classification: str,
) -> None:
    events = _live_events(
        status="failed",
        smoke_passed=False,
        failure_reason="auth_expired",
    )
    first_detail = next(
        event
        for event in events
        if event["event_type"] == "research.detail_attempt"
    )
    first_detail["payload"].update(
        {
            "classification": classification,
            "api_code": None,
            "identity_valid": False,
            "parsed": False,
            "has_title": False,
            "has_company": False,
            "has_description": False,
            "stop_batch": False,
        }
    )
    events[-1]["payload"]["success_count"] = 19
    artifact = _export_live(
        tmp_path,
        events=events,
        status="failed",
        smoke_passed=False,
    )

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "detail_failure_reason_mismatch" in result.issues


def test_verify_live_run_rejects_run_stopped_summary_reason_mismatch(tmp_path) -> None:
    events = _live_events(
        detail_attempts=1,
        status="failed",
        smoke_passed=False,
    )
    events[-1]["payload"]["stop_reason"] = "invalid_payload"
    artifact = _export_live(
        tmp_path,
        events=events,
        status="failed",
        smoke_passed=False,
    )

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "run_stopped_summary_reason_mismatch" in result.issues


def test_verify_live_run_rejects_unrelated_listing_failure_reason(tmp_path) -> None:
    events = _live_events(
        detail_attempts=0,
        status="failed",
        smoke_passed=False,
        failure_reason="invalid_payload",
    )
    page_event = next(
        event
        for event in events
        if event["event_type"] == "research.page_attempt"
    )
    page_event["payload"].update(
        {
            "classification": "auth_expired",
            "api_code": 1002,
            "stop_reason": "auth_expired",
        }
    )
    cohort_event = next(
        event
        for event in events
        if event["event_type"] == "research.detail_cohort_frozen"
    )
    cohort_event["payload"] = {"count": 0, "targets": []}
    events[-1]["payload"].update({"frozen_count": 0, "unattempted_count": 0})
    artifact = _export_live(
        tmp_path,
        events=events,
        status="failed",
        smoke_passed=False,
    )

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "listing_failure_reason_mismatch" in result.issues


def test_verify_live_run_rejects_unsanitized_unexpected_failure_reason(
    tmp_path,
) -> None:
    events = _live_events(
        detail_attempts=0,
        status="failed",
        smoke_passed=False,
        failure_reason="unexpected_live_smoke_error:TypeError:sensitive",
    )
    artifact = _export_live(
        tmp_path,
        events=events,
        status="failed",
        smoke_passed=False,
    )

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "invalid_unexpected_failure_reason" in result.issues


def test_verify_live_run_rejects_request_evidence_after_run_stopped(
    tmp_path,
) -> None:
    events = _live_events(
        detail_attempts=1,
        status="failed",
        smoke_passed=False,
    )
    stopped_event = next(
        event for event in events if event["event_type"] == "research.run_stopped"
    )
    events.remove(stopped_event)
    events.insert(2, stopped_event)
    for sequence_no, event in enumerate(events, start=1):
        event["sequence_no"] = sequence_no
    artifact = _export_live(
        tmp_path,
        events=events,
        status="failed",
        smoke_passed=False,
    )

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "request_evidence_after_run_stopped" in result.issues


def test_verify_live_run_accepts_terminal_exception_after_nonhard_detail_failure(
    tmp_path,
) -> None:
    reason = "unexpected_live_smoke_error:RuntimeError"
    events = _live_events(
        status="failed",
        smoke_passed=False,
        failure_reason=reason,
    )
    first_detail = next(
        event
        for event in events
        if event["event_type"] == "research.detail_attempt"
    )
    first_detail["payload"].update(
        {
            "classification": "transient_transport",
            "api_code": None,
            "identity_valid": False,
            "parsed": False,
            "has_title": False,
            "has_company": False,
            "has_description": False,
            "stop_batch": False,
        }
    )
    events[-1]["payload"]["success_count"] = 19
    artifact = _export_live(
        tmp_path,
        events=events,
        status="failed",
        smoke_passed=False,
    )

    result = verify_live_research_run(artifact)

    assert result.valid is True, result.issues
