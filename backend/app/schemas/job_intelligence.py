from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.job_intelligence.foundation import AuditPage


class GovernanceAuditEventSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    domain: str
    subject_type: str
    subject_id: str
    action: str
    actor: str
    command_hash: str
    idempotency_key: str
    before_summary: dict[str, Any]
    after_summary: dict[str, Any]
    evidence_refs: list[dict[str, Any]]
    correlation_id: str
    created_at: datetime


class GovernanceAuditPageSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[GovernanceAuditEventSchema]
    next_cursor: str | None

    @classmethod
    def from_contract(cls, page: AuditPage) -> GovernanceAuditPageSchema:
        return cls.model_validate(page)
