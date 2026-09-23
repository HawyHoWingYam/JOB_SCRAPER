from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from tempfile import TemporaryDirectory
from typing import Any

import requests

from app.scraper.manual_action import ManualActionRequiredError
from app.scraper.offertoday.category_registry import (
    OFFERTODAY_CATEGORIES_L1,
    OfferTodayCategory,
    offertoday_category_registry_hash,
    offertoday_category_registry_payload,
)
from app.scraper.offertoday_browser_runtime import OfferTodayBrowserRuntime
from app.source_classifications.domain import (
    CatalogNodeSnapshot,
    CatalogScopeCapabilities,
    CatalogValidationError,
    DiscoveredCatalog,
    SourceQueryTarget,
    payload_fingerprint,
)
from app.sources.offertoday.constants import (
    OFFERTODAY_LISTING_BROWSE_URL,
    OFFERTODAY_LISTING_SEARCH_URL,
    build_offertoday_listing_payload,
)


OFFERTODAY_TAXONOMY_URL = (
    "https://www.offertoday.com/wapi/geek/recommend/filter/content/all"
)


def _root_key(code: int) -> str:
    return f"offertoday:root:{code}"


class OfferTodaySourceClassificationAdapter:
    source_site = "offertoday"

    def __init__(
        self,
        *,
        browser_runtime_factory: Callable[[], Any] | None = None,
        live_discovery: bool = False,
        taxonomy_payload_provider: Callable[[], Mapping[str, Any]] | None = None,
        taxonomy_timeout_seconds: float = 15.0,
    ) -> None:
        self._browser_runtime_factory = browser_runtime_factory
        self._live_discovery = live_discovery
        self._taxonomy_payload_provider = taxonomy_payload_provider
        self._taxonomy_timeout_seconds = taxonomy_timeout_seconds

    @staticmethod
    def _target(
        classification_id: str,
        category_code: int,
    ) -> SourceQueryTarget:
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

    @classmethod
    def _targets(
        cls,
        classification_id: str,
        category_code: int,
    ) -> tuple[SourceQueryTarget, ...]:
        return (cls._target(classification_id, category_code),)

    @staticmethod
    def _semantics_hash(targets: tuple[SourceQueryTarget, ...]) -> str:
        return (
            targets[0].fingerprint
            if len(targets) == 1
            else payload_fingerprint([target.to_payload() for target in targets])
        )

    def discover(self) -> DiscoveredCatalog:
        if self._live_discovery:
            return self.discover_live()
        return self._build_catalog(
            OFFERTODAY_CATEGORIES_L1,
            source_payload=offertoday_category_registry_payload(),
            provenance={
                "adapter": "offertoday",
                "discovery": "bundled_registry",
                "source_classification_hash": offertoday_category_registry_hash(),
            },
        )

    def discover_live(self) -> DiscoveredCatalog:
        payload = dict(
            self._taxonomy_payload_provider()
            if self._taxonomy_payload_provider is not None
            else self._fetch_live_taxonomy_payload()
        )
        categories = self._parse_live_categories(payload)
        source_payload = {
            "endpoint": "/wapi/geek/recommend/filter/content/all",
            "language": "en",
            "categories": [item.to_registry_dict() for item in categories],
        }
        return self._build_catalog(
            categories,
            source_payload=source_payload,
            provenance={
                "adapter": "offertoday",
                "discovery": "live_taxonomy",
                "endpoint": "/wapi/geek/recommend/filter/content/all",
                "source_classification_hash": payload_fingerprint(source_payload),
            },
        )

    def _fetch_live_taxonomy_payload(self) -> Mapping[str, Any]:
        response = requests.get(
            OFFERTODAY_TAXONOMY_URL,
            headers={"Accept": "application/json", "Accept-Language": "en"},
            timeout=self._taxonomy_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise ValueError("OfferToday taxonomy response must be an object")
        return payload

    @classmethod
    def _parse_live_categories(
        cls, payload: Mapping[str, Any]
    ) -> tuple[OfferTodayCategory, ...]:
        if payload.get("code") != 0:
            raise ValueError("OfferToday taxonomy response code is not successful")
        try:
            raw_categories = payload["data"]["en"]["POSITION"]["children"]
        except (KeyError, TypeError) as exc:
            raise ValueError("OfferToday taxonomy POSITION tree is missing") from exc
        if not isinstance(raw_categories, list) or not raw_categories:
            raise ValueError("OfferToday taxonomy POSITION roots are missing")

        roots = tuple(cls._parse_live_node(item, root=True) for item in raw_categories)
        root_codes = {item.code for item in roots}
        if len(root_codes) != len(roots):
            raise ValueError("OfferToday taxonomy roots contain duplicate codes")
        child_codes: set[int] = set()
        for root in roots:
            alias_count = 0
            for child in root.children:
                if child.parent_code != root.code:
                    raise ValueError("OfferToday taxonomy child parent is inconsistent")
                if child.code == root.code:
                    alias_count += 1
                elif child.code in child_codes or child.code in root_codes:
                    raise ValueError("OfferToday taxonomy child code is not unique")
                else:
                    child_codes.add(child.code)
            if alias_count > 1:
                raise ValueError("OfferToday taxonomy root has duplicate all-category aliases")
        return roots

    @classmethod
    def _parse_live_node(
        cls,
        value: Any,
        *,
        root: bool,
    ) -> OfferTodayCategory:
        if not isinstance(value, Mapping):
            raise ValueError("OfferToday taxonomy node must be an object")
        code = value.get("code")
        name = value.get("name")
        level = value.get("level")
        parent_code = value.get("parentCode")
        children = value.get("children")
        if (
            not isinstance(code, int)
            or isinstance(code, bool)
            or not isinstance(name, str)
            or not name.strip()
            or name != name.strip()
            or not isinstance(level, int)
            or isinstance(level, bool)
            or level != (1 if root else 2)
            or not isinstance(parent_code, int)
            or isinstance(parent_code, bool)
            or not isinstance(children, list)
        ):
            raise ValueError("OfferToday taxonomy node fields are invalid")
        if not root and children:
            raise ValueError("OfferToday taxonomy child cannot own descendants")
        return OfferTodayCategory(
            code=code,
            name=name,
            parent_code=0 if root else parent_code,
            level=level,
            children=(
                tuple(cls._parse_live_node(child, root=False) for child in children)
                if root
                else ()
            ),
        )

    def _build_catalog(
        self,
        categories: Sequence[OfferTodayCategory],
        *,
        source_payload: Mapping[str, Any],
        provenance: Mapping[str, Any],
    ) -> DiscoveredCatalog:
        nodes: list[CatalogNodeSnapshot] = []
        for root in categories:
            root_classification_id = f"offertoday:{root.code}"
            root_node_key = _root_key(root.code)
            root_targets = self._targets(root_classification_id, root.code)
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
                    query_semantics_hash=self._semantics_hash(root_targets),
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
                targets = (
                    None
                    if classification_id is None
                    else self._targets(classification_id, child.code)
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
                        query_semantics_hash=(
                            self._semantics_hash(targets) if targets else None
                        ),
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
                    _root_key(root.code) for root in categories
                ),
                recommended_scope={
                    "mode": "subtree",
                    "classification_ids": ["offertoday:118000"],
                },
            ),
            source_payload=dict(source_payload),
            provenance=dict(provenance),
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
        return self._targets(node.classification_id, category_code)

    async def smoke(self, target: SourceQueryTarget) -> dict[str, Any]:
        try:
            if self._browser_runtime_factory is not None:
                async with self._browser_runtime_factory() as runtime:
                    return await self._smoke_with_runtime(target, runtime)
            with TemporaryDirectory(
                prefix="job-scraper-offertoday-catalog-smoke-"
            ) as profile_dir:
                async with OfferTodayBrowserRuntime(
                    headed=True,
                    user_data_dir=profile_dir,
                ) as runtime:
                    return await self._smoke_with_runtime(target, runtime)
        except Exception as exc:
            return self._smoke_exception_result(target, exc)

    @asynccontextmanager
    async def validation_smoke_session(
        self,
    ) -> AsyncIterator[
        Callable[[SourceQueryTarget], Awaitable[dict[str, Any]]]
    ]:
        """Reuse one isolated browser session for one coordinator worker batch."""

        if (
            self._browser_runtime_factory is not None
            or type(self).smoke is not OfferTodaySourceClassificationAdapter.smoke
        ):
            yield self.smoke
            return

        with TemporaryDirectory(
            prefix="job-scraper-offertoday-catalog-validation-"
        ) as profile_dir:
            runtime = OfferTodayBrowserRuntime(
                headed=True,
                user_data_dir=profile_dir,
            )
            try:
                await runtime.start()
            except Exception as exc:
                start_error = exc

                async def failed_start(target: SourceQueryTarget) -> dict[str, Any]:
                    return self._smoke_exception_result(target, start_error)

                yield failed_start
                return

            async def session_smoke(target: SourceQueryTarget) -> dict[str, Any]:
                return await self._smoke_with_runtime(target, runtime)

            try:
                yield session_smoke
            finally:
                await runtime.stop()

    async def _smoke_with_runtime(
        self,
        target: SourceQueryTarget,
        runtime: Any,
    ) -> dict[str, Any]:
        category_code = int(target.payload["category_code"])
        endpoint = str(target.payload["endpoint"])
        listing_url = (
            OFFERTODAY_LISTING_BROWSE_URL
            if endpoint == "browse"
            else OFFERTODAY_LISTING_SEARCH_URL
        )
        request_payload = build_offertoday_listing_payload(
            category_id=category_code,
            keyword=str(target.payload["keyword"]),
            page=1,
            rcd_type=target.payload["rcd_type"],
        )
        try:
            result = await runtime.fetch_listing_page(
                request_payload,
                listing_url=listing_url,
            )
        except Exception as exc:
            return self._smoke_exception_result(target, exc)
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

    @staticmethod
    def _smoke_exception_result(
        target: SourceQueryTarget,
        exc: Exception,
    ) -> dict[str, Any]:
        if isinstance(exc, ManualActionRequiredError):
            return {
                "status": "manual_action_required",
                "code": exc.code,
                "classification": exc.classification,
                "stage": exc.stage,
                "target_hash_prefix": target.fingerprint[:12],
            }
        return {
            "status": "failed",
            "error_type": type(exc).__name__,
            "target_hash_prefix": target.fingerprint[:12],
        }
