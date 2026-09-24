import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import UUID, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.api.ai import (
    CreateRunRequest,
    PendingSelectionRequest,
    _derive_excluded_details,
    get_pending_filter_options as get_pending_filter_options_endpoint,
    _serialize_runs,
    _serialize_single_run,
    router,
)
from app.models.company import Company
from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
from app.models.event_outbox import EventOutbox
from app.models.job import Job
from app.models.manual_job import ManualJobEvidence
from app.models.source_job_attributes import (
    SOURCE_JOB_ATTRIBUTE_TABLES,
    JobSourceAttributeProjection,
    JobSourceClassificationPath,
    JobSourceClassificationPathNode,
)
from app.services.enrichment_run_service import (
    ActiveEnrichmentRunError,
    EnrichmentRunService,
    PendingJobFilters,
)
from app.services.ai_enrichment_service import AIEnrichmentService


@compiles(UUID, "sqlite")
def compile_uuid_for_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(32)"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Company.__table__.create(engine)
    Job.__table__.create(engine)
    ManualJobEvidence.__table__.create(engine)
    for table in SOURCE_JOB_ATTRIBUTE_TABLES:
        table.create(engine, checkfirst=True)
    EnrichmentRun.__table__.create(engine)
    EnrichmentRunItem.__table__.create(engine)
    EventOutbox.__table__.create(engine)
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
    source_classification_id=None,
    classification="Information Technology",
    subclassification="Software Engineering",
    posted_date=datetime(2026, 7, 18, 12, 0),
    created_at=datetime(2026, 7, 18, 12, 0),
    enriched=False,
    deleted=False,
    projected=True,
):
    row = Job(
        id=uuid.UUID(job_id),
        job_id=f"job-{job_id}",
        source_site=source_site,
        source_job_id=f"source-{job_id}",
        company_id=company.id,
        title=f"Title {job_id[-4:]}",
        source_classification_id=(
            source_classification_id
            if source_classification_id is not None
            else ("6281" if classification else None)
        ),
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
    if projected:
        db.add(
            JobSourceAttributeProjection(
                job_id=row.id,
                source_site=source_site,
                evidence_hash="0" * 64,
            )
        )
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
        pending_items=len(ids)
        if status in {"waiting", "pending", "running", "stopping"}
        else 0,
        completed_items=0,
        failed_items=0,
        cancelled_items=0,
        created_at=created_at,
        completed_at=completed_at,
    )
    db.add(row)
    db.flush()
    for position, job_id in enumerate(ids):
        db.add(
            EnrichmentRunItem(
                run_id=row.id,
                job_id=uuid.UUID(job_id),
                position=position,
                status="pending",
            )
        )
    db.flush()
    return row


def add_source_path(db, job, *nodes):
    path = JobSourceClassificationPath(
        job_id=job.id,
        source_site=job.source_site,
        source_order=0,
        path_fingerprint=str(job.id).replace("-", "").ljust(64, "0"),
        is_primary=False,
        primary_basis=None,
        provenance={"method": "test"},
    )
    db.add(path)
    db.flush()
    for position, (source_classification_id, label) in enumerate(nodes):
        db.add(
            JobSourceClassificationPathNode(
                path_id=path.id,
                source_site=job.source_site,
                source_position=position,
                native_depth=position,
                source_classification_id=source_classification_id,
                native_id=source_classification_id.split(":", 1)[1],
                label=label,
            )
        )
    db.flush()
    return path


def make_manual_job(
    db,
    company,
    *,
    job_id: str,
    description: str | None,
    enriched_hash: str | None = None,
    enriched: bool = False,
):
    job = make_job(
        db,
        company,
        job_id=job_id,
        source_site="manual",
        classification=None,
        subclassification=None,
        projected=False,
        enriched=enriched,
    )
    job.description = description
    db.add(
        ManualJobEvidence(
            job_id=job.id,
            evidence_hash="a" * 64,
            enriched_evidence_hash=enriched_hash,
            operator_authored_fields=["title", "description"],
        )
    )
    db.flush()
    return job


