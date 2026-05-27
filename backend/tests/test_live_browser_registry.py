from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.host_manual_action_helper import (
    _is_default_browser_profile_path,
    build_host_manual_action_helper_app,
    close_profile_windows,
    launch_browser_process,
)
from app.manual_actions.live_browser_registry import LiveBrowserRegistry
from app.services import runtime_capabilities_service


class FakeSession:
    def close(self) -> None:
        return None


class FakeCrawlJobRepository:
    def __init__(self, manual_action: dict[str, str]) -> None:
        self._manual_action = manual_action

    def get_crawl_job_by_id(self, db, crawl_job_id):
        return SimpleNamespace(id=crawl_job_id, status="manual_action_required")

    def get_latest_manual_action_event(self, db, crawl_job_id):
        return SimpleNamespace(payload={"manual_action": self._manual_action})


def _build_client(
    *,
    manual_action: dict[str, str],
    registry: LiveBrowserRegistry | None = None,
    browser_launcher=None,
    process_lister=None,
    process_killer=None,
    reachability_probe=None,
):
    app = build_host_manual_action_helper_app(
        session_factory=FakeSession,
        crawl_job_repository=FakeCrawlJobRepository(manual_action),
        browser_launcher=browser_launcher,
        process_lister=process_lister,
        process_killer=process_killer,
        live_browser_registry=registry,
        session_reachability_probe=reachability_probe,
    )
    return TestClient(app)


def test_registering_launched_session_stores_expected_metadata():
    registry = LiveBrowserRegistry()
    launch_calls: list[dict[str, str]] = []

    def browser_launcher(**kwargs):
        launch_calls.append(kwargs)
        return {
            "browser_channel": kwargs["browser_channel"],
            "browser_profile_path": kwargs["browser_profile_path"],
            "blocked_url": kwargs["blocked_url"],
            "debug_port": 48888,
        }

    client = _build_client(
        manual_action={
            "browser_channel": "msedge",
            "browser_profile_path": r"C:\automation\profile-a",
            "blocked_url": "https://example.test/challenge",
        },
        registry=registry,
        browser_launcher=browser_launcher,
        reachability_probe=lambda session: True,
    )

    response = client.post("/manual-actions/open-browser", json={"crawl_job_id": str(uuid4())})

    assert response.status_code == 200
    assert len(launch_calls) == 1
    payload = response.json()
    assert payload["debug_port"] == 48888
    assert payload["status"] == "live"
    session = registry.get(r"C:\automation\profile-a")
    assert session is not None
    assert session.browser_channel == "msedge"
    assert session.browser_profile_path == r"C:\automation\profile-a"
    assert session.blocked_url == "https://example.test/challenge"
    assert session.debug_port == 48888
    assert session.status == "live"
    assert session.launched_at is not None
    assert session.last_seen_at is not None


def test_launch_browser_process_sets_debug_flags_and_registers_session(monkeypatch):
    registry = LiveBrowserRegistry()
    launch_commands: list[list[str]] = []

    monkeypatch.setattr(
        "app.host_manual_action_helper._default_browser_executable",
        lambda browser_channel: r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    )

    def process_launcher(command, **kwargs):
        launch_commands.append(command)
        return SimpleNamespace()

    payload = launch_browser_process(
        browser_channel="msedge",
        browser_profile_path=r"C:\automation\profile-launch",
        blocked_url="https://example.test/launch",
        live_browser_registry=registry,
        port_reserver=lambda: 45555,
        process_launcher=process_launcher,
    )

    assert payload["debug_port"] == 45555
    assert payload["status"] == "live"
    assert launch_commands == [[
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"--user-data-dir=C:\automation\profile-launch",
        "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=45555",
        "https://example.test/launch",
    ]]
    session = registry.get(r"C:\automation\profile-launch")
    assert session is not None
    assert session.debug_port == 45555


