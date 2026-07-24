from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any
import re
from urllib.parse import urlparse, urlsplit
from uuid import uuid4

from app.crawl_modes import resolve_crawl_mode
from app.scraper.ctgoodjobs.category_registry import (
    CTGOODJOBS_BASE_URL,
    CTGoodJobsCategory,
    get_static_ctgoodjobs_categories,
    parse_category_registry,
)
from app.scraper.ctgoodjobs.list_scraper import fetch_category_page_html
from app.scraper.ctgoodjobs_browser_page_scraper import CTGoodJobsBrowserPageScraper
from app.scraper.manual_action import ManualActionRequiredError
from app.source_catalog.domain import (
    CatalogNodeSnapshot,
    CatalogScopeCapabilities,
    CatalogValidationError,
    DiscoveredCatalog,
    SourceQueryTarget,
)


@dataclass(frozen=True)
class CTGoodJobsDiscoveryResult:
    categories: tuple[CTGoodJobsCategory, ...]
    method: str
    evidence: dict[str, Any]


def _discover_ctgoodjobs_categories() -> CTGoodJobsDiscoveryResult:
    """Discover live categories, retaining the bundled snapshot only as candidate input."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        running_loop = False
    else:
        running_loop = True
    if running_loop:
        raise RuntimeError("CTgoodjobs discovery must run outside an active event loop")

    fallback_reason = "empty_registry"
    try:
        page_html = asyncio.run(
            fetch_category_page_html(f"{CTGOODJOBS_BASE_URL}/jobs")
        )
        parsed = parse_category_registry(page_html)
        if parsed:
            return CTGoodJobsDiscoveryResult(
                categories=tuple(parsed),
                method="live_registry",
                evidence={"category_count": len(parsed)},
            )
    except Exception as exc:
        fallback_reason = type(exc).__name__
    fallback = tuple(get_static_ctgoodjobs_categories())
    return CTGoodJobsDiscoveryResult(
        categories=fallback,
        method="bundled_seed_fallback",
        evidence={"category_count": len(fallback), "reason": fallback_reason[:128]},
    )


class CTgoodjobsSourceCatalogAdapter:
    source_site = "ctgoodjobs"

    def __init__(
        self,
        *,
        category_provider: Callable[
            [], Sequence[CTGoodJobsCategory] | CTGoodJobsDiscoveryResult
        ]
        | None = None,
        browser_scraper_factory: Callable[[], Any] | None = None,
        crawl_mode: str | None = None,
    ) -> None:
        self._crawl_mode = resolve_crawl_mode("ctgoodjobs", crawl_mode)
        self._category_provider = category_provider or _discover_ctgoodjobs_categories
        self._browser_scraper_factory = browser_scraper_factory or (
            lambda: CTGoodJobsBrowserPageScraper(
                request_payload={
                    "crawl_mode": self._crawl_mode,
                    "crawl_phase": "catalog_validation",
                    "max_pages": 1,
                    "profile_operation_id": f"catalog-{uuid4()}",
                    "cleanup_profile_on_manual_action": True,
                },
                max_attempts=1,
            )
        )

    def discover(self) -> DiscoveredCatalog:
        discovery = self._category_provider()
        if isinstance(discovery, CTGoodJobsDiscoveryResult):
            categories = discovery.categories
            discovery_method = discovery.method
            discovery_evidence = discovery.evidence
        else:
            categories = tuple(discovery)
            discovery_method = "injected_registry"
            discovery_evidence = {"category_count": len(categories)}
        if not categories:
            raise CatalogValidationError(
                "CATALOG_DISCOVERY_EMPTY", "CTgoodjobs discovery returned no categories"
            )
        nodes: list[CatalogNodeSnapshot] = []
        source_categories: list[dict[str, Any]] = []
        for category in categories:
            url_path = urlparse(category.url).path
            target = SourceQueryTarget(
                adapter="ctgoodjobs.category",
                classification_id=category.source_classification_id,
                payload={
                    "native_id": category.ctgoodjobs_id,
                    "url_path": url_path,
                    "crawl_mode": self._crawl_mode,
                },
            )
            nodes.append(
                CatalogNodeSnapshot(
                    node_key=category.source_classification_id,
                    source_site=self.source_site,
                    classification_id=category.source_classification_id,
                    native_id=category.ctgoodjobs_id,
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
                    source_metadata={
                        "slug": category.slug,
                        "url_path": url_path,
                        "child_count": category.child_count,
                    },
                )
            )
            source_categories.append(
                {
                    "id": category.ctgoodjobs_id,
                    "name": category.name,
                    "slug": category.slug,
                    "url_path": url_path,
                    "child_count": category.child_count,
                }
            )
        return DiscoveredCatalog(
            source_site=self.source_site,
            nodes=tuple(nodes),
            capabilities=CatalogScopeCapabilities(
                supports_all_scope=True,
                all_scope_root_node_keys=tuple(node.node_key for node in nodes),
                recommended_scope={"mode": "all"},
            ),
            source_payload={"categories": source_categories},
            provenance={
                "adapter": "ctgoodjobs",
                "discovery": discovery_method,
                "evidence": discovery_evidence,
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
                "CTgoodjobs node is not an executable Source Classification",
                node_key=node.node_key,
            )
        native_id = str(node.native_id).strip()
        url_path = str(node.source_metadata.get("url_path") or "").strip()
        parsed_path = urlsplit(url_path)
        is_exact_category_path = bool(
            re.fullmatch(r"/jobs/jobs-in-[a-z0-9]+(?:-[a-z0-9]+)*", parsed_path.path)
        )
        if (
            not native_id
            or parsed_path.scheme
            or parsed_path.netloc
            or parsed_path.query
            or parsed_path.fragment
            or not is_exact_category_path
        ):
            raise CatalogValidationError(
                "SOURCE_CLASSIFICATION_NOT_EXECUTABLE",
                "CTgoodjobs published node has no validated native URL path",
                node_key=node.node_key,
            )
        return (
            SourceQueryTarget(
                adapter="ctgoodjobs.category",
                classification_id=node.classification_id,
                payload={
                    "native_id": native_id,
                    "url_path": url_path,
                    "crawl_mode": self._crawl_mode,
                },
            ),
        )

    async def smoke(self, target: SourceQueryTarget) -> dict[str, Any]:
        url_path = str(target.payload["url_path"])
        url = f"{CTGOODJOBS_BASE_URL}{url_path}"
        try:
            async with self._browser_scraper_factory() as browser_scraper:
                page_html = await browser_scraper.fetch_page_html(
                    url,
                    stage="category_page",
                    referer=f"{CTGOODJOBS_BASE_URL}/jobs",
                )
        except ManualActionRequiredError as exc:
            return {
                "status": "manual_action_required",
                "code": exc.code,
                "classification": exc.classification,
                "stage": exc.stage,
                "crawl_mode": self._crawl_mode,
                "target_hash_prefix": target.fingerprint[:12],
            }
        except Exception as exc:
            return {
                "status": "failed",
                "error_type": type(exc).__name__,
                "crawl_mode": self._crawl_mode,
                "target_hash_prefix": target.fingerprint[:12],
            }
        return {
            "status": "passed" if page_html.strip() else "failed",
            "crawl_mode": self._crawl_mode,
            "content_length": min(len(page_html), 1_000_000),
            "target_hash_prefix": target.fingerprint[:12],
        }
