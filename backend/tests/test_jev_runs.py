from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pytest

from app.models.jev import (
    JevRun,
    JevRunAttempt,
    JevRunItem,
    JevRuntimeSettings,
)
from app.services.jev_run_service import JevRunService
from app.services.jev_runtime_settings_service import JevRuntimeSettingsService


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
    settings = JevRuntimeSettingsService(db)
    settings.get_or_create()
    settings.update(
        {
            "enabled": True,
            "api_key": "test-secret",
        }
    )
    db.commit()
    return engine, db


def test_run_freezes_configuration_and_ordered_work_membership() -> None:
    engine, db = _session()
    try:
        run = JevRunService(db).start(
            purpose="skill_evidence_evaluation",
            rubric_version="skill-evidence-v1",
            items=[
                {
                    "subject_id": "job-2:python",
                    "evidence_refs": ["job:job-2#description"],
                    "payload": {"text": "Python preferred"},
                },
                {"subject_id": "job-7:sql", "payload": {"text": "SQL required"}},
            ],
        )
        db.commit()

        frozen = dict(run.settings_snapshot)
        assert frozen["endpoint"] == "https://www.rsiai.net/v1/systemone"
        assert frozen["model"] == "jev-latest"
        assert "max_request_reservation_microdollars" not in frozen
        assert "allowance_microdollars" not in frozen
        assert "api_key" not in frozen
        assert frozen["api_key_fingerprint"]
        assert [(item.position, item.subject_id) for item in run.items] == [
            (0, "job-2:python"),
            (1, "job-7:sql"),
        ]
        assert run.items[0].evidence_refs == ["job:job-2#description"]

        JevRuntimeSettingsService(db).update({"model": "jev-next", "sample_limit": 25})
        db.commit()
        db.refresh(run)
        assert run.settings_snapshot == frozen
    finally:
        db.close()
        engine.dispose()