def test_pending_request_normalizes_values_and_enforces_safe_scope():
    request = PendingSelectionRequest.model_validate(
        {
            "filters": {
                "source_sites": [" JobsDB ", "jobsdb"],
                "source_classification_names": [" Information Technology "],
            },
            "limit": 25,
        }
    )
    assert request.filters.source_sites == ["jobsdb"]
    assert request.filters.source_classification_names == ["information technology"]

    qualified_request = PendingSelectionRequest.model_validate(
        {
            "filters": {
                "source_classification_ids": [" jobsdb:6281 ", "jobsdb:6281"],
                "source_subclassification_ids": ["jobsdb:6287"],
            },
            "limit": 25,
        }
    )
    assert qualified_request.filters.source_classification_ids == ["jobsdb:6281"]
    assert qualified_request.filters.source_subclassification_ids == ["jobsdb:6287"]

    with pytest.raises(ValidationError):
        PendingSelectionRequest.model_validate(
            {
                "filters": {"source_classification_ids": ["6281"]},
                "limit": 25,
            }
        )

    with pytest.raises(ValidationError):
        PendingSelectionRequest(filters={}, limit=25)
    with pytest.raises(ValidationError):
        PendingSelectionRequest(filters={}, limit=0, all_pending_acknowledged=True)
    with pytest.raises(ValidationError):
        CreateRunRequest.model_validate(
            {"mode": "batch", "job_ids": [str(uuid.uuid4())]}
        )


def test_manual_origin_is_a_valid_explicit_pending_scope() -> None:
    request = PendingSelectionRequest(
        filters={"source_sites": [" MANUAL "]},
        limit=25,
    )

    assert request.filters.source_sites == ["manual"]
    assert request.filters.to_service_filters().has_constraints


def test_manual_jobs_use_evidence_freshness_and_description_eligibility(db, company):
    pending = make_manual_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000201",
        description="Build reliable systems",
    )
    make_manual_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000202",
        description=None,
    )
    stale = make_manual_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000203",
        description="Changed facts",
        enriched_hash="b" * 64,
        enriched=True,
    )
    make_manual_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000204",
        description="Current facts",
        enriched_hash="a" * 64,
        enriched=True,
    )
    service = EnrichmentRunService(db)

    preview = service.inspect_pending_selection(
        filters=PendingJobFilters(source_sites=("manual",)),
        limit=50,
    )
    counts = service.get_job_queue_counts()

    assert set(preview.supported_job_ids) == {str(pending.id), str(stale.id)}
    assert counts["manual_pending_jobs"] == 2
    assert counts["needs_job_description"] == 1


@pytest.mark.asyncio
async def test_manual_filter_option_has_no_source_classification_paths(db, company):
    make_manual_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000205",
        description="Build reliable systems",
    )

    payload = await get_pending_filter_options_endpoint(db)

    manual = next(
        item for item in payload["sources"] if item["source_site"] == "manual"
    )
    assert manual["classification_paths"] == []
    assert manual["classifications"] == []


class _StubInsightExtractor:
    def __init__(self, experience, *, skills=None):
        self.experience = experience
        self.skills = [] if skills is None else skills

    async def extract(self, **_kwargs):
        return {
            "summary": "Fresh AI summary",
            "classification": {"code": "software-engineering"},
            "skills": self.skills,
            "confidence": 0.8,
            "experience": self.experience,
        }


class _StubCurrentSkillEnrichment:
    def __init__(self, _db):
        pass

    def build_job_context(self, _evidence):
        return SimpleNamespace(prompt_payload=[])

    def build_skill_prompt(self, **_kwargs):
        return []

    def assign_job_from_classification(self, **_kwargs):
        return {"state": "assigned"}

    def replace_job_skills(self, **_kwargs):
        return {"skills": []}


