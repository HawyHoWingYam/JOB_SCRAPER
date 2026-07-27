from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.crawl_control.automation_contracts import AutomationConfigurationV1
from app.crawl_control.automation_service import AutomationService
from app.crawl_control.contracts import (
    AuthoredCrawlScopeV1,
    DetailSettingsV1,
    ListingSettingsV1,
)
from app.crawl_control.errors import AutomationDeleteReviewStaleError
from app.models.crawl_dispatch_plan import CRAWL_DISPATCH_PLAN_TABLES
from app.models.crawl_job import CrawlJob
from app.models.crawl_job_listing import CrawlJobListing
from app.models.schedule import (
    AUTOMATION_CONTROL_TABLES,
    AutomationDeleteReview,
    ScheduleExecution,
    ScrapeSchedule,
)


@compiles(UUID, "sqlite")
def compile_uuid_for_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(32)"


class StubScopeService:
    def preview(self, scope, *, listing_settings=None):
        return SimpleNamespace(
            resolved_scope=scope,
            listing_workload=None,
        )


@pytest.fixture
def automation_db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    tables = (
        AUTOMATION_CONTROL_TABLES[0],
        CrawlJob.__table__,
        CrawlJobListing.__table__,
        *CRAWL_DISPATCH_PLAN_TABLES,
        *AUTOMATION_CONTROL_TABLES[1:],
    )
    ScrapeSchedule.metadata.create_all(engine, tables=tables)
    db = sessionmaker(bind=engine)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _scope() -> AuthoredCrawlScopeV1:
    return AuthoredCrawlScopeV1(source_site="offertoday", mode="all")


def _listing_configuration(
    *,
    name: str = "OfferToday listing",
    page_depth: int = 2,
) -> AutomationConfigurationV1:
    return AutomationConfigurationV1(
        name=name,
        description="Current listing Automation",
        cron_expression="30 2 * * *",
        timezone="Asia/Hong_Kong",
        scope=_scope(),
        listing_settings=ListingSettingsV1(
            crawl_mode="headless",
            page_depth=page_depth,
            run_page_cap=100,
        ),
    )


