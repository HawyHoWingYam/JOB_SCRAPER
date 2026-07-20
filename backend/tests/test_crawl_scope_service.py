from __future__ import annotations

from dataclasses import dataclass, replace
from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.crawl_control.contracts import (
    AuthoredCrawlScopeV1,
    CrawlScopeRuleV1,
    DetailSettingsV1,
    ListingSettingsV1,
    QueryTargetSnapshotV1,
    contract_fingerprint,
)
from app.crawl_control.errors import (
    ScopeReviewRequiredError,
    ScopeRuleInvalidError,
    WorkloadCapExceededError,
)
from app.crawl_control.scope_service import CrawlScopeService
from app.services.source_catalog_service import PublishedSourceCatalog
from app.source_catalog.adapters import (
    CTgoodjobsSourceCatalogAdapter,
    JobsDBSourceCatalogAdapter,
    OfferTodaySourceCatalogAdapter,
)
from app.source_catalog.domain import (
    CatalogNodeSnapshot,
    CatalogScopeCapabilities,
    DiscoveredCatalog,
    SourceQueryTarget,
    payload_fingerprint,
)


@dataclass(frozen=True)
class FixtureRevision:
    id: UUID
    fingerprint: str


class FixtureCatalogGateway:
    def __init__(
        self,
        published: PublishedSourceCatalog,
        *,
        compiler: Callable[
            [PublishedSourceCatalog, CatalogNodeSnapshot],
            tuple[SourceQueryTarget, ...],
        ]
        | None = None,
    ) -> None:
        self.published = published
        self.compiler = compiler or (
            lambda _published, node: (_target_for_node(node),)
        )

    def get_published(self, source_site: str) -> PublishedSourceCatalog:
        assert source_site == self.published.catalog.source_site
        return self.published

    def compile_nodes(self, published, nodes):
        assert published.catalog.source_site == self.published.catalog.source_site
        return tuple(
            (node, target)
            for node in nodes
            for target in self.compiler(published, node)
        )


def _target_for_node(node: CatalogNodeSnapshot) -> SourceQueryTarget:
    assert node.classification_id is not None
    parameters = dict(node.source_metadata["target_parameters"])
    return SourceQueryTarget(
        adapter="offertoday.category",
        classification_id=node.classification_id,
        payload=parameters,
    )


def _queryable_node(
    *,
    classification_id: str,
    native_id: int,
    label: str,
    parent_node_key: str | None,
    native_path: tuple[str, ...],
    supports_subtree: bool,
    target_category_code: int | None = None,
    node_key: str | None = None,
) -> CatalogNodeSnapshot:
    source_site = classification_id.partition(":")[0]
    target = SourceQueryTarget(
        adapter="offertoday.category",
        classification_id=classification_id,
        payload={
            "category_code": target_category_code or native_id,
            "endpoint": "browse",
            "keyword": "",
            "rcd_type": 7,
        },
    )
    return CatalogNodeSnapshot(
        node_key=node_key or classification_id,
        source_site=source_site,
        classification_id=classification_id,
        native_id=native_id,
        native_label=label,
        parent_node_key=parent_node_key,
        native_path=native_path,
        depth=len(native_path) - 1,
        selectable=True,
        supports_exact=True,
        supports_subtree=supports_subtree,
        queryable=True,
        alias_of_node_key=None,
        query_semantics_hash=target.fingerprint,
        source_metadata={"target_parameters": dict(target.payload)},
    )


def _alias_node(*, root_label: str) -> CatalogNodeSnapshot:
    return CatalogNodeSnapshot(
        node_key="alias-a",
        source_site="offertoday",
        classification_id=None,
        native_id=10,
        native_label="A alias",
        parent_node_key="offertoday:1",
        native_path=(root_label, "A alias"),
        depth=1,
        selectable=False,
        supports_exact=False,
        supports_subtree=False,
        queryable=False,
        alias_of_node_key="offertoday:1",
        query_semantics_hash=None,
        source_metadata={},
    )


