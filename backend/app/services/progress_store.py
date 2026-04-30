"""
Shared Progress Store - Thread-safe singleton for scraping progress.
"""
import threading
from typing import Dict, Optional, TypeAlias
from datetime import datetime
from enum import Enum

from app.utils.time import utc_now

TERMINAL_SCRAPE_STATUSES = {"completed", "completed_with_ai_failures", "failed"}

ProgressKey: TypeAlias = int | str


class ScrapePhase(str, Enum):
    PENDING = "pending"
    COLLECTING_IDS = "collecting_ids"
    SCRAPING_DETAILS = "scraping_details"
    AI_RUNNING = "ai_running"
    COMPLETED_WITH_AI_FAILURES = "completed_with_ai_failures"
    COMPLETED = "completed"
    FAILED = "failed"


class ScrapeProgressStore:
    """Thread-safe singleton for sharing scrape progress across requests."""

    _instance: Optional["ScrapeProgressStore"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._progress: Dict[ProgressKey, Dict] = {}
                    cls._instance._data_lock = threading.Lock()
        return cls._instance

    def update(self, category_id: ProgressKey, data: Dict) -> None:
        """Update progress for a category."""
        with self._data_lock:
            if category_id not in self._progress:
                self._progress[category_id] = {}
            self._progress[category_id].update(data)
            self._progress[category_id]["updated_at"] = utc_now().isoformat()

    def get(self, category_id: ProgressKey) -> Optional[Dict]:
        """Get progress for a specific category."""
        with self._data_lock:
            return self._progress.get(category_id, {}).copy()

    def get_all(self) -> Dict[ProgressKey, Dict]:
        """Get all progress data."""
        with self._data_lock:
            return {k: v.copy() for k, v in self._progress.items()}

    def get_active(self) -> Dict[ProgressKey, Dict]:
        """Get only active (non-completed) progress."""
        with self._data_lock:
            return {
                k: v.copy() for k, v in self._progress.items()
                if v.get("status") not in TERMINAL_SCRAPE_STATUSES
            }

    def clear(self, category_id: ProgressKey) -> None:
        """Clear progress for a category."""
        with self._data_lock:
            self._progress.pop(category_id, None)

    def clear_completed(self, max_age_seconds: int = 60) -> None:
        """Clear completed/failed entries older than max_age_seconds."""
        with self._data_lock:
            now = utc_now()
            to_remove = []
            for cat_id, data in self._progress.items():
                if data.get("status") in TERMINAL_SCRAPE_STATUSES:
                    completed_at = data.get("completed_at")
                    if completed_at:
                        try:
                            completed_time = datetime.fromisoformat(completed_at)
                            if (now - completed_time).total_seconds() > max_age_seconds:
                                to_remove.append(cat_id)
                        except ValueError:
                            pass
            for cat_id in to_remove:
                del self._progress[cat_id]


def get_progress_store() -> ScrapeProgressStore:
    """Get the singleton progress store instance."""
    return ScrapeProgressStore()