def test_maintenance_run_freezes_strong_model_without_a_local_budget() -> None:
    engine, db = _session()
    try:
        settings = JevRuntimeSettingsService(db).get_or_create()
        settings.maintenance_model = "openai/gpt-5.4"
        db.flush()
        run = JevRunService(db).start(
            purpose="taxonomy_maintenance:test",
            rubric_version="taxonomy-maintenance-v1",
            profile="maintenance",
            items=[{"subject_id": "candidate-1", "payload": {}}],
        )

        assert run.settings_snapshot["model"] == "openai/gpt-5.4"
        assert "budget_scope" not in run.settings_snapshot
        assert "allowance_microdollars" not in run.settings_snapshot
    finally:
        db.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_execute_next_dispatches_and_persists_a_receipt_without_local_cost() -> None:
    engine, db = _session()

    class FakeEvaluator:
        def __init__(self) -> None:
            self.requests = []

        async def evaluate(self, request):
            from app.ai.system_one import (
                ChoiceAnswer,
                SystemOneResult,
                SystemOneUsage,
            )

            self.requests.append(request)
            return SystemOneResult(
                status="answered",
                model="jev-latest",
                answers={
                    "support": ChoiceAnswer(
                        type="choice",
                        choice="supported",
                        confidence=0.9,
                        probabilities={"supported": 0.9, "unsupported": 0.1},
                    )
                },
                usage=SystemOneUsage(input_tokens=20, output_tokens=2),
            )

    try:
        service = JevRunService(db)
        run = service.start(
            purpose="skill_evidence_evaluation",
            rubric_version="skill-evidence-v1",
            items=[
                {
                    "subject_id": "job-2:python",
                    "payload": {
                        "state": {"text": "Python is required."},
                        "questions": {
                            "support": {
                                "type": "choice",
                                "criteria": {
                                    "supported": "Required",
                                    "unsupported": "Not required",
                                },
                            }
                        },
                    },
                }
            ],
        )
        db.commit()
        evaluator = FakeEvaluator()

        completed = await service.execute_next(run.id, evaluator=evaluator)
        db.commit()

        assert completed is not None
        assert completed.status == "completed"
        assert completed.result["answers"]["support"]["choice"] == "supported"
        assert len(evaluator.requests) == 1
        db.refresh(run)
        assert run.status == "completed"
        assert run.completed_items == 1
        assert run.failed_items == 0
        attempt = db.query(JevRunAttempt).one()
        assert attempt.status == "answered"
        assert attempt.input_tokens == 20
        assert attempt.output_tokens == 2
        assert attempt.actual_microdollars is None
    finally:
        db.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_missing_provider_cost_is_not_estimated_from_local_token_prices() -> None:
    engine, db = _session()

    class PricedEvaluator:
        async def evaluate(self, _request):
            from app.ai.system_one import NoulAnswer, SystemOneResult, SystemOneUsage

            return SystemOneResult(
                status="answered",
                model="jev-latest",
                answers={"support": NoulAnswer(type="noul", noul=0.9)},
                usage=SystemOneUsage(input_tokens=20, output_tokens=2),
            )

    try:
        service = JevRunService(db)
        run = service.start(
            purpose="priced_evaluation",
            rubric_version="priced-v1",
            items=[
                {
                    "subject_id": "one",
                    "payload": {
                        "state": "Python required",
                        "questions": {"support": {"type": "noul"}},
                    },
                }
            ],
        )
        db.commit()

        await service.execute_next(run.id, evaluator=PricedEvaluator())
        db.commit()

        attempt = db.query(JevRunAttempt).one()
        assert attempt.actual_microdollars is None
    finally:
        db.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_provider_reported_cost_is_retained_as_audit_data() -> None:
    engine, db = _session()

    class OpenRouterEvaluator:
        async def evaluate(self, _request):
            from app.ai.system_one import NoulAnswer, SystemOneResult, SystemOneUsage

            return SystemOneResult(
                status="answered",
                request_id="gen-dec-test-receipt",
                model="typesafe/jev-1.13-20260917",
                provider="TypeSafe",
                answers={"support": NoulAnswer(type="noul", noul=0.9)},
                usage=SystemOneUsage(
                    input_tokens=476,
                    output_tokens=70,
                    cost=0.000019992,
                ),
            )

    try:
        service = JevRunService(db)
        run = service.start(
            purpose="openrouter_priced_evaluation",
            rubric_version="priced-v1",
            items=[
                {
                    "subject_id": "one",
                    "payload": {
                        "state": "Python required",
                        "questions": {"support": {"type": "noul"}},
                    },
                }
            ],
        )
        db.commit()

        item = await service.execute_next(run.id, evaluator=OpenRouterEvaluator())
        db.commit()

        assert item is not None
        assert item.result["request_id"] == "gen-dec-test-receipt"
        assert item.result["provider"] == "TypeSafe"
        assert item.result["usage"]["cost"] == 0.000019992
        attempt = db.query(JevRunAttempt).one()
        assert attempt.actual_microdollars == 20
    finally:
        db.close()
        engine.dispose()


def test_run_requires_no_local_monetary_configuration() -> None:
    engine, db = _session()
    try:
        run = JevRunService(db).start(
            purpose="provider_console_authorized_evaluation",
            rubric_version="provider-console-v1",
            items=[{"subject_id": "one", "payload": {}}],
        )
        assert run.status == "pending"
    finally:
        db.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_transport_exception_fails_item_and_keeps_an_attempt_receipt() -> None:
    engine, db = _session()

    class FailingEvaluator:
        async def evaluate(self, _request):
            raise TimeoutError("secret upstream diagnostic")

    try:
        service = JevRunService(db)
        run = service.start(
            purpose="skill_evidence_evaluation",
            rubric_version="skill-evidence-v1",
            items=[
                {
                    "subject_id": "job-2:python",
                    "payload": {
                        "state": "Python is required.",
                        "questions": {"support": {"type": "noul"}},
                    },
                }
            ],
        )
        db.commit()

        item = await service.execute_next(run.id, evaluator=FailingEvaluator())
        db.commit()

        assert item is not None
        assert item.status == "failed"
        assert item.error_code == "transport_error"
        assert item.error_message == "External Jev request failed"
        assert "secret" not in item.error_message
        attempt = db.query(JevRunAttempt).one()
        assert attempt.status == "unavailable"
        assert attempt.actual_microdollars is None
        db.refresh(run)
        assert run.status == "completed_with_failures"
    finally:
        db.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_abstained_result_is_a_terminal_auditable_receipt() -> None:
    engine, db = _session()

    class AbstainingEvaluator:
        async def evaluate(self, _request):
            from app.ai.system_one import SystemOneResult, SystemOneUsage

            return SystemOneResult(
                status="abstained",
                model="jev-latest",
                usage=SystemOneUsage(input_tokens=8, output_tokens=1),
                latency_ms=12,
            )

    try:
        service = JevRunService(db)
        run = service.start(
            purpose="abstention_test",
            rubric_version="v1",
            items=[
                {
                    "subject_id": "one",
                    "evidence_refs": ["job:one#description"],
                    "payload": {
                        "state": "Ambiguous text",
                        "questions": {"support": {"type": "noul"}},
                    },
                }
            ],
        )
        db.commit()

        item = await service.execute_next(run.id, evaluator=AbstainingEvaluator())
        db.commit()

        assert item.status == "completed"
        assert item.result == {
            "status": "abstained",
            "model": "jev-latest",
            "answers": {},
            "usage": {"input_tokens": 8, "output_tokens": 1},
            "latency_ms": 12,
        }
        assert db.query(JevRunAttempt).one().status == "abstained"
    finally:
        db.close()
        engine.dispose()


