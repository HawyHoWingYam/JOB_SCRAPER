from __future__ import annotations

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai.system_one import ChoiceAnswer, SystemOneResult
from app.models.jev import JevOnlineSkillClassification
from app.services.jev_online_skill_classification import (
    OnlineSkillCandidate,
    OnlineSkillCase,
    OnlineSkillOption,
    OnlineSkillThresholds,
    build_online_skill_dispatch,
    route_online_skill_result,
)
from app.services.jev_online_skill_store import JevOnlineSkillStore


def _session():
    engine = create_engine("sqlite:///:memory:")
    JevOnlineSkillClassification.__table__.create(engine)
    return engine, sessionmaker(bind=engine, autoflush=False)()


def _case(*, evidence: str = "Python is required.") -> OnlineSkillCase:
    return OnlineSkillCase(
        job_id="job-1",
        source_site="jobsdb",
        title="Backend Engineer",
        evidence_text=evidence,
        candidates=(
            OnlineSkillCandidate(
                raw_name="Python",
                evidence=evidence,
                options=(OnlineSkillOption(code="backend.python", label="Python"),),
            ),
        ),
        taxonomy_snapshot_sha256="a" * 64,
        rubric_version="jev-online-skill-v1",
    )


def _routing(case: OnlineSkillCase, *, input_fingerprint: str):
    return route_online_skill_result(
        case,
        SystemOneResult(
            status="answered",
            model="typesafe/jev-1.13",
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
        ),
        input_fingerprint=input_fingerprint,
        thresholds=OnlineSkillThresholds(
            evidence_millis=900,
            recommendation_millis=900,
            recommendation_margin_millis=100,
        ),
    )


def test_reservation_is_idempotent_for_same_job_and_input() -> None:
    engine, db = _session()
    try:
        store = JevOnlineSkillStore(db)
        job_id = uuid.uuid4()
        case = _case()
        dispatch = build_online_skill_dispatch(case, model="typesafe/jev-1.13")

        first = store.reserve(job_id=job_id, case=case, dispatch=dispatch)
        replay = store.reserve(job_id=job_id, case=case, dispatch=dispatch)

        assert first.created is True
        assert replay.created is False
        assert replay.record.id == first.record.id
        assert db.query(JevOnlineSkillClassification).count() == 1
        assert first.record.evidence_snapshot["evidence_text"] == "Python is required."
    finally:
        db.close()
        engine.dispose()


def test_changed_evidence_creates_new_auditable_record() -> None:
    engine, db = _session()
    try:
        store = JevOnlineSkillStore(db)
        job_id = uuid.uuid4()
        first_case = _case()
        changed_case = _case(evidence="Python is preferred.")
        first = store.reserve(
            job_id=job_id,
            case=first_case,
            dispatch=build_online_skill_dispatch(first_case, model="jev"),
        )
        changed = store.reserve(
            job_id=job_id,
            case=changed_case,
            dispatch=build_online_skill_dispatch(changed_case, model="jev"),
        )

        assert changed.created is True
        assert changed.record.id != first.record.id
        assert db.query(JevOnlineSkillClassification).count() == 2
    finally:
        db.close()
        engine.dispose()


def test_terminal_receipt_is_idempotent_but_immutable() -> None:
    engine, db = _session()
    try:
        store = JevOnlineSkillStore(db)
        job_id = uuid.uuid4()
        case = _case()
        reservation = store.reserve(
            job_id=job_id,
            case=case,
            dispatch=build_online_skill_dispatch(case, model="typesafe/jev-1.13"),
        )
        store.mark_running(reservation.record.id)
        routing = _routing(case, input_fingerprint=reservation.record.input_fingerprint)
        receipt = {"request_id": "gen-1", "model": "typesafe/jev-1.13"}

        completed = store.complete(
            reservation.record.id,
            routing=routing,
            receipt=receipt,
        )
        replay = store.complete(
            reservation.record.id,
            routing=routing,
            receipt=receipt,
        )

        assert completed.status == "answered"
        assert completed.apply_projection is True
        assert replay.id == completed.id
        assert completed.decisions[0]["skill_code"] == "backend.python"

        try:
            store.complete(
                reservation.record.id,
                routing=routing,
                receipt={"request_id": "different"},
            )
        except ValueError as exc:
            assert "immutable" in str(exc)
        else:
            raise AssertionError("terminal receipt must not be rewritten")
    finally:
        db.close()
        engine.dispose()
