from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, update
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.crawl_control.contracts import (
    AuthoredCrawlScopeV1,
    DetailSettingsV1,
    ListingSettingsV1,
    QueryTargetSnapshotV1,
    ResolvedRunScopeV1,
    SelectedClassificationSnapshotV1,
)
from app.crawl_control.dispatch_plan_contracts import (
    DispatchPlanContentV1,
    DispatchPlanReadinessV1,
    DispatchPlanTargetRowV1,
    DispatchPlanTargetV1,
    ExecutionResumeContextV1,
)
from app.crawl_control.dispatch_plan_repository import DispatchPlanRepository
from app.crawl_control.dispatch_plan_service import DispatchPlanService
from app.crawl_control.errors import (
    DispatchPlanAlreadyConsumedError,
    DispatchPlanExpiredError,
    DispatchPlanFingerprintMismatchError,
    DispatchPlanStaleError,
)
from app.crawl_control.runtime_authority import load_legacy_worker_startup_input
from app.database import Base
from app.models.crawl_dispatch_plan import (
    CRAWL_DISPATCH_PLAN_TABLES,
    CrawlDispatchPlan,
)
from app.models.crawl_job import CrawlJob, CrawlJobEvent
from app.models.crawl_job_execution import CrawlJobExecution
from app.models.crawl_job_listing import CrawlJobListing
from app.models.crawl_run import CrawlRun
from app.models.schedule import ScheduleExecution, ScrapeSchedule
from app.models.source_catalog import SourceCatalogCandidate, SourceCatalogRevision
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.scraper.manual_action import build_session_recovery_manual_action
from app.services.crawl_job_dispatch_service import CrawlJobDispatchService
from app.services.crawl_job_execution_launcher import CrawlJobExecutionLauncher
from app.source_catalog.domain import SourceQueryTarget, payload_fingerprint


@compiles(PostgreSQLUUID, "sqlite")
def compile_uuid_for_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(32)"


@pytest.fixture
def dispatch_db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    tables = (
        SourceCatalogCandidate.__table__,
        SourceCatalogRevision.__table__,
        ScrapeSchedule.__table__,
        CrawlJob.__table__,
        CrawlJobEvent.__table__,
        CrawlJobExecution.__table__,
        CrawlRun.__table__,
        CrawlJobListing.__table__,
        *CRAWL_DISPATCH_PLAN_TABLES,
        ScheduleExecution.__table__,
    )
    Base.metadata.create_all(engine, tables=tables)
    factory = sessionmaker(bind=engine)
    db = factory()
    revision = _create_catalog_revision(db)
    try:
        yield engine, factory, db, revision
    finally:
        db.close()
        engine.dispose()


def _create_catalog_revision(db) -> SourceCatalogRevision:
    candidate = SourceCatalogCandidate(
        source_site="jobsdb",
        fingerprint="c" * 64,
        normalized_payload={"version": 1, "nodes": []},
        source_payload={"categories": []},
        provenance={"method": "fixture"},
        diff={},
        validation_summary={"status": "passed"},
        state="published",
    )
    db.add(candidate)
    db.flush()
    revision = SourceCatalogRevision(
        source_site="jobsdb",
        sequence=1,
        fingerprint="d" * 64,
        normalized_payload={"version": 1, "nodes": []},
        source_payload={"categories": []},
        provenance={"method": "fixture"},
        candidate_id=candidate.id,
        publication_metadata={},
        published_by="operator@example.com",
    )
    db.add(revision)
    db.commit()
    db.refresh(revision)
    return revision


def _scope(revision_id: UUID) -> AuthoredCrawlScopeV1:
    return AuthoredCrawlScopeV1(
        source_site="jobsdb",
        reviewed_catalog_revision_id=revision_id,
        mode="all",
    )


def _resolved_scope(revision: SourceCatalogRevision) -> ResolvedRunScopeV1:
    scope = _scope(revision.id)
    source_target = SourceQueryTarget(
        adapter="jobsdb.classification",
        classification_id="jobsdb:6281",
        payload={"native_id": 6281},
    )
    selected = SelectedClassificationSnapshotV1(
        node_key="jobsdb:6281",
        classification_id="jobsdb:6281",
        native_label="Information Technology",
        native_path=("Information Technology",),
        query_semantics_hash=source_target.fingerprint,
    )
    return ResolvedRunScopeV1(
        source_site="jobsdb",
        catalog_revision_id=revision.id,
        catalog_revision_fingerprint=revision.fingerprint,
        authored_scope=scope,
        selected_classifications=(selected,),
        classification_expansion_hash=payload_fingerprint(
            [
                {
                    "node_key": selected.node_key,
                    "classification_id": selected.classification_id,
                    "query_semantics_hash": selected.query_semantics_hash,
                }
            ]
        ),
        query_targets=(QueryTargetSnapshotV1.from_source_target(source_target),),
        query_target_count=1,
    )


