from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from app.job_intelligence.source_attributes import (
    EmploymentTypeView,
    SourceJobAttributes,
    SourceJobAttributesView,
)
from app.models.job import Job


MANUAL_ORIGIN = "manual"


@dataclass(frozen=True)
class JobEnrichmentInput:
    origin: str
    evidence: SourceJobAttributesView
    operator_authored_fields: frozenset[str]


@dataclass(frozen=True)
class JobEnrichmentInspection:
    status: Literal["supported", "needs_job_description", "excluded"]
    reason: str | None = None
    enrichment_input: JobEnrichmentInput | None = None

    @property
    def supported(self) -> bool:
        return self.status == "supported" and self.enrichment_input is not None


class JobEnrichmentEvidence:
    """Resolve Source and Manual facts behind one enrichment boundary."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def inspect(self, job: Job) -> JobEnrichmentInspection:
        if str(job.source_site or "").strip().lower() == MANUAL_ORIGIN:
            return self._inspect_manual(job)
        return self._inspect_source(job)

    def _inspect_manual(self, job: Job) -> JobEnrichmentInspection:
        evidence = job.manual_evidence
        if evidence is None:
            return JobEnrichmentInspection(
                status="excluded",
                reason="manual_evidence_missing",
            )
        if not str(job.description or "").strip():
            return JobEnrichmentInspection(
                status="needs_job_description",
                reason="needs_job_description",
            )
        employment_types = tuple(
            EmploymentTypeView(
                code=item.code,
                label=item.label,
                sort_order=item.sort_order,
            )
            for item in job.employment_types
        )
        view = SourceJobAttributesView(
            job_id=job.id,
            source_site=MANUAL_ORIGIN,
            evidence_hash=evidence.evidence_hash,
            source_classification_paths=(),
            employment_types=employment_types,
            source_employment_labels=(),
        )
        return JobEnrichmentInspection(
            status="supported",
            enrichment_input=JobEnrichmentInput(
                origin=MANUAL_ORIGIN,
                evidence=view,
                operator_authored_fields=frozenset(
                    str(field) for field in (evidence.operator_authored_fields or [])
                ),
            ),
        )

    def _inspect_source(self, job: Job) -> JobEnrichmentInspection:
        try:
            evidence = SourceJobAttributes(self.db).get(job.id)
        except ValueError:
            return JobEnrichmentInspection(
                status="excluded",
                reason="source_attributes_missing",
            )
        return JobEnrichmentInspection(
            status="supported",
            enrichment_input=JobEnrichmentInput(
                origin=str(job.source_site or "").strip().lower(),
                evidence=evidence,
                operator_authored_fields=frozenset(),
            ),
        )


__all__ = [
    "JobEnrichmentEvidence",
    "JobEnrichmentInput",
    "JobEnrichmentInspection",
    "MANUAL_ORIGIN",
]
