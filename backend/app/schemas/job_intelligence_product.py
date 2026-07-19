from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.company import CompanyProductSchema
from app.schemas.job import JobDetailSchema
from app.schemas.job_intelligence import GovernanceAuditPageSchema
from app.schemas.job_search import FilterOptionsResponse, JobSearchResponse
from app.schemas.recommendations import JobRecommendationsResponse


class TrustedLocalOperationSchema(BaseModel):
    actor: Literal["local-operator"]
    authentication: Literal["none"]
    warning: str


class GovernanceAreaSummarySchema(BaseModel):
    key: Literal["job_taxonomy", "skill_candidates", "company_industries"]
    label: str
    available: bool
    pending_count: int
    oldest_pending_at: datetime | None
    active_revision_id: UUID | None
    unavailable_code: str | None
    deep_link: str


class JobIntelligenceCoverageSchema(BaseModel):
    total_jobs: int
    jobs_with_source_classification_paths: int
    jobs_with_employment_types: int
    jobs_with_canonical_assignment: int
    jobs_without_canonical_assignment: int
    jobs_with_unassigned_canonical_state: int
    jobs_with_unknown_canonical_state: int
    canonical_unassigned_reasons: dict[str, int]
    jobs_with_governed_skills: int
    jobs_with_unreviewed_skill_mentions: int
    total_companies: int
    companies_with_governed_industries: int
    companies_without_governed_industries: int


class JobIntelligenceGovernanceSummarySchema(BaseModel):
    generated_at: datetime
    trusted_local: TrustedLocalOperationSchema
    total_pending: int
    areas: list[GovernanceAreaSummarySchema]
    coverage: JobIntelligenceCoverageSchema


class JobIntelligenceProductFixtureSchema(BaseModel):
    summary: JobIntelligenceGovernanceSummarySchema
    canonical_audit: GovernanceAuditPageSchema
    job_filters: FilterOptionsResponse
    job_search: JobSearchResponse
    companies: list[CompanyProductSchema]
    job_detail: JobDetailSchema
    job_recommendations: JobRecommendationsResponse


__all__ = [
    "GovernanceAreaSummarySchema",
    "JobIntelligenceCoverageSchema",
    "JobIntelligenceGovernanceSummarySchema",
    "JobIntelligenceProductFixtureSchema",
    "TrustedLocalOperationSchema",
]
