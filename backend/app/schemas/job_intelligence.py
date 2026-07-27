from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.job_intelligence.foundation import AuditPage


class PendingSelectionScopeSchema(BaseModel):
    """Source-qualified, date-bounded scope for AI batch selection."""

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
        from app.services.source_sites import list_supported_source_sites

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
        from app.services.source_sites import list_supported_source_sites

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
