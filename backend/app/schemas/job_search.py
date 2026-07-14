from datetime import date
from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional, List

SourceSiteFilter = Literal["jobsdb", "ctgoodjobs", "offertoday"]


class SearchClauseSchema(BaseModel):
    clause_type: str
    value: str


class JobSearchFiltersSchema(BaseModel):
    source_site: Optional[SourceSiteFilter] = None
    location: Optional[str] = None
    region: Optional[str] = None
    district: Optional[str] = None
    employment_type: Optional[str] = None
    industry: Optional[str] = None
    posted_date_from: Optional[date] = None
    posted_date_to: Optional[date] = None
    experience_years_from: Optional[int] = Field(default=None, ge=0)
    experience_years_to: Optional[int] = Field(default=None, ge=0)
    skills: Optional[List[str]] = None
    skill_ids: Optional[List[str]] = None
    technology_ids: Optional[List[str]] = None
    skill_category_ids: Optional[List[str]] = None
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
