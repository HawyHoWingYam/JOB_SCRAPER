from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CompanyIndustryCountsSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    section: int
    division: int
    group: int
    class_: int = Field(alias="class", serialization_alias="class")
    subclass: int


class CompanyIndustryRevisionSchema(BaseModel):
    id: UUID
    release_key: str
    content_hash: str
    status: Literal["active"]
    lock_version: int
    activated_at: datetime
    counts: CompanyIndustryCountsSchema


class CompanyIndustryLabelsSchema(BaseModel):
    en: str
    zh_hant: str
    zh_hans: str


class CompanyIndustryNodeSchema(BaseModel):
    id: UUID
    code: str
    parent_id: UUID | None
    level: Literal["section", "division", "group", "class", "subclass"]
    labels: CompanyIndustryLabelsSchema
    order: int


class CompanyIndustryTreeSchema(BaseModel):
    revision: CompanyIndustryRevisionSchema
    parent_id: UUID | None
    nodes: list[CompanyIndustryNodeSchema]


class CompanyIndustryAssignmentSchema(BaseModel):
    id: UUID
    taxonomy_revision_id: UUID
    node_id: UUID
    method: Literal["authoritative_code", "reviewed_mapping", "operator"]
    breadcrumb: list[dict[str, Any]]
    is_primary: bool
    primary_basis: Literal["authoritative_source", "operator"] | None
    version: int
    provenance: dict[str, Any]


class CompanyIndustryReviewRefSchema(BaseModel):
    id: UUID
    status: Literal[
        "active",
        "assigned",
        "insufficient_evidence",
        "not_company_industry",
        "superseded",
    ]
    reason: str
    version: int
    decision_audit_id: UUID | None
    deep_link: str


class CompanyIndustryCompanyStateSchema(BaseModel):
    company_id: UUID
    assignments: list[CompanyIndustryAssignmentSchema]
    review_item_refs: list[CompanyIndustryReviewRefSchema]


class CompanyIndustryReviewItemSchema(BaseModel):
    id: UUID
    company_id: UUID
    taxonomy_revision_id: UUID | None
    source_site: str | None
    key_kind: Literal["code", "label"] | None
    raw_value: str | None
    normalized_key: str | None
    reason: str
    status: Literal[
        "active",
        "assigned",
        "insufficient_evidence",
        "not_company_industry",
        "superseded",
    ]
    evidence_hash: str
    provenance: dict[str, Any]
    recommendations: list[dict[str, Any]]
    version: int
    decision_audit_id: UUID | None
    assignment_id: UUID | None
    mapping_id: UUID | None
    deep_link: str
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None


class CompanyIndustryReviewPageSchema(BaseModel):
    items: list[CompanyIndustryReviewItemSchema]
    next_cursor: str | None
    total: int
    page: int | None = None
    limit: int | None = None
    offset: int | None = None
    page_count: int | None = None


class SourceIndustryMappingSchema(BaseModel):
    id: UUID
    source_site: str
    key_kind: Literal["code", "label"]
    raw_value: str
    normalized_key: str
    taxonomy_revision_id: UUID
    target_node_id: UUID
    status: Literal["active", "superseded", "retired"]
    version: int
    approved_by: Literal["local-operator"]
    approved_at: datetime
    decision_audit_id: UUID | None


class CompanyIndustryDecisionRequestSchema(BaseModel):
    action: Literal[
        "assign_existing_industry",
        "assign_existing_primary_industry",
        "approve_mapping_and_assign",
        "approve_mapping_and_assign_primary",
        "mark_insufficient_evidence",
        "mark_not_company_industry",
    ]
    target_id: UUID | None = None
    expected_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=255)
    confirmed: bool
    note: str | None = None
    correlation_id: str | None = None


class CompanyIndustryDecisionResultSchema(BaseModel):
    subject: dict[str, Any]
    resulting_projection: dict[str, Any] | None
    audit_event_id: UUID
    version: int
    replayed: bool


class CompanyIndustryFixtureSchema(BaseModel):
    revision: CompanyIndustryRevisionSchema
    tree: CompanyIndustryTreeSchema
    child_tree: CompanyIndustryTreeSchema
    company_state: CompanyIndustryCompanyStateSchema
    review_page: CompanyIndustryReviewPageSchema
    mappings: list[SourceIndustryMappingSchema]


__all__ = [
    "CompanyIndustryCompanyStateSchema",
    "CompanyIndustryCountsSchema",
    "CompanyIndustryDecisionRequestSchema",
    "CompanyIndustryDecisionResultSchema",
    "CompanyIndustryFixtureSchema",
    "CompanyIndustryNodeSchema",
    "CompanyIndustryReviewItemSchema",
    "CompanyIndustryReviewPageSchema",
    "CompanyIndustryRevisionSchema",
    "CompanyIndustryTreeSchema",
    "SourceIndustryMappingSchema",
]
