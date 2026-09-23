from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawl_control.contracts import (
    AuthoredCrawlScopeV1,
    CrawlScopeWarningV1,
    CrawlScopePreviewV1,
    LISTING_TECHNICAL_RUN_PAGE_CAP,
    ListingSettingsV1,
    ListingWorkloadPreviewV1,
    QueryTargetSnapshotV1,
    ResolvedRunScopeV1,
    SelectedClassificationSnapshotV1,
)
from app.crawl_control.errors import ScopeRuleInvalidError, WorkloadCapExceededError
from app.crawl_control.ordinary_scope import OrdinaryCrawlScopeResolver
from app.crawl_modes import get_supported_crawl_modes
from app.services.source_classification_registry import (
    SourceClassificationRegistry,
    build_source_classification_adapters,
)
from app.models.source_classification import SourceClassification
from app.services.offertoday_keyword_catalog import OfferTodayKeywordCatalog
from app.services.offertoday_taxonomy_resolver import (
    OfferTodayTaxonomyResolver,
    OfferTodayTaxonomyUnavailableError,
)
from app.source_classifications.domain import SourceQueryTarget, payload_fingerprint


DEFAULT_LISTING_SYSTEM_RUN_PAGE_CAP = 5000


def evaluate_listing_workload(
    resolved_scope: ResolvedRunScopeV1,
    settings: ListingSettingsV1,
    *,
    system_listing_run_page_cap: int = DEFAULT_LISTING_SYSTEM_RUN_PAGE_CAP,
    enforce: bool = True,
) -> ListingWorkloadPreviewV1:
    if system_listing_run_page_cap < 1:
        raise ValueError("system_listing_run_page_cap must be positive")
    supported_modes = get_supported_crawl_modes(resolved_scope.source_site)
    if settings.crawl_mode not in supported_modes:
        raise ScopeRuleInvalidError(
            "Crawl mode is not supported by this source",
            context={
                "source_site": resolved_scope.source_site,
                "crawl_mode": settings.crawl_mode,
                "supported_crawl_modes": ",".join(supported_modes),
            },
        )
    if resolved_scope.source_site != "offertoday" and settings.page_depth > 1000:
        raise ScopeRuleInvalidError(
            "Page Depth cannot exceed 1000 for this source",
            context={
                "source_site": resolved_scope.source_site,
                "page_depth": settings.page_depth,
                "maximum_page_depth": 1000,
            },
        )
    effective_system_run_page_cap = (
        LISTING_TECHNICAL_RUN_PAGE_CAP
        if resolved_scope.source_site == "offertoday"
        else system_listing_run_page_cap
    )
    maximum_technical_page_depth = (
        LISTING_TECHNICAL_RUN_PAGE_CAP // resolved_scope.query_target_count
    )
    if settings.page_depth > maximum_technical_page_depth:
        raise ScopeRuleInvalidError(
            "Page Depth exceeds the technical aggregate listing limit",
            context={
                "source_site": resolved_scope.source_site,
                "page_depth": settings.page_depth,
                "query_target_count": resolved_scope.query_target_count,
                "maximum_technical_page_depth": maximum_technical_page_depth,
            },
        )
    estimated_max_pages = resolved_scope.query_target_count * settings.page_depth
    preview = ListingWorkloadPreviewV1(
        query_target_count=resolved_scope.query_target_count,
        page_depth=settings.page_depth,
        estimated_max_pages=estimated_max_pages,
        run_page_cap=settings.run_page_cap,
        system_run_page_cap=effective_system_run_page_cap,
        within_operator_cap=estimated_max_pages <= settings.run_page_cap,
        within_system_cap=estimated_max_pages <= effective_system_run_page_cap,
    )
    if enforce and not preview.dispatchable:
        raise WorkloadCapExceededError(
            estimated_max_pages=preview.estimated_max_pages,
            run_page_cap=preview.run_page_cap,
            system_run_page_cap=preview.system_run_page_cap,
        )
    return preview


