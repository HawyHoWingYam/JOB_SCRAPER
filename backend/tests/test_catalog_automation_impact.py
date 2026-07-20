from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.crawl_control.automation_contracts import AutomationConfigurationV1
from app.crawl_control.automation_service import AutomationService
from app.crawl_control.catalog_impact import AutomationCatalogImpactEvaluator
from app.crawl_control.contracts import (
    AuthoredCrawlScopeV1,
    CrawlScopeRuleV1,
    ListingSettingsV1,
)
from app.crawl_control.scope_service import CrawlScopeService
from app.models.schedule import AutomationRevision, ScrapeSchedule
from app.models.source_catalog import SOURCE_CATALOG_TABLES, SourceCatalogCandidate
from app.repositories.source_catalog_repository import SourceCatalogRepository
from app.services.source_catalog_service import SourceCatalogService
from app.source_catalog.domain import (
    CatalogNodeSnapshot,
    CatalogScopeCapabilities,
    DiscoveredCatalog,
    SourceQueryTarget,
)


@compiles(PostgreSQLUUID, "sqlite")
def compile_uuid_for_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(32)"


class MutableTreeCatalogAdapter:
    source_site = "jobsdb"

    def __init__(self) -> None:
        self.root_label = "Technology"
        self.include_extra = False
        self.child_native_id = 101
        self.move_child_to_root = False

    @staticmethod
    def _target(classification_id: str, native_id: int) -> SourceQueryTarget:
        return SourceQueryTarget(
            adapter="jobsdb.classification",
            classification_id=classification_id,
            payload={"native_id": native_id},
        )

    def _node(
        self,
        *,
        classification_id: str,
        native_id: int,
        label: str,
        parent: str | None,
        path: tuple[str, ...],
    ) -> CatalogNodeSnapshot:
        target = self._target(classification_id, native_id)
        return CatalogNodeSnapshot(
            node_key=classification_id,
            source_site=self.source_site,
            classification_id=classification_id,
            native_id=native_id,
            native_label=label,
            parent_node_key=parent,
            native_path=path,
            depth=len(path) - 1,
            selectable=True,
            supports_exact=True,
            supports_subtree=True,
            queryable=True,
            alias_of_node_key=None,
            query_semantics_hash=target.fingerprint,
            source_metadata={},
        )

    def discover(self) -> DiscoveredCatalog:
        root_id = "jobsdb:100"
        nodes = [
            self._node(
                classification_id=root_id,
                native_id=100,
                label=self.root_label,
                parent=None,
                path=(self.root_label,),
            ),
            self._node(
                classification_id="jobsdb:101",
                native_id=self.child_native_id,
                label="Software",
                parent=(None if self.move_child_to_root else root_id),
                path=(
                    ("Software",)
                    if self.move_child_to_root
                    else (self.root_label, "Software")
                ),
            ),
        ]
        if self.include_extra:
            nodes.append(
                self._node(
                    classification_id="jobsdb:102",
                    native_id=102,
                    label="Data",
                    parent=root_id,
                    path=(self.root_label, "Data"),
                )
            )
        return DiscoveredCatalog(
            source_site=self.source_site,
            nodes=tuple(nodes),
            capabilities=CatalogScopeCapabilities(
                True,
                (
                    (root_id, "jobsdb:101")
                    if self.move_child_to_root
                    else (root_id,)
                ),
                {"mode": "all"},
            ),
            source_payload={"fixture": [node.native_id for node in nodes]},
            provenance={"method": "catalog-impact-test"},
        )

    def compile(self, node: CatalogNodeSnapshot):
        return (
            self._target(
                str(node.classification_id),
                int(node.native_id),
            ),
        )


@pytest.fixture
def catalog_impact_db():
    engine = create_engine("sqlite:///:memory:")
    SourceCatalogCandidate.metadata.create_all(
        engine,
        tables=(
            *SOURCE_CATALOG_TABLES,
            ScrapeSchedule.__table__,
            AutomationRevision.__table__,
        ),
    )
    db = sessionmaker(bind=engine)()
    repository = SourceCatalogRepository()
    adapter = MutableTreeCatalogAdapter()
    catalogs = SourceCatalogService(
        db,
        repository=repository,
        adapters={"jobsdb": adapter},
    )
    evaluator = AutomationCatalogImpactEvaluator(
        db,
        source_catalog_repository=repository,
        adapters={"jobsdb": adapter},
    )
    governed_catalogs = SourceCatalogService(
        db,
        repository=repository,
        adapters={"jobsdb": adapter},
        impact_evaluator=evaluator,
    )
    try:
        yield db, repository, adapter, catalogs, governed_catalogs
    finally:
        db.close()
        engine.dispose()


