from __future__ import annotations

import ast
import copy
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from sqlalchemy.exc import OperationalError, SQLAlchemyError

import scripts.offertoday_research as research_cli
from app.sources.offertoday.research.artifacts import (
    ResearchProvenance,
    export_research_artifact,
)
from app.sources.offertoday.research.contracts import (
    CrawlJobEvidenceSnapshot,
    ProductDataSnapshot,
    StagedListingSnapshot,
)
from scripts.offertoday_research import (
    EXIT_EVIDENCE_FAILURE,
    EXIT_HARD_STOP,
    EXIT_INCOMPLETE,
    EXIT_OK,
    EXIT_USAGE,
    build_parser,
    main,
)


FIXED_RUN_ID = "11111111-1111-1111-1111-111111111111"
FIXED_TIME = datetime(2026, 7, 10, tzinfo=UTC)


class ReadOnlyFakeSession:
    def __init__(self, *, close_error: BaseException | None = None) -> None:
        self.commit_calls = 0
        self.close_calls = 0
        self.write_calls: list[str] = []
        self.close_error = close_error

    def _forbid_write(self, name: str) -> None:
        self.write_calls.append(name)
        raise AssertionError(f"read-only CLI called Session.{name}")

    def add(self, *_args, **_kwargs) -> None:
        self._forbid_write("add")

    def flush(self, *_args, **_kwargs) -> None:
        self._forbid_write("flush")

    def commit(self) -> None:
        self.commit_calls += 1
        self._forbid_write("commit")

    def delete(self, *_args, **_kwargs) -> None:
        self._forbid_write("delete")

    def execute(self, *_args, **_kwargs) -> None:
        self._forbid_write("execute")

    def close(self) -> None:
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


class FakeResearchRepository:
    def __init__(
        self,
        *,
        listings=(),
        jobs=(),
        recent_runs=(),
        crawl_job=None,
        events=(),
        failures=None,
    ) -> None:
        self.listings = list(listings)
        self.jobs = list(jobs)
        self.recent_runs = list(recent_runs)
        self.crawl_job = crawl_job
        self.events = list(events)
        self.failures = dict(failures or {})
        self.calls: list[str] = []

    def _record(self, name: str) -> None:
        self.calls.append(name)
        failure = self.failures.get(name)
        if failure is not None:
            raise failure

    def list_staged_snapshots(self, db):
        self._record("list_staged_snapshots")
        return list(self.listings)

    def list_published_snapshots(self, db):
        self._record("list_published_snapshots")
        return list(self.jobs)

    def capture_product_data_snapshot(self, db):
        self._record("capture_product_data_snapshot")
        return ProductDataSnapshot.from_table_hashes(
            staged_rows_hash="a" * 64,
            published_jobs_hash="b" * 64,
            companies_hash="c" * 64,
        )

    def list_recent_crawl_jobs(self, db):
        self._record("list_recent_crawl_jobs")
        return list(self.recent_runs)

    def get_crawl_job(self, db, crawl_job_id):
        self._record("get_crawl_job")
        if self.crawl_job is None or self.crawl_job.id != crawl_job_id:
            return None
        return self.crawl_job

    def list_research_events(self, db, crawl_job_id):
        self._record("list_research_events")
        return list(self.events)


def fake_provenance(**kwargs) -> ResearchProvenance:
    return ResearchProvenance(
        commit_sha="fixture-sha",
        working_tree_patch="",
        source_hashes={},
        compose_file_hashes={},
        captured_at=kwargs["captured_at"],
        runtime_context=kwargs["runtime_context"],
        untracked_file_hashes={},
        excluded_tracked_file_hashes={},
        excluded_untracked_file_hashes={},
    )


def provenance_after_close(session: ReadOnlyFakeSession):
    def provider(**kwargs) -> ResearchProvenance:
        assert session.close_calls == 1
        return fake_provenance(**kwargs)

    return Mock(side_effect=provider)


def sensitive_operational_error() -> OperationalError:
    return OperationalError(
        "SELECT password FROM secrets WHERE dsn = :dsn",
        {
            "dsn": "postgresql://admin:dev_password@localhost:5433/jobsdb",
            "password": "dev_password",
        },
        RuntimeError("authentication failed for dev_password"),
    )


def sensitive_sqlalchemy_error() -> SQLAlchemyError:
    return SQLAlchemyError(
        "postgresql://admin:dev_password@localhost:5433/jobsdb "
        "SELECT password FROM secrets params={'password': 'dev_password'}"
    )


