from collections.abc import Mapping
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator
from pydantic import model_validator
from typing import Any, Literal, Optional
from datetime import datetime
from uuid import UUID

from app.schemas.company_industry import CompanyIndustryCompanyStateSchema
from app.schemas.job_intelligence import CanonicalJobStateSchema
from app.schemas.skill_governance import (
    JobSkillStateSchema,
    SkillUnreviewedMentionSchema,
)


EmploymentTypeCode = Literal[
    "full_time",
    "part_time",
    "permanent",
    "contract",
    "temporary",
    "internship",
    "freelance",
]


class JobCreateSchema(BaseModel):
    """Schema for creating a new job."""

    job_id: str
    company_id: UUID
    title: str
    description: Optional[str] = None
    subcategory_id: Optional[UUID] = None
    source_classification_id: Optional[str] = None
    source_classification_name: Optional[str] = None
    source_subclassification_id: Optional[str] = None
    source_subclassification_name: Optional[str] = None
    ai_summary: Optional[str] = None
    salary_range: Optional[str] = None
    location: Optional[str] = None
    employment_type: Optional[str] = None
    posted_date: Optional[datetime] = None


class ManualJobCreateSchema(BaseModel):
    """Schema for manually creating a job through the UI."""

    company_id: UUID
    title: str
    description: Optional[str] = None
    salary_range: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: Optional[str] = "HKD"
    location: Optional[str] = None
    employment_type: Optional[str] = None
    employment_type_codes: list[EmploymentTypeCode] = Field(default_factory=list)
    posted_date: Optional[datetime] = None
    experience_min_years: Optional[int] = None
    experience_max_years: Optional[int] = None

    @field_validator("employment_type_codes")
    @classmethod
    def _deduplicate_employment_type_codes(cls, values):
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def _keep_legacy_and_governed_employment_inputs_separate(self):
        if str(self.employment_type or "").strip() and self.employment_type_codes:
            raise ValueError(
                "employment_type and employment_type_codes cannot be submitted together"
            )
        return self


class JobTaxonomySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    domain_id: UUID
    domain_name: str
    category_id: UUID
    category_name: str
    subcategory_id: UUID
    subcategory_name: str
    path: str


class SourceCatalogRevisionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_site: str
    revision_id: UUID
    fingerprint: str


class SourceClassificationNodeSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_position: int
    native_depth: int
    source_classification_id: str
    native_id: str
    label: str


class SourceClassificationPathSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_site: str
    source_order: int
    nodes: list[SourceClassificationNodeSchema] = Field(default_factory=list)
    is_primary: bool
    primary_basis: Optional[str] = None
    catalog_revision: Optional[SourceCatalogRevisionSchema] = None
    provenance_limited: bool
    provenance: dict[str, Any]


class EmploymentTypeSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    label: str
    sort_order: int


class SourceEmploymentLabelSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_site: str
    source_order: int
    raw_code: Optional[str] = None
    raw_label: Optional[str] = None
    normalized_lookup_key: Optional[str] = None
    mapped_type_code: Optional[str] = None
    mapping_id: Optional[str] = None
    provenance: dict[str, Any]


class JobIntelligenceDomainAvailabilitySchema(BaseModel):
    available: bool = False
    unavailable_code: Optional[str] = "JOB_INTELLIGENCE_NOT_COMPOSED"


class JobIntelligenceAvailabilitySchema(BaseModel):
    source_attributes: JobIntelligenceDomainAvailabilitySchema = Field(
        default_factory=JobIntelligenceDomainAvailabilitySchema
    )
    canonical_taxonomy: JobIntelligenceDomainAvailabilitySchema = Field(
        default_factory=JobIntelligenceDomainAvailabilitySchema
    )
    company_industries: JobIntelligenceDomainAvailabilitySchema = Field(
        default_factory=JobIntelligenceDomainAvailabilitySchema
    )
    skills: JobIntelligenceDomainAvailabilitySchema = Field(
        default_factory=JobIntelligenceDomainAvailabilitySchema
    )


class JobSchema(JobCreateSchema):
    """Schema for job response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime
    job_taxonomy: Optional[JobTaxonomySchema] = None
    source_classification_paths: list[SourceClassificationPathSchema] = Field(
        default_factory=list
    )
    employment_types: list[EmploymentTypeSchema] = Field(default_factory=list)


class JobDetailSchema(JobSchema):
    """Expanded schema for the job detail view."""

    original_job_url: Optional[str] = None
    company_name: Optional[str] = None
    company_industry: Optional[str] = None
    company_ai_description: Optional[str] = None
    ai_enriched_at: Optional[datetime] = None
    experience_min_years: Optional[int] = None
    experience_max_years: Optional[int] = None
    experience_level: Optional[str] = None
    experience_summary: Optional[str] = None
    experience_evidence: Optional[list[str]] = None
    expiry_date: Optional[str] = None
    is_expired: Optional[bool] = None
    skills: list[str] = Field(default_factory=list)
    provisional_skills: list[str] = Field(default_factory=list)
    unreviewed_skill_mentions: list[SkillUnreviewedMentionSchema] = Field(
        default_factory=list
    )
    source_employment_labels: list[SourceEmploymentLabelSchema] = Field(
        default_factory=list
    )
    canonical_taxonomy: Optional[CanonicalJobStateSchema] = None
    company_industries: Optional[CompanyIndustryCompanyStateSchema] = None
    skill_state: Optional[JobSkillStateSchema] = None
    job_intelligence_availability: JobIntelligenceAvailabilitySchema = Field(
        default_factory=JobIntelligenceAvailabilitySchema
    )

    @model_validator(mode="before")
    @classmethod
    def require_composed_governed_states(cls, value):
        if isinstance(value, Mapping):
            required_fields = {
                "canonical_taxonomy",
                "company_industries",
                "skill_state",
                "job_intelligence_availability",
            }
            missing = sorted(required_fields - set(value))
            if missing:
                raise ValueError(
                    "Job Detail is missing composed governed state fields: "
                    + ", ".join(missing)
                )
        return value

    @field_serializer("ai_enriched_at")
    def serialize_ai_enriched_at(self, value: Optional[datetime]) -> Optional[str]:
        return value.isoformat() if value is not None else None
