from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from apscheduler.triggers.cron import CronTrigger
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.crawl_control.automation_contracts import AutomationConfigurationV1
from app.crawl_control.automation_service import AutomationService
from app.crawl_control.contracts import (
    AuthoredCrawlScopeV1,
    CrawlScopeErrorPayloadV1,
    DetailSettingsV1,
    ListingSettingsV1,
)
from app.crawl_control.errors import (
    AutomationDeleteReviewStaleError,
    AutomationRevisionConflictError,
    AutomationTransitionInvalidError,
    ScopeReviewRequiredError,
)
from app.models.crawl_job import CrawlJob
from app.models.crawl_job_listing import CrawlJobListing
from app.models.crawl_dispatch_plan import CRAWL_DISPATCH_PLAN_TABLES
from app.models.schedule import (
    AUTOMATION_CONTROL_TABLES,
    AutomationDeleteReview,
    AutomationRevision,
    ScheduleExecution,
    ScrapeSchedule,
)
from app.models.source_catalog import SourceCatalogCandidate, SourceCatalogRevision
from app.database import Base
from app.repositories.schedule_repository import ScheduleRepository
from app.services.crawl_job_dispatch_service import CrawlJobDispatchService
from app.services.scheduler_service import SchedulerService, _normalize_next_run_at


@compiles(UUID, "sqlite")
def compile_uuid_for_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(32)"


class StubScopeService:
    def __init__(self) -> None:
        self.reject = False
        self.calls: list[tuple[AuthoredCrawlScopeV1, ListingSettingsV1 | None]] = []

    def preview(self, scope, *, listing_settings=None):
        self.calls.append((scope, listing_settings))
        if self.reject:
            raise ScopeReviewRequiredError("Fixture Source Catalog advanced")
        return SimpleNamespace(resolved_scope=scope, listing_workload=None)


@pytest.fixture
def automation_db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    tables = (
        SourceCatalogCandidate.__table__,
        SourceCatalogRevision.__table__,
        AUTOMATION_CONTROL_TABLES[0],
        CrawlJob.__table__,
        CrawlJobListing.__table__,
        *CRAWL_DISPATCH_PLAN_TABLES,
        *AUTOMATION_CONTROL_TABLES[1:],
    )
    ScrapeSchedule.metadata.create_all(engine, tables=tables)
    factory = sessionmaker(bind=engine)
    db = factory()
    try:
        yield engine, factory, db
    finally:
        db.close()
        engine.dispose()


def _scope() -> AuthoredCrawlScopeV1:
    return AuthoredCrawlScopeV1(
        source_site="offertoday",
        reviewed_catalog_revision_id=uuid4(),
        mode="all",
    )


def _listing_configuration(
    *,
    name: str = "OfferToday listing",
    timezone: str = "America/New_York",
    page_depth: int = 2,
) -> AutomationConfigurationV1:
    return AutomationConfigurationV1(
        name=name,
        description="Versioned listing Automation",
        cron_expression="30 2 * * *",
        timezone=timezone,
        scope=_scope(),
        listing_settings=ListingSettingsV1(
            crawl_mode="headless",
            page_depth=page_depth,
            run_page_cap=100,
        ),
    )


def _detail_configuration(
    *,
    entire_snapshot: bool = False,
) -> AutomationConfigurationV1:
    return AutomationConfigurationV1(
        name="OfferToday detail",
        cron_expression="0 4 * * *",
        timezone="Europe/London",
        scope=_scope(),
        detail_settings=DetailSettingsV1.model_validate(
            {
                "crawl_mode": "headed",
                "backlog_scope": {"kind": "source_backlog"},
                "limit": (
                    {"kind": "entire_snapshot"}
                    if entire_snapshot
                    else {"kind": "stop_after", "detail_run_cap": 50}
                ),
            }
        ),
    )


def _service(db, scope_service: StubScopeService | None = None) -> AutomationService:
    return AutomationService(
        db,
        scope_service=scope_service or StubScopeService(),
    )


