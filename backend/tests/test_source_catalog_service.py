from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.source_catalog import SOURCE_CATALOG_TABLES, SourceCatalogCandidate
from app.repositories.source_catalog_repository import SourceCatalogRepository
from app.source_catalog.domain import (
    CatalogNodeSnapshot,
    CatalogScopeCapabilities,
    DiscoveredCatalog,
    SourceQueryTarget,
)
from app.source_catalog.errors import SourceCatalogError
from app.source_catalog.impact import CatalogImpactAssessment
from app.source_catalog.validation import CatalogValidationCoordinator
from app.services.source_category_registry import SourceCategoryRegistry
from app.services.source_catalog_service import SourceCatalogService


@compiles(UUID, "sqlite")
def compile_uuid_for_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(32)"


class MutableAdapter:
    source_site = "jobsdb"

    def __init__(self):
        self.label = "Accounting"
        self.classification_id = "jobsdb:1200"
        self.native_id = 1200

    def _target(self):
        return SourceQueryTarget(
            adapter="jobsdb.classification",
            classification_id=self.classification_id,
            payload={"native_id": self.native_id},
        )

    def discover(self):
        target = self._target()
        node = CatalogNodeSnapshot(
            node_key=self.classification_id,
            source_site="jobsdb",
            classification_id=self.classification_id,
            native_id=self.native_id,
            native_label=self.label,
            parent_node_key=None,
            native_path=(self.label,),
            depth=0,
            selectable=True,
            supports_exact=True,
            supports_subtree=False,
            queryable=True,
            alias_of_node_key=None,
            query_semantics_hash=target.fingerprint,
            source_metadata={},
        )
        return DiscoveredCatalog(
            source_site="jobsdb",
            nodes=(node,),
            capabilities=CatalogScopeCapabilities(True, (node.node_key,), {"mode": "all"}),
            source_payload={
                "categories": [{"id": self.native_id, "name": self.label}]
            },
            provenance={"method": "fixture"},
        )

    def compile(self, node):
        return (
            SourceQueryTarget(
                adapter="jobsdb.classification",
                classification_id=node.classification_id,
                payload={"native_id": int(node.native_id)},
            ),
        )

    async def smoke(self, target):
        return {"status": "passed", "target_hash_prefix": target.fingerprint[:12]}


class NoAutomationImpactEvaluator:
    def __init__(self):
        self.generation = 0

    def evaluate(self, **_kwargs):
        return CatalogImpactAssessment(
            allowed=True,
            versioned_automation_count=0,
            summary={
                "versioned_automation_count": 0,
                "generation": self.generation,
            },
        )


