from __future__ import annotations

from dataclasses import dataclass

from app.crawl_control.contracts import AuthoredCrawlScopeV1
from app.crawl_control.ordinary_scope import (
    OrdinaryCrawlScopeResolver,
    source_classification_node,
)
from app.database import SessionLocal
from app.services.source_classification_registry import (
    SourceClassificationRegistry,
    build_source_classification_adapters,
)
from app.source_classifications.domain import CatalogNodeSnapshot, SourceQueryTarget


@dataclass(frozen=True)
class ResolvedSourceQueryTarget:
    node: CatalogNodeSnapshot
    target: SourceQueryTarget


@dataclass(frozen=True)
class OrdinarySourceQueryPlan:
    source_site: str
    entries: tuple[ResolvedSourceQueryTarget, ...]


def load_source_query_plan(
    source_site: str,
    classification_ids,
    *,
    session_factory=SessionLocal,
) -> OrdinarySourceQueryPlan:
    return load_source_scope_query_plan(
        source_site,
        mode="selected",
        classification_ids=classification_ids,
        session_factory=session_factory,
    )


def load_source_scope_query_plan(
    source_site: str,
    *,
    mode: str,
    classification_ids=(),
    session_factory=SessionLocal,
) -> OrdinarySourceQueryPlan:
    db = session_factory()
    try:
        adapters = build_source_classification_adapters()
        registry = SourceClassificationRegistry(db)
        roots = registry.list_top_level(source_site)
        roots_by_id = {row.classification_id: row for row in roots}
        roots_by_native_id = {str(row.native_id): row for row in roots}

        if mode == "all":
            authored_scope = AuthoredCrawlScopeV1(source_site=source_site, mode="all")
        elif mode == "selected":
            normalized_ids: list[str] = []
            for value in classification_ids:
                raw_value = str(value).strip()
                row = roots_by_id.get(raw_value) or roots_by_native_id.get(raw_value)
                if row is None:
                    raise ValueError(
                        "Selected Source classification is unknown, inactive, or not top-level"
                    )
                normalized_ids.append(row.classification_id)
            authored_scope = AuthoredCrawlScopeV1(
                source_site=source_site,
                mode="selected",
                classification_ids=tuple(dict.fromkeys(normalized_ids)),
            )
        else:
            raise ValueError("Source classification scope mode must be all or selected")

        resolved = OrdinaryCrawlScopeResolver(db, adapters=adapters).resolve(
            authored_scope
        )
        entries = tuple(
            ResolvedSourceQueryTarget(
                node=source_classification_node(
                    roots_by_id[target.classification_id]
                ),
                target=target,
            )
            for target in resolved.query_targets
        )
        return OrdinarySourceQueryPlan(source_site=source_site, entries=entries)
    finally:
        db.close()
