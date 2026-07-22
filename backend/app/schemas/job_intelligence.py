from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.job_intelligence.foundation import AuditPage


class PendingSelectionScopeSchema(BaseModel):
    """Source-qualified, date-bounded scope shared by AI and governance reads."""

    source_sites: list[str] = Field(default_factory=list)
    source_classification_ids: list[str] = Field(default_factory=list)
    source_subclassification_ids: list[str] = Field(default_factory=list)
    source_classification_names: list[str] = Field(default_factory=list)
    source_subclassification_names: list[str] = Field(default_factory=list)
    posted_date_from: date | None = None
    posted_date_to: date | None = None

    @field_validator(
        "source_sites",
        "source_classification_names",
        "source_subclassification_names",
        mode="before",
    )
    @classmethod
    def normalize_text_values(cls, value):
        values = value if isinstance(value, list) else []
        normalized: list[str] = []
        seen: set[str] = set()
        for item in values:
            text_value = str(item or "").strip().lower()
            if text_value and text_value not in seen:
                seen.add(text_value)
                normalized.append(text_value)
        return normalized

    @field_validator(
        "source_classification_ids",
        "source_subclassification_ids",
        mode="before",
    )
    @classmethod
    def normalize_identity_values(cls, value):
        values = value if isinstance(value, list) else []
        normalized: list[str] = []
        seen: set[str] = set()
        for item in values:
            identity = str(item or "").strip()
            if identity and identity not in seen:
                seen.add(identity)
                normalized.append(identity)
        return normalized

    @field_validator("source_classification_ids", "source_subclassification_ids")
    @classmethod
    def validate_source_classification_ids(cls, value: list[str]) -> list[str]:
        from app.services.source_catalog import list_supported_source_sites

        supported = set(list_supported_source_sites())
        invalid = []
        for identity in value:
            source_site, separator, native_id = identity.partition(":")
            if not separator or source_site not in supported or not native_id:
                invalid.append(identity)
        if invalid:
            raise ValueError(
                "Source Classification IDs must be source-qualified: "
                + ", ".join(invalid)
            )
        return value

    @field_validator("source_sites")
    @classmethod
    def validate_sources(cls, value: list[str]) -> list[str]:
        from app.services.source_catalog import list_supported_source_sites

        supported = set(list_supported_source_sites())
        unsupported = [source for source in value if source not in supported]
        if unsupported:
            raise ValueError(f"Unsupported source site(s): {', '.join(unsupported)}")
        return value

    @model_validator(mode="after")
    def validate_dates(self):
        if (
            self.posted_date_from is not None
            and self.posted_date_to is not None
            and self.posted_date_from > self.posted_date_to
        ):
            raise ValueError("posted_date_from must be on or before posted_date_to")
        return self

    @property
    def has_constraints(self) -> bool:
        return bool(
            self.source_sites
            or self.source_classification_ids
            or self.source_subclassification_ids
            or self.source_classification_names
            or self.source_subclassification_names
            or self.posted_date_from
            or self.posted_date_to
        )

    def to_service_filters(self):
        from app.services.enrichment_run_service import PendingJobFilters

        return PendingJobFilters(
            source_sites=tuple(self.source_sites),
            source_classification_ids=tuple(self.source_classification_ids),
            source_subclassification_ids=tuple(self.source_subclassification_ids),
            source_classification_names=tuple(self.source_classification_names),
            source_subclassification_names=tuple(self.source_subclassification_names),
            posted_date_from=self.posted_date_from,
            posted_date_to=self.posted_date_to,
        )


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


class PendingSelectionSummarySchema(BaseModel):
    matching_pending_count: int
    selected_item_count: int
    effective_item_count: int
    excluded_item_count: int
    selected_job_ids: list[UUID] = Field(default_factory=list)
    supported_job_ids: list[UUID] = Field(default_factory=list)
    excluded_reasons_by_job_id: dict[str, str] = Field(default_factory=dict)
    excluded_items: list[dict[str, Any]] = Field(default_factory=list)


class ProvenanceRepairInspectRequestSchema(BaseModel):
    scope: PendingSelectionScopeSchema
    limit: int = Field(ge=1, le=5000)


class ProvenanceRepairApplyRequestSchema(ProvenanceRepairInspectRequestSchema):
    revision_id: UUID
    expected_fingerprint: str = Field(min_length=1)
    repairable_job_ids: list[UUID] = Field(default_factory=list)
    confirmed: bool


class ProvenanceRepairReportSchema(BaseModel):
    source_site: str
    revision_id: UUID
    revision_fingerprint: str
    revision_sequence: int
    active_revision_id: UUID | None
    active_revision_fingerprint: str | None
    revision_is_active: bool
    jobs_inspected: int
    paths_inspected: int
    missing_provenance_paths: int
    already_bound_paths: int
    repairable_jobs: int
    repairable_paths: int
    missing_path_jobs: int
    empty_path_jobs: int
    incompatible_revision_jobs: int
    incompatible_revision_paths: int
    source_mismatch_jobs: int
    source_mismatch_paths: int
    unknown_identity_jobs: list[dict[str, Any]]
    unknown_classification_ids: list[str]
    repairable_job_ids: list[UUID]
    pending_only: bool
    coverage_complete: bool
    write_blockers: list[str]


class ProvenanceRepairInspectResponseSchema(BaseModel):
    selection: PendingSelectionSummarySchema
    report: ProvenanceRepairReportSchema


class ProvenanceRepairApplyResultSchema(BaseModel):
    source_site: str
    revision_id: UUID
    changed_jobs: int
    changed_paths: int
    skipped_jobs: int
    batches_committed: int


class ProvenanceRepairApplyResponseSchema(BaseModel):
    selection: PendingSelectionSummarySchema
    repair: ProvenanceRepairApplyResultSchema


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
    page: int | None = None
    limit: int | None = None
    offset: int | None = None
    page_count: int | None = None


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
