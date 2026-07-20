from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session, undefer

from app.job_intelligence.company_industry.contracts import CompanyIndustryEvidence
from app.job_intelligence.company_industry.read_model import CompanyIndustry
from app.job_intelligence.foundation import Provenance
from app.models.company import Company
from app.models.company_industry import (
    CompanyIndustryActiveRevision,
    SourceIndustryMapping,
)
from app.models.job import Job


@dataclass(frozen=True)
class CompanyIndustryRebuildReport:
    companies_inspected: int
    active_revision_id: UUID | None
    evidence_states: dict[str, int]
    auto_mappable: int
    review_required: int
    primary_evidence: int
    company_ids_by_state: dict[str, tuple[UUID, ...]]

    def to_payload(self) -> dict[str, object]:
        return {
            "mode": "dry-run",
            "companies_inspected": self.companies_inspected,
            "active_revision_id": (
                str(self.active_revision_id)
                if self.active_revision_id is not None
                else None
            ),
            "evidence_states": {
                key: self.evidence_states[key] for key in sorted(self.evidence_states)
            },
            "auto_mappable": self.auto_mappable,
            "review_required": self.review_required,
            "primary_evidence": self.primary_evidence,
            "company_ids_by_state": {
                key: [str(value) for value in self.company_ids_by_state[key]]
                for key in sorted(self.company_ids_by_state)
            },
        }


@dataclass(frozen=True)
class RecoveredCompanyIndustry:
    company_id: UUID
    source_site: str
    source_company_id: str
    state: str
    evidence: CompanyIndustryEvidence | None

    @property
    def cursor(self) -> str:
        return f"{self.source_site}\x1f{self.source_company_id}\x1f{self.company_id}"


