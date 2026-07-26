from __future__ import annotations

from dataclasses import dataclass
from sqlalchemy.orm import Session

from app.crawl_control.contracts import AuthoredCrawlScopeV1
from app.services.source_classification_registry import SourceClassificationRegistry
from app.source_classifications.domain import (
    CatalogNodeSnapshot,
    SourceQueryTarget,
)


SourceCrawlScope = AuthoredCrawlScopeV1


@dataclass(frozen=True)
class ResolvedSourceCrawlScope:
    source_site: str
    classification_ids: tuple[str, ...]
    query_targets: tuple[SourceQueryTarget, ...]


class OrdinaryCrawlScopeResolver:
    def __init__(self, db: Session, *, adapters: dict[str, object]) -> None:
        self.registry = SourceClassificationRegistry(db)
        self.adapters = adapters

    def resolve(self, scope: SourceCrawlScope) -> ResolvedSourceCrawlScope:
        adapter = self.adapters.get(scope.source_site)
        if adapter is None:
            raise ValueError(f"Unsupported Source {scope.source_site}")
        active_roots = {
            row.classification_id: row
            for row in self.registry.list_top_level(scope.source_site)
        }
        selected_ids = (
            tuple(active_roots) if scope.mode == "all" else scope.classification_ids
        )
        missing = [value for value in selected_ids if value not in active_roots]
        if missing:
            raise ValueError(
                "Selected Source classification is unknown, inactive, or not top-level"
            )
        targets: list[SourceQueryTarget] = []
        for classification_id in selected_ids:
            row = active_roots[classification_id]
            node = source_classification_node(row)
            targets.extend(adapter.compile(node))
        if not targets:
            raise ValueError("Crawl scope resolved to no query targets")
        return ResolvedSourceCrawlScope(
            source_site=scope.source_site,
            classification_ids=selected_ids,
            query_targets=tuple(targets),
        )


def source_classification_node(row) -> CatalogNodeSnapshot:
    """Project one ordinary root row into the existing adapter input contract."""

    metadata = dict(row.query_metadata or {})
    return CatalogNodeSnapshot(
        node_key=row.classification_id,
        source_site=row.source_site,
        classification_id=row.classification_id,
        native_id=row.native_id,
        native_label=row.label,
        parent_node_key=None,
        native_path=(row.label,),
        depth=0,
        selectable=True,
        supports_exact=bool(metadata.pop("supports_exact", True)),
        supports_subtree=bool(metadata.pop("supports_subtree", False)),
        queryable=bool(metadata.pop("queryable", True)),
        alias_of_node_key=None,
        query_semantics_hash=None,
        source_metadata=metadata,
    )
