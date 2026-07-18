"""Published Source Catalog compatibility projection.

This adapter intentionally performs no source discovery, network fetch, TTL
fallback, or static executable lookup. Governance discovery lives behind the
Source Catalog candidate API; runtime readers see only the active revision.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.database import SessionLocal
from app.services.source_catalog_service import SourceCatalogService


def _normalize_source_site(value: str | None) -> str:
    return (value or "jobsdb").strip().lower()


class SourceCategoryRegistry:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Any] = SessionLocal,
        ctgoodjobs_ttl_s: float | None = None,
    ) -> None:
        # Kept only for constructor compatibility; authority is revision-based,
        # so a TTL would make atomic publication observably stale.
        del ctgoodjobs_ttl_s
        self._session_factory = session_factory

    def list_categories(self, *, source_site: str | None = None) -> list[dict[str, Any]]:
        normalized = _normalize_source_site(source_site)
        db = self._session_factory()
        try:
            return SourceCatalogService(db).get_legacy_categories(normalized)
        finally:
            db.close()


_registry: SourceCategoryRegistry | None = None


def get_source_category_registry() -> SourceCategoryRegistry:
    global _registry
    if _registry is None:
        _registry = SourceCategoryRegistry()
    return _registry
