from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import app.sources.offertoday.research.stage_gate as stage_gate

from app.sources.offertoday.detail_identity import (
    OfferTodayDetailIdentity,
    OfferTodayEncryptedJobIdSource,
    build_offertoday_identity_authority_index,
)
from app.sources.offertoday.research.artifacts import (
    ResearchProvenance,
    export_research_artifact,
)
from app.sources.offertoday.research.stage_gate import (
    LiveRunVerification,
    load_baseline_artifact,
    require_matching_baselines,
    verify_live_research_run,
)


SNAPSHOT_HASH = "a" * 64
INVENTORY_HASH = "b" * 64
RUN_ID_1 = "11111111-1111-1111-1111-111111111111"
RUN_ID_2 = "22222222-2222-2222-2222-222222222222"
CURRENT_SMOKE_BUDGET = {"listing": 2, "detail": 20}
LEGACY_SMOKE_BUDGET = {"listing": 1, "detail": 20}
BASELINE_COUNTS = {
    "staged_rows": 100,
    "distinct_staged_ids": 80,
    "published_jobs": 40,
    "distinct_staged_unpublished_ids": 40,
    "pending_rows": 25,
    "duplicate_staging_rows": 20,
    "missing_encrypted_job_id_rows": 10,
    "observed_encrypted_job_id_rows": 70,
    "job_id_fallback_rows": 10,
    "unusable_identity_rows": 0,
}