def test_claim_respects_the_frozen_concurrency_limit() -> None:
    engine, db = _session()
    try:
        JevRuntimeSettingsService(db).update({"concurrency": 1})
        db.commit()
        service = JevRunService(db)
        run = service.start(
            purpose="concurrency_test",
            rubric_version="v1",
            items=[
                {"subject_id": "one", "payload": {}},
                {"subject_id": "two", "payload": {}},
            ],
        )
        db.commit()

        first = service.claim_next_item(run.id)
        db.commit()
        second = service.claim_next_item(run.id)

        assert first is not None
        assert second is None
        assert service.get(run.id).running_items == 1
        assert service.get(run.id).pending_items == 1
    finally:
        db.close()
        engine.dispose()


def test_stop_cancels_pending_items_and_is_idempotent() -> None:
    engine, db = _session()
    try:
        service = JevRunService(db)
        run = service.start(
            purpose="skill_evidence_evaluation",
            rubric_version="skill-evidence-v1",
            items=[
                {"subject_id": "one", "payload": {}},
                {"subject_id": "two", "payload": {}},
            ],
        )
        db.commit()

        stopped = service.request_stop(run.id)
        db.commit()
        stopped_again = service.request_stop(run.id)

        assert stopped.status == "cancelled"
        assert stopped_again.status == "cancelled"
        assert stopped.cancelled_items == 2
        assert {item.status for item in stopped.items} == {"cancelled"}
        assert service.claim_next_item(run.id) is None
    finally:
        db.close()
        engine.dispose()


def test_cancelled_run_can_be_resumed_explicitly() -> None:
    engine, db = _session()
    try:
        service = JevRunService(db)
        run = service.start(
            purpose="skill_evidence_evaluation",
            rubric_version="skill-evidence-v1",
            items=[{"subject_id": "one", "payload": {}}],
        )
        db.commit()
        service.request_stop(run.id)
        db.commit()

        resumed = service.resume(run.id)
        db.commit()

        assert resumed.status == "pending"
        assert resumed.pending_items == 1
        assert resumed.cancelled_items == 0
        assert resumed.stop_requested_at is None
        assert resumed.completed_at is None
    finally:
        db.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_failed_item_can_retry_only_within_frozen_retry_limit() -> None:
    engine, db = _session()

    class UnavailableEvaluator:
        async def evaluate(self, _request):
            from app.ai.system_one import SystemOneResult

            return SystemOneResult(
                status="unavailable",
                error_code="upstream_unavailable",
                error_message="Jev unavailable",
            )

    try:
        JevRuntimeSettingsService(db).update({"retry_limit": 1})
        db.commit()
        service = JevRunService(db)
        run = service.start(
            purpose="skill_evidence_evaluation",
            rubric_version="skill-evidence-v1",
            items=[
                {
                    "subject_id": "one",
                    "payload": {
                        "state": "Python required",
                        "questions": {"support": {"type": "noul"}},
                    },
                }
            ],
        )
        db.commit()
        await service.execute_next(run.id, evaluator=UnavailableEvaluator())
        db.commit()

        retried = service.retry_failed(run.id)
        db.commit()
        assert retried.status == "pending"
        assert retried.pending_items == 1

        await service.execute_next(run.id, evaluator=UnavailableEvaluator())
        db.commit()
        with pytest.raises(ValueError, match="retry limit"):
            service.retry_failed(run.id)
    finally:
        db.close()
        engine.dispose()
