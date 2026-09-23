from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.source_classification import SourceClassification
from app.source_classifications.adapters import (
    CTgoodjobsSourceClassificationAdapter,
    JobsDBSourceClassificationAdapter,
    OfferTodaySourceClassificationAdapter,
    SourceClassificationAdapter,
)
from app.source_classifications.domain import (
    DiscoveredCatalog,
    SUPPORTED_SOURCE_SITES,
    is_source_qualified_classification_id,
    validate_executable_catalog,
)
from app.utils.time import utc_now


@dataclass(frozen=True)
class ObservedSourceClassification:
    classification_id: str
    native_id: str
    label: str
    depth: int
    parent_classification_id: str | None = None
    query_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceClassificationSyncResult:
    source_site: str
    observed_count: int
    created_count: int
    updated_count: int
    reactivated_count: int
    inactivated_count: int
    complete: bool


class SourceClassificationRegistry:
    """Owns ordinary current Source classifications and crawl-choice reads."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def synchronize_catalog(
        self,
        catalog: DiscoveredCatalog,
        *,
        complete: bool,
        compiler: SourceClassificationAdapter,
    ) -> SourceClassificationSyncResult:
        validate_executable_catalog(catalog, compiler)
        node_identity = {
            node.node_key: node.classification_id
            for node in catalog.nodes
            if node.classification_id is not None
        }
        observations = tuple(
            ObservedSourceClassification(
                classification_id=node.classification_id,
                native_id=str(node.native_id),
                label=node.native_label,
                depth=node.depth,
                parent_classification_id=(
                    node_identity.get(node.parent_node_key)
                    if node.parent_node_key is not None
                    else None
                ),
                query_metadata={
                    "queryable": node.queryable,
                    "supports_exact": node.supports_exact,
                    "supports_subtree": node.supports_subtree,
                    **dict(node.source_metadata),
                },
            )
            for node in catalog.nodes
            if node.classification_id is not None
        )
        return self.synchronize(catalog.source_site, observations, complete=complete)

    def synchronize(
        self,
        source_site: str,
        observed_classifications: Iterable[ObservedSourceClassification],
        *,
        complete: bool,
    ) -> SourceClassificationSyncResult:
        observations = tuple(observed_classifications)
        self._validate(source_site, observations)
        now = utc_now()
        existing = {
            row.classification_id: row
            for row in self.db.scalars(
                select(SourceClassification).where(
                    SourceClassification.source_site == source_site
                )
            )
        }
        created = updated = reactivated = 0
        created_identities: set[str] = set()

        for item in sorted(observations, key=lambda value: value.depth):
            row = existing.get(item.classification_id)
            if row is None:
                query_metadata = dict(item.query_metadata)
                row = SourceClassification(
                    source_site=source_site,
                    classification_id=item.classification_id,
                    native_id=item.native_id,
                    label=item.label,
                    depth=item.depth,
                    is_top_level=item.depth == 0,
                    is_active=True,
                    query_metadata=query_metadata,
                    first_observed_at=now,
                    last_observed_at=now,
                )
                self.db.add(row)
                existing[item.classification_id] = row
                created_identities.add(item.classification_id)
                created += 1
                continue
            query_metadata = dict(item.query_metadata)
            if not complete:
                query_metadata = {
                    **dict(row.query_metadata or {}),
                    **query_metadata,
                }
            changed = (
                row.native_id != item.native_id
                or row.label != item.label
                or row.depth != item.depth
                or row.query_metadata != query_metadata
            )
            if not row.is_active:
                row.is_active = True
                reactivated += 1
            row.native_id = item.native_id
            row.label = item.label
            row.depth = item.depth
            row.is_top_level = item.depth == 0
            row.query_metadata = query_metadata
            row.last_observed_at = now
            if changed:
                updated += 1

        self.db.flush()
        for item in observations:
            row = existing[item.classification_id]
            parent = (
                existing[item.parent_classification_id]
                if item.parent_classification_id is not None
                else None
            )
            if row.parent_id != (parent.id if parent is not None else None):
                row.parent = parent
                if item.classification_id not in created_identities:
                    updated += 1

        inactivated = 0
        if complete:
            observed_ids = {item.classification_id for item in observations}
            for row in existing.values():
                if (
                    (row.is_top_level or source_site == "offertoday")
                    and row.is_active
                    and row.classification_id not in observed_ids
                ):
                    row.is_active = False
                    inactivated += 1
        self.db.flush()
        return SourceClassificationSyncResult(
            source_site=source_site,
            observed_count=len(observations),
            created_count=created,
            updated_count=updated,
            reactivated_count=reactivated,
            inactivated_count=inactivated,
            complete=complete,
        )

    def observe_path(
        self,
        job_id: object,
        source_site: str,
        captured_path: Sequence[ObservedSourceClassification],
    ) -> SourceClassificationSyncResult:
        del job_id
        return self.synchronize(source_site, captured_path, complete=False)

    def list_top_level(
        self,
        source_site: str,
        *,
        active_only: bool = True,
    ) -> tuple[SourceClassification, ...]:
        statement = select(SourceClassification).where(
            SourceClassification.source_site == source_site,
            SourceClassification.is_top_level.is_(True),
        )
        if active_only:
            statement = statement.where(SourceClassification.is_active.is_(True))
        return tuple(
            self.db.scalars(
                statement.order_by(
                    SourceClassification.label,
                    SourceClassification.classification_id,
                )
            )
        )

    def list_all(
        self,
        *,
        source_site: str | None = None,
        active_only: bool = False,
    ) -> tuple[SourceClassification, ...]:
        statement = select(SourceClassification)
        if source_site is not None:
            statement = statement.where(SourceClassification.source_site == source_site)
        if active_only:
            statement = statement.where(SourceClassification.is_active.is_(True))
        return tuple(
            self.db.scalars(
                statement.order_by(
                    SourceClassification.source_site,
                    SourceClassification.depth,
                    SourceClassification.classification_id,
                )
            )
        )

    @staticmethod
    def _validate(
        source_site: str,
        observations: Sequence[ObservedSourceClassification],
    ) -> None:
        if source_site not in SUPPORTED_SOURCE_SITES:
            raise ValueError(f"Unsupported Source {source_site}")
        identities = {item.classification_id for item in observations}
        if len(identities) != len(observations):
            raise ValueError("Source classification observations contain duplicates")
        for item in observations:
            if not is_source_qualified_classification_id(
                item.classification_id,
                source_site,
            ):
                raise ValueError(
                    "Source classification identity is not source-qualified"
                )
            if not item.native_id.strip() or not item.label.strip() or item.depth < 0:
                raise ValueError("Source classification observation is malformed")
            if item.depth == 0 and item.parent_classification_id is not None:
                raise ValueError("Top-level Source classification cannot have a parent")
            if item.depth > 0 and item.parent_classification_id not in identities:
                raise ValueError("Child Source classification parent is missing")


def build_source_classification_adapters() -> dict[str, SourceClassificationAdapter]:
    """Build the three discovery/query adapters used by the ordinary registry."""

    adapters = (
        JobsDBSourceClassificationAdapter(),
        CTgoodjobsSourceClassificationAdapter(),
        OfferTodaySourceClassificationAdapter(live_discovery=True),
    )
    return {adapter.source_site: adapter for adapter in adapters}


def synchronize_source_classification_adapters(
    db: Session,
    adapters: Iterable[SourceClassificationAdapter],
) -> dict[str, SourceClassificationSyncResult | str]:
    """Refresh every Source independently; one failed Source cannot stale the rest."""

    results: dict[str, SourceClassificationSyncResult | str] = {}
    registry = SourceClassificationRegistry(db)
    for adapter in adapters:
        source_site = str(getattr(adapter, "source_site", ""))
        try:
            with db.begin_nested():
                catalog = adapter.discover()
                results[source_site] = registry.synchronize_catalog(
                    catalog,
                    complete=True,
                    compiler=adapter,
                )
        except Exception as exc:
            results[source_site] = type(exc).__name__
    return results
