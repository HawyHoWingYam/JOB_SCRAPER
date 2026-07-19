from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.job_intelligence.foundation import AuditPage


class GovernanceAuditEventSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    domain: str
    subject_type: str
    subject_id: str
    action: str
    actor: str
    command_hash: str
    idempotency_key: str
    before_summary: dict[str, Any]
    after_summary: dict[str, Any]
    evidence_refs: list[dict[str, Any]]
    correlation_id: str
    created_at: datetime


class GovernanceAuditPageSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[GovernanceAuditEventSchema]
    next_cursor: str | None

    @classmethod
    def from_contract(cls, page: AuditPage) -> GovernanceAuditPageSchema:
        return cls.model_validate(page)


class CanonicalCountsSchema(BaseModel):
    domains: int
    categories: int
    subcategories: int


class CanonicalActiveMappingSchema(BaseModel):
    id: UUID
    content_hash: str
    lock_version: int
    activated_at: datetime


class CanonicalTaxonomyRevisionSchema(BaseModel):
    id: UUID
    release_key: str
    content_hash: str
    status: Literal["active"]
    lock_version: int
    activated_at: datetime
    counts: CanonicalCountsSchema
    active_mapping: CanonicalActiveMappingSchema | None


class CanonicalSubcategorySchema(BaseModel):
    id: UUID
    code: str
    label: str
    order: int
    is_assignable: bool


class CanonicalCategorySchema(BaseModel):
    id: UUID
    code: str
    label: str
    order: int
    subcategories: list[CanonicalSubcategorySchema]


class CanonicalDomainSchema(BaseModel):
    id: UUID
    code: str
    label: str
    order: int
    categories: list[CanonicalCategorySchema]


class CanonicalTaxonomyTreeSchema(BaseModel):
    revision: CanonicalTaxonomyRevisionSchema
    counts: CanonicalCountsSchema
    domains: list[CanonicalDomainSchema]


class CanonicalBreadcrumbNodeSchema(BaseModel):
    id: UUID
    code: str
    label: str


class CanonicalBreadcrumbSchema(BaseModel):
    domain: CanonicalBreadcrumbNodeSchema
    category: CanonicalBreadcrumbNodeSchema
    subcategory: CanonicalBreadcrumbNodeSchema


class CanonicalAssignmentModelSchema(BaseModel):
    provider: str | None
    name: str | None
    version: str | None


class CanonicalAssignmentProvenanceSchema(BaseModel):
    evidence_hash: str
    source_evidence_refs: list[dict[str, Any]]
    mapping_revision_id: UUID | None
    mapping_ids: list[str]
    model: CanonicalAssignmentModelSchema | None
    captured_at: datetime


class CanonicalAssignmentSchema(BaseModel):
    id: UUID
    job_id: UUID
    taxonomy_revision_id: UUID
    subcategory_id: UUID
    method: Literal["reviewed_mapping", "constrained_ai", "operator"]
    breadcrumb: CanonicalBreadcrumbSchema
    version: int
    provenance: CanonicalAssignmentProvenanceSchema


class CanonicalReviewRefSchema(BaseModel):
    id: UUID
    status: Literal[
        "active",
        "assigned",
        "insufficient_evidence",
        "superseded",
    ]
    version: int
    decision_audit_id: UUID | None
    deep_link: str


class CanonicalJobStateSchema(BaseModel):
    job_id: UUID
    state: Literal["assigned", "unassigned"]
    assignment: CanonicalAssignmentSchema | None
    reasons: list[str]
    review_item_refs: list[CanonicalReviewRefSchema]


class CanonicalReviewItemSchema(BaseModel):
    id: UUID
    job_id: UUID
    taxonomy_revision_id: UUID
    mapping_revision_id: UUID | None
    status: Literal[
        "active",
        "assigned",
        "insufficient_evidence",
        "superseded",
    ]
    reasons: list[str]
    evidence_hash: str
    evidence_refs: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    version: int
    decision_audit_id: UUID | None
    assignment_id: UUID | None
    deep_link: str
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None


class CanonicalReviewPageSchema(BaseModel):
    items: list[CanonicalReviewItemSchema]
    next_cursor: str | None
    total: int


class CanonicalTaxonomyDecisionRequestSchema(BaseModel):
    action: Literal[
        "assign_existing_subcategory",
        "mark_insufficient_evidence",
    ]
    target_id: UUID | None = None
    expected_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=255)
    confirmed: bool
    note: str | None = None
    correlation_id: str | None = None


class CanonicalTaxonomyDecisionResultSchema(BaseModel):
    subject: dict[str, Any]
    resulting_projection: dict[str, Any] | None
    audit_event_id: UUID
    version: int
    replayed: bool


class CanonicalTaxonomyFixtureSchema(BaseModel):
    revision: CanonicalTaxonomyRevisionSchema
    tree: CanonicalTaxonomyTreeSchema
    assigned_job: CanonicalJobStateSchema
    unassigned_job: CanonicalJobStateSchema
    review_page: CanonicalReviewPageSchema