def test_reopening_same_profile_reuses_existing_session():
    registry = LiveBrowserRegistry()
    launch_calls: list[dict[str, str]] = []

    def browser_launcher(**kwargs):
        launch_calls.append(kwargs)
        return {
            "browser_channel": kwargs["browser_channel"],
            "browser_profile_path": kwargs["browser_profile_path"],
            "blocked_url": kwargs["blocked_url"],
            "debug_port": 49991,
        }

    client = _build_client(
        manual_action={
            "browser_channel": "chrome",
            "browser_profile_path": r"C:\automation\profile-b",
            "blocked_url": "https://example.test/verify",
        },
        registry=registry,
        browser_launcher=browser_launcher,
        reachability_probe=lambda session: True,
    )
    request_payload = {"crawl_job_id": str(uuid4())}

    first = client.post("/manual-actions/open-browser", json=request_payload)
    second = client.post("/manual-actions/open-browser", json=request_payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(launch_calls) == 1
    assert second.json()["debug_port"] == 49991
    assert second.json()["status"] == "live"
    assert registry.get(r"C:\automation\profile-b").debug_port == 49991


def test_open_browser_waits_for_reachable_session_before_immediate_reuse_status_check():
    registry = LiveBrowserRegistry()
    probe_calls = {"count": 0}

    def browser_launcher(**kwargs):
        return {
            "browser_channel": kwargs["browser_channel"],
            "browser_profile_path": kwargs["browser_profile_path"],
            "blocked_url": kwargs["blocked_url"],
            "debug_port": 47771,
        }

    def reachability_probe(session):
        probe_calls["count"] += 1
        return probe_calls["count"] >= 3

    client = _build_client(
        manual_action={
            "browser_channel": "chrome",
            "browser_profile_path": r"C:\automation\profile-race",
            "blocked_url": "https://example.test/race",
        },
        registry=registry,
        browser_launcher=browser_launcher,
        reachability_probe=reachability_probe,
    )
    request_payload = {"crawl_job_id": str(uuid4())}

    open_response = client.post("/manual-actions/open-browser", json=request_payload)
    reuse_response = client.post("/manual-actions/reuse-status", json=request_payload)

    assert open_response.status_code == 200
    assert reuse_response.status_code == 200
    assert reuse_response.json()["available"] is True
    assert probe_calls["count"] >= 3


def test_registry_normalizes_profile_identity_keys():
    registry = LiveBrowserRegistry()
    registry.register(
        browser_channel="msedge",
        browser_profile_path=r"C:/Automation/Profile-E/",
        blocked_url="https://example.test/e",
        debug_port=41111,
        status="live",
    )

    session = registry.get(r"c:\automation\profile-e")

    assert session is not None
    assert session.browser_profile_path == r"C:/Automation/Profile-E/"
    registry.remove(r"C:\AUTOMATION\PROFILE-E\\")
    assert registry.get(r"c:\automation\profile-e") is None


def test_registry_persists_sessions_to_disk_and_reload_across_instances(tmp_path):
    state_path = tmp_path / "manual-actions" / "live-browser-sessions.json"
    first_registry = LiveBrowserRegistry(storage_path=state_path)
    first_registry.register(
        browser_channel="msedge",
        browser_profile_path=r"C:\automation\profile-persisted",
        blocked_url="https://example.test/persisted",
        debug_port=40123,
        status="live",
    )

    second_registry = LiveBrowserRegistry(storage_path=state_path)
    session = second_registry.get(r"C:\automation\profile-persisted")

    assert session is not None
    assert session.browser_channel == "msedge"
    assert session.debug_port == 40123
    assert Path(state_path).exists()


def test_registry_revalidate_marks_unreachable_sessions_stale_in_shared_state(tmp_path):
    state_path = tmp_path / "manual-actions" / "live-browser-sessions.json"
    first_registry = LiveBrowserRegistry(storage_path=state_path)
    first_registry.register(
        browser_channel="msedge",
        browser_profile_path=r"C:\automation\profile-stale",
        blocked_url="https://example.test/stale",
        debug_port=40234,
        status="live",
    )

    second_registry = LiveBrowserRegistry(storage_path=state_path)
    second_registry.revalidate(lambda session: False)

    reloaded = LiveBrowserRegistry(storage_path=state_path)
    session = reloaded.get(r"C:\automation\profile-stale")

    assert session is not None
    assert session.status == "stale"


def test_close_profile_windows_clears_matching_registry_state():
    registry = LiveBrowserRegistry()
    registry.register(
        browser_channel="msedge",
        browser_profile_path=r"C:\automation\profile-c",
        blocked_url="https://example.test",
        debug_port=47777,
        status="live",
    )
    killed_pids: list[int] = []
    processes = [
        {
            "pid": 1234,
            "name": "msedge.exe",
            "command_line": r"msedge.exe --user-data-dir=C:\automation\profile-c",
        }
    ]

    def process_killer(pid):
        killed_pids.append(pid)
        processes[:] = [process for process in processes if process["pid"] != pid]
        return True

    client = _build_client(
        manual_action={
            "browser_channel": "msedge",
            "browser_profile_path": r"C:\automation\profile-c",
            "blocked_url": "https://example.test",
        },
        registry=registry,
        process_lister=lambda: list(processes),
        process_killer=process_killer,
        reachability_probe=lambda session: True,
    )

    response = client.post("/manual-actions/close-profile-windows", json={"crawl_job_id": str(uuid4())})

    assert response.status_code == 200
    assert response.json()["closed_processes"] == 1
    assert killed_pids == [1234]
    assert registry.get(r"C:\automation\profile-c") is None


def test_close_profile_windows_keeps_registry_when_termination_fails():
    registry = LiveBrowserRegistry()
    registry.register(
        browser_channel="msedge",
        browser_profile_path=r"C:\automation\profile-f",
        blocked_url="https://example.test/f",
        debug_port=43333,
        status="live",
    )

    def process_killer(pid):
        return False

    result = close_profile_windows(
        browser_channel="msedge",
        browser_profile_path=r"C:\automation\profile-f",
        live_browser_registry=registry,
        process_lister=lambda: [
            {
                "pid": 4444,
                "name": "msedge.exe",
                "command_line": r'msedge.exe --user-data-dir="C:\automation\profile-f"',
            }
        ],
        process_killer=process_killer,
    )

    assert result == {
        "matched_processes": 1,
        "closed_processes": 0,
    }
    assert registry.get(r"C:\automation\profile-f") is not None


def test_close_profile_windows_matches_user_data_dir_exactly():
    registry = LiveBrowserRegistry()
    registry.register(
        browser_channel="msedge",
        browser_profile_path=r"C:\automation\profile-g",
        blocked_url="https://example.test/g",
        debug_port=42222,
        status="live",
    )
    killed_pids: list[int] = []
    processes = [
        {
            "pid": 2001,
            "name": "msedge.exe",
            "command_line": r'msedge.exe --user-data-dir="C:\automation\profile-g2"',
        },
        {
            "pid": 2002,
            "name": "msedge.exe",
            "command_line": r'msedge.exe --remote-debugging-port=45555 --user-data-dir="C:\automation\profile-g"',
        },
    ]

    def process_killer(pid):
        killed_pids.append(pid)
        processes[:] = [process for process in processes if process["pid"] != pid]
        return True

    result = close_profile_windows(
        browser_channel="msedge",
        browser_profile_path=r"C:\automation\profile-g",
        live_browser_registry=registry,
        process_lister=lambda: list(processes),
        process_killer=process_killer,
    )

    assert result == {
        "matched_processes": 1,
        "closed_processes": 1,
    }
    assert killed_pids == [2002]
    assert registry.get(r"C:\automation\profile-g") is None


def test_reuse_status_returns_unavailable_for_stale_or_unreachable_entry():
    registry = LiveBrowserRegistry()
    registry.register(
        browser_channel="chrome",
        browser_profile_path=r"C:\automation\profile-d",
        blocked_url="https://example.test/stale",
        debug_port=46666,
        status="live",
    )
    client = _build_client(
        manual_action={
            "browser_channel": "chrome",
            "browser_profile_path": r"C:\automation\profile-d",
            "blocked_url": "https://example.test/stale",
        },
        registry=registry,
        reachability_probe=lambda session: False,
    )

    response = client.post("/manual-actions/reuse-status", json={"crawl_job_id": str(uuid4())})

    assert response.status_code == 200
    assert response.json() == {
        "available": False,
        "reason": "live_browser_unreachable",
    }
    session = registry.get(r"C:\automation\profile-d")
    assert session is not None
    assert session.status == "stale"


def test_default_profile_reuse_is_rejected_before_registry_probe():
    registry = LiveBrowserRegistry()
    registry.register(
        browser_channel="chrome",
        browser_profile_path=r"C:\Users\alice\AppData\Local\Google\Chrome\User Data\Default",
        blocked_url="https://example.test/default",
        debug_port=45501,
        status="live",
    )
    probe_calls = {"count": 0}

    def reachability_probe(session):
        probe_calls["count"] += 1
        return True

    client = _build_client(
        manual_action={
            "browser_channel": "chrome",
            "browser_profile_path": r"C:\Users\alice\AppData\Local\Google\Chrome\User Data\Default",
            "blocked_url": "https://example.test/default",
        },
        registry=registry,
        reachability_probe=reachability_probe,
    )

    open_response = client.post("/manual-actions/open-browser", json={"crawl_job_id": str(uuid4())})
    reuse_response = client.post("/manual-actions/reuse-status", json={"crawl_job_id": str(uuid4())})

    assert open_response.status_code == 409
    assert reuse_response.status_code == 409
    assert probe_calls["count"] == 0


def test_default_profile_detection_blocks_browser_defaults_but_allows_automation_folder():
    assert _is_default_browser_profile_path(r"C:\automation\Default") is False
    assert _is_default_browser_profile_path(r"C:\automation\User Data") is False
    assert (
        _is_default_browser_profile_path(
            r"C:\Users\alice\AppData\Local\Google\Chrome\User Data\Default"
        )
        is True
    )
    assert (
        _is_default_browser_profile_path(
            r"C:\Users\alice\AppData\Local\Microsoft\Edge\User Data\Profile 3"
        )
        is True
    )


def test_runtime_capabilities_expose_reuse_open_browser_support(monkeypatch):
    monkeypatch.setattr(
        runtime_capabilities_service,
        "get_profile_runtime_metadata",
        lambda scope: SimpleNamespace(
            is_ready=False,
            requires_test=False,
            configured_provider=None,
            model=None,
            active_fingerprint=None,
            config_fingerprint=None,
            last_tested_fingerprint=None,
            last_test_fingerprint=None,
            degradation_reason=None,
            last_test_error=None,
            last_tested_at=None,
            is_degraded=False,
        ),
    )
    monkeypatch.setattr(
        runtime_capabilities_service,
        "get_scheduler_runtime_status",
        lambda: {"enabled": True},
    )

    capabilities = runtime_capabilities_service.build_runtime_capabilities()

    assert capabilities["manual_actions"]["reuse_open_browser_supported"] is True
