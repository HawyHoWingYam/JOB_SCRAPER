from collections.abc import Mapping
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator
from pydantic import model_validator
from typing import Annotated, Any, Literal, Optional, Union
from datetime import datetime
from uuid import UUID

from app.schemas.current_taxonomy import CurrentJobSkillStateSchema
from app.company_website import normalize_company_website


EmploymentTypeCode = Literal[
    "full_time",
    "part_time",
    "permanent",
    "contract",
    "temporary",
    "internship",
    "freelance",
]

SUPPORTED_MANUAL_SALARY_CURRENCIES = frozenset(
    {"AUD", "CAD", "CNY", "EUR", "GBP", "HKD", "JPY", "SGD", "USD"}
)


class JobCreateSchema(BaseModel):
    """Schema for creating a new job."""

    job_id: str
    company_id: UUID
    title: str
    description: Optional[str] = None
    source_classification_id: Optional[str] = None
    source_classification_name: Optional[str] = None
    source_subclassification_id: Optional[str] = None
    source_subclassification_name: Optional[str] = None
    ai_summary: Optional[str] = None
    salary_range: Optional[str] = None
    location: Optional[str] = None
    employment_type: Optional[str] = None
    posted_date: Optional[datetime] = None


class ExistingCompanyChoiceSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["existing"]
    company_id: UUID


class NewCompanyChoiceSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["new"]
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
    def _normalize_company_optional_text(cls, value):
        normalized = str(value or "").strip()
        return normalized or None


ManualCompanyChoiceSchema = Annotated[
    Union[ExistingCompanyChoiceSchema, NewCompanyChoiceSchema],
    Field(discriminator="mode"),
]


class ManualJobCreateSchema(BaseModel):
    """Atomic Manual Job mutation command used by Add Job and Manual editing."""

    model_config = ConfigDict(extra="forbid")

    company: ManualCompanyChoiceSchema
    title: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    salary_min: Optional[int] = Field(default=None, ge=0)
    salary_max: Optional[int] = Field(default=None, ge=0)
    salary_currency: str = Field(default="HKD", min_length=3, max_length=3)
    location: Optional[str] = Field(default=None, max_length=255)
    employment_type_codes: list[EmploymentTypeCode] = Field(default_factory=list)
    posted_date: Optional[datetime] = None
    experience_min_years: Optional[int] = Field(default=None, ge=0)
    experience_max_years: Optional[int] = Field(default=None, ge=0)
    duplicate_confirmation: Optional[str] = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern="^[0-9a-f]{64}$",
    )

    @field_validator("title")
    @classmethod
    def _normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("title must not be blank")
        return normalized

    @field_validator("description", "location", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value):
        normalized = str(value or "").strip()
        return normalized or None

    @field_validator("salary_currency")
    @classmethod
    def _normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in SUPPORTED_MANUAL_SALARY_CURRENCIES:
            supported = ", ".join(sorted(SUPPORTED_MANUAL_SALARY_CURRENCIES))
            raise ValueError(f"salary_currency must be one of: {supported}")
        return normalized

    @field_validator("employment_type_codes")
    @classmethod
    def _deduplicate_employment_type_codes(cls, values):
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def _validate_ranges(self):
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("salary_min must not exceed salary_max")
        if (
            self.experience_min_years is not None
            and self.experience_max_years is not None
            and self.experience_min_years > self.experience_max_years
        ):
            raise ValueError(
                "experience_min_years must not exceed experience_max_years"
            )
        return self


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
    skills: JobIntelligenceDomainAvailabilitySchema = Field(
        default_factory=JobIntelligenceDomainAvailabilitySchema
    )


class JobSchema(JobCreateSchema):
    """Schema for job response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    source_classification_paths: list[SourceClassificationPathSchema] = Field(
        default_factory=list
    )
    employment_types: list[EmploymentTypeSchema] = Field(default_factory=list)


class JobDetailSchema(JobSchema):
    """Expanded schema for the job detail view."""

    original_job_url: Optional[str] = None
    company_name: Optional[str] = None
    company_ai_description: Optional[str] = None
    company_website: Optional[str] = None
    origin: str = "source"
    manual_editable: bool = False
    enrichment_eligibility: Literal[
        "pending", "needs_job_description", "current", "stale"
    ] = "pending"
    job_intelligence_freshness: Literal[
        "not_enriched", "current", "stale"
    ] = "not_enriched"
    ai_enriched_at: Optional[datetime] = None
    experience_min_years: Optional[int] = None
    experience_max_years: Optional[int] = None
    experience_level: Optional[str] = None
    experience_summary: Optional[str] = None
    experience_evidence: Optional[list[str]] = None
    expiry_date: Optional[str] = None
    is_expired: Optional[bool] = None
    skills: list[str] = Field(default_factory=list)
    source_employment_labels: list[SourceEmploymentLabelSchema] = Field(
        default_factory=list
    )
    skill_state: Optional[CurrentJobSkillStateSchema] = None
    job_intelligence_availability: JobIntelligenceAvailabilitySchema = Field(
        default_factory=JobIntelligenceAvailabilitySchema
    )

    @model_validator(mode="before")
    @classmethod
    def require_composed_governed_states(cls, value):
        if isinstance(value, Mapping):
            required_fields = {"skill_state", "job_intelligence_availability"}
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
