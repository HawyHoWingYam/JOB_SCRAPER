from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Literal, Optional, List

from app.job_intelligence.source_attributes import EMPLOYMENT_TYPE_SEEDS
from app.schemas.job import (
    EmploymentTypeCode,
    EmploymentTypeSchema,
    JobIntelligenceDomainAvailabilitySchema,
    JobTaxonomySchema,
    SourceClassificationPathSchema,
)
from app.schemas.job_intelligence import CanonicalJobStateSchema

SourceSiteFilter = Literal["jobsdb", "ctgoodjobs", "offertoday"]
_EMPLOYMENT_TYPE_CODE_BY_LABEL = {
    label.casefold(): code for code, label, _sort_order in EMPLOYMENT_TYPE_SEEDS
}


class SearchClauseSchema(BaseModel):
    clause_type: str
    value: str


class LocationHierarchyItem(BaseModel):
    region: str
    districts: List[str]


class EmploymentTypeOption(BaseModel):
    code: str
    label: str
    order: int


class SourceClassificationOption(BaseModel):
    id: str
    label: str
    source: str
    path: str


class FilterOptionsResponse(BaseModel):
    locations: List[str]
    regions: List[str]
    location_hierarchy: List[LocationHierarchyItem]
    employment_types: List[EmploymentTypeOption]
    source_classifications: List[SourceClassificationOption]
    industries: List[str]


class JobSearchFiltersSchema(BaseModel):
    source_site: Optional[SourceSiteFilter] = None
    location: Optional[str] = None
    region: Optional[str] = None
    district: Optional[str] = None
    employment_type: Optional[str] = None
    source_classification_ids: Optional[List[str]] = None
    employment_type_codes: Optional[List[EmploymentTypeCode]] = None
    industry: Optional[str] = None
    posted_date_from: Optional[date] = None
    posted_date_to: Optional[date] = None
    experience_years_from: Optional[int] = Field(default=None, ge=0)
    experience_years_to: Optional[int] = Field(default=None, ge=0)
    skills: Optional[List[str]] = None
    skill_ids: Optional[List[str]] = None
    technology_ids: Optional[List[str]] = None
    skill_category_ids: Optional[List[str]] = None
    canonical_subcategory_ids: Optional[List[str]] = None
    canonical_category_ids: Optional[List[str]] = None
    canonical_domain_ids: Optional[List[str]] = None
    company_industry_node_ids: Optional[List[str]] = None
    subcategory_ids: Optional[List[str]] = None
    job_category_ids: Optional[List[str]] = None
    domain_ids: Optional[List[str]] = None
    salary_min: Optional[int] = Field(default=None, ge=0)
    salary_max: Optional[int] = Field(default=None, ge=0)

    @field_validator(
        "posted_date_from",
        "posted_date_to",
        "experience_years_from",
        "experience_years_to",
        "salary_min",
        "salary_max",
        mode="before",
    )
    @classmethod
    def _coerce_blank_optionals_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("source_site", mode="before")
    @classmethod
    def _normalize_source_site(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized or None
        return value

    @field_validator("source_classification_ids", mode="before")
    @classmethod
    def _validate_source_classification_ids(cls, value):
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("source_classification_ids must be an array")
        normalized: list[str] = []
        for raw_value in value:
            classification_id = str(raw_value or "").strip()
            prefix, separator, token = classification_id.partition(":")
            if (
                separator != ":"
                or prefix not in {"jobsdb", "ctgoodjobs", "offertoday"}
                or not token
                or not token[0].isalnum()
                or any(
                    not (character.isalnum() or character in {".", "_", "-"})
                    for character in token
                )
            ):
                raise ValueError(
                    f"Invalid Source Classification identity: {classification_id}"
                )
            if classification_id not in normalized:
                normalized.append(classification_id)
        return normalized or None

    @model_validator(mode="after")
    def _translate_legacy_employment_type(self):
        legacy_label = str(self.employment_type or "").strip()
        if not legacy_label:
            self.employment_type = None
            return self
        legacy_code = _EMPLOYMENT_TYPE_CODE_BY_LABEL.get(legacy_label.casefold())
        if legacy_code is None:
            raise ValueError(
                "employment_type must be one recognized Employment Type label"
            )
        codes = list(self.employment_type_codes or [])
        if legacy_code not in codes:
            codes.append(legacy_code)
        self.employment_type_codes = codes
        return self


class JobSearchLayerSchema(BaseModel):
    client_id: str
    text_expression: str = ""
    structured_filters: JobSearchFiltersSchema = Field(default_factory=JobSearchFiltersSchema)


class JobSearchScopeSchema(BaseModel):
    layers: List[JobSearchLayerSchema] = Field(default_factory=list)


class JobSearchRequestSchema(BaseModel):
    scope: JobSearchScopeSchema
    retrieval_mode: Literal["lexical", "semantic", "hybrid"] = "lexical"
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class JobSearchLayerSummarySchema(BaseModel):
    client_id: str
    label: str


class JobSearchErrorSchema(BaseModel):
    code: str
    message: str
    position: int
    token: str


class JobWithCompanySchema(BaseModel):
    """Governed Job Browser card contract."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: str
    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    salary_range: Optional[str] = None
    employment_type: Optional[str] = None
    subcategory_id: Optional[UUID] = None
    job_taxonomy: Optional[JobTaxonomySchema] = None
    company_name: Optional[str] = None
    posted_date: Optional[str] = None
    source_classification_paths: List[SourceClassificationPathSchema] = Field(
        default_factory=list
    )
    employment_types: List[EmploymentTypeSchema] = Field(default_factory=list)
    canonical_taxonomy: Optional[CanonicalJobStateSchema]
    canonical_taxonomy_availability: JobIntelligenceDomainAvailabilitySchema


class JobSearchResponse(BaseModel):
    """Paginated Job Browser response contract."""

    jobs: List[JobWithCompanySchema]
    total: int
    page: int
    page_size: int
    total_pages: int
    applied_scope: Optional[JobSearchScopeSchema] = None
    layer_summaries: Optional[List[JobSearchLayerSummarySchema]] = None
