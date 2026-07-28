from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utc_now


class ManualJobEvidence(Base):
    """Current operator-authored evidence and enrichment freshness for a Manual Job."""

    __tablename__ = "manual_job_evidence"
    __table_args__ = (
        CheckConstraint(
            "length(evidence_hash) = 64",
            name="ck_manual_job_evidence_hash",
        ),
        CheckConstraint(
            "enriched_evidence_hash IS NULL OR length(enriched_evidence_hash) = 64",
            name="ck_manual_job_enriched_evidence_hash",
        ),
    )

    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    evidence_hash = Column(String(64), nullable=False)
    enriched_evidence_hash = Column(String(64), nullable=True)
    operator_authored_fields = Column(JSON, nullable=False, default=list)
    captured_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    job = relationship("Job", back_populates="manual_evidence")


class ManualJobMutationReceipt(Base):
    """Immutable first result for one Manual Job mutation idempotency key."""

    __tablename__ = "manual_job_mutation_receipts"
    __table_args__ = (
        CheckConstraint(
            "length(command_hash) = 64",
            name="ck_manual_job_mutation_command_hash",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    idempotency_key = Column(String(255), nullable=False, unique=True, index=True)
    command_hash = Column(String(64), nullable=False)
    command_kind = Column(String(16), nullable=False)
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
