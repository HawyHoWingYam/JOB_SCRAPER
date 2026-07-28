from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional
from datetime import datetime
from uuid import UUID

from app.schemas.current_taxonomy import CurrentCompanyIndustryStateSchema
from app.schemas.job import JobIntelligenceDomainAvailabilitySchema
from app.company_website import normalize_company_website


class CompanyCreateSchema(BaseModel):
    """Schema for creating a new company.

    When creating via the UI, ``company_id`` can be omitted; the server
    auto-generates one (``manual:<uuid>``).  The ``name`` field is always
    required.
    """

    model_config = ConfigDict(extra="forbid")

    company_id: Optional[str] = None
    name: str = Field(min_length=1, max_length=255)
    website: Optional[str] = Field(default=None, max_length=2048)
    industry: Optional[str] = Field(default=None, max_length=255)
    location: Optional[str] = Field(default=None, max_length=255)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized

    @field_validator("website", mode="before")
    @classmethod
    def _normalize_website(cls, value):
        return normalize_company_website(value)

    @field_validator("industry", "location", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value):
        normalized = str(value or "").strip()
        return normalized or None


class CompanySchema(CompanyCreateSchema):
    """Schema for company response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ai_description: Optional[str] = None
    ai_description_updated_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class CompanyProductSchema(CompanySchema):
    """Company response with scoped governed Industry state."""

    company_industries: Optional[CurrentCompanyIndustryStateSchema]
    company_industry_availability: JobIntelligenceDomainAvailabilitySchema
