from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.crawl_control.contracts import AuthoredCrawlScopeV1, ListingSettingsV1
from app.crawl_control.errors import ScopeRuleInvalidError, WorkloadCapExceededError
from app.crawl_control.scope_service import CrawlScopeService
from app.models.source_classification import SourceClassification
from app.services.source_classification_registry import (
    ObservedSourceClassification,
    SourceClassificationRegistry,
)
from app.source_classifications.domain import SourceQueryTarget


class JobsDBAdapter:
    source_site = "jobsdb"

    @staticmethod
    def compile(node):
        return (
            SourceQueryTarget(
                adapter="jobsdb.classification",
                classification_id=node.classification_id,
                payload={"native_id": int(node.native_id)},
            ),
        )


@compiles(UUID, "sqlite")
def compile_uuid_for_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(32)"


@pytest.fixture()
def scope_db():
    engine = create_engine("sqlite:///:memory:")
    SourceClassification.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        SourceClassification.__table__.drop(engine)
        engine.dispose()


def _seed(db):
    SourceClassificationRegistry(db).synchronize(
        "jobsdb",
        (
            ObservedSourceClassification(
                classification_id="jobsdb:6281",
                native_id="6281",
                label="Information Technology",
                depth=0,
                query_metadata={"queryable": True, "supports_exact": True},
            ),
            ObservedSourceClassification(
                classification_id="jobsdb:1200",
                native_id="1200",
                label="Accounting",
                depth=0,
                query_metadata={"queryable": True, "supports_exact": True},
            ),
            ObservedSourceClassification(
                classification_id="jobsdb:6287",
                native_id="6287",
                label="Developers",
                depth=1,
                parent_classification_id="jobsdb:6281",
                query_metadata={"queryable": True, "supports_exact": True},
            ),
        ),
        complete=True,
    )
    db.commit()


def test_authored_scope_is_only_all_or_selected_top_level_ids():
    selected = AuthoredCrawlScopeV1(
        source_site="jobsdb",
        mode="selected",
        classification_ids=("jobsdb:6281", "jobsdb:6281"),
    )
    assert selected.classification_ids == ("jobsdb:6281",)

    with pytest.raises(ValueError, match="Selected scope requires"):
        AuthoredCrawlScopeV1(source_site="jobsdb", mode="selected")
    with pytest.raises(ValueError, match="belong to source_site"):
        AuthoredCrawlScopeV1(
            source_site="jobsdb",
            mode="selected",
            classification_ids=("offertoday:118000",),
        )


def test_selected_scope_resolves_active_root_and_query_snapshot(scope_db):
    _seed(scope_db)
    service = CrawlScopeService(scope_db, adapters={"jobsdb": JobsDBAdapter()})

    preview = service.preview(
        AuthoredCrawlScopeV1(
            source_site="jobsdb",
            mode="selected",
            classification_ids=("jobsdb:6281",),
        ),
        listing_settings=ListingSettingsV1(
            crawl_mode="headless",
            page_depth=2,
            run_page_cap=2,
        ),
    )

    assert preview.resolved_scope.authored_scope.classification_ids == (
        "jobsdb:6281",
    )
    assert preview.resolved_scope.query_targets[0].parameter_payload == {
        "native_id": 6281
    }
    assert preview.listing_workload is not None
    assert preview.listing_workload.estimated_max_pages == 2


def test_all_scope_uses_every_active_root_but_never_children(scope_db):
    _seed(scope_db)
    row = scope_db.query(SourceClassification).filter_by(
        classification_id="jobsdb:1200"
    ).one()
    row.is_active = False
    scope_db.commit()
    service = CrawlScopeService(scope_db, adapters={"jobsdb": JobsDBAdapter()})

    resolved = service.resolve_for_run(
        AuthoredCrawlScopeV1(source_site="jobsdb", mode="all")
    )

    assert resolved.authored_scope.classification_ids == ()
    assert tuple(
        item.classification_id for item in resolved.selected_classifications
    ) == ("jobsdb:6281",)


def test_selected_scope_rejects_inactive_or_child_classification(scope_db):
    _seed(scope_db)
    service = CrawlScopeService(scope_db, adapters={"jobsdb": JobsDBAdapter()})

    for classification_id in ("jobsdb:6287", "jobsdb:9999"):
        with pytest.raises(ScopeRuleInvalidError, match="not top-level"):
            service.preview(
                AuthoredCrawlScopeV1(
                    source_site="jobsdb",
                    mode="selected",
                    classification_ids=(classification_id,),
                )
            )


def test_listing_workload_cap_still_uses_compiled_query_target_count(scope_db):
    _seed(scope_db)
    service = CrawlScopeService(scope_db, adapters={"jobsdb": JobsDBAdapter()})

    with pytest.raises(WorkloadCapExceededError):
        service.preview(
            AuthoredCrawlScopeV1(source_site="jobsdb", mode="all"),
            listing_settings=ListingSettingsV1(
                crawl_mode="headless",
                page_depth=2,
                run_page_cap=3,
            ),
        )