def _identity_resolution_hash(
    job_id: str,
    encrypted_job_id: str,
    source: OfferTodayEncryptedJobIdSource,
) -> str:
    canonical = json.dumps(
        {
            "job_id": job_id,
            "encrypted_job_id": encrypted_job_id,
            "encrypted_job_id_source": source,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


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


@pytest.mark.parametrize(
    ("experiment", "verifier_name", "expected_kwargs"),
    (
        ("census-candidate", "_verify_candidate_research_run", {}),
        ("listing-calibration", "_verify_calibration_research_run", {}),
        ("category-pilot", "_verify_pilot_research_run", {}),
        ("full-census", "_verify_census_research_run", {}),
        (
            "fixed-condition-repeat",
            "_verify_census_research_run",
            {"fixed_repeat": True},
        ),
        (
            "census-stability-comparison",
            "_verify_comparison_research_run",
            {},
        ),
    ),
)
def test_legacy_experiment_names_route_to_exact_frozen_verifiers(
    tmp_path,
    monkeypatch,
    experiment: str,
    verifier_name: str,
    expected_kwargs: dict,
) -> None:
    artifact = export_research_artifact(
        root=tmp_path,
        run_id=RUN_ID_1,
        metadata={"experiment": experiment},
        events=[],
        provenance=_provenance(),
    )
    calls = []
    expected = stage_gate.LiveRunVerification(
        valid=True,
        issues=(),
        experiment=experiment,
        run_id=RUN_ID_1,
    )

    def verifier(path, **kwargs):
        calls.append((Path(path), kwargs))
        return expected

    monkeypatch.setattr(stage_gate, verifier_name, verifier)

    assert verify_live_research_run(artifact) == expected
    assert calls == [(artifact, expected_kwargs)]


def test_unknown_cursor_experiment_version_fails_closed(tmp_path) -> None:
    artifact = export_research_artifact(
        root=tmp_path,
        run_id=RUN_ID_1,
        metadata={"experiment": "cursor-pagination-bakeoff-v3"},
        events=[],
        provenance=_provenance(),
    )

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "unsupported_live_experiment" in result.issues


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
    assert (
        gate.parent_artifact_hash
        == hashlib.sha256((second_dir / "manifest.json").read_bytes()).hexdigest()
    )


def test_verify_live_run_accepts_foundation_baseline(tmp_path) -> None:
    artifact_dir = _export(tmp_path, run_id=RUN_ID_1)

    result = verify_live_research_run(artifact_dir)

    assert result == LiveRunVerification(
        valid=True,
        issues=(),
        experiment="foundation-baseline",
        run_id=RUN_ID_1,
    )


def test_verify_live_run_rejects_invalid_foundation_baseline(tmp_path) -> None:
    artifact_dir = _export(
        tmp_path,
        run_id=RUN_ID_1,
        metadata={"experiment": "foundation-baseline", "data_hash": "f" * 64},
    )

    result = verify_live_research_run(artifact_dir)

    assert result == LiveRunVerification(
        valid=False,
        issues=("invalid_foundation_baseline",),
        experiment="foundation-baseline",
        run_id=RUN_ID_1,
    )


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
        (
            {"count_changes": {"missing_encrypted_job_id_rows": 11}},
            "count evidence",
        ),
        (
            {"count_changes": {"observed_encrypted_job_id_rows": 69}},
            "count evidence",
        ),
        (
            {"count_changes": {"job_id_fallback_rows": 11}},
            "count evidence",
        ),
        (
            {"count_changes": {"unusable_identity_rows": 1}},
            "count evidence",
        ),
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
    listing_pages: tuple[int, ...] = (1,),
    detail_attempts: int = 20,
    status: str = "completed",
    smoke_passed: bool = True,
    failure_reason: str | None = None,
    identity_source: OfferTodayEncryptedJobIdSource = "encryptJobId",
    page_identity_specs: (
        tuple[tuple[tuple[str, str, OfferTodayEncryptedJobIdSource], ...], ...] | None
    ) = None,
    page_attempts: tuple[int, ...] | None = None,
    request_budget: dict[str, int] | None = None,
) -> list[dict]:
    budget = dict(CURRENT_SMOKE_BUDGET if request_budget is None else request_budget)
    if page_identity_specs is None:
        identities = tuple(
            (
                f"j{position}",
                (
                    f"j{position}"
                    if identity_source == "jobId_fallback"
                    else f"e{position}"
                ),
                identity_source,
            )
            for position in range(1, 21)
        )
        page_count = len(listing_pages)
        base_size, extra = divmod(len(identities), page_count)
        page_identity_specs_list = []
        start = 0
        for page_index in range(page_count):
            size = base_size + (1 if page_index < extra else 0)
            page_identity_specs_list.append(identities[start : start + size])
            start += size
        page_identity_specs = tuple(page_identity_specs_list)
    if len(page_identity_specs) != len(listing_pages):
        raise ValueError("page identity fixture count must match listing pages")
    if page_attempts is None:
        page_attempts = (1,) * len(listing_pages)
    if len(page_attempts) != len(listing_pages):
        raise ValueError("page attempt fixture count must match listing pages")

    committed: list[OfferTodayDetailIdentity] = []
    first_seen_job_ids: list[str] = []
    seen_job_ids: set[str] = set()
    page_payloads: list[dict] = []
    for page_index, (page, attempt, identity_specs) in enumerate(
        zip(listing_pages, page_attempts, page_identity_specs, strict=True)
    ):
        current_rows = [OfferTodayDetailIdentity(*spec) for spec in identity_specs]
        accumulated = [*committed, *current_rows]
        authority = build_offertoday_identity_authority_index(accumulated)
        current_job_order = list(dict.fromkeys(row.job_id for row in current_rows))
        page_pairs = [
            authority.authoritative_identity_by_job[job_id]
            for job_id in current_job_order
            if job_id in authority.authoritative_identity_by_job
            and job_id not in authority.conflict_reason_by_job
        ]
        committed.extend(current_rows)
        for row in current_rows:
            if row.job_id not in seen_job_ids:
                seen_job_ids.add(row.job_id)
                first_seen_job_ids.append(row.job_id)
        final_page = page_index == len(listing_pages) - 1
        final_authority_count = len(
            [
                job_id
                for job_id in first_seen_job_ids
                if job_id in authority.authoritative_identity_by_job
                and job_id not in authority.conflict_reason_by_job
            ]
        )
        page_payloads.append(
            {
                "search_family": "runtime_smoke",
                "category_id": 118000,
                "keyword": "",
                "endpoint": "search",
                "rcd_type": 7,
                "page": page,
                "attempt": attempt,
                "classification": "success",
                "api_code": 0,
                "session_mode": "fresh-headless",
                "has_more": True,
                "stop_reason": (
                    "target_cap"
                    if final_page and final_authority_count >= 20
                    else "page_cap" if final_page else None
                ),
                "row_count": len(current_rows),
                "missing_job_id_count": 0,
                "missing_encrypted_job_id_count": sum(
                    row.encrypted_job_id_source == "jobId_fallback"
                    for row in current_rows
                ),
                "job_id_fallback_count": sum(
                    row.encrypted_job_id_source == "jobId_fallback"
                    for row in current_rows
                ),
                "id_pairs": [
                    {
                        "job_id": pair.job_id,
                        "encrypted_job_id": pair.encrypted_job_id,
                        "encrypted_job_id_source": pair.encrypted_job_id_source,
                    }
                    for pair in page_pairs
                ],
                "rows": [
                    {
                        "job_id": row.job_id,
                        "encrypted_job_id": row.encrypted_job_id,
                        "encrypted_job_id_source": row.encrypted_job_id_source,
                        "observed_encrypted_job_id": (
                            None
                            if row.encrypted_job_id_source == "jobId_fallback"
                            else row.encrypted_job_id
                        ),
                    }
                    for row in current_rows
                ],
                "identity_issues": [],
                "identity_conflicts": [],
            }
        )

    final_authority = build_offertoday_identity_authority_index(committed)
    frozen_identities = [
        final_authority.authoritative_identity_by_job[job_id]
        for job_id in first_seen_job_ids
        if job_id in final_authority.authoritative_identity_by_job
        and job_id not in final_authority.conflict_reason_by_job
    ][:20]
    targets = [
        {
            "position": position,
            "job_id": identity.job_id,
            "encrypted_job_id": identity.encrypted_job_id,
            "encrypted_job_id_source": identity.encrypted_job_id_source,
            "job_id_hash": hashlib.sha256(identity.job_id.encode()).hexdigest(),
            "encrypted_job_id_hash": hashlib.sha256(
                identity.encrypted_job_id.encode()
            ).hexdigest(),
            "identity_resolution_hash": _identity_resolution_hash(
                identity.job_id,
                identity.encrypted_job_id,
                identity.encrypted_job_id_source,
            ),
        }
        for position, identity in enumerate(frozen_identities, start=1)
    ]
    events: list[dict] = [
        {
            "sequence_no": 1,
            "event_type": "research.run_started",
            "payload": {
                "experiment": "runtime-smoke",
                "request_budget": dict(budget),
            },
        }
    ]
    for page_payload in page_payloads:
        events.append(
            {
                "sequence_no": len(events) + 1,
                "event_type": "research.page_attempt",
                "payload": page_payload,
            }
        )
    events.append(
        {
            "sequence_no": len(events) + 1,
            "event_type": "research.detail_cohort_frozen",
            "payload": {"count": len(targets), "targets": targets},
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
                "listing_attempt_count": len(listing_pages),
                "attempted_count": detail_attempts,
                "frozen_count": len(targets),
                "success_count": detail_attempts,
                "terminal_count": 0,
                "unattempted_count": len(targets) - detail_attempts,
                "missing_encrypted_job_id_count": sum(
                    payload["missing_encrypted_job_id_count"]
                    for payload in page_payloads
                ),
                "job_id_fallback_count": sum(
                    payload["job_id_fallback_count"] for payload in page_payloads
                ),
                "listing_stop_reason": page_payloads[-1]["stop_reason"],
                "stop_reason": None if smoke_passed else failure_reason,
                "request_budget": dict(budget),
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
    budget = dict(CURRENT_SMOKE_BUDGET if request_budget is None else request_budget)
    return export_research_artifact(
        root=root,
        run_id=run_id,
        metadata={
            "experiment": "runtime-smoke",
            "crawl_job_id": run_id,
            "crawl_job_status": status,
            "parent_artifact_hash": parent_artifact_hash,
            "request_budget": budget,
            "smoke_passed": smoke_passed,
        },
        events=(
            _live_events(
                status=status,
                smoke_passed=smoke_passed,
                request_budget=budget,
            )
            if events is None
            else events
        ),
        provenance=_provenance(),
    )


def _natural_exhaustion_events(
    *,
    identity_count: int,
    has_more: bool | None,
) -> list[dict]:
    identities = tuple(
        (f"j{position}", f"e{position}", "encryptJobId")
        for position in range(1, identity_count + 1)
    )
    events = _live_events(
        listing_pages=(1,),
        page_identity_specs=(identities,),
        detail_attempts=0,
        status="failed",
        smoke_passed=False,
        failure_reason="listing_natural_exhaustion",
    )
    page = next(
        event["payload"]
        for event in events
        if event["event_type"] == "research.page_attempt"
    )
    page["has_more"] = has_more
    page["stop_reason"] = "natural_exhaustion"
    events[-1]["payload"].update(
        {
            "listing_stop_reason": "natural_exhaustion",
            "listing_complete": True,
            "expected_truncation": False,
        }
    )
    return events


@pytest.mark.parametrize("listing_pages", [(1,), (1, 2)])
def test_verify_live_run_accepts_current_completed_one_or_two_page_smoke(
    tmp_path,
    listing_pages: tuple[int, ...],
) -> None:
    artifact = _export_live(
        tmp_path,
        events=_live_events(listing_pages=listing_pages),
    )

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


def test_verify_live_run_rejects_page_three_over_current_listing_budget(
    tmp_path,
) -> None:
    artifact = _export_live(
        tmp_path,
        events=_live_events(listing_pages=(1, 2, 3)),
    )

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "listing_request_budget_exceeded:3>2" in result.issues


@pytest.mark.parametrize("listing_pages", [(2,), (1, 1)])
def test_verify_live_run_rejects_out_of_order_or_duplicate_page_sequence(
    tmp_path,
    listing_pages: tuple[int, ...],
) -> None:
    artifact = _export_live(
        tmp_path,
        events=_live_events(listing_pages=listing_pages),
    )

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "invalid_runtime_smoke_page_sequence" in result.issues


def test_verify_live_run_rejects_page_two_retry_attempt(tmp_path) -> None:
    artifact = _export_live(
        tmp_path,
        events=_live_events(
            listing_pages=(1, 2),
            page_attempts=(1, 2),
        ),
    )

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "invalid_runtime_smoke_listing_attempt" in result.issues


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [("stop_reason", "target_cap"), ("has_more", False)],
)
def test_verify_live_run_rejects_page_two_after_page_one_terminal_signal(
    tmp_path,
    field_name: str,
    invalid_value,
) -> None:
    events = _live_events(listing_pages=(1, 2))
    first_page = next(
        event["payload"]
        for event in events
        if event["event_type"] == "research.page_attempt"
    )
    first_page[field_name] = invalid_value
    artifact = _export_live(tmp_path, events=events)

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "invalid_runtime_smoke_page_two_entry" in result.issues


def test_cross_page_identity_authority_freezes_first_twenty_in_order(
    tmp_path,
) -> None:
    events = _live_events(listing_pages=(1, 2))
    cohort = next(
        event["payload"]
        for event in events
        if event["event_type"] == "research.detail_cohort_frozen"
    )
    artifact = _export_live(tmp_path, events=events)

    result = verify_live_research_run(artifact)

    assert [target["job_id"] for target in cohort["targets"]] == [
        f"j{position}" for position in range(1, 21)
    ]
    assert result.valid is True, result.issues


def test_cross_page_repeats_freeze_fifteen_and_attempt_no_details(
    tmp_path,
) -> None:
    first_page = tuple(
        (f"j{position}", f"e{position}", "encryptJobId") for position in range(1, 11)
    )
    second_page = (
        *first_page[:5],
        *tuple(
            (f"j{position}", f"e{position}", "encryptJobId")
            for position in range(11, 16)
        ),
    )
    events = _live_events(
        listing_pages=(1, 2),
        page_identity_specs=(first_page, second_page),
        detail_attempts=0,
        status="failed",
        smoke_passed=False,
        failure_reason="insufficient_valid_detail_targets",
    )
    artifact = _export_live(
        tmp_path,
        events=events,
        status="failed",
        smoke_passed=False,
    )

    result = verify_live_research_run(artifact)

    summary = events[-1]["payload"]
    assert summary["frozen_count"] == 15
    assert summary["attempted_count"] == 0
    assert summary["stop_reason"] == "insufficient_valid_detail_targets"
    assert result.valid is True, result.issues


@pytest.mark.parametrize(
    ("identity_count", "has_more"),
    [(10, False), (0, None)],
    ids=["rows", "empty"],
)
def test_natural_exhaustion_is_valid_failed_terminal_evidence(
    tmp_path,
    identity_count: int,
    has_more: bool | None,
) -> None:
    events = _natural_exhaustion_events(
        identity_count=identity_count,
        has_more=has_more,
    )
    artifact = _export_live(
        tmp_path,
        events=events,
        status="failed",
        smoke_passed=False,
    )

    result = verify_live_research_run(artifact)

    assert result.valid is True, result.issues


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [("listing_complete", False), ("expected_truncation", True)],
)
def test_natural_exhaustion_rejects_tampered_failed_summary(
    tmp_path,
    field_name: str,
    invalid_value: bool,
) -> None:
    events = _natural_exhaustion_events(identity_count=10, has_more=False)
    events[-1]["payload"][field_name] = invalid_value
    artifact = _export_live(
        tmp_path,
        events=events,
        status="failed",
        smoke_passed=False,
    )

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "failed_smoke_status_mismatch" in result.issues


def test_failed_target_cap_rejects_insufficient_frozen_authority(tmp_path) -> None:
    first_page = tuple(
        (f"j{position}", f"e{position}", "encryptJobId") for position in range(1, 11)
    )
    second_page = (
        *first_page[:5],
        *tuple(
            (f"j{position}", f"e{position}", "encryptJobId")
            for position in range(11, 16)
        ),
    )
    events = _live_events(
        listing_pages=(1, 2),
        page_identity_specs=(first_page, second_page),
        detail_attempts=0,
        status="failed",
        smoke_passed=False,
        failure_reason="insufficient_valid_detail_targets",
    )
    page_payloads = [
        event["payload"]
        for event in events
        if event["event_type"] == "research.page_attempt"
    ]
    page_payloads[-1]["stop_reason"] = "target_cap"
    events[-1]["payload"]["listing_stop_reason"] = "target_cap"
    artifact = _export_live(
        tmp_path,
        events=events,
        status="failed",
        smoke_passed=False,
    )

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "failed_smoke_status_mismatch" in result.issues


def test_failed_one_page_target_cap_rejects_insufficient_frozen_authority(
    tmp_path,
) -> None:
    identities = tuple(
        (f"j{position}", f"e{position}", "encryptJobId") for position in range(1, 16)
    )
    events = _live_events(
        listing_pages=(1,),
        page_identity_specs=(identities,),
        detail_attempts=0,
        status="failed",
        smoke_passed=False,
        failure_reason="insufficient_valid_detail_targets",
    )
    page = next(
        event["payload"]
        for event in events
        if event["event_type"] == "research.page_attempt"
    )
    page["stop_reason"] = "target_cap"
    events[-1]["payload"]["listing_stop_reason"] = "target_cap"
    artifact = _export_live(
        tmp_path,
        events=events,
        status="failed",
        smoke_passed=False,
    )

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "failed_smoke_status_mismatch" in result.issues


def test_detail_ready_failed_smoke_rejects_zero_detail_bypass(tmp_path) -> None:
    events = _live_events(
        detail_attempts=0,
        status="failed",
        smoke_passed=False,
        failure_reason="invalid_payload",
    )
    artifact = _export_live(
        tmp_path,
        events=events,
        status="failed",
        smoke_passed=False,
    )

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "detail_failure_reason_mismatch" in result.issues


def test_cross_page_page_cap_rejects_tampered_summary_listing_stop_reason(
    tmp_path,
) -> None:
    first_page = tuple(
        (f"j{position}", f"e{position}", "encryptJobId") for position in range(1, 11)
    )
    second_page = (
        *first_page[:5],
        *tuple(
            (f"j{position}", f"e{position}", "encryptJobId")
            for position in range(11, 16)
        ),
    )
    events = _live_events(
        listing_pages=(1, 2),
        page_identity_specs=(first_page, second_page),
        detail_attempts=0,
        status="failed",
        smoke_passed=False,
        failure_reason="insufficient_valid_detail_targets",
    )
    events[-1]["payload"]["listing_stop_reason"] = "target_cap"
    artifact = _export_live(
        tmp_path,
        events=events,
        status="failed",
        smoke_passed=False,
    )

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "failed_smoke_status_mismatch" in result.issues


def test_cross_page_page_cap_rejects_page_two_terminal_has_more_false(
    tmp_path,
) -> None:
    first_page = tuple(
        (f"j{position}", f"e{position}", "encryptJobId") for position in range(1, 11)
    )
    second_page = (
        *first_page[:5],
        *tuple(
            (f"j{position}", f"e{position}", "encryptJobId")
            for position in range(11, 16)
        ),
    )
    events = _live_events(
        listing_pages=(1, 2),
        page_identity_specs=(first_page, second_page),
        detail_attempts=0,
        status="failed",
        smoke_passed=False,
        failure_reason="insufficient_valid_detail_targets",
    )
    page_payloads = [
        event["payload"]
        for event in events
        if event["event_type"] == "research.page_attempt"
    ]
    page_payloads[1]["has_more"] = False
    artifact = _export_live(
        tmp_path,
        events=events,
        status="failed",
        smoke_passed=False,
    )

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "invalid_runtime_smoke_page_terminal_signal" in result.issues


@pytest.mark.parametrize(
    ("detail_attempts", "failure_reason"),
    [
        (0, "invalid_payload"),
        (1, "unattempted_without_batch_stop"),
    ],
)
def test_cross_page_page_cap_shortfall_requires_insufficient_zero_attempts(
    tmp_path,
    detail_attempts: int,
    failure_reason: str,
) -> None:
    first_page = tuple(
        (f"j{position}", f"e{position}", "encryptJobId") for position in range(1, 11)
    )
    second_page = (
        *first_page[:5],
        *tuple(
            (f"j{position}", f"e{position}", "encryptJobId")
            for position in range(11, 16)
        ),
    )
    events = _live_events(
        listing_pages=(1, 2),
        page_identity_specs=(first_page, second_page),
        detail_attempts=detail_attempts,
        status="failed",
        smoke_passed=False,
        failure_reason=failure_reason,
    )
    artifact = _export_live(
        tmp_path,
        events=events,
        status="failed",
        smoke_passed=False,
    )

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "failed_smoke_status_mismatch" in result.issues


def _promotion_page_specs() -> tuple[
    tuple[tuple[str, str, OfferTodayEncryptedJobIdSource], ...],
    tuple[tuple[str, str, OfferTodayEncryptedJobIdSource], ...],
]:
    first_page = (
        ("j1", "j1", "jobId_fallback"),
        *tuple(
            (f"j{position}", f"e{position}", "encryptJobId")
            for position in range(2, 11)
        ),
    )
    second_page = (
        ("j1", "enc-j1", "encryptJobId"),
        *tuple(
            (f"j{position}", f"e{position}", "encryptJobId")
            for position in range(11, 21)
        ),
    )
    return first_page, second_page


def test_promoted_cross_page_identity_keeps_original_cohort_position(
    tmp_path,
) -> None:
    events = _live_events(
        listing_pages=(1, 2),
        page_identity_specs=_promotion_page_specs(),
    )
    cohort = next(
        event["payload"]
        for event in events
        if event["event_type"] == "research.detail_cohort_frozen"
    )
    artifact = _export_live(tmp_path, events=events)

    result = verify_live_research_run(artifact)

    assert cohort["targets"][0]["job_id"] == "j1"
    assert cohort["targets"][0]["encrypted_job_id"] == "enc-j1"
    assert cohort["targets"][0]["encrypted_job_id_source"] == "encryptJobId"
    assert result.valid is True, result.issues


def test_illegal_page_two_promotion_does_not_change_committed_authority(
    tmp_path,
) -> None:
    first_page = (
        ("j1", "j1", "jobId_fallback"),
        *tuple(
            (f"j{position}", f"e{position}", "encryptJobId")
            for position in range(2, 21)
        ),
    )
    second_page = (("j1", "enc-j1", "encryptJobId"),)
    events = _live_events(
        listing_pages=(1, 2),
        page_identity_specs=(first_page, second_page),
    )
    cohort = next(
        event["payload"]
        for event in events
        if event["event_type"] == "research.detail_cohort_frozen"
    )
    assert cohort["targets"][0]["encrypted_job_id"] == "enc-j1"
    artifact = _export_live(tmp_path, events=events)

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "invalid_runtime_smoke_page_two_entry" in result.issues
    assert "detail_cohort_identity_mismatch" in result.issues


def test_no_downgrade_when_later_page_only_has_fallback_identity(
    tmp_path,
) -> None:
    first_page, second_page = _promotion_page_specs()
    first_page = (
        ("j1", "enc-j1", "encryptJobId"),
        *first_page[1:],
    )
    second_page = (
        ("j1", "j1", "jobId_fallback"),
        *second_page[1:],
    )
    events = _live_events(
        listing_pages=(1, 2),
        page_identity_specs=(first_page, second_page),
    )
    second_page_payload = [
        event["payload"]
        for event in events
        if event["event_type"] == "research.page_attempt"
    ][1]
    cohort = next(
        event["payload"]
        for event in events
        if event["event_type"] == "research.detail_cohort_frozen"
    )
    artifact = _export_live(tmp_path, events=events)

    result = verify_live_research_run(artifact)

    assert second_page_payload["id_pairs"][0] == {
        "job_id": "j1",
        "encrypted_job_id": "enc-j1",
        "encrypted_job_id_source": "encryptJobId",
    }
    assert cohort["targets"][0]["encrypted_job_id"] == "enc-j1"
    assert result.valid is True, result.issues


@pytest.mark.parametrize(
    ("tamper_kind", "expected_issue"),
    [
        ("promoted_route", "page_identity_authority_mismatch"),
        ("promoted_source", "page_identity_authority_mismatch"),
        ("promoted_order", "page_identity_authority_mismatch"),
        ("frozen_position", "detail_cohort_identity_mismatch"),
    ],
)
def test_promoted_cohort_identity_tampering_is_rejected(
    tmp_path,
    tamper_kind: str,
    expected_issue: str,
) -> None:
    events = _live_events(
        listing_pages=(1, 2),
        page_identity_specs=_promotion_page_specs(),
    )
    second_page = [
        event["payload"]
        for event in events
        if event["event_type"] == "research.page_attempt"
    ][1]
    cohort = next(
        event["payload"]
        for event in events
        if event["event_type"] == "research.detail_cohort_frozen"
    )
    if tamper_kind == "promoted_route":
        second_page["id_pairs"][0]["encrypted_job_id"] = "tampered-route"
    elif tamper_kind == "promoted_source":
        second_page["id_pairs"][0]["encrypted_job_id_source"] = "jobId_fallback"
    elif tamper_kind == "promoted_order":
        second_page["id_pairs"][0], second_page["id_pairs"][1] = (
            second_page["id_pairs"][1],
            second_page["id_pairs"][0],
        )
    elif tamper_kind == "frozen_position":
        cohort["targets"][0]["position"] = 2
    else:  # pragma: no cover - parameter contract
        raise AssertionError(tamper_kind)
    artifact = _export_live(tmp_path, events=events)

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert expected_issue in result.issues


def test_verify_live_run_accepts_consistent_completed_fallback_smoke(
    tmp_path,
) -> None:
    artifact = _export_live(
        tmp_path,
        events=_live_events(identity_source="jobId_fallback"),
    )

    result = verify_live_research_run(artifact)

    assert result.valid is True, result.issues


def test_verify_live_run_rejects_tampered_summary_missing_encrypted_id_count(
    tmp_path,
) -> None:
    events = _live_events(identity_source="jobId_fallback")
    events[-1]["payload"]["missing_encrypted_job_id_count"] = 19
    artifact = _export_live(tmp_path, events=events)

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "missing_encrypted_job_id_count_mismatch" in result.issues


@pytest.mark.parametrize(
    ("tamper_kind", "expected_issue"),
    [
        ("target_source", "detail_cohort_identity_mismatch"),
        ("target_resolution_hash", "invalid_detail_identity_resolution_hash"),
        ("page_row_source", "page_identity_authority_mismatch"),
        ("page_pair_source", "page_identity_authority_mismatch"),
        ("page_missing_count", "missing_encrypted_job_id_count_mismatch"),
        ("page_fallback_count", "job_id_fallback_count_mismatch"),
        ("summary_fallback_count", "job_id_fallback_count_mismatch"),
    ],
)
def test_verify_live_run_rejects_tampered_fallback_identity_evidence(
    tmp_path,
    tamper_kind: str,
    expected_issue: str,
) -> None:
    events = _live_events(identity_source="jobId_fallback")
    page = next(
        event["payload"]
        for event in events
        if event["event_type"] == "research.page_attempt"
    )
    cohort = next(
        event["payload"]
        for event in events
        if event["event_type"] == "research.detail_cohort_frozen"
    )
    summary = events[-1]["payload"]

    if tamper_kind == "target_source":
        target = cohort["targets"][0]
        target["encrypted_job_id_source"] = "encryptJobId"
        target["identity_resolution_hash"] = _identity_resolution_hash(
            target["job_id"],
            target["encrypted_job_id"],
            "encryptJobId",
        )
    elif tamper_kind == "target_resolution_hash":
        cohort["targets"][0]["identity_resolution_hash"] = "0" * 64
    elif tamper_kind == "page_row_source":
        page["rows"][0]["encrypted_job_id_source"] = "encryptJobId"
        page["rows"][0]["observed_encrypted_job_id"] = page["rows"][0][
            "encrypted_job_id"
        ]
    elif tamper_kind == "page_pair_source":
        page["id_pairs"][0]["encrypted_job_id_source"] = "encryptJobId"
    elif tamper_kind == "page_missing_count":
        page["missing_encrypted_job_id_count"] = 19
    elif tamper_kind == "page_fallback_count":
        page["job_id_fallback_count"] = 19
    elif tamper_kind == "summary_fallback_count":
        summary["job_id_fallback_count"] = 19
    else:  # pragma: no cover - parameter contract
        raise AssertionError(tamper_kind)

    artifact = _export_live(tmp_path, events=events)
    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert expected_issue in result.issues


def test_verify_live_run_accepts_consistent_failed_partial_smoke(tmp_path) -> None:
    events = _live_events(
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
            lambda events: [
                *events,
                {"sequence_no": 99, "event_type": "research.extra", "payload": {}},
            ],
            {},
            "event_after_terminal_summary",
        ),
        (
            lambda events: [*events, events[-1]],
            {},
            "terminal_summary_count:2",
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
        parent_artifact_hash=metadata_changes.get("parent_artifact_hash", "c" * 64),
    )

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert expected_issue in result.issues


@pytest.mark.parametrize(
    "request_budget",
    [
        {"listing": 1, "detail": 20},
        {"listing": 2, "detail": 19},
        {"listing": 2, "detail": 20, "extra": 0},
    ],
)
def test_legacy_budget_or_other_wrong_budget_cannot_complete_current_smoke(
    tmp_path,
    request_budget: dict[str, int],
) -> None:
    artifact = _export_live(
        tmp_path,
        events=_live_events(request_budget=request_budget),
        request_budget=request_budget,
    )

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "invalid_runtime_smoke_request_budget" in result.issues


@pytest.mark.parametrize(
    "tampered_source",
    ["manifest", "run_start", "summary"],
)
def test_request_budget_agreement_rejects_independent_tampering(
    tmp_path,
    tampered_source: str,
) -> None:
    events = _live_events(
        detail_attempts=1,
        status="failed",
        smoke_passed=False,
        request_budget=LEGACY_SMOKE_BUDGET,
    )
    metadata_budget = dict(LEGACY_SMOKE_BUDGET)
    if tampered_source == "manifest":
        metadata_budget = dict(CURRENT_SMOKE_BUDGET)
    elif tampered_source == "run_start":
        events[0]["payload"]["request_budget"] = dict(CURRENT_SMOKE_BUDGET)
    elif tampered_source == "summary":
        events[-1]["payload"]["request_budget"] = dict(CURRENT_SMOKE_BUDGET)
    else:  # pragma: no cover - parameter contract
        raise AssertionError(tampered_source)
    artifact = _export_live(
        tmp_path,
        events=events,
        status="failed",
        smoke_passed=False,
        request_budget=metadata_budget,
    )

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
        event for event in events if event["event_type"] == "research.detail_attempt"
    )
    first_detail["payload"]["target"] = dict(events[2]["payload"]["targets"][1])
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
        event for event in events if event["event_type"] == "research.page_attempt"
    )
    page_event["payload"][field_name] = invalid_value
    artifact = _export_live(tmp_path, events=events)

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "invalid_runtime_smoke_page_control" in result.issues


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("has_more", "yes"),
        ("has_more", 0),
        ("api_code", False),
        ("api_code", 0.0),
        ("rcd_type", 7.0),
        ("category_id", 118000.0),
    ],
)
def test_verify_live_run_rejects_inexact_json_page_control_types(
    tmp_path,
    field_name: str,
    invalid_value,
) -> None:
    events = _live_events()
    page = next(
        event["payload"]
        for event in events
        if event["event_type"] == "research.page_attempt"
    )
    page[field_name] = invalid_value
    artifact = _export_live(tmp_path, events=events)

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "invalid_runtime_smoke_page_control" in result.issues


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [("api_code", "1002"), ("has_more", "yes")],
)
def test_verify_live_run_rejects_inexact_failed_page_scalar_types(
    tmp_path,
    field_name: str,
    invalid_value,
) -> None:
    events = _live_events(
        detail_attempts=0,
        status="failed",
        smoke_passed=False,
        failure_reason="listing_auth_expired",
    )
    page = next(
        event["payload"]
        for event in events
        if event["event_type"] == "research.page_attempt"
    )
    page.update(
        {
            "classification": "auth_expired",
            "api_code": 1002,
            "has_more": None,
            "row_count": 0,
            "id_pairs": [],
            "rows": [],
            "stop_reason": "auth_expired",
        }
    )
    page[field_name] = invalid_value
    cohort = next(
        event["payload"]
        for event in events
        if event["event_type"] == "research.detail_cohort_frozen"
    )
    cohort.update({"count": 0, "targets": []})
    events[-1]["payload"].update(
        {
            "frozen_count": 0,
            "unattempted_count": 0,
            "listing_stop_reason": "auth_expired",
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
        event for event in events if event["event_type"] == "research.detail_attempt"
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
        event for event in events if event["event_type"] == "research.detail_attempt"
    )
    detail["payload"].update({"classification": "terminal_unavailable", "api_code": 0})
    events[-1]["payload"].update({"success_count": 19, "terminal_count": 1})
    artifact = _export_live(tmp_path, events=events)

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "terminal_unavailable_code_mismatch" in result.issues


def test_verify_live_run_rejects_attempt_after_batch_stop(tmp_path) -> None:
    events = _live_events(status="failed", smoke_passed=False)
    first_detail = next(
        event for event in events if event["event_type"] == "research.detail_attempt"
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
        event for event in events if event["event_type"] == "research.detail_attempt"
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
        event for event in events if event["event_type"] == "research.page_attempt"
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


def test_failed_gap_page_is_not_committed_to_cohort_authority(tmp_path) -> None:
    events = _live_events(
        detail_attempts=0,
        status="failed",
        smoke_passed=False,
        failure_reason="listing_gap",
    )
    page = next(
        event["payload"]
        for event in events
        if event["event_type"] == "research.page_attempt"
    )
    page["stop_reason"] = "gap"
    events[-1]["payload"]["listing_stop_reason"] = "gap"
    artifact = _export_live(
        tmp_path,
        events=events,
        status="failed",
        smoke_passed=False,
    )

    result = verify_live_research_run(artifact)

    assert result.valid is False
    assert "detail_cohort_identity_mismatch" in result.issues


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
        event for event in events if event["event_type"] == "research.detail_attempt"
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


@pytest.mark.parametrize(
    "relative_path",
    [
        ("backend/runtime/offertoday-research/" "fab9d8e1-4c12-4170-a539-c0a6cdbbca93"),
        ("backend/runtime/offertoday-research/" "63b9d32a-5d47-44c9-8904-25a68ee2dee8"),
    ],
)
def test_verify_live_run_keeps_each_immutable_failed_smoke_valid(
    relative_path: str,
) -> None:
    artifact = Path(relative_path)
    if not (artifact / "manifest.json").is_file():
        pytest.skip("immutable failed smoke artifact is unavailable in this checkout")
    manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))

    result = verify_live_research_run(artifact)

    assert manifest["metadata"]["request_budget"] == LEGACY_SMOKE_BUDGET
    assert manifest["metadata"]["crawl_job_status"] == "failed"
    assert manifest["metadata"]["smoke_passed"] is False
    assert result.valid is True, result.issues