def test_automation_contracts_require_iana_timezone_and_one_phase_settings():
    listing = _listing_configuration()
    detail = _detail_configuration()

    assert listing.crawl_phase == "listing"
    assert listing.crawl_mode == "headless"
    assert detail.crawl_phase == "detail"
    assert detail.crawl_mode == "headed"
    with pytest.raises(ValidationError, match="Invalid timezone identifier"):
        _listing_configuration(timezone="Hong Kong local")
    with pytest.raises(ValidationError, match="exactly one"):
        AutomationConfigurationV1(
            name="Invalid",
            cron_expression="0 1 * * *",
            timezone="UTC",
            scope=_scope(),
        )

    normalized = _normalize_next_run_at(
        datetime(2026, 3, 8, 7, 30, tzinfo=UTC)
    )
    assert normalized is not None
    assert normalized.tzinfo is UTC

    trigger = CronTrigger.from_crontab(
        "30 2 * * *",
        timezone=ZoneInfo("America/New_York"),
    )
    winter = trigger.get_next_fire_time(
        None,
        datetime(2026, 1, 10, tzinfo=UTC),
    )
    summer = trigger.get_next_fire_time(
        None,
        datetime(2026, 7, 10, tzinfo=UTC),
    )
    assert winter is not None and summer is not None
    assert winter.utcoffset() == timedelta(hours=-5)
    assert summer.utcoffset() == timedelta(hours=-4)


def test_create_update_and_stale_cas_preserve_immutable_revisions(automation_db):
    _engine, factory, db = automation_db
    scope_service = StubScopeService()
    service = _service(db, scope_service)
    created = service.create(
        _listing_configuration(),
        actor="operator@example.com",
        initial_state="active",
    )
    automation_id = created.snapshot.automation_id

    row = db.get(ScrapeSchedule, automation_id)
    assert row.revision == 1
    assert row.lifecycle_state == "active"
    assert row.scope_contract["mode"] == "all"
    assert row.listing_page_depth == 2
    assert row.category_ids is None
    assert created.created_at.tzinfo is not None
    first_revision = db.query(AutomationRevision).one()
    first_snapshot = dict(first_revision.snapshot)

    stale_db = factory()
    stale_service = _service(stale_db, StubScopeService())
    stale_service.get(automation_id)
    updated = service.update_configuration(
        automation_id,
        expected_revision=1,
        configuration=_listing_configuration(name="Renamed", page_depth=3),
        actor="operator@example.com",
    )
    assert updated.snapshot.revision == 2
    assert updated.snapshot.configuration.name == "Renamed"
    assert db.query(AutomationRevision).count() == 2
    assert db.get(AutomationRevision, first_revision.id).snapshot == first_snapshot

    with pytest.raises(AutomationRevisionConflictError) as conflict:
        stale_service.update_configuration(
            automation_id,
            expected_revision=1,
            configuration=_listing_configuration(name="Lost update"),
            actor="second-operator@example.com",
        )
    assert conflict.value.context["current_revision"] == 2
    stale_db.rollback()
    stale_db.close()

    first_revision.snapshot = {"tampered": True}
    with pytest.raises(ValueError, match="immutable"):
        db.commit()
    db.rollback()
    assert db.get(AutomationRevision, first_revision.id).snapshot == first_snapshot
    assert len(scope_service.calls) == 2


def test_lifecycle_transitions_are_monotonic_and_scope_review_is_fail_closed(
    automation_db,
):
    _engine, _factory, db = automation_db
    scope_service = StubScopeService()
    service = _service(db, scope_service)
    created = service.create(
        _detail_configuration(),
        actor="operator@example.com",
        initial_state="active",
    )
    automation_id = created.snapshot.automation_id

    paused = service.pause(
        automation_id,
        expected_revision=1,
        actor="operator@example.com",
    )
    assert (paused.snapshot.lifecycle_state, paused.snapshot.revision) == (
        "paused",
        2,
    )
    resumed = service.resume(
        automation_id,
        expected_revision=2,
        actor="operator@example.com",
    )
    assert (resumed.snapshot.lifecycle_state, resumed.snapshot.revision) == (
        "active",
        3,
    )
    review_required = service.mark_scope_review_required(
        automation_id,
        expected_revision=3,
        reason=CrawlScopeErrorPayloadV1(
            code="SCOPE_REVIEW_REQUIRED",
            message="Published catalog query semantics changed",
        ),
        actor="catalog-governance",
    )
    assert review_required.snapshot.lifecycle_state == "scope_review_required"
    assert db.get(ScrapeSchedule, automation_id).is_active is False

    paused_review = service.pause(
        automation_id,
        expected_revision=4,
        actor="operator@example.com",
    )
    assert paused_review.snapshot.scope_review_reason is not None
    scope_service.reject = True
    with pytest.raises(ScopeReviewRequiredError):
        service.resume(
            automation_id,
            expected_revision=5,
            actor="operator@example.com",
        )
    db.rollback()

    scope_service.reject = False
    updated = service.update_configuration(
        automation_id,
        expected_revision=5,
        configuration=_detail_configuration(),
        actor="operator@example.com",
    )
    assert updated.snapshot.scope_review_reason is None
    archived = service.archive(
        automation_id,
        expected_revision=6,
        actor="operator@example.com",
    )
    assert archived.snapshot.archived_at is not None
    with pytest.raises(AutomationTransitionInvalidError):
        service.pause(
            automation_id,
            expected_revision=7,
            actor="operator@example.com",
        )
    db.rollback()
    restored = service.restore(
        automation_id,
        expected_revision=7,
        actor="operator@example.com",
    )
    assert (restored.snapshot.lifecycle_state, restored.snapshot.revision) == (
        "paused",
        8,
    )


