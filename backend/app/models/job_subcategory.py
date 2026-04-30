from sqlalchemy import Boolean, Column, String, Text, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime

from app.database import Base


class JobSubcategory(Base):
    """Level 3: Job Subcategories (e.g., Web Development, Mobile Development)"""

    __tablename__ = "job_subcategories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category_id = Column(UUID(as_uuid=True), ForeignKey("job_categories.id", ondelete="CASCADE"), nullable=False, index=True)
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
    category = relationship("JobCategory", back_populates="subcategories")
    jobs = relationship("Job", back_populates="subcategory")

    __table_args__ = (
        UniqueConstraint('category_id', 'name', name='uq_job_subcategory_category_name'),
    )
