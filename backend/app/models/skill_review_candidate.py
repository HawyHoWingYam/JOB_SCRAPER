from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class SkillReviewCandidate(Base):
    """Unresolved technical skills that require taxonomy review."""

    __tablename__ = "skill_review_candidates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    raw_name = Column(String(100), nullable=False)
    normalized_name = Column(String(100), nullable=False, unique=True, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    suggested_category = Column(String(100), nullable=True)
    suggested_technology = Column(String(100), nullable=True)
    occurrence_count = Column(Integer, nullable=False, default=1)
    first_seen_job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=True)
    last_seen_job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