def test_phase_and_detail_limit_changes_clear_legacy_compatibility_values(
    automation_db,
):
    _engine, _factory, db = automation_db
    service = _service(db)
    created = service.create(
        _listing_configuration(page_depth=9),
        actor="operator@example.com",
    )
    automation_id = created.snapshot.automation_id
    detail = service.update_configuration(
        automation_id,
        expected_revision=1,
        configuration=_detail_configuration(),
        actor="operator@example.com",
    )
    row = db.get(ScrapeSchedule, automation_id)
    assert detail.snapshot.configuration.crawl_phase == "detail"
    assert row.max_pages == 1
    assert row.detail_limit == 50

    service.update_configuration(
        automation_id,
        expected_revision=2,
        configuration=_detail_configuration(entire_snapshot=True),
        actor="operator@example.com",
    )
    assert row.detail_run_cap is None
    assert row.detail_limit_kind == "entire_snapshot"
    assert row.detail_limit == 1

    service.update_configuration(
        automation_id,
        expected_revision=3,
        configuration=_listing_configuration(page_depth=4),
        actor="operator@example.com",
    )
    assert row.max_pages == 4
    assert row.detail_limit == 100
    assert row.detail_limit_kind is None


def test_permanent_delete_requires_fresh_impact_and_preserves_run_history(
    automation_db,
):
    _engine, _factory, db = automation_db
    service = _service(db)
    created = service.create(
        _listing_configuration(),
        actor="operator@example.com",
    )
    automation_id = created.snapshot.automation_id
    snapshot_payload = created.snapshot.model_dump(mode="json")
    crawl_job = CrawlJob(
        source_site="offertoday",
        trigger_type="schedule",
        schedule_id=automation_id,
        status="completed",
        request_payload={"compatibility": True},
    )
    db.add(crawl_job)
    db.flush()
    execution = ScheduleExecution(
        schedule_id=automation_id,
        crawl_job_id=crawl_job.id,
        automation_id_snapshot=automation_id,
        automation_revision=1,
        automation_snapshot=snapshot_payload,
        status="completed",
    )
    db.add(execution)
    db.flush()
    execution_id = execution.id
    crawl_job_id = crawl_job.id
    db.commit()

    archived = service.archive(
        automation_id,
        expected_revision=1,
        actor="operator@example.com",
    )
    expired = service.review_permanent_delete(
        automation_id,
        actor="operator@example.com",
        ttl=timedelta(seconds=-1),
    )
    with pytest.raises(AutomationDeleteReviewStaleError):
        service.permanently_delete(
            automation_id,
            expected_revision=archived.snapshot.revision,
            actor="operator@example.com",
            review_token=expired.review_token,
        )
    db.rollback()

    review = service.review_permanent_delete(
        automation_id,
        actor="operator@example.com",
    )
    assert review.impact.schedule_execution_count == 1
    assert review.impact.crawl_job_count == 1
    impact = service.permanently_delete(
        automation_id,
        expected_revision=archived.snapshot.revision,
        actor="operator@example.com",
        review_token=review.review_token,
    )

    assert impact.preserved_records == (
        "schedule_executions",
        "crawl_jobs",
        "run_history",
    )
    assert db.get(ScrapeSchedule, automation_id) is None
    assert (
        db.query(AutomationRevision)
        .filter(AutomationRevision.automation_id == automation_id)
        .count()
        == 0
    )
    preserved_execution = db.get(ScheduleExecution, execution_id)
    preserved_job_schedule_id = db.execute(
        select(CrawlJob.schedule_id).where(CrawlJob.id == crawl_job_id)
    ).scalar_one()
    assert preserved_execution.schedule_id is None
    assert preserved_execution.automation_id_snapshot == automation_id
    assert preserved_execution.automation_snapshot == snapshot_payload
    assert preserved_job_schedule_id is None
    assert (
        db.query(AutomationDeleteReview)
        .filter(AutomationDeleteReview.automation_id_snapshot == automation_id)
        .count()
        == 2
    )


