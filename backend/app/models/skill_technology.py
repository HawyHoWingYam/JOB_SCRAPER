from sqlalchemy import Boolean, Column, String, Text, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime

from app.database import Base


class SkillTechnology(Base):
    """Level 2: Skill Technologies (e.g., JavaScript, Python, Docker)"""

    __tablename__ = "skill_technologies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category_id = Column(UUID(as_uuid=True), ForeignKey("skill_categories.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False, index=True)
    description = Column(Text, nullable=True)
    created_by = Column(String(20), default="seed", nullable=False, index=True)
    is_auto_created = Column(Boolean, default=False, nullable=False, index=True)
    is_filter_visible = Column(Boolean, default=False, nullable=False, index=True)
    usage_count = Column(Integer, default=0, nullable=False)
    distinct_job_count = Column(Integer, default=0, nullable=False, index=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    category = relationship("SkillCategory", back_populates="technologies")
    skills = relationship("Skill", back_populates="technology", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('category_id', 'name', name='uq_skill_technology_category_name'),
    )