def _listing_content(revision: SourceCatalogRevision) -> DispatchPlanContentV1:
    resolved = _resolved_scope(revision)
    return DispatchPlanContentV1(
        source_site="jobsdb",
        crawl_phase="listing",
        trigger_kind="one_off",
        catalog_revision_id=revision.id,
        authored_scope=resolved.authored_scope,
        resolved_scope=resolved,
        listing_settings=ListingSettingsV1(
            crawl_mode="headless",
            page_depth=2,
            run_page_cap=10,
        ),
    )


def _detail_content(revision: SourceCatalogRevision) -> DispatchPlanContentV1:
    resolved = _resolved_scope(revision)
    return DispatchPlanContentV1(
        source_site="jobsdb",
        crawl_phase="detail",
        trigger_kind="one_off",
        catalog_revision_id=revision.id,
        authored_scope=resolved.authored_scope,
        resolved_scope=resolved,
        detail_settings=DetailSettingsV1.model_validate(
            {
                "crawl_mode": "headless",
                "backlog_scope": {"kind": "source_backlog"},
                "limit": {"kind": "stop_after", "detail_run_cap": 10},
            }
        ),
    )


def _ready(now: datetime) -> DispatchPlanReadinessV1:
    return DispatchPlanReadinessV1(
        status="ready",
        checked_at=now,
        capabilities={"headed_worker_ready": True},
    )


def _service(db, now: list[datetime], *, repository=None) -> DispatchPlanService:
    return DispatchPlanService(
        db,
        repository=repository,
        clock=lambda: now[0],
        token_factory=lambda: "confirmation-token-0123456789",
    )


def _create_linked_job(db, preparation, *, payload=None) -> CrawlJob:
    return CrawlJobRepository().create_crawl_job(
        db,
        source_site="jobsdb",
        trigger_type="manual",
        request_payload=payload or {"crawl_phase": "listing"},
        dispatch_plan_id=preparation.plan.plan_id,
        dispatch_plan_fingerprint=preparation.plan.plan_fingerprint,
    )


def test_prepare_consume_is_single_use_and_payload_is_not_authority(dispatch_db):
    _engine, _factory, db, revision = dispatch_db
    now = [datetime(2026, 7, 20, 10, 0, tzinfo=UTC)]
    service = _service(db, now)
    preparation = service.prepare(
        _listing_content(revision),
        readiness=_ready(now[0]),
        prepared_by="operator@example.com",
    )
    crawl_job = _create_linked_job(
        db,
        preparation,
        payload={
            "crawl_phase": "detail",
            "category_ids": ["attacker-controlled"],
            "run_page_cap": 999999,
        },
    )

    with pytest.raises(DispatchPlanStaleError) as bad_token:
        service.consume(
            preparation.plan.plan_id,
            crawl_job_id=crawl_job.id,
            confirmation_token="wrong-confirmation-token",
        )
    assert bad_token.value.code == "DISPATCH_PLAN_STALE"
    assert service.get(preparation.plan.plan_id).state == "prepared"

    consumed = service.consume(
        preparation.plan.plan_id,
        crawl_job_id=crawl_job.id,
        confirmation_token=preparation.confirmation_token,
        expected_plan_fingerprint=preparation.plan.plan_fingerprint,
    )
    assert consumed.state == "consumed"
    assert consumed.crawl_job_id == crawl_job.id

    with pytest.raises(DispatchPlanAlreadyConsumedError) as reused:
        service.consume(
            preparation.plan.plan_id,
            crawl_job_id=crawl_job.id,
            confirmation_token=preparation.confirmation_token,
        )
    assert reused.value.code == "DISPATCH_PLAN_ALREADY_CONSUMED"

    authority = service.load_execution_authority(crawl_job.id)
    assert authority is not None
    assert authority.dispatch_plan.content.crawl_phase == "listing"
    assert authority.dispatch_plan.content.listing_settings.run_page_cap == 10