def assert_safe_database_failure(capsys) -> None:
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"error": "database operation failed"}
    assert "Traceback" not in captured.err
    for sensitive in (
        "postgresql://",
        "dev_password",
        "SELECT",
        "params",
        "dsn",
    ):
        assert sensitive not in captured.err


def build_fixture_artifact(root: Path) -> Path:
    return export_research_artifact(
        root=root,
        run_id=FIXED_RUN_ID,
        metadata={"experiment": "fixture"},
        events=[],
        provenance=fake_provenance(
            captured_at=FIXED_TIME.isoformat(),
            runtime_context={"session_mode": "fixture"},
        ),
    )


def _event(
    sequence_no: int,
    event_type: str,
    payload: dict,
) -> SimpleNamespace:
    return SimpleNamespace(
        sequence_no=sequence_no,
        event_type=event_type,
        payload=payload,
        emitted_by="fixture",
        created_at=FIXED_TIME,
    )


def _crawl_job(*, status: str = "completed") -> SimpleNamespace:
    return SimpleNamespace(
        id=UUID(FIXED_RUN_ID),
        status=status,
        request_payload={
            "research": {
                "run_start_inventory": {
                    "published_job_ids": ["j-1"],
                    "staged_unpublished_job_ids": [],
                    "data_hash": "fixture-inventory-hash",
                }
            }
        },
    )


def _valid_page_event(sequence_no: int = 1) -> SimpleNamespace:
    return _event(
        sequence_no,
        "research.page_attempt",
        {
            "condition_id": "condition-1",
            "page": 1,
            "classification": "success",
            "row_count": 1,
            "missing_job_id_count": 0,
            "rows": [
                {
                    "job_id": "j-1",
                    "encrypted_job_id": "enc-1",
                }
            ],
            "id_pairs": [
                {
                    "job_id": "j-1",
                    "encrypted_job_id": "enc-1",
                }
            ],
        },
    )


