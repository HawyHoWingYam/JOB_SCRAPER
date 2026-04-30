from sqlalchemy import Boolean, Column, String, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime

from app.database import Base


class Skill(Base):
    """Level 3: Skills (e.g., React, Django, Kubernetes)"""

    __tablename__ = "skills"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    technology_id = Column(UUID(as_uuid=True), ForeignKey("skill_technologies.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False, index=True)
    aliases = Column(ARRAY(String), nullable=True)
    popularity = Column(Integer, default=0, index=True)
    created_by = Column(String(20), default="seed", nullable=False, index=True)
    is_auto_created = Column(Boolean, default=False, nullable=False, index=True)
    is_filter_visible = Column(Boolean, default=False, nullable=False, index=True)
    usage_count = Column(Integer, default=0, nullable=False)
    distinct_job_count = Column(Integer, default=0, nullable=False, index=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    technology = relationship("SkillTechnology", back_populates="skills")
    job_skills = relationship("JobSkill", back_populates="skill", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('technology_id', 'name', name='uq_skill_technology_name'),
    )
