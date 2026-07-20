from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.crawl_control.contracts import (
    AuthoredCrawlScopeV1,
    CrawlScopeErrorPayloadV1,
    CrawlScopeImpactV1,
    CrawlScopePreviewV1,
    CrawlScopeRuleV1,
    CrawlScopeWarningV1,
    DetailSettingsV1,
    ListingSettingsV1,
    ListingWorkloadPreviewV1,
    QueryTargetSnapshotV1,
    ResolvedRunScopeV1,
    ScopeImpactReasonCode,
    SelectedClassificationSnapshotV1,
)
from app.crawl_control.errors import (
    CrawlControlError,
    ScopeReviewRequiredError,
    ScopeRuleInvalidError,
    WorkloadCapExceededError,
)
from app.crawl_modes import get_supported_crawl_modes
from app.services.source_catalog_service import PublishedSourceCatalog
from app.source_catalog.domain import (
    CatalogNodeSnapshot,
    CatalogValidationError,
    DiscoveredCatalog,
    SourceQueryTarget,
    expand_catalog_scope,
    expansion_fingerprint,
    payload_fingerprint,
)


DEFAULT_LISTING_SYSTEM_RUN_PAGE_CAP = 1000


def evaluate_listing_workload(
    resolved_scope: ResolvedRunScopeV1,
    settings: ListingSettingsV1,
    *,
    system_listing_run_page_cap: int = DEFAULT_LISTING_SYSTEM_RUN_PAGE_CAP,
    enforce: bool = True,
) -> ListingWorkloadPreviewV1:
    """Evaluate reviewed listing workload without requiring a catalog gateway."""

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


class CrawlScopeCatalogGateway(Protocol):
    def get_published(self, source_site: str) -> PublishedSourceCatalog: ...

    def compile_nodes(
        self,
        published: PublishedSourceCatalog,
        nodes: Sequence[CatalogNodeSnapshot],
    ) -> tuple[tuple[CatalogNodeSnapshot, SourceQueryTarget], ...]: ...


