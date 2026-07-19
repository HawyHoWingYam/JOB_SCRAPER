from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.job_intelligence.company_industry.contracts import (
    CompanyIndustryEvidence,
    CompanyIndustryOutcome,
)
from app.job_intelligence.company_industry.read_model import CompanyIndustry
from app.job_intelligence.foundation import Provenance
from app.repositories.event_outbox_repository import EventOutboxRepository
from app.utils.time import utc_now


def _field(canonical_job: object, name: str) -> Any:
    if isinstance(canonical_job, Mapping):
        return canonical_job.get(name)
    return getattr(canonical_job, name, None)


def _aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _captured_at(canonical_job: object, raw_data: Mapping[str, Any]) -> datetime:
    source_attributes = _field(canonical_job, "source_attribute_evidence")
    if isinstance(source_attributes, Mapping):
        for collection_name in ("classification_paths", "employment_labels"):
            rows = source_attributes.get(collection_name)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                provenance = row.get("provenance")
                if not isinstance(provenance, Mapping):
                    continue
                captured_at = _aware_datetime(provenance.get("captured_at"))
                if captured_at is not None:
                    return captured_at
    for value in (
        _field(canonical_job, "captured_at"),
        raw_data.get("captured_at"),
        raw_data.get("scraped_at"),
    ):
        captured_at = _aware_datetime(value)
        if captured_at is not None:
            return captured_at
    return utc_now()


class CompanyIndustryEvidenceAdapter:
    """Extract company-owned Industry evidence without accepting Job taxonomy."""

    def extract(self, canonical_job: object) -> CompanyIndustryEvidence | None:
        source_site = str(_field(canonical_job, "source_site") or "").strip().lower()
        if source_site != "offertoday":
            return None
        raw_data = _field(canonical_job, "raw_data")
        if not isinstance(raw_data, Mapping):
            return None
        label = raw_data.get("company_industry")
        if not isinstance(label, str) or not label.strip():
            industry = raw_data.get("industry")
            label = industry.get("name") if isinstance(industry, Mapping) else None
        if not isinstance(label, str) or not label.strip():
            return None
        source_job_id = str(_field(canonical_job, "source_job_id") or "").strip()
        return CompanyIndustryEvidence(
            evidence_kind="source_industry",
            source_site="offertoday",
            raw_label=label.strip(),
            provenance=Provenance(
                method="offertoday-company-detail",
                source_site="offertoday",
                evidence_refs=(
                    {
                        "kind": "company-detail",
                        "source_job_id": source_job_id,
                    },
                ),
                captured_at=_captured_at(canonical_job, raw_data),
            ),
        )


def project_company_industry(
    db: Session,
    company_id: UUID,
    canonical_job: object,
    *,
    outbox_repository: EventOutboxRepository | None = None,
) -> CompanyIndustryOutcome | None:
    evidence = CompanyIndustryEvidenceAdapter().extract(canonical_job)
    if evidence is None:
        return None
    return CompanyIndustry(
        db,
        outbox_repository=outbox_repository,
    ).ingest_evidence(company_id, evidence)


__all__ = ["CompanyIndustryEvidenceAdapter", "project_company_industry"]
