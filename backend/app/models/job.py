from sqlalchemy import Column, String, Text, DateTime, Boolean, JSON, ForeignKey, UUID, Integer, text
from sqlalchemy.orm import relationship, deferred
from datetime import datetime, UTC
import json
from typing import Any, List, Optional
from app.database import Base
import uuid


class Job(Base):
    """Job model for storing JobsDB job listings."""

    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    job_id = Column(String(255), unique=True, nullable=False, index=True)
    # Added for source-aware routing. Deferred so lightweight sqlite test
    # fixtures that define a minimal `jobs` table can still query `Job` without
    # selecting this column, while production schemas include it.
    source_site = deferred(
        Column(
            String(32),
            nullable=False,
            default="jobsdb",
            server_default=text("'jobsdb'"),
            index=True,
        )
    )
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    subcategory_id = Column(UUID(as_uuid=True), ForeignKey("job_subcategories.id"), nullable=True, index=True)
    source_classification_id = Column(String(50), nullable=True, index=True)
    source_classification_name = Column(String(255), nullable=True, index=True)
    source_subclassification_id = Column(String(50), nullable=True, index=True)
    source_subclassification_name = Column(String(255), nullable=True, index=True)
    ai_category = Column(String(255), nullable=True, index=True)
    ai_summary = Column(Text, nullable=True)
    ai_enriched_at = Column(DateTime, nullable=True)
    experience_min_years = Column(Integer, nullable=True, index=True)
    experience_max_years = Column(Integer, nullable=True, index=True)
    experience_level = Column(String(50), nullable=True, index=True)
    experience_summary = Column(Text, nullable=True)
    _experience_evidence = Column(
        "experience_evidence",
        JSON,
        nullable=True,
    )
    salary_range = Column(String(255), nullable=True)
    salary_min = Column(Integer, nullable=True, index=True)
    salary_max = Column(Integer, nullable=True, index=True)
    salary_currency = Column(String(10), default='HKD', nullable=True)
    location = Column(String(255), nullable=True)
    employment_type = Column(String(100), nullable=True)
    raw_data = Column(JSON, nullable=True)
    search_vector = Column(String, nullable=True)
    posted_date = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    company = relationship("Company", back_populates="jobs")
    subcategory = relationship("JobSubcategory", back_populates="jobs")
    job_skills = relationship("JobSkill", back_populates="job", cascade="all, delete-orphan")

    @property
    def skills_list(self) -> List[str]:
        """Get skills from relational table"""
        return [js.skill.name for js in self.job_skills]

    @property
    def skills(self) -> List[str]:
        """Expose relational skills through the API without a legacy column."""
        return self.skills_list

    @property
    def company_name(self) -> Optional[str]:
        """Convenience field for job detail responses."""
        return self.company.name if self.company else None

    @property
    def company_industry(self) -> Optional[str]:
        return self.company.industry if self.company else None

    @property
    def company_ai_description(self) -> Optional[str]:
        return self.company.ai_description if self.company else None

    def _raw_data_mapping(self) -> Optional[dict[str, Any]]:
        value: Any = self.raw_data
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return None
            if isinstance(parsed, dict):
                return parsed
        return None

    def _coerce_raw_bool(self, value: Any) -> Optional[bool]:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes"}:
                return True
            if normalized in {"false", "0", "no"}:
                return False
        return None

    @property
    def experience_evidence(self) -> Optional[list[str]]:
        value: Any = self._experience_evidence
        if value is None:
            return None
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return [value]
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, str):
                return [parsed]
            return None
        return None

    @experience_evidence.setter
    def experience_evidence(self, value: Any) -> None:
        self._experience_evidence = value

    @property
    def expiry_date(self) -> Optional[str]:
        raw_data = self._raw_data_mapping()
        if raw_data is None:
            return None
        value = raw_data.get("expiry_date")
        if value:
            return value
        expires_at = raw_data.get("expiresAt")
        if isinstance(expires_at, dict):
            maybe_value = expires_at.get("dateTimeUtc")
            if isinstance(maybe_value, str):
                return maybe_value
        return None

    @property
    def is_expired(self) -> Optional[bool]:
        raw_data = self._raw_data_mapping()
        if raw_data is None:
            return None
        if "is_expired" in raw_data:
            parsed = self._coerce_raw_bool(raw_data.get("is_expired"))
            if parsed is not None:
                return parsed
        if "isExpired" in raw_data:
            parsed = self._coerce_raw_bool(raw_data.get("isExpired"))
            if parsed is not None:
                return parsed
        expiry_date = self.expiry_date
        if not expiry_date:
            return None
        normalized = expiry_date.replace("Z", "+00:00")
        try:
            expires_at = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at <= datetime.now(UTC)

    def __repr__(self):
        return f"<Job(id={self.id}, title={self.title})>"
