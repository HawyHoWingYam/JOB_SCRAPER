from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
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
    ExecutionResumeContextV1,
)
from app.crawl_control.dispatch_plan_repository import DispatchPlanRepository
from app.crawl_control.dispatch_plan_service import DispatchPlanService
from app.crawl_control.detail_runtime import DetailBacklogSnapshotBuilder
from app.crawl_control.errors import (
    DispatchPlanAlreadyConsumedError,
    DispatchPlanExpiredError,
    DispatchPlanFingerprintMismatchError,
    DispatchPlanStaleError,
    BacklogSafetyCapExceededError,
    WorkloadCapExceededError,
)
from app.crawl_control.runtime_authority import (
    load_legacy_worker_startup_input,
    load_worker_startup_input,
)
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
from app.repositories.crawl_job_listing_repository import (
    CrawlJobListingRepository,
)
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.scraper.manual_action import build_session_recovery_manual_action
from app.services.crawl_job_dispatch_service import CrawlJobDispatchService
from app.services.crawl_job_cancellation_service import CrawlJobCancellationService
from app.services.crawl_job_execution_launcher import CrawlJobExecutionLauncher
from app.services.crawl_job_runtime import CrawlJobRuntime
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


def _detail_content_with_settings(
    revision: SourceCatalogRevision,
    settings: dict,
) -> DispatchPlanContentV1:
    content = _detail_content(revision)
    return DispatchPlanContentV1.model_validate(
        {
            **content.model_dump(mode="json"),
            "detail_settings": settings,
        }
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


def _staging_row(
    *,
    source_job_id: str,
    crawl_job_id: UUID,
    created_at: datetime,
    classification_id: str | None = "jobsdb:6281",
    listing_rank: int | None = None,
    detail_status: str = "pending",
) -> CrawlJobListing:
    return CrawlJobListing(
        crawl_job_id=crawl_job_id,
        source_site="jobsdb",
        source_job_id=source_job_id,
        source_url=f"https://example.test/jobs/{source_job_id}",
        source_classification_id=classification_id,
        source_classification_name=(
            "Information Technology" if classification_id else None
        ),
        listing_rank=listing_rank,
        listing_payload={"source_job_id": source_job_id},
        detail_status=detail_status,
        created_at=created_at,
        updated_at=created_at,
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


def test_prepare_rejects_listing_workload_above_reviewed_cap(dispatch_db):
    _engine, _factory, db, revision = dispatch_db
    now = [datetime(2026, 7, 20, 10, 0, tzinfo=UTC)]
    content = _listing_content(revision).model_copy(
        update={
            "listing_settings": ListingSettingsV1(
                crawl_mode="headless",
                page_depth=2,
                run_page_cap=1,
            )
        }
    )

    with pytest.raises(WorkloadCapExceededError) as over_cap:
        _service(db, now).prepare(
            content,
            readiness=_ready(now[0]),
            prepared_by="operator@example.com",
        )

    assert over_cap.value.context == {
        "estimated_max_pages": 2,
        "run_page_cap": 1,
        "system_run_page_cap": 1000,
    }


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
    source_job_ids = ("z-target", "a-target", "z-target")
    listing_ranks = (2, 3, 1)
    rows = [
        CrawlJobListing(
            crawl_job_id=uuid4(),
            source_site="jobsdb",
            source_job_id=source_job_ids[index],
            source_url=f"https://example.test/jobs/{index}",
            listing_payload={"index": index},
            listing_rank=listing_ranks[index],
            detail_status="pending",
            created_at=now[0] - timedelta(minutes=1),
            updated_at=now[0] - timedelta(minutes=1),
        )
        for index in range(3)
    ]
    db.add_all(rows)
    db.commit()
    preparation = _service(db, now).prepare(
        _detail_content(revision),
        readiness=_ready(now[0]),
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
    assert snapshot.content.detail_settings.backlog_snapshot.selected_target_count == 2
    assert snapshot.content.detail_settings.backlog_snapshot.selected_row_count == 3
    assert "z-target" not in caplog.text
    assert "a-target" not in caplog.text


def test_detail_backlog_scopes_freeze_duplicates_nulls_batches_and_cutoff(
    dispatch_db,
):
    _engine, _factory, db, revision = dispatch_db
    now = [datetime(2026, 7, 20, 10, 0, tzinfo=UTC)]
    batch_one = uuid4()
    batch_two = uuid4()
    rows = (
        _staging_row(
            source_job_id="duplicate",
            crawl_job_id=batch_one,
            created_at=now[0] - timedelta(minutes=5),
            listing_rank=1,
        ),
        _staging_row(
            source_job_id="duplicate",
            crawl_job_id=batch_two,
            created_at=now[0] - timedelta(minutes=4),
            listing_rank=2,
        ),
        _staging_row(
            source_job_id="null-classification",
            crawl_job_id=batch_one,
            classification_id=None,
            created_at=now[0] - timedelta(minutes=3),
            listing_rank=3,
        ),
        _staging_row(
            source_job_id="other-classification",
            crawl_job_id=batch_one,
            classification_id="jobsdb:9999",
            created_at=now[0] - timedelta(minutes=2),
            listing_rank=4,
        ),
        _staging_row(
            source_job_id="after-cutoff",
            crawl_job_id=batch_one,
            created_at=now[0] + timedelta(minutes=1),
            listing_rank=0,
        ),
    )
    db.add_all(rows)
    db.commit()

    source_plan = _service(db, now).prepare(
        _detail_content_with_settings(
            revision,
            {
                "crawl_mode": "headless",
                "backlog_scope": {"kind": "source_backlog"},
                "limit": {"kind": "entire_snapshot"},
            },
        ),
        readiness=_ready(now[0]),
        prepared_by="operator@example.com",
    ).plan
    assert [target.source_job_id for target in source_plan.targets] == [
        "duplicate",
        "null-classification",
        "other-classification",
    ]
    assert [
        row.crawl_job_listing_id for row in source_plan.targets[0].rows
    ] == [rows[0].id, rows[1].id]
    source_snapshot = source_plan.content.detail_settings.backlog_snapshot
    assert source_snapshot is not None
    assert source_snapshot.eligible_target_count == 3
    assert source_snapshot.selected_row_count == 4

    crawl_scope_plan = _service(db, now).prepare(
        _detail_content_with_settings(
            revision,
            {
                "crawl_mode": "headless",
                "backlog_scope": {
                    "kind": "crawl_scope",
                    "scope": _scope(revision.id).model_dump(mode="json"),
                },
                "limit": {"kind": "entire_snapshot"},
            },
        ),
        readiness=_ready(now[0]),
        prepared_by="operator@example.com",
    ).plan
    assert [target.source_job_id for target in crawl_scope_plan.targets] == [
        "duplicate"
    ]

    listing_batch_plan = _service(db, now).prepare(
        _detail_content_with_settings(
            revision,
            {
                "crawl_mode": "headless",
                "backlog_scope": {
                    "kind": "listing_batch",
                    "source_listing_crawl_job_id": str(batch_one),
                },
                "limit": {"kind": "entire_snapshot"},
            },
        ),
        readiness=_ready(now[0]),
        prepared_by="operator@example.com",
    ).plan
    assert [target.source_job_id for target in listing_batch_plan.targets] == [
        "duplicate",
        "null-classification",
        "other-classification",
    ]
    assert [
        row.crawl_job_listing_id for row in listing_batch_plan.targets[0].rows
    ] == [rows[0].id]
    assert all(
        target.source_job_id != "after-cutoff"
        for plan in (source_plan, crawl_scope_plan, listing_batch_plan)
        for target in plan.targets
    )


def test_entire_detail_snapshot_fails_closed_above_absolute_safety_cap(
    dispatch_db,
):
    _engine, _factory, db, revision = dispatch_db
    now = [datetime(2026, 7, 20, 10, 0, tzinfo=UTC)]
    db.add_all(
        [
            _staging_row(
                source_job_id=f"job-{index}",
                crawl_job_id=uuid4(),
                created_at=now[0] - timedelta(minutes=1),
                listing_rank=index,
            )
            for index in range(2)
        ]
    )
    db.commit()
    service = DispatchPlanService(
        db,
        clock=lambda: now[0],
        token_factory=lambda: "confirmation-token-0123456789",
        detail_backlog_builder=DetailBacklogSnapshotBuilder(
            absolute_safety_cap=1
        ),
    )

    with pytest.raises(BacklogSafetyCapExceededError) as over_cap:
        service.prepare(
            _detail_content_with_settings(
                revision,
                {
                    "crawl_mode": "headless",
                    "backlog_scope": {"kind": "source_backlog"},
                    "limit": {"kind": "entire_snapshot"},
                },
            ),
            readiness=_ready(now[0]),
            prepared_by="operator@example.com",
        )

    assert over_cap.value.code == "BACKLOG_SAFETY_CAP_EXCEEDED"
    assert over_cap.value.context["eligible_target_count"] == 2
    assert db.query(CrawlDispatchPlan).count() == 0


def test_offertoday_future_terminal_sibling_cannot_change_snapshot_cutoff(
    dispatch_db,
):
    _engine, _factory, db, _revision = dispatch_db
    cutoff = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
    pending = CrawlJobListing(
        crawl_job_id=uuid4(),
        source_site="offertoday",
        source_job_id="same-job",
        source_url="https://www.offertoday.com/jobs/same-job",
        listing_payload={"job_id": "same-job"},
        detail_status="pending",
        created_at=cutoff - timedelta(minutes=1),
        updated_at=cutoff - timedelta(minutes=1),
    )
    future_terminal = CrawlJobListing(
        crawl_job_id=uuid4(),
        source_site="offertoday",
        source_job_id="same-job",
        source_url="https://www.offertoday.com/jobs/same-job",
        listing_payload={"job_id": "same-job"},
        detail_status="terminal_unavailable",
        created_at=cutoff + timedelta(minutes=1),
        updated_at=cutoff + timedelta(minutes=1),
    )
    db.add_all((pending, future_terminal))
    db.commit()

    selected = CrawlJobListingRepository().list_detail_candidates(
        db,
        source_site="offertoday",
        detail_scope="global",
        eligible_at_or_before=cutoff,
    )

    assert [row.id for row in selected] == [pending.id]


def test_empty_detail_snapshot_is_persisted_as_blocked_review(dispatch_db):
    _engine, _factory, db, revision = dispatch_db
    now = [datetime(2026, 7, 20, 10, 0, tzinfo=UTC)]

    preparation = _service(db, now).prepare(
        _detail_content_with_settings(
            revision,
            {
                "crawl_mode": "headless",
                "backlog_scope": {"kind": "source_backlog"},
                "limit": {"kind": "entire_snapshot"},
            },
        ),
        readiness=_ready(now[0]),
        prepared_by="operator@example.com",
    )

    assert preparation.plan.targets == ()
    assert preparation.plan.readiness.status == "blocked"
    assert preparation.plan.readiness.blocking_errors[0].code == (
        "DETAIL_BACKLOG_EMPTY"
    )
    assert preparation.confirmation_token is None


def test_versioned_detail_runtime_uses_only_frozen_membership_and_tracks_future(
    dispatch_db,
):
    _engine, factory, db, revision = dispatch_db
    now = [datetime(2026, 7, 20, 10, 0, tzinfo=UTC)]
    listing_jobs = tuple(
        CrawlJobRepository().create_crawl_job(
            db,
            source_site="jobsdb",
            trigger_type="manual",
            request_payload={"crawl_phase": "listing"},
        )
        for _index in range(2)
    )
    duplicate_rows = (
        _staging_row(
            source_job_id="frozen-duplicate",
            crawl_job_id=listing_jobs[0].id,
            created_at=now[0] - timedelta(minutes=2),
            listing_rank=1,
        ),
        _staging_row(
            source_job_id="frozen-duplicate",
            crawl_job_id=listing_jobs[1].id,
            created_at=now[0] - timedelta(minutes=1),
            listing_rank=2,
        ),
    )
    db.add_all(duplicate_rows)
    db.commit()
    service = _service(db, now)
    preparation = service.prepare(
        _detail_content_with_settings(
            revision,
            {
                "crawl_mode": "headless",
                "backlog_scope": {"kind": "source_backlog"},
                "limit": {"kind": "stop_after", "detail_run_cap": 1},
            },
        ),
        readiness=_ready(now[0]),
        prepared_by="operator@example.com",
    )
    crawl_job = _create_linked_job(
        db,
        preparation,
        payload={
            "crawl_phase": "listing",
            "source_job_ids": ["attacker-controlled"],
            "detail_limit": 999999,
        },
    )
    service.consume(
        preparation.plan.plan_id,
        crawl_job_id=crawl_job.id,
        confirmation_token=preparation.confirmation_token,
    )
    future_row = _staging_row(
        source_job_id="future-job",
        crawl_job_id=uuid4(),
        created_at=now[0] + timedelta(minutes=1),
        listing_rank=0,
    )
    db.add(future_row)
    db.commit()

    startup = load_worker_startup_input(
        db,
        crawl_job_id=crawl_job.id,
        default_source_site="jobsdb",
    )
    assert startup.request_payload == {}
    assert startup.listing_runtime_plan is None
    assert startup.detail_runtime_plan is not None
    runtime = CrawlJobRuntime(factory)
    loaded = runtime.load_detail_targets(
        source_site="jobsdb",
        request_payload={"source_job_ids": ["future-job"]},
        detail_crawl_job_id=crawl_job.id,
        detail_runtime_plan=startup.detail_runtime_plan,
    )

    assert loaded.fetch_cohort_source_job_ids == ("frozen-duplicate",)
    assert loaded.targets[0]["listing_ids"] == tuple(
        row.id for row in duplicate_rows
    )
    assert loaded.snapshot_target_count == 1
    assert loaded.snapshot_remaining_target_count == 1
    assert loaded.live_future_eligible_target_count == 1
    runtime.mark_detail_running(
        listing_ids=loaded.targets[0]["listing_ids"],
        detail_crawl_job_id=crawl_job.id,
    )
    db.expire_all()
    assert {
        db.query(CrawlJobListing).filter(CrawlJobListing.id == row.id).one().detail_status
        for row in duplicate_rows
    } == {"running"}
    duplicate_rows[0].listing_payload = {"tampered": True}
    db.commit()
    with pytest.raises(DispatchPlanStaleError) as changed_inputs:
        runtime.load_detail_targets(
            source_site="jobsdb",
            request_payload={},
            detail_crawl_job_id=crawl_job.id,
            detail_runtime_plan=startup.detail_runtime_plan,
        )
    assert changed_inputs.value.context["reason"] == (
        "detail_target_inputs_changed"
    )


def test_versioned_cancellation_releases_only_frozen_running_membership(
    dispatch_db,
):
    _engine, factory, db, revision = dispatch_db
    now = [datetime(2026, 7, 20, 10, 0, tzinfo=UTC)]
    frozen_running = _staging_row(
        source_job_id="frozen-running",
        crawl_job_id=uuid4(),
        created_at=now[0] - timedelta(minutes=2),
        listing_rank=1,
    )
    frozen_settled = _staging_row(
        source_job_id="frozen-settled",
        crawl_job_id=uuid4(),
        created_at=now[0] - timedelta(minutes=1),
        listing_rank=2,
    )
    db.add_all((frozen_running, frozen_settled))
    db.commit()
    preparation = _service(db, now).prepare(
        _detail_content_with_settings(
            revision,
            {
                "crawl_mode": "headless",
                "backlog_scope": {"kind": "source_backlog"},
                "limit": {"kind": "entire_snapshot"},
            },
        ),
        readiness=_ready(now[0]),
        prepared_by="operator@example.com",
    )
    crawl_job = _create_linked_job(
        db,
        preparation,
        payload={"crawl_phase": "detail"},
    )
    _service(db, now).consume(
        preparation.plan.plan_id,
        crawl_job_id=crawl_job.id,
        confirmation_token=preparation.confirmation_token,
    )
    rogue = _staging_row(
        source_job_id="not-in-plan",
        crawl_job_id=uuid4(),
        created_at=now[0] + timedelta(minutes=1),
        listing_rank=3,
    )
    db.add(rogue)
    db.flush()
    frozen_running.detail_status = "running"
    frozen_running.last_detail_crawl_job_id = crawl_job.id
    frozen_settled.detail_status = "completed"
    frozen_settled.last_detail_crawl_job_id = crawl_job.id
    rogue.detail_status = "running"
    rogue.last_detail_crawl_job_id = crawl_job.id
    crawl_job.status = "cancelling"
    db.commit()

    assert CrawlJobCancellationService(
        session_factory=factory
    ).acknowledge_cancelled(crawl_job_id=crawl_job.id)
    db.expire_all()
    assert db.get(CrawlJobListing, frozen_running.id).detail_status == "pending"
    assert db.get(CrawlJobListing, frozen_settled.id).detail_status == "completed"
    assert db.get(CrawlJobListing, rogue.id).detail_status == "running"
    db.refresh(crawl_job)
    assert crawl_job.status == "cancelled"


def test_versioned_content_anomaly_resume_retries_failed_and_manual_membership(
    dispatch_db,
):
    _engine, factory, db, revision = dispatch_db
    now = [datetime(2026, 7, 20, 10, 0, tzinfo=UTC)]
    rows = (
        _staging_row(
            source_job_id="completed-before-resume",
            crawl_job_id=uuid4(),
            created_at=now[0] - timedelta(minutes=2),
            listing_rank=1,
        ),
        _staging_row(
            source_job_id="failed-before-resume",
            crawl_job_id=uuid4(),
            created_at=now[0] - timedelta(minutes=1),
            listing_rank=2,
        ),
        _staging_row(
            source_job_id="manual-before-resume",
            crawl_job_id=uuid4(),
            created_at=now[0] - timedelta(seconds=30),
            listing_rank=3,
        ),
    )
    db.add_all(rows)
    db.commit()
    plan_service = _service(db, now)
    preparation = plan_service.prepare(
        _detail_content_with_settings(
            revision,
            {
                "crawl_mode": "headless",
                "backlog_scope": {"kind": "source_backlog"},
                "limit": {"kind": "entire_snapshot"},
            },
        ),
        readiness=_ready(now[0]),
        prepared_by="operator@example.com",
    )
    crawl_job = _create_linked_job(
        db,
        preparation,
        payload={"crawl_phase": "listing", "detail_limit": 999999},
    )
    plan_service.consume(
        preparation.plan.plan_id,
        crawl_job_id=crawl_job.id,
        confirmation_token=preparation.confirmation_token,
    )
    rows[0].detail_status = "completed"
    rows[0].last_detail_crawl_job_id = crawl_job.id
    rows[1].detail_status = "failed"
    rows[1].last_detail_crawl_job_id = crawl_job.id
    rows[2].detail_status = "manual_action_required"
    rows[2].last_detail_crawl_job_id = crawl_job.id
    crawl_job.status = "manual_action_required"
    db.commit()
    manual_action = build_session_recovery_manual_action(
        source_site="jobsdb",
        stage="detail",
        blocked_url="https://example.test/jobs/manual-before-resume",
        classification="content_anomaly",
        resume_context={
            "crawl_phase": "detail",
            "source_job_ids": ["attacker-controlled"],
            "detail_limit": 999999,
        },
    ).to_payload(
        crawl_mode="headless",
        browser_channel=None,
        browser_profile_path=None,
    )
    CrawlJobRepository().append_event(
        db,
        crawl_job_id=crawl_job.id,
        event_type="crawl.manual_action_required",
        payload={"manual_action": manual_action},
    )
    original_payload = dict(crawl_job.request_payload)

    class Launcher:
        @staticmethod
        def should_launch_locally(_crawl_job):
            return True

        @staticmethod
        def launch(_crawl_job):
            return SimpleNamespace(launched=True, command=("python", "worker"))

    resumed = CrawlJobDispatchService(
        execution_launcher=Launcher(),
    ).resume_crawl_job(
        db,
        crawl_job_id=crawl_job.id,
        requested_by="operator@example.com",
    )

    assert resumed.status == "dispatching"
    assert resumed.request_payload == original_payload
    assert resumed.resume_context["detail_statuses"] == [
        "failed",
        "manual_action_required",
        "pending",
    ]
    startup = load_worker_startup_input(
        db,
        crawl_job_id=crawl_job.id,
        default_source_site="jobsdb",
    )
    assert startup.detail_runtime_plan is not None
    loaded = CrawlJobRuntime(factory).load_detail_targets(
        source_site="jobsdb",
        request_payload={"source_job_ids": ["attacker-controlled"]},
        detail_crawl_job_id=crawl_job.id,
        detail_runtime_plan=startup.detail_runtime_plan,
    )
    assert loaded.fetch_cohort_source_job_ids == (
        "failed-before-resume",
        "manual-before-resume",
    )


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


def test_consumed_listing_plan_launches_and_worker_ignores_compatibility_payload(
    dispatch_db,
):
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
    process = type("Process", (), {"pid": 4321})()
    launcher = CrawlJobExecutionLauncher(
        session_factory=factory,
        popen=lambda *args, **kwargs: popen_calls.append((args, kwargs))
        or process,
        process_factory=lambda _pid: type(
            "ProcessSnapshot",
            (),
            {"create_time": lambda self: 123.0},
        )(),
    )
    launcher._start_monitor = lambda _generation: None

    launch_result = launcher.launch(crawl_job)
    assert launch_result.launched is True
    with pytest.raises(DispatchPlanStaleError):
        load_legacy_worker_startup_input(
            db,
            crawl_job_id=crawl_job.id,
            default_source_site="jobsdb",
        )
    startup = load_worker_startup_input(
        db,
        crawl_job_id=crawl_job.id,
        default_source_site="jobsdb",
    )
    assert startup.request_payload == {}
    assert startup.listing_runtime_plan is not None
    assert startup.listing_runtime_plan.page_depth == 2
    assert startup.listing_runtime_plan.run_page_cap == 10
    assert [
        target.classification_id
        for target in startup.listing_runtime_plan.targets
    ] == ["jobsdb:6281"]
    with pytest.raises(DispatchPlanStaleError) as wrong_worker:
        load_worker_startup_input(
            db,
            crawl_job_id=crawl_job.id,
            default_source_site="ctgoodjobs",
        )
    assert wrong_worker.value.context["reason"] == "worker_source_mismatch"
    crawl_job.request_payload = {"crawl_phase": "listing"}
    with pytest.raises(ValueError, match="compatibility request payload"):
        db.commit()
    db.rollback()
    db.refresh(crawl_job)
    assert crawl_job.request_payload == original_payload
    assert len(popen_calls) == 1


def test_worker_startup_missing_job_fails_closed(dispatch_db):
    _engine, _factory, db, _revision = dispatch_db

    with pytest.raises(DispatchPlanStaleError) as missing:
        load_worker_startup_input(
            db,
            crawl_job_id=uuid4(),
            default_source_site="jobsdb",
        )

    assert missing.value.context["reason"] == "crawl_job_missing"


def test_versioned_worker_wraps_malformed_resume_context_as_stale(dispatch_db):
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
    crawl_job.resume_context = {"is_resume": True, "detail_limit": 999999}
    db.commit()

    with pytest.raises(DispatchPlanStaleError) as invalid_resume:
        load_worker_startup_input(
            db,
            crawl_job_id=crawl_job.id,
            default_source_site="jobsdb",
        )

    assert invalid_resume.value.context["reason"] == "resume_context_invalid"


def test_versioned_launcher_popen_failure_settles_execution_and_job(dispatch_db):
    _engine, factory, db, revision = dispatch_db
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

    def fail_popen(*_args, **_kwargs):
        raise OSError("process unavailable")

    launcher = CrawlJobExecutionLauncher(
        session_factory=factory,
        popen=fail_popen,
    )
    with pytest.raises(OSError, match="process unavailable"):
        launcher.launch(crawl_job)

    db.expire_all()
    execution = db.query(CrawlJobExecution).one()
    db.refresh(crawl_job)
    assert execution.status == "launch_failed"
    assert crawl_job.status == "failed"
    assert crawl_job.error_message == "Crawler process launch failed: OSError"


def test_versioned_launcher_registration_failure_terminates_process(dispatch_db):
    _engine, factory, db, revision = dispatch_db
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
    process = type("Process", (), {"pid": 4321})()
    launcher = CrawlJobExecutionLauncher(
        session_factory=factory,
        popen=lambda *_args, **_kwargs: process,
        process_factory=lambda _pid: type(
            "ProcessSnapshot",
            (),
            {"create_time": lambda self: 123.0},
        )(),
    )
    terminated = []
    launcher._terminate_unregistered_process = terminated.append

    def fail_mark_running(*_args, **_kwargs):
        raise RuntimeError("registration failed")

    launcher._execution_repository.mark_running = fail_mark_running
    with pytest.raises(RuntimeError, match="registration failed"):
        launcher.launch(crawl_job)

    db.expire_all()
    execution = db.query(CrawlJobExecution).one()
    db.refresh(crawl_job)
    assert terminated == [process]
    assert execution.status == "launch_failed"
    assert crawl_job.status == "failed"


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
