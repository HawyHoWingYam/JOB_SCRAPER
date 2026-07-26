from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy.orm import Session

from app.crawl_control.contracts import (
    AuthoredCrawlScopeV1,
    CrawlScopePreviewV1,
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
from app.source_classifications.domain import payload_fingerprint


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
    estimated_max_pages = resolved_scope.query_target_count * settings.page_depth
    preview = ListingWorkloadPreviewV1(
        query_target_count=resolved_scope.query_target_count,
        page_depth=settings.page_depth,
        estimated_max_pages=estimated_max_pages,
        run_page_cap=settings.run_page_cap,
        system_run_page_cap=system_listing_run_page_cap,
        within_operator_cap=estimated_max_pages <= settings.run_page_cap,
        within_system_cap=estimated_max_pages <= system_listing_run_page_cap,
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
        system_listing_run_page_cap: int = DEFAULT_LISTING_SYSTEM_RUN_PAGE_CAP,
    ) -> None:
        if system_listing_run_page_cap < 1:
            raise ValueError("system_listing_run_page_cap must be positive")
        self.db = db
        self.adapters = dict(adapters or build_source_classification_adapters())
        self.registry = SourceClassificationRegistry(db)
        self.resolver = OrdinaryCrawlScopeResolver(db, adapters=self.adapters)
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
    ) -> CrawlScopePreviewV1:
        resolved = self._resolve(authored_scope)
        workload = (
            self.assess_listing_workload(resolved, listing_settings)
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
    ) -> ResolvedRunScopeV1:
        return self.preview(
            authored_scope,
            listing_settings=listing_settings,
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

    def _resolve(self, authored_scope: AuthoredCrawlScopeV1) -> ResolvedRunScopeV1:
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
