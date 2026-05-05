import sys
import uuid
import asyncio
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings
from app.database import Base
from app.models.app_runtime_settings import AppRuntimeSettings
from app.models import JobSkill, JobSkillMention, Skill, SkillCategory, SkillTechnology
from app.models.skill_review_candidate import SkillReviewCandidate
from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
from app.models.job import Job
from app.services.ai_runtime_settings_service import AIRuntimeSettingsService
from app.services.enrichment_run_service import EnrichmentRunService


if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"
if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):
    SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"


def _build_sqlite_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Job.__table__,
            AppRuntimeSettings.__table__,
            SkillCategory.__table__,
            SkillTechnology.__table__,
            Skill.__table__,
            JobSkill.__table__,
            SkillReviewCandidate.__table__,
            JobSkillMention.__table__,
            EnrichmentRun.__table__,
            EnrichmentRunItem.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    return Session()


def _create_job(
    db,
    *,
    source_classification_id,
    created_at,
    is_deleted=False,
    ai_enriched_at=None,
    source_subclassification_name=None,
    title="Test Job",
):
    job = Job(
        id=uuid.uuid4(),
        job_id=str(uuid.uuid4()),
        source_site="jobsdb",
        company_id=uuid.uuid4(),
        title=title,
        description="Test Description",
        source_classification_id=source_classification_id,
        source_classification_name="Information & Communication Technology"
        if source_classification_id
        else None,
        source_subclassification_name=source_subclassification_name,
        is_deleted=is_deleted,
        ai_enriched_at=ai_enriched_at,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(job)
    db.commit()
    return job


def _create_run_with_items(
    db,
    *,
    jobs,
    item_statuses,
    created_at,
    source_type="manual_pending",
    run_status="completed_with_failures",
):
    run = EnrichmentRun(
        source_type=source_type,
        status=run_status,
        job_ids=[str(job.id) for job in jobs],
        total_items=len(jobs),
        pending_items=sum(1 for status in item_statuses if status == "pending"),
        completed_items=sum(1 for status in item_statuses if status == "completed"),
        failed_items=sum(1 for status in item_statuses if status == "failed"),
        created_at=created_at,
        started_at=created_at,
        completed_at=created_at,
    )
    db.add(run)
    db.flush()

    for position, (job, status) in enumerate(zip(jobs, item_statuses)):
        db.add(
            EnrichmentRunItem(
                run_id=run.id,
                job_id=job.id,
                position=position,
                status=status,
                created_at=created_at,
                started_at=created_at,
                completed_at=created_at,
                error_message=f"{status} {job.id}" if status == "failed" else None,
            )
        )

    db.commit()
    return run


def test_create_manual_pending_run_skips_jobs_missing_source_classification():
    db = _build_sqlite_session()
    try:
        expected_job = _create_job(
            db,
            source_classification_id="6281",
            created_at=datetime(2026, 4, 30, 1, 0, 0),
        )
        _create_job(
            db,
            source_classification_id="",
            created_at=datetime(2026, 4, 30, 0, 0, 0),
        )
        _create_job(
            db,
            source_classification_id=None,
            created_at=datetime(2026, 4, 30, 2, 0, 0),
        )

        run = EnrichmentRunService(db).create_manual_pending_run(limit=10)

        assert run is not None
        assert run.total_items == 1
        assert run.job_ids == [str(expected_job.id)]
    finally:
        db.close()


def _create_skill_hierarchy(db, *, category_name, technology_name, skill_name):
    category = SkillCategory(
        id=uuid.uuid4(),
        name=category_name,
        created_by="seed",
        is_auto_created=False,
    )
    technology = SkillTechnology(
        id=uuid.uuid4(),
        category_id=category.id,
        name=technology_name,
        created_by="seed",
        is_auto_created=False,
    )
    skill = Skill(
        id=uuid.uuid4(),
        technology_id=technology.id,
        name=skill_name,
        created_by="seed",
        is_auto_created=False,
    )
    db.add_all([category, technology, skill])
    db.commit()
    return skill


def _create_review_candidate(db, *, raw_name, normalized_name, occurrence_count=1):
    candidate = SkillReviewCandidate(
        id=uuid.uuid4(),
        raw_name=raw_name,
        normalized_name=normalized_name,
        occurrence_count=occurrence_count,
    )
    db.add(candidate)
    db.commit()
    return candidate


def _create_review_mention(db, *, job_id, review_candidate_id, raw_name, normalized_name):
    mention = JobSkillMention(
        id=uuid.uuid4(),
        job_id=job_id,
        raw_name=raw_name,
        normalized_name=normalized_name,
        resolution="review_candidate",
        review_candidate_id=review_candidate_id,
        source="ai",
    )
    db.add(mention)
    db.commit()
    return mention


def _create_job_skill(db, *, job_id, skill_id):
    db.add(
        JobSkill(
            job_id=job_id,
            skill_id=skill_id,
            source="ai",
            confidence=0.9,
            created_at=datetime(2026, 4, 30, 12, 0, 0),
        )
    )
    db.commit()


def test_create_manual_query_run_requires_selector():
    db = _build_sqlite_session()
    try:
        with pytest.raises(ValueError, match="At least one query selector is required"):
            EnrichmentRunService(db).create_manual_query_run(
                review_candidate_names=None,
                polluted_skill_names=None,
                source_subclassification_names=None,
            )
    finally:
        db.close()


def test_create_manual_query_run_selects_union_and_applies_scope_and_subclassification():
    db = _build_sqlite_session()
    try:
        selected_review_job = _create_job(
            db,
            source_classification_id="6281",
            source_subclassification_name="Networks & Systems Administration",
            ai_enriched_at=datetime(2026, 4, 30, 12, 0, 0),
            created_at=datetime(2026, 4, 30, 1, 0, 0),
            title="Review Candidate Job",
        )
        selected_polluted_job = _create_job(
            db,
            source_classification_id="6281",
            source_subclassification_name="Networks & Systems Administration",
            ai_enriched_at=datetime(2026, 4, 30, 13, 0, 0),
            created_at=datetime(2026, 4, 30, 2, 0, 0),
            title="Polluted Skill Job",
        )
        _create_job(
            db,
            source_classification_id="6281",
            source_subclassification_name="Help Desk & IT Support",
            ai_enriched_at=datetime(2026, 4, 30, 14, 0, 0),
            created_at=datetime(2026, 4, 30, 3, 0, 0),
            title="Wrong Subclassification Job",
        )
        not_enriched_job = _create_job(
            db,
            source_classification_id="6281",
            source_subclassification_name="Networks & Systems Administration",
            ai_enriched_at=None,
            created_at=datetime(2026, 4, 30, 4, 0, 0),
            title="Unenriched Polluted Job",
        )

        dns_candidate = _create_review_candidate(
            db,
            raw_name="DNS",
            normalized_name="dns",
            occurrence_count=2,
        )
        _create_review_mention(
            db,
            job_id=selected_review_job.id,
            review_candidate_id=dns_candidate.id,
            raw_name="DNS",
            normalized_name="dns",
        )

        polluted_skill = _create_skill_hierarchy(
            db,
            category_name="Other",
            technology_name="General",
            skill_name="Legacy Polluted Skill",
        )
        _create_job_skill(db, job_id=selected_polluted_job.id, skill_id=polluted_skill.id)
        _create_job_skill(db, job_id=not_enriched_job.id, skill_id=polluted_skill.id)

        run = EnrichmentRunService(db).create_manual_query_run(
            review_candidate_names=["DNS"],
            polluted_skill_names=["Legacy Polluted Skill"],
            source_subclassification_names=["Networks & Systems Administration"],
            scope="enriched_only",
        )

        assert run is not None
        assert run.source_type == "manual_query"
        assert run.total_items == 2
        assert run.job_ids == [str(selected_review_job.id), str(selected_polluted_job.id)]
    finally:
        db.close()


def test_get_overview_counts_only_latest_unrecovered_failed_jobs():
    db = _build_sqlite_session()
    try:
        counted_job = _create_job(
            db,
            source_classification_id="6281",
            created_at=datetime(2026, 5, 1, 9, 0, 0),
            title="Counted Failed Job",
        )
        duplicate_failed_job = _create_job(
            db,
            source_classification_id="6281",
            created_at=datetime(2026, 5, 1, 9, 5, 0),
            title="Duplicate Failed Job",
        )
        retrying_job = _create_job(
            db,
            source_classification_id="6281",
            created_at=datetime(2026, 5, 1, 9, 10, 0),
            title="Retrying Job",
        )
        recovered_job = _create_job(
            db,
            source_classification_id="6281",
            created_at=datetime(2026, 5, 1, 9, 15, 0),
            title="Recovered Job",
            ai_enriched_at=datetime(2026, 5, 1, 11, 0, 0),
        )
        deleted_job = _create_job(
            db,
            source_classification_id="6281",
            created_at=datetime(2026, 5, 1, 9, 20, 0),
            title="Deleted Failed Job",
            is_deleted=True,
        )

        _create_run_with_items(
            db,
            jobs=[counted_job],
            item_statuses=["failed"],
            created_at=datetime(2026, 5, 1, 10, 0, 0),
            run_status="failed",
        )
        _create_run_with_items(
            db,
            jobs=[duplicate_failed_job],
            item_statuses=["failed"],
            created_at=datetime(2026, 5, 1, 10, 5, 0),
            run_status="failed",
        )
        _create_run_with_items(
            db,
            jobs=[duplicate_failed_job],
            item_statuses=["failed"],
            created_at=datetime(2026, 5, 1, 10, 10, 0),
            run_status="failed",
        )
        _create_run_with_items(
            db,
            jobs=[retrying_job],
            item_statuses=["failed"],
            created_at=datetime(2026, 5, 1, 10, 15, 0),
            run_status="failed",
        )
        _create_run_with_items(
            db,
            jobs=[retrying_job],
            item_statuses=["pending"],
            created_at=datetime(2026, 5, 1, 10, 20, 0),
            run_status="pending",
        )
        _create_run_with_items(
            db,
            jobs=[recovered_job],
            item_statuses=["failed"],
            created_at=datetime(2026, 5, 1, 10, 25, 0),
            run_status="failed",
        )
        _create_run_with_items(
            db,
            jobs=[deleted_job],
            item_statuses=["failed"],
            created_at=datetime(2026, 5, 1, 10, 30, 0),
            run_status="failed",
        )

        overview = EnrichmentRunService(db).get_overview()

        assert overview["failed_jobs"] == 2
        assert overview["failed_items"] == 6
    finally:
        db.close()


class _RecordingRunEnrichmentService:
    def __init__(self):
        self.started_job_ids = []
        self.completed_job_ids = []
        self.active_jobs = 0
        self.max_active_jobs = 0
        self.event = asyncio.Event()

    async def enrich_job_id(self, job_id):
        self.started_job_ids.append(str(job_id))
        self.active_jobs += 1
        self.max_active_jobs = max(self.max_active_jobs, self.active_jobs)
        try:
            await self.event.wait()
            self.completed_job_ids.append(str(job_id))
            return {"job_id": str(job_id), "status": "success"}
        finally:
            self.active_jobs -= 1


class _MixedOutcomeRunEnrichmentService:
    def __init__(self, failing_job_ids):
        self.failing_job_ids = {str(job_id) for job_id in failing_job_ids}
        self.started_job_ids = []

    async def enrich_job_id(self, job_id):
        self.started_job_ids.append(str(job_id))
        if str(job_id) in self.failing_job_ids:
            return {
                "job_id": str(job_id),
                "status": "error",
                "error": f"failed {job_id}",
            }
        return {"job_id": str(job_id), "status": "success"}


@pytest.mark.asyncio
async def test_execute_run_uses_persisted_effective_concurrency_and_updates_monitor_fields(
    monkeypatch,
):
    db = _build_sqlite_session()
    try:
        monkeypatch.setattr(settings, "llm_provider", "mock")
        monkeypatch.setattr(settings, "ai_enrichment_run_concurrency", 5)
        AIRuntimeSettingsService(db).update_settings(
            {
                "ai_enrichment_run_concurrency": 3,
            }
        )
        jobs = [
            _create_job(
                db,
                source_classification_id="6281",
                created_at=datetime(2026, 4, 30, 1, index, 0),
                title=f"Concurrent Job {index + 1}",
            )
            for index in range(4)
        ]
        run = EnrichmentRunService(db).create_manual_batch_run([str(job.id) for job in jobs])
        assert run is not None
        db.commit()

        service = _RecordingRunEnrichmentService()

        task = asyncio.create_task(
            EnrichmentRunService(db).execute_run(run.id, enrichment_service=service)
        )

        for _ in range(50):
            await asyncio.sleep(0)
            db.expire_all()
            persisted_run = EnrichmentRunService(db).get_run(run.id)
            if persisted_run and persisted_run.pending_items == 1 and persisted_run.completed_items == 0:
                break
        else:
            pytest.fail("run did not reach expected concurrent in-flight state")

        assert service.max_active_jobs == 3

        db.expire_all()
        persisted_run = EnrichmentRunService(db).get_run(run.id)
        assert persisted_run is not None
        assert persisted_run.status == "running"
        assert persisted_run.pending_items == 1
        assert persisted_run.completed_items == 0
        assert persisted_run.failed_items == 0
        assert persisted_run.current_job_title == "Concurrent Job 3"

        running_items = EnrichmentRunService(db).list_run_items(run.id, status="running")
        assert len(running_items) == 3

        service.event.set()
        await task

        db.expire_all()
        persisted_run = EnrichmentRunService(db).get_run(run.id)
        assert persisted_run is not None
        assert persisted_run.status == "completed"
        assert persisted_run.pending_items == 0
        assert persisted_run.completed_items == 4
        assert persisted_run.failed_items == 0
        assert persisted_run.current_job_title is None

        completed_items = EnrichmentRunService(db).list_run_items(run.id, status="completed")
        assert len(completed_items) == 4
    finally:
        db.close()


@pytest.mark.asyncio
async def test_execute_run_snapshots_concurrency_when_runtime_settings_change_mid_run(
    monkeypatch,
):
    db = _build_sqlite_session()
    try:
        monkeypatch.setattr(settings, "llm_provider", "mock")
        monkeypatch.setattr(settings, "ai_enrichment_run_concurrency", 5)
        runtime_settings = AIRuntimeSettingsService(db)
        runtime_settings.update_settings(
            {
                "ai_enrichment_run_concurrency": 2,
            }
        )

        jobs = [
            _create_job(
                db,
                source_classification_id="6281",
                created_at=datetime(2026, 4, 30, 5, index, 0),
                title=f"Snapshot Job {index + 1}",
            )
            for index in range(4)
        ]
        run = EnrichmentRunService(db).create_manual_batch_run([str(job.id) for job in jobs])
        assert run is not None
        db.commit()

        service = _RecordingRunEnrichmentService()
        task = asyncio.create_task(
            EnrichmentRunService(db).execute_run(run.id, enrichment_service=service)
        )

        for _ in range(50):
            await asyncio.sleep(0)
            if service.max_active_jobs == 2:
                break
        else:
            pytest.fail("run did not start with the persisted worker count")

        runtime_settings.update_settings(
            {
                "ai_enrichment_run_concurrency": 4,
            }
        )

        for _ in range(20):
            await asyncio.sleep(0)

        assert service.max_active_jobs == 2

        service.event.set()
        await task

        next_run = EnrichmentRunService(db).create_manual_batch_run([str(job.id) for job in jobs])
        assert next_run is not None

        next_service = _RecordingRunEnrichmentService()
        next_task = asyncio.create_task(
            EnrichmentRunService(db).execute_run(next_run.id, enrichment_service=next_service)
        )

        for _ in range(50):
            await asyncio.sleep(0)
            if next_service.max_active_jobs == 4:
                break
        else:
            pytest.fail("new run did not pick up the updated persisted worker count")

        assert next_service.max_active_jobs == 4
        next_service.event.set()
        await next_task
    finally:
        db.close()


@pytest.mark.asyncio
async def test_execute_run_marks_failed_items_and_terminal_status_with_mixed_worker_outcomes(monkeypatch):
    db = _build_sqlite_session()
    try:
        jobs = [
            _create_job(
                db,
                source_classification_id="6281",
                created_at=datetime(2026, 4, 30, 2, index, 0),
                title=f"Outcome Job {index + 1}",
            )
            for index in range(3)
        ]
        run = EnrichmentRunService(db).create_manual_batch_run([str(job.id) for job in jobs])
        assert run is not None
        db.commit()

        monkeypatch.setattr(settings, "ai_enrichment_run_concurrency", 3)
        service = _MixedOutcomeRunEnrichmentService([jobs[1].id])

        await EnrichmentRunService(db).execute_run(run.id, enrichment_service=service)

        db.expire_all()
        persisted_run = EnrichmentRunService(db).get_run(run.id)
        assert persisted_run is not None
        assert persisted_run.status == "completed_with_failures"
        assert persisted_run.pending_items == 0
        assert persisted_run.completed_items == 2
        assert persisted_run.failed_items == 1
        assert persisted_run.error_message == "1 item(s) failed"
        assert persisted_run.current_job_title is None

        items = EnrichmentRunService(db).list_run_items(run.id)
        failed_items = [item for item in items if item.status == "failed"]
        completed_items = [item for item in items if item.status == "completed"]
        assert len(failed_items) == 1
        assert len(completed_items) == 2
        assert failed_items[0].error_message == f"failed {jobs[1].id}"
    finally:
        db.close()
