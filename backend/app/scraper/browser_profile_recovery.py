from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import os
from pathlib import Path
import shutil
import time
from typing import Any, Callable, Literal

from app.config import settings
from app.manual_actions.live_browser_registry import get_live_browser_registry
from app.scraper.manual_action import resolve_manual_action_cdp_connect_host


PROFILE_LOCK_MARKERS = ("SingletonLock", "SingletonSocket", "SingletonCookie")
PROFILE_SCOPE_FRESH = "fresh_profile"
PROFILE_SCOPE_OPERATION = "operation_profile"
PROFILE_SCOPE_FIXED = "fixed_profile"
LIVENESS_LIVE = "live"
LIVENESS_DEAD = "dead"
LIVENESS_UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ProfileLiveness:
    state: Literal["live", "dead", "unknown"]
    matching_processes: tuple[int, ...] = ()
    registry_session: bool = False
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ProfileResetResult:
    available: bool
    profile_path: str
    profile_scope: str
    liveness: ProfileLiveness
    removed_lock_markers: tuple[str, ...] = ()
    recreated: bool = False
    reason: str | None = None


def normalize_profile_path(value: str | os.PathLike[str] | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return os.path.normcase(os.path.normpath(os.path.expanduser(raw))).casefold()


def _profile_root(
    *,
    configured_path: str | None = None,
    browser_channel: str | None = None,
) -> Path:
    configured = str(
        configured_path or settings.jobsdb_headed_browser_user_data_dir or ""
    ).strip()
    if configured:
        return Path(configured).expanduser()
    return Path(".playwright") / (
        str(browser_channel or settings.jobsdb_headed_browser_channel).strip()
        or "chromium"
    )


def fresh_profile_path(
    crawl_job_id: str | None,
    *,
    configured_path: str | None = None,
    browser_channel: str | None = None,
) -> Path:
    root = _profile_root(
        configured_path=configured_path,
        browser_channel=browser_channel,
    )
    normalized_id = str(crawl_job_id or "").strip()
    if not normalized_id:
        return root
    if normalized_id in {".", ".."} or Path(normalized_id).name != normalized_id:
        raise ValueError("crawl_job_id must be a non-empty path segment")
    return root / "tasks" / normalized_id


def operation_profile_path(
    operation_id: str,
    *,
    configured_path: str | None = None,
    browser_channel: str | None = None,
) -> Path:
    root = _profile_root(
        configured_path=configured_path,
        browser_channel=browser_channel,
    )
    normalized_id = str(operation_id or "").strip()
    if not normalized_id or normalized_id in {".", ".."}:
        raise ValueError("operation_id must be a non-empty path segment")
    if Path(normalized_id).name != normalized_id:
        raise ValueError("operation_id must not contain path separators")
    return root / "operations" / normalized_id


def _owned_profile_path(
    profile_path: str | os.PathLike[str] | None,
    *,
    owner_directory: Literal["tasks", "operations"],
    configured_path: str | None = None,
    browser_channel: str | None = None,
) -> Path | None:
    raw_path = str(profile_path or "").strip()
    if not raw_path:
        return None

    candidate = Path(raw_path).expanduser().absolute()
    if not candidate.name or candidate.name in {".", ".."}:
        return None

    configured_root = _profile_root(
        configured_path=configured_path,
        browser_channel=browser_channel,
    ).absolute()
    expected_owner = configured_root / owner_directory
    if candidate.parent != expected_owner:
        return None

    resolved_root = configured_root.resolve(strict=False)
    resolved_owner = expected_owner.resolve(strict=False)
    if resolved_owner != resolved_root / owner_directory:
        return None

    resolved_candidate = candidate.resolve(strict=False)
    if resolved_candidate.parent != resolved_owner:
        return None
    return resolved_candidate


def is_task_owned_profile(
    profile_path: str | os.PathLike[str] | None,
    *,
    configured_path: str | None = None,
    browser_channel: str | None = None,
) -> bool:
    return (
        _owned_profile_path(
            profile_path,
            owner_directory="tasks",
            configured_path=configured_path,
            browser_channel=browser_channel,
        )
        is not None
    )


def is_operation_owned_profile(
    profile_path: str | os.PathLike[str] | None,
    *,
    configured_path: str | None = None,
    browser_channel: str | None = None,
) -> bool:
    return (
        _owned_profile_path(
            profile_path,
            owner_directory="operations",
            configured_path=configured_path,
            browser_channel=browser_channel,
        )
        is not None
    )


def _fixed_profile_path(
    profile_path: str | os.PathLike[str] | None,
    *,
    configured_path: str | None = None,
    browser_channel: str | None = None,
) -> Path | None:
    raw_path = str(profile_path or "").strip()
    if not raw_path:
        return None
    candidate = Path(raw_path).expanduser().absolute().resolve(strict=False)
    configured_root = (
        _profile_root(
            configured_path=configured_path,
            browser_channel=browser_channel,
        )
        .absolute()
        .resolve(strict=False)
    )
    return candidate if candidate == configured_root else None


def is_fixed_profile(
    profile_path: str | os.PathLike[str] | None,
    *,
    configured_path: str | None = None,
    browser_channel: str | None = None,
) -> bool:
    return (
        _fixed_profile_path(
            profile_path,
            configured_path=configured_path,
            browser_channel=browser_channel,
        )
        is not None
    )


def is_profile_lock_error(exc: Exception) -> bool:
    message = str(exc or "")
    if "launch_persistent_context" not in message:
        return False
    return any(
        marker in message
        for marker in (
            "Target page, context or browser has been closed",
            "Failed to create a ProcessSingleton for your profile directory",
            "SingletonLock: File exists",
        )
    )


def _browser_name_matches(name: str, browser_channel: str | None) -> bool:
    normalized_name = str(name or "").strip().lower()
    normalized_name = normalized_name.removesuffix(".exe").removesuffix(".app")
    normalized_channel = str(browser_channel or "").strip().lower()
    if normalized_channel in {"msedge", "edge"}:
        return normalized_name in {"msedge", "microsoft edge"}
    if normalized_channel == "chrome":
        return normalized_name in {"chrome", "google chrome", "google chrome for testing"}
    if normalized_channel == "chromium":
        return normalized_name in {
            "chromium",
            "chromium-browser",
            "chrome",
            "google chrome",
            "google chrome for testing",
        }
    return normalized_name in {
        "msedge",
        "microsoft edge",
        "chrome",
        "google chrome",
        "google chrome for testing",
        "chromium",
        "chromium-browser",
    }


def _command_profile_path(command_line: list[str] | tuple[str, ...] | None) -> str:
    values = [str(item) for item in (command_line or ())]
    for index, value in enumerate(values):
        normalized = value.strip()
        if normalized.startswith("--user-data-dir="):
            return normalize_profile_path(normalized.split("=", 1)[1].strip('"'))
        if normalized == "--user-data-dir" and index + 1 < len(values):
            return normalize_profile_path(values[index + 1].strip('"'))
    return ""


def _default_process_lister() -> list[dict[str, Any]]:
    try:
        import psutil
    except ImportError as exc:  # pragma: no cover - runtime dependency
        raise RuntimeError("Browser process inspection is unavailable") from exc

    processes: list[dict[str, Any]] = []
    for process in psutil.process_iter(["pid", "name", "cmdline", "status"]):
        try:
            info = process.info
        except (psutil.AccessDenied, psutil.NoSuchProcess) as exc:
            raise RuntimeError("Browser process inspection is incomplete") from exc
        processes.append(info)
    return processes


def _matching_processes(
    profile_path: str,
    *,
    browser_channel: str | None,
    process_lister: Callable[[], list[dict[str, Any]]] = _default_process_lister,
) -> tuple[int, ...]:
    normalized_profile = normalize_profile_path(profile_path)
    processes = process_lister()
    matched: list[int] = []
    for process in processes:
        if not _browser_name_matches(str(process.get("name") or ""), browser_channel):
            continue
        if str(process.get("status") or "").strip().lower() == "zombie":
            continue
        command_line = process.get("cmdline")
        if command_line is None:
            raise RuntimeError("Browser process command line is unavailable")
        if _command_profile_path(command_line) == normalized_profile:
            matched.append(int(process.get("pid")))
    return tuple(sorted(set(matched)))


def _probe_registry_session(session: Any) -> Literal["live", "dead", "unknown"]:
    debug_port = int(getattr(session, "debug_port", 0) or 0)
    if debug_port <= 0:
        return LIVENESS_DEAD
    host = resolve_manual_action_cdp_connect_host(
        settings.manual_action_cdp_host or settings.manual_action_helper_host
    )
    try:
        import json
        from urllib.request import urlopen

        with urlopen(
            f"http://{host}:{debug_port}/json/version",
            timeout=1.0,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return (
            LIVENESS_LIVE
            if payload.get("Browser") or payload.get("webSocketDebuggerUrl")
            else LIVENESS_DEAD
        )
    except ConnectionRefusedError:
        return LIVENESS_DEAD
    except (OSError, TimeoutError, ValueError, UnicodeError):
        return LIVENESS_UNKNOWN


def inspect_profile(
    profile_path: str | os.PathLike[str],
    *,
    browser_channel: str | None = None,
    process_lister: Callable[[], list[dict[str, Any]]] = _default_process_lister,
    registry=None,
) -> ProfileLiveness:
    path = str(profile_path)
    try:
        matching = _matching_processes(
            path,
            browser_channel=browser_channel or settings.jobsdb_headed_browser_channel,
            process_lister=process_lister,
        )
    except Exception:
        return ProfileLiveness(
            state=LIVENESS_UNKNOWN,
            reason="browser_process_inspection_unavailable",
        )
    if matching:
        return ProfileLiveness(
            state=LIVENESS_LIVE,
            matching_processes=matching,
            reason="matching_browser_process",
        )

    registry = registry or get_live_browser_registry()
    try:
        session = registry.get(path)
    except Exception:
        return ProfileLiveness(
            state=LIVENESS_UNKNOWN,
            reason="live_browser_registry_unavailable",
        )
    if session is None:
        return ProfileLiveness(state=LIVENESS_DEAD, reason="no_active_browser_session")

    registry_state = _probe_registry_session(session)
    if registry_state == LIVENESS_LIVE:
        return ProfileLiveness(
            state=LIVENESS_LIVE,
            registry_session=True,
            reason="reachable_live_browser_session",
        )
    if registry_state == LIVENESS_UNKNOWN:
        return ProfileLiveness(
            state=LIVENESS_UNKNOWN,
            registry_session=True,
            reason="browser_session_reachability_unknown",
        )
    return ProfileLiveness(
        state=LIVENESS_DEAD,
        registry_session=True,
        reason="stale_browser_session",
    )


def _remove_lock_markers(profile_path: Path) -> tuple[str, ...]:
    removed: list[str] = []
    for marker in PROFILE_LOCK_MARKERS:
        marker_path = profile_path / marker
        try:
            marker_path.unlink()
        except FileNotFoundError:
            continue
        removed.append(marker)
    return tuple(removed)


def reset_profile(
    profile_path: str | os.PathLike[str],
    *,
    profile_scope: str,
    browser_channel: str | None = None,
    configured_path: str | None = None,
    process_lister: Callable[[], list[dict[str, Any]]] = _default_process_lister,
    registry=None,
) -> ProfileResetResult:
    path = Path(profile_path).expanduser()
    owned_path = (
        _owned_profile_path(
            path,
            owner_directory="tasks",
            configured_path=configured_path,
            browser_channel=browser_channel,
        )
        if profile_scope == PROFILE_SCOPE_FRESH
        else _owned_profile_path(
            path,
            owner_directory="operations",
            configured_path=configured_path,
            browser_channel=browser_channel,
        )
        if profile_scope == PROFILE_SCOPE_OPERATION
        else _fixed_profile_path(
            path,
            configured_path=configured_path,
            browser_channel=browser_channel,
        )
        if profile_scope == PROFILE_SCOPE_FIXED
        else None
    )
    if owned_path is None:
        return ProfileResetResult(
            available=False,
            profile_path=str(path),
            profile_scope=profile_scope,
            liveness=ProfileLiveness(
                state=LIVENESS_UNKNOWN,
                reason="profile_ownership_unverified",
            ),
            reason=(
                "temporary_profile_not_owned"
                if profile_scope in {PROFILE_SCOPE_FRESH, PROFILE_SCOPE_OPERATION}
                else "fixed_profile_not_configured"
            ),
        )
    liveness = inspect_profile(
        path,
        browser_channel=browser_channel,
        process_lister=process_lister,
        registry=registry,
    )
    if liveness.state != LIVENESS_DEAD:
        return ProfileResetResult(
            available=False,
            profile_path=str(path),
            profile_scope=profile_scope,
            liveness=liveness,
            reason=(
                "profile_is_in_use"
                if liveness.state == LIVENESS_LIVE
                else "profile_liveness_unknown"
            ),
        )

    registry = registry or get_live_browser_registry()
    if profile_scope in {PROFILE_SCOPE_FRESH, PROFILE_SCOPE_OPERATION}:
        if owned_path.exists():
            shutil.rmtree(owned_path)
        owned_path.mkdir(parents=True, exist_ok=True)
        try:
            registry.remove(str(path))
        except Exception:
            pass
        return ProfileResetResult(
            available=True,
            profile_path=str(path),
            profile_scope=profile_scope,
            liveness=liveness,
            recreated=True,
        )

    removed = _remove_lock_markers(owned_path)
    try:
        registry.remove(str(path))
    except Exception:
        pass
    return ProfileResetResult(
        available=True,
        profile_path=str(path),
        profile_scope=PROFILE_SCOPE_FIXED,
        liveness=liveness,
        removed_lock_markers=removed,
    )


def cleanup_profile(
    profile_path: str | os.PathLike[str],
    *,
    profile_scope: str,
    browser_channel: str | None = None,
    configured_path: str | None = None,
    process_lister: Callable[[], list[dict[str, Any]]] = _default_process_lister,
) -> ProfileResetResult:
    return reset_profile(
        profile_path,
        profile_scope=profile_scope,
        browser_channel=browser_channel,
        configured_path=configured_path,
        process_lister=process_lister,
    )


def delete_owned_profile(
    profile_path: str | os.PathLike[str],
    *,
    profile_scope: str,
    browser_channel: str | None = None,
    configured_path: str | None = None,
    process_lister: Callable[[], list[dict[str, Any]]] = _default_process_lister,
    registry=None,
) -> ProfileResetResult:
    path = Path(profile_path).expanduser()
    owned_path = (
        _owned_profile_path(
            path,
            owner_directory="tasks",
            configured_path=configured_path,
            browser_channel=browser_channel,
        )
        if profile_scope == PROFILE_SCOPE_FRESH
        else _owned_profile_path(
            path,
            owner_directory="operations",
            configured_path=configured_path,
            browser_channel=browser_channel,
        )
        if profile_scope == PROFILE_SCOPE_OPERATION
        else None
    )
    if owned_path is None:
        return ProfileResetResult(
            available=False,
            profile_path=str(path),
            profile_scope=profile_scope,
            liveness=ProfileLiveness(
                state=LIVENESS_UNKNOWN,
                reason="profile_ownership_unverified",
            ),
            reason="temporary_profile_not_owned",
        )
    liveness = inspect_profile(
        path,
        browser_channel=browser_channel,
        process_lister=process_lister,
        registry=registry,
    )
    if liveness.state != LIVENESS_DEAD:
        return ProfileResetResult(
            available=False,
            profile_path=str(path),
            profile_scope=profile_scope,
            liveness=liveness,
            reason=(
                "profile_is_in_use"
                if liveness.state == LIVENESS_LIVE
                else "profile_liveness_unknown"
            ),
        )
    if owned_path.exists():
        shutil.rmtree(owned_path)
    registry = registry or get_live_browser_registry()
    try:
        registry.remove(str(path))
    except Exception:
        pass
    return ProfileResetResult(
        available=True,
        profile_path=str(path),
        profile_scope=profile_scope,
        liveness=liveness,
    )


def cleanup_orphan_profiles(
    *,
    configured_path: str | None = None,
    browser_channel: str | None = None,
    ttl: timedelta = timedelta(hours=24),
    now: float | None = None,
    process_lister: Callable[[], list[dict[str, Any]]] = _default_process_lister,
) -> tuple[str, ...]:
    profile_root = _profile_root(
        configured_path=configured_path,
        browser_channel=browser_channel,
    ).absolute()
    resolved_profile_root = profile_root.resolve(strict=False)
    cutoff = (time.time() if now is None else float(now)) - ttl.total_seconds()
    removed: list[str] = []
    for owner_directory in ("tasks", "operations"):
        root = profile_root / owner_directory
        resolved_owner_root = root.resolve(strict=False)
        if resolved_owner_root != resolved_profile_root / owner_directory:
            continue
        if not resolved_owner_root.exists():
            continue
        for candidate in resolved_owner_root.iterdir():
            owned_candidate = _owned_profile_path(
                candidate,
                owner_directory=owner_directory,
                configured_path=str(profile_root),
                browser_channel=browser_channel,
            )
            if owned_candidate is None or not owned_candidate.is_dir():
                continue
            try:
                if owned_candidate.stat().st_mtime > cutoff:
                    continue
            except OSError:
                continue
            liveness = inspect_profile(
                owned_candidate,
                browser_channel=browser_channel,
                process_lister=process_lister,
            )
            if liveness.state != LIVENESS_DEAD:
                continue
            try:
                shutil.rmtree(owned_candidate)
            except OSError:
                continue
            removed.append(str(owned_candidate))
    return tuple(removed)
