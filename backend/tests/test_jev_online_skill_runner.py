from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai.system_one import ChoiceAnswer, SystemOneResult, SystemOneUsage
from app.models.jev import (
    JevOnlineSkillClassification,
    JevRun,
    JevRunAttempt,
    JevRunItem,
    JevRuntimeSettings,
)
from app.services.jev_online_skill_classification import (
    OnlineSkillCandidate,
    OnlineSkillCase,
    OnlineSkillOption,
)
from app.services.jev_online_skill_runner import JevOnlineSkillRunner
from app.services.jev_runtime_settings_service import JevRuntimeSettingsService


class _Evaluator:
    def __init__(self, result: SystemOneResult) -> None:
        self.result = result
        self.requests = []

    async def evaluate(self, request):
        self.requests.append(request)
        return self.result


def _session():
    engine = create_engine("sqlite:///:memory:")
    for table in (
        JevRuntimeSettings.__table__,
        JevRun.__table__,
        JevRunItem.__table__,
        JevRunAttempt.__table__,
        JevOnlineSkillClassification.__table__,
    ):
        table.create(engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    settings = JevRuntimeSettingsService(db).get_or_create()
    settings.enabled = True
    settings.api_key = "test-secret"
    settings.model = "typesafe/jev-1.13"
    settings.evidence_threshold_millis = 900
    settings.recommendation_threshold_millis = 900
    db.flush()
    return engine, db


def _case() -> OnlineSkillCase:
    return OnlineSkillCase(
        job_id="job-1",
        source_site="jobsdb",
        title="Backend Engineer",
        evidence_text="Python is required.",
        candidates=(
            OnlineSkillCandidate(
                raw_name="Python",
                evidence="Python is required.",
                options=(OnlineSkillOption(code="backend.python", label="Python"),),
            ),
        ),
        taxonomy_snapshot_sha256="a" * 64,
        rubric_version="jev-online-skill-v1",
    )


def _successful_result() -> SystemOneResult:
    return SystemOneResult(
        status="answered",
        request_id="gen-online-1",
        model="typesafe/jev-1.13-20260917",
        provider="TypeSafe",
        answers={
            "skill_000_evidence": ChoiceAnswer(
                type="choice",
                choice="required",
                confidence=0.98,
                probabilities={"required": 0.98, "insufficient": 0.02},
            ),
            "skill_000_mapping": ChoiceAnswer(
                type="choice",
                choice="backend.python",
                confidence=0.97,
                probabilities={"backend.python": 0.97, "keep_candidate": 0.03},
            ),
        },
        usage=SystemOneUsage(input_tokens=100, output_tokens=20, cost=0.00002),
        latency_ms=125,
    )


def test_online_runner_reuses_bounded_run_and_provider_receipt() -> None:
    engine, db = _session()
    try:
        runner = JevOnlineSkillRunner(db)
        case = _case()
        job_id = uuid.uuid4()
        record = runner.start(job_id=job_id, case=case)
        replay = runner.start(job_id=job_id, case=case)
        evaluator = _Evaluator(_successful_result())

        completed = asyncio.run(
            runner.execute(record.id, case=case, evaluator=evaluator)
        )

        assert replay.id == record.id
        assert db.query(JevRun).count() == 1
        assert len(evaluator.requests) == 1
        assert completed.status == "answered"
        assert completed.apply_projection is True
        assert completed.receipt["request_id"] == "gen-online-1"
        assert completed.receipt["provider"] == "TypeSafe"

        terminal_replay = asyncio.run(
            runner.execute(
                record.id,
                case=case,
                evaluator=evaluator,
            )
        )
        assert terminal_replay.id == completed.id
        assert len(evaluator.requests) == 1
    finally:
        db.close()
        engine.dispose()


def test_online_runner_retains_unavailable_receipt_and_unresolved_status() -> None:
    engine, db = _session()
    try:
        runner = JevOnlineSkillRunner(db)
        case = _case()
        record = runner.start(job_id=uuid.uuid4(), case=case)
        evaluator = _Evaluator(
            SystemOneResult(
                status="unavailable",
                model="typesafe/jev-1.13",
                error_code="http_520",
                error_message="System One returned HTTP 520",
            )
        )

        completed = asyncio.run(
            runner.execute(record.id, case=case, evaluator=evaluator)
        )

        assert completed.status == "unavailable"
        assert completed.apply_projection is False
        assert completed.decisions[0]["route"] == "unresolved"
        assert completed.error_code == "http_520"
    finally:
        db.close()
        engine.dispose()


def test_online_runner_records_disabled_state_without_provider_dispatch() -> None:
    engine, db = _session()
    try:
        settings = db.get(JevRuntimeSettings, 1)
        settings.enabled = False
        runner = JevOnlineSkillRunner(db)

        record = runner.start(job_id=uuid.uuid4(), case=_case())

        assert record.status == "unavailable"
        assert record.jev_run_id is None
        assert record.apply_projection is False
        assert record.error_code == "jev_disabled"
        assert record.receipt["error_code"] == "jev_disabled"
        assert db.query(JevRun).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_online_runner_explicit_retry_preserves_failed_receipt_history() -> None:
    engine, db = _session()
    try:
        settings = db.get(JevRuntimeSettings, 1)
        settings.retry_limit = 1
        runner = JevOnlineSkillRunner(db)
        case = _case()
        record = runner.start(job_id=uuid.uuid4(), case=case)
        failed = asyncio.run(
            runner.execute(
                record.id,
                case=case,
                evaluator=_Evaluator(
                    SystemOneResult(
                        status="unavailable",
                        error_code="http_503",
                        error_message="temporarily unavailable",
                    )
                ),
            )
        )
        assert failed.status == "unavailable"

        pending = runner.retry(failed.id)
        assert pending.status == "pending"
        assert pending.receipt_history[0]["error_code"] == "http_503"
        completed = asyncio.run(
            runner.execute(
                pending.id,
                case=case,
                evaluator=_Evaluator(_successful_result()),
            )
        )

        assert completed.status == "answered"
        assert completed.receipt["request_id"] == "gen-online-1"
        assert completed.receipt_history[0]["receipt"]["status"] == "unavailable"
        run = db.get(JevRun, completed.jev_run_id)
        assert run.status == "completed"
        assert run.items[0].attempt_count == 2
        assert len(run.items[0].attempts) == 2
    finally:
        db.close()
        engine.dispose()