def test_expiry_is_durable_and_cleanup_deletes_only_expired_plans(dispatch_db):
    _engine, _factory, db, revision = dispatch_db
    now = [datetime(2026, 7, 20, 10, 0, tzinfo=UTC)]
    service = _service(db, now)
    preparation = service.prepare(
        _listing_content(revision),
        readiness=_ready(now[0]),
        prepared_by="operator@example.com",
        ttl=timedelta(minutes=1),
    )
    crawl_job = _create_linked_job(db, preparation)
    now[0] += timedelta(minutes=2)

    with pytest.raises(DispatchPlanExpiredError) as expired:
        service.consume(
            preparation.plan.plan_id,
            crawl_job_id=crawl_job.id,
            confirmation_token=preparation.confirmation_token,
        )
    assert expired.value.code == "DISPATCH_PLAN_EXPIRED"
    assert service.get(preparation.plan.plan_id).state == "expired"

    db.delete(crawl_job)
    db.commit()
    result = service.cleanup_expired(retention=timedelta(0))
    assert result.expired_count == 0
    assert result.deleted_count == 1
    assert db.query(CrawlDispatchPlan).count() == 0


def test_cleanup_retains_recent_expired_plan(dispatch_db):
    _engine, _factory, db, revision = dispatch_db
    now = [datetime(2026, 7, 20, 10, 0, tzinfo=UTC)]
    service = _service(db, now)
    preparation = service.prepare(
        _listing_content(revision),
        readiness=_ready(now[0]),
        prepared_by="operator@example.com",
        ttl=timedelta(minutes=1),
    )
    now[0] += timedelta(minutes=2)

    result = service.cleanup_expired(retention=timedelta(days=7))

    assert result.expired_count == 1
    assert result.deleted_count == 0
    assert service.get(preparation.plan.plan_id).state == "expired"


def test_snapshot_reconstructs_deterministic_target_and_row_order(
    dispatch_db,
    caplog,
):
    _engine, _factory, db, revision = dispatch_db
    now = [datetime(2026, 7, 20, 10, 0, tzinfo=UTC)]
    rows = [
        CrawlJobListing(
            crawl_job_id=uuid4(),
            source_site="jobsdb",
            source_job_id=f"row-{index}",
            source_url=f"https://example.test/jobs/{index}",
            listing_payload={"index": index},
            detail_status="pending",
        )
        for index in range(3)
    ]
    db.add_all(rows)
    db.commit()
    targets = (
        DispatchPlanTargetV1(
            source_site="jobsdb",
            source_job_id="z-target",
            selection_order=0,
            eligibility_fingerprint="1" * 64,
            eligibility_status="pending",
            rows=(
                DispatchPlanTargetRowV1(
                    crawl_job_listing_id=rows[2].id,
                    row_order=0,
                    eligibility_fingerprint="2" * 64,
                    eligibility_status="pending",
                ),
                DispatchPlanTargetRowV1(
                    crawl_job_listing_id=rows[0].id,
                    row_order=1,
                    eligibility_fingerprint="3" * 64,
                    eligibility_status="pending",
                ),
            ),
        ),
        DispatchPlanTargetV1(
            source_site="jobsdb",
            source_job_id="a-target",
            selection_order=1,
            eligibility_fingerprint="4" * 64,
            eligibility_status="pending",
            rows=(
                DispatchPlanTargetRowV1(
                    crawl_job_listing_id=rows[1].id,
                    row_order=0,
                    eligibility_fingerprint="5" * 64,
                    eligibility_status="pending",
                ),
            ),
        ),
    )
    preparation = _service(db, now).prepare(
        _detail_content(revision),
        readiness=_ready(now[0]),
        targets=targets,
        prepared_by="operator@example.com",
    )

    snapshot = _service(db, now).get(preparation.plan.plan_id)
    assert [target.source_job_id for target in snapshot.targets] == [
        "z-target",
        "a-target",
    ]
    assert [
        row.crawl_job_listing_id for row in snapshot.targets[0].rows
    ] == [rows[2].id, rows[0].id]
    assert "z-target" not in caplog.text
    assert "a-target" not in caplog.text


