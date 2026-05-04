from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class JobSkillMention(Base):
    __tablename__ = "job_skill_mentions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    raw_name = Column(String(100), nullable=False)
    normalized_name = Column(String(100), nullable=False, index=True)
    resolution = Column(String(32), nullable=False, index=True)
    skill_id = Column(
        UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    review_candidate_id = Column(
        UUID(as_uuid=True),
        ForeignKey("skill_review_candidates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    generic_tag = Column(String(100), nullable=True)
    source = Column(String(50), nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    job = relationship("Job", back_populates="job_skill_mentions")
    skill = relationship("Skill")
    review_candidate = relationship("SkillReviewCandidate")
