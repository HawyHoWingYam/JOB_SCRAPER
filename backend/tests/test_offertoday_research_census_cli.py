from __future__ import annotations

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
from app.sources.offertoday.listing_runner import (
    ListingPageObservation,
    ListingRunResult,
    OfferTodayIdentityPair,
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
from app.sources.offertoday.research.live_contracts import (
    DetailSmokeObservation,
    DetailSmokeTarget,
    LiveSmokeExecution,
)
from app.sources.offertoday.research.contracts import StagedListingSnapshot
from app.sources.offertoday.research.smoke import (
    build_runtime_smoke_condition,
    evaluate_smoke,
)


RUN_ID = "33333333-3333-3333-3333-333333333333"
BASELINE_RUN_1 = "11111111-1111-1111-1111-111111111111"
BASELINE_RUN_2 = "22222222-2222-2222-2222-222222222222"


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
    snapshot = build_baseline_snapshot(listings=baseline_listings, jobs=[])
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


def listing_result(count: int = 20) -> ListingRunResult:
    condition = build_runtime_smoke_condition()
    pairs = tuple(
        OfferTodayIdentityPair(f"j{index}", f"e{index}")
        for index in range(1, count + 1)
    )
    observation = ListingPageObservation(
        condition_id=condition.condition_id,
        search_family=condition.search_family,
        category_id=condition.category_id,
        keyword=condition.keyword,
        endpoint=condition.endpoint,
        rcd_type=condition.rcd_type,
        page=1,
        attempt=1,
        request_fingerprint="d" * 64,
        classification="success",
        api_code=0,
        reported_total=100,
        has_more=True,
        row_count=count,
        missing_job_id_count=0,
        missing_encrypted_job_id_count=0,
        id_pairs=pairs,
        rows=(),
        identity_issues=(),
        identity_conflicts=(),
        latency_ms=50,
        session_mode="fresh-headless",
        retry_reason=None,
        stop_reason=None,
    )
    return ListingRunResult(
        ordered_job_ids=tuple(item.job_id for item in pairs),
        accepted_job_ids=tuple(item.job_id for item in pairs),
        id_pairs=pairs,
        observations=(observation,),
        condition_outcomes=(),
        identity_conflicts=(),
        identity_issues=(),
        gaps=(),
        stop_reason="page_cap",
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
        result = replace(result, stop_reason=listing_stop_reason)
        targets: tuple[DetailSmokeTarget, ...] = ()
    else:
        targets = tuple(
            DetailSmokeTarget(index, f"j{index}", f"e{index}")
            for index in range(1, target_count + 1)
        )
    if target_count < 20 or listing_stop_reason is not None:
        observations: tuple[DetailSmokeObservation, ...] = ()
    else:
        attempted_targets = targets if detail_classification == "success" else targets[:1]
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
        end_snapshot_error: BaseException | None = None,
        event_load_errors: list[BaseException] | None = None,
    ) -> None:
        self.state = state
        self.drift = drift
        self.end_snapshot_error = end_snapshot_error
        self.event_load_errors = list(event_load_errors or [])
        self.staged_reads = 0

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
        observation_service.record_event(
            "research.page_attempt",
            {"page": 1, "attempt": 1, "classification": "success"},
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


def invoke_smoke(
    tmp_path: Path,
    *,
    result: LiveSmokeExecution | BaseException | None = None,
    drift: bool = False,
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


def test_parser_exposes_only_locked_smoke_inputs_and_offline_verify() -> None:
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
    verify = parser.parse_args(["verify-run", "--artifact", "run"])

    assert smoke.command == "smoke"
    assert smoke.baseline_artifact == [Path("first"), Path("second")]
    assert verify.command == "verify-run"
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


def test_verify_run_is_network_and_database_free(tmp_path) -> None:
    events = [
        {"sequence_no": 1, "event_type": "research.run_started", "payload": {}},
        {
            "sequence_no": 2,
            "event_type": "research.page_attempt",
            "payload": {"page": 1, "attempt": 1, "classification": "success"},
        },
        {
            "sequence_no": 3,
            "event_type": "research.detail_cohort_frozen",
            "payload": {
                "count": 20,
                "targets": [
                    DetailSmokeTarget(position, f"j{position}", f"e{position}").to_payload()
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
                "stop_reason": None,
                "product_data_unchanged": True,
                "run_start_snapshot_hash": "d" * 64,
                "run_end_snapshot_hash": "d" * 64,
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
            "request_budget": {"listing": 1, "detail": 20},
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


def test_successful_smoke_lifecycle_and_artifact(tmp_path) -> None:
    exit_code, state, session, artifact = invoke_smoke(tmp_path)

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
    assert state.finished[0]["summary"]["run_start_snapshot_hash"] == state.finished[0]["summary"]["run_end_snapshot_hash"]
    assert state.finished[0]["summary"]["run_start_inventory_hash"] == state.finished[0]["summary"]["run_end_inventory_hash"]
    assert verify_research_artifact(artifact).valid is True


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
