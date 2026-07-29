from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utc_now


class ClassificationBatchRun(Base):
    """One bounded automated classification run for a single domain."""

    __tablename__ = "classification_batch_runs"
    __table_args__ = (
        CheckConstraint(
            "domain IN ('company_industry', 'skill')",
            name="ck_classification_batch_run_domain",
        ),
        CheckConstraint("total_items >= 0", name="ck_classification_batch_run_total"),
        Index(
            "ux_classification_batch_run_active_domain",
            "domain",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running', 'stopping')"),
            sqlite_where=text("status IN ('pending', 'running', 'stopping')"),
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    domain = Column(String(32), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    filters = Column(JSON, nullable=False, default=dict)
    requested_limit = Column(Integer, nullable=False)
    total_items = Column(Integer, nullable=False)
    pending_items = Column(Integer, nullable=False)
    completed_items = Column(Integer, nullable=False, default=0)
    failed_items = Column(Integer, nullable=False, default=0)
    cancelled_items = Column(Integer, nullable=False, default=0)
    retry_of_run_id = Column(
        String(36),
        ForeignKey("classification_batch_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    started_at = Column(DateTime(timezone=True), nullable=True)
    stop_requested_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)

    items = relationship(
        "ClassificationBatchRunItem",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="ClassificationBatchRunItem.position",
        foreign_keys="ClassificationBatchRunItem.run_id",
    )


class ClassificationBatchRunItem(Base):
    """A stable subject snapshot processed by one classification run."""

    __tablename__ = "classification_batch_run_items"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "subject_id",
            name="uq_classification_batch_run_item_subject",
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(
        String(36),
        ForeignKey("classification_batch_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_id = Column(String(255), nullable=False, index=True)
    subject_label = Column(String(500), nullable=True)
    position = Column(Integer, nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    status = Column(String(32), nullable=False, default="pending", index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    error_code = Column(String(128), nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    run = relationship(
        "ClassificationBatchRun",
        back_populates="items",
        foreign_keys=[run_id],
    )


CLASSIFICATION_BATCH_TABLES = (
    ClassificationBatchRun.__table__,
    ClassificationBatchRunItem.__table__,
)


__all__ = [
    "CLASSIFICATION_BATCH_TABLES",
    "ClassificationBatchRun",
    "ClassificationBatchRunItem",
]
