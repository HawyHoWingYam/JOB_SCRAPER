from sqlalchemy import Column, String, Text, DateTime, Boolean, JSON, UUID
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base
import uuid


class Company(Base):
    """Company model for storing JobsDB company information."""

    __tablename__ = "companies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    company_id = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False, unique=True)
    industry = Column(String(255), nullable=True)
    location = Column(String(255), nullable=True)
    ai_description = Column(Text, nullable=True)
    extra_data = Column("metadata", JSON, nullable=True)
    is_deleted = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    jobs = relationship("Job", back_populates="company", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Company(id={self.id}, name={self.name})>"
