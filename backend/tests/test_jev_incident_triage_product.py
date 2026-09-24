from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.ai.system_one import ChoiceAnswer, SystemOneResult, SystemOneUsage
from app.database import Base
import app.models  # noqa: F401
from app.models.crawl_job import CrawlJob, CrawlJobEvent
from app.models.jev import JevRun
from app.services.jev_incident_triage_product import JevIncidentTriageProductService
from app.services.jev_runtime_settings_service import JevRuntimeSettingsService
from scripts.bootstrap_db import bootstrap_database


def _session():
    database_url = os.getenv("JEV_INCIDENT_TRIAGE_TEST_DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("disposable Jev incident-triage PostgreSQL URL is not configured")
    parsed_url = make_url(database_url)
    if parsed_url.get_backend_name() != "postgresql":
        raise RuntimeError("JEV_INCIDENT_TRIAGE_TEST_DATABASE_URL must use PostgreSQL")
    if not (make_url(database_url).database or "").endswith("_test"):
        raise RuntimeError("JEV_INCIDENT_TRIAGE_TEST_DATABASE_URL must end in _test")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    bootstrap_database(db_engine=engine, metadata=Base.metadata)
    db = sessionmaker(bind=engine, autoflush=False)()
    settings = JevRuntimeSettingsService(db).get_or_create()
    settings.enabled = True
    settings.api_key = "test-secret"
    settings.incident_triage_enabled = True
    settings.incident_triage_event_limit = 100
    job = CrawlJob(
        id=uuid.uuid4(),
        source_site="jobsdb",
        trigger_type="manual",
        status="failed",
        request_payload={"crawl_phase": "detail"},
        error_message="Failed at https://secret.invalid/jobs/123 token=top-secret",
    )
    db.add(job)
    db.flush()
    for sequence in range(1, 4):
        db.add(
            CrawlJobEvent(
                crawl_job_id=job.id,
                sequence_no=sequence,
                event_type="crawl.failed",
                payload={
                    "error": (
                        f"Failed at https://secret.invalid/jobs/{sequence} "
                        f"Authorization: Bearer secret-{sequence}"
                    ),
                    "stage": "Authorization: Bearer stage-secret",
                    "code": "password=code-secret",
                },
                emitted_by="test",
            )
        )
    db.commit()
    return engine, db, job.id


def _dispose(engine, db):
    db.close()
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()


class _Evaluator:
    def __init__(self, *, unavailable=False):
        self.unavailable = unavailable
        self.requests = []

    async def evaluate(self, request):
        self.requests.append(request)
        if self.unavailable:
            return SystemOneResult(status="unavailable", error_code="http_503")
        return SystemOneResult(
            status="answered",
            request_id="incident-request-1",
            model="jev-incident-resolved",
            provider="local-test",
            answers={
                name: ChoiceAnswer(
                    type="choice",
                    choice="investigate_now",
                    confidence=0.97,
                    probabilities={"investigate_now": 0.97, "insufficient": 0.03},
                )
                for name in request.questions
            },
            usage=SystemOneUsage(input_tokens=40, output_tokens=5, cost=0.00002),
        )


def test_preview_is_free_secret_safe_and_preserves_all_event_references() -> None:
    engine, db, job_id = _session()
    try:
        service = JevIncidentTriageProductService(db)
        evaluation = service.preview(event_limit=100)
        db.commit()
        payload = service.serialize(evaluation)

        assert payload["total_event_count"] == 3
        assert payload["selected_cluster_count"] == 1
        cluster = payload["clusters"][0]
        assert cluster["event_count"] == 3
        assert len(cluster["event_refs"]) == 3
        assert "secret.invalid" not in cluster["normalized_symptom"]
        assert "secret-" not in cluster["normalized_symptom"]
        assert "[url]" in cluster["normalized_symptom"]
        assert "[credential]" in cluster["normalized_symptom"]
        assert cluster["issue_code"] is None
        assert cluster["issue_stage"] is None
        assert db.query(JevRun).count() == 0
        assert db.get(CrawlJob, job_id).status == "failed"
        assert db.query(CrawlJobEvent).count() == 3
    finally:
        _dispose(engine, db)


@pytest.mark.asyncio
async def test_evaluate_adds_advice_and_receipt_without_crawl_mutation() -> None:
    engine, db, job_id = _session()
    try:
        service = JevIncidentTriageProductService(db)
        evaluation = service.preview(event_limit=100)
        evaluator = _Evaluator()
        await service.execute(evaluation.id, evaluator=evaluator)
        db.commit()
        payload = service.serialize(evaluation)

        assert payload["status"] == "completed"
        assert payload["request_id"] == "incident-request-1"
        assert payload["clusters"][0]["disposition"] == "investigate_now"
        assert len(evaluator.requests) == 1
        rendered_request = evaluator.requests[0].model_dump_json()
        assert "stage-secret" not in rendered_request
        assert "code-secret" not in rendered_request
        assert db.get(CrawlJob, job_id).status == "failed"
        assert db.query(CrawlJobEvent).count() == 3
    finally:
        _dispose(engine, db)


@pytest.mark.asyncio
async def test_unavailable_keeps_unprioritized_clusters() -> None:
    engine, db, job_id = _session()
    try:
        service = JevIncidentTriageProductService(db)
        unavailable = service.preview(event_limit=99)
        unavailable_evaluator = _Evaluator(unavailable=True)
        await service.execute(unavailable.id, evaluator=unavailable_evaluator)
        assert service.serialize(unavailable)["clusters"][0]["disposition"] is None

        assert db.get(CrawlJob, job_id).status == "failed"
        assert db.query(CrawlJobEvent).count() == 3
    finally:
        _dispose(engine, db)
