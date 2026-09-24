from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai.system_one import ChoiceAnswer, SystemOneResult, SystemOneUsage
from app.models.jev import (
    JevRun,
    JevRunAttempt,
    JevRunItem,
    JevRuntimeSettings,
)
from app.services.jev_evaluation import load_controlled_cases
from app.services.jev_evaluation_runner import JevEvaluationRunner
from app.services.jev_runtime_settings_service import JevRuntimeSettingsService


FIXTURE = Path(__file__).parent / "fixtures" / "jev_skill_controlled_v1.jsonl"


def _session():
    engine = create_engine("sqlite:///:memory:")
    for table in (
        JevRuntimeSettings.__table__,
        JevRun.__table__,
        JevRunItem.__table__,
        JevRunAttempt.__table__,
    ):
        table.create(engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    JevRuntimeSettingsService(db).update(
        {
            "enabled": True,
            "api_key": "isolation-test-secret",
            "retry_limit": 1,
        }
    )
    db.commit()
    return engine, db


@pytest.mark.asyncio
async def test_evaluation_runner_reuses_run_and_exports_observations() -> None:
    engine, db = _session()

    class Evaluator:
        def __init__(self):
            self.calls = 0

        async def evaluate(self, request):
            self.calls += 1
            choice = request.state.get("expected_for_test", "required")
            return SystemOneResult(
                status="answered",
                model="jev-latest",
                answers={
                    "decision": ChoiceAnswer(
                        type="choice",
                        choice=choice,
                        confidence=0.9,
                        probabilities={choice: 0.9},
                    )
                },
                usage=SystemOneUsage(input_tokens=10, output_tokens=1),
                latency_ms=12,
            )

    try:
        cases = load_controlled_cases(FIXTURE)[:2]
        evaluator = Evaluator()
        runner = JevEvaluationRunner(db)
        run = runner.start(cases=cases, manifest_sha256="b" * 64)
        db.commit()

        await runner.execute_remaining(run.id, evaluator=evaluator)
        db.commit()
        observations = runner.observations(run.id)
        await runner.execute_remaining(run.id, evaluator=evaluator)

        assert evaluator.calls == 2
        assert len(observations) == 2
        assert observations[0].case_id == cases[0].case_id
        assert observations[0].run_id == run.id
        assert observations[0].manifest_sha256 == "b" * 64
        assert observations[0].rubric_version == "jev-skill-evaluation-v1"
        assert observations[0].model == "jev-latest"
        assert observations[0].status == "answered"
        assert observations[0].input_tokens == 10
        assert observations[0].actual_microdollars is None
    finally:
        db.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_evaluation_runner_stops_after_ambiguous_failure() -> None:
    engine, db = _session()

    class FailingEvaluator:
        def __init__(self):
            self.calls = 0

        async def evaluate(self, _request):
            self.calls += 1
            raise TimeoutError("must-not-leak")

    try:
        cases = load_controlled_cases(FIXTURE)[:2]
        evaluator = FailingEvaluator()
        runner = JevEvaluationRunner(db)
        run = runner.start(cases=cases, manifest_sha256="c" * 64)
        db.commit()

        await runner.execute_remaining(run.id, evaluator=evaluator)
        db.commit()
        observations = runner.observations(run.id)

        assert evaluator.calls == 1
        assert observations[0].status == "unavailable"
        assert observations[0].error_code == "transport_error"
        assert "must-not-leak" not in str(observations[0].model_dump())
        assert observations[0].actual_microdollars is None
    finally:
        db.close()
        engine.dispose()
