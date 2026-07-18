from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from app.scraper.categories import get_all_categories
from app.source_catalog.domain import (
    CatalogNodeSnapshot,
    CatalogScopeCapabilities,
    CatalogValidationError,
    DiscoveredCatalog,
    SourceQueryTarget,
)
from app.sources.jobsdb.request import (
    JOBSDB_LISTING_API_URL,
    build_jobsdb_search_params,
)


class JobsDBSourceCatalogAdapter:
    source_site = "jobsdb"

    def __init__(
        self,
        *,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=30.0)
        )

    def discover(self) -> DiscoveredCatalog:
        categories = tuple(get_all_categories())
        nodes: list[CatalogNodeSnapshot] = []
        for category in categories:
            classification_id = f"jobsdb:{category.id}"
            target = SourceQueryTarget(
                adapter="jobsdb.classification",
                classification_id=classification_id,
                payload={"native_id": category.id},
            )
            nodes.append(
                CatalogNodeSnapshot(
                    node_key=classification_id,
                    source_site=self.source_site,
                    classification_id=classification_id,
                    native_id=category.id,
                    native_label=category.name,
                    parent_node_key=None,
                    native_path=(category.name,),
                    depth=0,
                    selectable=True,
                    supports_exact=True,
                    supports_subtree=False,
                    queryable=True,
                    alias_of_node_key=None,
                    query_semantics_hash=target.fingerprint,
                    source_metadata={"slug": category.slug},
                )
            )
        return DiscoveredCatalog(
            source_site=self.source_site,
            nodes=tuple(nodes),
            capabilities=CatalogScopeCapabilities(
                supports_all_scope=True,
                all_scope_root_node_keys=tuple(node.node_key for node in nodes),
                recommended_scope={"mode": "all"},
            ),
            source_payload={
                "categories": [
                    {"id": item.id, "name": item.name, "slug": item.slug}
                    for item in categories
                ]
            },
            provenance={"adapter": "jobsdb", "discovery": "bundled_registry"},
        )

    def compile(self, node: CatalogNodeSnapshot) -> tuple[SourceQueryTarget, ...]:
        if (
            node.source_site != self.source_site
            or not node.queryable
            or not node.supports_exact
            or node.classification_id is None
        ):
            raise CatalogValidationError(
                "SOURCE_CLASSIFICATION_NOT_EXECUTABLE",
                "JobsDB node is not an executable Source Classification",
                node_key=node.node_key,
            )
        try:
            native_id = int(node.native_id)
        except (TypeError, ValueError) as exc:
            raise CatalogValidationError(
                "SOURCE_CLASSIFICATION_NOT_EXECUTABLE",
                "JobsDB native classification must be an integer",
                node_key=node.node_key,
            ) from exc
        return (
            SourceQueryTarget(
                adapter="jobsdb.classification",
                classification_id=node.classification_id,
                payload={"native_id": native_id},
            ),
        )

    async def smoke(self, target: SourceQueryTarget) -> dict[str, Any]:
        native_id = int(target.payload["native_id"])
        params = build_jobsdb_search_params(native_id, page=1)
        async with self._client_factory() as client:
            response = await client.get(JOBSDB_LISTING_API_URL, params=params)
        content_type = str(response.headers.get("content-type") or "").lower()
        passed = (
            200 <= response.status_code < 300
            and "application/json" in content_type
            and str(response.request.url.params.get("classification")) == str(native_id)
        )
        return {
            "status": "passed" if passed else "failed",
            "http_status": response.status_code,
            "content_type": content_type[:128],
            "constraint": "classification",
            "target_hash_prefix": target.fingerprint[:12],
        }