def _detail_configuration(*, entire_snapshot: bool = False):
    return AutomationConfigurationV1(
        name="OfferToday detail",
        cron_expression="0 4 * * *",
        timezone="Asia/Hong_Kong",
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


def _service(db) -> AutomationService:
    return AutomationService(db, scope_service=StubScopeService())


def test_automation_contract_requires_one_phase_and_valid_timezone():
    assert _listing_configuration().crawl_phase == "listing"
    assert _detail_configuration().crawl_phase == "detail"
    with pytest.raises(ValidationError, match="Invalid timezone identifier"):
        AutomationConfigurationV1(
            name="Invalid",
            cron_expression="0 1 * * *",
            timezone="Hong Kong local",
            scope=_scope(),
            listing_settings=ListingSettingsV1(
                crawl_mode="headless",
                page_depth=1,
                run_page_cap=10,
            ),
        )
    with pytest.raises(ValidationError, match="exactly one"):
        AutomationConfigurationV1(
            name="Invalid",
            cron_expression="0 1 * * *",
            timezone="UTC",
            scope=_scope(),
        )


def test_two_stale_forms_save_in_order_and_later_submission_wins(automation_db):
    service = _service(automation_db)
    created = service.create(
        _listing_configuration(name="Original"),
        actor="operator@example.com",
    )
    automation_id = created.snapshot.automation_id

    first_form = _listing_configuration(name="First form", page_depth=3)
    second_form = _listing_configuration(name="Second form", page_depth=7)
    service.update_configuration(
        automation_id,
        configuration=first_form,
        actor="operator@example.com",
    )
    final = service.update_configuration(
        automation_id,
        configuration=second_form,
        actor="operator@example.com",
    )

    row = automation_db.get(ScrapeSchedule, automation_id)
    assert row.name == "Second form"
    assert row.listing_page_depth == 7
    assert final.snapshot.configuration == second_form
    assert "revision" not in final.model_dump(mode="json")
    assert "version" not in final.model_dump(mode="json")
    assert "automation_revisions" not in ScrapeSchedule.metadata.tables


def test_current_row_lifecycle_and_phase_changes(automation_db):
    service = _service(automation_db)
    created = service.create(
        _listing_configuration(page_depth=9),
        actor="operator@example.com",
        initial_state="active",
    )
    automation_id = created.snapshot.automation_id

    paused = service.pause(automation_id, actor="operator@example.com")
    assert paused.snapshot.lifecycle_state == "paused"
    service.resume(automation_id, actor="operator@example.com")
    detail = service.update_configuration(
        automation_id,
        configuration=_detail_configuration(),
        actor="operator@example.com",
    )
    row = automation_db.get(ScrapeSchedule, automation_id)
    assert detail.snapshot.configuration.crawl_phase == "detail"
    assert row.max_pages == 1
    assert row.detail_limit == 50

    service.update_configuration(
        automation_id,
        configuration=_detail_configuration(entire_snapshot=True),
        actor="operator@example.com",
    )
    assert row.detail_run_cap is None
    assert row.detail_limit_kind == "entire_snapshot"

    archived = service.archive(automation_id, actor="operator@example.com")
    assert archived.snapshot.lifecycle_state == "archived"


def test_permanent_delete_review_preserves_run_history(automation_db):
    service = _service(automation_db)
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
        request_payload={"current": True},
    )
    automation_db.add(crawl_job)
    automation_db.flush()
    execution = ScheduleExecution(
        schedule_id=automation_id,
        crawl_job_id=crawl_job.id,
        automation_id_snapshot=automation_id,
        automation_snapshot=snapshot_payload,
        status="completed",
    )
    automation_db.add(execution)
    automation_db.flush()
    execution_id = execution.id
    crawl_job_id = crawl_job.id
    automation_db.commit()

    service.archive(automation_id, actor="operator@example.com")
    expired = service.review_permanent_delete(
        automation_id,
        actor="operator@example.com",
        ttl=timedelta(seconds=-1),
    )
    with pytest.raises(AutomationDeleteReviewStaleError):
        service.permanently_delete(
            automation_id,
            actor="operator@example.com",
            review_token=expired.review_token,
        )
    automation_db.rollback()

    review = service.review_permanent_delete(
        automation_id,
        actor="operator@example.com",
    )
    assert review.impact.removed_records == ("automation",)
    impact = service.permanently_delete(
        automation_id,
        actor="operator@example.com",
        review_token=review.review_token,
    )

    assert impact.preserved_records == (
        "schedule_executions",
        "crawl_jobs",
        "run_history",
    )
    assert automation_db.get(ScrapeSchedule, automation_id) is None
    preserved_execution = automation_db.get(ScheduleExecution, execution_id)
    preserved_job_schedule_id = automation_db.execute(
        select(CrawlJob.schedule_id).where(CrawlJob.id == crawl_job_id)
    ).scalar_one()
    assert preserved_execution.schedule_id is None
    assert preserved_execution.automation_id_snapshot == automation_id
    assert preserved_execution.automation_snapshot == snapshot_payload
    assert preserved_job_schedule_id is None
    assert (
        automation_db.query(AutomationDeleteReview)
        .filter(AutomationDeleteReview.automation_id_snapshot == automation_id)
        .count()
        == 2
    )


def test_automation_orm_has_only_current_state_and_set_null_history():
    assert "automation_revisions" not in ScrapeSchedule.metadata.tables
    assert "revision" not in ScrapeSchedule.__table__.columns
    assert "automation_revision" not in ScheduleExecution.__table__.columns
    assert "expected_revision" not in AutomationDeleteReview.__table__.columns
    schedule_fk = next(iter(ScheduleExecution.__table__.c.schedule_id.foreign_keys))
    assert ScheduleExecution.__table__.c.schedule_id.nullable is True
    assert schedule_fk.ondelete == "SET NULL"
