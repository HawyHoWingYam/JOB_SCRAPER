from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import crawl_control as crawl_control_api
from app.api import crawl_jobs as crawl_jobs_api
from app.api import schedules as schedules_api
from app.api import router as production_api_router
from app.crawl_control.task_control_board_contracts import (
    RunAuthorityProjectionV1,
)
from app.database import get_db
from app.models.crawl_dispatch_plan import CRAWL_DISPATCH_PLAN_TABLES
from app.models.crawl_job import CrawlJob, CrawlJobEvent
from app.models.crawl_job_execution import CrawlJobExecution
from app.models.crawl_job_listing import CrawlJobListing
from app.models.crawl_run import CrawlRun
from app.models.event_outbox import EventOutbox
from app.models.schedule import (
    AutomationDeleteReview,
    AutomationRevision,
    ScheduleExecution,
    ScrapeSchedule,
)
from app.models.scraper_pacing_settings import ScraperPacingSettings
from app.models.source_catalog import SOURCE_CATALOG_TABLES, SourceCatalogCandidate
from app.repositories.source_catalog_repository import SourceCatalogRepository
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.services.crawl_job_dispatch_service import CrawlJobDispatchService
from app.services.crawl_job_execution_launcher import CrawlJobLaunchResult
from app.source_catalog.adapters.jobsdb import JobsDBSourceCatalogAdapter


@compiles(PostgreSQLUUID, "sqlite")
def compile_uuid_for_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(32)"


class _NoopLauncher:
    def should_launch_locally(self, _crawl_job):
        return True

    def launch(self, _crawl_job):
        return CrawlJobLaunchResult(launched=False, command=None)


class _NoopOutboxPublisher:
    def publish_row(self, _db, *, row):
        return row

    def publish_pending_batch(self, _db, *, limit):
        assert limit == 100
        return []