def test_plan_and_execution_link_tamper_fail_closed(dispatch_db):
    _engine, _factory, db, revision = dispatch_db
    now = [datetime(2026, 7, 20, 10, 0, tzinfo=UTC)]
    service = _service(db, now)
    preparation = service.prepare(
        _listing_content(revision),
        readiness=_ready(now[0]),
        prepared_by="operator@example.com",
    )
    crawl_job = _create_linked_job(db, preparation)
    service.consume(
        preparation.plan.plan_id,
        crawl_job_id=crawl_job.id,
        confirmation_token=preparation.confirmation_token,
    )
    execution = ScheduleExecution(
        schedule_id=None,
        crawl_job_id=crawl_job.id,
        dispatch_plan_id=preparation.plan.plan_id,
        dispatch_plan_fingerprint="0" * 64,
        status="pending",
    )
    db.add(execution)
    db.commit()

    with pytest.raises(DispatchPlanFingerprintMismatchError):
        service.load_execution_authority(crawl_job.id)

    db.delete(execution)
    db.commit()
    db.execute(
        update(CrawlDispatchPlan)
        .where(CrawlDispatchPlan.id == preparation.plan.plan_id)
        .values(prepared_by="tampered@example.com")
    )
    db.commit()
    with pytest.raises(DispatchPlanFingerprintMismatchError) as tampered:
        service.get(preparation.plan.plan_id)
    assert tampered.value.code == "DISPATCH_PLAN_FINGERPRINT_MISMATCH"


def test_consumption_failure_rolls_back_plan_lifecycle(dispatch_db):
    _engine, _factory, db, revision = dispatch_db
    now = [datetime(2026, 7, 20, 10, 0, tzinfo=UTC)]
    preparation = _service(db, now).prepare(
        _listing_content(revision),
        readiness=_ready(now[0]),
        prepared_by="operator@example.com",
    )
    crawl_job = _create_linked_job(db, preparation)

    class FailingRepository(DispatchPlanRepository):
        def mark_consumed(self, plan, *, crawl_job_id, consumed_at):
            super().mark_consumed(
                plan,
                crawl_job_id=crawl_job_id,
                consumed_at=consumed_at,
            )
            raise RuntimeError("injected consumption failure")

    service = _service(db, now, repository=FailingRepository())
    with pytest.raises(RuntimeError, match="injected consumption failure"):
        service.consume(
            preparation.plan.plan_id,
            crawl_job_id=crawl_job.id,
            confirmation_token=preparation.confirmation_token,
        )
    assert _service(db, now).get(preparation.plan.plan_id).state == "prepared"


def test_missing_fingerprint_and_legacy_jobs_are_distinguished(dispatch_db):
    _engine, _factory, db, revision = dispatch_db
    now = [datetime(2026, 7, 20, 10, 0, tzinfo=UTC)]
    preparation = _service(db, now).prepare(
        _listing_content(revision),
        readiness=_ready(now[0]),
        prepared_by="operator@example.com",
    )
    repository = CrawlJobRepository()
    with pytest.raises(ValueError, match="supplied together"):
        repository.create_crawl_job(
            db,
            source_site="jobsdb",
            trigger_type="manual",
            request_payload={"crawl_phase": "listing"},
            dispatch_plan_id=preparation.plan.plan_id,
        )

    partial = CrawlJob(
        source_site="jobsdb",
        trigger_type="manual",
        request_payload={"crawl_phase": "listing"},
        dispatch_plan_id=preparation.plan.plan_id,
    )
    db.add(partial)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    legacy = repository.create_crawl_job(
        db,
        source_site="jobsdb",
        trigger_type="manual",
        request_payload={"crawl_phase": "listing"},
    )
    assert _service(db, now).load_execution_authority(legacy.id) is None
    startup = load_legacy_worker_startup_input(
        db,
        crawl_job_id=legacy.id,
        default_source_site="jobsdb",
    )
    assert startup.request_payload == {"crawl_phase": "listing"}


def test_resume_overlay_contract_cannot_carry_scope_or_limits():
    overlay = ExecutionResumeContextV1(
        manual_action_event_sequence=3,
        requested_at=datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
        resume_strategy="fresh_profile",
        manual_action_classification="ip_blocked",
        detail_statuses=("manual_action_required", "pending"),
    )

    assert set(overlay.model_dump()) == {
        "version",
        "is_resume",
        "manual_action_event_sequence",
        "requested_at",
        "resume_strategy",
        "manual_action_classification",
        "detail_statuses",
        "browser_channel",
        "browser_profile_path",
    }


