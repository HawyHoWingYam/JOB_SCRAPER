from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.company_industry import (
    CompanyIndustryAssignment,
    CompanyIndustryTaxonomyNode,
)


CompatibilityAuthority = Literal[
    "governed_primary",
    "governed_single",
    "ambiguous_governed",
    "legacy_evidence",
    "unknown",
]


@dataclass(frozen=True)
class CompanyIndustryCompatibilityProjection:
    company_id: UUID
    value: str | None
    authority: CompatibilityAuthority
    assignment_id: UUID | None


class CompanyIndustryCompatibilityAdapter:
    """Time-bounded scalar projection for consumers awaiting governed arrays."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def project(self, company_id: UUID) -> CompanyIndustryCompatibilityProjection:
        company = self.db.get(Company, company_id)
        if company is None:
            raise ValueError("Company was not found")
        assignments = (
            self.db.query(CompanyIndustryAssignment)
            .filter(
                CompanyIndustryAssignment.company_id == company_id,
                CompanyIndustryAssignment.status == "active",
            )
            .order_by(
                CompanyIndustryAssignment.is_primary.desc(),
                CompanyIndustryAssignment.captured_at,
                CompanyIndustryAssignment.id,
            )
            .all()
        )
        primary = [assignment for assignment in assignments if assignment.is_primary]
        if len(primary) == 1:
            return self._governed(primary[0], "governed_primary")
        if len(assignments) == 1:
            return self._governed(assignments[0], "governed_single")
        if assignments:
            return CompanyIndustryCompatibilityProjection(
                company_id=company_id,
                value=None,
                authority="ambiguous_governed",
                assignment_id=None,
            )
        legacy = str(company.industry or "").strip()
        return CompanyIndustryCompatibilityProjection(
            company_id=company_id,
            value=legacy or None,
            authority="legacy_evidence" if legacy else "unknown",
            assignment_id=None,
        )

    def _governed(
        self,
        assignment: CompanyIndustryAssignment,
        authority: CompatibilityAuthority,
    ) -> CompanyIndustryCompatibilityProjection:
        node = self.db.get(CompanyIndustryTaxonomyNode, assignment.node_id)
        if node is None or node.revision_id != assignment.taxonomy_revision_id:
            raise ValueError("Company Industry assignment target is invalid")
        return CompanyIndustryCompatibilityProjection(
            company_id=assignment.company_id,
            value=node.label_en,
            authority=authority,
            assignment_id=assignment.id,
        )


__all__ = [
    "CompanyIndustryCompatibilityAdapter",
    "CompanyIndustryCompatibilityProjection",
]
