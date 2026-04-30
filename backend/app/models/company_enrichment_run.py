from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import relationship

from app.database import Base


class CompanyEnrichmentRun(Base):
    """Tracks a persisted company enrichment orchestration run."""

    __tablename__ = "company_enrichment_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    status = Column(String(32), nullable=False, default="pending", index=True)
    total_items = Column(Integer, nullable=False)
    pending_items = Column(Integer, nullable=False)
    completed_items = Column(Integer, nullable=False, default=0)
    failed_items = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    current_company_name = Column(String(255), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    items = relationship(
        "CompanyEnrichmentRunItem",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="CompanyEnrichmentRunItem.position",
    )


class CompanyEnrichmentRunItem(Base):
    """Tracks each company inside a persisted company enrichment run."""

    __tablename__ = "company_enrichment_run_items"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(
        String(36),
        ForeignKey("company_enrichment_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=False,
        index=True,
    )
    position = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    run = relationship("CompanyEnrichmentRun", back_populates="items")
