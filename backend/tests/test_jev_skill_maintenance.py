from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai.system_one import ChoiceAnswer, SystemOneResult, SystemOneUsage
from app.models.current_taxonomy import (
    CurrentJobSkillAssignment,
    CurrentJobSkillMention,
    CurrentSkillCandidate,
    CurrentTaxonomyAliasRecord,
    CurrentTaxonomyNodeRecord,
)
from app.models.jev import (
    JevRun,
    JevRunAttempt,
    JevRunItem,
    JevRuntimeSettings,
    JevSkillMaintenanceBatch,
)
from app.services.jev_runtime_settings_service import JevRuntimeSettingsService
from app.services.jev_run_service import JevRunService
from app.services.jev_skill_maintenance import JevSkillMaintenanceService


def _session():
    engine = create_engine("sqlite:///:memory:")
    for table in (
        CurrentTaxonomyNodeRecord.__table__,
        CurrentTaxonomyAliasRecord.__table__,
        CurrentJobSkillAssignment.__table__,
        CurrentSkillCandidate.__table__,
        CurrentJobSkillMention.__table__,
        JevRuntimeSettings.__table__,
        JevRun.__table__,
        JevRunItem.__table__,
        JevRunAttempt.__table__,
        JevSkillMaintenanceBatch.__table__,
    ):
        table.create(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    settings = JevRuntimeSettingsService(db).get_or_create()
    settings.enabled = True
    settings.api_key = "maintenance-secret"
    settings.maintenance_enabled = True
    settings.maintenance_model = "strong/model"
    settings.maintenance_min_candidates = 2
    settings.maintenance_batch_size = 10
    settings.maintenance_threshold_millis = 900
    db.add_all(
        (
            CurrentTaxonomyNodeRecord(
                taxonomy="skill",
                code="backend",
                parent_code=None,
                level="category",
                labels={"en": "Backend"},
                sort_order=1,
                is_assignable=False,
                is_active=True,
            ),
            CurrentTaxonomyNodeRecord(
                taxonomy="skill",
                code="backend.languages",
                parent_code="backend",
                level="technology",
                labels={"en": "Languages"},
                sort_order=1,
                is_assignable=False,
                is_active=True,
            ),
            CurrentTaxonomyNodeRecord(
                taxonomy="skill",
                code="backend.python",
                parent_code="backend.languages",
                level="skill",
                labels={"en": "Python"},
                sort_order=1,
                is_assignable=True,
                is_active=True,
            ),
        )
    )
    db.flush()
    return engine, db


def _candidate(db, name: str, count: int = 5):
    row = CurrentSkillCandidate(
        normalized_key=name.casefold(),
        canonical_raw_name=name,
        raw_variants=[name],
        occurrence_count=count,
        distinct_job_count=count,
        evidence_summary={"active_mentions": count},
    )
    db.add(row)
    db.flush()
    return row


class _MaintenanceEvaluator:
    def __init__(self) -> None:
        self.requests = []

    async def evaluate(self, request):
        self.requests.append(request)
        answers = {}
        for name in request.questions:
            if name == "candidate_000_action":
                choice = "backend.python"
            elif name == "candidate_001_action":
                choice = "propose_new"
            else:
                choice = "backend.languages"
            answers[name] = ChoiceAnswer(
                type="choice",
                choice=choice,
                confidence=0.98,
                probabilities={choice: 0.98, "insufficient": 0.02},
            )
        return SystemOneResult(
            status="answered",
            request_id="maintenance-1",
            model="strong/model",
            provider="test",
            answers=answers,
            usage=SystemOneUsage(input_tokens=100, output_tokens=20, cost=0.00002),
        )


def test_maintenance_check_below_threshold_is_free() -> None:
    engine, db = _session()
    try:
        _candidate(db, "Py")
        service = JevSkillMaintenanceService(db)

        eligibility, batch = service.start(trigger="manual")

        assert eligibility.reason == "insufficient_candidates"
        assert eligibility.eligible_count == 1
        assert batch is None
        assert db.query(JevRun).count() == 0
        assert db.get(JevRuntimeSettings, 1).maintenance_last_checked_at is not None
    finally:
        db.close()
        engine.dispose()


def test_scheduled_eligibility_accepts_sqlite_naive_last_checked_timestamp() -> None:
    engine, db = _session()
    try:
        settings = db.get(JevRuntimeSettings, 1)
        settings.maintenance_last_checked_at = datetime(2026, 1, 1)
        db.flush()

        eligibility = JevSkillMaintenanceService(db).eligibility()

        assert eligibility.due is True
        assert settings.maintenance_last_checked_at.tzinfo is None
        assert datetime.now(UTC).tzinfo is UTC
    finally:
        db.close()
        engine.dispose()


def test_maintenance_auto_applies_existing_and_holds_new_for_batch_approval() -> None:
    engine, db = _session()
    try:
        existing = _candidate(db, "Python language", 9)
        novel = _candidate(db, "NovelDB", 7)
        service = JevSkillMaintenanceService(db)
        eligibility, batch = service.start(trigger="manual")
        evaluator = _MaintenanceEvaluator()

        completed = asyncio.run(service.execute(batch.id, evaluator=evaluator))

        assert eligibility.can_start is True
        assert len(evaluator.requests) == 1
        assert completed.status == "ready_for_approval"
        assert completed.auto_applied_count == 1
        assert completed.held_for_approval_count == 1
        assert existing.resolved_skill_code == "backend.python"
        assert novel.resolved_skill_code is None
        alias = db.get(
            CurrentTaxonomyAliasRecord,
            ("skill", "backend.python", "Python language"),
        )
        assert alias.normalized_alias == "python language"
        approved = service.approve(completed.id)

        assert approved.status == "applied"
        assert approved.held_for_approval_count == 0
        assert novel.resolved_skill_code == "backend.languages.noveldb"
        assert approved.approved_at is not None
        assert (
            db.get(
                CurrentTaxonomyNodeRecord,
                ("skill", "backend.languages.noveldb"),
            )
            is not None
        )
    finally:
        db.close()
        engine.dispose()


def test_active_maintenance_batch_prevents_duplicate_manual_dispatch() -> None:
    engine, db = _session()
    try:
        _candidate(db, "Python language", 9)
        _candidate(db, "NovelDB", 7)
        service = JevSkillMaintenanceService(db)

        first_eligibility, first = service.start(trigger="manual")
        second_eligibility, second = service.start(trigger="manual")

        assert first_eligibility.can_start is True
        assert first is not None
        assert second is None
        assert second_eligibility.can_start is False
        assert second_eligibility.reason == "maintenance_in_progress"
        assert db.query(JevSkillMaintenanceBatch).count() == 1
        assert db.query(JevRun).count() == 1
    finally:
        db.close()
        engine.dispose()


def test_pending_batch_can_be_terminated_as_auditable_configuration_failure() -> None:
    engine, db = _session()
    try:
        _candidate(db, "Python language", 9)
        _candidate(db, "NovelDB", 7)
        service = JevSkillMaintenanceService(db)
        _eligibility, batch = service.start(trigger="manual")

        failed = service.mark_unavailable(
            batch.id,
            error_code="configuration_error",
        )

        assert failed.status == "unavailable"
        assert failed.receipt == {
            "status": "unavailable",
            "error_code": "configuration_error",
        }
        assert JevRunService(db).get(batch.jev_run_id).status == "cancelled"
        assert service.pending() is None
    finally:
        db.close()
        engine.dispose()