class CrawlScopeService:
    """Resolve ordinary active top-level Source classifications for a crawl."""

    def __init__(
        self,
        db: Session,
        *,
        adapters: Mapping[str, object] | None = None,
        offertoday_taxonomy_resolver: OfferTodayTaxonomyResolver | None = None,
        system_listing_run_page_cap: int = DEFAULT_LISTING_SYSTEM_RUN_PAGE_CAP,
    ) -> None:
        if system_listing_run_page_cap < 1:
            raise ValueError("system_listing_run_page_cap must be positive")
        self.db = db
        self.adapters = dict(adapters or build_source_classification_adapters())
        self.registry = SourceClassificationRegistry(db)
        self.resolver = OrdinaryCrawlScopeResolver(db, adapters=self.adapters)
        self.offertoday_taxonomy_resolver = (
            offertoday_taxonomy_resolver or OfferTodayTaxonomyResolver(db)
        )
        self.system_listing_run_page_cap = system_listing_run_page_cap

    def canonicalize(
        self,
        authored_scope: AuthoredCrawlScopeV1,
        **_ignored,
    ) -> AuthoredCrawlScopeV1:
        resolved = self._resolve(authored_scope)
        if authored_scope.mode == "all":
            return authored_scope
        return resolved.authored_scope

    def preview(
        self,
        authored_scope: AuthoredCrawlScopeV1,
        *,
        listing_settings: ListingSettingsV1 | None = None,
        enforce_listing_workload: bool = True,
        refresh_offertoday_taxonomy: bool = False,
    ) -> CrawlScopePreviewV1:
        resolved = self._resolve(
            authored_scope,
            listing_settings=listing_settings,
            refresh_offertoday_taxonomy=refresh_offertoday_taxonomy,
        )
        if (
            listing_settings is not None
            and authored_scope.source_site == "offertoday"
            and (
                authored_scope.mode != "selected"
                or len(authored_scope.classification_ids) != 1
            )
        ):
            raise ScopeRuleInvalidError(
                "OfferToday listing scope requires exactly one top-level classification",
                context={
                    "source_site": authored_scope.source_site,
                    "selected_classification_count": len(
                        authored_scope.classification_ids
                    ),
                },
            )
        workload = (
            self.assess_listing_workload(
                resolved,
                listing_settings,
                enforce=enforce_listing_workload,
            )
            if listing_settings is not None
            else None
        )
        return CrawlScopePreviewV1(
            resolved_scope=resolved,
            listing_workload=workload,
        )

    def resolve_for_run(
        self,
        authored_scope: AuthoredCrawlScopeV1,
        *,
        listing_settings: ListingSettingsV1 | None = None,
        refresh_offertoday_taxonomy: bool = False,
    ) -> ResolvedRunScopeV1:
        return self.preview(
            authored_scope,
            listing_settings=listing_settings,
            refresh_offertoday_taxonomy=refresh_offertoday_taxonomy,
        ).resolved_scope

    def assess_listing_workload(
        self,
        resolved_scope: ResolvedRunScopeV1,
        settings: ListingSettingsV1,
        *,
        enforce: bool = True,
    ) -> ListingWorkloadPreviewV1:
        return evaluate_listing_workload(
            resolved_scope,
            settings,
            system_listing_run_page_cap=self.system_listing_run_page_cap,
            enforce=enforce,
        )

    def _resolve(
        self,
        authored_scope: AuthoredCrawlScopeV1,
        *,
        listing_settings: ListingSettingsV1 | None = None,
        refresh_offertoday_taxonomy: bool = False,
    ) -> ResolvedRunScopeV1:
        if authored_scope.source_site == "offertoday" and listing_settings is not None:
            return self._resolve_offertoday_listing(
                authored_scope,
                refresh_taxonomy=refresh_offertoday_taxonomy,
            )
        try:
            ordinary = self.resolver.resolve(authored_scope)
        except ValueError as exc:
            raise ScopeRuleInvalidError(
                str(exc),
                context={"source_site": authored_scope.source_site},
            ) from exc

        roots = {
            row.classification_id: row
            for row in self.registry.list_top_level(authored_scope.source_site)
        }
        selected = tuple(
            SelectedClassificationSnapshotV1.from_registry_row(
                roots[classification_id]
            )
            for classification_id in ordinary.classification_ids
        )
        query_targets = tuple(
            QueryTargetSnapshotV1.from_source_target(target)
            for target in ordinary.query_targets
        )
        canonical_scope = (
            authored_scope
            if authored_scope.mode == "all"
            else authored_scope.model_copy(
                update={"classification_ids": ordinary.classification_ids}
            )
        )
        expansion_hash = payload_fingerprint(
            [
                {
                    "node_key": item.node_key,
                    "classification_id": item.classification_id,
                    "query_semantics_hash": item.query_semantics_hash,
                }
                for item in selected
            ]
        )
        return ResolvedRunScopeV1(
            source_site=ordinary.source_site,
            authored_scope=canonical_scope,
            selected_classifications=selected,
            classification_expansion_hash=expansion_hash,
            query_targets=query_targets,
            query_target_count=len(query_targets),
        )

    def _resolve_offertoday_listing(
        self,
        authored_scope: AuthoredCrawlScopeV1,
        *,
        refresh_taxonomy: bool,
    ) -> ResolvedRunScopeV1:
        if authored_scope.mode != "selected" or len(authored_scope.classification_ids) != 1:
            raise ScopeRuleInvalidError(
                "OfferToday listing scope requires exactly one top-level classification",
                context={"source_site": "offertoday"},
            )
        try:
            taxonomy = self.offertoday_taxonomy_resolver.refresh_or_last_verified(
                refresh=refresh_taxonomy
            )
        except OfferTodayTaxonomyUnavailableError as exc:
            raise ScopeRuleInvalidError(
                str(exc),
                context={
                    "source_site": "offertoday",
                    "reason": "verified_taxonomy_snapshot_missing",
                },
            ) from exc

        root_id = authored_scope.classification_ids[0]
        root = self.db.scalar(
            select(SourceClassification).where(
                SourceClassification.source_site == "offertoday",
                SourceClassification.classification_id == root_id,
                SourceClassification.is_top_level.is_(True),
                SourceClassification.is_active.is_(True),
            )
        )
        if root is None:
            raise ScopeRuleInvalidError(
                "Selected OfferToday classification is unknown or inactive",
                context={"source_site": "offertoday", "classification_id": root_id},
            )
        children = tuple(
            self.db.scalars(
                select(SourceClassification)
                .where(
                    SourceClassification.source_site == "offertoday",
                    SourceClassification.parent_id == root.id,
                    SourceClassification.is_active.is_(True),
                    SourceClassification.is_top_level.is_(False),
                )
                .order_by(SourceClassification.classification_id)
            )
        )
        catalog = OfferTodayKeywordCatalog(self.db)
        keywords = catalog.enabled_entries_for_classification(root_id)
        catalog_fingerprint = catalog.catalog_fingerprint()
        catalog_updated_at = catalog.catalog_updated_at()
        catalog_updated_value = (
            catalog_updated_at.isoformat() if catalog_updated_at is not None else None
        )

        selected_rows = (root, *children)
        selected = tuple(
            SelectedClassificationSnapshotV1(
                node_key=row.classification_id,
                classification_id=row.classification_id,
                native_label=row.label,
                native_path=(root.label,) if row.id == root.id else (root.label, row.label),
                query_semantics_hash=payload_fingerprint(
                    {
                        "classification_id": row.classification_id,
                        "native_id": row.native_id,
                        "query_metadata": dict(row.query_metadata or {}),
                        "taxonomy_snapshot_fingerprint": taxonomy.fingerprint,
                    }
                ),
            )
            for row in selected_rows
        )

        def target(
            row: SourceClassification,
            *,
            target_kind: str,
            keyword: str = "",
            normalized_keyword: str | None = None,
        ) -> QueryTargetSnapshotV1:
            source_target = SourceQueryTarget(
                adapter="offertoday.category",
                classification_id=row.classification_id,
                payload={
                    "category_code": int(row.native_id),
                    "search_family": (
                        "classification_keyword_pack"
                        if target_kind == "keyword"
                        else "native_classification"
                    ),
                    "endpoint": "search",
                    "keyword": keyword,
                    "rcd_type": None,
                    "target_kind": target_kind,
                    "top_level_classification_id": root.classification_id,
                    "normalized_keyword": normalized_keyword,
                    "taxonomy_snapshot_fingerprint": taxonomy.fingerprint,
                    "keyword_catalog_fingerprint": catalog_fingerprint,
                    "keyword_catalog_updated_at": catalog_updated_value,
                },
            )
            return QueryTargetSnapshotV1.from_source_target(source_target)

        query_targets = (
            target(root, target_kind="native_top_level"),
            *(target(child, target_kind="native_child") for child in children),
            *(
                target(
                    root,
                    target_kind="keyword",
                    keyword=entry.keyword,
                    normalized_keyword=entry.normalized_keyword,
                )
                for entry in keywords
            ),
        )
        expansion_hash = payload_fingerprint(
            [
                {
                    "node_key": item.node_key,
                    "classification_id": item.classification_id,
                    "query_semantics_hash": item.query_semantics_hash,
                }
                for item in selected
            ]
        )
        warnings = ()
        if taxonomy.warning is not None:
            warning = taxonomy.warning
            warnings = (
                CrawlScopeWarningV1(
                    code=warning["code"],
                    message=warning["message"],
                    context={
                        key: value
                        for key, value in warning.items()
                        if key not in {"code", "message"}
                    },
                ),
            )
        return ResolvedRunScopeV1(
            source_site="offertoday",
            authored_scope=authored_scope,
            selected_classifications=selected,
            classification_expansion_hash=expansion_hash,
            query_targets=query_targets,
            query_target_count=len(query_targets),
            warnings=warnings,
        )
