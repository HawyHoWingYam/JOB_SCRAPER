from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.scraper import ctgoodjobs_browser_page_scraper as scraper_module
from app.scraper.ctgoodjobs_browser_page_scraper import CTGoodJobsBrowserPageScraper
from app.scraper.manual_action import ManualActionRequiredError


class _FakePage:
    def wait_for_timeout(self, _milliseconds: int) -> None:
        return None


class _FakeContext:
    def __init__(self) -> None:
        self.pages = [_FakePage()]

    def set_default_navigation_timeout(self, _timeout_ms: int) -> None:
        return None

    def close(self) -> None:
        return None


class _FakePlaywright:
    chromium = object()

    def stop(self) -> None:
        return None


class _FakeSyncPlaywright:
    @staticmethod
    def start() -> _FakePlaywright:
        return _FakePlaywright()


@pytest.mark.asyncio
async def test_ctgoodjobs_headless_fresh_run_uses_task_owned_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = _FakeContext()
    launches: list[dict[str, object]] = []
    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright",
        lambda: _FakeSyncPlaywright(),
    )

    def fake_launch(_chromium, **kwargs):
        launches.append(kwargs)
        return SimpleNamespace(
            context=context,
            attempted_fallback=False,
            requested_channel="chromium",
            resolved_channel="chromium",
        )

    monkeypatch.setattr(
        scraper_module,
        "launch_persistent_context_with_fallback",
        fake_launch,
    )
    monkeypatch.setattr(
        scraper_module,
        "delete_owned_profile",
        lambda *_args, **_kwargs: SimpleNamespace(available=True),
    )

    scraper = CTGoodJobsBrowserPageScraper(
        request_payload={
            "crawl_job_id": "ct-run-1",
            "crawl_mode": "headless",
            "resume_strategy": "fresh_profile",
        },
        user_data_dir=str(tmp_path),
    )

    async with scraper:
        pass

    assert launches[0]["headless"] is True
    assert launches[0]["user_data_dir"] == str(tmp_path / "tasks" / "ct-run-1")


def test_ctgoodjobs_catalog_validation_uses_operation_owned_profile(
    tmp_path: Path,
) -> None:
    scraper = CTGoodJobsBrowserPageScraper(
        request_payload={
            "crawl_mode": "headless",
            "profile_operation_id": "catalog-1",
        },
        user_data_dir=str(tmp_path),
    )

    assert scraper._resolve_user_data_dir() == tmp_path / "operations" / "catalog-1"


def test_ctgoodjobs_process_singleton_becomes_profile_recovery() -> None:
    scraper = CTGoodJobsBrowserPageScraper(
        request_payload={"crawl_job_id": "ct-run-2", "crawl_mode": "headless"},
    )

    with pytest.raises(ManualActionRequiredError) as raised:
        scraper._raise_if_profile_in_use(
            RuntimeError(
                "BrowserType.launch_persistent_context: Failed to create a "
                "ProcessSingleton for your profile directory. This usually means "
                "that the profile is already in use by another instance of Chromium."
            )
        )

    assert raised.value.stage == "browser_profile_in_use"
    assert raised.value.action_type == "profile_recovery"
    assert raised.value.resume_context["profile_scope"] == "fresh_profile"
    assert raised.value.resume_context["browser_profile_path"].endswith(
        "/tasks/ct-run-2"
    )


@pytest.mark.asyncio
async def test_ctgoodjobs_resume_retries_process_singleton_only_once_after_safe_reset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = _FakeContext()
    launches: list[dict[str, object]] = []
    cleanup_calls: list[Path] = []
    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright",
        lambda: _FakeSyncPlaywright(),
    )

    def fake_launch(_chromium, **kwargs):
        launches.append(kwargs)
        if len(launches) == 1:
            raise RuntimeError(
                "BrowserType.launch_persistent_context: Failed to create a "
                "ProcessSingleton for your profile directory"
            )
        return SimpleNamespace(
            context=context,
            attempted_fallback=False,
            requested_channel="chromium",
            resolved_channel="chromium",
        )

    monkeypatch.setattr(
        scraper_module,
        "launch_persistent_context_with_fallback",
        fake_launch,
    )

    def fake_cleanup(path, **_kwargs):
        cleanup_calls.append(Path(path))
        return SimpleNamespace(
            available=True,
            liveness=SimpleNamespace(state="dead"),
            reason=None,
        )

    monkeypatch.setattr(scraper_module, "cleanup_profile", fake_cleanup)
    monkeypatch.setattr(scraper_module, "delete_owned_profile", fake_cleanup)

    scraper = CTGoodJobsBrowserPageScraper(
        request_payload={
            "crawl_job_id": "ct-resume-1",
            "crawl_mode": "headless",
            "resume_strategy": "fresh_profile",
            "is_resume": True,
        },
        user_data_dir=str(tmp_path),
    )

    async with scraper:
        pass

    assert len(launches) == 2
    assert all(call["headless"] is True for call in launches)
    assert len(cleanup_calls) == 2
