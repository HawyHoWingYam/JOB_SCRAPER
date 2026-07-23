from __future__ import annotations

from pathlib import Path

from app.scraper.jobsdb_profile_recovery import (
    PROFILE_SCOPE_FIXED,
    _browser_name_matches,
    inspect_profile,
    reset_profile,
)


class _EmptyRegistry:
    def get(self, _profile_path):
        return None

    def remove(self, _profile_path):
        return None


def test_chromium_matches_macos_playwright_process_name() -> None:
    assert _browser_name_matches("Google Chrome for Testing", "chromium") is True
    assert _browser_name_matches("Microsoft Edge", "chromium") is False


def test_inspect_profile_recognizes_macos_chromium_process() -> None:
    profile_path = "/tmp/jobsdb-profile"

    liveness = inspect_profile(
        profile_path,
        browser_channel="chromium",
        process_lister=lambda: [
            {
                "pid": 123,
                "name": "Google Chrome for Testing",
                "cmdline": [
                    "Google Chrome for Testing",
                    f"--user-data-dir={profile_path}",
                ],
            }
        ],
        registry=_EmptyRegistry(),
    )

    assert liveness.state == "live"
    assert liveness.matching_processes == (123,)


def test_fixed_profile_reset_removes_only_singleton_markers(tmp_path: Path) -> None:
    profile_path = tmp_path / "fixed-profile"
    profile_path.mkdir()
    (profile_path / "SingletonLock").write_text("stale", encoding="utf-8")
    (profile_path / "SingletonSocket").write_text("stale", encoding="utf-8")
    keep_file = profile_path / "Cookies"
    keep_file.write_text("preserve", encoding="utf-8")

    result = reset_profile(
        profile_path,
        profile_scope=PROFILE_SCOPE_FIXED,
        browser_channel="chromium",
        process_lister=lambda: [],
        registry=_EmptyRegistry(),
    )

    assert result.available is True
    assert result.removed_lock_markers == ("SingletonLock", "SingletonSocket")
    assert keep_file.read_text(encoding="utf-8") == "preserve"
    assert profile_path.exists()


def test_profile_reset_fails_closed_when_process_liveness_is_unknown(tmp_path: Path) -> None:
    profile_path = tmp_path / "fixed-profile"
    profile_path.mkdir()
    marker = profile_path / "SingletonLock"
    marker.write_text("stale", encoding="utf-8")

    def unavailable_process_lister():
        raise RuntimeError("process inspection unavailable")

    result = reset_profile(
        profile_path,
        profile_scope=PROFILE_SCOPE_FIXED,
        browser_channel="chromium",
        process_lister=unavailable_process_lister,
        registry=_EmptyRegistry(),
    )

    assert result.available is False
    assert result.liveness.state == "unknown"
    assert marker.exists()
