from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class _CurrentTaxonomySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CurrentTaxonomyNodeSchema(_CurrentTaxonomySchema):
    code: str
    parent_code: str | None
    level: str
    labels: dict[str, str]
    order: int
    is_assignable: bool


class CurrentTaxonomyTreeSchema(_CurrentTaxonomySchema):
    taxonomy: Literal["company_industry", "skill"]
    nodes: list[CurrentTaxonomyNodeSchema]


class CurrentCompanyIndustryAssignmentSchema(_CurrentTaxonomySchema):
    id: int
    company_id: UUID
    taxonomy_code: str
    method: str
    breadcrumb: dict[str, Any]
    is_primary: bool
    primary_basis: str | None
    provenance: dict[str, Any]


class CurrentCompanyIndustryStateSchema(_CurrentTaxonomySchema):
    company_id: UUID
    assignments: list[CurrentCompanyIndustryAssignmentSchema]


class CurrentJobSkillSchema(_CurrentTaxonomySchema):
    code: str
    name: str
    source: str
    confidence: float | None
    provenance: dict[str, Any]
    mention_count: int


class CurrentSkillCandidateMentionSchema(_CurrentTaxonomySchema):
    id: UUID
    raw_name: str
    normalized_key: str
    candidate_id: UUID
    source: str
    confidence: float | None
    provenance: dict[str, Any]


class CurrentJobSkillStateSchema(_CurrentTaxonomySchema):
    job_id: UUID
    skills: list[CurrentJobSkillSchema]
    candidate_mentions: list[CurrentSkillCandidateMentionSchema]


__all__ = [
    "CurrentCompanyIndustryAssignmentSchema",
    "CurrentCompanyIndustryStateSchema",
    "CurrentJobSkillSchema",
    "CurrentJobSkillStateSchema",
    "CurrentSkillCandidateMentionSchema",
    "CurrentTaxonomyNodeSchema",
    "CurrentTaxonomyTreeSchema",
]