def _read_observations(artifact_dir: Path) -> list[dict]:
    payload = (artifact_dir / "observations.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in payload.splitlines() if line]


def _stdout_json(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def test_foundation_cli_has_only_offline_commands_and_fixed_exit_codes():
    parser = build_parser()

    assert set(parser._subparsers._group_actions[0].choices) == {
        "baseline",
        "conservation",
        "export-run",
        "verify-artifact",
    }
    assert (EXIT_OK, EXIT_USAGE, EXIT_INCOMPLETE, EXIT_HARD_STOP) == (0, 2, 3, 4)
    assert EXIT_EVIDENCE_FAILURE == 5


def test_parser_uses_plan_defaults_and_requires_command_arguments():
    parser = build_parser()
    baseline = parser.parse_args(["baseline"])

    assert baseline.run_id is None
    assert baseline.artifact_root == Path("backend/runtime/offertoday-research")
    assert baseline.repo_root == Path(__file__).resolve().parents[2]
    with pytest.raises(SystemExit) as missing_command:
        parser.parse_args([])
    with pytest.raises(SystemExit) as missing_job:
        parser.parse_args(["conservation"])
    with pytest.raises(SystemExit) as missing_artifact:
        parser.parse_args(["verify-artifact"])
    assert missing_command.value.code == EXIT_USAGE
    assert missing_job.value.code == EXIT_USAGE
    assert missing_artifact.value.code == EXIT_USAGE


def test_baseline_is_read_only_and_exports_snapshot_inventory_and_recent_runs(
    tmp_path,
    capsys,
):
    session = ReadOnlyFakeSession()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    recent = CrawlJobEvidenceSnapshot(
        crawl_job_id="recent-run",
        status="completed",
        request_payload={
            "safe": "request-evidence",
            "api_token": "must-not-export",
        },
        metrics={"listing_rows": 4},
        error_message=None,
        started_at=FIXED_TIME.isoformat(),
        completed_at=FIXED_TIME.isoformat(),
    )
    repository = FakeResearchRepository(
        listings=[
            StagedListingSnapshot(
                "row-1",
                "j-1",
                "pending",
                None,
                "run-1",
                encrypted_job_id="enc-1",
            )
        ],
        jobs=[],
        recent_runs=[recent],
    )
    browser_factory = Mock(side_effect=AssertionError("browser must not start"))
    provenance_provider = provenance_after_close(session)

    exit_code = main(
        [
            "baseline",
            "--artifact-root",
            str(tmp_path / "artifacts"),
            "--repo-root",
            str(repo_root),
            "--run-id",
            FIXED_RUN_ID,
        ],
        session_factory=lambda: session,
        repository=repository,
        browser_factory=browser_factory,
        provenance_provider=provenance_provider,
    )

    assert exit_code == EXIT_OK
    assert session.commit_calls == 0
    assert session.write_calls == []
    assert session.close_calls == 1
    assert browser_factory.call_count == 0
    assert repository.calls == [
        "list_staged_snapshots",
        "list_published_snapshots",
        "capture_product_data_snapshot",
        "list_recent_crawl_jobs",
    ]
    provider_kwargs = provenance_provider.call_args.kwargs
    assert provider_kwargs["repo_root"] == repo_root.resolve()
    assert provider_kwargs["runtime_context"]["command"] == "baseline"
    assert provider_kwargs["runtime_context"]["latest_request_payload"] == (
        recent.request_payload
    )
    datetime.fromisoformat(provider_kwargs["captured_at"])

    output = _stdout_json(capsys)
    artifact_dir = Path(output["artifact"])
    assert artifact_dir == tmp_path / "artifacts" / FIXED_RUN_ID
    assert output["run_id"] == FIXED_RUN_ID
    assert output["valid"] is True
    assert output["staged_rows"] == 1
    assert output["distinct_staged_ids"] == 1
    assert output["published_jobs"] == 0
    assert output["distinct_staged_unpublished_ids"] == 1
    assert len(output["data_hash"]) == 64
    assert len(output["inventory_data_hash"]) == 64

    observations = _read_observations(artifact_dir)
    assert [event["event_type"] for event in observations] == [
        "research.baseline"
    ]
    payload = observations[0]["payload"]
    assert payload["snapshot"]["data_hash"] == output["data_hash"]
    assert payload["run_start_inventory"]["data_hash"] == (
        output["inventory_data_hash"]
    )
    assert payload["recent_crawl_jobs"][0]["request_payload"] == {
        "safe": "request-evidence"
    }
    serialized = json.dumps(observations)
    assert "must-not-export" not in serialized
    assert "api_token" not in serialized


def test_conservation_returns_zero_and_appends_serialized_valid_report(
    tmp_path,
    capsys,
):
    session = ReadOnlyFakeSession()
    repository = FakeResearchRepository(
        crawl_job=_crawl_job(),
        events=[_valid_page_event()],
    )
    provenance_provider = provenance_after_close(session)

    exit_code = main(
        [
            "conservation",
            "--crawl-job-id",
            FIXED_RUN_ID,
            "--artifact-root",
            str(tmp_path),
        ],
        session_factory=lambda: session,
        repository=repository,
        provenance_provider=provenance_provider,
    )

    assert exit_code == EXIT_OK
    assert session.write_calls == []
    assert session.close_calls == 1
    assert repository.calls == [
        "get_crawl_job",
        "list_research_events",
        "list_staged_snapshots",
        "list_published_snapshots",
        "list_recent_crawl_jobs",
    ]
    output = _stdout_json(capsys)
    assert output["valid"] is True
    observations = _read_observations(Path(output["artifact"]))
    assert [event["event_type"] for event in observations] == [
        "research.page_attempt",
        "research.conservation",
    ]
    report = observations[-1]["payload"]
    assert isinstance(report, dict)
    assert report["listing"]["raw_rows"]["left_value"] == 1
    assert report["listing"]["raw_rows"]["right_parts"] == {
        "rows_containing_job_id": 1,
        "rows_missing_job_id": 0,
    }


def test_conservation_returns_five_for_invalid_report(tmp_path, capsys):
    session = ReadOnlyFakeSession()
    repository = FakeResearchRepository(
        crawl_job=_crawl_job(status="failed"),
        events=[
            _event(
                1,
                "research.condition_incomplete",
                {"stop_reason": "unresolved_gap", "is_complete": False},
            )
        ],
    )

    exit_code = main(
        [
            "conservation",
            "--crawl-job-id",
            FIXED_RUN_ID,
            "--artifact-root",
            str(tmp_path),
        ],
        session_factory=lambda: session,
        repository=repository,
        provenance_provider=fake_provenance,
    )

    assert exit_code == EXIT_EVIDENCE_FAILURE
    assert session.write_calls == []
    assert session.close_calls == 1
    output = _stdout_json(capsys)
    assert output["valid"] is False
    observations = _read_observations(Path(output["artifact"]))
    assert observations[-1]["event_type"] == "research.conservation"


def test_conservation_returns_safe_failure_for_corrupt_evidence(tmp_path, capsys):
    session = ReadOnlyFakeSession()
    corrupt = _valid_page_event()
    corrupt.payload["row_count"] = -1
    repository = FakeResearchRepository(
        crawl_job=_crawl_job(),
        events=[corrupt],
    )

    exit_code = main(
        [
            "conservation",
            "--crawl-job-id",
            FIXED_RUN_ID,
            "--artifact-root",
            str(tmp_path),
        ],
        session_factory=lambda: session,
        repository=repository,
        provenance_provider=fake_provenance,
    )

    assert exit_code == EXIT_EVIDENCE_FAILURE
    assert session.close_calls == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert "nonnegative integer" in error["error"]


def test_export_run_orders_and_redacts_events_without_mutating_them(
    tmp_path,
    capsys,
):
    session = ReadOnlyFakeSession()
    events = [
        _event(
            2,
            "research.condition_completed",
            {"condition_id": "condition-1", "is_complete": True},
        ),
        _event(
            1,
            "research.page_attempt",
            {
                "condition_id": "condition-1",
                "headers": {"Authorization": "Bearer must-not-export"},
                "rows": [],
            },
        ),
    ]
    original_payloads = copy.deepcopy([event.payload for event in events])
    repository = FakeResearchRepository(crawl_job=_crawl_job(), events=events)
    provenance_provider = provenance_after_close(session)

    exit_code = main(
        [
            "export-run",
            "--crawl-job-id",
            FIXED_RUN_ID,
            "--artifact-root",
            str(tmp_path),
        ],
        session_factory=lambda: session,
        repository=repository,
        provenance_provider=provenance_provider,
    )

    assert exit_code == EXIT_OK
    assert session.write_calls == []
    assert session.close_calls == 1
    assert repository.calls == [
        "get_crawl_job",
        "list_research_events",
        "list_recent_crawl_jobs",
    ]
    assert [event.payload for event in events] == original_payloads
    output = _stdout_json(capsys)
    observations = _read_observations(Path(output["artifact"]))
    assert [event["sequence_no"] for event in observations] == [1, 2]
    assert [event["event_type"] for event in observations] == [
        "research.page_attempt",
        "research.condition_completed",
    ]
    serialized = json.dumps(observations)
    assert "must-not-export" not in serialized
    assert "Authorization" not in serialized


@pytest.mark.parametrize(
    ("tamper", "expected_code", "expected_valid"),
    ((False, EXIT_OK, True), (True, EXIT_EVIDENCE_FAILURE, False)),
)
def test_verify_artifact_hashes_only_without_opening_a_session(
    tmp_path,
    capsys,
    tamper,
    expected_code,
    expected_valid,
):
    artifact_dir = build_fixture_artifact(tmp_path)
    if tamper:
        (artifact_dir / "observations.jsonl").write_text(
            "changed\n",
            encoding="utf-8",
        )
    session_factory = Mock(side_effect=AssertionError("database must not open"))

    exit_code = main(
        ["verify-artifact", "--artifact", str(artifact_dir)],
        session_factory=session_factory,
    )

    assert exit_code == expected_code
    assert session_factory.call_count == 0
    assert _stdout_json(capsys)["valid"] is expected_valid


def test_verify_artifact_oserror_is_safe_json_without_opening_a_session(
    tmp_path,
    capsys,
    monkeypatch,
):
    session_factory = Mock(side_effect=AssertionError("database must not open"))
    monkeypatch.setattr(
        research_cli,
        "verify_research_artifact",
        Mock(side_effect=OSError('unreadable "artifact"\nwithout traceback')),
    )

    exit_code = main(
        ["verify-artifact", "--artifact", str(tmp_path / "artifact")],
        session_factory=session_factory,
    )

    assert exit_code == EXIT_EVIDENCE_FAILURE
    assert session_factory.call_count == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": 'unreadable "artifact"\nwithout traceback'
    }
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    "argv",
    (
        ["baseline", "--run-id", "not-a-uuid"],
        ["conservation", "--crawl-job-id", "not-a-uuid"],
        ["export-run", "--crawl-job-id", "not-a-uuid"],
    ),
    ids=("baseline", "conservation", "export-run"),
)
def test_bad_uuid_never_opens_a_session_or_queries_repository(
    capsys,
    argv,
):
    session_factory = Mock(side_effect=AssertionError("session must not open"))
    repository = FakeResearchRepository()

    exit_code = main(
        argv,
        session_factory=session_factory,
        repository=repository,
        provenance_provider=fake_provenance,
    )

    assert exit_code == EXIT_EVIDENCE_FAILURE
    assert session_factory.call_count == 0
    assert repository.calls == []
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert "badly formed" in error["error"]
    assert set(error) == {"error"}