@pytest.mark.asyncio
async def test_ordinary_ai_enrichment_publishes_skills_without_starting_jev(
    db,
    company,
    monkeypatch,
):
    job = make_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000208",
    )
    job.description = "Python is required for this role."
    db.commit()
    replacements = []

    class RecordingSkillEnrichment(_StubCurrentSkillEnrichment):
        def replace_job_skills(self, **kwargs):
            replacements.append(kwargs)
            return {"skills": [{"skill_code": "backend.python"}]}

    monkeypatch.setattr(
        "app.services.ai_enrichment_service.CurrentSkillEnrichment",
        RecordingSkillEnrichment,
    )
    monkeypatch.setattr(
        "app.services.ai_enrichment_service.get_llm_status",
        lambda _scope: {"active_provider": "test", "active_model": "model"},
    )
    service = AIEnrichmentService()
    service.insight_extractor = _StubInsightExtractor(
        {
            "experience_level": "not_specified",
            "experience_min_years": None,
            "experience_max_years": None,
            "summary": "Not specified",
            "evidence": [],
        },
        skills=[{"name": "Python", "kind": "technical"}],
    )

    result = await service.enrich_job(job, db)

    assert result["status"] == "success"
    assert result["jev_skill_classification"] == {
        "status": "not_started",
        "reason": "manual_start_required",
        "apply_projection": False,
    }
    assert len(replacements) == 1
    assert replacements[0]["extracted_skills"] == [
        {"name": "Python", "kind": "technical"}
    ]
    assert replacements[0]["source"] == "ai-extraction"
    assert replacements[0]["provenance"] == {
        "method": "constrained-ai-extraction",
        "model": {"provider": "test", "name": "model"},
        "job_evidence_hash": "0" * 64,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "operator_fields",
        "stored_min",
        "stored_max",
        "extracted_min",
        "extracted_max",
        "expected_min",
        "expected_max",
        "expected_conflicts",
    ),
    [
        (
            ["title", "description"],
            None,
            None,
            2,
            4,
            2,
            4,
            [],
        ),
        (
            ["title", "description", "experience_min_years", "experience_max_years"],
            2,
            4,
            2,
            4,
            2,
            4,
            [],
        ),
        (
            ["title", "description", "experience_min_years", "experience_max_years"],
            3,
            5,
            1,
            2,
            3,
            5,
            [
                "AI suggested experience_min_years=1; operator-authored value preserved",
                "AI suggested experience_max_years=2; operator-authored value preserved",
            ],
        ),
    ],
)
async def test_manual_enrichment_preserves_operator_experience_and_fills_only_omitted_values(
    db,
    company,
    monkeypatch,
    operator_fields,
    stored_min,
    stored_max,
    extracted_min,
    extracted_max,
    expected_min,
    expected_max,
    expected_conflicts,
):
    job = make_manual_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000206",
        description="Build reliable systems",
        enriched_hash="b" * 64,
        enriched=True,
    )
    job.experience_min_years = stored_min
    job.experience_max_years = stored_max
    job.manual_evidence.operator_authored_fields = operator_fields
    db.commit()

    monkeypatch.setattr(
        "app.services.ai_enrichment_service.CurrentSkillEnrichment",
        _StubCurrentSkillEnrichment,
    )
    monkeypatch.setattr(
        "app.services.ai_enrichment_service.get_llm_status",
        lambda _scope: {},
    )
    service = AIEnrichmentService()
    service.insight_extractor = _StubInsightExtractor(
        {
            "experience_level": "mid",
            "experience_min_years": extracted_min,
            "experience_max_years": extracted_max,
            "summary": "Experience extracted",
            "evidence": ["Role description evidence"],
        }
    )

    result = await service.enrich_job(job, db)

    assert result["status"] == "success"
    assert job.experience_min_years == expected_min
    assert job.experience_max_years == expected_max
    assert job.experience_evidence == ["Role description evidence", *expected_conflicts]
    assert (
        job.manual_evidence.enriched_evidence_hash == job.manual_evidence.evidence_hash
    )