def _catalog(
    *,
    root_label: str = "Root",
    a_label: str = "A",
    include_a: bool = True,
    include_extra_descendant: bool = False,
    a_supports_subtree: bool = True,
    a_target_native_id: int = 10,
    alias_becomes_queryable: bool = False,
) -> DiscoveredCatalog:
    root = _queryable_node(
        classification_id="offertoday:1",
        native_id=1,
        label=root_label,
        parent_node_key=None,
        native_path=(root_label,),
        supports_subtree=True,
    )
    nodes: list[CatalogNodeSnapshot] = [root]
    if include_a:
        a = _queryable_node(
            classification_id="offertoday:10",
            native_id=10,
            label=a_label,
            parent_node_key=root.node_key,
            native_path=(root_label, a_label),
            supports_subtree=a_supports_subtree,
            target_category_code=a_target_native_id,
        )
        a1 = _queryable_node(
            classification_id="offertoday:11",
            native_id=11,
            label="A1",
            parent_node_key=a.node_key,
            native_path=(root_label, a_label, "A1"),
            supports_subtree=False,
        )
        nodes.extend((a, a1))
        if include_extra_descendant:
            nodes.append(
                _queryable_node(
                    classification_id="offertoday:12",
                    native_id=12,
                    label="A2",
                    parent_node_key=a.node_key,
                    native_path=(root_label, a_label, "A2"),
                    supports_subtree=False,
                )
            )
    nodes.append(
        _queryable_node(
            classification_id="offertoday:20",
            native_id=20,
            label="B",
            parent_node_key=root.node_key,
            native_path=(root_label, "B"),
            supports_subtree=False,
        )
    )
    if alias_becomes_queryable:
        nodes.append(
            _queryable_node(
                classification_id="offertoday:13",
                native_id=13,
                label="A alias",
                parent_node_key=root.node_key,
                native_path=(root_label, "A alias"),
                supports_subtree=False,
                node_key="alias-a",
            )
        )
    else:
        nodes.append(_alias_node(root_label=root_label))
    return DiscoveredCatalog(
        source_site="offertoday",
        nodes=tuple(nodes),
        capabilities=CatalogScopeCapabilities(
            supports_all_scope=True,
            all_scope_root_node_keys=(root.node_key,),
            recommended_scope={"mode": "all"},
        ),
        source_payload={},
        provenance={"method": "fixture"},
    )


def _published(catalog: DiscoveredCatalog) -> PublishedSourceCatalog:
    return PublishedSourceCatalog(
        revision=FixtureRevision(id=uuid4(), fingerprint=catalog.fingerprint),
        catalog=catalog,
    )


def _scope(
    published: PublishedSourceCatalog,
    *,
    mode: str = "rules",
    rules: tuple[CrawlScopeRuleV1, ...] = (),
) -> AuthoredCrawlScopeV1:
    return AuthoredCrawlScopeV1(
        source_site="offertoday",
        reviewed_catalog_revision_id=published.revision.id,
        mode=mode,
        rules=rules,
    )


def _rule(kind: str, classification_id: str) -> CrawlScopeRuleV1:
    return CrawlScopeRuleV1(kind=kind, classification_id=classification_id)


def _detail_settings() -> DetailSettingsV1:
    return DetailSettingsV1.model_validate(
        {
            "backlog_scope": {"kind": "source_backlog"},
            "limit": {"kind": "stop_after", "detail_run_cap": 100},
        }
    )


