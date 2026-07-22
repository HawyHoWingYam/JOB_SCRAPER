from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class SkillCountsSchema(BaseModel):
    categories: int
    technologies: int
    skills: int


class SkillRevisionSchema(BaseModel):
    id: UUID
    release_key: str
    content_hash: str
    status: Literal["active"]
    lock_version: int
    activated_at: datetime
    counts: SkillCountsSchema
    component_hashes: dict[str, str]


class SkillNodeRefSchema(BaseModel):
    id: UUID
    code: str
    name: str


class GovernedSkillSchema(BaseModel):
    id: UUID
    revision_id: UUID
    category: SkillNodeRefSchema
    technology: SkillNodeRefSchema
    code: str
    name: str
    order: int
    origin: Literal["seed", "operator"]
    aliases: list[str]


class SkillTechnologySchema(BaseModel):
    id: UUID
    code: str
    name: str
    order: int
    skills: list[GovernedSkillSchema]


class SkillCategorySchema(BaseModel):
    id: UUID
    code: str
    name: str
    order: int
    technologies: list[SkillTechnologySchema]


class SkillTreeSchema(BaseModel):
    revision: SkillRevisionSchema
    categories: list[SkillCategorySchema]


class SkillUnreviewedMentionSchema(BaseModel):
    id: UUID
    label: Literal["Unreviewed Skill Mention"]
    raw_name: str
    normalized_key: str
    candidate_id: UUID
    candidate_version: int
    source: str
    confidence: float | None
    provenance: dict[str, Any]
    deep_link: str
    created_at: datetime
    updated_at: datetime


class JobSkillStateSchema(BaseModel):
    job_id: UUID
    taxonomy_revision_id: UUID
    skills: list[GovernedSkillSchema]
    unreviewed_skill_mentions: list[SkillUnreviewedMentionSchema]


class SkillRecommendationSchema(BaseModel):
    skill_id: UUID
    skill_code: str
    skill_name: str
    category_code: str
    category_name: str
    technology_code: str
    technology_name: str
    score: float
    reason: str
    advisory_only: Literal[True]


class SkillCandidateSchema(BaseModel):
    id: UUID
    taxonomy_revision_id: UUID
    normalized_key: str
    canonical_raw_name: str
    raw_variants: list[str]
    status: Literal[
        "pending",
        "resolved_merged",
        "resolved_created",
        "resolved_generic",
        "rejected",
        "superseded",
    ]
    suggested_category_code: str | None
    suggested_technology_code: str | None
    occurrence_count: int
    affected_job_count: int
    evidence_summary: dict[str, Any]
    recommendations: list[SkillRecommendationSchema]
    version: int
    decision_audit_id: UUID | None
    resolved_skill_id: UUID | None
    generic_tag: str | None
    rejection_reason: str | None
    deep_link: str
    first_seen_at: datetime
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None


class SkillCandidatePageSchema(BaseModel):
    items: list[SkillCandidateSchema]
    next_cursor: str | None
    total: int
    page: int | None = None
    limit: int | None = None
    offset: int | None = None
    page_count: int | None = None


class SkillCreateTargetSchema(BaseModel):
    category_code: str = Field(min_length=1, max_length=255)
    technology_code: str = Field(min_length=1, max_length=255)
    stable_code: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list)


class SkillCandidateDecisionRequestSchema(BaseModel):
    action: Literal["merge_existing", "create_skill", "classify_generic", "reject"]
    target_skill_id: UUID | None = None
    create_target: SkillCreateTargetSchema | None = None
    generic_tag: str | None = None
    rejection_reason: str | None = None
    expected_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=255)
    confirmed: bool
    note: str | None = None
    correlation_id: str | None = None


class SkillCandidateDecisionResultSchema(BaseModel):
    subject: dict[str, Any]
    resulting_projection: dict[str, Any] | None
    audit_event_id: UUID
    version: int
    replayed: bool


class SkillSearchSchema(BaseModel):
    skills: list[GovernedSkillSchema]


class SkillGovernanceFixtureSchema(BaseModel):
    revision: SkillRevisionSchema
    tree: SkillTreeSchema
    job_state: JobSkillStateSchema
    candidate_page: SkillCandidatePageSchema


__all__ = [
    "GovernedSkillSchema",
    "JobSkillStateSchema",
    "SkillCandidateDecisionRequestSchema",
    "SkillCandidateDecisionResultSchema",
    "SkillCandidatePageSchema",
    "SkillCandidateSchema",
    "SkillCategorySchema",
    "SkillCountsSchema",
    "SkillCreateTargetSchema",
    "SkillGovernanceFixtureSchema",
    "SkillNodeRefSchema",
    "SkillRecommendationSchema",
    "SkillRevisionSchema",
    "SkillSearchSchema",
    "SkillTechnologySchema",
    "SkillTreeSchema",
    "SkillUnreviewedMentionSchema",
]
