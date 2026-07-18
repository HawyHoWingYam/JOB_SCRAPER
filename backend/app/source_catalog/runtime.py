from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database import SessionLocal
from app.services.source_catalog_service import SourceCatalogService
from app.source_catalog.domain import CatalogNodeSnapshot, SourceQueryTarget


@dataclass(frozen=True)
class ResolvedSourceQueryTarget:
    node: CatalogNodeSnapshot
    target: SourceQueryTarget


@dataclass(frozen=True)
class PublishedSourceQueryPlan:
    source_site: str
    revision_id: Any
    revision_fingerprint: str
    entries: tuple[ResolvedSourceQueryTarget, ...]


def load_published_query_plan(
    source_site: str,
    classification_ids,
    *,
    session_factory=SessionLocal,
) -> PublishedSourceQueryPlan:
    """Resolve legacy IDs against one active revision before any source request."""

    db = session_factory()
    try:
        service = SourceCatalogService(db)
        published, nodes = service.validate_classifications(
            source_site, classification_ids
        )
        entries = tuple(
            ResolvedSourceQueryTarget(node=node, target=target)
            for node, target in service.compile_nodes(published, nodes)
        )
        return PublishedSourceQueryPlan(
            source_site=published.catalog.source_site,
            revision_id=published.revision.id,
            revision_fingerprint=published.revision.fingerprint,
            entries=entries,
        )
    finally:
        db.close()


def load_published_scope_query_plan(
    source_site: str,
    *,
    mode: str,
    classification_ids=(),
    session_factory=SessionLocal,
) -> PublishedSourceQueryPlan:
    db = session_factory()
    try:
        service = SourceCatalogService(db)
        published, nodes, targets = service.resolve_scope(
            source_site,
            mode=mode,
            classification_ids=classification_ids,
        )
        entries: list[ResolvedSourceQueryTarget] = []
        entries.extend(
            ResolvedSourceQueryTarget(node=node, target=target)
            for node, target in service.compile_nodes(published, nodes)
        )
        if len(entries) != len(targets):
            raise RuntimeError("Published Source Query Target expansion changed unexpectedly")
        return PublishedSourceQueryPlan(
            source_site=published.catalog.source_site,
            revision_id=published.revision.id,
            revision_fingerprint=published.revision.fingerprint,
            entries=tuple(entries),
        )
    finally:
        db.close()