def test_missing_job_queries_only_the_requested_crawl_job(capsys):
    session = ReadOnlyFakeSession()
    repository = FakeResearchRepository()
    provenance_provider = Mock(side_effect=AssertionError("must not export"))

    exit_code = main(
        ["export-run", "--crawl-job-id", FIXED_RUN_ID],
        session_factory=lambda: session,
        repository=repository,
        provenance_provider=provenance_provider,
    )

    assert exit_code == EXIT_EVIDENCE_FAILURE
    assert session.close_calls == 1
    assert repository.calls == ["get_crawl_job"]
    assert provenance_provider.call_count == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert "Crawl job not found" in error["error"]
    assert set(error) == {"error"}


@pytest.mark.parametrize(
    "error_factory",
    (sensitive_operational_error, sensitive_sqlalchemy_error),
    ids=("operational-error", "sqlalchemy-error"),
)
def test_session_factory_database_errors_are_sanitized(
    capsys,
    error_factory,
):
    session_factory = Mock(side_effect=error_factory())
    repository = FakeResearchRepository()

    exit_code = main(
        ["baseline", "--run-id", FIXED_RUN_ID],
        session_factory=session_factory,
        repository=repository,
        provenance_provider=fake_provenance,
    )

    assert exit_code == EXIT_EVIDENCE_FAILURE
    assert session_factory.call_count == 1
    assert repository.calls == []
    assert_safe_database_failure(capsys)


