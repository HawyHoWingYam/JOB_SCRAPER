from sqlalchemy import Boolean, Column, DateTime, JSON, String, Text, UUID, UniqueConstraint, text
from sqlalchemy.orm import deferred, relationship
from datetime import datetime
from app.database import Base
from app.utils.source_identity import derive_source_company_id_from_compat, normalize_source_site
import uuid


def _default_source_site(context) -> str:
    return normalize_source_site(context.get_current_parameters().get("source_site"))


def _default_source_company_id(context) -> str:
    params = context.get_current_parameters()
    source_site = normalize_source_site(params.get("source_site"))
    return derive_source_company_id_from_compat(source_site, params.get("company_id"))


class Company(Base):
    """Company model for storing JobsDB company information."""

    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("source_site", "source_company_id", name="uq_companies_source_company_key"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    company_id = Column(String(255), unique=True, nullable=False, index=True)
    source_site = deferred(
        Column(
            String(32),
            nullable=False,
            default=_default_source_site,
            server_default=text("'jobsdb'"),
            index=True,
        )
    )
    source_company_id = deferred(
        Column(
            String(255),
            nullable=False,
            default=_default_source_company_id,
            index=True,
        )
    )
    name = Column(String(255), nullable=False)
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