def test_crawl_control_contracts_are_registered_in_production_openapi():
    app = FastAPI()
    app.include_router(production_api_router)

    paths = app.openapi()["paths"]

    expected_operations = {
        "/api/v1/crawl-scopes/preview": {"post"},
        "/api/v1/automations": {"get", "post"},
        "/api/v1/automations/reviews": {"post"},
        "/api/v1/automations/{automation_id}": {"get", "put", "delete"},
        "/api/v1/automations/{automation_id}/pause": {"post"},
        "/api/v1/automations/{automation_id}/resume": {"post"},
        "/api/v1/automations/{automation_id}/archive": {"post"},
        "/api/v1/automations/{automation_id}/restore": {"post"},
        "/api/v1/automations/{automation_id}/delete-reviews": {"post"},
        "/api/v1/dispatch-plans": {"post"},
        "/api/v1/dispatch-plans/{plan_id}": {"get"},
        "/api/v1/dispatch-plans/{plan_id}/dispatch": {"post"},
        "/api/v1/task-control-board": {"get"},
        "/api/v1/crawl-jobs/tasks": {"get"},
    }
    for path, methods in expected_operations.items():
        assert methods <= set(paths[path])
    board_schema = paths["/api/v1/task-control-board"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert {variant["$ref"] for variant in board_schema["anyOf"]} == {
        "#/components/schemas/TaskControlBoardProjectionV1",
        "#/components/schemas/TaskControlBoardProjectionV2",
    }
    assert paths["/api/v1/dispatch-plans/{plan_id}/dispatch"]["post"][
        "responses"
    ]["202"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/DispatchPlanDispatchResponseV1"
    )


def test_legacy_run_authority_cannot_claim_versioned_automation_fields():
    with pytest.raises(ValueError, match="Legacy authority"):
        RunAuthorityProjectionV1(
            authority_kind="legacy",
            automation_id=uuid4(),
            automation_revision=1,
        )


@pytest.fixture
def crawl_control_client(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SourceCatalogCandidate.metadata.create_all(
        engine,
        tables=(
            *SOURCE_CATALOG_TABLES,
            ScrapeSchedule.__table__,
            AutomationRevision.__table__,
            CrawlJob.__table__,
            CrawlJobEvent.__table__,
            CrawlJobExecution.__table__,
            CrawlRun.__table__,
            CrawlJobListing.__table__,
            *CRAWL_DISPATCH_PLAN_TABLES,
            ScheduleExecution.__table__,
            AutomationDeleteReview.__table__,
            EventOutbox.__table__,
            ScraperPacingSettings.__table__,
        ),
    )
    session_factory = sessionmaker(bind=engine)
    db = session_factory()
    repository = SourceCatalogRepository()
    catalog = JobsDBSourceCatalogAdapter().discover()
    candidate, _created = repository.create_or_get_candidate(
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
        published_by="local-operator",
    )
    repository.set_active_revision(
        db,
        source_site="jobsdb",
        revision_id=revision.id,
        expected_revision_id=None,
        updated_by="local-operator",
    )
    db.add(
        ScraperPacingSettings(
            source_site="jobsdb",
            interval_min_seconds=1,
            interval_max_seconds=3,
            burst_size=20,
            burst_pause_seconds=30,
        )
    )
    db.commit()
    revision_id = revision.id
    db.close()

    app = FastAPI()
    app.state.session_factory = session_factory
    app.include_router(crawl_control_api.router, prefix="/api/v1")
    app.include_router(crawl_jobs_api.router, prefix="/api/v1")
    app.include_router(schedules_api.router, prefix="/api/v1")
    monkeypatch.setattr(
        crawl_control_api,
        "crawl_job_dispatch_service",
        CrawlJobDispatchService(
            execution_launcher=_NoopLauncher(),
            outbox_publisher=_NoopOutboxPublisher(),
        ),
        raising=False,
    )
    monkeypatch.setattr(
        schedules_api,
        "crawl_job_dispatch_service",
        CrawlJobDispatchService(
            execution_launcher=_NoopLauncher(),
            outbox_publisher=_NoopOutboxPublisher(),
        ),
        raising=False,
    )

    def override_get_db():
        request_db = session_factory()
        try:
            yield request_db
        finally:
            request_db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, revision_id
    engine.dispose()


def _review_automation_configuration(
    client: TestClient,
    configuration: dict,
    *,
    automation_id: str | None = None,
    expected_revision: int | None = None,
) -> dict:
    response = client.post(
        "/api/v1/automations/reviews",
        json={
            "configuration": configuration,
            **(
                {
                    "automation_id": automation_id,
                    "expected_revision": expected_revision,
                }
                if automation_id is not None
                else {}
            ),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_scope_preview_returns_normalized_workload_and_stable_revision_error(
    crawl_control_client,
):
    client, revision_id = crawl_control_client
    request = {
        "scope": {
            "version": 1,
            "source_site": "jobsdb",
            "reviewed_catalog_revision_id": str(revision_id),
            "mode": "all",
            "rules": [],
        },
        "listing_settings": {
            "version": 1,
            "crawl_mode": "headless",
            "page_depth": 2,
            "run_page_cap": 100,
        },
    }

    response = client.post("/api/v1/crawl-scopes/preview", json=request)

    assert response.status_code == 200
    payload = response.json()
    assert payload["resolved_scope"]["catalog_revision_id"] == str(revision_id)
    assert payload["resolved_scope"]["query_target_count"] == 25
    assert payload["listing_workload"] == {
        "version": 1,
        "query_target_count": 25,
        "page_depth": 2,
        "estimated_max_pages": 50,
        "run_page_cap": 100,
        "system_run_page_cap": 1000,
        "within_operator_cap": True,
        "within_system_cap": True,
    }

    request["scope"]["reviewed_catalog_revision_id"] = str(uuid4())
    stale = client.post("/api/v1/crawl-scopes/preview", json=request)

    assert stale.status_code == 409
    assert stale.json()["detail"] == {
        "code": "SCOPE_REVIEW_REQUIRED",
        "message": "The reviewed Source Catalog revision is no longer active",
        "context": {
            "reviewed_catalog_revision_id": request["scope"][
                "reviewed_catalog_revision_id"
            ],
            "current_catalog_revision_id": str(revision_id),
        },
    }


def test_legacy_schedule_create_writes_a_versioned_automation(
    crawl_control_client,
):
    client, revision_id = crawl_control_client

    response = client.post(
        "/api/v1/schedules",
        json={
            "name": "Legacy-compatible listing",
            "description": "Created through the temporary route",
            "cron_expression": "0 4 * * *",
            "timezone": "Asia/Hong_Kong",
            "source_site": "jobsdb",
            "crawl_phase": "listing",
            "crawl_mode": "headless",
            "category_ids": [6281],
            "max_pages": 2,
            "is_active": True,
        },
    )

    assert response.status_code == 200
    schedule = response.json()
    assert schedule["category_ids"] is None
    assert schedule["revision"] == 1
    assert schedule["lifecycle_state"] == "active"
    assert schedule["scope_contract"] == {
        "version": 1,
        "source_site": "jobsdb",
        "reviewed_catalog_revision_id": str(revision_id),
        "mode": "rules",
        "rules": [
            {"kind": "exact", "classification_id": "jobsdb:6281"}
        ],
    }
    assert schedule["listing_page_depth"] == 2
    assert schedule["listing_run_page_cap"] == 2

    automation = client.get(
        f"/api/v1/automations/{schedule['id']}"
    ).json()
    assert automation["snapshot"]["configuration"]["scope"] == (
        schedule["scope_contract"]
    )


def test_legacy_schedule_mutations_delegate_for_versioned_rows(
    crawl_control_client,
):
    client, _revision_id = crawl_control_client
    created = client.post(
        "/api/v1/schedules",
        json={
            "name": "Temporary route delegation",
            "cron_expression": "0 4 * * *",
            "source_site": "jobsdb",
            "crawl_phase": "listing",
            "crawl_mode": "headless",
            "category_ids": [6281],
            "max_pages": 2,
            "is_active": True,
        },
    ).json()
    schedule_id = created["id"]

    updated = client.put(
        f"/api/v1/schedules/{schedule_id}",
        json={
            "description": "Updated without primitive scope writes",
            "max_pages": 3,
        },
    )

    assert updated.status_code == 200
    updated_schedule = updated.json()
    assert updated_schedule["revision"] == 2
    assert updated_schedule["description"] == (
        "Updated without primitive scope writes"
    )
    assert updated_schedule["category_ids"] is None
    assert updated_schedule["listing_page_depth"] == 3
    assert updated_schedule["listing_run_page_cap"] == 3

    combined = client.put(
        f"/api/v1/schedules/{schedule_id}",
        json={
            "description": "Must not partially persist",
            "is_active": False,
        },
    )

    assert combined.status_code == 422
    assert combined.json()["detail"]["code"] == (
        "AUTOMATION_COMPATIBILITY_MUTATION_SPLIT_REQUIRED"
    )
    after_rejection = client.get(f"/api/v1/schedules/{schedule_id}").json()
    assert after_rejection["revision"] == 2
    assert after_rejection["description"] == (
        "Updated without primitive scope writes"
    )
    assert after_rejection["is_active"] is True

    run_now = client.post(f"/api/v1/schedules/{schedule_id}/run")

    assert run_now.status_code == 409
    assert run_now.json()["detail"]["code"] == (
        "DISPATCH_PLAN_REVIEW_REQUIRED"
    )

    toggled = client.post(f"/api/v1/schedules/{schedule_id}/toggle")

    assert toggled.status_code == 200
    assert toggled.json()["is_active"] is False
    after_toggle = client.get(f"/api/v1/schedules/{schedule_id}").json()
    assert after_toggle["revision"] == 3
    assert after_toggle["lifecycle_state"] == "paused"

    deleted = client.delete(f"/api/v1/schedules/{schedule_id}")

    assert deleted.status_code == 200
    assert deleted.json() == {"message": "Schedule deleted"}
    archived = client.get(f"/api/v1/schedules/{schedule_id}").json()
    assert archived["revision"] == 4
    assert archived["lifecycle_state"] == "archived"
    assert archived["is_active"] is False


def test_legacy_schedule_create_returns_stable_source_errors(
    crawl_control_client,
):
    client, _revision_id = crawl_control_client
    base_request = {
        "name": "Invalid source",
        "cron_expression": "0 4 * * *",
        "crawl_phase": "listing",
        "crawl_mode": "headless",
        "category_ids": None,
        "max_pages": 1,
    }

    unsupported = client.post(
        "/api/v1/schedules",
        json={**base_request, "source_site": "unknown-source"},
    )

    assert unsupported.status_code == 422
    assert unsupported.json()["detail"] == {
        "code": "SOURCE_SITE_UNSUPPORTED",
        "message": "Unsupported Crawl Control source_site",
        "context": {"source_site": "unknown-source"},
    }

    unpublished = client.post(
        "/api/v1/schedules",
        json={**base_request, "source_site": "offertoday"},
    )

    assert unpublished.status_code == 404
    assert unpublished.json()["detail"]["code"] == "CATALOG_NOT_PUBLISHED"


def test_pre_cutover_schedule_rows_keep_bounded_legacy_mutations(
    crawl_control_client,
):
    client, _revision_id = crawl_control_client
    request_db = client.app.state.session_factory()
    try:
        legacy = ScrapeSchedule(
            name="Pre-cutover row",
            description=None,
            cron_expression="0 3 * * *",
            timezone="Asia/Hong_Kong",
            source_site="jobsdb",
            crawl_phase="listing",
            crawl_mode="headless",
            category_ids=[6281],
            max_pages=2,
            detail_limit=100,
            revision=1,
            lifecycle_state="active",
            scope_contract=None,
            is_active=True,
        )
        request_db.add(legacy)
        request_db.commit()
        schedule_id = str(legacy.id)
    finally:
        request_db.close()

    updated = client.put(
        f"/api/v1/schedules/{schedule_id}",
        json={"name": "Still bounded legacy", "max_pages": 3},
    )

    assert updated.status_code == 200
    assert updated.json()["scope_contract"] is None
    assert updated.json()["category_ids"] == [6281]
    assert updated.json()["max_pages"] == 3
    assert updated.json()["revision"] == 2

    toggled = client.post(f"/api/v1/schedules/{schedule_id}/toggle")

    assert toggled.status_code == 200
    assert toggled.json()["is_active"] is False

    deleted = client.delete(f"/api/v1/schedules/{schedule_id}")

    assert deleted.status_code == 200
    assert client.get(f"/api/v1/schedules/{schedule_id}").status_code == 404


def test_automation_lifecycle_and_reviewed_permanent_delete_are_revisioned(
    crawl_control_client,
):
    client, revision_id = crawl_control_client
    configuration = {
        "version": 1,
        "name": "Lifecycle fixture",
        "description": None,
        "cron_expression": "0 4 * * *",
        "timezone": "UTC",
        "scope": {
            "version": 1,
            "source_site": "jobsdb",
            "reviewed_catalog_revision_id": str(revision_id),
            "mode": "all",
            "rules": [],
        },
        "listing_settings": {
            "version": 1,
            "crawl_mode": "headless",
            "page_depth": 1,
            "run_page_cap": 25,
        },
        "detail_settings": None,
    }
    automation_review = _review_automation_configuration(client, configuration)
    created_response = client.post(
        "/api/v1/automations",
        json={
            "configuration": configuration,
            "review_fingerprint": automation_review["input_fingerprint"],
            "initial_state": "active",
        },
    )
    assert created_response.status_code == 201
    created = created_response.json()
    automation_id = created["snapshot"]["automation_id"]

    paused = client.post(
        f"/api/v1/automations/{automation_id}/pause",
        json={"expected_revision": 1},
    )
    assert paused.status_code == 200
    assert paused.headers["etag"] == '"2"'
    assert paused.json()["snapshot"]["lifecycle_state"] == "paused"

    stale_resume = client.post(
        f"/api/v1/automations/{automation_id}/resume",
        json={"expected_revision": 1},
    )
    assert stale_resume.status_code == 409
    assert stale_resume.json()["detail"]["context"]["current_revision"] == 2

    resumed = client.post(
        f"/api/v1/automations/{automation_id}/resume",
        json={"expected_revision": 2},
    )
    assert resumed.status_code == 200
    assert resumed.json()["snapshot"]["revision"] == 3
    assert resumed.json()["snapshot"]["lifecycle_state"] == "active"

    archived = client.post(
        f"/api/v1/automations/{automation_id}/archive",
        json={"expected_revision": 3},
    )
    assert archived.status_code == 200
    assert archived.json()["snapshot"]["revision"] == 4
    assert archived.json()["snapshot"]["lifecycle_state"] == "archived"

    review = client.post(
        f"/api/v1/automations/{automation_id}/delete-reviews"
    )
    assert review.status_code == 200
    review_payload = review.json()
    assert review_payload["impact"]["expected_revision"] == 4
    assert review_payload["impact"]["removed_records"] == [
        "automation",
        "automation_revisions",
    ]
    assert review_payload["impact"]["preserved_records"] == [
        "schedule_executions",
        "crawl_jobs",
        "run_history",
    ]

    deleted = client.request(
        "DELETE",
        f"/api/v1/automations/{automation_id}",
        json={
            "expected_revision": 4,
            "review_token": review_payload["review_token"],
        },
    )
    assert deleted.status_code == 200
    assert deleted.json()["automation_id"] == automation_id
    assert client.get(f"/api/v1/automations/{automation_id}").status_code == 404


def test_dispatch_plan_prepare_and_get_review_without_launching(
    crawl_control_client,
):
    client, revision_id = crawl_control_client
    request = {
        "version": 1,
        "kind": "one_off",
        "scope": {
            "version": 1,
            "source_site": "jobsdb",
            "reviewed_catalog_revision_id": str(revision_id),
            "mode": "all",
            "rules": [],
        },
        "listing_settings": {
            "version": 1,
            "crawl_mode": "headless",
            "page_depth": 1,
            "run_page_cap": 25,
        },
        "detail_settings": None,
    }

    prepared = client.post("/api/v1/dispatch-plans", json=request)

    assert prepared.status_code == 201
    preparation = prepared.json()
    plan_id = preparation["plan"]["plan_id"]
    assert preparation["confirmation_token"]
    assert preparation["plan"]["state"] == "prepared"
    assert preparation["plan"]["readiness"]["status"] == "ready"
    assert preparation["plan"]["content"]["catalog_revision_id"] == str(
        revision_id
    )

    reviewed = client.get(f"/api/v1/dispatch-plans/{plan_id}")
    assert reviewed.status_code == 200
    assert reviewed.json()["plan_id"] == plan_id
    assert reviewed.json()["state"] == "prepared"
    assert "confirmation_token" not in reviewed.json()


def test_dispatch_plan_confirmation_returns_normalized_single_use_run(
    crawl_control_client,
):
    client, revision_id = crawl_control_client
    request = {
        "version": 1,
        "kind": "one_off",
        "scope": {
            "version": 1,
            "source_site": "jobsdb",
            "reviewed_catalog_revision_id": str(revision_id),
            "mode": "all",
            "rules": [],
        },
        "listing_settings": {
            "version": 1,
            "crawl_mode": "headless",
            "page_depth": 1,
            "run_page_cap": 25,
        },
        "detail_settings": None,
    }
    preparation = client.post("/api/v1/dispatch-plans", json=request).json()
    plan = preparation["plan"]
    dispatch_request = {
        "confirmation_token": preparation["confirmation_token"],
        "expected_plan_fingerprint": plan["plan_fingerprint"],
    }

    missing_fingerprint = client.post(
        f"/api/v1/dispatch-plans/{plan['plan_id']}/dispatch",
        json={"confirmation_token": preparation["confirmation_token"]},
    )

    assert missing_fingerprint.status_code == 422
    assert client.get(
        f"/api/v1/dispatch-plans/{plan['plan_id']}"
    ).json()["state"] == "prepared"

    dispatched = client.post(
        f"/api/v1/dispatch-plans/{plan['plan_id']}/dispatch",
        json=dispatch_request,
    )

    assert dispatched.status_code == 202
    payload = dispatched.json()
    assert payload["plan"]["state"] == "consumed"
    assert payload["run"]["status"] == "queued"
    assert payload["run"]["source_site"] == "jobsdb"
    assert payload["run"]["crawl_phase"] == "listing"
    assert payload["run"]["authority"] == {
        "version": 1,
        "authority_kind": "dispatch_plan",
        "dispatch_plan_id": plan["plan_id"],
        "dispatch_plan_fingerprint": plan["plan_fingerprint"],
        "plan_state": "consumed",
        "catalog_revision_id": str(revision_id),
        "automation_id": None,
        "automation_revision": None,
        "authored_scope": plan["content"]["authored_scope"],
        "resolved_scope": plan["content"]["resolved_scope"],
        "readiness": plan["readiness"],
    }
    assert payload["run"]["listing_workload"] == {
        "version": 1,
        "query_target_count": 25,
        "page_depth": 1,
        "estimated_max_pages": 25,
        "run_page_cap": 25,
        "pages_requested": 0,
    }
    assert payload["run"]["detail_snapshot"] is None
    assert "request_payload" not in payload["run"]

    repeated = client.post(
        f"/api/v1/dispatch-plans/{plan['plan_id']}/dispatch",
        json=dispatch_request,
    )
    assert repeated.status_code == 409
    assert repeated.json()["detail"]["code"] == (
        "DISPATCH_PLAN_ALREADY_CONSUMED"
    )


def test_task_control_board_returns_normalized_automation_and_run_rows(
    crawl_control_client,
    monkeypatch,
):
    client, revision_id = crawl_control_client
    configuration = {
        "version": 1,
        "name": "Board Automation",
        "description": None,
        "cron_expression": "0 4 * * *",
        "timezone": "UTC",
        "scope": {
            "version": 1,
            "source_site": "jobsdb",
            "reviewed_catalog_revision_id": str(revision_id),
            "mode": "all",
            "rules": [],
        },
        "listing_settings": {
            "version": 1,
            "crawl_mode": "headless",
            "page_depth": 1,
            "run_page_cap": 25,
        },
        "detail_settings": None,
    }
    automation_review = _review_automation_configuration(client, configuration)
    created = client.post(
        "/api/v1/automations",
        json={
            "configuration": configuration,
            "review_fingerprint": automation_review["input_fingerprint"],
            "initial_state": "paused",
        },
    ).json()
    one_off = {
        "version": 1,
        "kind": "one_off",
        "scope": configuration["scope"],
        "listing_settings": configuration["listing_settings"],
        "detail_settings": None,
    }
    preparation = client.post("/api/v1/dispatch-plans", json=one_off).json()
    dispatched = client.post(
        f"/api/v1/dispatch-plans/{preparation['plan']['plan_id']}/dispatch",
        json={
            "confirmation_token": preparation["confirmation_token"],
            "expected_plan_fingerprint": preparation["plan"][
                "plan_fingerprint"
            ],
        },
    ).json()

    response = client.get("/api/v1/task-control-board?source_site=jobsdb")

    assert response.status_code == 200
    board = response.json()
    assert board["source_site"] == "jobsdb"
    assert board["automation_total"] == 1
    assert board["run_total"] == 1
    assert board["automations"] == [
        {
            "version": 1,
            "automation_id": created["snapshot"]["automation_id"],
            "revision": 1,
            "lifecycle_state": "paused",
            "name": "Board Automation",
            "source_site": "jobsdb",
            "crawl_phase": "listing",
            "crawl_mode": "headless",
            "authored_scope": configuration["scope"],
            "scope_review_reason": None,
            "created_at": created["created_at"],
            "updated_at": created["updated_at"],
            "last_run_at": None,
            "next_run_at": None,
        }
    ]
    assert board["runs"][0]["crawl_job_id"] == dispatched["run"]["crawl_job_id"]
    assert board["runs"][0]["authority"]["authority_kind"] == (
        "dispatch_plan"
    )
    assert board["runs"][0]["listing_workload"]["query_target_count"] == 25
    assert "request_payload" not in board["runs"][0]
    assert "events" not in board["runs"][0]

    board_sources = []
    original_list_page = CrawlJobRepository.list_crawl_task_page

    def record_board_source(self, db, **kwargs):
        board_sources.append(kwargs["source_site"])
        return original_list_page(self, db, **kwargs)

    monkeypatch.setattr(
        CrawlJobRepository,
        "list_crawl_task_page",
        record_board_source,
    )
    v2_response = client.get(
        "/api/v1/task-control-board",
        params={"version": 2, "source_site": "jobsdb"},
    )
    assert v2_response.status_code == 200
    v2 = v2_response.json()
    assert v2["version"] == 2
    assert v2["selected_source"] == "jobsdb"
    assert board_sources == ["jobsdb", "ctgoodjobs", "offertoday"]
    assert [item["source_site"] for item in v2["source_summaries"]] == [
        "jobsdb",
        "ctgoodjobs",
        "offertoday",
    ]
    assert v2["source_summaries"][0]["catalog_health"]["state"] == "healthy"
    assert v2["source_summaries"][1]["catalog_health"]["state"] == "unpublished"
    assert v2["needs_attention"] == []
    assert len(v2["active_runs"]) == 1
    assert v2["active_runs"][0]["run"]["crawl_job_id"] == dispatched["run"]["crawl_job_id"]
    assert v2["active_runs"][0]["actions"][0]["action"] == "view_task"
    assert len(v2["upcoming"]) == 1
    assert v2["upcoming"][0]["schedule"]["timezone"] == "UTC"
    assert v2["upcoming"][0]["catalog_health"]["state"] == "healthy"
    assert v2["upcoming"][0]["actions"][0] == {
        "version": 1,
        "action": "edit",
        "enabled": True,
        "reason_code": None,
    }
    assert v2["all_clear"] is False

    task_response = client.get(
        f"/api/v1/crawl-jobs/tasks/{dispatched['run']['crawl_job_id']}"
    )
    assert task_response.status_code == 200
    task = task_response.json()
    assert task["run"]["authority"]["authority_kind"] == "dispatch_plan"
    assert task["run"]["listing_workload"]["query_target_count"] == 25
    assert task["actions"][0]["action"] == "view_task"
    assert "request_payload" not in task
    assert "manual_action" not in task

    missing_id = uuid4()
    missing_response = client.get(f"/api/v1/crawl-jobs/tasks/{missing_id}")
    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == {
        "code": "CRAWL_TASK_NOT_FOUND",
        "message": "Crawl task not found",
        "context": {"crawl_job_id": str(missing_id)},
    }


def test_control_board_rejects_an_unsupported_source_with_a_stable_error(
    crawl_control_client,
):
    client, _revision_id = crawl_control_client

    response = client.get(
        "/api/v1/task-control-board",
        params={"source_site": "unknown-source"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "SOURCE_SITE_UNSUPPORTED",
        "message": "Unsupported Crawl Control source_site",
        "context": {"source_site": "unknown-source"},
    }


def test_crawl_tasks_use_dispatch_plan_when_raw_payloads_are_absent(
    crawl_control_client,
):
    client, revision_id = crawl_control_client
    one_off = {
        "version": 1,
        "kind": "one_off",
        "scope": {
            "version": 1,
            "source_site": "jobsdb",
            "reviewed_catalog_revision_id": str(revision_id),
            "mode": "all",
            "rules": [],
        },
        "listing_settings": {
            "version": 1,
            "crawl_mode": "headless",
            "page_depth": 2,
            "run_page_cap": 50,
        },
        "detail_settings": None,
    }
    preparation = client.post("/api/v1/dispatch-plans", json=one_off).json()
    dispatched = client.post(
        f"/api/v1/dispatch-plans/{preparation['plan']['plan_id']}/dispatch",
        json={
            "confirmation_token": preparation["confirmation_token"],
            "expected_plan_fingerprint": preparation["plan"][
                "plan_fingerprint"
            ],
        },
    ).json()
    crawl_job_id = dispatched["run"]["crawl_job_id"]

    # Simulate an old compatibility projection whose raw JSON was unavailable.
    # Dispatch Plan columns remain the immutable authority exercised by the API.
    request_db = client.app.state.session_factory()
    try:
        request_db.execute(
            update(CrawlJob)
            .where(CrawlJob.id == UUID(crawl_job_id))
            .values(request_payload={})
        )
        request_db.execute(
            update(CrawlJobEvent)
            .where(CrawlJobEvent.crawl_job_id == UUID(crawl_job_id))
            .values(payload={})
        )
        request_db.commit()
    finally:
        request_db.close()

    response = client.get("/api/v1/crawl-jobs/tasks")

    assert response.status_code == 200
    task = response.json()["items"][0]
    assert task["crawl_job_id"] == crawl_job_id
    assert task["crawl_phase"] == "listing"
    assert task["dispatch_plan_id"] == preparation["plan"]["plan_id"]
    assert task["authority"]["catalog_revision_id"] == str(revision_id)
    assert task["listing_workload"] == {
        "version": 1,
        "query_target_count": 25,
        "page_depth": 2,
        "estimated_max_pages": 50,
        "run_page_cap": 50,
        "pages_requested": 0,
    }


def test_run_projections_normalize_the_latest_recovery_attempt(
    crawl_control_client,
):
    client, _revision_id = crawl_control_client
    request_db = client.app.state.session_factory()
    repository = CrawlJobRepository()
    try:
        crawl_job = repository.create_crawl_job(
            request_db,
            source_site="jobsdb",
            trigger_type="manual",
            status="manual_action_required",
            request_payload={
                "crawl_phase": "detail",
                "crawl_mode": "headless",
                "detail_limit": 10,
            },
            requested_by="operator-1",
            auto_commit=False,
        )
        crawl_job.metrics = {"detail_target_rows": 25}
        repository.append_event(
            request_db,
            crawl_job_id=crawl_job.id,
            event_type="crawl.manual_action_required",
            payload={
                "manual_action": {
                    "classification": "waf_challenge",
                    "message": "Initial challenge",
                    "resume_supported": True,
                }
            },
            emitted_by="jobsdb-crawl",
            auto_commit=False,
        )
        resume_event = repository.append_event(
            request_db,
            crawl_job_id=crawl_job.id,
            event_type="crawl.resume_requested",
            payload={
                "requested_by": "operator-2",
                "strategy": "fresh_profile",
                "manual_action": {"classification": "waf_challenge"},
                "raw_internal_note": "must not escape the event stream",
            },
            emitted_by="operator-2",
            auto_commit=False,
        )
        repository.append_event(
            request_db,
            crawl_job_id=crawl_job.id,
            event_type="crawl.requested",
            payload={"request_payload": {"internal_resume_overlay": True}},
            emitted_by="operator-2",
            auto_commit=False,
        )
        outcome_event = repository.append_event(
            request_db,
            crawl_job_id=crawl_job.id,
            event_type="crawl.manual_action_required",
            payload={
                "error": "The resumed browser was blocked again",
                "manual_action": {
                    "classification": "ip_blocked",
                    "message": "Rotate the network before retrying",
                    "resume_supported": True,
                },
            },
            emitted_by="jobsdb-crawl",
            auto_commit=False,
        )
        repository.append_event(
            request_db,
            crawl_job_id=crawl_job.id,
            event_type="crawl.manual_action_required",
            payload={
                "error": "Later bookkeeping must not replace the outcome",
                "manual_action": {
                    "classification": "content_anomaly",
                    "message": "A later manual-action event",
                    "resume_supported": True,
                },
            },
            emitted_by="jobsdb-crawl",
            auto_commit=False,
        )
        request_db.commit()
        crawl_job_id = str(crawl_job.id)
        resume_sequence = resume_event.sequence_no
        outcome_sequence = outcome_event.sequence_no
    finally:
        request_db.close()

    tasks_response = client.get("/api/v1/crawl-jobs/tasks")

    assert tasks_response.status_code == 200
    task = tasks_response.json()["items"][0]
    assert task["crawl_job_id"] == crawl_job_id
    recovery_attempt = task["recovery_attempt"]
    assert recovery_attempt["version"] == 1
    assert recovery_attempt["request_event_sequence"] == resume_sequence
    assert recovery_attempt["requested_at"]
    assert recovery_attempt["requested_by"] == "operator-2"
    assert recovery_attempt["strategy"] == "fresh_profile"
    assert recovery_attempt["trigger_classification"] == "waf_challenge"
    assert recovery_attempt["outcome"] == "manual_action_required"
    assert recovery_attempt["outcome_event_sequence"] == outcome_sequence
    assert recovery_attempt["outcome_at"]
    assert recovery_attempt["outcome_classification"] == "ip_blocked"
    assert recovery_attempt["outcome_error"] == (
        "The resumed browser was blocked again"
    )
    assert task["detail_snapshot"]["target_count"] == 25
    assert task["detail_snapshot"]["detail_run_cap"] == 10

    board_response = client.get("/api/v1/task-control-board")

    assert board_response.status_code == 200
    board_run = board_response.json()["runs"][0]
    assert board_run["recovery_attempt"] == recovery_attempt
    assert "request_payload" not in board_run
    assert "events" not in board_run


def test_detail_run_projections_keep_frozen_plan_membership_and_live_counts(
    crawl_control_client,
):
    client, revision_id = crawl_control_client
    request_db = client.app.state.session_factory()
    try:
        request_db.add_all(
            [
                CrawlJobListing(
                    crawl_job_id=uuid4(),
                    source_site="jobsdb",
                    source_job_id=f"detail-target-{index}",
                    source_url=f"https://example.test/jobs/{index}",
                    listing_payload={"source_job_id": f"detail-target-{index}"},
                    listing_rank=index,
                    detail_status="pending",
                )
                for index in range(8)
            ]
        )
        request_db.commit()
    finally:
        request_db.close()

    one_off = {
        "version": 1,
        "kind": "one_off",
        "scope": {
            "version": 1,
            "source_site": "jobsdb",
            "reviewed_catalog_revision_id": str(revision_id),
            "mode": "all",
            "rules": [],
        },
        "listing_settings": None,
        "detail_settings": {
            "version": 1,
            "crawl_mode": "headless",
            "backlog_scope": {"kind": "source_backlog"},
            "limit": {"kind": "stop_after", "detail_run_cap": 8},
            "backlog_snapshot": None,
        },
    }
    preparation = client.post("/api/v1/dispatch-plans", json=one_off).json()
    plan = preparation["plan"]
    frozen = plan["content"]["detail_settings"]["backlog_snapshot"]
    assert frozen["selected_target_count"] == 8
    dispatched = client.post(
        f"/api/v1/dispatch-plans/{plan['plan_id']}/dispatch",
        json={
            "confirmation_token": preparation["confirmation_token"],
            "expected_plan_fingerprint": plan["plan_fingerprint"],
        },
    ).json()
    crawl_job_id = dispatched["run"]["crawl_job_id"]

    request_db = client.app.state.session_factory()
    try:
        request_db.execute(
            update(CrawlJob)
            .where(CrawlJob.id == UUID(crawl_job_id))
            .values(
                metrics={
                    # Mutable runtime metrics cannot redefine frozen authority.
                    "detail_snapshot_cutoff_at": "1999-01-01T00:00:00Z",
                    "detail_snapshot_target_count": 999,
                    "detail_snapshot_fetched_count": 2,
                    "jobs_saved": 1,
                    "detail_snapshot_failed_count": 1,
                    "detail_snapshot_unavailable_count": 1,
                    "detail_snapshot_manual_action_count": 1,
                    "detail_snapshot_remaining_count": 3,
                    "detail_live_future_eligible_count": 5,
                    "detail_run_cap": 999,
                }
            )
        )
        request_db.commit()
    finally:
        request_db.close()

    tasks_response = client.get("/api/v1/crawl-jobs/tasks")

    assert tasks_response.status_code == 200
    task = tasks_response.json()["items"][0]
    expected_detail_snapshot = {
        "version": 1,
        "backlog_scope": {"kind": "source_backlog"},
        "limit_kind": "stop_after",
        "cutoff_at": frozen["cutoff_at"],
        "target_count": 8,
        "fetched_count": 2,
        "saved_count": 1,
        "failed_count": 1,
        "unavailable_count": 1,
        "manual_action_count": 1,
        "remaining_count": 3,
        "future_eligible_count": 5,
        "detail_run_cap": 8,
    }
    assert task["crawl_job_id"] == crawl_job_id
    assert task["detail_snapshot"] == expected_detail_snapshot

    board_response = client.get("/api/v1/task-control-board")

    assert board_response.status_code == 200
    board_run = board_response.json()["runs"][0]
    assert board_run["crawl_job_id"] == crawl_job_id
    assert board_run["detail_snapshot"] == expected_detail_snapshot


def test_automation_api_lists_versioned_rows_and_rejects_stale_updates(
    crawl_control_client,
):
    client, revision_id = crawl_control_client
    configuration = {
        "version": 1,
        "name": "JobsDB listing",
        "description": "Reviewed recurring crawl",
        "cron_expression": "0 4 * * *",
        "timezone": "Asia/Hong_Kong",
        "scope": {
            "version": 1,
            "source_site": "jobsdb",
            "reviewed_catalog_revision_id": str(revision_id),
            "mode": "all",
            "rules": [],
        },
        "listing_settings": {
            "version": 1,
            "crawl_mode": "headless",
            "page_depth": 2,
            "run_page_cap": 100,
        },
        "detail_settings": None,
    }

    create_review = _review_automation_configuration(client, configuration)
    stale_create = client.post(
        "/api/v1/automations",
        json={
            "configuration": configuration,
            "review_fingerprint": "0" * 64,
            "initial_state": "paused",
        },
    )
    assert stale_create.status_code == 409
    assert stale_create.json()["detail"]["code"] == "AUTOMATION_REVIEW_STALE"

    created = client.post(
        "/api/v1/automations",
        json={
            "configuration": configuration,
            "review_fingerprint": create_review["input_fingerprint"],
            "initial_state": "paused",
        },
    )

    assert created.status_code == 201
    assert created.headers["etag"] == '"1"'
    created_payload = created.json()
    automation_id = created_payload["snapshot"]["automation_id"]
    assert created_payload["snapshot"]["revision"] == 1
    assert created_payload["snapshot"]["lifecycle_state"] == "paused"

    listed = client.get("/api/v1/automations?source_site=jobsdb")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert [
        item["snapshot"]["automation_id"] for item in listed.json()["items"]
    ] == [automation_id]

    renamed_configuration = {**configuration, "name": "Renamed listing"}
    update_review = _review_automation_configuration(
        client,
        renamed_configuration,
        automation_id=automation_id,
        expected_revision=1,
    )
    updated = client.put(
        f"/api/v1/automations/{automation_id}",
        json={
            "expected_revision": 1,
            "configuration": renamed_configuration,
            "review_fingerprint": update_review["input_fingerprint"],
        },
    )
    assert updated.status_code == 200
    assert updated.headers["etag"] == '"2"'
    assert updated.json()["snapshot"]["configuration"]["name"] == (
        "Renamed listing"
    )

    stale = client.put(
        f"/api/v1/automations/{automation_id}",
        json={
            "expected_revision": 1,
            "configuration": configuration,
            "review_fingerprint": update_review["input_fingerprint"],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == {
        "code": "AUTOMATION_REVISION_CONFLICT",
        "message": "Automation revision changed before this mutation",
        "context": {
            "automation_id": automation_id,
            "expected_revision": 1,
            "current_revision": 2,
        },
    }
