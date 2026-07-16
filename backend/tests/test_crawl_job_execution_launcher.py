from __future__ import annotations

from types import SimpleNamespace

import psutil
import pytest

from app.services import crawl_job_execution_launcher as launcher_module
from app.services.crawl_job_execution_launcher import (
    CrawlJobExecutionLauncher,
    ProcessIdentityUnavailable,
)
from app.utils.time import utc_now


class _Session:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class _CancellationService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def acknowledge_cancelled(self, **kwargs) -> bool:
        self.calls.append(kwargs)
        return True


def _launcher(**kwargs) -> CrawlJobExecutionLauncher:
    return CrawlJobExecutionLauncher(
        session_factory=lambda: _Session(),
        cancellation_service=_CancellationService(),
        **kwargs,
    )


def test_build_command_persists_execution_generation() -> None:
    command = _launcher().build_command(
        SimpleNamespace(id="job-id", source_site="jobsdb"),
        generation="generation-id",
    )

    assert command[-4:] == [
        "--crawl-job-id",
        "job-id",
        "--execution-generation",
        "generation-id",
    ]


def test_validated_process_rejects_pid_reuse_with_wrong_command() -> None:
    process = SimpleNamespace(
        create_time=lambda: 123.0,
        cmdline=lambda: [
            "C:/Python/python.exe",
            "C:/other-script.py",
            "--crawl-job-id",
            "job-id",
            "--execution-generation",
            "generation-id",
        ],
    )
    launcher = _launcher(process_factory=lambda _pid: process)
    snapshot = {
        "pid": 99,
        "process_create_time": 123.0,
        "generation": "generation-id",
        "crawl_job_id": "job-id",
        "command": [
            "python",
            "C:/expected-script.py",
            "--crawl-job-id",
            "job-id",
            "--execution-generation",
            "generation-id",
        ],
    }

    assert launcher._validated_process(snapshot) is None


def test_validated_process_accepts_same_generation_create_time_and_command() -> None:
    command = [
        "python",
        "C:/expected-script.py",
        "--crawl-job-id",
        "job-id",
        "--execution-generation",
        "generation-id",
    ]
    process = SimpleNamespace(
        create_time=lambda: 123.0,
        cmdline=lambda: ["C:/Python/python.exe", *command[1:]],
    )
    launcher = _launcher(process_factory=lambda _pid: process)

    assert (
        launcher._validated_process(
            {
                "pid": 99,
                "process_create_time": 123.0,
                "generation": "generation-id",
                "crawl_job_id": "job-id",
                "command": command,
            }
        )
        is process
    )


def test_validated_process_does_not_treat_access_denied_as_exit() -> None:
    def denied_process(_pid):
        raise psutil.AccessDenied(pid=99)

    launcher = _launcher(process_factory=denied_process)

    with pytest.raises(ProcessIdentityUnavailable):
        launcher._validated_process(
            {
                "pid": 99,
                "process_create_time": 123.0,
                "generation": "generation-id",
                "crawl_job_id": "job-id",
                "command": ["python", "script.py"],
            }
        )


def test_force_stop_kills_surviving_process_tree(monkeypatch) -> None:
    calls: list[str] = []

    class _Process:
        def __init__(self, name: str) -> None:
            self.name = name

        def children(self, recursive: bool):
            assert recursive is True
            return [child]

        def terminate(self) -> None:
            calls.append(f"terminate:{self.name}")

        def kill(self) -> None:
            calls.append(f"kill:{self.name}")

    parent = _Process("parent")
    child = _Process("child")
    wait_calls = 0

    def fake_wait_procs(processes, timeout):
        nonlocal wait_calls
        wait_calls += 1
        if wait_calls == 1:
            return [], list(processes)
        return list(processes), []

    monkeypatch.setattr(psutil, "wait_procs", fake_wait_procs)

    assert CrawlJobExecutionLauncher._terminate_process_tree(parent)
    assert calls == [
        "terminate:child",
        "terminate:parent",
        "kill:child",
        "kill:parent",
    ]


def test_supervisor_waits_full_grace_then_force_stops_and_acknowledges(
    monkeypatch,
) -> None:
    now = 0.0
    process = SimpleNamespace(is_running=lambda: True)
    snapshot = {
        "pid": 99,
        "process_create_time": 123.0,
        "generation": "generation-id",
        "crawl_job_id": "job-id",
        "command": ["python", "script.py"],
        "stop_requested_at": utc_now(),
    }
    launcher = _launcher()
    launcher._execution_snapshot = lambda _generation: snapshot
    launcher._validated_process = lambda _snapshot: process
    terminated: list[object] = []
    acknowledged: list[dict] = []

    def fake_sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setattr(launcher_module.time, "monotonic", lambda: now)
    launcher._sleep = fake_sleep
    launcher._terminate_process_tree = lambda value: terminated.append(value) or True
    launcher._record_exit_and_acknowledge = lambda value, **kwargs: acknowledged.append(
        {"snapshot": value, **kwargs}
    )

    launcher._supervise_cancellation("generation-id")

    assert now >= 30.0
    assert terminated == [process]
    assert acknowledged == [
        {"snapshot": snapshot, "status": "terminated", "exit_code": None}
    ]


def test_restart_recovery_supervises_active_and_acknowledges_pidless_jobs() -> None:
    active = SimpleNamespace(generation="active-generation", status="running")
    jobs = [
        SimpleNamespace(id="active-job", error_message=None),
        SimpleNamespace(id="pidless-job", error_message="operator cancelled"),
    ]

    class _CrawlRepository:
        @staticmethod
        def list_crawl_jobs_by_statuses(_db, *, statuses, limit=None):
            assert statuses == ["cancelling"]
            assert limit is None
            return jobs

    class _ExecutionRepository:
        requested: list[object] = []

        @staticmethod
        def get_latest_active_for_job(_db, crawl_job_id, *, for_update=False):
            assert for_update is True
            return active if crawl_job_id == "active-job" else None

        @classmethod
        def request_stop(cls, execution) -> None:
            cls.requested.append(execution)
            execution.status = "stop_requested"

    cancellation = _CancellationService()
    launcher = CrawlJobExecutionLauncher(
        session_factory=lambda: _Session(),
        cancellation_service=cancellation,
    )
    launcher._crawl_job_repository = _CrawlRepository()
    launcher._execution_repository = _ExecutionRepository()
    supervised: list[str] = []
    launcher.supervise_cancellation = supervised.append

    assert launcher.recover_pending_cancellations() == 2
    assert supervised == ["active-generation"]
    assert cancellation.calls == [
        {"crawl_job_id": "pidless-job", "reason": "operator cancelled"}
    ]
