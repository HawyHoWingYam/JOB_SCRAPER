from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from app.job_intelligence.foundation import Provenance


CompanyIndustryEvidenceKind = Literal[
    "source_industry",
    "manual",
    "ai_recommendation",
]


@dataclass(frozen=True)
class CompanyIndustryEvidence:
    evidence_kind: CompanyIndustryEvidenceKind
    provenance: Provenance
    source_site: str | None = None
    raw_code: str | None = None
    raw_label: str | None = None
    hsic_codes: tuple[str, ...] = ()
    declares_primary: bool = False
    recommendations: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.evidence_kind not in {
            "source_industry",
            "manual",
            "ai_recommendation",
        }:
            raise ValueError("Unsupported Company Industry evidence kind")
        if self.evidence_kind == "source_industry" and not self.source_site:
            raise ValueError("Source Industry evidence requires a Source")
        if self.evidence_kind != "source_industry" and self.declares_primary:
            raise ValueError("Only authoritative Source evidence can declare Primary")
        if self.source_site != self.provenance.source_site:
            raise ValueError("Company Industry evidence Source/provenance mismatch")
        for value in (self.raw_code, self.raw_label):
            if value is not None and len(value) > 500:
                raise ValueError(
                    "Company Industry evidence values are bounded to 500 chars"
                )
        if (
            not self.raw_code
            and not self.raw_label
            and not self.hsic_codes
            and not self.recommendations
        ):
            raise ValueError("Company Industry evidence is empty")

    def to_payload(self) -> dict[str, Any]:
        return {
            "evidence_kind": self.evidence_kind,
            "source_site": self.source_site,
            "raw_code": self.raw_code,
            "raw_label": self.raw_label,
            "hsic_codes": list(self.hsic_codes),
            "declares_primary": self.declares_primary,
            "recommendations": [dict(item) for item in self.recommendations],
            "provenance": self.provenance.to_payload(),
        }


@dataclass(frozen=True)
class CompanyIndustryOutcome:
    company_id: UUID
    state: Literal["assigned", "review"]
    assignment_id: UUID | None
    review_item_id: UUID | None
    changed: bool


__all__ = ["CompanyIndustryEvidence", "CompanyIndustryOutcome"]
