from __future__ import annotations

from collections.abc import Callable
from tempfile import TemporaryDirectory
from typing import Any

from app.scraper.manual_action import ManualActionRequiredError
from app.scraper.offertoday.category_registry import (
    OFFERTODAY_CATEGORIES_L1,
    offertoday_category_catalog_hash,
    offertoday_category_catalog_payload,
)
from app.scraper.offertoday_browser_runtime import OfferTodayBrowserRuntime
from app.source_catalog.domain import (
    CatalogNodeSnapshot,
    CatalogScopeCapabilities,
    CatalogValidationError,
    DiscoveredCatalog,
    SourceQueryTarget,
)
from app.sources.offertoday.constants import (
    OFFERTODAY_LISTING_BROWSE_URL,
    OFFERTODAY_LISTING_SEARCH_URL,
    build_offertoday_listing_payload,
)
from app.sources.offertoday.search_space import build_offertoday_listing_conditions


def _root_key(code: int) -> str:
    return f"offertoday:root:{code}"


class OfferTodaySourceCatalogAdapter:
    source_site = "offertoday"

    def __init__(
        self,
        *,
        browser_runtime_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._browser_runtime_factory = browser_runtime_factory

    @staticmethod
    def _target(classification_id: str, category_code: int) -> SourceQueryTarget:
        return SourceQueryTarget(
            adapter="offertoday.category",
            classification_id=classification_id,
            payload={
                "category_code": category_code,
                "endpoint": "browse",
                "keyword": "",
                "rcd_type": 7,
            },
        )

    def discover(self) -> DiscoveredCatalog:
        nodes: list[CatalogNodeSnapshot] = []
        for root in OFFERTODAY_CATEGORIES_L1:
            root_classification_id = f"offertoday:{root.code}"
            root_node_key = _root_key(root.code)
            root_target = self._target(root_classification_id, root.code)
            nodes.append(
                CatalogNodeSnapshot(
                    node_key=root_node_key,
                    source_site=self.source_site,
                    classification_id=root_classification_id,
                    native_id=root.code,
                    native_label=root.name,
                    parent_node_key=None,
                    native_path=(root.name,),
                    depth=0,
                    selectable=True,
                    supports_exact=True,
                    supports_subtree=True,
                    queryable=True,
                    alias_of_node_key=None,
                    query_semantics_hash=root_target.fingerprint,
                    source_metadata={"level": root.level, "parent_code": root.parent_code},
                )
            )
            for child_index, child in enumerate(root.children):
                is_alias = child.code == root.code
                child_node_key = (
                    f"offertoday:alias:{root.code}:{child_index}"
                    if is_alias
                    else f"offertoday:node:{root.code}:{child.code}"
                )
                classification_id = None if is_alias else f"offertoday:{child.code}"
                target = (
                    None
                    if classification_id is None
                    else self._target(classification_id, child.code)
                )
                nodes.append(
                    CatalogNodeSnapshot(
                        node_key=child_node_key,
                        source_site=self.source_site,
                        classification_id=classification_id,
                        native_id=child.code,
                        native_label=child.name,
                        parent_node_key=root_node_key,
                        native_path=(root.name, child.name),
                        depth=1,
                        selectable=not is_alias,
                        supports_exact=not is_alias,
                        supports_subtree=False,
                        queryable=not is_alias,
                        alias_of_node_key=root_node_key if is_alias else None,
                        query_semantics_hash=target.fingerprint if target else None,
                        source_metadata={
                            "level": child.level,
                            "parent_code": child.parent_code,
                            "relationship": (
                                "same-code-alias" if is_alias else "child"
                            ),
                        },
                    )
                )
        return DiscoveredCatalog(
            source_site=self.source_site,
            nodes=tuple(nodes),
            capabilities=CatalogScopeCapabilities(
                supports_all_scope=True,
                all_scope_root_node_keys=tuple(
                    _root_key(root.code) for root in OFFERTODAY_CATEGORIES_L1
                ),
                recommended_scope={
                    "mode": "subtree",
                    "classification_ids": ["offertoday:118000"],
                },
            ),
            source_payload=offertoday_category_catalog_payload(),
            provenance={
                "adapter": "offertoday",
                "discovery": "verified_versioned_snapshot",
                "source_catalog_hash": offertoday_category_catalog_hash(),
            },
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
                "OfferToday alias or hierarchy node has no independent query",
                node_key=node.node_key,
            )
        try:
            category_code = int(node.native_id)
        except (TypeError, ValueError) as exc:
            raise CatalogValidationError(
                "SOURCE_CLASSIFICATION_NOT_EXECUTABLE",
                "OfferToday category code must be an integer",
                node_key=node.node_key,
            ) from exc
        conditions = build_offertoday_listing_conditions(
            [category_code],
            keywords=None,
            default_to_it=False,
            category_endpoint="browse",
            rcd_type=7,
            expand_category_roots=False,
        )
        if (
            len(conditions) != 1
            or conditions[0].category_id != category_code
            or conditions[0].keyword
        ):
            raise CatalogValidationError(
                "SOURCE_CLASSIFICATION_NOT_EXECUTABLE",
                "OfferToday classification did not compile to one bounded category query",
                node_key=node.node_key,
            )
        return (self._target(node.classification_id, category_code),)

    async def smoke(self, target: SourceQueryTarget) -> dict[str, Any]:
        category_code = int(target.payload["category_code"])
        endpoint = str(target.payload["endpoint"])
        listing_url = (
            OFFERTODAY_LISTING_BROWSE_URL
            if endpoint == "browse"
            else OFFERTODAY_LISTING_SEARCH_URL
        )
        request_payload = build_offertoday_listing_payload(
            category_id=category_code,
            keyword="",
            page=1,
            rcd_type=int(target.payload["rcd_type"]),
        )

        async def fetch(runtime: Any) -> Any:
            async with runtime:
                return await runtime.fetch_listing_page(
                    request_payload,
                    listing_url=listing_url,
                )

        try:
            if self._browser_runtime_factory is not None:
                result = await fetch(self._browser_runtime_factory())
            else:
                with TemporaryDirectory(
                    prefix="job-scraper-offertoday-catalog-smoke-"
                ) as profile_dir:
                    result = await fetch(
                        OfferTodayBrowserRuntime(
                            headed=True,
                            user_data_dir=profile_dir,
                        )
                    )
        except ManualActionRequiredError as exc:
            return {
                "status": "manual_action_required",
                "code": exc.code,
                "classification": exc.classification,
                "stage": exc.stage,
                "target_hash_prefix": target.fingerprint[:12],
            }
        except Exception as exc:
            return {
                "status": "failed",
                "error_type": type(exc).__name__,
                "target_hash_prefix": target.fingerprint[:12],
            }
        response_payload = getattr(result, "payload", None)
        http_status = getattr(result, "http_status", None)
        passed = (
            isinstance(response_payload, dict)
            and (http_status is None or 200 <= int(http_status) < 300)
            and request_payload.get("jobFunctionCodes") == [category_code]
        )
        return {
            "status": "passed" if passed else "failed",
            "http_status": http_status,
            "constraint": "jobFunctionCodes",
            "warmup": "completed",
            "target_hash_prefix": target.fingerprint[:12],
        }