def test_repository_database_error_closes_once_and_is_sanitized(capsys):
    session = ReadOnlyFakeSession()
    repository = FakeResearchRepository(
        failures={"list_staged_snapshots": sensitive_operational_error()}
    )
    provenance_provider = Mock(side_effect=AssertionError("must not export"))

    exit_code = main(
        ["baseline", "--run-id", FIXED_RUN_ID],
        session_factory=lambda: session,
        repository=repository,
        provenance_provider=provenance_provider,
    )

    assert exit_code == EXIT_EVIDENCE_FAILURE
    assert session.close_calls == 1
    assert repository.calls == ["list_staged_snapshots"]
    assert provenance_provider.call_count == 0
    assert_safe_database_failure(capsys)


def test_close_database_error_prevents_export_and_is_sanitized(tmp_path, capsys):
    session = ReadOnlyFakeSession(close_error=sensitive_sqlalchemy_error())
    repository = FakeResearchRepository()
    provenance_provider = Mock(side_effect=fake_provenance)
    artifact_root = tmp_path / "artifacts"

    exit_code = main(
        [
            "baseline",
            "--run-id",
            FIXED_RUN_ID,
            "--artifact-root",
            str(artifact_root),
        ],
        session_factory=lambda: session,
        repository=repository,
        provenance_provider=provenance_provider,
    )

    assert exit_code == EXIT_EVIDENCE_FAILURE
    assert session.close_calls == 1
    assert provenance_provider.call_count == 0
    assert not artifact_root.exists()
    assert_safe_database_failure(capsys)


def test_oserror_is_safe_json_and_always_closes_session(tmp_path, capsys):
    session = ReadOnlyFakeSession()

    def fail_provenance(**_kwargs):
        raise OSError('capture failed at "fixture"\nwithout traceback')

    exit_code = main(
        [
            "baseline",
            "--run-id",
            FIXED_RUN_ID,
            "--artifact-root",
            str(tmp_path),
        ],
        session_factory=lambda: session,
        repository=FakeResearchRepository(),
        provenance_provider=fail_provenance,
    )

    assert exit_code == EXIT_EVIDENCE_FAILURE
    assert session.close_calls == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": 'capture failed at "fixture"\nwithout traceback'
    }
    assert "Traceback" not in captured.err


def test_script_entrypoint_dispatches_help_with_backend_only_pythonpath():
    repo_root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repo_root / "backend")

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "backend" / "scripts" / "offertoday_research.py"),
            "--help",
        ],
        cwd=repo_root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == EXIT_OK
    assert result.stderr == ""
    assert "baseline" in result.stdout
    assert "conservation" in result.stdout
    assert "export-run" in result.stdout
    assert "verify-artifact" in result.stdout


def test_script_has_no_browser_or_network_imports():
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "backend" / "scripts" / "offertoday_research.py"
    tree = ast.parse(script.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = (
        "playwright",
        "scrapling",
        "requests",
        "httpx",
        "urllib",
        "socket",
        "app.scraper.offertoday",
    )
    assert not any(
        module == prefix or module.startswith(f"{prefix}.")
        for module in imported
        for prefix in forbidden
    )
