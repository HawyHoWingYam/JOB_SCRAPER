from __future__ import annotations

import threading
from types import SimpleNamespace
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

import app.host_manual_action_helper as helper_module
from app.host_manual_action_helper import (
    _default_browser_executable,
    _matching_profile_process_pids,
    _resolve_host_browser_profile_path,
    launch_browser_process,
)
from app.manual_actions.live_browser_registry import LiveBrowserRegistry


def _make_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    path.chmod(0o755)
    return path


def test_macos_resolves_chromium_app(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    executable = _make_executable(
        tmp_path
        / "Applications"
        / "Chromium.app"
        / "Contents"
        / "MacOS"
        / "Chromium"
    )

    assert _default_browser_executable("chromium", platform_name="darwin") == str(executable)


def test_container_profile_path_maps_to_bind_mounted_host_profile() -> None:
    resolved = _resolve_host_browser_profile_path(
        "/app/.host_browser_profiles/chromium"
    )

    assert resolved == Path(__file__).resolve().parents[1] / ".host_browser_profiles" / "chromium"


def test_chromium_launch_uses_resolved_executable_and_registers_session(monkeypatch) -> None:
    calls: list[list[str]] = []
    registry = LiveBrowserRegistry()

    monkeypatch.setattr(
        "app.host_manual_action_helper._resolve_browser_executable",
        lambda *_args, **_kwargs: "/Applications/Chromium.app/Contents/MacOS/Chromium",
    )
    monkeypatch.setattr(
        "app.host_manual_action_helper._ensure_non_default_browser_profile",
        lambda _profile: None,
    )

    def fake_launcher(command, **_kwargs):
        calls.append(command)
        return object()

    result = launch_browser_process(
        browser_channel="chromium",
        browser_profile_path="/tmp/jobsdb-profile",
        blocked_url="https://hk.jobsdb.com/",
        live_browser_registry=registry,
        port_reserver=lambda: 47801,
        process_launcher=fake_launcher,
    )

    assert calls == [
        [
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "--user-data-dir=/tmp/jobsdb-profile",
            "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=47801",
            "https://hk.jobsdb.com/",
        ]
    ]
    assert result["browser_channel"] == "chromium"
    assert result["debug_port"] == 47801


def test_chromium_process_name_matches_profile() -> None:
    assert _matching_profile_process_pids(
        browser_channel="chromium",
        browser_profile_path="/tmp/jobsdb-profile",
        processes=[
            {
                "pid": 42,
                "name": "Chromium",
                "command_line": "Chromium --user-data-dir=/tmp/jobsdb-profile",
            },
            {
                "pid": 43,
                "name": "Google Chrome",
                "command_line": "Google Chrome --user-data-dir=/tmp/other-profile",
            },
        ],
    ) == [42]


def test_open_browser_runs_sync_launcher_outside_async_event_loop() -> None:
    launcher_threads: list[int] = []
    main_thread = threading.get_ident()
    crawl_job_id = UUID("a7abf015-dffc-415a-80b4-aca43114daad")

    class _Repository:
        @staticmethod
        def get_crawl_job_by_id(_db, _crawl_job_id):
            return SimpleNamespace(
                status="manual_action_required",
                source_site="jobsdb",
                request_payload={},
            )

        @staticmethod
        def get_latest_manual_action_event(_db, _crawl_job_id):
            return SimpleNamespace(
                payload={
                    "manual_action": {
                        "source_site": "jobsdb",
                        "stage": "detail_page",
                        "classification": "waf_challenge",
                        "blocked_url": "https://hk.jobsdb.com/job/93444650",
                        "browser_channel": "chromium",
                        "browser_profile_path": "/tmp/jobsdb-profile",
                        "resume_supported": True,
                    }
                }
            )

    class _Session:
        def close(self):
            return None

    def fake_launcher(**kwargs):
        launcher_threads.append(threading.get_ident())
        return {
            "browser_channel": kwargs["browser_channel"],
            "browser_profile_path": kwargs["browser_profile_path"],
            "blocked_url": kwargs["blocked_url"],
            "debug_port": 47825,
            "status": "live",
        }

    registry = LiveBrowserRegistry()
    app = helper_module.build_host_manual_action_helper_app(
        session_factory=lambda: _Session(),
        crawl_job_repository=_Repository(),
        browser_launcher=fake_launcher,
        live_browser_registry=registry,
        session_reachability_probe=lambda _session: False,
    )

    response = TestClient(app).post(
        "/manual-actions/open-browser",
        json={"crawl_job_id": str(crawl_job_id)},
    )

    assert response.status_code == 200
    assert launcher_threads and launcher_threads[0] != main_thread
    assert response.json()["browser_channel"] == "chromium"
