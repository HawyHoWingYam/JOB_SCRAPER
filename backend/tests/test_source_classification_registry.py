from __future__ import annotations

from dataclasses import replace

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
import pytest

from app.models.source_classification import SOURCE_CLASSIFICATION_TABLES
from app.crawl_control.ordinary_scope import (
    OrdinaryCrawlScopeResolver,
    SourceCrawlScope,
)
from app.scraper.ctgoodjobs.category_registry import get_static_ctgoodjobs_categories
from app.services.source_classification_registry import (
    ObservedSourceClassification,
    SourceClassificationRegistry,
    SourceClassificationSyncResult,
    synchronize_source_classification_adapters,
)
from app.source_classifications.runtime import (
    load_source_query_plan,
    load_source_scope_query_plan,
)
from app.source_classifications.adapters.ctgoodjobs import (
    CTgoodjobsSourceClassificationAdapter,
)
from app.source_classifications.adapters.jobsdb import JobsDBSourceClassificationAdapter
from app.source_classifications.adapters.offertoday import (
    OfferTodaySourceClassificationAdapter,
)
from app.source_classifications.domain import CatalogValidationError


@compiles(UUID, "sqlite")
def compile_uuid_for_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(32)"


def _session():
    engine = create_engine("sqlite:///:memory:")
    SOURCE_CLASSIFICATION_TABLES[0].metadata.create_all(
        engine,
        tables=SOURCE_CLASSIFICATION_TABLES,
    )
    return engine, sessionmaker(bind=engine)()


def _adapters():
    return (
        JobsDBSourceClassificationAdapter(),
        OfferTodaySourceClassificationAdapter(),
        CTgoodjobsSourceClassificationAdapter(
            category_provider=get_static_ctgoodjobs_categories,
        ),
    )


def test_all_sources_synchronize_into_one_ordinary_registry():
    engine, db = _session()
    try:
        registry = SourceClassificationRegistry(db)
        for adapter in _adapters():
            result = registry.synchronize_catalog(
                adapter.discover(),
                complete=True,
                compiler=adapter,
            )
            assert result.observed_count > 0

        assert {row.source_site for row in registry.list_all()} == {
            "jobsdb",
            "offertoday",
            "ctgoodjobs",
        }
        assert registry.list_top_level("jobsdb")
        assert registry.list_top_level("ctgoodjobs")
        assert registry.list_top_level("offertoday")
        assert any(
            row.depth == 1 and row.parent_id is not None
            for row in registry.list_all(source_site="offertoday")
        )
    finally:
        db.close()
        engine.dispose()


def test_invalid_ctgoodjobs_catalog_is_rejected_before_current_registry_changes():
    engine, db = _session()
    try:
        adapter = CTgoodjobsSourceClassificationAdapter(
            category_provider=get_static_ctgoodjobs_categories,
        )
        catalog = adapter.discover()
        registry = SourceClassificationRegistry(db)
        registry.synchronize_catalog(catalog, complete=True, compiler=adapter)
        db.commit()

        def current_rows():
            return tuple(
                (
                    row.classification_id,
                    row.native_id,
                    row.label,
                    row.depth,
                    row.is_top_level,
                    row.is_active,
                    dict(row.query_metadata),
                    row.first_observed_at,
                    row.last_observed_at,
                )
                for row in registry.list_all(source_site="ctgoodjobs")
            )

        before = current_rows()
        broken_nodes = list(catalog.nodes)
        broken_nodes[0] = replace(
            broken_nodes[0],
            native_label="Must not replace the current label",
            native_path=("Must not replace the current label",),
            source_metadata={
                **broken_nodes[0].source_metadata,
                "url_path": "",
            },
        )
        broken_nodes[1] = replace(
            broken_nodes[1],
            source_metadata={
                **broken_nodes[1].source_metadata,
                "url_path": f"{broken_nodes[1].source_metadata['url_path']}?token=secret",
            },
        )
        broken_catalog = replace(catalog, nodes=tuple(broken_nodes))

        with pytest.raises(CatalogValidationError) as exc_info:
            registry.synchronize_catalog(
                broken_catalog,
                complete=True,
                compiler=adapter,
            )

        assert exc_info.value.code == "CATALOG_NOT_EXECUTABLE"
        assert [issue.to_payload() for issue in exc_info.value.issues] == [
            {
                "source_site": "ctgoodjobs",
                "classification_id": broken_nodes[0].classification_id,
                "native_id": str(broken_nodes[0].native_id),
                "label": "Must not replace the current label",
                "node_key": broken_nodes[0].node_key,
                "field": "url_path",
                "value": "",
                "code": "SOURCE_CLASSIFICATION_NOT_EXECUTABLE",
                "reason": "CTgoodjobs published node has no validated native URL path",
            },
            {
                "source_site": "ctgoodjobs",
                "classification_id": broken_nodes[1].classification_id,
                "native_id": str(broken_nodes[1].native_id),
                "label": broken_nodes[1].native_label,
                "node_key": broken_nodes[1].node_key,
                "field": "url_path",
                "value": f"{broken_nodes[1].source_metadata['url_path'].split('?', 1)[0]}?<redacted>",
                "code": "SOURCE_CLASSIFICATION_NOT_EXECUTABLE",
                "reason": "CTgoodjobs published node has no validated native URL path",
            },
        ]
        assert current_rows() == before
    finally:
        db.close()
        engine.dispose()