def _validate_candidate(service, repository, db):
    candidate, _created = service.discover("jobsdb")
    repository.mark_candidate_validated(db, candidate=candidate)
    return candidate


def _publish_candidate(service, repository, db):
    candidate = _validate_candidate(service, repository, db)
    review = service.review_publication(
        candidate.id,
        actor="local-operator",
    )
    revision = service.publish(
        candidate.id,
        review_token=review.review_token,
        actor="local-operator",
    )
    return candidate, revision, review


def _automation_service(db, catalogs) -> AutomationService:
    return AutomationService(
        db,
        scope_service=CrawlScopeService(catalogs),
    )


def _create_listing_automation(
    service: AutomationService,
    *,
    catalog_revision_id,
    name: str,
    run_page_cap: int,
    classification_id: str | None = None,
):
    scope = AuthoredCrawlScopeV1(
        source_site="jobsdb",
        reviewed_catalog_revision_id=catalog_revision_id,
        mode="rules" if classification_id else "all",
        rules=(
            (
                CrawlScopeRuleV1(
                    kind="exact",
                    classification_id=classification_id,
                ),
            )
            if classification_id
            else ()
        ),
    )
    return service.create(
        AutomationConfigurationV1(
            name=name,
            cron_expression="0 4 * * *",
            timezone="UTC",
            scope=scope,
            listing_settings=ListingSettingsV1(
                crawl_mode="headless",
                page_depth=2 if classification_id is None else 1,
                run_page_cap=run_page_cap,
            ),
        ),
        actor="local-operator",
        initial_state="active",
    )


def test_publication_applies_real_automation_impact_atomically(
    catalog_impact_db,
    monkeypatch,
):
    db, repository, adapter, catalogs, governed_catalogs = catalog_impact_db
    _candidate, initial_revision, _review = _publish_candidate(
        governed_catalogs,
        repository,
        db,
    )
    automations = _automation_service(db, catalogs)
    capped = _create_listing_automation(
        automations,
        catalog_revision_id=initial_revision.id,
        name="Cap-sensitive Automation",
        run_page_cap=4,
    )
    roomy = _create_listing_automation(
        automations,
        catalog_revision_id=initial_revision.id,
        name="Future-descendant Automation",
        run_page_cap=10,
    )

    adapter.root_label = "Digital Technology"
    label_candidate = _validate_candidate(governed_catalogs, repository, db)
    label_review = governed_catalogs.review_publication(
        label_candidate.id,
        actor="local-operator",
    )
    assert label_review.impact["compatible_count"] == 2
    assert label_review.impact["scope_review_required_count"] == 0
    label_revision = governed_catalogs.publish(
        label_candidate.id,
        review_token=label_review.review_token,
        actor="local-operator",
    )
    assert automations.get(capped.snapshot.automation_id).snapshot.revision == 1
    assert automations.get(roomy.snapshot.automation_id).snapshot.revision == 1

    adapter.include_extra = True
    expansion_candidate = _validate_candidate(governed_catalogs, repository, db)
    expansion_review = governed_catalogs.review_publication(
        expansion_candidate.id,
        actor="local-operator",
    )
    assert expansion_review.impact["versioned_automation_count"] == 2
    assert expansion_review.impact["compatible_count"] == 1
    assert expansion_review.impact["scope_review_required_count"] == 1
    impacted = {
        item["automation_id"]: item
        for item in expansion_review.impact["automations"]
    }
    capped_impact = impacted[str(capped.snapshot.automation_id)]
    assert capped_impact["impact"]["reason_codes"] == [
        "SCOPE_WORKLOAD_CAP_EXCEEDED"
    ]
    assert capped_impact["impact"]["after"]["query_target_count"] == 3

    expansion_revision = governed_catalogs.publish(
        expansion_candidate.id,
        review_token=expansion_review.review_token,
        actor="local-operator",
    )
    capped_after = automations.get(capped.snapshot.automation_id).snapshot
    roomy_after = automations.get(roomy.snapshot.automation_id).snapshot
    assert capped_after.revision == 2
    assert capped_after.lifecycle_state == "scope_review_required"
    assert capped_after.scope_review_reason is not None
    assert roomy_after.revision == 1
    assert roomy_after.lifecycle_state == "active"

    adapter.child_native_id = 999
    failing_candidate = _validate_candidate(governed_catalogs, repository, db)
    failing_review = governed_catalogs.review_publication(
        failing_candidate.id,
        actor="local-operator",
    )
    original_append = repository.append_publication

    def fail_publication(*_args, **_kwargs):
        raise RuntimeError("injected publication audit failure")

    monkeypatch.setattr(repository, "append_publication", fail_publication)
    with pytest.raises(RuntimeError, match="injected publication audit failure"):
        governed_catalogs.publish(
            failing_candidate.id,
            review_token=failing_review.review_token,
            actor="local-operator",
        )
    monkeypatch.setattr(repository, "append_publication", original_append)

    db.expire_all()
    assert repository.get_active_revision(
        db,
        source_site="jobsdb",
    ).id == expansion_revision.id
    assert automations.get(capped.snapshot.automation_id).snapshot.revision == 2
    assert automations.get(roomy.snapshot.automation_id).snapshot.revision == 1
    assert label_revision.id != expansion_revision.id


