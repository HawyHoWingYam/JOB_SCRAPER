from datetime import datetime, timezone
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import UUID, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.api.ai import CreateRunRequest, PendingSelectionRequest, router
from app.models.company import Company
from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
from app.models.job import Job
from app.services.enrichment_run_service import (
    ActiveEnrichmentRunError,
    EnrichmentRunService,
    PendingJobFilters,
)


@compiles(UUID, "sqlite")
def compile_uuid_for_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(32)"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Company.__table__.create(engine)
    Job.__table__.create(engine)
    EnrichmentRun.__table__.create(engine)
    EnrichmentRunItem.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def company(db):
    row = Company(
        company_id="company-1",
        source_site="jobsdb",
        source_company_id="company-1",
        name="Example Co",
    )
    db.add(row)
    db.flush()
    return row


def make_job(
    db,
    company,
    *,
    job_id,
    source_site="jobsdb",
    classification="Information Technology",
    subclassification="Software Engineering",
    posted_date=datetime(2026, 7, 18, 12, 0),
    created_at=datetime(2026, 7, 18, 12, 0),
    enriched=False,
    deleted=False,
):
    row = Job(
        id=uuid.UUID(job_id),
        job_id=f"job-{job_id}",
        source_site=source_site,
        source_job_id=f"source-{job_id}",
        company_id=company.id,
        title=f"Title {job_id[-4:]}",
        source_classification_id="6281" if classification else None,
        source_classification_name=classification,
        source_subclassification_id="6282" if subclassification else None,
        source_subclassification_name=subclassification,
        posted_date=posted_date,
        created_at=created_at,
        ai_enriched_at=datetime(2026, 7, 18, 13, 0) if enriched else None,
        is_deleted=deleted,
    )
    db.add(row)
    db.flush()
    return row


def make_run(db, *, run_id, status, created_at, completed_at=None, job_ids=None):
    ids = list(job_ids or [])
    row = EnrichmentRun(
        id=run_id,
        source_type="manual_pending",
        status=status,
        job_ids=ids,
        total_items=len(ids),
        pending_items=len(ids) if status in {"waiting", "pending", "running", "stopping"} else 0,
        completed_items=0,
        failed_items=0,
        cancelled_items=0,
        created_at=created_at,
        completed_at=completed_at,
    )
    db.add(row)
    db.flush()
    for position, job_id in enumerate(ids):
        db.add(EnrichmentRunItem(run_id=row.id, job_id=uuid.UUID(job_id), position=position, status="pending"))
    db.flush()
    return row


def test_pending_request_normalizes_values_and_enforces_safe_scope():
    request = PendingSelectionRequest.model_validate({
        "filters": {
            "source_sites": [" JobsDB ", "jobsdb"],
            "source_classification_names": [" Information Technology "],
        },
        "limit": 25,
    })
    assert request.filters.source_sites == ["jobsdb"]
    assert request.filters.source_classification_names == ["information technology"]

    with pytest.raises(ValidationError):
        PendingSelectionRequest(filters={}, limit=25)
    with pytest.raises(ValidationError):
        PendingSelectionRequest(filters={}, limit=0, all_pending_acknowledged=True)
    with pytest.raises(ValidationError):
        CreateRunRequest.model_validate({"mode": "batch", "job_ids": [str(uuid.uuid4())]})


def test_public_routes_expose_filtered_controls_and_remove_single_job_endpoint():
    route_paths = {(route.path, method) for route in router.routes for method in route.methods}
    assert ("/api/v1/ai/pending/filter-options", "GET") in route_paths
    assert ("/api/v1/ai/pending/preview", "POST") in route_paths
    assert ("/api/v1/ai/runs/{run_id}/stop", "POST") in route_paths
    assert not any(path == "/api/v1/ai/enrich-job/{job_id}" for path, _ in route_paths)


def test_filters_use_or_within_fields_and_and_across_fields_with_inclusive_dates(db, company):
    matching = make_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000001",
        source_site="jobsdb",
        subclassification="Security",
        posted_date=datetime(2026, 7, 1, 23, 59),
    )
    make_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000002",
        source_site="offertoday",
        subclassification="Security",
        posted_date=datetime(2026, 7, 1, 12, 0),
    )
    make_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000003",
        source_site="jobsdb",
        subclassification="Sales",
        posted_date=datetime(2026, 7, 1, 12, 0),
    )

    filters = PendingJobFilters(
        source_sites=("jobsdb", "ctgoodjobs"),
        source_subclassification_names=("security", "software engineering"),
        posted_date_from=datetime(2026, 7, 1, tzinfo=timezone.utc).date(),
        posted_date_to=datetime(2026, 7, 1, tzinfo=timezone.utc).date(),
    )
    service = EnrichmentRunService(db)
    assert service.preview_pending_jobs(filters=filters, limit=50) == {
        "matching_pending_count": 1,
        "effective_item_count": 1,
    }
    run = service.create_manual_pending_run(limit=50, filters=filters)
    assert run.job_ids == [str(matching.id)]