def test_startup_sync_isolates_invalid_ctgoodjobs_from_other_sources():
    engine, db = _session()
    try:
        ctgoodjobs = CTgoodjobsSourceClassificationAdapter(
            category_provider=get_static_ctgoodjobs_categories,
        )
        catalog = ctgoodjobs.discover()
        broken_nodes = list(catalog.nodes)
        broken_nodes[0] = replace(
            broken_nodes[0],
            source_metadata={
                **broken_nodes[0].source_metadata,
                "url_path": "",
            },
        )

        class InvalidCTgoodjobsAdapter:
            source_site = "ctgoodjobs"

            def discover(self):
                return replace(catalog, nodes=tuple(broken_nodes))

            def compile(self, node):
                return ctgoodjobs.compile(node)

            async def smoke(self, target):
                return await ctgoodjobs.smoke(target)

        results = synchronize_source_classification_adapters(
            db,
            (
                JobsDBSourceClassificationAdapter(),
                InvalidCTgoodjobsAdapter(),
                OfferTodaySourceClassificationAdapter(),
            ),
        )

        assert isinstance(results["jobsdb"], SourceClassificationSyncResult)
        assert results["ctgoodjobs"] == "CatalogValidationError"
        assert isinstance(results["offertoday"], SourceClassificationSyncResult)
        assert {
            row.source_site for row in SourceClassificationRegistry(db).list_all()
        } == {
            "jobsdb",
            "offertoday",
        }
    finally:
        db.close()
        engine.dispose()


def test_complete_sync_updates_labels_and_inactivates_missing_roots_without_deleting():
    engine, db = _session()
    try:
        registry = SourceClassificationRegistry(db)
        roots = (
            ObservedSourceClassification(
                classification_id="jobsdb:100",
                native_id="100",
                label="Old label",
                depth=0,
            ),
            ObservedSourceClassification(
                classification_id="jobsdb:200",
                native_id="200",
                label="Disappearing",
                depth=0,
            ),
        )
        registry.synchronize("jobsdb", roots, complete=True)
        registry.synchronize(
            "jobsdb",
            (replace(roots[0], label="New label"),),
            complete=True,
        )

        rows = {row.classification_id: row for row in registry.list_all()}
        assert rows["jobsdb:100"].label == "New label"
        assert rows["jobsdb:100"].is_active is True
        assert rows["jobsdb:200"].is_active is False
        assert db.get(type(rows["jobsdb:200"]), rows["jobsdb:200"].id) is not None
    finally:
        db.close()
        engine.dispose()