def test_publish_and_rollback_require_fresh_single_use_impact_reviews():
    engine = create_engine("sqlite:///:memory:")
    SourceCatalogCandidate.metadata.create_all(engine, tables=SOURCE_CATALOG_TABLES)
    db = sessionmaker(bind=engine)()
    repository = SourceCatalogRepository()
    adapter = MutableAdapter()
    coordinator = CatalogValidationCoordinator(
        db,
        repository=repository,
        adapters={"jobsdb": adapter},
    )
    service_without_impact = SourceCatalogService(
        db,
        repository=repository,
        adapters={"jobsdb": adapter},
    )
    impact_evaluator = NoAutomationImpactEvaluator()
    service = SourceCatalogService(
        db,
        repository=repository,
        adapters={"jobsdb": adapter},
        impact_evaluator=impact_evaluator,
    )
    try:
        first_candidate, _ = service.discover("jobsdb")
        with pytest.raises(SourceCatalogError) as unpublished:
            service.get_published("jobsdb")
        assert unpublished.value.code == "CATALOG_NOT_PUBLISHED"
        coordinator.start(first_candidate.id)
        asyncio.run(coordinator.run_pending(first_candidate.id, worker_id="worker"))

        with pytest.raises(SourceCatalogError) as unavailable:
            service_without_impact.review_publication(
                first_candidate.id,
                actor="operator@example.com",
            )
        assert unavailable.value.code == "CATALOG_IMPACT_STALE"

        expired_review = service.review_publication(
            first_candidate.id,
            actor="operator@example.com",
            ttl=timedelta(seconds=-1),
        )
        with pytest.raises(SourceCatalogError) as expired:
            service.publish(
                first_candidate.id,
                review_token=expired_review.review_token,
                actor="operator@example.com",
            )
        assert expired.value.code == "CATALOG_IMPACT_STALE"

        stale_impact_review = service.review_publication(
            first_candidate.id,
            actor="operator@example.com",
        )
        impact_evaluator.generation += 1
        with pytest.raises(SourceCatalogError) as stale_impact:
            service.publish(
                first_candidate.id,
                review_token=stale_impact_review.review_token,
                actor="operator@example.com",
            )
        assert stale_impact.value.code == "CATALOG_IMPACT_STALE"

        first_review = service.review_publication(
            first_candidate.id,
            actor="operator@example.com",
        )
        with pytest.raises(SourceCatalogError) as publish_without_impact:
            service_without_impact.publish(
                first_candidate.id,
                review_token=first_review.review_token,
                actor="operator@example.com",
            )
        assert publish_without_impact.value.code == "CATALOG_IMPACT_STALE"
        with pytest.raises(SourceCatalogError) as wrong_source:
            service.publish(
                first_candidate.id,
                review_token=first_review.review_token,
                actor="operator@example.com",
                expected_source_site="offertoday",
            )
        assert wrong_source.value.code == "CATALOG_CANDIDATE_STALE"
        first_revision = service.publish(
            first_candidate.id,
            review_token=first_review.review_token,
            actor="operator@example.com",
        )
        with pytest.raises(SourceCatalogError) as reused:
            service.publish(
                first_candidate.id,
                review_token=first_review.review_token,
                actor="operator@example.com",
            )
        assert reused.value.code == "CATALOG_IMPACT_STALE"

        adapter.label = "Accounting and Audit"
        second_candidate, _ = service.discover("jobsdb")
        second_runs = coordinator.start(second_candidate.id)
        assert [run.validation_kind for run in second_runs] == ["offline"]
        asyncio.run(coordinator.run_pending(second_candidate.id, worker_id="worker"))
        second_review = service.review_publication(
            second_candidate.id,
            actor="operator@example.com",
        )
        second_revision = service.publish(
            second_candidate.id,
            review_token=second_review.review_token,
            actor="operator@example.com",
        )

        rollback_review = service.review_rollback(
            first_revision.id,
            actor="operator@example.com",
        )
        rolled_back = service.rollback(
            first_revision.id,
            review_token=rollback_review.review_token,
            actor="operator@example.com",
        )

        assert second_revision.id != first_revision.id
        assert rolled_back.id == first_revision.id
        assert service.get_published("jobsdb").revision.id == first_revision.id
        assert service.get_legacy_categories("jobsdb") == [
            {
                "id": 1200,
                "name": "Accounting",
                "slug": "accounting",
                "source_site": "jobsdb",
            }
        ]
        registry = SourceCategoryRegistry(session_factory=sessionmaker(bind=engine))
        assert registry.list_categories(source_site="jobsdb")[0]["name"] == "Accounting"
        targets = service.compile_classifications("jobsdb", [1200])
        assert targets[0].to_payload()["native_id"] == 1200
        with pytest.raises(SourceCatalogError) as unknown:
            service.compile_classifications("jobsdb", [9999])
        assert unknown.value.code == "SOURCE_CLASSIFICATION_UNKNOWN"
        assert len(repository.list_revisions(db, source_site="jobsdb")) == 2
        assert len(repository.list_publications(db, source_site="jobsdb")) == 3

        adapter.native_id = 1201
        semantics_candidate, _ = service.discover("jobsdb")
        semantics_runs = coordinator.start(semantics_candidate.id)
        assert [run.validation_kind for run in semantics_runs] == [
            "offline",
            "live_smoke",
        ]

        adapter.classification_id = "jobsdb:1201"
        candidate_only, _ = service.discover("jobsdb")
        assert candidate_only.state == "discovered"
        with pytest.raises(SourceCatalogError) as candidate_error:
            service.compile_classifications("jobsdb", [1201])
        assert candidate_error.value.code == "SOURCE_CLASSIFICATION_UNKNOWN"
        assert service.compile_classifications("jobsdb", [1200])[0].payload[
            "native_id"
        ] == 1200
    finally:
        db.close()
        engine.dispose()


def test_publication_failure_rolls_back_revision_pointer_and_audit(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SourceCatalogCandidate.metadata.create_all(engine, tables=SOURCE_CATALOG_TABLES)
    db = sessionmaker(bind=engine)()
    repository = SourceCatalogRepository()
    adapter = MutableAdapter()
    evaluator = NoAutomationImpactEvaluator()
    coordinator = CatalogValidationCoordinator(
        db,
        repository=repository,
        adapters={"jobsdb": adapter},
    )
    service = SourceCatalogService(
        db,
        repository=repository,
        adapters={"jobsdb": adapter},
        impact_evaluator=evaluator,
    )
    try:
        candidate, _ = service.discover("jobsdb")
        coordinator.start(candidate.id)
        asyncio.run(coordinator.run_pending(candidate.id, worker_id="worker"))
        review = service.review_publication(
            candidate.id,
            actor="operator@example.com",
        )

        def fail_publication_audit(*_args, **_kwargs):
            raise RuntimeError("fixture publication audit failure")

        monkeypatch.setattr(
            repository,
            "append_publication",
            fail_publication_audit,
        )
        with pytest.raises(RuntimeError, match="fixture publication audit failure"):
            service.publish(
                candidate.id,
                review_token=review.review_token,
                actor="operator@example.com",
            )

        db.expire_all()
        persisted_candidate = repository.get_candidate(db, candidate.id)
        assert persisted_candidate.state == "validated"
        assert repository.get_active_revision(db, source_site="jobsdb") is None
        assert repository.list_revisions(db, source_site="jobsdb") == []
        assert repository.list_publications(db, source_site="jobsdb") == []
        persisted_review = repository.get_change_review_by_token_hash_for_update(
            db,
            token_hash=service._token_hash(review.review_token),
        )
        assert persisted_review.consumed_at is None
    finally:
        db.close()
        engine.dispose()
