from __future__ import annotations

from pathlib import Path

import pytest

from app.scraper.browser_profile_recovery import (
    PROFILE_SCOPE_FIXED,
    PROFILE_SCOPE_OPERATION,
    _browser_name_matches,
    delete_owned_profile,
    inspect_profile,
    is_profile_lock_error,
    operation_profile_path,
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


def test_inspect_profile_ignores_dead_chromium_zombies_without_cmdline() -> None:
    liveness = inspect_profile(
        "/tmp/browser-profile",
        browser_channel="chromium",
        process_lister=lambda: [
            {
                "pid": 456,
                "name": "chrome",
                "cmdline": None,
                "status": "zombie",
            }
        ],
        registry=_EmptyRegistry(),
    )

    assert liveness.state == "dead"


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
        configured_path=str(profile_path),
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
        configured_path=str(profile_path),
        process_lister=unavailable_process_lister,
        registry=_EmptyRegistry(),
    )

    assert result.available is False
    assert result.liveness.state == "unknown"
    assert marker.exists()


@pytest.mark.parametrize(
    "message",
    [
        "BrowserType.launch_persistent_context: Target page, context or browser has been closed",
        (
            "BrowserType.launch_persistent_context: Failed to create a ProcessSingleton "
            "for your profile directory. This usually means that the profile is already in use."
        ),
        (
            "Unable to launch headed browser with channel 'chromium': "
            "BrowserType.launch_persistent_context: Failed to create /tmp/profile/SingletonLock: "
            "File exists (17)"
        ),
    ],
)
def test_profile_lock_recognizes_real_and_wrapped_playwright_errors(message: str) -> None:
    assert is_profile_lock_error(RuntimeError(message)) is True


def test_profile_lock_does_not_relabel_unrelated_launch_failure() -> None:
    assert (
        is_profile_lock_error(
            RuntimeError(
                "BrowserType.launch_persistent_context: Missing X server or $DISPLAY"
            )
        )
        is False
    )


def test_operation_profile_is_owned_and_recreated_without_touching_fixed_root(
    tmp_path: Path,
) -> None:
    profile_path = operation_profile_path("catalog-validation-1", configured_path=str(tmp_path))
    profile_path.mkdir(parents=True)
    (profile_path / "Cookies").write_text("temporary", encoding="utf-8")
    fixed_cookie = tmp_path / "Cookies"
    fixed_cookie.write_text("preserve", encoding="utf-8")

    result = reset_profile(
        profile_path,
        profile_scope=PROFILE_SCOPE_OPERATION,
        browser_channel="chromium",
        configured_path=str(tmp_path),
        process_lister=lambda: [],
        registry=_EmptyRegistry(),
    )

    assert result.available is True
    assert result.recreated is True
    assert profile_path.is_dir()
    assert list(profile_path.iterdir()) == []
    assert fixed_cookie.read_text(encoding="utf-8") == "preserve"


def test_terminal_cleanup_deletes_only_owned_operation_profile(tmp_path: Path) -> None:
    profile_path = operation_profile_path("catalog-validation-2", configured_path=str(tmp_path))
    profile_path.mkdir(parents=True)
    fixed_cookie = tmp_path / "Cookies"
    fixed_cookie.write_text("preserve", encoding="utf-8")

    result = delete_owned_profile(
        profile_path,
        profile_scope=PROFILE_SCOPE_OPERATION,
        browser_channel="chromium",
        configured_path=str(tmp_path),
        process_lister=lambda: [],
        registry=_EmptyRegistry(),
    )

    assert result.available is True
    assert not profile_path.exists()
    assert fixed_cookie.read_text(encoding="utf-8") == "preserve"


def test_fresh_profile_path_rejects_path_traversal(tmp_path: Path) -> None:
    from app.scraper.browser_profile_recovery import fresh_profile_path

    with pytest.raises(ValueError, match="path segment"):
        fresh_profile_path("../../outside/tasks/victim", configured_path=str(tmp_path))


def test_terminal_cleanup_rejects_profile_under_unrelated_root(tmp_path: Path) -> None:
    configured_root = tmp_path / "configured"
    unrelated_profile = tmp_path / "unrelated" / "operations" / "victim"
    unrelated_profile.mkdir(parents=True)
    keep_file = unrelated_profile / "Cookies"
    keep_file.write_text("preserve", encoding="utf-8")

    result = delete_owned_profile(
        unrelated_profile,
        profile_scope=PROFILE_SCOPE_OPERATION,
        browser_channel="chromium",
        configured_path=str(configured_root),
        process_lister=lambda: [],
        registry=_EmptyRegistry(),
    )

    assert result.available is False
    assert result.reason == "temporary_profile_not_owned"
    assert keep_file.read_text(encoding="utf-8") == "preserve"


def test_terminal_cleanup_rejects_symlinked_owner_directory(tmp_path: Path) -> None:
    configured_root = tmp_path / "configured"
    external_owner = tmp_path / "external-operations"
    external_profile = external_owner / "victim"
    external_profile.mkdir(parents=True)
    configured_root.mkdir()
    (configured_root / "operations").symlink_to(external_owner, target_is_directory=True)
    keep_file = external_profile / "Cookies"
    keep_file.write_text("preserve", encoding="utf-8")

    result = delete_owned_profile(
        configured_root / "operations" / "victim",
        profile_scope=PROFILE_SCOPE_OPERATION,
        browser_channel="chromium",
        configured_path=str(configured_root),
        process_lister=lambda: [],
        registry=_EmptyRegistry(),
    )

    assert result.available is False
    assert result.reason == "temporary_profile_not_owned"
    assert keep_file.read_text(encoding="utf-8") == "preserve"