def test_launcher_rejects_unconsumed_versioned_plan_before_process_creation(
    dispatch_db,
):
    _engine, factory, db, revision = dispatch_db
    now = [datetime(2026, 7, 20, 10, 0, tzinfo=UTC)]
    preparation = _service(db, now).prepare(
        _listing_content(revision),
        readiness=_ready(now[0]),
        prepared_by="operator@example.com",
    )
    crawl_job = _create_linked_job(db, preparation)
    popen_calls = []
    launcher = CrawlJobExecutionLauncher(
        session_factory=factory,
        popen=lambda *_args, **_kwargs: popen_calls.append(True),
    )

    with pytest.raises(DispatchPlanStaleError) as stale:
        launcher.launch(crawl_job)
    assert stale.value.code == "DISPATCH_PLAN_STALE"
    assert popen_calls == []


def test_consumed_plan_fails_closed_until_worker_reads_authority(dispatch_db):
    _engine, factory, db, revision = dispatch_db
    now = [datetime(2026, 7, 20, 10, 0, tzinfo=UTC)]
    service = _service(db, now)
    preparation = service.prepare(
        _listing_content(revision),
        readiness=_ready(now[0]),
        prepared_by="operator@example.com",
    )
    crawl_job = _create_linked_job(
        db,
        preparation,
        payload={"crawl_phase": "detail", "max_pages": 999999},
    )
    service.consume(
        preparation.plan.plan_id,
        crawl_job_id=crawl_job.id,
        confirmation_token=preparation.confirmation_token,
    )
    original_payload = dict(crawl_job.request_payload)
    popen_calls = []
    launcher = CrawlJobExecutionLauncher(
        session_factory=factory,
        popen=lambda *_args, **_kwargs: popen_calls.append(True),
    )

    with pytest.raises(DispatchPlanStaleError) as unsupported:
        launcher.launch(crawl_job)
    assert unsupported.value.context["reason"] == (
        "runtime_authority_adapter_required"
    )
    with pytest.raises(DispatchPlanStaleError):
        load_legacy_worker_startup_input(
            db,
            crawl_job_id=crawl_job.id,
            default_source_site="jobsdb",
        )
    crawl_job.request_payload = {"crawl_phase": "listing"}
    with pytest.raises(ValueError, match="compatibility request payload"):
        db.commit()
    db.rollback()
    db.refresh(crawl_job)
    assert crawl_job.request_payload == original_payload
    assert popen_calls == []


def test_versioned_resume_cannot_rewrite_compatibility_payload(dispatch_db):
    _engine, _factory, db, revision = dispatch_db
    now = [datetime(2026, 7, 20, 10, 0, tzinfo=UTC)]
    plan_service = _service(db, now)
    preparation = plan_service.prepare(
        _listing_content(revision),
        readiness=_ready(now[0]),
        prepared_by="operator@example.com",
    )
    crawl_job = _create_linked_job(
        db,
        preparation,
        payload={"crawl_phase": "detail", "max_pages": 999999},
    )
    plan_service.consume(
        preparation.plan.plan_id,
        crawl_job_id=crawl_job.id,
        confirmation_token=preparation.confirmation_token,
    )
    crawl_job.status = "manual_action_required"
    db.commit()
    manual_action = build_session_recovery_manual_action(
        source_site="jobsdb",
        stage="listing",
        blocked_url="https://example.test/jobs",
        classification="ip_blocked",
        resume_context={
            "crawl_phase": "detail",
            "category_ids": ["tampered"],
            "detail_limit": 999999,
        },
    ).to_payload(
        crawl_mode="headless",
        browser_channel="msedge",
        browser_profile_path="/tmp/profile",
    )
    CrawlJobRepository().append_event(
        db,
        crawl_job_id=crawl_job.id,
        event_type="crawl.manual_action_required",
        payload={"manual_action": manual_action},
    )
    original_payload = dict(crawl_job.request_payload)

    with pytest.raises(DispatchPlanStaleError) as unsupported:
        CrawlJobDispatchService().resume_crawl_job(
            db,
            crawl_job_id=crawl_job.id,
            requested_by="operator@example.com",
        )

    assert unsupported.value.context["reason"] == (
        "runtime_authority_adapter_required"
    )
    db.rollback()
    db.refresh(crawl_job)
    assert crawl_job.status == "manual_action_required"
    assert crawl_job.request_payload == original_payload
    assert crawl_job.resume_context is None