@pytest.mark.asyncio
async def test_failed_manual_enrichment_preserves_old_intelligence_and_stale_hash(
    db,
    company,
    monkeypatch,
):
    job = make_manual_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000207",
        description="Changed facts",
        enriched_hash="b" * 64,
        enriched=True,
    )
    old_enriched_at = datetime(2026, 7, 18, 13, 0)
    job.ai_summary = "Old intelligence"
    job.ai_enriched_at = old_enriched_at
    db.commit()

    class FailingSkillEnrichment(_StubCurrentSkillEnrichment):
        def replace_job_skills(self, **_kwargs):
            raise RuntimeError("skill replacement failed")

    monkeypatch.setattr(
        "app.services.ai_enrichment_service.CurrentSkillEnrichment",
        FailingSkillEnrichment,
    )
    monkeypatch.setattr(
        "app.services.ai_enrichment_service.get_llm_status",
        lambda _scope: {},
    )
    service = AIEnrichmentService()
    service.insight_extractor = _StubInsightExtractor(
        {
            "experience_level": "mid",
            "experience_min_years": 2,
            "experience_max_years": 4,
            "summary": "Experience extracted",
            "evidence": [],
        }
    )

    result = await service.enrich_job(job, db)

    assert result["status"] == "error"
    assert job.ai_summary == "Old intelligence"
    assert job.ai_enriched_at == old_enriched_at
    assert job.manual_evidence.enriched_evidence_hash == "b" * 64
    assert (
        job.manual_evidence.enriched_evidence_hash != job.manual_evidence.evidence_hash
    )


def test_pending_preview_and_create_do_not_gate_jobs_on_taxonomy_mapping(db, company):
    first = make_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000101",
        source_site="offertoday",
        source_classification_id="offertoday:103000",
        classification="Advertising & Media",
    )
    second = make_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000102",
        source_site="offertoday",
        source_classification_id="offertoday:113000",
        classification="Farming",
    )

    service = EnrichmentRunService(db)
    preview = service.preview_pending_jobs(filters=PendingJobFilters(), limit=50)

    assert preview["matching_pending_count"] == 2
    assert preview["effective_item_count"] == 2
    assert preview["excluded_item_count"] == 0
    assert preview["excluded_items"] == []

    run = service.create_manual_pending_run(limit=50)
    items = service.list_run_items(run.id)
    item_by_job_id = {item.job_id: item for item in items}

    assert run.total_items == 2
    assert run.pending_items == 2
    assert run.excluded_items == 0
    assert item_by_job_id[first.id].status == "pending"
    assert item_by_job_id[second.id].status == "pending"

    serialized = _serialize_single_run(run, db)
    assert serialized["excluded_items"] == 0
    assert serialized["excluded_details"] == []


def test_pending_preview_keeps_unmapped_authoritative_path_eligible(db, company):
    job = make_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000106",
        source_site="offertoday",
        source_classification_id="offertoday:103000",
        classification="Legacy scalar label",
    )

    add_source_path(db, job, ("offertoday:118000", "資訊科技"))
    preview = EnrichmentRunService(db).preview_pending_jobs(
        filters=PendingJobFilters(),
        limit=50,
    )

    assert preview["effective_item_count"] == 1
    assert preview["excluded_items"] == []


def test_persisted_exclusion_details_prefer_authoritative_path_identity(db, company):
    job = make_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000107",
        source_site="offertoday",
        source_classification_id="offertoday:103000",
        classification="Legacy scalar label",
    )
    add_source_path(db, job, ("offertoday:118000", "資訊科技"))
    run = make_run(
        db,
        run_id="run-authoritative-path",
        status="completed",
        created_at=datetime(2026, 7, 18, 12, 0),
        completed_at=datetime(2026, 7, 18, 12, 1),
        job_ids=[str(job.id)],
    )
    item = run.items[0]
    item.status = "excluded"
    item.error_message = "source_mapping_excluded"
    run.excluded_items = 1
    db.flush()

    assert _derive_excluded_details(db, [run.id])[run.id] == [
        {
            "source_classification_id": "offertoday:118000",
            "source_classification_name": "資訊科技",
            "count": 1,
            "reason": "source_mapping_excluded",
            "job_ids": [str(job.id)],
        }
    ]


def test_unmapped_pending_items_start_a_normal_worker_run(db, company):
    job = make_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000103",
        source_site="offertoday",
        source_classification_id="offertoday:129000",
        classification="Sport",
    )

    run = EnrichmentRunService(db).create_manual_pending_run(limit=50)

    assert run.status == "pending"
    assert run.total_items == 1
    assert run.pending_items == 1
    assert run.excluded_items == 0
    assert run.items[0].job_id == job.id
    assert run.items[0].status == "pending"