def test_partial_sync_never_marks_unseen_roots_inactive():
    engine, db = _session()
    try:
        registry = SourceClassificationRegistry(db)
        roots = tuple(
            ObservedSourceClassification(
                classification_id=f"ctgoodjobs:{value}",
                native_id=value,
                label=value,
                depth=0,
            )
            for value in ("001", "002")
        )
        registry.synchronize("ctgoodjobs", roots, complete=True)
        registry.synchronize("ctgoodjobs", roots[:1], complete=False)

        assert all(row.is_active for row in registry.list_top_level("ctgoodjobs"))
    finally:
        db.close()
        engine.dispose()


def test_ingest_observation_idempotently_preserves_child_identity_but_not_as_crawl_choice():
    engine, db = _session()
    try:
        registry = SourceClassificationRegistry(db)
        path = (
            ObservedSourceClassification(
                classification_id="offertoday:100000",
                native_id="100000",
                label="Root",
                depth=0,
            ),
            ObservedSourceClassification(
                classification_id="offertoday:100100",
                native_id="100100",
                label="Child",
                depth=1,
                parent_classification_id="offertoday:100000",
            ),
        )
        registry.observe_path("job-1", "offertoday", path)
        registry.observe_path("job-1", "offertoday", path)

        assert [
            row.classification_id for row in registry.list_top_level("offertoday")
        ] == ["offertoday:100000"]
        assert len(registry.list_all(source_site="offertoday")) == 2
    finally:
        db.close()
        engine.dispose()


def test_all_sources_resolve_only_active_top_level_crawl_choices():
    engine, db = _session()
    try:
        adapters = {
            adapter.source_site: adapter
            for adapter in (
                JobsDBSourceClassificationAdapter(),
                OfferTodaySourceClassificationAdapter(),
                CTgoodjobsSourceClassificationAdapter(
                    category_provider=get_static_ctgoodjobs_categories,
                ),
            )
        }
        registry = SourceClassificationRegistry(db)
        for adapter in adapters.values():
            registry.synchronize_catalog(
                adapter.discover(),
                complete=True,
                compiler=adapter,
            )
        resolver = OrdinaryCrawlScopeResolver(db, adapters=adapters)

        for source_site in adapters:
            root = registry.list_top_level(source_site)[0]
            resolved = resolver.resolve(
                SourceCrawlScope(
                    source_site=source_site,
                    mode="selected",
                    classification_ids=(root.classification_id,),
                )
            )
            assert resolved.classification_ids == (root.classification_id,)
            assert resolved.query_targets[0].classification_id == root.classification_id

        inactive = registry.list_top_level("jobsdb")[0]
        inactive.is_active = False
        db.flush()
        try:
            resolver.resolve(
                SourceCrawlScope(
                    source_site="jobsdb",
                    mode="selected",
                    classification_ids=(inactive.classification_id,),
                )
            )
        except ValueError as exc:
            assert "inactive" in str(exc)
        else:
            raise AssertionError("inactive root must not be authorable")
    finally:
        db.close()
        engine.dispose()


def test_ordinary_runtime_accepts_native_compatibility_ids_and_all_scope():
    engine, db = _session()
    session_factory = sessionmaker(bind=engine)
    try:
        registry = SourceClassificationRegistry(db)
        for adapter in _adapters():
            registry.synchronize_catalog(
                adapter.discover(),
                complete=True,
                compiler=adapter,
            )
        db.commit()

        jobsdb = load_source_query_plan(
            "jobsdb",
            [6281],
            session_factory=session_factory,
        )
        assert [entry.node.classification_id for entry in jobsdb.entries] == [
            "jobsdb:6281"
        ]
        assert jobsdb.entries[0].target.payload["native_id"] == 6281

        ctgoodjobs = load_source_scope_query_plan(
            "ctgoodjobs",
            mode="all",
            session_factory=session_factory,
        )
        assert ctgoodjobs.entries
        assert all(
            entry.node.classification_id.startswith("ctgoodjobs:")
            for entry in ctgoodjobs.entries
        )
    finally:
        db.close()
        engine.dispose()
