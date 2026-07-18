from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.models  # noqa: F401
from app.models.source_catalog import (
    SOURCE_CATALOG_TABLES,
    SourceCatalogActiveRevision,
    SourceCatalogCandidate,
    SourceCatalogRevision,
)
from app.repositories.source_catalog_repository import SourceCatalogRepository


@compiles(UUID, "sqlite")
def compile_uuid_for_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(32)"


def _session():
    engine = create_engine("sqlite:///:memory:")
    SourceCatalogCandidate.metadata.create_all(engine, tables=SOURCE_CATALOG_TABLES)
    return engine, sessionmaker(bind=engine)()


def test_discovery_reuses_the_same_active_candidate_fingerprint():
    engine, db = _session()
    repository = SourceCatalogRepository()
    try:
        first, first_created = repository.create_or_get_candidate(
            db,
            source_site="jobsdb",
            fingerprint="a" * 64,
            normalized_payload={"version": 1, "nodes": []},
            source_payload={"categories": []},
            provenance={"method": "fixture"},
        )
        second, second_created = repository.create_or_get_candidate(
            db,
            source_site="jobsdb",
            fingerprint="a" * 64,
            normalized_payload={"version": 1, "nodes": []},
            source_payload={"categories": []},
            provenance={"method": "fixture"},
        )

        assert first_created is True
        assert second_created is False
        assert second.id == first.id
        assert second.state == "discovered"
        first.source_payload = {"categories": [{"id": "mutated"}]}
        with pytest.raises(ValueError, match="immutable"):
            db.commit()
        db.rollback()
    finally:
        db.close()
        engine.dispose()


def test_fresh_bootstrap_metadata_registers_every_source_catalog_table():
    assert {table.name for table in SOURCE_CATALOG_TABLES} <= set(Base.metadata.tables)


def test_active_pointer_switch_preserves_immutable_revision_history():
    engine, db = _session()
    repository = SourceCatalogRepository()
    try:
        first_candidate, _ = repository.create_or_get_candidate(
            db,
            source_site="jobsdb",
            fingerprint="1" * 64,
            normalized_payload={"version": 1, "nodes": [{"node_key": "6281"}]},
            source_payload={"categories": [{"id": 6281}]},
            provenance={"method": "fixture"},
        )
        repository.mark_candidate_validated(db, candidate=first_candidate)
        first_revision = repository.create_revision(
            db,
            candidate=first_candidate,
            published_by="operator@example.com",
        )
        repository.set_active_revision(
            db,
            source_site="jobsdb",
            revision_id=first_revision.id,
            expected_revision_id=None,
            updated_by="operator@example.com",
        )

        second_candidate, _ = repository.create_or_get_candidate(
            db,
            source_site="jobsdb",
            fingerprint="2" * 64,
            normalized_payload={"version": 1, "nodes": [{"node_key": "6282"}]},
            source_payload={"categories": [{"id": 6282}]},
            provenance={"method": "fixture"},
            base_revision_id=first_revision.id,
        )
        repository.mark_candidate_validated(db, candidate=second_candidate)
        second_revision = repository.create_revision(
            db,
            candidate=second_candidate,
            published_by="operator@example.com",
        )
        repository.set_active_revision(
            db,
            source_site="jobsdb",
            revision_id=second_revision.id,
            expected_revision_id=first_revision.id,
            updated_by="operator@example.com",
        )

        active = db.get(SourceCatalogActiveRevision, "jobsdb")
        revisions = db.query(SourceCatalogRevision).order_by(SourceCatalogRevision.sequence).all()
        assert active.revision_id == second_revision.id
        assert [(row.id, row.sequence) for row in revisions] == [
            (first_revision.id, 1),
            (second_revision.id, 2),
        ]
        assert first_revision.normalized_payload["nodes"][0]["node_key"] == "6281"

        first_revision.fingerprint = "f" * 64
        with pytest.raises(ValueError, match="immutable"):
            db.commit()
        db.rollback()
        db.refresh(first_revision)
        assert first_revision.fingerprint == "1" * 64
    finally:
        db.close()
        engine.dispose()
