from __future__ import annotations

import hashlib
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from app.ai.system_one import SystemOneAnswer, SystemOneResult, SystemOneUsage
from app.models.jev import JevOnlineSkillClassification
from app.services.jev_budget import JevBudgetExhaustedError
from app.services.jev_online_skill_classification import (
    OnlineSkillCase,
    OnlineSkillRoutingResult,
    OnlineSkillThresholds,
    RoutedSkillDecision,
    build_online_skill_dispatch,
    build_projection_skills,
    route_online_skill_result,
)
from app.services.jev_online_skill_store import JevOnlineSkillStore
from app.services.jev_run_service import JevRunConfigurationError, JevRunService
from app.services.jev_runtime_settings_service import JevRuntimeSettingsService


_ANSWER_ADAPTER = TypeAdapter(SystemOneAnswer)


class JevOnlineSkillRunner:
    """Connect Job-level idempotency to the shared bounded Jev run machinery."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.store = JevOnlineSkillStore(db)
        self.runs = JevRunService(db)

    def start(
        self,
        *,
        job_id: UUID,
        case: OnlineSkillCase,
    ) -> JevOnlineSkillClassification:
        settings = JevRuntimeSettingsService(self.db).get_or_create()
        dispatch = self.dispatch(case)
        reservation = self.store.reserve(
            job_id=job_id,
            case=case,
            dispatch=dispatch,
        )
        record = reservation.record
        if not reservation.created or record.jev_run_id is not None:
            return record
        try:
            run = self.runs.start(
                purpose=f"online_skill:{record.id}",
                rubric_version=case.rubric_version,
                items=(
                    {
                        "subject_id": str(job_id),
                        "evidence_refs": [dispatch.input_fingerprint],
                        "payload": {
                            "state": dispatch.request.state,
                            "questions": {
                                name: question.model_dump(exclude_none=True)
                                for name, question in dispatch.request.questions.items()
                            },
                        },
                    },
                ),
            )
        except JevRunConfigurationError as error:
            error_code = _configuration_error_code(str(error))
            routing = route_online_skill_result(
                case,
                SystemOneResult(
                    status="unavailable",
                    model=settings.model,
                    error_code=error_code,
                    error_message=str(error),
                ),
                input_fingerprint=dispatch.input_fingerprint,
                thresholds=OnlineSkillThresholds(
                    evidence_millis=settings.evidence_threshold_millis,
                    recommendation_millis=settings.recommendation_threshold_millis,
                ),
            )
            return self.store.complete(
                record.id,
                routing=routing,
                receipt={
                    "status": "unavailable",
                    "model": settings.model,
                    "error_code": error_code,
                    "error_message": str(error),
                },
            )
        record.jev_run_id = run.id
        self.db.flush()
        return record

    def dispatch(self, case: OnlineSkillCase):
        """Build the authoritative frozen dispatch/fingerprint for one case."""
        settings = JevRuntimeSettingsService(self.db).get_or_create()
        return build_online_skill_dispatch(
            case,
            model=settings.model,
            runtime_identity=_runtime_identity(settings),
        )

    async def execute(
        self,
        record_id: str,
        *,
        case: OnlineSkillCase,
        evaluator,
    ) -> JevOnlineSkillClassification:
        record = self.db.get(JevOnlineSkillClassification, record_id)
        if record is None:
            raise ValueError("online Skill classification does not exist")
        if record.status in {"answered", "unavailable", "invalid"}:
            return record
        if record.jev_run_id is None:
            raise ValueError("online Skill classification has no bounded Jev run")
        self.store.mark_running(record.id)
        try:
            item = await self.runs.execute_next(record.jev_run_id, evaluator=evaluator)
        except JevBudgetExhaustedError:
            routing = route_online_skill_result(
                case,
                SystemOneResult(
                    status="unavailable",
                    error_code="jev_allowance_exhausted",
                    error_message="Jev allowance cannot cover another request",
                ),
                input_fingerprint=record.input_fingerprint,
                thresholds=OnlineSkillThresholds(
                    evidence_millis=900,
                    recommendation_millis=900,
                ),
            )
            return self.store.complete(
                record.id,
                routing=routing,
                receipt={
                    "status": "unavailable",
                    "error_code": "jev_allowance_exhausted",
                    "error_message": "Jev allowance cannot cover another request",
                },
            )
        if item is None:
            raise ValueError("online Skill bounded run has no executable item")
        run = self.runs.get(record.jev_run_id)
        result = _result_from_item(item)
        routing = route_online_skill_result(
            case,
            result,
            input_fingerprint=record.input_fingerprint,
            thresholds=OnlineSkillThresholds(
                evidence_millis=int(run.settings_snapshot["evidence_threshold_millis"]),
                recommendation_millis=int(
                    run.settings_snapshot["recommendation_threshold_millis"]
                ),
            ),
        )
        receipt = dict(item.result or {})
        if not receipt:
            receipt = {
                "status": result.status,
                "error_code": result.error_code,
                "model": result.model,
            }
        return self.store.complete(record.id, routing=routing, receipt=receipt)

    @staticmethod
    def projection_skills(
        record: JevOnlineSkillClassification,
    ) -> tuple[dict[str, object], ...]:
        routing = OnlineSkillRoutingResult(
            input_fingerprint=record.input_fingerprint,
            status=record.status,
            apply_projection=bool(record.apply_projection),
            decisions=tuple(
                RoutedSkillDecision.model_validate(decision)
                for decision in (record.decisions or [])
            ),
            error_code=record.error_code,
        )
        return build_projection_skills(routing)

    def retry(self, record_id: str) -> JevOnlineSkillClassification:
        record = self.db.get(JevOnlineSkillClassification, record_id)
        if record is None:
            raise ValueError("online Skill classification does not exist")
        if record.jev_run_id is None:
            raise ValueError("configuration-only failure requires changed Settings")
        self.runs.retry_failed(record.jev_run_id)
        return self.store.prepare_retry(record.id)


def _result_from_item(item) -> SystemOneResult:
    receipt = item.result or {}
    if item.status != "completed":
        status = (
            "invalid"
            if item.error_code in {"invalid_response", "answer_mismatch"}
            else "unavailable"
        )
        return SystemOneResult(
            status=status,
            error_code=item.error_code or status,
            error_message=item.error_message,
        )
    answers = {
        str(name): _ANSWER_ADAPTER.validate_python(answer)
        for name, answer in (receipt.get("answers") or {}).items()
    }
    usage_payload = receipt.get("usage")
    usage = (
        SystemOneUsage.model_validate(usage_payload)
        if isinstance(usage_payload, dict)
        else None
    )
    return SystemOneResult(
        status="answered",
        request_id=_optional(receipt.get("request_id")),
        model=_optional(receipt.get("model")),
        provider=_optional(receipt.get("provider")),
        answers=answers,
        usage=usage,
        latency_ms=(
            int(receipt["latency_ms"])
            if isinstance(receipt.get("latency_ms"), int)
            else None
        ),
    )


def _optional(value: object) -> str | None:
    return str(value) if value is not None else None


def _runtime_identity(settings) -> dict[str, object]:
    return {
        "enabled": bool(settings.enabled),
        "endpoint": settings.endpoint,
        "model": settings.model,
        "api_key_fingerprint": (
            hashlib.sha256(settings.api_key.encode("utf-8")).hexdigest()
            if settings.api_key
            else None
        ),
        "allowance_microdollars": settings.allowance_microdollars,
        "max_request_reservation_microdollars": (
            settings.max_request_reservation_microdollars
        ),
        "evidence_threshold_millis": settings.evidence_threshold_millis,
        "recommendation_threshold_millis": settings.recommendation_threshold_millis,
    }


def _configuration_error_code(message: str) -> str:
    if message == "Jev is disabled":
        return "jev_disabled"
    if message == "Jev API key is missing":
        return "jev_api_key_missing"
    if message == "Jev maximum request reservation is required":
        return "jev_reservation_missing"
    return "jev_configuration_error"


__all__ = ["JevOnlineSkillRunner"]