def test_execute_run_does_not_block_unmapped_job_before_worker_dispatch(db, company):
    job = make_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000105",
    )
    run = make_run(
        db,
        run_id="canonical-preflight-execution",
        status="running",
        created_at=datetime(2026, 7, 18, 12, 0),
        job_ids=[str(job.id)],
    )

    calls = 0

    class _SuccessfulEnrichmentService:
        async def enrich_job_id(self, _job_id):
            nonlocal calls
            calls += 1
            return {"status": "success", "job_id": str(_job_id)}

    service = EnrichmentRunService(db)
    service._resolve_run_concurrency = lambda: 1

    result = asyncio.run(
        service.execute_run(
            run.id,
            enrichment_service=_SuccessfulEnrichmentService(),
            claim=False,
        )
    )

    assert calls == 1
    assert result.status == "completed"
    assert result.excluded_items == 0
    assert result.items[0].status == "completed"


def test_jev_skill_backfill_run_uses_dedicated_executor_and_skips_standard_preflight(
    db, company
):
    job = make_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000106",
        projected=False,
        enriched=True,
    )
    run = make_run(
        db,
        run_id="jev-skill-backfill-execution",
        status="running",
        created_at=datetime(2026, 7, 18, 12, 0),
        job_ids=[str(job.id)],
    )
    run.source_type = "jev_skill_backfill"
    calls = []

    class _BackfillService:
        async def enrich_job_id(self, job_id):
            calls.append(job_id)
            return {"status": "success", "job_id": str(job_id)}

    class _WrongStandardService:
        async def enrich_job_id(self, _job_id):
            raise AssertionError("standard enrichment must not run for Jev backfill")

    service = EnrichmentRunService(db)
    service._resolve_run_concurrency = lambda: 1

    result = asyncio.run(
        service.execute_run(
            run.id,
            enrichment_service=_WrongStandardService(),
            backfill_service=_BackfillService(),
            claim=False,
        )
    )

    assert calls == [job.id]
    assert result.status == "completed"
    assert result.excluded_items == 0
    assert result.items[0].status == "completed"


def test_cancelled_jev_backfill_resumes_only_untouched_items_in_a_new_run(db, company):
    first = make_job(db, company, job_id="00000000-0000-0000-0000-000000000107")
    second = make_job(db, company, job_id="00000000-0000-0000-0000-000000000108")
    source = make_run(
        db,
        run_id="cancelled-jev-backfill",
        status="cancelled",
        created_at=datetime(2026, 7, 18, 12, 0),
        job_ids=[str(first.id), str(second.id)],
    )
    source.source_type = "jev_skill_backfill"
    source.pending_items = 0
    source.cancelled_items = 1
    source.items[0].status = "completed"
    source.items[1].status = "cancelled"
    db.flush()

    continuation = EnrichmentRunService(db).create_resume_run_from_cancelled_backfill(
        source.id
    )

    assert continuation.id != source.id
    assert continuation.source_type == "jev_skill_backfill"
    assert continuation.job_ids == [str(second.id)]
    assert continuation.run_snapshot["resumed_from_run_id"] == source.id
    assert source.items[0].status == "completed"
    assert source.items[1].status == "cancelled"


def test_public_routes_expose_filtered_controls_and_remove_single_job_endpoint():
    route_paths = {
        (route.path, method) for route in router.routes for method in route.methods
    }
    assert ("/api/ai/pending/filter-options", "GET") in route_paths
    assert ("/api/ai/pending/preview", "POST") in route_paths
    assert ("/api/ai/runs/{run_id}/stop", "POST") in route_paths
    assert not any(path == "/api/ai/enrich-job/{job_id}" for path, _ in route_paths)


def test_pending_eligibility_uses_source_attribute_projection_not_legacy_scalar(
    db,
    company,
):
    projected = make_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000104",
        classification=None,
        projected=True,
    )

    preview = EnrichmentRunService(db).preview_pending_jobs(
        filters=PendingJobFilters(),
        limit=50,
    )

    assert preview["matching_pending_count"] == 1
    assert preview["effective_item_count"] == 1
    run = EnrichmentRunService(db).create_manual_pending_run(limit=50)
    assert run.job_ids == [str(projected.id)]


def test_filters_use_or_within_fields_and_and_across_fields_with_inclusive_dates(
    db, company
):
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
        "selected_item_count": 1,
        "effective_item_count": 1,
        "excluded_item_count": 0,
        "excluded_items": [],
    }
    run = service.create_manual_pending_run(limit=50, filters=filters)
    assert run.job_ids == [str(matching.id)]


