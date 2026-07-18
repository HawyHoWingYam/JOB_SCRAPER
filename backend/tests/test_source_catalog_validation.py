from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.source_catalog import SOURCE_CATALOG_TABLES, SourceCatalogCandidate
from app.repositories.source_catalog_repository import (
    SourceCatalogConcurrentChangeError,
    SourceCatalogRepository,
)
from app.source_catalog.domain import (
    CatalogNodeSnapshot,
    CatalogScopeCapabilities,
    DiscoveredCatalog,
    SourceQueryTarget,
)
from app.source_catalog.adapters.offertoday import OfferTodaySourceCatalogAdapter
from app.source_catalog.validation import CatalogValidationCoordinator
from app.services.source_catalog_service import SourceCatalogService
from app.utils.time import utc_now


@compiles(UUID, "sqlite")
def compile_uuid_for_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(32)"


class PassingAdapter:
    source_site = "jobsdb"

    def __init__(self):
        self.smoke_status = "passed"
        target = SourceQueryTarget(
            adapter="jobsdb.classification",
            classification_id="jobsdb:1200",
            payload={"native_id": 1200},
        )
        self.node = CatalogNodeSnapshot(
            node_key="jobsdb:1200",
            source_site="jobsdb",
            classification_id="jobsdb:1200",
            native_id=1200,
            native_label="Accounting",
            parent_node_key=None,
            native_path=("Accounting",),
            depth=0,
            selectable=True,
            supports_exact=True,
            supports_subtree=False,
            queryable=True,
            alias_of_node_key=None,
            query_semantics_hash=target.fingerprint,
            source_metadata={},
        )

    def discover(self):
        return DiscoveredCatalog(
            source_site="jobsdb",
            nodes=(self.node,),
            capabilities=CatalogScopeCapabilities(
                supports_all_scope=True,
                all_scope_root_node_keys=(self.node.node_key,),
                recommended_scope={"mode": "all"},
            ),
            source_payload={"categories": [{"id": 1200}]},
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
        if self.smoke_status == "manual_action_required":
            return {
                "status": "manual_action_required",
                "classification": "waf_challenge",
                "body": "must never persist",
                "cookies": ["must never persist"],
                "target_hash_prefix": target.fingerprint[:12],
            }
        if self.smoke_status == "failed":
            return {
                "status": "failed",
                "reason": "unexpected_shape",
                "error_type": "FixtureFailure",
                "body": "must never persist",
                "cookies": ["must never persist"],
                "target_hash_prefix": target.fingerprint[:12],
            }
        return {
            "status": "passed",
            "constraint": "classification",
            "target_hash_prefix": target.fingerprint[:12],
        }


def test_validation_is_durable_and_does_not_activate_the_candidate():
    engine = create_engine("sqlite:///:memory:")
    SourceCatalogCandidate.metadata.create_all(engine, tables=SOURCE_CATALOG_TABLES)
    db = sessionmaker(bind=engine)()
    repository = SourceCatalogRepository()
    adapter = PassingAdapter()
    service = SourceCatalogService(
        db,
        repository=repository,
        adapters={"jobsdb": adapter},
    )
    coordinator = CatalogValidationCoordinator(
        db,
        repository=repository,
        adapters={"jobsdb": adapter},
    )
    try:
        candidate, created = service.discover("jobsdb")
        runs = coordinator.start(candidate.id)

        assert created is True
        assert [(run.validation_kind, run.status) for run in runs] == [
            ("offline", "pending"),
            ("live_smoke", "pending"),
        ]

        asyncio.run(coordinator.run_pending(candidate.id, worker_id="test-worker"))

        db.refresh(candidate)
        completed = repository.list_validation_runs(db, candidate_id=candidate.id)
        assert candidate.state == "validated"
        assert [run.status for run in completed] == ["passed", "passed"]
        assert repository.get_active_revision(db, source_site="jobsdb") is None
        assert all("payload" not in (run.evidence or {}) for run in completed)
    finally:
        db.close()
        engine.dispose()


def test_manual_action_validation_is_redacted_and_retryable_on_the_same_target_hash():
    engine = create_engine("sqlite:///:memory:")
    SourceCatalogCandidate.metadata.create_all(engine, tables=SOURCE_CATALOG_TABLES)
    db = sessionmaker(bind=engine)()
    repository = SourceCatalogRepository()
    adapter = PassingAdapter()
    adapter.smoke_status = "manual_action_required"
    service = SourceCatalogService(
        db,
        repository=repository,
        adapters={"jobsdb": adapter},
    )
    coordinator = CatalogValidationCoordinator(
        db,
        repository=repository,
        adapters={"jobsdb": adapter},
    )
    try:
        candidate, _ = service.discover("jobsdb")
        coordinator.start(candidate.id)
        asyncio.run(coordinator.run_pending(candidate.id, worker_id="worker-1"))
        db.refresh(candidate)
        first_runs = repository.list_validation_runs(db, candidate_id=candidate.id)

        assert candidate.state == "manual_action_required"
        manual_run = next(run for run in first_runs if run.validation_kind == "live_smoke")
        assert manual_run.manual_action["classification"] == "waf_challenge"
        assert "body" not in manual_run.manual_action
        assert "cookies" not in manual_run.manual_action

        adapter.smoke_status = "passed"
        retry_runs = coordinator.start(candidate.id)
        assert [(run.validation_kind, run.attempt, run.status) for run in retry_runs] == [
            ("offline", 1, "passed"),
            ("live_smoke", 1, "manual_action_required"),
            ("live_smoke", 2, "pending"),
        ]
        asyncio.run(coordinator.run_pending(candidate.id, worker_id="worker-2"))
        db.refresh(candidate)
        assert candidate.state == "validated"
    finally:
        db.close()
        engine.dispose()


def test_failed_validation_persists_only_bounded_scalar_evidence():
    engine = create_engine("sqlite:///:memory:")
    SourceCatalogCandidate.metadata.create_all(engine, tables=SOURCE_CATALOG_TABLES)
    db = sessionmaker(bind=engine)()
    repository = SourceCatalogRepository()
    adapter = PassingAdapter()
    adapter.smoke_status = "failed"
    service = SourceCatalogService(
        db,
        repository=repository,
        adapters={"jobsdb": adapter},
    )
    coordinator = CatalogValidationCoordinator(
        db,
        repository=repository,
        adapters={"jobsdb": adapter},
    )
    try:
        candidate, _ = service.discover("jobsdb")
        coordinator.start(candidate.id)
        asyncio.run(coordinator.run_pending(candidate.id, worker_id="worker"))

        live_run = next(
            run
            for run in repository.list_validation_runs(
                db,
                candidate_id=candidate.id,
            )
            if run.validation_kind == "live_smoke"
        )
        assert live_run.error == {
            "status": "failed",
            "reason": "unexpected_shape",
            "error_type": "FixtureFailure",
            "target_hash_prefix": live_run.expected_target_hash[:12],
        }
        assert "body" not in live_run.evidence
        assert "cookies" not in live_run.evidence
    finally:
        db.close()
        engine.dispose()


def test_stale_worker_cannot_overwrite_a_reclaimed_validation_result():
    engine = create_engine("sqlite:///:memory:")
    SourceCatalogCandidate.metadata.create_all(engine, tables=SOURCE_CATALOG_TABLES)
    db = sessionmaker(bind=engine)()
    repository = SourceCatalogRepository()
    adapter = PassingAdapter()
    service = SourceCatalogService(
        db,
        repository=repository,
        adapters={"jobsdb": adapter},
    )
    coordinator = CatalogValidationCoordinator(
        db,
        repository=repository,
        adapters={"jobsdb": adapter},
    )
    try:
        candidate, _ = service.discover("jobsdb")
        coordinator.start(candidate.id)
        claimed = repository.claim_next_validation_run(
            db,
            candidate_id=candidate.id,
            worker_id="stale-worker",
        )
        repository.fail_stale_validation_runs(
            db,
            candidate_id=candidate.id,
            stale_before=utc_now(),
        )

        with pytest.raises(SourceCatalogConcurrentChangeError):
            repository.complete_validation_run(
                db,
                run=claimed,
                worker_id="stale-worker",
                status="passed",
            )
    finally:
        db.rollback()
        db.close()
        engine.dispose()


def test_full_offertoday_catalog_validation_compiles_and_smokes_every_query_target_offline():
    class OfflineOfferTodayAdapter(OfferTodaySourceCatalogAdapter):
        def __init__(self):
            super().__init__()
            self.smoke_count = 0

        async def smoke(self, target):
            self.smoke_count += 1
            return {
                "status": "passed",
                "target_hash_prefix": target.fingerprint[:12],
                "constraint": "jobFunctionCodes",
            }

    engine = create_engine("sqlite:///:memory:")
    SourceCatalogCandidate.metadata.create_all(engine, tables=SOURCE_CATALOG_TABLES)
    db = sessionmaker(bind=engine)()
    repository = SourceCatalogRepository()
    adapter = OfflineOfferTodayAdapter()
    service = SourceCatalogService(
        db,
        repository=repository,
        adapters={"offertoday": adapter},
    )
    coordinator = CatalogValidationCoordinator(
        db,
        repository=repository,
        adapters={"offertoday": adapter},
    )
    try:
        candidate, _ = service.discover("offertoday")
        runs = coordinator.start(candidate.id)
        assert sum(run.validation_kind == "offline" for run in runs) == 1
        assert sum(run.validation_kind == "live_smoke" for run in runs) == 462

        asyncio.run(
            coordinator.run_pending(candidate.id, worker_id="offline-test-worker")
        )
        db.refresh(candidate)
        assert candidate.state == "validated"
        assert adapter.smoke_count == 462
    finally:
        db.close()
        engine.dispose()
