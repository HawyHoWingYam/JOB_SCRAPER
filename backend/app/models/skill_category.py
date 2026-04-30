from sqlalchemy import Boolean, Column, String, Text, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime

from app.database import Base


class SkillCategory(Base):
    """Level 1: Skill Categories (e.g., Frontend, Backend, DevOps)"""

    __tablename__ = "skill_categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), unique=True, nullable=False, index=True)
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
    technologies = relationship("SkillTechnology", back_populates="category", cascade="all, delete-orphan")
