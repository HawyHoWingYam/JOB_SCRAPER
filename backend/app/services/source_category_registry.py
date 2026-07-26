"""Compatibility projection of ordinary top-level Source classifications."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.database import SessionLocal
from app.services.source_classification_registry import SourceClassificationRegistry
from app.source_classifications.domain import SUPPORTED_SOURCE_SITES


def _normalize_source_site(value: str | None) -> str:
    return (value or "jobsdb").strip().lower()


class SourceCategoryRegistry:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Any] = SessionLocal,
        ctgoodjobs_ttl_s: float | None = None,
    ) -> None:
        # Kept only for constructor compatibility.
        del ctgoodjobs_ttl_s
        self._session_factory = session_factory

    def list_categories(self, *, source_site: str | None = None) -> list[dict[str, Any]]:
        normalized = _normalize_source_site(source_site)
        if normalized not in SUPPORTED_SOURCE_SITES:
            raise ValueError(f"Unsupported Source {normalized}")
        db = self._session_factory()
        try:
            rows = SourceClassificationRegistry(db).list_top_level(normalized)
            return [
                {
                    "id": (
                        row.classification_id
                        if normalized == "ctgoodjobs"
                        else row.native_id
                    ),
                    "name": row.label,
                    "slug": row.native_id,
                    "source_site": normalized,
                }
                for row in rows
            ]
        finally:
            db.close()


_registry: SourceCategoryRegistry | None = None


def get_source_category_registry() -> SourceCategoryRegistry:
    global _registry
    if _registry is None:
        _registry = SourceCategoryRegistry()
    return _registry