def test_source_qualified_filters_and_options_do_not_merge_duplicate_names(
    db,
    company,
):
    jobsdb_job = make_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000004",
        source_site="jobsdb",
        source_classification_id="legacy-jobsdb",
        classification="Information Technology",
        subclassification="Security",
    )
    add_source_path(
        db,
        jobsdb_job,
        ("jobsdb:6281", "Information Technology"),
        ("jobsdb:6287", "Security"),
    )
    ctgoodjobs_job = make_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000005",
        source_site="ctgoodjobs",
        source_classification_id="legacy-ctgoodjobs",
        classification="Information Technology",
        subclassification="Security",
    )
    add_source_path(
        db,
        ctgoodjobs_job,
        ("ctgoodjobs:021", "Information Technology"),
        ("ctgoodjobs:022", "Security"),
    )

    service = EnrichmentRunService(db)
    jobsdb_preview = service.preview_pending_jobs(
        filters=PendingJobFilters(source_classification_ids=("jobsdb:6281",)),
        limit=50,
    )
    assert jobsdb_preview["matching_pending_count"] == 1
    assert service._select_pending_jobs(
        filters=PendingJobFilters(source_subclassification_ids=("ctgoodjobs:022",)),
        limit=50,
    ) == [ctgoodjobs_job]

    payload = asyncio.run(get_pending_filter_options_endpoint(db))
    sources = {source["source_site"]: source for source in payload["sources"]}
    assert sources["jobsdb"]["classifications"] == [
        {
            "id": "jobsdb:6281",
            "source_site": "jobsdb",
            "name": "Information Technology",
            "subclassifications": ["Security"],
            "subclassification_options": [
                {
                    "id": "jobsdb:6287",
                    "source_site": "jobsdb",
                    "name": "Security",
                    "breadcrumb": "Information Technology / Security",
                }
            ],
        }
    ]
    assert sources["ctgoodjobs"]["classifications"][0]["id"] == "ctgoodjobs:021"
    assert sources["ctgoodjobs"]["classification_paths"][0]["nodes"] == [
        {
            "id": "ctgoodjobs:021",
            "name": "Information Technology",
            "source_position": 0,
        },
        {
            "id": "ctgoodjobs:022",
            "name": "Security",
            "source_position": 1,
        },
    ]


def test_candidate_query_excludes_ineligible_enriched_deleted_and_reserved_jobs(
    db, company
):
    eligible = make_job(db, company, job_id="00000000-0000-0000-0000-000000000010")
    reserved = make_job(db, company, job_id="00000000-0000-0000-0000-000000000011")
    make_job(
        db,
        company,
        job_id="00000000-0000-0000-0000-000000000012",
        classification=None,
        projected=False,
    )
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
    assert (
        service.preview_pending_jobs(filters=PendingJobFilters(), limit=50)[
            "matching_pending_count"
        ]
        == 1
    )
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
    service._update_item_finished(
        run.id, items[0].id, {"status": "error", "error": "bad output"}
    )
    finalized = service._finalize_stopping_run(service.get_run(run.id))
    assert finalized.status == "cancelled"
    assert finalized.pending_items == 0
    assert finalized.failed_items == 1
    assert finalized.cancelled_items == 1
    assert [item.status for item in service.list_run_items(run.id)] == [
        "failed",
        "cancelled",
    ]


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
    active = make_run(
        db, run_id="active", status="stopping", created_at=datetime(2026, 7, 18, 13, 0)
    )
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


def test_compact_run_projection_omits_job_ids_but_detail_projection_keeps_them(db):
    run = make_run(
        db,
        run_id="compact-projection",
        status="completed",
        created_at=datetime(2026, 7, 18, 14, 0),
        completed_at=datetime(2026, 7, 18, 14, 1),
        job_ids=[str(uuid.uuid4()), str(uuid.uuid4())],
    )

    compact = _serialize_runs([run], db, include_job_ids=False)[0]
    detail = _serialize_single_run(run, db)

    assert "job_ids" not in compact
    assert detail["job_ids"] == run.job_ids
