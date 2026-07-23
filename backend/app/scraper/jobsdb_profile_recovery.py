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
    return root / "tasks" / normalized_id


def is_task_owned_profile(profile_path: str | os.PathLike[str] | None) -> bool:
    normalized = normalize_profile_path(profile_path)
    if not normalized:
        return False
    path = Path(normalized)
    if path.parent.name != "tasks":
        return False
    return bool(path.name)


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
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
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
    process_lister: Callable[[], list[dict[str, Any]]] = _default_process_lister,
    registry=None,
) -> ProfileResetResult:
    path = Path(profile_path).expanduser()
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
    task_owned = is_task_owned_profile(path)
    if profile_scope == PROFILE_SCOPE_FRESH and not task_owned:
        return ProfileResetResult(
            available=False,
            profile_path=str(path),
            profile_scope=profile_scope,
            liveness=liveness,
            reason="fresh_profile_not_task_owned",
        )
    if profile_scope == PROFILE_SCOPE_FRESH:
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
        try:
            registry.remove(str(path))
        except Exception:
            pass
        return ProfileResetResult(
            available=True,
            profile_path=str(path),
            profile_scope=PROFILE_SCOPE_FRESH,
            liveness=liveness,
            recreated=True,
        )

    removed = _remove_lock_markers(path)
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
    process_lister: Callable[[], list[dict[str, Any]]] = _default_process_lister,
) -> ProfileResetResult:
    return reset_profile(
        profile_path,
        profile_scope=profile_scope,
        browser_channel=browser_channel,
        process_lister=process_lister,
    )


def cleanup_orphan_profiles(
    *,
    configured_path: str | None = None,
    browser_channel: str | None = None,
    ttl: timedelta = timedelta(hours=24),
    now: float | None = None,
    process_lister: Callable[[], list[dict[str, Any]]] = _default_process_lister,
) -> tuple[str, ...]:
    root = _profile_root(
        configured_path=configured_path,
        browser_channel=browser_channel,
    ) / "tasks"
    if not root.exists():
        return ()
    cutoff = (time.time() if now is None else float(now)) - ttl.total_seconds()
    removed: list[str] = []
    for candidate in root.iterdir():
        if not candidate.is_dir():
            continue
        try:
            if candidate.stat().st_mtime > cutoff:
                continue
        except OSError:
            continue
        liveness = inspect_profile(
            candidate,
            browser_channel=browser_channel,
            process_lister=process_lister,
        )
        if liveness.state != LIVENESS_DEAD:
            continue
        try:
            shutil.rmtree(candidate)
        except OSError:
            continue
        removed.append(str(candidate))
    return tuple(removed)
