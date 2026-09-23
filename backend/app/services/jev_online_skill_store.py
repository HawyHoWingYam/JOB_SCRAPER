from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.jev import JevOnlineSkillClassification
from app.services.jev_online_skill_classification import (
    OnlineSkillCase,
    OnlineSkillDispatch,
    OnlineSkillRoutingResult,
)
from app.utils.time import utc_now


@dataclass(frozen=True)
class OnlineSkillReservation:
    record: JevOnlineSkillClassification
    created: bool


class JevOnlineSkillStore:
    """Own idempotency and immutable terminal receipts for online Skill work."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def reserve(
        self,
        *,
        job_id: UUID,
        case: OnlineSkillCase,
        dispatch: OnlineSkillDispatch,
    ) -> OnlineSkillReservation:
        existing = self._find(job_id, dispatch.input_fingerprint)
        if existing is not None:
            return OnlineSkillReservation(record=existing, created=False)
        record = JevOnlineSkillClassification(
            job_id=job_id,
            input_fingerprint=dispatch.input_fingerprint,
            taxonomy_snapshot_sha256=case.taxonomy_snapshot_sha256,
            rubric_version=case.rubric_version,
            status="pending",
            apply_projection=False,
            receipt_history=[],
            evidence_snapshot={
                "job_id": case.job_id,
                "source_site": case.source_site,
                "title": case.title,
                "evidence_text": case.evidence_text,
                "candidates": [
                    {
                        "raw_name": candidate.raw_name,
                        "evidence": candidate.evidence,
                        "options": [
                            option.model_dump() for option in candidate.options
                        ],
                    }
                    for candidate in case.candidates
                ],
            },
        )
        try:
            with self.db.begin_nested():
                self.db.add(record)
                self.db.flush()
        except IntegrityError:
            concurrent = self._find(job_id, dispatch.input_fingerprint)
            if concurrent is None:
                raise
            return OnlineSkillReservation(record=concurrent, created=False)
        return OnlineSkillReservation(record=record, created=True)

    def mark_running(self, record_id: str) -> JevOnlineSkillClassification:
        record = self._require(record_id)
        if record.status == "running":
            return record
        if record.status != "pending":
            raise ValueError("terminal online Skill classification cannot restart")
        record.status = "running"
        record.started_at = utc_now()
        self.db.flush()
        return record

    def complete(
        self,
        record_id: str,
        *,
        routing: OnlineSkillRoutingResult,
        receipt: dict[str, object],
    ) -> JevOnlineSkillClassification:
        record = self._require(record_id)
        if record.input_fingerprint != routing.input_fingerprint:
            raise ValueError(
                "online Skill routing fingerprint does not match reservation"
            )
        decisions = [decision.model_dump() for decision in routing.decisions]
        if record.status in {"answered", "unavailable", "invalid"}:
            if (
                record.status == routing.status
                and record.apply_projection == routing.apply_projection
                and record.decisions == decisions
                and record.receipt == receipt
                and record.error_code == routing.error_code
            ):
                return record
            raise ValueError("terminal online Skill classification is immutable")
        if record.status not in {"pending", "running"}:
            raise ValueError("online Skill classification is not completable")
        record.status = routing.status
        record.apply_projection = routing.apply_projection
        record.decisions = decisions
        record.receipt = dict(receipt)
        record.error_code = routing.error_code
        record.completed_at = utc_now()
        self.db.flush()
        return record

    def latest_for_job(self, job_id: UUID) -> JevOnlineSkillClassification | None:
        return self.db.scalar(
            select(JevOnlineSkillClassification)
            .where(JevOnlineSkillClassification.job_id == job_id)
            .order_by(
                JevOnlineSkillClassification.created_at.desc(),
                JevOnlineSkillClassification.id.desc(),
            )
            .limit(1)
        )

    def prepare_retry(self, record_id: str) -> JevOnlineSkillClassification:
        record = self._require(record_id)
        if record.status not in {"unavailable", "invalid"}:
            raise ValueError("only failed online Skill classification can retry")
        history = list(record.receipt_history or [])
        history.append(
            {
                "status": record.status,
                "apply_projection": bool(record.apply_projection),
                "decisions": list(record.decisions or []),
                "receipt": dict(record.receipt or {}),
                "error_code": record.error_code,
                "completed_at": (
                    record.completed_at.isoformat() if record.completed_at else None
                ),
            }
        )
        record.receipt_history = history
        record.status = "pending"
        record.apply_projection = False
        record.decisions = None
        record.receipt = None
        record.error_code = None
        record.started_at = None
        record.completed_at = None
        self.db.flush()
        return record

    def _find(
        self,
        job_id: UUID,
        input_fingerprint: str,
    ) -> JevOnlineSkillClassification | None:
        return self.db.scalar(
            select(JevOnlineSkillClassification).where(
                JevOnlineSkillClassification.job_id == job_id,
                JevOnlineSkillClassification.input_fingerprint == input_fingerprint,
            )
        )

    def _require(self, record_id: str) -> JevOnlineSkillClassification:
        record = self.db.get(JevOnlineSkillClassification, record_id)
        if record is None:
            raise ValueError("online Skill classification does not exist")
        return record


__all__ = ["JevOnlineSkillStore", "OnlineSkillReservation"]
