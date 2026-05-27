from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path, PureWindowsPath
import threading
from typing import Any, Callable


logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_browser_profile_path(browser_profile_path: str) -> str:
    raw_value = str(browser_profile_path or "").strip()
    if not raw_value:
        return ""
    normalized = raw_value.replace("/", "\\").rstrip("\\")
    return str(PureWindowsPath(normalized)).lower()


@dataclass(slots=True)
class LiveBrowserSession:
    browser_channel: str
    browser_profile_path: str
    blocked_url: str
    debug_port: int
    launched_at: datetime
    last_seen_at: datetime
    status: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["launched_at"] = self.launched_at.isoformat()
        payload["last_seen_at"] = self.last_seen_at.isoformat()
        return payload


class LiveBrowserRegistry:
    def __init__(self, *, storage_path: str | Path | None = None) -> None:
        self._storage_path = Path(storage_path) if storage_path else None
        self._sessions: dict[str, LiveBrowserSession] = {}
        self._lock = threading.Lock()
        with self._lock:
            self._load_unlocked()

    def _load_unlocked(self) -> None:
        if self._storage_path is None:
            return

        loaded_sessions: dict[str, LiveBrowserSession] = {}
        if not self._storage_path.exists():
            self._sessions = {}
            return

        try:
            raw_payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.exception("Failed to load live browser registry state from %s", self._storage_path)
            return

        session_rows: list[dict[str, Any]]
        if isinstance(raw_payload, dict):
            session_rows = [
                row for row in raw_payload.get("sessions", [])
                if isinstance(row, dict)
            ]
        elif isinstance(raw_payload, list):
            session_rows = [row for row in raw_payload if isinstance(row, dict)]
        else:
            session_rows = []

        for row in session_rows:
            browser_profile_path = str(row.get("browser_profile_path") or "").strip()
            normalized_profile_path = normalize_browser_profile_path(browser_profile_path)
            if not normalized_profile_path:
                continue

            launched_at = _parse_datetime(row.get("launched_at"))
            last_seen_at = _parse_datetime(row.get("last_seen_at"))
            loaded_sessions[normalized_profile_path] = LiveBrowserSession(
                browser_channel=str(row.get("browser_channel") or ""),
                browser_profile_path=browser_profile_path,
                blocked_url=str(row.get("blocked_url") or ""),
                debug_port=int(row.get("debug_port") or 0),
                launched_at=launched_at,
                last_seen_at=last_seen_at,
                status=str(row.get("status") or "stale"),
            )
        self._sessions = loaded_sessions

    def _save_unlocked(self) -> None:
        if self._storage_path is None:
            return

        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "sessions": [session.to_dict() for session in self._sessions.values()],
        }
        temp_path = self._storage_path.with_suffix(f"{self._storage_path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self._storage_path)

    def register(
        self,
        *,
        browser_channel: str,
        browser_profile_path: str,
        blocked_url: str,
        debug_port: int,
        status: str = "live",
    ) -> LiveBrowserSession:
        with self._lock:
            self._load_unlocked()
            normalized_profile_path = normalize_browser_profile_path(browser_profile_path)
            existing = self._sessions.get(normalized_profile_path)
            launched_at = existing.launched_at if existing is not None else _utcnow()
            session = LiveBrowserSession(
                browser_channel=browser_channel,
                browser_profile_path=browser_profile_path,
                blocked_url=blocked_url,
                debug_port=int(debug_port),
                launched_at=launched_at,
                last_seen_at=_utcnow(),
                status=status,
            )
            self._sessions[normalized_profile_path] = session
            self._save_unlocked()
            return session

    def get(self, browser_profile_path: str) -> LiveBrowserSession | None:
        with self._lock:
            self._load_unlocked()
            return self._sessions.get(normalize_browser_profile_path(browser_profile_path))

    def remove(self, browser_profile_path: str) -> LiveBrowserSession | None:
        with self._lock:
            self._load_unlocked()
            removed = self._sessions.pop(normalize_browser_profile_path(browser_profile_path), None)
            self._save_unlocked()
            return removed

    def touch(self, browser_profile_path: str, *, status: str = "live") -> LiveBrowserSession | None:
        with self._lock:
            self._load_unlocked()
            session = self._sessions.get(normalize_browser_profile_path(browser_profile_path))
            if session is None:
                return None
            session.last_seen_at = _utcnow()
            session.status = status
            self._save_unlocked()
            return session

    def mark_stale(self, browser_profile_path: str) -> LiveBrowserSession | None:
        return self.touch(browser_profile_path, status="stale")

    def list_sessions(self) -> list[LiveBrowserSession]:
        with self._lock:
            self._load_unlocked()
            return list(self._sessions.values())

    def revalidate(self, reachability_probe: Callable[[LiveBrowserSession], bool]) -> dict[str, int]:
        with self._lock:
            self._load_unlocked()
            live_count = 0
            stale_count = 0
            for session in self._sessions.values():
                if reachability_probe(session):
                    session.status = "live"
                    session.last_seen_at = _utcnow()
                    live_count += 1
                else:
                    session.status = "stale"
                    stale_count += 1
            self._save_unlocked()
            return {
                "total_sessions": len(self._sessions),
                "live_sessions": live_count,
                "stale_sessions": stale_count,
            }


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return _utcnow()
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return _utcnow()


_DEFAULT_REGISTRY: LiveBrowserRegistry | None = None


def get_live_browser_registry() -> LiveBrowserRegistry:
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        from app.config import settings

        _DEFAULT_REGISTRY = LiveBrowserRegistry(
            storage_path=settings.manual_action_registry_state_path,
        )
    return _DEFAULT_REGISTRY
