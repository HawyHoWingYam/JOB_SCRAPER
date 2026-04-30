"""Source-aware category registry.

Task 2 scope:
- JobsDB categories are served from the existing in-repo registry.
- CTgoodjobs categories are parsed via the existing research probe parser.
- CTgoodjobs registry fetch is protected by a simple in-memory TTL cache to avoid
  live-fetching on every API request.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

from app.scraper.categories import get_all_categories
from app.scraper.ctgoodjobs.category_registry import (
    CTGOODJOBS_BASE_URL,
    parse_category_registry,
)
from app.scraper.ctgoodjobs.research_probe import HttpxHtmlClient

SourceSite = Literal["jobsdb", "ctgoodjobs"]


def _normalize_source_site(value: str | None) -> str:
    return (value or "jobsdb").strip().lower()


def _fetch_ctgoodjobs_registry_html() -> str:
    """Fetch CTgoodjobs registry HTML.

    Kept as a standalone function so tests can monkeypatch it to avoid network.
    """

    client = HttpxHtmlClient(timeout_s=20.0)
    try:
        resp = client.get(f"{CTGOODJOBS_BASE_URL}/jobs")
        status_code = getattr(resp, "status_code", None)
        if status_code != 200:
            raise RuntimeError(f"CTgoodjobs registry fetch returned status_code={status_code}")
        text = getattr(resp, "text", "")
        return text if isinstance(text, str) else ""
    finally:
        client.close()


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
        self._ctgoodjobs_cache = _TtlCache(ttl_s=ctgoodjobs_ttl_s)

    def list_categories(self, *, source_site: str | None = None) -> list[dict[str, Any]]:
        normalized = _normalize_source_site(source_site)
        if normalized == "jobsdb":
            return [
                {
                    "id": cat.id,
                    "name": cat.name,
                    "slug": cat.slug,
                    "source_site": "jobsdb",
                }
                for cat in get_all_categories()
            ]

        if normalized == "ctgoodjobs":
            cached = self._ctgoodjobs_cache.get()
            if isinstance(cached, list):
                return cached

            html = _fetch_ctgoodjobs_registry_html()
            if not html.strip():
                raise RuntimeError("CTgoodjobs registry fetch returned empty HTML")

            registry = parse_category_registry(html)
            if not registry:
                raise RuntimeError("CTgoodjobs registry parsed to an empty registry")

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
            return payload

        raise ValueError(f"Unsupported source_site: {normalized}")


_registry: SourceCategoryRegistry | None = None


def get_source_category_registry() -> SourceCategoryRegistry:
    global _registry
    if _registry is None:
        _registry = SourceCategoryRegistry()
    return _registry
