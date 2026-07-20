from __future__ import annotations

import asyncio

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.category_routes import _list_categories_impl
from app.api.source_catalogs import (
    get_published_source_catalog,
    list_source_catalog_validation_runs,
    start_source_catalog_validation,
)
from app.models.source_catalog import SOURCE_CATALOG_TABLES, SourceCatalogCandidate
from app.repositories.source_catalog_repository import SourceCatalogRepository
from app.request_monitoring import should_log_request_summary
from app.services.source_category_registry import SourceCategoryRegistry
import app.services.source_category_registry as registry_module
from app.services import runtime_capabilities_service
from app.source_catalog.adapters.jobsdb import JobsDBSourceCatalogAdapter


@compiles(UUID, "sqlite")
def compile_uuid_for_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(32)"


def test_published_tree_and_legacy_categories_share_one_revision_without_discovery(
    monkeypatch,
):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SourceCatalogCandidate.metadata.create_all(engine, tables=SOURCE_CATALOG_TABLES)
    Session = sessionmaker(bind=engine)
    db = Session()
    repository = SourceCatalogRepository()
    original_registry = registry_module._registry
    try:
        with pytest.raises(HTTPException) as unpublished:
            get_published_source_catalog("jobsdb", db)
        assert unpublished.value.status_code == 404
        assert unpublished.value.detail["code"] == "CATALOG_NOT_PUBLISHED"

        catalog = JobsDBSourceCatalogAdapter().discover()
        candidate, _ = repository.create_or_get_candidate(
            db,
            source_site="jobsdb",
            fingerprint=catalog.fingerprint,
            normalized_payload=catalog.normalized_payload(),
            source_payload=dict(catalog.source_payload),
            provenance=dict(catalog.provenance),
        )
        repository.mark_candidate_validated(db, candidate=candidate)
        revision = repository.create_revision(
            db,
            candidate=candidate,
            published_by="fixture",
        )
        repository.set_active_revision(
            db,
            source_site="jobsdb",
            revision_id=revision.id,
            expected_revision_id=None,
            updated_by="fixture",
        )

        tree = get_published_source_catalog("jobsdb", db)
        registry_module._registry = SourceCategoryRegistry(session_factory=Session)
        legacy = asyncio.run(_list_categories_impl("jobsdb"))
        monkeypatch.setattr(runtime_capabilities_service, "SessionLocal", Session)
        health = runtime_capabilities_service._source_catalog_health()

        assert tree["revision"]["fingerprint"] == catalog.fingerprint
        assert tree["revision"]["node_count"] == 25
        assert tree["revision"]["query_target_count"] == 25
        assert tree["revision"]["validation_summary"]["status"] == "passed"
        assert tree["revision"]["provenance"] == catalog.provenance
        assert len(tree["catalog"]["nodes"]) == 25
        assert legacy["total"] == 25
        assert legacy["categories"][0]["id"] == 1200
        assert health["jobsdb"]["revision_id"] == str(revision.id)
        assert health["ctgoodjobs"]["published"] is False
    finally:
        registry_module._registry = original_registry
        db.close()
        engine.dispose()


@pytest.mark.parametrize(
    "endpoint",
    (start_source_catalog_validation, list_source_catalog_validation_runs),
)
def test_candidate_validation_endpoints_return_stable_missing_candidate_error(endpoint):
    engine = create_engine("sqlite:///:memory:")
    SourceCatalogCandidate.metadata.create_all(engine, tables=SOURCE_CATALOG_TABLES)
    db = sessionmaker(bind=engine)()
    try:
        with pytest.raises(HTTPException) as exc_info:
            endpoint("jobsdb", "00000000-0000-0000-0000-000000000000", db)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == {
            "code": "CATALOG_CANDIDATE_STALE",
            "message": "Candidate not found",
        }
    finally:
        db.close()
        engine.dispose()


def test_source_catalog_api_is_included_in_request_id_summary_logging():
    assert should_log_request_summary(
        path="/api/v1/source-catalogs/jobsdb/published",
        status_code=200,
        duration_ms=1,
    )