def test_rollback_marks_automation_whose_scope_is_missing_from_target_revision(
    catalog_impact_db,
):
    db, repository, adapter, catalogs, governed_catalogs = catalog_impact_db
    _candidate, base_revision, _review = _publish_candidate(
        governed_catalogs,
        repository,
        db,
    )
    adapter.include_extra = True
    _candidate, expanded_revision, _review = _publish_candidate(
        governed_catalogs,
        repository,
        db,
    )
    automations = _automation_service(db, catalogs)
    exact_extra = _create_listing_automation(
        automations,
        catalog_revision_id=expanded_revision.id,
        name="New classification Automation",
        run_page_cap=1,
        classification_id="jobsdb:102",
    )

    review = governed_catalogs.review_rollback(
        base_revision.id,
        actor="local-operator",
    )
    assert review.impact["scope_review_required_count"] == 1
    assert review.impact["automations"][0]["impact"]["reason_codes"] == [
        "SCOPE_REFERENCE_MISSING"
    ]

    active = governed_catalogs.rollback(
        base_revision.id,
        review_token=review.review_token,
        actor="local-operator",
    )

    assert active.id == base_revision.id
    snapshot = automations.get(exact_extra.snapshot.automation_id).snapshot
    assert snapshot.revision == 2
    assert snapshot.lifecycle_state == "scope_review_required"
    assert snapshot.scope_review_reason is not None


def test_initial_publication_reports_legacy_reset_warning(catalog_impact_db):
    db, repository, _adapter, _catalogs, governed_catalogs = catalog_impact_db
    db.add(
        ScrapeSchedule(
            name="Legacy schedule awaiting cutover",
            cron_expression="0 4 * * *",
            timezone="UTC",
            source_site="jobsdb",
            crawl_phase="listing",
            crawl_mode="headless",
            category_ids=[100],
            max_pages=1,
            detail_limit=100,
            revision=1,
            lifecycle_state="active",
            scope_contract=None,
            is_active=True,
        )
    )
    db.commit()
    candidate = _validate_candidate(governed_catalogs, repository, db)

    review = governed_catalogs.review_publication(
        candidate.id,
        actor="local-operator",
    )

    assert review.impact["versioned_automation_count"] == 0
    assert review.impact["legacy_automation_count"] == 1
    assert review.impact["warnings"] == [
        {
            "code": "LEGACY_CRAWL_CONTROL_RESET_REQUIRED",
            "message": (
                "Legacy Crawl Control rows require the approved maintenance "
                "cutover before versioned dispatch"
            ),
            "count": 1,
        }
    ]
    published = governed_catalogs.publish(
        candidate.id,
        review_token=review.review_token,
        actor="local-operator",
    )
    assert published.source_site == "jobsdb"


def test_hierarchy_move_with_stable_identity_and_query_semantics_is_compatible(
    catalog_impact_db,
):
    db, repository, adapter, catalogs, governed_catalogs = catalog_impact_db
    _candidate, base_revision, _review = _publish_candidate(
        governed_catalogs,
        repository,
        db,
    )
    automations = _automation_service(db, catalogs)
    exact = _create_listing_automation(
        automations,
        catalog_revision_id=base_revision.id,
        name="Move-compatible Automation",
        run_page_cap=1,
        classification_id="jobsdb:101",
    )
    adapter.move_child_to_root = True
    candidate = _validate_candidate(governed_catalogs, repository, db)

    review = governed_catalogs.review_publication(
        candidate.id,
        actor="local-operator",
    )

    assert review.impact["compatible_count"] == 1
    assert review.impact["scope_review_required_count"] == 0
    governed_catalogs.publish(
        candidate.id,
        review_token=review.review_token,
        actor="local-operator",
    )
    snapshot = automations.get(exact.snapshot.automation_id).snapshot
    assert snapshot.revision == 1
    assert snapshot.lifecycle_state == "active"
