from __future__ import annotations

from types import SimpleNamespace
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
from app.api import router as production_api_router
from app.crawl_control import task_control_board_service as task_control_board_service_api
from app.database import get_db
from app.models.crawl_dispatch_plan import CRAWL_DISPATCH_PLAN_TABLES
from app.models.crawl_job import CrawlJob, CrawlJobEvent
from app.models.crawl_job_execution import CrawlJobExecution
from app.models.crawl_job_listing import CrawlJobListing
from app.models.crawl_run import CrawlRun
from app.models.event_outbox import EventOutbox
from app.models.schedule import (
    AutomationDeleteReview,
    ScheduleExecution,
    ScrapeSchedule,
)
from app.models.scraper_pacing_settings import ScraperPacingSettings
from app.models.source_classification import SourceClassification
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.services.crawl_job_dispatch_service import CrawlJobDispatchService
from app.services.crawl_job_execution_launcher import CrawlJobLaunchResult
from app.services.source_classification_registry import SourceClassificationRegistry
from app.source_classifications.adapters.jobsdb import JobsDBSourceClassificationAdapter


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
        "/api/crawl-scopes/preview": {"post"},
        "/api/automations": {"get", "post"},
        "/api/automations/reviews": {"post"},
        "/api/automations/{automation_id}": {"get", "put", "delete"},
        "/api/automations/{automation_id}/pause": {"post"},
        "/api/automations/{automation_id}/resume": {"post"},
        "/api/automations/{automation_id}/archive": {"post"},
        "/api/automations/{automation_id}/restore": {"post"},
        "/api/automations/{automation_id}/delete-reviews": {"post"},
        "/api/dispatch-plans": {"post"},
        "/api/dispatch-plans/{plan_id}": {"get"},
        "/api/dispatch-plans/{plan_id}/dispatch": {"post"},
        "/api/task-control-board": {"get"},
        "/api/crawl-jobs/tasks": {"get"},
        "/api/crawl-jobs/{crawl_job_id}/dismiss-failed-attention": {"post"},
    }
    for path, methods in expected_operations.items():
        assert methods <= set(paths[path])
    assert "/api/crawl-jobs" not in paths
    board_schema = paths["/api/task-control-board"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert board_schema["$ref"].endswith("/TaskControlBoardProjectionV2")
    assert paths["/api/dispatch-plans/{plan_id}/dispatch"]["post"][
        "responses"
    ]["202"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/DispatchPlanDispatchResponseV1"
    )


@pytest.fixture
def crawl_control_client(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SourceClassification.metadata.create_all(
        engine,
        tables=(
            SourceClassification.__table__,
            ScrapeSchedule.__table__,
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
    catalog = JobsDBSourceClassificationAdapter().discover()
    SourceClassificationRegistry(db).synchronize_catalog(catalog, complete=True)
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
    obsolete_revision_id = uuid4()
    db.close()

    app = FastAPI()
    app.state.session_factory = session_factory
    app.include_router(crawl_control_api.router, prefix="/api")
    app.include_router(crawl_jobs_api.router, prefix="/api")
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
        crawl_jobs_api,
        "dispatch_service",
        CrawlJobDispatchService(
            execution_launcher=_NoopLauncher(),
            outbox_publisher=_NoopOutboxPublisher(),
        ),
    )

    def override_get_db():
        request_db = session_factory()
        try:
            yield request_db
        finally:
            request_db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, obsolete_revision_id
    engine.dispose()


def _review_automation_configuration(
    client: TestClient,
    configuration: dict,
    *,
    automation_id: str | None = None,
) -> dict:
    response = client.post(
        "/api/automations/reviews",
        json={
            "configuration": configuration,
            **(
                {
                    "automation_id": automation_id,
                }
                if automation_id is not None
                else {}
            ),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _dispatch_current_listing(client, *, requested_by: str) -> UUID:
    db = client.app.state.session_factory()
    try:
        result = CrawlJobDispatchService(
            execution_launcher=_NoopLauncher(),
            outbox_publisher=_NoopOutboxPublisher(),
        ).dispatch_manual_crawl_job(
            db,
            source_site="jobsdb",
            crawl_phase="listing",
            crawl_mode="headless",
            category_ids=[6281],
            max_pages=1,
            requested_by=requested_by,
        )
        return result.crawl_job.id
    finally:
        db.close()


def test_scope_preview_returns_normalized_workload_and_rejects_unknown_root(
    crawl_control_client,
):
    client, revision_id = crawl_control_client
    request = {
        "scope": {
            "source_site": "jobsdb",
            "mode": "all",
            "classification_ids": [],
        },
        "listing_settings": {
            "crawl_mode": "headless",
            "page_depth": 2,
            "run_page_cap": 100,
        },
    }

    response = client.post("/api/crawl-scopes/preview", json=request)

    assert response.status_code == 200
    payload = response.json()
    assert payload["resolved_scope"]["query_target_count"] == 25
    assert payload["listing_workload"] == {
        "query_target_count": 25,
        "page_depth": 2,
        "estimated_max_pages": 50,
        "run_page_cap": 100,
        "system_run_page_cap": 5000,
        "within_operator_cap": True,
        "within_system_cap": True,
    }

    request["scope"] = {
        "source_site": "jobsdb",
        "mode": "selected",
        "classification_ids": ["jobsdb:unknown"],
    }
    unknown = client.post("/api/crawl-scopes/preview", json=request)

    assert unknown.status_code == 422
    assert unknown.json()["detail"]["code"] == "SCOPE_RULE_INVALID"


def test_automation_lifecycle_and_reviewed_permanent_delete_use_current_row(
    crawl_control_client,
):
    client, revision_id = crawl_control_client
    configuration = {
        "name": "Lifecycle fixture",
        "description": None,
        "cron_expression": "0 4 * * *",
        "timezone": "UTC",
        "scope": {
            "source_site": "jobsdb",
            "mode": "all",
            "classification_ids": [],
        },
        "listing_settings": {
            "crawl_mode": "headless",
            "page_depth": 1,
            "run_page_cap": 25,
        },
        "detail_settings": None,
    }
    automation_review = _review_automation_configuration(client, configuration)
    created_response = client.post(
        "/api/automations",
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
        f"/api/automations/{automation_id}/pause",
        json={},
    )
    assert paused.status_code == 200
    assert "etag" not in paused.headers
    assert paused.json()["snapshot"]["lifecycle_state"] == "paused"

    resumed = client.post(
        f"/api/automations/{automation_id}/resume",
        json={},
    )
    assert resumed.status_code == 200
    assert resumed.json()["snapshot"]["lifecycle_state"] == "active"

    archived = client.post(
        f"/api/automations/{automation_id}/archive",
        json={},
    )
    assert archived.status_code == 200
    assert archived.json()["snapshot"]["lifecycle_state"] == "archived"

    review = client.post(
        f"/api/automations/{automation_id}/delete-reviews"
    )
    assert review.status_code == 200
    review_payload = review.json()
    assert review_payload["impact"]["removed_records"] == [
        "automation",
    ]
    assert review_payload["impact"]["preserved_records"] == [
        "schedule_executions",
        "crawl_jobs",
        "run_history",
    ]

    deleted = client.request(
        "DELETE",
        f"/api/automations/{automation_id}",
        json={
            "review_token": review_payload["review_token"],
        },
    )
    assert deleted.status_code == 200
    assert deleted.json()["automation_id"] == automation_id
    assert client.get(f"/api/automations/{automation_id}").status_code == 404


def test_dispatch_plan_prepare_and_get_review_without_launching(
    crawl_control_client,
):
    client, revision_id = crawl_control_client
    request = {
        "kind": "one_off",
        "scope": {
            "source_site": "jobsdb",
            "mode": "all",
            "classification_ids": [],
        },
        "listing_settings": {
            "crawl_mode": "headless",
            "page_depth": 1,
            "run_page_cap": 25,
        },
        "detail_settings": None,
    }

    prepared = client.post("/api/dispatch-plans", json=request)

    assert prepared.status_code == 201
    preparation = prepared.json()
    plan_id = preparation["plan"]["plan_id"]
    assert preparation["confirmation_token"]
    assert preparation["plan"]["state"] == "prepared"
    assert preparation["plan"]["readiness"]["status"] == "ready"
    assert "catalog_revision_id" not in preparation["plan"]["content"]

    reviewed = client.get(f"/api/dispatch-plans/{plan_id}")
    assert reviewed.status_code == 200
    assert reviewed.json()["plan_id"] == plan_id
    assert reviewed.json()["state"] == "prepared"
    assert "confirmation_token" not in reviewed.json()


def test_dispatch_plan_confirmation_returns_normalized_single_use_run(
    crawl_control_client,
):
    client, revision_id = crawl_control_client
    request = {
        "kind": "one_off",
        "scope": {
            "source_site": "jobsdb",
            "mode": "all",
            "classification_ids": [],
        },
        "listing_settings": {
            "crawl_mode": "headless",
            "page_depth": 1,
            "run_page_cap": 25,
        },
        "detail_settings": None,
    }
    preparation = client.post("/api/dispatch-plans", json=request).json()
    plan = preparation["plan"]
    dispatch_request = {
        "confirmation_token": preparation["confirmation_token"],
        "expected_plan_fingerprint": plan["plan_fingerprint"],
    }

    missing_fingerprint = client.post(
        f"/api/dispatch-plans/{plan['plan_id']}/dispatch",
        json={"confirmation_token": preparation["confirmation_token"]},
    )

    assert missing_fingerprint.status_code == 422
    assert client.get(
        f"/api/dispatch-plans/{plan['plan_id']}"
    ).json()["state"] == "prepared"

    dispatched = client.post(
        f"/api/dispatch-plans/{plan['plan_id']}/dispatch",
        json=dispatch_request,
    )

    assert dispatched.status_code == 202
    payload = dispatched.json()
    assert payload["plan"]["state"] == "consumed"
    assert payload["run"]["status"] == "queued"
    assert payload["run"]["source_site"] == "jobsdb"
    assert payload["run"]["crawl_phase"] == "listing"
    assert payload["run"]["authority"] == {
        "authority_kind": "dispatch_plan",
        "dispatch_plan_id": plan["plan_id"],
        "dispatch_plan_fingerprint": plan["plan_fingerprint"],
        "plan_state": "consumed",
        "automation_id": None,
        "authored_scope": plan["content"]["authored_scope"],
        "resolved_scope": plan["content"]["resolved_scope"],
        "readiness": plan["readiness"],
    }
    assert payload["run"]["listing_workload"] == {
        "query_target_count": 25,
        "page_depth": 1,
        "estimated_max_pages": 25,
        "run_page_cap": 25,
        "pages_requested": 0,
    }
    assert payload["run"]["detail_snapshot"] is None
    assert "request_payload" not in payload["run"]

    repeated = client.post(
        f"/api/dispatch-plans/{plan['plan_id']}/dispatch",
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
        "name": "Board Automation",
        "description": None,
        "cron_expression": "0 4 * * *",
        "timezone": "UTC",
        "scope": {
            "source_site": "jobsdb",
            "mode": "all",
            "classification_ids": [],
        },
        "listing_settings": {
            "crawl_mode": "headless",
            "page_depth": 1,
            "run_page_cap": 25,
        },
        "detail_settings": None,
    }
    automation_review = _review_automation_configuration(client, configuration)
    client.post(
        "/api/automations",
        json={
            "configuration": configuration,
            "review_fingerprint": automation_review["input_fingerprint"],
            "initial_state": "paused",
        },
    ).json()
    one_off = {
        "kind": "one_off",
        "scope": configuration["scope"],
        "listing_settings": configuration["listing_settings"],
        "detail_settings": None,
    }
    preparation = client.post("/api/dispatch-plans", json=one_off).json()
    dispatched = client.post(
        f"/api/dispatch-plans/{preparation['plan']['plan_id']}/dispatch",
        json={
            "confirmation_token": preparation["confirmation_token"],
            "expected_plan_fingerprint": preparation["plan"][
                "plan_fingerprint"
            ],
        },
    ).json()

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
    board_response = client.get(
        "/api/task-control-board",
        params={"source_site": "jobsdb"},
    )
    assert board_response.status_code == 200
    board = board_response.json()
    assert board["selected_source"] == "jobsdb"
    assert board_sources == ["jobsdb", "ctgoodjobs", "offertoday"]
    assert [item["source_site"] for item in board["source_summaries"]] == [
        "jobsdb",
        "ctgoodjobs",
        "offertoday",
    ]
    assert "catalog_health" not in board["source_summaries"][0]
    assert board["needs_attention"] == []
    assert len(board["active_runs"]) == 1
    assert board["active_runs"][0]["run"]["crawl_job_id"] == dispatched["run"]["crawl_job_id"]
    assert board["active_runs"][0]["actions"][0]["action"] == "view_task"
    assert len(board["upcoming"]) == 1
    assert board["upcoming"][0]["schedule"]["timezone"] == "UTC"
    assert "catalog_health" not in board["upcoming"][0]
    assert board["upcoming"][0]["actions"][0] == {
        "action": "edit",
        "enabled": True,
        "reason_code": None,
    }
    assert board["all_clear"] is False

    task_response = client.get(
        f"/api/crawl-jobs/tasks/{dispatched['run']['crawl_job_id']}"
    )
    assert task_response.status_code == 200
    task = task_response.json()
    assert task["run"]["authority"]["authority_kind"] == "dispatch_plan"
    assert task["run"]["listing_workload"]["query_target_count"] == 25
    assert task["actions"][0]["action"] == "view_task"
    assert "request_payload" not in task
    assert "manual_action" not in task

    missing_id = uuid4()
    missing_response = client.get(f"/api/crawl-jobs/tasks/{missing_id}")
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
        "/api/task-control-board",
        params={"source_site": "unknown-source"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "SOURCE_SITE_UNSUPPORTED",
        "message": "Unsupported Crawl Control source_site",
        "context": {"source_site": "unknown-source"},
    }


def test_failed_run_attention_dismissal_is_sequence_safe_and_idempotent(
    crawl_control_client,
):
    client, _revision_id = crawl_control_client
    session_factory = client.app.state.session_factory
    repository = CrawlJobRepository()
    created_id = _dispatch_current_listing(client, requested_by="test")
    db = session_factory()
    try:
        crawl_job = db.get(CrawlJob, created_id)
        assert crawl_job is not None
        repository.record_runtime_event(
            db,
            crawl_job_id=crawl_job.id,
            status="failed",
            event_type="crawl.failed",
            payload={"error": "synthetic terminal failure"},
            emitted_by="test",
            completed_at=crawl_job.queued_at,
            error_message="synthetic terminal failure",
        )
        failure = repository.list_events(
            db,
            crawl_job.id,
            event_types={"crawl.failed"},
        )[-1]
        crawl_job_id = str(crawl_job.id)
        failure_sequence = failure.sequence_no
    finally:
        db.close()

    board_before = client.get(
        "/api/task-control-board",
        params={"source_site": "jobsdb"},
    )
    assert board_before.status_code == 200
    failed_item = next(
        item
        for item in board_before.json()["needs_attention"]
        if item["entity_id"] == crawl_job_id
    )
    assert failed_item["kind"] == "failed_run"
    assert failed_item["failure_event_sequence"] == failure_sequence
    assert failed_item["secondary_actions"][-1]["action"] == "dismiss_failed_run"

    first = client.post(
        f"/api/crawl-jobs/{crawl_job_id}/dismiss-failed-attention",
        json={"expected_failure_event_sequence": failure_sequence},
    )
    assert first.status_code == 200
    assert first.json() == {
        "crawl_job_id": crawl_job_id,
        "failure_event_sequence": failure_sequence,
        "dismissal_event_sequence": failure_sequence + 1,
        "replayed": False,
    }

    repeated = client.post(
        f"/api/crawl-jobs/{crawl_job_id}/dismiss-failed-attention",
        json={"expected_failure_event_sequence": failure_sequence},
    )
    assert repeated.status_code == 200
    assert repeated.json() == {**first.json(), "replayed": True}

    db = session_factory()
    try:
        dismissals = repository.list_events(
            db,
            UUID(crawl_job_id),
            event_types={"crawl.failed_attention_dismissed"},
        )
        assert len(dismissals) == 1
        assert dismissals[0].emitted_by == "local-operator"
        assert dismissals[0].payload == {
            "crawl_job_id": crawl_job_id,
            "failure_event_sequence": failure_sequence,
            "actor": "local-operator",
        }
    finally:
        db.close()

    board_after = client.get(
        "/api/task-control-board",
        params={"source_site": "jobsdb"},
    )
    assert board_after.status_code == 200
    assert all(
        item["entity_id"] != crawl_job_id
        for item in board_after.json()["needs_attention"]
    )
    task_after = client.get(f"/api/crawl-jobs/tasks/{crawl_job_id}")
    assert task_after.status_code == 200
    assert task_after.json()["persisted_status"] == "failed"
    assert task_after.json()["issue"]["summary"] == "synthetic terminal failure"

    db = session_factory()
    try:
        next_failure = repository.append_event(
            db,
            crawl_job_id=UUID(crawl_job_id),
            event_type="crawl.failed",
            payload={"error": "new terminal failure"},
            emitted_by="test",
        )
        next_failure_sequence = next_failure.sequence_no
    finally:
        db.close()

    board_with_new_failure = client.get(
        "/api/task-control-board",
        params={"source_site": "jobsdb"},
    ).json()
    next_item = next(
        item
        for item in board_with_new_failure["needs_attention"]
        if item["entity_id"] == crawl_job_id
    )
    assert next_item["failure_event_sequence"] == next_failure_sequence

    stale = client.post(
        f"/api/crawl-jobs/{crawl_job_id}/dismiss-failed-attention",
        json={"expected_failure_event_sequence": failure_sequence},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "FAILED_ATTENTION_SEQUENCE_CONFLICT"


def test_failed_run_attention_dismissal_rejects_a_non_failed_task(
    crawl_control_client,
):
    client, _revision_id = crawl_control_client
    session_factory = client.app.state.session_factory
    db = session_factory()
    try:
        crawl_job = CrawlJobRepository().create_crawl_job(
            db,
            source_site="ctgoodjobs",
            trigger_type="manual",
            request_payload={"crawl_phase": "listing"},
            requested_by="test",
        )
        crawl_job_id = str(crawl_job.id)
    finally:
        db.close()

    response = client.post(
        f"/api/crawl-jobs/{crawl_job_id}/dismiss-failed-attention",
        json={"expected_failure_event_sequence": 1},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "FAILED_ATTENTION_STATE_INVALID",
        "message": "Only a terminal failed crawl task can be dismissed from attention",
        "context": {
            "crawl_job_id": crawl_job_id,
            "current_status": "queued",
        },
    }


def test_failed_run_attention_dismissal_rejects_an_unknown_task(
    crawl_control_client,
):
    client, _revision_id = crawl_control_client
    crawl_job_id = uuid4()

    response = client.post(
        f"/api/crawl-jobs/{crawl_job_id}/dismiss-failed-attention",
        json={"expected_failure_event_sequence": 1},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "CRAWL_TASK_NOT_FOUND",
        "message": "Crawl task not found",
        "context": {"crawl_job_id": str(crawl_job_id)},
    }


def test_crawl_tasks_use_dispatch_plan_when_raw_payloads_are_absent(
    crawl_control_client,
):
    client, revision_id = crawl_control_client
    one_off = {
        "kind": "one_off",
        "scope": {
            "source_site": "jobsdb",
            "mode": "all",
            "classification_ids": [],
        },
        "listing_settings": {
            "crawl_mode": "headless",
            "page_depth": 2,
            "run_page_cap": 50,
        },
        "detail_settings": None,
    }
    preparation = client.post("/api/dispatch-plans", json=one_off).json()
    dispatched = client.post(
        f"/api/dispatch-plans/{preparation['plan']['plan_id']}/dispatch",
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

    response = client.get("/api/crawl-jobs/tasks")

    assert response.status_code == 200
    task = response.json()["items"][0]
    assert task["crawl_job_id"] == crawl_job_id
    assert task["crawl_phase"] == "listing"
    assert task["dispatch_plan_id"] == preparation["plan"]["plan_id"]
    assert "catalog_revision_id" not in task["authority"]
    assert task["listing_workload"] == {
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
    created_id = _dispatch_current_listing(
        client,
        requested_by="operator-1",
    )
    request_db = client.app.state.session_factory()
    repository = CrawlJobRepository()
    try:
        crawl_job = request_db.get(CrawlJob, created_id)
        assert crawl_job is not None
        crawl_job.status = "manual_action_required"
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

    tasks_response = client.get("/api/crawl-jobs/tasks")

    assert tasks_response.status_code == 200
    task = tasks_response.json()["items"][0]
    assert task["crawl_job_id"] == crawl_job_id
    recovery_attempt = task["recovery_attempt"]
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
    board_response = client.get("/api/task-control-board")

    assert board_response.status_code == 200
    board_run = board_response.json()["active_runs"][0]["run"]
    assert board_run["recovery_attempt"] == recovery_attempt
    assert "request_payload" not in board_run
    assert "events" not in board_run


@pytest.mark.parametrize("source_site", ["jobsdb", "ctgoodjobs"])
def test_reset_browser_profile_records_safe_reset_without_changing_task_scope(
    crawl_control_client,
    monkeypatch,
    tmp_path,
    source_site,
):
    client, _revision_id = crawl_control_client
    repository = CrawlJobRepository()
    request_db = client.app.state.session_factory()
    profile_path = str(tmp_path / "fixed-profile")
    try:
        crawl_job = repository.create_crawl_job(
            request_db,
            source_site=source_site,
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
        repository.append_event(
            request_db,
            crawl_job_id=crawl_job.id,
            event_type="crawl.manual_action_required",
            payload={
                "manual_action": {
                    "source_site": source_site,
                    "stage": "browser_profile_in_use",
                    "browser_channel": "chromium",
                    "browser_profile_path": profile_path,
                    "profile_scope": "fixed_profile",
                    "resume_supported": True,
                }
            },
            emitted_by=f"{source_site}-crawl",
            auto_commit=False,
        )
        request_db.commit()
        crawl_job_id = str(crawl_job.id)
    finally:
        request_db.close()


    def fake_reset(path, **kwargs):
        assert path == profile_path
        assert kwargs["profile_scope"] == "fixed_profile"
        assert kwargs["browser_channel"] == "chromium"
        return SimpleNamespace(
            available=True,
            profile_path=path,
            profile_scope="fixed_profile",
            liveness=SimpleNamespace(state="dead"),
            removed_lock_markers=("SingletonLock",),
            recreated=False,
        )

    monkeypatch.setattr(crawl_jobs_api, "reset_profile", fake_reset)

    response = client.post(
        f"/api/crawl-jobs/{crawl_job_id}/reset-browser-profile"
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "reset",
        "crawl_job_id": crawl_job_id,
        "profile_scope": "fixed_profile",
        "liveness": "dead",
        "removed_lock_markers": ["SingletonLock"],
        "recreated": False,
    }

    request_db = client.app.state.session_factory()
    try:
        event = (
            request_db.query(CrawlJobEvent)
            .filter(
                CrawlJobEvent.crawl_job_id == UUID(crawl_job_id),
                CrawlJobEvent.event_type == "crawl.browser_profile_reset",
            )
            .one()
        )
        assert event.payload["profile_scope"] == "fixed_profile"
        assert event.payload["recreated"] is False
    finally:
        request_db.close()


def test_manual_profile_guidance_uses_event_browser_channel_for_liveness(
    monkeypatch,
):
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        task_control_board_service_api.settings,
        "jobsdb_headed_browser_user_data_dir",
        "/var/lib/jobsdb/fixed-profile",
    )

    def fake_inspect(profile_path, *, browser_channel=None):
        observed["profile_path"] = profile_path
        observed["browser_channel"] = browser_channel
        return SimpleNamespace(state="dead", reason="no_active_browser_session")

    monkeypatch.setattr(task_control_board_service_api, "inspect_profile", fake_inspect)

    guidance = task_control_board_service_api._manual_action_guidance(
        {
            "source_site": "jobsdb",
            "manual_action": {
                "stage": "browser_profile_in_use",
                "browser_channel": "chromium",
                "browser_profile_path": "/var/lib/jobsdb/fixed-profile",
                "resume_supported": True,
            },
        }
    )

    assert guidance is not None
    assert observed == {
        "profile_path": "/var/lib/jobsdb/fixed-profile",
        "browser_channel": "chromium",
    }
    assert guidance.reset_supported is True
    assert guidance.profile_scope == "fixed_profile"
    assert guidance.resume_strategies == ("fresh_profile",)


def test_reset_capability_is_projected_for_ctgoodjobs_profile_locks(
    monkeypatch,
):
    monkeypatch.setattr(
        task_control_board_service_api.settings,
        "jobsdb_headed_browser_user_data_dir",
        "/var/lib/jobsdb/fixed-profile",
    )
    monkeypatch.setattr(
        task_control_board_service_api,
        "inspect_profile",
        lambda *_args, **_kwargs: SimpleNamespace(state="dead", reason=None),
    )

    guidance = task_control_board_service_api._manual_action_guidance(
        {
            "source_site": "ctgoodjobs",
            "manual_action": {
                "stage": "browser_profile_in_use",
                "browser_profile_path": "/var/lib/jobsdb/fixed-profile",
                "reset_supported": True,
                "resume_supported": True,
            },
        }
    )

    assert guidance is not None
    assert guidance.reset_supported is True


def test_reset_capability_rejects_profile_outside_configured_root(monkeypatch):
    monkeypatch.setattr(
        task_control_board_service_api.settings,
        "jobsdb_headed_browser_user_data_dir",
        "/var/lib/jobsdb/configured-profile",
    )
    monkeypatch.setattr(
        task_control_board_service_api,
        "inspect_profile",
        lambda *_args, **_kwargs: pytest.fail("unowned profile must not be inspected"),
    )

    guidance = task_control_board_service_api._manual_action_guidance(
        {
            "source_site": "ctgoodjobs",
            "manual_action": {
                "stage": "browser_profile_in_use",
                "browser_profile_path": "/tmp/unrelated/fixed-profile",
                "reset_supported": True,
                "resume_supported": True,
            },
        }
    )

    assert guidance is not None
    assert guidance.reset_supported is False
    assert guidance.reset_reason == "profile_ownership_unverified"


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
        "kind": "one_off",
        "scope": {
            "source_site": "jobsdb",
            "mode": "all",
            "classification_ids": [],
        },
        "listing_settings": None,
        "detail_settings": {
            "crawl_mode": "headless",
            "backlog_scope": {"kind": "source_backlog"},
            "limit": {"kind": "stop_after", "detail_run_cap": 8},
            "backlog_snapshot": None,
        },
    }
    preparation = client.post("/api/dispatch-plans", json=one_off).json()
    plan = preparation["plan"]
    frozen = plan["content"]["detail_settings"]["backlog_snapshot"]
    assert frozen["selected_target_count"] == 8
    dispatched = client.post(
        f"/api/dispatch-plans/{plan['plan_id']}/dispatch",
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

    tasks_response = client.get("/api/crawl-jobs/tasks")

    assert tasks_response.status_code == 200
    task = tasks_response.json()["items"][0]
    expected_detail_snapshot = {
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

    board_response = client.get("/api/task-control-board")

    assert board_response.status_code == 200
    board_run = board_response.json()["active_runs"][0]["run"]
    assert board_run["crawl_job_id"] == crawl_job_id
    assert board_run["detail_snapshot"] == expected_detail_snapshot


def test_automation_api_lists_current_rows_and_later_update_wins(
    crawl_control_client,
):
    client, revision_id = crawl_control_client
    configuration = {
        "name": "JobsDB listing",
        "description": "Reviewed recurring crawl",
        "cron_expression": "0 4 * * *",
        "timezone": "Asia/Hong_Kong",
        "scope": {
            "source_site": "jobsdb",
            "mode": "all",
            "classification_ids": [],
        },
        "listing_settings": {
            "crawl_mode": "headless",
            "page_depth": 2,
            "run_page_cap": 100,
        },
        "detail_settings": None,
    }

    create_review = _review_automation_configuration(client, configuration)
    stale_create = client.post(
        "/api/automations",
        json={
            "configuration": configuration,
            "review_fingerprint": "0" * 64,
            "initial_state": "paused",
        },
    )
    assert stale_create.status_code == 409
    assert stale_create.json()["detail"]["code"] == "AUTOMATION_REVIEW_STALE"

    created = client.post(
        "/api/automations",
        json={
            "configuration": configuration,
            "review_fingerprint": create_review["input_fingerprint"],
            "initial_state": "paused",
        },
    )

    assert created.status_code == 201
    assert "etag" not in created.headers
    created_payload = created.json()
    automation_id = created_payload["snapshot"]["automation_id"]
    assert created_payload["snapshot"]["lifecycle_state"] == "paused"

    listed = client.get("/api/automations?source_site=jobsdb")
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
    )
    later_review = _review_automation_configuration(
        client,
        configuration,
        automation_id=automation_id,
    )
    updated = client.put(
        f"/api/automations/{automation_id}",
        json={
            "configuration": renamed_configuration,
            "review_fingerprint": update_review["input_fingerprint"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["snapshot"]["configuration"]["name"] == (
        "Renamed listing"
    )

    later = client.put(
        f"/api/automations/{automation_id}",
        json={
            "configuration": configuration,
            "review_fingerprint": later_review["input_fingerprint"],
        },
    )
    assert later.status_code == 200
    assert later.json()["snapshot"]["configuration"]["name"] == "JobsDB listing"
