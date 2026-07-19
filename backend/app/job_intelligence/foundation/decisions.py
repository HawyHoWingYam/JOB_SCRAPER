from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.job_intelligence.foundation.contracts import (
    LOCAL_OPERATOR,
    DecisionCommand,
    DecisionResult,
    DecisionTransition,
)
from app.job_intelligence.foundation.errors import (
    DecisionContractError,
    DecisionSubjectNotFoundError,
    IdempotencyConflictError,
    InvalidDecisionActorError,
    StaleDecisionVersionError,
    UnconfirmedDecisionError,
)
from app.job_intelligence.foundation.hashing import (
    json_payload,
    normalized_content_hash,
)
from app.models.governance import (
    GovernanceAuditEvent,
    GovernanceIdempotencyRecord,
)
from app.repositories.event_outbox_repository import EventOutboxRepository


class GovernanceUnitOfWork:
    """Execute one domain-owned human decision as a single database transaction."""

    def __init__(
        self,
        db: Session,
        *,
        outbox_repository: EventOutboxRepository | None = None,
    ) -> None:
        self.db = db
        self.outbox_repository = outbox_repository or EventOutboxRepository()

    def _lock_idempotency_key(self, domain: str, idempotency_key: str) -> None:
        bind = self.db.get_bind()
        if bind.dialect.name == "postgresql":
            self.db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
                {"lock_key": f"{domain}:{idempotency_key}"},
            )

    def _stored_result(
        self,
        *,
        domain: str,
        idempotency_key: str,
        command_hash: str,
    ) -> DecisionResult | None:
        record = (
            self.db.query(GovernanceIdempotencyRecord)
            .filter(
                GovernanceIdempotencyRecord.domain == domain,
                GovernanceIdempotencyRecord.idempotency_key == idempotency_key,
            )
            .with_for_update()
            .one_or_none()
        )
        if record is None:
            return None
        if record.command_hash != command_hash:
            raise IdempotencyConflictError(
                domain=domain,
                idempotency_key=idempotency_key,
            )
        return DecisionResult.from_payload(record.result_payload, replayed=True)

    def execute(
        self,
        command: DecisionCommand,
        transition: DecisionTransition[Any],
    ) -> DecisionResult:
        try:
            if not command.confirmed:
                raise UnconfirmedDecisionError()
            if command.actor != LOCAL_OPERATOR:
                raise InvalidDecisionActorError(command.actor)

            command_hash = normalized_content_hash(
                {
                    "domain": transition.domain,
                    "subject_type": transition.subject_type,
                    "command": command.to_payload(),
                }
            )
            self._lock_idempotency_key(
                transition.domain,
                command.idempotency_key,
            )
            replay = self._stored_result(
                domain=transition.domain,
                idempotency_key=command.idempotency_key,
                command_hash=command_hash,
            )
            if replay is not None:
                self.db.commit()
                return replay

            subject = transition.load_for_update(self.db, command.subject_id)
            if subject is None:
                raise DecisionSubjectNotFoundError(
                    subject_type=transition.subject_type,
                    subject_id=command.subject_id,
                )
            current_version = transition.version(subject)
            if current_version != command.expected_version:
                raise StaleDecisionVersionError(
                    expected_version=command.expected_version,
                    current_version=current_version,
                )

            before_summary = json_payload(transition.snapshot(subject))
            effect = transition.apply(self.db, subject, command)
            if not effect.outbox_events:
                raise DecisionContractError(
                    "Domain transition must emit at least one outbox event"
                )
            self.db.flush()
            current_after_version = transition.version(subject)
            if effect.version != current_after_version:
                raise DecisionContractError(
                    "Domain transition result version does not match its subject"
                )
            if effect.version <= command.expected_version:
                raise DecisionContractError(
                    "Domain transition must advance the subject version"
                )
            after_summary = json_payload(effect.subject)
            if after_summary != json_payload(transition.snapshot(subject)):
                raise DecisionContractError(
                    "Domain transition result subject does not match its persisted subject"
                )
            evidence_refs = json_payload(effect.evidence_refs)

            audit = GovernanceAuditEvent(
                domain=transition.domain,
                subject_type=transition.subject_type,
                subject_id=command.subject_id,
                action=command.action,
                actor=command.actor,
                command_hash=command_hash,
                idempotency_key=command.idempotency_key,
                before_summary=before_summary,
                after_summary=after_summary,
                evidence_refs=evidence_refs,
                correlation_id=command.correlation_id or command.idempotency_key,
            )
            self.db.add(audit)
            self.db.flush()
            attach_audit_reference = getattr(
                transition,
                "attach_audit_reference",
                None,
            )
            if attach_audit_reference is not None:
                attach_audit_reference(self.db, subject, audit.id)
                self.db.flush()

            for event in effect.outbox_events:
                payload = {
                    **json_payload(event.payload),
                    "governance_audit_event_id": str(audit.id),
                    "governance_idempotency_key": command.idempotency_key,
                }
                self.outbox_repository.enqueue(
                    self.db,
                    topic=event.topic,
                    aggregate_type=event.aggregate_type,
                    aggregate_id=event.aggregate_id,
                    event_type=event.event_type,
                    source_service=event.source_service,
                    payload=payload,
                    auto_commit=False,
                )

            result = DecisionResult(
                subject=after_summary,
                resulting_projection=(
                    json_payload(effect.resulting_projection)
                    if effect.resulting_projection is not None
                    else None
                ),
                audit_event_id=audit.id,
                version=effect.version,
                replayed=False,
            )
            self.db.add(
                GovernanceIdempotencyRecord(
                    domain=transition.domain,
                    idempotency_key=command.idempotency_key,
                    command_hash=command_hash,
                    audit_event_id=audit.id,
                    result_payload=result.to_payload(),
                )
            )
            self.db.flush()
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise
