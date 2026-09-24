from __future__ import annotations

from datetime import date, datetime
import inspect
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.ai.system_one import ChoiceAnswer, ScoreAnswer, SystemOneResult, SystemOneUsage
from app.database import Base
from app.api.jev_operations import JevOperationSelectionRequest
from app.models.company import Company
from app.models.job import Job
from app.models.jev import JevDuplicateAssociation, JevOperationBatchItem
from app.services.jev_duplicate_association import JevDuplicateAssociationService
from app.services.jev_operation_batch import (
    JevOperationBatchService,
    execute_jev_operation_batch,
)
from app.services.jev_related_jobs import JevRelatedJobsService
from app.services.jev_runtime_settings_service import JevRuntimeSettingsService
import app.models  # noqa: F401
from scripts.bootstrap_db import bootstrap_database


def _session():
    database_url = os.getenv("JEV_OPERATIONS_TEST_DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("disposable Jev operations PostgreSQL URL is not configured")
    parsed_url = make_url(database_url)
    if parsed_url.get_backend_name() != "postgresql":
        raise RuntimeError("JEV_OPERATIONS_TEST_DATABASE_URL must use PostgreSQL")
    if not (make_url(database_url).database or "").endswith("_test"):
        raise RuntimeError("JEV_OPERATIONS_TEST_DATABASE_URL must end in _test")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    bootstrap_database(db_engine=engine, metadata=Base.metadata)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    settings = JevRuntimeSettingsService(db)
    settings.get_or_create()
    settings.update(
        {
            "enabled": True,
            "api_key": "test-secret",
        }
    )
    company = Company(
        company_id="jev-operations-company",
        source_site="jobsdb",
        source_company_id="jev-operations-company",
        name="Operations Company",
    )
    subject = Job(
        id=uuid.uuid4(),
        job_id="operations-subject",
        source_site="jobsdb",
        source_job_id="operations-subject",
        company=company,
        title="Platform Engineer",
        description="Build Python platforms.",
        is_deleted=False,
    )
    candidate = Job(
        id=uuid.uuid4(),
        job_id="operations-candidate",
        source_site="ctgoodjobs",
        source_job_id="operations-candidate",
        company=company,
        title="Backend Engineer",
        description="Build related backend services.",
        is_deleted=False,
    )
    db.add_all((subject, candidate))
    db.commit()
    return engine, db, subject, candidate


def _dispose(db, engine) -> None:
    db.close()
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()


def _recommendation(candidate: Job) -> dict[str, object]:
    return {
        "id": candidate.id,
        "job_id": candidate.job_id,
        "title": candidate.title,
        "company_name": candidate.company.name,
        "location": candidate.location,
        "employment_types": [],
        "posted_date": None,
        "job_intelligence_availability": {
            "source_attributes": {"available": False, "unavailable_code": "not_projected"},
            "skills": {"available": False, "unavailable_code": "not_projected"},
        },
        "semantic_score": 0.9,
        "skill_overlap_score": 0.0,
        "freshness_score": 0.0,
        "combined_score": 0.72,
    }


class _Request:
    source_sites = ["jobsdb"]
    keyword = None
    job_ids = []
    posted_date_from = None
    posted_date_to = None
    processing_status = "all"
    job_offset = 0
    max_jobs = 10
    execution_batch_size = 5
    start_execution_batch = 1
    operations = ["duplicate"]
    force_reevaluation = False


class _TwoJobRequest(_Request):
    source_sites = []


def test_background_batch_entry_point_is_synchronous_for_threadpool_isolation() -> None:
    assert not inspect.iscoroutinefunction(execute_jev_operation_batch)


def test_operation_scope_accepts_inclusive_posted_date_window() -> None:
    request = JevOperationSelectionRequest(
        posted_date_from="2026-09-01",
        posted_date_to="2026-09-30",
        operations=["skills"],
    )

    assert request.posted_date_from == date(2026, 9, 1)
    assert request.posted_date_to == date(2026, 9, 30)
    assert request.job_offset == 0
    assert request.execution_batch_size == 500
    assert request.start_execution_batch == 1


def test_operation_scope_has_no_application_job_count_ceiling() -> None:
    request = JevOperationSelectionRequest(
        max_jobs=25_000,
        job_offset=2_000_000,
        execution_batch_size=500,
        start_execution_batch=9,
        operations=["skills", "duplicate", "related_jobs"],
    )

    assert request.max_jobs == 25_000
    assert request.job_offset == 2_000_000
    assert request.execution_batch_size == 500
    assert request.start_execution_batch == 9

    unlimited = JevOperationSelectionRequest(
        max_jobs=None,
        operations=["skills", "duplicate", "related_jobs"],
    )
    assert unlimited.max_jobs is None


def test_operation_scope_rejects_a_start_batch_outside_a_bounded_scope() -> None:
    with pytest.raises(
        ValueError,
        match="start_execution_batch must fall within the maximum matching Jobs",
    ):
        JevOperationSelectionRequest(
            max_jobs=4_000,
            execution_batch_size=500,
            start_execution_batch=9,
            operations=["skills"],
        )


def test_operation_scope_rejects_reversed_posted_date_window() -> None:
    with pytest.raises(ValueError, match="posted_date_from must be on or before"):
        JevOperationSelectionRequest(
            posted_date_from="2026-09-30",
            posted_date_to="2026-09-01",
            operations=["skills"],
        )


def test_preview_is_provider_free_and_start_is_idempotent() -> None:
    engine, db, subject, _candidate = _session()
    try:
        service = JevOperationBatchService(db)
        preview = service.preview(_Request())

        assert preview["selected_job_ids"] == [str(subject.id)]
        assert preview["operations"]["duplicate"]["eligible"] == 1
        assert "cost_ceiling_microdollars" not in preview
        assert db.execute(text("SELECT count(*) FROM jev_runs")).scalar_one() == 0

        batch = service.start(
            _Request(),
            preview_fingerprint=preview["preview_fingerprint"],
            idempotency_key="one-manual-start",
        )
        replay = service.start(
            _Request(),
            preview_fingerprint=preview["preview_fingerprint"],
            idempotency_key="one-manual-start",
        )
        assert replay.id == batch.id
        assert [(item.operation, item.status) for item in batch.items] == [
            ("duplicate", "pending")
        ]
    finally:
        _dispose(db, engine)


def test_direct_start_freezes_scope_and_defers_expensive_eligibility() -> None:
    engine, db, subject, _candidate = _session()
    try:
        service = JevOperationBatchService(db)
        batch = service.start(
            _Request(),
            preview_fingerprint=None,
            idempotency_key="direct-manual-start",
        )

        assert batch.selected_job_ids == [str(subject.id)]
        assert [(item.operation, item.status, item.eligibility_reason) for item in batch.items] == [
            ("duplicate", "pending", "deferred")
        ]
        assert db.execute(text("SELECT count(*) FROM jev_runs")).scalar_one() == 0
    finally:
        _dispose(db, engine)


def test_interrupted_batch_is_stopped_without_dispatch_and_requires_resume() -> None:
    engine, db, _subject, _candidate = _session()
    try:
        service = JevOperationBatchService(db)
        preview = service.preview(_Request())
        batch = service.start(
            _Request(),
            preview_fingerprint=preview["preview_fingerprint"],
            idempotency_key="restart-test",
        )
        batch.status = "running"
        batch.items[0].status = "running"
        db.commit()

        assert service.recover_interrupted() == 1
        assert batch.status == "stopped"
        assert batch.items[0].status == "stopped"
        assert db.execute(text("SELECT count(*) FROM jev_runs")).scalar_one() == 0

        resumed = service.resume(batch.id)
        assert resumed.status == "pending"
        assert resumed.items[0].status == "pending"
    finally:
        _dispose(db, engine)


class _ScoreEvaluator:
    def __init__(self, score: int | None):
        self.score = score

    async def evaluate(self, request):
        answers = {}
        if self.score is not None:
            answers = {
                name: ScoreAnswer(
                    type="score",
                    score=self.score,
                    confidence=0.95,
                    legend={0: "not related", 1: "loose", 2: "related", 3: "strong"},
                    probabilities={0: 0.01, 1: 0.01, 2: 0.03, 3: 0.95},
                )
                for name in request.questions
            }
        return SystemOneResult(
            status="answered",
            request_id="related-request",
            model="jev-latest",
            provider="fake",
            answers=answers,
            usage=SystemOneUsage(input_tokens=50, output_tokens=5, cost=0.001),
            latency_ms=5,
        )


class _DuplicateEvaluator:
    async def evaluate(self, request):
        return SystemOneResult(
            status="answered",
            request_id="duplicate-request",
            model="jev-latest",
            provider="fake",
            answers={
                "decision": ChoiceAnswer(
                    type="choice",
                    choice="same_vacancy",
                    confidence=0.95,
                    probabilities={
                        "same_vacancy": 0.95,
                        "different_vacancy": 0.03,
                        "insufficient": 0.02,
                    },
                )
            },
            usage=SystemOneUsage(input_tokens=50, output_tokens=5, cost=0.001),
            latency_ms=5,
        )


@pytest.mark.asyncio
async def test_duplicate_force_reevaluation_preserves_same_evidence_history() -> None:
    engine, db, subject, _candidate = _session()
    try:
        service = JevDuplicateAssociationService(db)
        first = service.start_for_job(subject.id, candidate_limit=1)
        assert first.run_id is not None
        await service.execute(first.run_id, evaluator=_DuplicateEvaluator())
        db.commit()

        skipped = service.start_for_job(subject.id, candidate_limit=1)
        assert skipped.run_id is None
        assert skipped.skipped_current_count == 1

        forced = service.start_for_job(subject.id, candidate_limit=1, force=True)
        assert forced.run_id is not None
        await service.execute(forced.run_id, evaluator=_DuplicateEvaluator())
        db.commit()

        rows = list(
            db.query(JevDuplicateAssociation)
            .order_by(JevDuplicateAssociation.attempt_generation)
            .all()
        )
        assert [row.attempt_generation for row in rows] == [1, 2]
        assert [row.jev_run_id for row in rows] == [first.run_id, forced.run_id]
    finally:
        _dispose(db, engine)


@pytest.mark.asyncio
async def test_related_jobs_persists_success_and_changed_evidence_uses_labeled_fallback(
    monkeypatch,
) -> None:
    engine, db, subject, candidate = _session()
    try:
        baseline = [_recommendation(candidate)]
        monkeypatch.setattr(
            "app.services.jev_related_jobs.JobRecommendationService.recommend_for_job",
            lambda _service, _job_id, limit: baseline[:limit],
        )
        service = JevRelatedJobsService(db)
        evaluation = service.start(subject.id)
        db.commit()
        evaluation = await service.execute(
            evaluation.id,
            evaluator=_ScoreEvaluator(3),
        )
        db.commit()

        current = service.read(subject.id)
        assert current["jev_status"] == "evaluated"
        assert current["recommendations"][0]["jev_reason"] == (
            "Strong related alternative"
        )

        subject.title = "Changed Platform Lead"
        subject.updated_at = datetime(2026, 9, 24, 12, 0)
        db.commit()
        stale = service.read(subject.id)
        assert stale["jev_status"] == "awaiting_reevaluation"
        assert stale["recommendations"][0]["id"] == str(candidate.id)
        assert stale["recommendations"][0]["job_id"] == candidate.job_id
    finally:
        _dispose(db, engine)


def test_retry_failed_only_requeues_failed_items() -> None:
    engine, db, _subject, _candidate = _session()
    try:
        service = JevOperationBatchService(db)
        preview = service.preview(_Request())
        batch = service.start(
            _Request(),
            preview_fingerprint=preview["preview_fingerprint"],
            idempotency_key="retry-test",
        )
        batch.items[0].status = "failed"
        extra = JevOperationBatchItem(
            batch_id=batch.id,
            job_id=batch.items[0].job_id,
            operation="related_jobs",
            position=1,
            status="completed",
            eligibility_reason="eligible",
        )
        db.add(extra)
        db.commit()
        db.expire(batch, ["items"])

        retried = service.retry_failed(batch.id)
        assert [item.status for item in retried.items] == ["pending", "completed"]
    finally:
        _dispose(db, engine)


@pytest.mark.asyncio
async def test_partial_failure_continues_independent_items(monkeypatch) -> None:
    engine, db, _subject, _candidate = _session()
    try:
        service = JevOperationBatchService(db)
        preview = service.preview(_TwoJobRequest())
        batch = service.start(
            _TwoJobRequest(),
            preview_fingerprint=preview["preview_fingerprint"],
            idempotency_key="partial-failure-test",
        )
        calls = []

        async def execute_item(item, *, force):
            calls.append((item.job_id, force))
            if len(calls) == 1:
                raise RuntimeError("isolated failure")
            return {"status": "completed"}

        monkeypatch.setattr(service, "_execute_item", execute_item)
        completed = await service.execute(batch.id)

        assert completed.status == "completed_with_failures"
        assert completed.failed_items == 1
        assert completed.completed_items == 1
        assert len(calls) == 2
    finally:
        _dispose(db, engine)


@pytest.mark.asyncio
async def test_stop_after_dispatched_item_prevents_next_item(monkeypatch) -> None:
    engine, db, _subject, _candidate = _session()
    try:
        service = JevOperationBatchService(db)
        preview = service.preview(_TwoJobRequest())
        batch = service.start(
            _TwoJobRequest(),
            preview_fingerprint=preview["preview_fingerprint"],
            idempotency_key="stop-test",
        )
        calls = []

        async def execute_item(item, *, force):
            calls.append((item.job_id, force))
            service.request_stop(batch.id)
            db.commit()
            return {"status": "completed"}

        monkeypatch.setattr(service, "_execute_item", execute_item)
        stopped = await service.execute(batch.id)

        assert stopped.status == "stopped"
        assert stopped.completed_items == 1
        assert [item.status for item in stopped.items] == ["completed", "stopped"]
        assert len(calls) == 1
    finally:
        _dispose(db, engine)