class CrawlScopeService:
    """Resolve versioned Crawl Scope without duplicating Source Catalog logic."""

    def __init__(
        self,
        source_catalogs: CrawlScopeCatalogGateway,
        *,
        system_listing_run_page_cap: int = DEFAULT_LISTING_SYSTEM_RUN_PAGE_CAP,
    ) -> None:
        if system_listing_run_page_cap < 1:
            raise ValueError("system_listing_run_page_cap must be positive")
        self.source_catalogs = source_catalogs
        self.system_listing_run_page_cap = system_listing_run_page_cap

    def canonicalize(
        self,
        authored_scope: AuthoredCrawlScopeV1,
        *,
        published: PublishedSourceCatalog | None = None,
        require_reviewed_revision: bool = True,
    ) -> AuthoredCrawlScopeV1:
        selected_catalog = published or self.source_catalogs.get_published(
            authored_scope.source_site
        )
        self._validate_published_source(authored_scope, selected_catalog)
        if require_reviewed_revision:
            self._require_reviewed_revision(authored_scope, selected_catalog)
        canonical, _nodes = self._canonicalize_and_expand(
            authored_scope, selected_catalog.catalog
        )
        return canonical

    def preview(
        self,
        authored_scope: AuthoredCrawlScopeV1,
        *,
        listing_settings: ListingSettingsV1 | None = None,
    ) -> CrawlScopePreviewV1:
        published = self.source_catalogs.get_published(authored_scope.source_site)
        return self.resolve_against_published(
            authored_scope,
            published=published,
            listing_settings=listing_settings,
            require_reviewed_revision=True,
            enforce_workload=True,
        )

    def resolve_for_run(
        self,
        authored_scope: AuthoredCrawlScopeV1,
        *,
        listing_settings: ListingSettingsV1 | None = None,
    ) -> ResolvedRunScopeV1:
        published = self.source_catalogs.get_published(authored_scope.source_site)
        return self.resolve_against_published(
            authored_scope,
            published=published,
            listing_settings=listing_settings,
            require_reviewed_revision=False,
            enforce_workload=True,
        ).resolved_scope

    def resolve_against_published(
        self,
        authored_scope: AuthoredCrawlScopeV1,
        *,
        published: PublishedSourceCatalog,
        listing_settings: ListingSettingsV1 | None = None,
        require_reviewed_revision: bool = False,
        enforce_workload: bool = True,
    ) -> CrawlScopePreviewV1:
        resolved = self._resolve_published(
            authored_scope,
            published,
            require_reviewed_revision=require_reviewed_revision,
        )
        workload = None
        if listing_settings is not None:
            workload = self.assess_listing_workload(
                resolved,
                listing_settings,
                enforce=enforce_workload,
            )
        return CrawlScopePreviewV1(
            resolved_scope=resolved,
            listing_workload=workload,
        )

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

    def assess_catalog_change(
        self,
        authored_scope: AuthoredCrawlScopeV1,
        *,
        before: PublishedSourceCatalog,
        after: PublishedSourceCatalog,
        execution_settings: ListingSettingsV1 | DetailSettingsV1,
    ) -> CrawlScopeImpactV1:
        reasons: list[ScopeImpactReasonCode] = []
        blocking_errors: list[CrawlScopeErrorPayloadV1] = []
        listing_settings = (
            execution_settings
            if isinstance(execution_settings, ListingSettingsV1)
            else None
        )

        try:
            before_preview = self.resolve_against_published(
                authored_scope,
                published=before,
                listing_settings=listing_settings,
                require_reviewed_revision=False,
                enforce_workload=False,
            )
        except CrawlControlError as exc:
            self._append_reason(reasons, "SCOPE_BASELINE_INVALID")
            blocking_errors.append(exc.to_payload())
            return CrawlScopeImpactV1(
                status="scope_review_required",
                authored_scope=authored_scope,
                before=None,
                after=None,
                reason_codes=tuple(reasons),
                blocking_errors=tuple(blocking_errors),
            )

        for reason in self._authored_capability_reasons(
            authored_scope,
            before.catalog,
            after.catalog,
        ):
            self._append_reason(reasons, reason)

        after_preview: CrawlScopePreviewV1 | None = None
        try:
            after_preview = self.resolve_against_published(
                authored_scope,
                published=after,
                listing_settings=listing_settings,
                require_reviewed_revision=False,
                enforce_workload=False,
            )
        except CrawlControlError as exc:
            if not reasons:
                self._append_reason(reasons, "SCOPE_RESOLUTION_FAILED")
            blocking_errors.append(exc.to_payload())

        if after_preview is not None:
            before_targets = self._targets_by_classification(
                before_preview.resolved_scope
            )
            after_targets = self._targets_by_classification(
                after_preview.resolved_scope
            )
            for classification_id in before_targets.keys() & after_targets.keys():
                if before_targets[classification_id] != after_targets[classification_id]:
                    self._append_reason(
                        reasons, "SCOPE_QUERY_SEMANTICS_CHANGED"
                    )
                    break

            if self._alias_deduplication_changed(
                authored_scope,
                before.catalog,
                after.catalog,
            ):
                self._append_reason(
                    reasons, "SCOPE_ALIAS_DEDUPLICATION_CHANGED"
                )

            after_workload = after_preview.listing_workload
            if after_workload is not None and not after_workload.dispatchable:
                self._append_reason(
                    reasons, "SCOPE_WORKLOAD_CAP_EXCEEDED"
                )

        status = "scope_review_required" if reasons else "compatible"
        return CrawlScopeImpactV1(
            status=status,
            authored_scope=before_preview.resolved_scope.authored_scope,
            before=before_preview.resolved_scope,
            after=(
                after_preview.resolved_scope
                if after_preview is not None
                else None
            ),
            before_listing_workload=before_preview.listing_workload,
            after_listing_workload=(
                after_preview.listing_workload
                if after_preview is not None
                else None
            ),
            reason_codes=tuple(reasons),
            blocking_errors=tuple(blocking_errors),
        )

    def _resolve_published(
        self,
        authored_scope: AuthoredCrawlScopeV1,
        published: PublishedSourceCatalog,
        *,
        require_reviewed_revision: bool,
    ) -> ResolvedRunScopeV1:
        self._validate_published_source(authored_scope, published)
        if require_reviewed_revision:
            self._require_reviewed_revision(authored_scope, published)
        try:
            canonical_scope, selected_nodes = self._canonicalize_and_expand(
                authored_scope, published.catalog
            )
            compiled = self.source_catalogs.compile_nodes(
                published, selected_nodes
            )
            self._validate_compiled_selection(selected_nodes, compiled)
            selected_snapshots = tuple(
                SelectedClassificationSnapshotV1.from_catalog_node(node)
                for node in selected_nodes
            )
            target_snapshots = tuple(
                QueryTargetSnapshotV1.from_source_target(target)
                for _node, target in compiled
            )
        except CatalogValidationError as exc:
            raise self._catalog_scope_error(authored_scope, published, exc) from exc
        except ValueError as exc:
            raise self._catalog_scope_error(authored_scope, published, exc) from exc

        if not selected_snapshots or not target_snapshots:
            raise self._catalog_scope_error(
                authored_scope,
                published,
                ValueError("Crawl Scope resolved to no executable Query Targets"),
            )

        warnings: tuple[CrawlScopeWarningV1, ...] = ()
        if str(authored_scope.reviewed_catalog_revision_id) != str(
            published.revision.id
        ):
            warnings = (
                CrawlScopeWarningV1(
                    code="CATALOG_REVISION_ADVANCED",
                    message=(
                        "Crawl Scope was resolved against a newer published "
                        "Source Catalog revision"
                    ),
                    context={
                        "reviewed_catalog_revision_id": str(
                            authored_scope.reviewed_catalog_revision_id
                        ),
                        "resolved_catalog_revision_id": str(
                            published.revision.id
                        ),
                    },
                ),
            )

        return ResolvedRunScopeV1(
            source_site=canonical_scope.source_site,
            catalog_revision_id=published.revision.id,
            catalog_revision_fingerprint=published.revision.fingerprint,
            authored_scope=canonical_scope,
            selected_classifications=selected_snapshots,
            classification_expansion_hash=expansion_fingerprint(
                selected_nodes
            ),
            query_targets=target_snapshots,
            query_target_count=len(target_snapshots),
            warnings=warnings,
        )

    @staticmethod
    def _validate_published_source(
        authored_scope: AuthoredCrawlScopeV1,
        published: PublishedSourceCatalog,
    ) -> None:
        if published.catalog.source_site != authored_scope.source_site:
            raise ScopeRuleInvalidError(
                "Published Source Catalog belongs to another source",
                context={
                    "scope_source_site": authored_scope.source_site,
                    "catalog_source_site": published.catalog.source_site,
                },
            )

    @staticmethod
    def _require_reviewed_revision(
        authored_scope: AuthoredCrawlScopeV1,
        published: PublishedSourceCatalog,
    ) -> None:
        if str(authored_scope.reviewed_catalog_revision_id) == str(
            published.revision.id
        ):
            return
        raise ScopeReviewRequiredError(
            "The reviewed Source Catalog revision is no longer active",
            context={
                "reviewed_catalog_revision_id": str(
                    authored_scope.reviewed_catalog_revision_id
                ),
                "current_catalog_revision_id": str(published.revision.id),
            },
        )

    def _canonicalize_and_expand(
        self,
        authored_scope: AuthoredCrawlScopeV1,
        catalog: DiscoveredCatalog,
    ) -> tuple[AuthoredCrawlScopeV1, tuple[CatalogNodeSnapshot, ...]]:
        if authored_scope.mode == "all":
            try:
                selected = expand_catalog_scope(catalog, mode="all")
            except CatalogValidationError:
                raise
            return authored_scope, selected

        by_classification = {
            node.classification_id: node
            for node in catalog.nodes
            if node.classification_id is not None
        }
        validated_rules: list[tuple[CrawlScopeRuleV1, CatalogNodeSnapshot]] = []
        for rule in authored_scope.rules:
            node = by_classification.get(rule.classification_id)
            if node is None:
                raise CatalogValidationError(
                    "SOURCE_CLASSIFICATION_UNKNOWN",
                    f"Unknown Source Classification {rule.classification_id!r}",
                )
            if rule.kind == "exact" and (
                not node.supports_exact or not node.queryable
            ):
                raise CatalogValidationError(
                    "SOURCE_CLASSIFICATION_NOT_EXECUTABLE",
                    f"Source Classification {rule.classification_id!r} "
                    "has no exact query",
                    node_key=node.node_key,
                )
            if rule.kind == "subtree" and not node.supports_subtree:
                raise CatalogValidationError(
                    "SOURCE_CLASSIFICATION_NOT_EXECUTABLE",
                    f"Source Classification {rule.classification_id!r} "
                    "does not support subtree scope",
                    node_key=node.node_key,
                )
            validated_rules.append((rule, node))

        subtree_nodes = tuple(
            node for rule, node in validated_rules if rule.kind == "subtree"
        )
        canonical_rules: list[CrawlScopeRuleV1] = []
        for rule, node in validated_rules:
            if rule.kind == "subtree":
                if any(
                    other.node_key != node.node_key
                    and self._is_descendant_or_self(catalog, other, node)
                    for other in subtree_nodes
                ):
                    continue
            elif any(
                self._is_descendant_or_self(catalog, subtree, node)
                for subtree in subtree_nodes
            ):
                continue
            canonical_rules.append(rule)

        catalog_order = {
            node.classification_id: index
            for index, node in enumerate(catalog.nodes)
            if node.classification_id is not None
        }
        canonical_scope = authored_scope.model_copy(
            update={
                "rules": tuple(
                    sorted(
                        canonical_rules,
                        key=lambda rule: catalog_order[rule.classification_id],
                    )
                )
            }
        )
        selected_node_keys: set[str] = set()
        for rule in canonical_scope.rules:
            expanded = expand_catalog_scope(
                catalog,
                mode=rule.kind,
                classification_ids=(rule.classification_id,),
            )
            for node in expanded:
                selected_node_keys.add(node.node_key)
        selected = tuple(
            node for node in catalog.nodes if node.node_key in selected_node_keys
        )
        return canonical_scope, selected

    @staticmethod
    def _validate_compiled_selection(
        selected_nodes: Sequence[CatalogNodeSnapshot],
        compiled: Sequence[tuple[CatalogNodeSnapshot, SourceQueryTarget]],
    ) -> None:
        selected_by_key = {node.node_key: node for node in selected_nodes}
        targets_by_node: dict[str, list[SourceQueryTarget]] = {}
        seen_target_fingerprints: set[str] = set()
        for node, target in compiled:
            selected = selected_by_key.get(node.node_key)
            if selected is None:
                raise CatalogValidationError(
                    "CATALOG_QUERY_TARGET_CLASSIFICATION_MISMATCH",
                    "Compiler returned a Query Target for an unselected node",
                    node_key=node.node_key,
                )
            if target.classification_id != selected.classification_id:
                raise CatalogValidationError(
                    "CATALOG_QUERY_TARGET_CLASSIFICATION_MISMATCH",
                    "Query Target identity differs from its Source Classification",
                    node_key=node.node_key,
                )
            if target.fingerprint in seen_target_fingerprints:
                raise CatalogValidationError(
                    "CATALOG_QUERY_TARGET_DUPLICATE",
                    "Two selected nodes compiled to the same Query Target",
                    node_key=node.node_key,
                )
            seen_target_fingerprints.add(target.fingerprint)
            targets_by_node.setdefault(node.node_key, []).append(target)

        for node in selected_nodes:
            targets = targets_by_node.get(node.node_key, [])
            if not targets:
                raise CatalogValidationError(
                    "CATALOG_QUERY_TARGET_MISSING",
                    "Selected Source Classification compiled to no Query Target",
                    node_key=node.node_key,
                )
            semantics_hash = (
                targets[0].fingerprint
                if len(targets) == 1
                else payload_fingerprint(
                    [target.to_payload() for target in targets]
                )
            )
            if node.query_semantics_hash != semantics_hash:
                raise CatalogValidationError(
                    "CATALOG_QUERY_SEMANTICS_MISMATCH",
                    "Selected node semantics differ from its Query Targets",
                    node_key=node.node_key,
                )

    @staticmethod
    def _is_descendant_or_self(
        catalog: DiscoveredCatalog,
        ancestor: CatalogNodeSnapshot,
        node: CatalogNodeSnapshot,
    ) -> bool:
        by_key = {item.node_key: item for item in catalog.nodes}
        current: CatalogNodeSnapshot | None = node
        while current is not None:
            if current.node_key == ancestor.node_key:
                return True
            current = (
                by_key.get(current.parent_node_key)
                if current.parent_node_key is not None
                else None
            )
        return False

    @staticmethod
    def _catalog_scope_error(
        authored_scope: AuthoredCrawlScopeV1,
        published: PublishedSourceCatalog,
        exc: ValueError,
    ) -> CrawlControlError:
        catalog_error_code = getattr(exc, "code", "SCOPE_RESOLUTION_FAILED")
        context = {
            "source_site": authored_scope.source_site,
            "catalog_revision_id": str(published.revision.id),
            "catalog_error_code": str(catalog_error_code),
        }
        if str(authored_scope.reviewed_catalog_revision_id) != str(
            published.revision.id
        ):
            return ScopeReviewRequiredError(str(exc), context=context)
        return ScopeRuleInvalidError(str(exc), context=context)

    @staticmethod
    def _targets_by_classification(
        resolved: ResolvedRunScopeV1,
    ) -> dict[str, tuple[str, ...]]:
        grouped: dict[str, list[str]] = {}
        for target in resolved.query_targets:
            grouped.setdefault(target.classification_id, []).append(
                target.query_target_fingerprint
            )
        return {
            classification_id: tuple(fingerprints)
            for classification_id, fingerprints in grouped.items()
        }

    def _authored_capability_reasons(
        self,
        authored_scope: AuthoredCrawlScopeV1,
        before: DiscoveredCatalog,
        after: DiscoveredCatalog,
    ) -> tuple[ScopeImpactReasonCode, ...]:
        if authored_scope.mode == "all":
            if (
                before.capabilities.supports_all_scope
                and not after.capabilities.supports_all_scope
            ):
                return ("SCOPE_CAPABILITY_CHANGED",)
            return ()

        before_nodes = {
            node.classification_id: node
            for node in before.nodes
            if node.classification_id is not None
        }
        after_nodes = {
            node.classification_id: node
            for node in after.nodes
            if node.classification_id is not None
        }
        reasons: list[ScopeImpactReasonCode] = []
        for rule in authored_scope.rules:
            before_node = before_nodes.get(rule.classification_id)
            after_node = after_nodes.get(rule.classification_id)
            if before_node is None or after_node is None:
                self._append_reason(reasons, "SCOPE_REFERENCE_MISSING")
                continue
            before_capability = (
                before_node.supports_exact and before_node.queryable
                if rule.kind == "exact"
                else before_node.supports_subtree
            )
            after_capability = (
                after_node.supports_exact and after_node.queryable
                if rule.kind == "exact"
                else after_node.supports_subtree
            )
            if before_capability != after_capability or not after_capability:
                self._append_reason(reasons, "SCOPE_CAPABILITY_CHANGED")
        return tuple(reasons)

    def _alias_deduplication_changed(
        self,
        authored_scope: AuthoredCrawlScopeV1,
        before: DiscoveredCatalog,
        after: DiscoveredCatalog,
    ) -> bool:
        before_covered = {
            node.node_key: node
            for node in self._covered_catalog_nodes(authored_scope, before)
        }
        after_covered = {
            node.node_key: node
            for node in self._covered_catalog_nodes(authored_scope, after)
        }
        for node_key in before_covered.keys() & after_covered.keys():
            previous = before_covered[node_key]
            current = after_covered[node_key]
            if (
                previous.alias_of_node_key,
                previous.classification_id,
                previous.queryable,
            ) != (
                current.alias_of_node_key,
                current.classification_id,
                current.queryable,
            ) and (
                previous.alias_of_node_key is not None
                or current.alias_of_node_key is not None
            ):
                return True
        return False

    @staticmethod
    def _covered_catalog_nodes(
        authored_scope: AuthoredCrawlScopeV1,
        catalog: DiscoveredCatalog,
    ) -> tuple[CatalogNodeSnapshot, ...]:
        by_key = {node.node_key: node for node in catalog.nodes}
        by_classification = {
            node.classification_id: node
            for node in catalog.nodes
            if node.classification_id is not None
        }
        children: dict[str, list[CatalogNodeSnapshot]] = {}
        for node in catalog.nodes:
            if node.parent_node_key is not None:
                children.setdefault(node.parent_node_key, []).append(node)

        selected: list[CatalogNodeSnapshot] = []
        seen: set[str] = set()

        def include(node: CatalogNodeSnapshot, *, descendants: bool) -> None:
            if node.node_key not in seen:
                selected.append(node)
                seen.add(node.node_key)
            if descendants:
                for child in children.get(node.node_key, ()):
                    include(child, descendants=True)

        if authored_scope.mode == "all":
            for root_key in catalog.capabilities.all_scope_root_node_keys:
                root = by_key.get(root_key)
                if root is not None:
                    include(root, descendants=True)
            return tuple(selected)

        for rule in authored_scope.rules:
            node = by_classification.get(rule.classification_id)
            if node is not None:
                include(node, descendants=rule.kind == "subtree")
        return tuple(selected)

    @staticmethod
    def _append_reason(
        reasons: list[ScopeImpactReasonCode],
        reason: ScopeImpactReasonCode,
    ) -> None:
        if reason not in reasons:
            reasons.append(reason)
