"""Source-aware category registry.

Task 2 scope:
- JobsDB categories are served from the existing in-repo registry.
- CTgoodjobs categories are parsed via the existing research probe parser.
- CTgoodjobs registry fetch is protected by a simple in-memory TTL cache to avoid
  live-fetching on every API request.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Literal

from app.scraper.categories import get_all_categories
from app.scraper.ctgoodjobs.category_registry import (
    CTGOODJOBS_BASE_URL,
    get_static_ctgoodjobs_categories,
    parse_category_registry,
)
from app.scraper.ctgoodjobs.list_scraper import fetch_category_page_html

SourceSite = Literal["jobsdb", "ctgoodjobs"]


def _normalize_source_site(value: str | None) -> str:
    return (value or "jobsdb").strip().lower()


def _fetch_ctgoodjobs_registry_html() -> str:
    """Fetch CTgoodjobs registry HTML.

    Kept as a standalone function so tests can monkeypatch it to avoid network.
    """

    return asyncio.run(fetch_category_page_html(f"{CTGOODJOBS_BASE_URL}/jobs"))


@dataclass
class _TtlCache:
    ttl_s: float
    loaded_at_s: float | None = None
    value: Any | None = None

    def get(self) -> Any | None:
        if self.loaded_at_s is None:
            return None
        if (time.time() - self.loaded_at_s) >= self.ttl_s:
            return None
        return self.value

    def set(self, value: Any) -> None:
        self.value = value
        self.loaded_at_s = time.time()


class SourceCategoryRegistry:
    def __init__(self, *, ctgoodjobs_ttl_s: float = 60.0 * 60.0):
        self._jobsdb_categories: list[dict[str, Any]] | None = None
        self._ctgoodjobs_cache = _TtlCache(ttl_s=ctgoodjobs_ttl_s)
        self._ctgoodjobs_last_value: list[dict[str, Any]] | None = None

    def list_categories(self, *, source_site: str | None = None) -> list[dict[str, Any]]:
        normalized = _normalize_source_site(source_site)
        if normalized == "jobsdb":
            if isinstance(self._jobsdb_categories, list):
                return self._jobsdb_categories

            payload = [
                {
                    "id": cat.id,
                    "name": cat.name,
                    "slug": cat.slug,
                    "source_site": "jobsdb",
                }
                for cat in get_all_categories()
            ]
            self._jobsdb_categories = payload
            return payload

        if normalized == "ctgoodjobs":
            cached = self._ctgoodjobs_cache.get()
            if isinstance(cached, list):
                return cached

            try:
                html = _fetch_ctgoodjobs_registry_html()
            except Exception:
                if isinstance(self._ctgoodjobs_last_value, list) and self._ctgoodjobs_last_value:
                    return self._ctgoodjobs_last_value
                payload = [
                    {
                        "id": category.source_classification_id,
                        "name": category.name,
                        "slug": category.slug,
                        "source_site": "ctgoodjobs",
                    }
                    for category in get_static_ctgoodjobs_categories()
                ]
                self._ctgoodjobs_last_value = payload
                return payload
            if not html.strip():
                if isinstance(self._ctgoodjobs_last_value, list) and self._ctgoodjobs_last_value:
                    return self._ctgoodjobs_last_value
                payload = [
                    {
                        "id": category.source_classification_id,
                        "name": category.name,
                        "slug": category.slug,
                        "source_site": "ctgoodjobs",
                    }
                    for category in get_static_ctgoodjobs_categories()
                ]
                self._ctgoodjobs_last_value = payload
                return payload

            registry = parse_category_registry(html)
            if not registry:
                if isinstance(self._ctgoodjobs_last_value, list) and self._ctgoodjobs_last_value:
                    return self._ctgoodjobs_last_value
                payload = [
                    {
                        "id": category.source_classification_id,
                        "name": category.name,
                        "slug": category.slug,
                        "source_site": "ctgoodjobs",
                    }
                    for category in get_static_ctgoodjobs_categories()
                ]
                self._ctgoodjobs_last_value = payload
                return payload

            payload = [
                {
                    "id": category.source_classification_id,
                    "name": category.name,
                    "slug": category.slug,
                    "source_site": "ctgoodjobs",
                }
                for category in registry
            ]
            if not payload:
                # Defensive: don't cache/return an "empty success" payload.
                raise RuntimeError("CTgoodjobs registry produced empty payload")
            self._ctgoodjobs_cache.set(payload)
            self._ctgoodjobs_last_value = payload
            return payload

        raise ValueError(f"Unsupported source_site: {normalized}")


_registry: SourceCategoryRegistry | None = None


def get_source_category_registry() -> SourceCategoryRegistry:
    global _registry
    if _registry is None:
        _registry = SourceCategoryRegistry()
    return _registry