def test_authored_and_detail_contracts_require_explicit_versioned_shapes():
    revision_id = uuid4()
    with pytest.raises(ValidationError, match="All scope cannot contain"):
        AuthoredCrawlScopeV1(
            source_site="offertoday",
            reviewed_catalog_revision_id=revision_id,
            mode="all",
            rules=[_rule("exact", "offertoday:10")],
        )
    with pytest.raises(ValidationError, match="requires at least one"):
        AuthoredCrawlScopeV1(
            source_site="offertoday",
            reviewed_catalog_revision_id=revision_id,
            mode="rules",
        )
    with pytest.raises(ValidationError, match="exactly <source>:<token>"):
        CrawlScopeRuleV1(kind="exact", classification_id="100")
    with pytest.raises(ValidationError, match="belong to source_site"):
        AuthoredCrawlScopeV1(
            source_site="offertoday",
            reviewed_catalog_revision_id=revision_id,
            mode="rules",
            rules=[_rule("exact", "jobsdb:10")],
        )

    settings = DetailSettingsV1.model_validate(
        {
            "backlog_scope": {
                "kind": "listing_batch",
                "source_listing_crawl_job_id": str(uuid4()),
            },
            "limit": {"kind": "stop_after", "detail_run_cap": 25},
        }
    )
    assert settings.version == 1
    assert settings.backlog_scope.kind == "listing_batch"
    assert settings.limit.kind == "stop_after"

    source_backlog = DetailSettingsV1.model_validate(
        {
            "backlog_scope": {"kind": "source_backlog"},
            "limit": {"kind": "entire_snapshot"},
        }
    )
    assert DetailSettingsV1.model_validate(
        source_backlog.model_dump(mode="json")
    ) == source_backlog

    crawl_scope = DetailSettingsV1.model_validate(
        {
            "backlog_scope": {
                "kind": "crawl_scope",
                "scope": {
                    "source_site": "offertoday",
                    "reviewed_catalog_revision_id": str(revision_id),
                    "mode": "all",
                },
            },
            "limit": {"kind": "entire_snapshot"},
        }
    )
    assert crawl_scope.backlog_scope.kind == "crawl_scope"
    with pytest.raises(ValidationError, match="union_tag_invalid"):
        DetailSettingsV1.model_validate(
            {
                "backlog_scope": {"kind": "newest_batch"},
                "limit": {"kind": "entire_snapshot"},
            }
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DetailSettingsV1.model_validate(
            {
                "backlog_scope": {"kind": "source_backlog", "category": 10},
                "limit": {"kind": "entire_snapshot"},
            }
        )


@pytest.mark.parametrize(
    "classification_id",
    ("offertoday:", "offertoday:foo bar", "offertoday:foo:bar"),
)
def test_source_qualified_ids_reject_empty_ambiguous_or_extra_tokens(
    classification_id: str,
):
    with pytest.raises(ValidationError, match="exactly <source>:<token>"):
        CrawlScopeRuleV1(kind="exact", classification_id=classification_id)


def test_query_target_snapshots_accept_only_bounded_public_adapter_contracts():
    target = SourceQueryTarget(
        adapter="offertoday.category",
        classification_id="offertoday:10",
        payload={
            "category_code": 10,
            "endpoint": "browse",
            "keyword": "",
            "rcd_type": 7,
        },
    )
    snapshot = QueryTargetSnapshotV1.from_source_target(target)
    assert snapshot.query_target_fingerprint == target.fingerprint
    with pytest.raises(ValidationError, match="Instance is frozen"):
        snapshot.parameters.category_code = 20

    unsafe = SourceQueryTarget(
        adapter="offertoday.category",
        classification_id="offertoday:10",
        payload={**target.payload, "q": "Bearer sk-example"},
    )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        QueryTargetSnapshotV1.from_source_target(unsafe)


def test_every_production_adapter_compiles_to_the_public_snapshot_contract():
    adapters = (
        JobsDBSourceCatalogAdapter(),
        CTgoodjobsSourceCatalogAdapter(),
        OfferTodaySourceCatalogAdapter(),
    )
    for adapter in adapters:
        catalog = adapter.discover()
        node = next(item for item in catalog.nodes if item.queryable)
        target = adapter.compile(node)[0]
        snapshot = QueryTargetSnapshotV1.from_source_target(target)
        assert snapshot.parameter_payload == dict(target.payload)


def test_exact_subtree_and_all_resolve_deterministically_and_skip_aliases():
    published = _published(_catalog())
    service = CrawlScopeService(FixtureCatalogGateway(published))

    exact = service.preview(
        _scope(published, rules=(_rule("exact", "offertoday:10"),))
    ).resolved_scope
    subtree = service.preview(
        _scope(published, rules=(_rule("subtree", "offertoday:10"),))
    ).resolved_scope
    all_scope = service.preview(
        _scope(published, mode="all")
    ).resolved_scope

    assert [
        item.classification_id for item in exact.selected_classifications
    ] == ["offertoday:10"]
    assert [
        item.classification_id for item in subtree.selected_classifications
    ] == ["offertoday:10", "offertoday:11"]
    assert [
        item.classification_id for item in all_scope.selected_classifications
    ] == ["offertoday:1", "offertoday:10", "offertoday:11", "offertoday:20"]
    assert all("alias" not in item.node_key for item in all_scope.selected_classifications)
    assert all_scope.query_target_count == 4
    assert all_scope.fingerprint == contract_fingerprint(all_scope)
    assert all_scope.model_dump_json() == service.preview(
        _scope(published, mode="all")
    ).resolved_scope.model_dump_json()


def test_mixed_rule_canonicalization_removes_redundant_descendants_stably():
    published = _published(_catalog())
    service = CrawlScopeService(FixtureCatalogGateway(published))
    authored = _scope(
        published,
        rules=(
            _rule("exact", "offertoday:11"),
            _rule("subtree", "offertoday:10"),
            _rule("exact", "offertoday:20"),
            _rule("subtree", "offertoday:1"),
            _rule("exact", "offertoday:1"),
            _rule("subtree", "offertoday:1"),
        ),
    )

    resolved = service.preview(authored).resolved_scope

    assert resolved.authored_scope.rules == (
        _rule("subtree", "offertoday:1"),
    )
    assert resolved.query_target_count == 4


def test_equivalent_mixed_rule_orders_have_one_canonical_scope_and_fingerprint():
    published = _published(_catalog())
    service = CrawlScopeService(FixtureCatalogGateway(published))
    first = _scope(
        published,
        rules=(
            _rule("exact", "offertoday:20"),
            _rule("subtree", "offertoday:10"),
        ),
    )
    second = _scope(
        published,
        rules=(
            _rule("subtree", "offertoday:10"),
            _rule("exact", "offertoday:20"),
        ),
    )

    first_resolved = service.preview(first).resolved_scope
    second_resolved = service.preview(second).resolved_scope

    assert first_resolved.authored_scope == second_resolved.authored_scope
    assert first_resolved.fingerprint == second_resolved.fingerprint


def test_compiler_mapping_supports_multiple_targets_and_rejects_drift():
    catalog = _catalog()
    a_node = next(
        node for node in catalog.nodes if node.classification_id == "offertoday:10"
    )
    first_target = _target_for_node(a_node)
    second_target = SourceQueryTarget(
        adapter="offertoday.category",
        classification_id="offertoday:10",
        payload={
            "category_code": 1010,
            "endpoint": "browse",
            "keyword": "",
            "rcd_type": 7,
        },
    )
    multi_semantics = payload_fingerprint(
        [first_target.to_payload(), second_target.to_payload()]
    )
    multi_catalog = replace(
        catalog,
        nodes=tuple(
            replace(node, query_semantics_hash=multi_semantics)
            if node.node_key == a_node.node_key
            else node
            for node in catalog.nodes
        ),
    )
    published = _published(multi_catalog)

    def multi_compiler(_published, node):
        if node.classification_id == "offertoday:10":
            return (first_target, second_target)
        return (_target_for_node(node),)

    service = CrawlScopeService(
        FixtureCatalogGateway(published, compiler=multi_compiler)
    )
    authored = _scope(
        published,
        rules=(_rule("exact", "offertoday:10"),),
    )
    resolved = service.preview(authored).resolved_scope
    assert [
        target.query_target_fingerprint for target in resolved.query_targets
    ] == [first_target.fingerprint, second_target.fingerprint]

    empty_service = CrawlScopeService(
        FixtureCatalogGateway(
            published,
            compiler=lambda _published, _node: (),
        )
    )
    with pytest.raises(ScopeRuleInvalidError) as missing_target:
        empty_service.preview(authored)
    assert missing_target.value.context["catalog_error_code"] == (
        "CATALOG_QUERY_TARGET_MISSING"
    )

    wrong_target = replace(second_target, classification_id="offertoday:20")
    mismatched_service = CrawlScopeService(
        FixtureCatalogGateway(
            published,
            compiler=lambda _published, _node: (wrong_target,),
        )
    )
    with pytest.raises(ScopeRuleInvalidError) as mismatch:
        mismatched_service.preview(authored)
    assert mismatch.value.context["catalog_error_code"] == (
        "CATALOG_QUERY_TARGET_CLASSIFICATION_MISMATCH"
    )


def test_automation_resolution_includes_future_descendants_but_review_preview_stales():
    before = _published(_catalog())
    after = _published(_catalog(include_extra_descendant=True))
    gateway = FixtureCatalogGateway(after)
    service = CrawlScopeService(gateway)
    authored = _scope(
        before,
        rules=(_rule("subtree", "offertoday:10"),),
    )

    with pytest.raises(ScopeReviewRequiredError) as stale_preview:
        service.preview(authored)
    assert stale_preview.value.code == "SCOPE_REVIEW_REQUIRED"

    resolved = service.resolve_for_run(authored)
    assert [
        item.classification_id for item in resolved.selected_classifications
    ] == ["offertoday:10", "offertoday:11", "offertoday:12"]
    assert [warning.code for warning in resolved.warnings] == [
        "CATALOG_REVISION_ADVANCED"
    ]

    impact = service.assess_catalog_change(
        authored,
        before=before,
        after=after,
        execution_settings=_detail_settings(),
    )
    assert impact.status == "compatible"
    assert impact.reason_codes == ()


def test_label_changes_are_compatible_but_stale_and_changed_capabilities_require_review():
    before = _published(_catalog())
    label_only = _published(_catalog(root_label="New Root", a_label="New A"))
    missing = _published(_catalog(include_a=False))
    capability_changed = _published(_catalog(a_supports_subtree=False))
    service = CrawlScopeService(FixtureCatalogGateway(before))
    authored = _scope(
        before,
        rules=(_rule("subtree", "offertoday:10"),),
    )

    assert service.assess_catalog_change(
        authored,
        before=before,
        after=label_only,
        execution_settings=_detail_settings(),
    ).status == "compatible"

    missing_impact = service.assess_catalog_change(
        authored,
        before=before,
        after=missing,
        execution_settings=_detail_settings(),
    )
    assert missing_impact.status == "scope_review_required"
    assert "SCOPE_REFERENCE_MISSING" in missing_impact.reason_codes

    capability_impact = service.assess_catalog_change(
        authored,
        before=before,
        after=capability_changed,
        execution_settings=_detail_settings(),
    )
    assert capability_impact.status == "scope_review_required"
    assert "SCOPE_CAPABILITY_CHANGED" in capability_impact.reason_codes

    with pytest.raises(ScopeReviewRequiredError):
        service.resolve_against_published(authored, published=missing)


def test_unknown_current_rule_is_invalid_and_query_or_alias_changes_require_review():
    before = _published(_catalog())
    query_changed = _published(_catalog(a_target_native_id=999))
    alias_changed = _published(_catalog(alias_becomes_queryable=True))
    service = CrawlScopeService(FixtureCatalogGateway(before))

    unknown = _scope(
        before,
        rules=(_rule("exact", "offertoday:999"),),
    )
    with pytest.raises(ScopeRuleInvalidError) as invalid:
        service.preview(unknown)
    assert invalid.value.code == "SCOPE_RULE_INVALID"
    assert invalid.value.context["catalog_error_code"] == (
        "SOURCE_CLASSIFICATION_UNKNOWN"
    )

    exact = _scope(
        before,
        rules=(_rule("exact", "offertoday:10"),),
    )
    query_impact = service.assess_catalog_change(
        exact,
        before=before,
        after=query_changed,
        execution_settings=_detail_settings(),
    )
    assert "SCOPE_QUERY_SEMANTICS_CHANGED" in query_impact.reason_codes

    all_scope = _scope(before, mode="all")
    alias_impact = service.assess_catalog_change(
        all_scope,
        before=before,
        after=alias_changed,
        execution_settings=_detail_settings(),
    )
    assert "SCOPE_ALIAS_DEDUPLICATION_CHANGED" in alias_impact.reason_codes

    baseline_impact = service.assess_catalog_change(
        unknown,
        before=before,
        after=query_changed,
        execution_settings=_detail_settings(),
    )
    assert baseline_impact.reason_codes == ("SCOPE_BASELINE_INVALID",)


def test_all_scope_rejects_a_catalog_without_explicit_all_capability():
    catalog = _catalog()
    unsupported = replace(
        catalog,
        capabilities=replace(
            catalog.capabilities,
            supports_all_scope=False,
            all_scope_root_node_keys=(),
        ),
    )
    published = _published(unsupported)
    service = CrawlScopeService(FixtureCatalogGateway(published))

    with pytest.raises(ScopeRuleInvalidError) as invalid:
        service.preview(_scope(published, mode="all"))
    assert invalid.value.context["catalog_error_code"] == (
        "SOURCE_CLASSIFICATION_NOT_EXECUTABLE"
    )


def test_listing_workload_uses_target_count_page_depth_and_both_aggregate_caps():
    before = _published(_catalog())
    after = _published(_catalog(include_extra_descendant=True))
    service = CrawlScopeService(
        FixtureCatalogGateway(before),
        system_listing_run_page_cap=12,
    )
    authored = _scope(before, mode="all")

    preview = service.preview(
        authored,
        listing_settings=ListingSettingsV1(
            crawl_mode="headless",
            page_depth=3,
            run_page_cap=12,
        ),
    )
    assert preview.listing_workload is not None
    assert preview.listing_workload.estimated_max_pages == 12
    assert preview.listing_workload.dispatchable is True

    with pytest.raises(WorkloadCapExceededError) as over_cap:
        service.preview(
            authored,
            listing_settings=ListingSettingsV1(
                crawl_mode="headless",
                page_depth=3,
                run_page_cap=11,
            ),
        )
    assert over_cap.value.to_detail()["context"]["estimated_max_pages"] == 12

    system_limited = CrawlScopeService(
        FixtureCatalogGateway(before),
        system_listing_run_page_cap=11,
    )
    with pytest.raises(WorkloadCapExceededError) as system_cap:
        system_limited.preview(
            authored,
            listing_settings=ListingSettingsV1(
                crawl_mode="headless",
                page_depth=3,
                run_page_cap=12,
            ),
        )
    assert system_cap.value.context["system_run_page_cap"] == 11

    impact = service.assess_catalog_change(
        authored,
        before=before,
        after=after,
        execution_settings=ListingSettingsV1(
            crawl_mode="headless",
            page_depth=3,
            run_page_cap=12,
        ),
    )
    assert impact.status == "scope_review_required"
    assert "SCOPE_WORKLOAD_CAP_EXCEEDED" in impact.reason_codes
