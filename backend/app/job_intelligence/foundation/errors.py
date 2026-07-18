from __future__ import annotations

from typing import Any


class GovernanceError(RuntimeError):
    """Stable failure raised by the Job Intelligence governance foundation."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = dict(context or {})

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            **({"context": self.context} if self.context else {}),
        }


class RevisionConflictError(GovernanceError):
    def __init__(self, *, domain: str, release_key: str) -> None:
        super().__init__(
            "GOVERNANCE_REVISION_CONFLICT",
            "Revision release key or content hash is already bound to different content",
            context={"domain": domain, "release_key": release_key},
        )


class UnconfirmedDecisionError(GovernanceError):
    def __init__(self) -> None:
        super().__init__(
            "GOVERNANCE_DECISION_UNCONFIRMED",
            "Governance decisions require explicit confirmation",
        )


class InvalidDecisionActorError(GovernanceError):
    def __init__(self, actor: str) -> None:
        super().__init__(
            "GOVERNANCE_DECISION_ACTOR_INVALID",
            "Trusted-local governance decisions must use local-operator",
            context={"actor": actor},
        )


class DecisionSubjectNotFoundError(GovernanceError):
    def __init__(self, *, subject_type: str, subject_id: str) -> None:
        super().__init__(
            "GOVERNANCE_DECISION_SUBJECT_NOT_FOUND",
            "Governance decision subject was not found",
            context={"subject_type": subject_type, "subject_id": subject_id},
        )


class StaleDecisionVersionError(GovernanceError):
    def __init__(self, *, expected_version: int, current_version: int) -> None:
        super().__init__(
            "GOVERNANCE_DECISION_STALE_VERSION",
            "Governance decision expected version is stale",
            context={
                "expected_version": expected_version,
                "current_version": current_version,
            },
        )


class IdempotencyConflictError(GovernanceError):
    def __init__(self, *, domain: str, idempotency_key: str) -> None:
        super().__init__(
            "GOVERNANCE_IDEMPOTENCY_CONFLICT",
            "Idempotency key was already used for a different decision command",
            context={"domain": domain, "idempotency_key": idempotency_key},
        )


class DecisionContractError(GovernanceError):
    def __init__(self, message: str) -> None:
        super().__init__("GOVERNANCE_DECISION_CONTRACT_INVALID", message)