def test_legacy_repository_cannot_mutate_versioned_automation(automation_db):
    _engine, _factory, db = automation_db
    service = _service(db)
    automation = service.create(
        _listing_configuration(),
        actor="operator@example.com",
    )
    automation_id = automation.snapshot.automation_id
    repository = ScheduleRepository()

    with pytest.raises(RuntimeError, match="AutomationService"):
        repository.update_schedule(db, automation_id, {"name": "legacy write"})
    with pytest.raises(RuntimeError, match="lifecycle transitions"):
        repository.toggle_schedule(db, automation_id)
    db.rollback()
    with pytest.raises(RuntimeError, match="reviewed permanent deletion"):
        repository.delete_schedule(db, automation_id)
    db.rollback()
    row = db.get(ScrapeSchedule, automation_id)
    with pytest.raises(RuntimeError, match="immutable Dispatch Plan"):
        CrawlJobDispatchService().dispatch_schedule_crawl_job(
            db,
            schedule=row,
        )


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs = {}
        self.last_args = None

    def add_job(self, _func, *, trigger, id, args, replace_existing):
        self.last_args = list(args)
        job = SimpleNamespace(
            id=id,
            trigger=trigger,
            next_run_time=datetime(2026, 7, 21, 4, 0, tzinfo=UTC),
        )
        self.jobs[id] = job
        return job

    def get_job(self, job_id):
        return self.jobs.get(str(job_id))

    def get_jobs(self):
        return list(self.jobs.values())

    def remove_job(self, job_id):
        self.jobs.pop(str(job_id), None)


class FakeDispatchService:
    def __init__(self) -> None:
        self.calls = []

    def dispatch_schedule_crawl_job(self, db, **kwargs):
        self.calls.append((db, kwargs))
        return SimpleNamespace(crawl_job=SimpleNamespace(id=uuid4()))


def test_scheduler_registration_and_callback_are_revision_and_lifecycle_fenced(
    automation_db,
    monkeypatch,
):
    _engine, factory, db = automation_db
    service = _service(db)
    created = service.create(
        _listing_configuration(),
        actor="operator@example.com",
        initial_state="active",
    )
    automation_id = created.snapshot.automation_id
    row = db.get(ScrapeSchedule, automation_id)

    scheduler_service = SchedulerService(owner="test")
    scheduler_service.scheduler = FakeScheduler()
    scheduler_service.dispatch_service = FakeDispatchService()
    assert scheduler_service._add_job(row, db=db) is True
    assert scheduler_service.scheduler.last_args == [str(automation_id), 1]
    assert str(scheduler_service.scheduler.jobs[str(automation_id)].trigger.timezone) == (
        "America/New_York"
    )
    assert row.next_run_at.tzinfo is not None

    import app.services.scheduler_service as scheduler_module

    monkeypatch.setattr(scheduler_module, "SessionLocal", factory)
    stale = asyncio.run(
        scheduler_service._dispatch_schedule(
            automation_id,
            registered_revision=0,
            trigger_type="schedule",
        )
    )
    assert stale is None
    assert scheduler_service.dispatch_service.calls == []

    dispatched = asyncio.run(
        scheduler_service._dispatch_schedule(
            automation_id,
            registered_revision=1,
            trigger_type="schedule",
        )
    )
    assert dispatched is not None
    assert len(scheduler_service.dispatch_service.calls) == 1

    service.pause(
        automation_id,
        expected_revision=1,
        actor="operator@example.com",
    )
    paused_callback = asyncio.run(
        scheduler_service._dispatch_schedule(
            automation_id,
            registered_revision=1,
            trigger_type="schedule",
        )
    )
    assert paused_callback is None
    assert len(scheduler_service.dispatch_service.calls) == 1
    manual = asyncio.run(
        scheduler_service._dispatch_schedule(
            automation_id,
            trigger_type="manual",
        )
    )
    assert manual is not None
    assert len(scheduler_service.dispatch_service.calls) == 2


def test_automation_migration_is_schema_only_and_preserves_execution_fk(
    monkeypatch,
):
    created_tables: list[str] = []
    dropped_tables: list[str] = []
    added_columns: list[tuple[str, str]] = []
    executed_sql: list[str] = []
    foreign_keys: list[tuple[str, str | None]] = []

    alembic_stub = ModuleType("alembic")
    alembic_stub.op = SimpleNamespace(
        add_column=lambda table, column: added_columns.append((table, column.name)),
        alter_column=lambda *_args, **_kwargs: None,
        create_check_constraint=lambda *_args, **_kwargs: None,
        create_foreign_key=lambda name, *_args, **kwargs: foreign_keys.append(
            (name, kwargs.get("ondelete"))
        ),
        create_index=lambda *_args, **_kwargs: None,
        create_table=lambda name, *_columns, **_kwargs: created_tables.append(name),
        drop_column=lambda *_args, **_kwargs: None,
        drop_constraint=lambda *_args, **_kwargs: None,
        drop_index=lambda *_args, **_kwargs: None,
        drop_table=lambda name: dropped_tables.append(name),
        execute=lambda statement: executed_sql.append(str(statement)),
    )
    monkeypatch.setitem(sys.modules, "alembic", alembic_stub)

    migration = runpy.run_path(
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "20260720_120000_add_versioned_automation_lifecycle.py"
    )
    migration["upgrade"]()
    migration["downgrade"]()

    assert migration["down_revision"] == "20260719_160000"
    assert created_tables == [
        "automation_revisions",
        "automation_delete_reviews",
    ]
    assert dropped_tables == list(reversed(created_tables))
    assert ("schedule_executions", "automation_snapshot") in added_columns
    assert (
        "fk_schedule_executions_schedule_id_scrape_schedules",
        "SET NULL",
    ) in foreign_keys
    assert not any("INSERT" in statement.upper() for statement in executed_sql)
    assert any(
        "TRG_AUTOMATION_REVISIONS_IMMUTABLE" in statement.upper()
        for statement in executed_sql
    )
    assert any(
        "TIMESTAMP WITH TIME ZONE" in statement.upper()
        for statement in executed_sql
    )
    assert any(
        "RESTORE THE PRE-CUTOVER DATABASE BACKUP" in statement.upper()
        for statement in executed_sql
    )


def test_automation_orm_metadata_registers_parity_columns_and_set_null_history():
    assert {
        "automation_revisions",
        "automation_delete_reviews",
        "scrape_schedules",
        "schedule_executions",
    } <= set(Base.metadata.tables)
    schedule_columns = set(ScrapeSchedule.__table__.columns.keys())
    assert {
        "revision",
        "lifecycle_state",
        "scope_contract",
        "listing_page_depth",
        "listing_run_page_cap",
        "detail_run_cap",
        "detail_limit_kind",
        "detail_backlog_scope",
        "scope_review_reason",
        "archived_at",
    } <= schedule_columns
    schedule_fk = next(iter(ScheduleExecution.__table__.c.schedule_id.foreign_keys))
    assert ScheduleExecution.__table__.c.schedule_id.nullable is True
    assert schedule_fk.ondelete == "SET NULL"
    for column in (
        ScrapeSchedule.__table__.c.created_at,
        ScrapeSchedule.__table__.c.updated_at,
        ScrapeSchedule.__table__.c.last_run_at,
        ScrapeSchedule.__table__.c.next_run_at,
        ScheduleExecution.__table__.c.started_at,
        ScheduleExecution.__table__.c.completed_at,
        ScheduleExecution.__table__.c.created_at,
    ):
        assert column.type.timezone is True
