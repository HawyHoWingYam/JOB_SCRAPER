from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.jev import JevRunAttempt
from app.services.jev_evaluation import (
    ControlledEvaluationCase,
    EvaluationObservation,
)
from app.services.jev_run_service import JevRunService


class JevEvaluationRunner:
    """Run immutable evaluation cases in a caller-owned isolated database."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.runs = JevRunService(db)

    def start(
        self,
        *,
        cases: Sequence[ControlledEvaluationCase],
        manifest_sha256: str,
    ):
        if len(manifest_sha256) != 64:
            raise ValueError("manifest_sha256 must be a SHA-256 hex digest")
        run = self.runs.start(
            purpose="skill_offline_evaluation",
            rubric_version="jev-skill-evaluation-v1",
            items=[
                {
                    "subject_id": case.case_id,
                    "evidence_refs": list(case.evidence_refs),
                    "payload": {
                        "state": case.state,
                        "questions": case.questions,
                        "evaluation": {
                            "case_id": case.case_id,
                            "split": case.split,
                            "decision_kind": case.decision_kind,
                            "expected": case.expected,
                            "label_provenance": case.label_provenance,
                            "language": case.language,
                            "stability_group": case.stability_group,
                            "manifest_sha256": manifest_sha256,
                        },
                    },
                }
                for case in cases
            ],
        )
        run.settings_snapshot = {
            **run.settings_snapshot,
            "evaluation_manifest_sha256": manifest_sha256,
        }
        self.db.flush()
        return run

    async def execute_remaining(self, run_id: str, *, evaluator) -> None:
        while True:
            item = await self.runs.execute_next(run_id, evaluator=evaluator)
            if item is None:
                return
            self.db.flush()
            if item.status == "failed":
                return

    def observations(self, run_id: str) -> list[EvaluationObservation]:
        run = self.runs.get(run_id)
        observations: list[EvaluationObservation] = []
        for item in run.items:
            if item.status not in {"completed", "failed"}:
                continue
            attempt = self.db.scalar(
                select(JevRunAttempt)
                .where(JevRunAttempt.item_id == item.id)
                .order_by(JevRunAttempt.attempt_number.desc())
                .limit(1)
            )
            evaluation = item.payload.get("evaluation") or {}
            result = item.result or {}
            answers = result.get("answers") or {}
            decision = answers.get("decision") or {}
            status = result.get("status") or (
                "invalid" if item.error_code == "invalid_response" else "unavailable"
            )
            if status not in {"answered", "abstained", "unavailable", "invalid"}:
                status = "unavailable"
            observations.append(
                EvaluationObservation(
                    case_id=str(evaluation.get("case_id") or item.subject_id),
                    run_id=run.id,
                    manifest_sha256=evaluation.get("manifest_sha256"),
                    rubric_version=run.rubric_version,
                    model=result.get("model") or run.settings_snapshot.get("model"),
                    reservation_id=attempt.reservation_id if attempt else None,
                    reserved_microdollars=(
                        int(attempt.reserved_microdollars or 0) if attempt else 0
                    ),
                    split=str(evaluation.get("split") or "development"),
                    decision_kind=str(
                        evaluation.get("decision_kind") or "evidence_support"
                    ),
                    status=status,
                    expected=evaluation.get("expected"),
                    predicted=decision.get("choice"),
                    reference_provenance=evaluation.get("label_provenance"),
                    language=evaluation.get("language"),
                    stability_group=evaluation.get("stability_group"),
                    latency_ms=result.get("latency_ms"),
                    input_tokens=int(attempt.input_tokens or 0) if attempt else 0,
                    output_tokens=int(attempt.output_tokens or 0) if attempt else 0,
                    actual_microdollars=(
                        int(attempt.actual_microdollars or 0) if attempt else 0
                    ),
                    error_code=item.error_code,
                )
            )
        return observations


__all__ = ["JevEvaluationRunner"]