class CompanyIndustryRebuildInspector:
    """Classify preserved Company Industry evidence without writing projections."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def inspect(
        self,
        company_ids: Sequence[UUID] | None = None,
    ) -> CompanyIndustryRebuildReport:
        requested_ids = tuple(dict.fromkeys(company_ids or ()))
        with self.db.no_autoflush:
            query = (
                self.db.query(Company)
                .options(
                    undefer(Company.source_site),
                    undefer(Company.source_company_id),
                )
                .filter(Company.is_deleted.is_(False))
                .order_by(
                    Company.source_site,
                    Company.source_company_id,
                    Company.id,
                )
            )
            if company_ids is not None:
                query = query.filter(Company.id.in_(requested_ids))
            companies = query.all()
            selected_ids = tuple(company.id for company in companies)
            classification_rows = (
                self.db.query(Job.company_id, Job.source_classification_name)
                .filter(
                    Job.company_id.in_(selected_ids),
                    Job.source_classification_name.isnot(None),
                )
                .all()
                if selected_ids
                else []
            )
            active = self.db.get(CompanyIndustryActiveRevision, "company-industry")
            mappings = (
                self.db.query(SourceIndustryMapping)
                .filter(
                    SourceIndustryMapping.status == "active",
                    SourceIndustryMapping.taxonomy_revision_id == active.revision_id,
                )
                .all()
                if active is not None
                else []
            )

        classifications: dict[UUID, set[str]] = defaultdict(set)
        for company_id, label in classification_rows:
            normalized = _normalized(label)
            if normalized:
                classifications[company_id].add(normalized)
        mapping_keys = {
            (row.source_site, row.key_kind, row.normalized_key) for row in mappings
        }
        states: Counter[str] = Counter()
        ids_by_state: dict[str, list[UUID]] = defaultdict(list)
        auto_mappable = 0
        review_required = 0
        primary_evidence = 0

        for company in companies:
            legacy = _clean_text(company.industry)
            source_label, source_primary = _company_source_evidence(company)
            if source_primary:
                primary_evidence += 1
            if source_label:
                if legacy and _normalized(legacy) != _normalized(source_label):
                    state = "conflicting"
                    review_required += 1
                else:
                    state = "recoverable"
                    mapping_key = (
                        company.source_site,
                        "label",
                        CompanyIndustry.normalize_mapping_key(source_label),
                    )
                    if mapping_key in mapping_keys:
                        auto_mappable += 1
                    else:
                        review_required += 1
            elif legacy:
                if _normalized(legacy) in classifications.get(company.id, set()):
                    state = "polluted"
                else:
                    state = "legacy_review"
                review_required += 1
            else:
                state = "no_evidence"
            states[state] += 1
            ids_by_state[state].append(company.id)

        return CompanyIndustryRebuildReport(
            companies_inspected=len(companies),
            active_revision_id=active.revision_id if active is not None else None,
            evidence_states=dict(states),
            auto_mappable=auto_mappable,
            review_required=review_required,
            primary_evidence=primary_evidence,
            company_ids_by_state={
                key: tuple(values) for key, values in ids_by_state.items()
            },
        )

    def recover(
        self,
        company_ids: Sequence[UUID] | None = None,
    ) -> tuple[RecoveredCompanyIndustry, ...]:
        """Recover typed evidence without granting legacy scalars authority."""

        report = self.inspect(company_ids)
        state_by_id = {
            company_id: state
            for state, company_ids_for_state in report.company_ids_by_state.items()
            for company_id in company_ids_for_state
        }
        requested_ids = tuple(dict.fromkeys(company_ids or ()))
        with self.db.no_autoflush:
            query = (
                self.db.query(Company)
                .options(
                    undefer(Company.source_site),
                    undefer(Company.source_company_id),
                )
                .filter(Company.is_deleted.is_(False))
                .order_by(
                    Company.source_site,
                    Company.source_company_id,
                    Company.id,
                )
            )
            if company_ids is not None:
                query = query.filter(Company.id.in_(requested_ids))
            companies = query.all()

        recovered: list[RecoveredCompanyIndustry] = []
        for company in companies:
            state = state_by_id[company.id]
            source_label, source_primary = _company_source_evidence(company)
            legacy_label = _clean_text(company.industry)
            captured_at = _aware_utc(company.updated_at or company.created_at)
            evidence_ref = {
                "kind": "preserved-company-industry",
                "company_id": str(company.id),
                "source_company_id": company.source_company_id,
                "rebuild_state": state,
            }
            if (
                state == "recoverable"
                and source_label is not None
                and company.source_site == "offertoday"
            ):
                evidence = CompanyIndustryEvidence(
                    evidence_kind="source_industry",
                    source_site=company.source_site,
                    raw_label=source_label,
                    declares_primary=source_primary,
                    provenance=Provenance(
                        method="offertoday-preserved-company-industry",
                        source_site=company.source_site,
                        evidence_refs=(evidence_ref,),
                        captured_at=captured_at,
                    ),
                )
            else:
                review_label = source_label or legacy_label
                evidence = (
                    CompanyIndustryEvidence(
                        evidence_kind="manual",
                        raw_label=review_label,
                        provenance=Provenance(
                            method=(
                                "legacy-company-industry-cutover"
                                if state in {"legacy_review", "polluted"}
                                else "non-authoritative-company-industry-cutover"
                            ),
                            evidence_refs=(evidence_ref,),
                            captured_at=captured_at,
                        ),
                    )
                    if review_label is not None
                    else None
                )
            recovered.append(
                RecoveredCompanyIndustry(
                    company_id=company.id,
                    source_site=company.source_site,
                    source_company_id=company.source_company_id,
                    state=state,
                    evidence=evidence,
                )
            )
        return tuple(recovered)


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _normalized(value: object) -> str:
    return CompanyIndustry.normalize_mapping_key(str(value or ""))


def _company_source_evidence(company: Company) -> tuple[str | None, bool]:
    metadata = company.extra_data if isinstance(company.extra_data, dict) else {}
    raw_data = metadata.get("raw_data")
    if not isinstance(raw_data, dict):
        raw_data = metadata
    label = _clean_text(raw_data.get("company_industry"))
    if label is None:
        industry = raw_data.get("industry")
        if isinstance(industry, dict):
            label = _clean_text(industry.get("name"))
    return label, raw_data.get("company_industry_primary") is True


def _aware_utc(value: datetime | None) -> datetime:
    captured_at = value or datetime(1970, 1, 1, tzinfo=timezone.utc)
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=timezone.utc)
    return captured_at


__all__ = [
    "CompanyIndustryRebuildInspector",
    "CompanyIndustryRebuildReport",
    "RecoveredCompanyIndustry",
]
