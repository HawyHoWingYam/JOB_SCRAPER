"""Shared contracts for governed Job Intelligence modules."""

from app.job_intelligence.foundation.audit import (
    AuditEvent,
    AuditPage,
    AuditQuery,
    AuditReader,
)
from app.job_intelligence.foundation.contracts import (
    LOCAL_OPERATOR,
    DecisionCommand,
    DecisionEffect,
    DecisionResult,
    DecisionTransition,
    OutboxEvent,
    Provenance,
    RevisionManifest,
    RevisionRef,
)
from app.job_intelligence.foundation.decisions import GovernanceUnitOfWork
from app.job_intelligence.foundation.errors import (
    DecisionContractError,
    DecisionSubjectNotFoundError,
    GovernanceError,
    IdempotencyConflictError,
    InvalidDecisionActorError,
    RevisionConflictError,
    StaleDecisionVersionError,
    UnconfirmedDecisionError,
)
from app.job_intelligence.foundation.hashing import normalized_content_hash
from app.job_intelligence.foundation.revisions import RevisionStore
from app.job_intelligence.foundation.seed_validation import (
    SeedIssue,
    SeedRule,
    SeedValidator,
    ValidationReport,
)

__all__ = [
    "AuditEvent",
    "AuditPage",
    "AuditQuery",
    "AuditReader",
    "LOCAL_OPERATOR",
    "DecisionCommand",
    "DecisionContractError",
    "DecisionEffect",
    "DecisionResult",
    "DecisionSubjectNotFoundError",
    "DecisionTransition",
    "GovernanceError",
    "GovernanceUnitOfWork",
    "IdempotencyConflictError",
    "InvalidDecisionActorError",
    "OutboxEvent",
    "Provenance",
    "RevisionConflictError",
    "RevisionManifest",
    "RevisionRef",
    "RevisionStore",
    "StaleDecisionVersionError",
    "SeedIssue",
    "SeedRule",
    "SeedValidator",
    "ValidationReport",
    "UnconfirmedDecisionError",
    "normalized_content_hash",
]