def test_candidate_query_excludes_ineligible_enriched_deleted_and_reserved_jobs(db, company):
    eligible = make_job(db, company, job_id="00000000-0000-0000-0000-000000000010")
    reserved = make_job(db, company, job_id="00000000-0000-0000-0000-000000000011")
    make_job(db, company, job_id="00000000-0000-0000-0000-000000000012", classification=None)
    make_job(db, company, job_id="00000000-0000-0000-0000-000000000013", enriched=True)
    make_job(db, company, job_id="00000000-0000-0000-0000-000000000014", deleted=True)
    make_run(
        db,
        run_id="waiting-reservation",
        status="waiting",
        created_at=datetime(2026, 7, 18, 10, 0),
        job_ids=[str(reserved.id)],
    )

    service = EnrichmentRunService(db)
    assert service.preview_pending_jobs(filters=PendingJobFilters(), limit=50)["matching_pending_count"] == 1
    assert service._query_pending_candidates(Job.id).one().id == eligible.id


def test_manual_pending_selection_is_oldest_first_with_uuid_tie_break(db, company):
    newest = make_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000099",
        created_at=datetime(2026, 7, 18, 12, 0),
    )
    tie_second = make_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000002",
        created_at=datetime(2026, 7, 18, 10, 0),
    )
    tie_first = make_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000001",
        created_at=datetime(2026, 7, 18, 10, 0),
    )
    run = EnrichmentRunService(db).create_manual_pending_run(limit=2)
    assert run.job_ids == [str(tie_first.id), str(tie_second.id)]
    assert str(newest.id) not in run.job_ids


def test_active_slot_rejects_manual_create_and_retry(db, company):
    job = make_job(db, company, job_id="00000000-0000-0000-0000-000000000021")
    active = make_run(
        db,
        run_id="active-run",
        status="running",
        created_at=datetime(2026, 7, 18, 10, 0),
        job_ids=[str(job.id)],
    )
    service = EnrichmentRunService(db)
    with pytest.raises(ActiveEnrichmentRunError) as create_error:
        service.create_manual_pending_run(limit=1)
    assert create_error.value.run_id == active.id
    with pytest.raises(ActiveEnrichmentRunError):
        service.create_retry_run_from_failed_items("missing-run")


def test_cooperative_stop_finishes_in_flight_and_cancels_untouched_items(db, company):
    first = make_job(db, company, job_id="00000000-0000-0000-0000-000000000031")
    second = make_job(db, company, job_id="00000000-0000-0000-0000-000000000032")
    run = make_run(
        db,
        run_id="cooperative-stop",
        status="running",
        created_at=datetime(2026, 7, 18, 10, 0),
        job_ids=[str(first.id), str(second.id)],
    )
    service = EnrichmentRunService(db)
    items = service.list_run_items(run.id)
    assert service._update_item_started(run.id, items[0].id, first.title) is not None
    stopped = service.request_stop(run.id)
    assert stopped.status == "stopping"
    assert stopped.stop_requested_at is not None
    assert service._update_item_started(run.id, items[1].id, second.title) is None
    service._update_item_finished(run.id, items[0].id, {"status": "error", "error": "bad output"})
    finalized = service._finalize_stopping_run(service.get_run(run.id))
    assert finalized.status == "cancelled"
    assert finalized.pending_items == 0
    assert finalized.failed_items == 1
    assert finalized.cancelled_items == 1
    assert [item.status for item in service.list_run_items(run.id)] == ["failed", "cancelled"]


def test_stop_is_idempotent_for_terminal_runs(db):
    run = make_run(
        db,
        run_id="already-completed",
        status="completed",
        created_at=datetime(2026, 7, 18, 10, 0),
        completed_at=datetime(2026, 7, 18, 11, 0),
    )
    stopped = EnrichmentRunService(db).request_stop(run.id)
    assert stopped.status == "completed"
    assert stopped.stop_requested_at is None


def test_monitor_returns_active_plus_latest_terminal_or_latest_two_terminals(db):
    active = make_run(db, run_id="active", status="stopping", created_at=datetime(2026, 7, 18, 13, 0))
    latest = make_run(
        db,
        run_id="latest",
        status="failed",
        created_at=datetime(2026, 7, 18, 12, 0),
        completed_at=datetime(2026, 7, 18, 12, 30),
    )
    older = make_run(
        db,
        run_id="older",
        status="completed",
        created_at=datetime(2026, 7, 18, 11, 0),
        completed_at=datetime(2026, 7, 18, 11, 30),
    )
    service = EnrichmentRunService(db)
    assert [run.id for run in service.list_runs_for_monitor()] == [active.id, latest.id]
    active.status = "cancelled"
    active.completed_at = datetime(2026, 7, 18, 13, 30)
    db.flush()
    assert [run.id for run in service.list_runs_for_monitor()] == [active.id, latest.id]
    assert older.id not in [run.id for run in service.list_runs_for_monitor()]
