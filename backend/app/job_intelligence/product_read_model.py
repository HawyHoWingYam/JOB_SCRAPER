from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.job_intelligence.canonical_taxonomy import (
    CanonicalJobTaxonomy,
    CanonicalJobStateView,
    CanonicalReadError,
)
from app.job_intelligence.company_industry import (
    CompanyIndustry,
    CompanyIndustryCompanyStateView,
    CompanyIndustryReadError,
)
from app.job_intelligence.skill_governance import (
    JobSkillStateView,
    SkillGovernanceReadError,
    SkillGovernanceReader,
)
from app.job_intelligence.source_attributes import (
    SourceJobAttributes,
    SourceJobAttributesView,
)
from app.models.canonical_job_taxonomy import (
    JobTaxonomyAssignment,
    JobTaxonomyReviewItem,
)
from app.models.company import Company
from app.models.company_industry import (
    CompanyIndustryAssignment,
    CompanyIndustryReviewItem,
)
from app.models.job import Job
from app.models.skill_governance import (
    GovernedJobSkill,
    GovernedJobSkillMention,
    GovernedSkill,
    GovernedSkillCategory,
    GovernedSkillTechnology,
    SkillCandidate,
)
from app.models.source_job_attributes import (
    EmploymentType,
    JobEmploymentType,
    JobSourceAttributeProjection,
    JobSourceClassificationPath,
)
from app.utils.time import utc_now


_TRUSTED_LOCAL_WARNING = (
    "Trusted local operation only. Governance decision routes are not "
    "authenticated and must not be exposed to an untrusted network."
)


@dataclass(frozen=True)
class GovernanceAreaSummaryView:
    key: Literal["job_taxonomy", "skill_candidates", "company_industries"]
    label: str
    available: bool
    pending_count: int
    oldest_pending_at: datetime | None
    active_revision_id: UUID | None
    unavailable_code: str | None
    deep_link: str

    def to_payload(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "available": self.available,
            "pending_count": self.pending_count,
            "oldest_pending_at": self.oldest_pending_at,
            "active_revision_id": (
                str(self.active_revision_id)
                if self.active_revision_id is not None
                else None
            ),
            "unavailable_code": self.unavailable_code,
            "deep_link": self.deep_link,
        }


@dataclass(frozen=True)
class JobIntelligenceCoverageView:
    total_jobs: int
    jobs_with_source_classification_paths: int
    jobs_with_employment_types: int
    jobs_with_canonical_assignment: int
    jobs_without_canonical_assignment: int
    jobs_with_unassigned_canonical_state: int
    jobs_with_unknown_canonical_state: int
    canonical_unassigned_reasons: dict[str, int]
    jobs_with_governed_skills: int
    jobs_with_unreviewed_skill_mentions: int
    total_companies: int
    companies_with_governed_industries: int
    companies_without_governed_industries: int

    def to_payload(self) -> dict[str, object]:
        return {
            "total_jobs": self.total_jobs,
            "jobs_with_source_classification_paths": (
                self.jobs_with_source_classification_paths
            ),
            "jobs_with_employment_types": self.jobs_with_employment_types,
            "jobs_with_canonical_assignment": self.jobs_with_canonical_assignment,
            "jobs_without_canonical_assignment": (
                self.jobs_without_canonical_assignment
            ),
            "jobs_with_unassigned_canonical_state": (
                self.jobs_with_unassigned_canonical_state
            ),
            "jobs_with_unknown_canonical_state": (
                self.jobs_with_unknown_canonical_state
            ),
            "canonical_unassigned_reasons": dict(self.canonical_unassigned_reasons),
            "jobs_with_governed_skills": self.jobs_with_governed_skills,
            "jobs_with_unreviewed_skill_mentions": (
                self.jobs_with_unreviewed_skill_mentions
            ),
            "total_companies": self.total_companies,
            "companies_with_governed_industries": (
                self.companies_with_governed_industries
            ),
            "companies_without_governed_industries": (
                self.companies_without_governed_industries
            ),
        }


@dataclass(frozen=True)
class JobIntelligenceGovernanceSummaryView:
    generated_at: datetime
    areas: tuple[GovernanceAreaSummaryView, ...]
    coverage: JobIntelligenceCoverageView

    @property
    def total_pending(self) -> int:
        return sum(area.pending_count for area in self.areas)

    def to_payload(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "trusted_local": {
                "actor": "local-operator",
                "authentication": "none",
                "warning": _TRUSTED_LOCAL_WARNING,
            },
            "total_pending": self.total_pending,
            "areas": [area.to_payload() for area in self.areas],
            "coverage": self.coverage.to_payload(),
        }


@dataclass(frozen=True)
class JobIntelligenceDomainAvailabilityView:
    available: bool
    unavailable_code: str | None

    def to_payload(self) -> dict[str, object]:
        return {
            "available": self.available,
            "unavailable_code": self.unavailable_code,
        }


@dataclass(frozen=True)
class JobIntelligenceJobDetailView:
    source_attributes: SourceJobAttributesView | None
    source_attributes_availability: JobIntelligenceDomainAvailabilityView
    canonical_taxonomy: CanonicalJobStateView | None
    canonical_taxonomy_availability: JobIntelligenceDomainAvailabilityView
    company_industries: CompanyIndustryCompanyStateView | None
    company_industries_availability: JobIntelligenceDomainAvailabilityView
    skill_state: JobSkillStateView | None
    skill_availability: JobIntelligenceDomainAvailabilityView

    def to_payload(self) -> dict[str, object]:
        source_payload = self._source_attributes_payload()
        skill_payload = (
            self.skill_state.to_payload() if self.skill_state is not None else None
        )
        return {
            **source_payload,
            "canonical_taxonomy": (
                self.canonical_taxonomy.to_payload()
                if self.canonical_taxonomy is not None
                else None
            ),
            "company_industries": (
                self.company_industries.to_payload()
                if self.company_industries is not None
                else None
            ),
            "skill_state": skill_payload,
            "skills": (
                [skill.name for skill in self.skill_state.skills]
                if self.skill_state is not None
                else []
            ),
            "provisional_skills": (
                [
                    mention.raw_name
                    for mention in self.skill_state.unreviewed_skill_mentions
                ]
                if self.skill_state is not None
                else []
            ),
            "unreviewed_skill_mentions": (
                [
                    mention.to_payload()
                    for mention in self.skill_state.unreviewed_skill_mentions
                ]
                if self.skill_state is not None
                else []
            ),
            "job_intelligence_availability": {
                "source_attributes": (self.source_attributes_availability.to_payload()),
                "canonical_taxonomy": (
                    self.canonical_taxonomy_availability.to_payload()
                ),
                "company_industries": (
                    self.company_industries_availability.to_payload()
                ),
                "skills": self.skill_availability.to_payload(),
            },
        }

    def _source_attributes_payload(self) -> dict[str, object]:
        view = self.source_attributes
        if view is None:
            return {
                "source_classification_paths": [],
                "employment_types": [],
                "source_employment_labels": [],
            }
        return {
            "source_classification_paths": [
                {
                    "id": str(path.id),
                    "source_site": view.source_site,
                    "source_order": path.source_order,
                    "nodes": [
                        {
                            "source_position": node.source_position,
                            "native_depth": node.native_depth,
                            "source_classification_id": (node.source_classification_id),
                            "native_id": node.native_id,
                            "label": node.label,
                        }
                        for node in path.nodes
                    ],
                    "is_primary": path.is_primary,
                    "primary_basis": path.primary_basis,
                    "catalog_revision": (
                        {
                            "source_site": path.source_catalog_revision.source_site,
                            "revision_id": str(
                                path.source_catalog_revision.revision_id
                            ),
                            "fingerprint": (path.source_catalog_revision.fingerprint),
                        }
                        if path.source_catalog_revision is not None
                        else None
                    ),
                    "provenance_limited": path.provenance_limited,
                    "provenance": dict(path.provenance),
                }
                for path in view.source_classification_paths
            ],
            "employment_types": [
                {
                    "code": item.code,
                    "label": item.label,
                    "sort_order": item.sort_order,
                }
                for item in view.employment_types
            ],
            "source_employment_labels": [
                {
                    "id": str(item.id),
                    "source_site": view.source_site,
                    "source_order": item.source_order,
                    "raw_code": item.raw_code,
                    "raw_label": item.raw_label,
                    "normalized_lookup_key": item.normalized_lookup_key,
                    "mapped_type_code": item.mapped_type_code,
                    "mapping_id": item.mapping_id,
                    "provenance": dict(item.provenance),
                }
                for item in view.source_employment_labels
            ],
        }


class JobIntelligenceProductReadModel:
    """Compose domain-owned governed state for read-only product surfaces."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_governance_summary(
        self,
        *,
        generated_at: datetime | None = None,
    ) -> JobIntelligenceGovernanceSummaryView:
        canonical_revision_id, canonical_error = self._canonical_revision()
        skill_revision_id, skill_error = self._skill_revision()
        industry_revision_id, industry_error = self._industry_revision()

        canonical_count, canonical_oldest = self._pending_metrics(
            JobTaxonomyReviewItem,
            status="active",
            timestamp_column=JobTaxonomyReviewItem.created_at,
            revision_criterion=(
                JobTaxonomyReviewItem.taxonomy_revision_id == canonical_revision_id
                if canonical_revision_id is not None
                else False
            ),
        )
        skill_count, skill_oldest = self._pending_metrics(
            SkillCandidate,
            status="pending",
            timestamp_column=SkillCandidate.first_seen_at,
            revision_criterion=(
                SkillCandidate.taxonomy_revision_id == skill_revision_id
                if skill_revision_id is not None
                else False
            ),
        )
        industry_count, industry_oldest = self._pending_metrics(
            CompanyIndustryReviewItem,
            status="active",
            timestamp_column=CompanyIndustryReviewItem.created_at,
            revision_criterion=(
                CompanyIndustryReviewItem.taxonomy_revision_id == industry_revision_id
                if industry_revision_id is not None
                else False
            ),
        )
        areas = (
            GovernanceAreaSummaryView(
                key="job_taxonomy",
                label="Job Taxonomy Review",
                available=canonical_error is None,
                pending_count=canonical_count,
                oldest_pending_at=canonical_oldest,
                active_revision_id=canonical_revision_id,
                unavailable_code=canonical_error,
                deep_link="/job-intelligence/job-taxonomy",
            ),
            GovernanceAreaSummaryView(
                key="skill_candidates",
                label="Skill Candidates",
                available=skill_error is None,
                pending_count=skill_count,
                oldest_pending_at=skill_oldest,
                active_revision_id=skill_revision_id,
                unavailable_code=skill_error,
                deep_link="/job-intelligence/skill-candidates",
            ),
            GovernanceAreaSummaryView(
                key="company_industries",
                label="Company Industries",
                available=industry_error is None,
                pending_count=industry_count,
                oldest_pending_at=industry_oldest,
                active_revision_id=industry_revision_id,
                unavailable_code=industry_error,
                deep_link="/job-intelligence/company-industries",
            ),
        )
        return JobIntelligenceGovernanceSummaryView(
            generated_at=generated_at or utc_now(),
            areas=areas,
            coverage=self._coverage(
                canonical_revision_id=canonical_revision_id,
                skill_revision_id=skill_revision_id,
                industry_revision_id=industry_revision_id,
            ),
        )

    def get_job_detail(
        self,
        *,
        job_id: UUID,
        company_id: UUID,
    ) -> JobIntelligenceJobDetailView:
        source_attributes, source_availability = self._source_attributes(job_id)
        canonical_taxonomy, canonical_availability = self._canonical_job_state(job_id)
        company_industries, industry_availability = self._company_industry_state(
            company_id
        )
        skill_state, skill_availability = self._skill_job_state(job_id)
        return JobIntelligenceJobDetailView(
            source_attributes=source_attributes,
            source_attributes_availability=source_availability,
            canonical_taxonomy=canonical_taxonomy,
            canonical_taxonomy_availability=canonical_availability,
            company_industries=company_industries,
            company_industries_availability=industry_availability,
            skill_state=skill_state,
            skill_availability=skill_availability,
        )

    def get_company_detail(self, company_id: UUID) -> dict[str, object]:
        return self.get_company_details((company_id,))[company_id]

    def get_company_details(
        self,
        company_ids: tuple[UUID, ...] | list[UUID],
    ) -> dict[UUID, dict[str, object]]:
        ordered_ids = tuple(dict.fromkeys(company_ids))
        if not ordered_ids:
            return {}
        try:
            revision = CompanyIndustry(self.db).get_active_revision()
        except CompanyIndustryReadError as exc:
            unavailable = JobIntelligenceDomainAvailabilityView(
                available=False,
                unavailable_code=exc.code,
            ).to_payload()
            return {
                company_id: {
                    "company_industries": None,
                    "company_industry_availability": unavailable,
                }
                for company_id in ordered_ids
            }

        assignments_by_company: dict[UUID, list[dict[str, object]]] = defaultdict(list)
        assignments = (
            self.db.query(CompanyIndustryAssignment)
            .filter(
                CompanyIndustryAssignment.company_id.in_(ordered_ids),
                CompanyIndustryAssignment.taxonomy_revision_id == revision.id,
                CompanyIndustryAssignment.status == "active",
            )
            .order_by(
                CompanyIndustryAssignment.company_id,
                CompanyIndustryAssignment.is_primary.desc(),
                CompanyIndustryAssignment.captured_at,
                CompanyIndustryAssignment.id,
            )
            .all()
        )
        for assignment in assignments:
            assignments_by_company[assignment.company_id].append(
                {
                    "id": str(assignment.id),
                    "taxonomy_revision_id": str(assignment.taxonomy_revision_id),
                    "node_id": str(assignment.node_id),
                    "method": assignment.method,
                    "breadcrumb": [dict(item) for item in assignment.breadcrumb],
                    "is_primary": assignment.is_primary,
                    "primary_basis": assignment.primary_basis,
                    "version": assignment.lock_version,
                    "provenance": dict(assignment.provenance),
                }
            )

        reviews_by_company: dict[UUID, list[dict[str, object]]] = defaultdict(list)
        reviews = (
            self.db.query(CompanyIndustryReviewItem)
            .filter(
                CompanyIndustryReviewItem.company_id.in_(ordered_ids),
                CompanyIndustryReviewItem.taxonomy_revision_id == revision.id,
            )
            .order_by(
                CompanyIndustryReviewItem.company_id,
                CompanyIndustryReviewItem.created_at.desc(),
                CompanyIndustryReviewItem.id.desc(),
            )
            .all()
        )
        for review in reviews:
            reviews_by_company[review.company_id].append(
                {
                    "id": str(review.id),
                    "status": review.status,
                    "reason": review.reason,
                    "version": review.lock_version,
                    "decision_audit_id": (
                        str(review.decision_audit_id)
                        if review.decision_audit_id is not None
                        else None
                    ),
                    "deep_link": (
                        "/api/v1/job-intelligence/governance/"
                        "company-industries/review-items/"
                        f"{review.id}"
                    ),
                }
            )

        available = JobIntelligenceDomainAvailabilityView(
            available=True,
            unavailable_code=None,
        ).to_payload()
        return {
            company_id: {
                "company_industries": {
                    "company_id": str(company_id),
                    "assignments": assignments_by_company.get(company_id, []),
                    "review_item_refs": reviews_by_company.get(company_id, []),
                },
                "company_industry_availability": available,
            }
            for company_id in ordered_ids
        }

    def get_canonical_job_states(
        self,
        job_ids: tuple[UUID, ...] | list[UUID],
    ) -> dict[UUID, dict[str, object]]:
        ordered_ids = tuple(dict.fromkeys(job_ids))
        if not ordered_ids:
            return {}
        try:
            revision = CanonicalJobTaxonomy(self.db).get_active_revision()
        except CanonicalReadError as exc:
            unavailable = JobIntelligenceDomainAvailabilityView(
                available=False,
                unavailable_code=exc.code,
            ).to_payload()
            return {
                job_id: {
                    "canonical_taxonomy": None,
                    "canonical_taxonomy_availability": unavailable,
                }
                for job_id in ordered_ids
            }

        assignments = (
            self.db.query(JobTaxonomyAssignment)
            .filter(
                JobTaxonomyAssignment.job_id.in_(ordered_ids),
                JobTaxonomyAssignment.taxonomy_revision_id == revision.id,
                JobTaxonomyAssignment.is_current.is_(True),
            )
            .all()
        )
        assignments_by_job = {row.job_id: row for row in assignments}
        reviews = (
            self.db.query(JobTaxonomyReviewItem)
            .filter(
                JobTaxonomyReviewItem.job_id.in_(ordered_ids),
                JobTaxonomyReviewItem.taxonomy_revision_id == revision.id,
                JobTaxonomyReviewItem.status != "superseded",
            )
            .order_by(
                JobTaxonomyReviewItem.job_id,
                JobTaxonomyReviewItem.created_at.desc(),
                JobTaxonomyReviewItem.id.desc(),
            )
            .all()
        )
        reviews_by_job: dict[UUID, JobTaxonomyReviewItem] = {}
        for review in reviews:
            reviews_by_job.setdefault(review.job_id, review)

        available = JobIntelligenceDomainAvailabilityView(
            available=True,
            unavailable_code=None,
        ).to_payload()
        payloads: dict[UUID, dict[str, object]] = {}
        for job_id in ordered_ids:
            assignment = assignments_by_job.get(job_id)
            review = reviews_by_job.get(job_id)
            reasons: list[str] = []
            if assignment is None and review is not None:
                if review.status == "active":
                    reasons = [str(reason) for reason in review.reasons]
                elif review.status == "insufficient_evidence":
                    reasons = ["insufficient_evidence"]
            payloads[job_id] = {
                "canonical_taxonomy": {
                    "job_id": str(job_id),
                    "state": "assigned" if assignment is not None else "unassigned",
                    "assignment": (
                        self._canonical_assignment_payload(assignment)
                        if assignment is not None
                        else None
                    ),
                    "reasons": reasons,
                    "review_item_refs": (
                        [self._canonical_review_ref_payload(review)]
                        if review is not None
                        else []
                    ),
                },
                "canonical_taxonomy_availability": available,
            }
        return payloads

    def get_employment_type_states(
        self,
        job_ids: tuple[UUID, ...] | list[UUID],
    ) -> dict[UUID, dict[str, object]]:
        ordered_ids = tuple(dict.fromkeys(job_ids))
        if not ordered_ids:
            return {}

        projected_job_ids = {
            job_id
            for (job_id,) in self.db.query(JobSourceAttributeProjection.job_id)
            .filter(JobSourceAttributeProjection.job_id.in_(ordered_ids))
            .all()
        }
        employment_types_by_job: dict[UUID, list[dict[str, object]]] = defaultdict(list)
        rows = (
            self.db.query(JobEmploymentType.job_id, EmploymentType)
            .join(
                EmploymentType,
                EmploymentType.code == JobEmploymentType.employment_type_code,
            )
            .filter(JobEmploymentType.job_id.in_(ordered_ids))
            .order_by(
                JobEmploymentType.job_id,
                EmploymentType.sort_order,
                EmploymentType.code,
            )
            .all()
        )
        for job_id, employment_type in rows:
            employment_types_by_job[job_id].append(
                {
                    "code": employment_type.code,
                    "label": employment_type.label,
                    "sort_order": employment_type.sort_order,
                }
            )

        return {
            job_id: {
                "employment_types": employment_types_by_job.get(job_id, []),
                "source_attributes_availability": (
                    JobIntelligenceDomainAvailabilityView(
                        available=True,
                        unavailable_code=None,
                    ).to_payload()
                    if job_id in projected_job_ids
                    else JobIntelligenceDomainAvailabilityView(
                        available=False,
                        unavailable_code="SOURCE_JOB_ATTRIBUTES_NOT_PROJECTED",
                    ).to_payload()
                ),
            }
            for job_id in ordered_ids
        }

    def get_governed_skill_name_states(
        self,
        job_ids: tuple[UUID, ...] | list[UUID],
    ) -> dict[UUID, dict[str, object]]:
        ordered_ids = tuple(dict.fromkeys(job_ids))
        if not ordered_ids:
            return {}

        revision_id, revision_error = self._skill_revision()
        if revision_id is None:
            unavailable = JobIntelligenceDomainAvailabilityView(
                available=False,
                unavailable_code=revision_error,
            ).to_payload()
            return {
                job_id: {
                    "governed_skill_names": [],
                    "skills_availability": unavailable,
                }
                for job_id in ordered_ids
            }

        skill_names_by_job: dict[UUID, list[str]] = defaultdict(list)
        rows = (
            self.db.query(GovernedJobSkill.job_id, GovernedSkill.name)
            .join(
                GovernedSkill,
                and_(
                    GovernedSkill.id == GovernedJobSkill.skill_id,
                    GovernedSkill.revision_id == GovernedJobSkill.taxonomy_revision_id,
                ),
            )
            .join(
                GovernedSkillTechnology,
                and_(
                    GovernedSkillTechnology.id == GovernedSkill.technology_id,
                    GovernedSkillTechnology.revision_id == GovernedSkill.revision_id,
                ),
            )
            .join(
                GovernedSkillCategory,
                and_(
                    GovernedSkillCategory.id == GovernedSkillTechnology.category_id,
                    GovernedSkillCategory.revision_id
                    == GovernedSkillTechnology.revision_id,
                ),
            )
            .filter(
                GovernedJobSkill.job_id.in_(ordered_ids),
                GovernedJobSkill.taxonomy_revision_id == revision_id,
                GovernedSkill.is_active.is_(True),
                GovernedSkillTechnology.is_active.is_(True),
                GovernedSkillCategory.is_active.is_(True),
            )
            .order_by(
                GovernedJobSkill.job_id,
                GovernedSkillCategory.source_order,
                GovernedSkillTechnology.source_order,
                GovernedSkill.source_order,
                GovernedSkill.code,
            )
            .all()
        )
        for job_id, skill_name in rows:
            skill_names_by_job[job_id].append(skill_name)

        available = JobIntelligenceDomainAvailabilityView(
            available=True,
            unavailable_code=None,
        ).to_payload()
        return {
            job_id: {
                "governed_skill_names": skill_names_by_job.get(job_id, []),
                "skills_availability": available,
            }
            for job_id in ordered_ids
        }

    @staticmethod
    def _canonical_assignment_payload(
        assignment: JobTaxonomyAssignment,
    ) -> dict[str, object]:
        model = None
        if any(
            (
                assignment.model_provider,
                assignment.model_name,
                assignment.model_version,
            )
        ):
            model = {
                "provider": assignment.model_provider,
                "name": assignment.model_name,
                "version": assignment.model_version,
            }
        return {
            "id": str(assignment.id),
            "job_id": str(assignment.job_id),
            "taxonomy_revision_id": str(assignment.taxonomy_revision_id),
            "subcategory_id": str(assignment.subcategory_id),
            "method": assignment.method,
            "breadcrumb": dict(assignment.breadcrumb),
            "version": assignment.lock_version,
            "provenance": {
                "evidence_hash": assignment.evidence_hash,
                "source_evidence_refs": [
                    dict(item) for item in assignment.source_evidence_refs
                ],
                "mapping_revision_id": (
                    str(assignment.mapping_revision_id)
                    if assignment.mapping_revision_id is not None
                    else None
                ),
                "mapping_ids": list(assignment.mapping_ids),
                "model": model,
                "captured_at": assignment.captured_at,
            },
        }

    @staticmethod
    def _canonical_review_ref_payload(
        review: JobTaxonomyReviewItem,
    ) -> dict[str, object]:
        return {
            "id": str(review.id),
            "status": review.status,
            "version": review.lock_version,
            "decision_audit_id": (
                str(review.decision_audit_id)
                if review.decision_audit_id is not None
                else None
            ),
            "deep_link": (
                "/api/v1/job-intelligence/governance/job-taxonomy/"
                f"review-items/{review.id}"
            ),
        }

    def _source_attributes(
        self,
        job_id: UUID,
    ) -> tuple[SourceJobAttributesView | None, JobIntelligenceDomainAvailabilityView,]:
        try:
            view = SourceJobAttributes(self.db).get(job_id)
        except ValueError:
            return None, JobIntelligenceDomainAvailabilityView(
                available=False,
                unavailable_code="SOURCE_JOB_ATTRIBUTES_NOT_PROJECTED",
            )
        return view, JobIntelligenceDomainAvailabilityView(
            available=True,
            unavailable_code=None,
        )

    def _canonical_job_state(
        self,
        job_id: UUID,
    ) -> tuple[CanonicalJobStateView | None, JobIntelligenceDomainAvailabilityView,]:
        reader = CanonicalJobTaxonomy(self.db)
        try:
            reader.get_active_revision()
            view = reader.get_job_state(job_id)
        except CanonicalReadError as exc:
            return None, JobIntelligenceDomainAvailabilityView(
                available=False,
                unavailable_code=exc.code,
            )
        return view, JobIntelligenceDomainAvailabilityView(
            available=True,
            unavailable_code=None,
        )

    def _company_industry_state(
        self,
        company_id: UUID,
    ) -> tuple[
        CompanyIndustryCompanyStateView | None,
        JobIntelligenceDomainAvailabilityView,
    ]:
        reader = CompanyIndustry(self.db)
        try:
            reader.get_active_revision()
            view = reader.get_company_state(company_id)
        except CompanyIndustryReadError as exc:
            return None, JobIntelligenceDomainAvailabilityView(
                available=False,
                unavailable_code=exc.code,
            )
        return view, JobIntelligenceDomainAvailabilityView(
            available=True,
            unavailable_code=None,
        )

    def _skill_job_state(
        self,
        job_id: UUID,
    ) -> tuple[JobSkillStateView | None, JobIntelligenceDomainAvailabilityView,]:
        try:
            view = SkillGovernanceReader(self.db).get_job_state(job_id)
        except SkillGovernanceReadError as exc:
            return None, JobIntelligenceDomainAvailabilityView(
                available=False,
                unavailable_code=exc.code,
            )
        return view, JobIntelligenceDomainAvailabilityView(
            available=True,
            unavailable_code=None,
        )

    def _canonical_revision(self) -> tuple[UUID | None, str | None]:
        try:
            return CanonicalJobTaxonomy(self.db).get_active_revision().id, None
        except CanonicalReadError as exc:
            return None, exc.code

    def _skill_revision(self) -> tuple[UUID | None, str | None]:
        try:
            return SkillGovernanceReader(self.db).get_active_revision().id, None
        except SkillGovernanceReadError as exc:
            return None, exc.code

    def _industry_revision(self) -> tuple[UUID | None, str | None]:
        try:
            return CompanyIndustry(self.db).get_active_revision().id, None
        except CompanyIndustryReadError as exc:
            return None, exc.code

    def _pending_metrics(
        self,
        model,
        *,
        status: str,
        timestamp_column,
        revision_criterion,
    ) -> tuple[int, datetime | None]:
        count, oldest = (
            self.db.query(func.count(model.id), func.min(timestamp_column))
            .filter(model.status == status, revision_criterion)
            .one()
        )
        return int(count or 0), oldest

    def _coverage(
        self,
        *,
        canonical_revision_id: UUID | None,
        skill_revision_id: UUID | None,
        industry_revision_id: UUID | None,
    ) -> JobIntelligenceCoverageView:
        total_jobs = self._count_current_jobs()
        total_companies = self._count_current_companies()
        canonical_assignments = self._distinct_job_count(
            JobTaxonomyAssignment,
            JobTaxonomyAssignment.job_id,
            JobTaxonomyAssignment.is_current.is_(True),
            *(
                (JobTaxonomyAssignment.taxonomy_revision_id == canonical_revision_id,)
                if canonical_revision_id is not None
                else (False,)
            ),
        )
        current_canonical_assignment_exists = (
            self.db.query(JobTaxonomyAssignment.id)
            .filter(
                JobTaxonomyAssignment.job_id == JobTaxonomyReviewItem.job_id,
                JobTaxonomyAssignment.is_current.is_(True),
                *(
                    (
                        JobTaxonomyAssignment.taxonomy_revision_id
                        == canonical_revision_id,
                    )
                    if canonical_revision_id is not None
                    else (False,)
                ),
            )
            .exists()
        )
        canonical_unassigned_jobs = self._distinct_job_count(
            JobTaxonomyReviewItem,
            JobTaxonomyReviewItem.job_id,
            JobTaxonomyReviewItem.status == "active",
            *(
                (JobTaxonomyReviewItem.taxonomy_revision_id == canonical_revision_id,)
                if canonical_revision_id is not None
                else (False,)
            ),
            ~current_canonical_assignment_exists,
        )
        canonical_unknown_jobs = max(
            total_jobs - canonical_assignments - canonical_unassigned_jobs,
            0,
        )
        governed_skill_jobs = self._distinct_job_count(
            GovernedJobSkill,
            GovernedJobSkill.job_id,
            *(
                (GovernedJobSkill.taxonomy_revision_id == skill_revision_id,)
                if skill_revision_id is not None
                else (False,)
            ),
        )
        unreviewed_skill_jobs = self._distinct_job_count(
            GovernedJobSkillMention,
            GovernedJobSkillMention.job_id,
            GovernedJobSkillMention.status == "active",
            GovernedJobSkillMention.resolution == "review_candidate",
            *(
                (GovernedJobSkillMention.taxonomy_revision_id == skill_revision_id,)
                if skill_revision_id is not None
                else (False,)
            ),
        )
        industry_companies = self._distinct_company_count(
            CompanyIndustryAssignment,
            CompanyIndustryAssignment.company_id,
            CompanyIndustryAssignment.status == "active",
            *(
                (
                    CompanyIndustryAssignment.taxonomy_revision_id
                    == industry_revision_id,
                )
                if industry_revision_id is not None
                else (False,)
            ),
        )
        return JobIntelligenceCoverageView(
            total_jobs=total_jobs,
            jobs_with_source_classification_paths=self._distinct_job_count(
                JobSourceClassificationPath,
                JobSourceClassificationPath.job_id,
            ),
            jobs_with_employment_types=self._distinct_job_count(
                JobEmploymentType,
                JobEmploymentType.job_id,
            ),
            jobs_with_canonical_assignment=canonical_assignments,
            jobs_without_canonical_assignment=max(
                total_jobs - canonical_assignments,
                0,
            ),
            jobs_with_unassigned_canonical_state=canonical_unassigned_jobs,
            jobs_with_unknown_canonical_state=canonical_unknown_jobs,
            canonical_unassigned_reasons=self._canonical_unassigned_reasons(
                canonical_revision_id
            ),
            jobs_with_governed_skills=governed_skill_jobs,
            jobs_with_unreviewed_skill_mentions=unreviewed_skill_jobs,
            total_companies=total_companies,
            companies_with_governed_industries=industry_companies,
            companies_without_governed_industries=max(
                total_companies - industry_companies,
                0,
            ),
        )

    def _count_current_jobs(self) -> int:
        return int(
            self.db.query(func.count(Job.id)).filter(Job.is_deleted.is_(False)).scalar()
            or 0
        )

    def _count_current_companies(self) -> int:
        return int(
            self.db.query(func.count(Company.id))
            .filter(Company.is_deleted.is_(False))
            .scalar()
            or 0
        )

    def _distinct_job_count(self, model, identifier_column, *criteria) -> int:
        return int(
            self.db.query(func.count(func.distinct(identifier_column)))
            .select_from(model)
            .join(Job, Job.id == identifier_column)
            .filter(Job.is_deleted.is_(False), *criteria)
            .scalar()
            or 0
        )

    def _distinct_company_count(self, model, identifier_column, *criteria) -> int:
        return int(
            self.db.query(func.count(func.distinct(identifier_column)))
            .select_from(model)
            .join(Company, Company.id == identifier_column)
            .filter(Company.is_deleted.is_(False), *criteria)
            .scalar()
            or 0
        )

    def _canonical_unassigned_reasons(
        self,
        canonical_revision_id: UUID | None,
    ) -> dict[str, int]:
        rows = (
            self.db.query(JobTaxonomyReviewItem.reasons)
            .join(Job, Job.id == JobTaxonomyReviewItem.job_id)
            .filter(
                JobTaxonomyReviewItem.status == "active",
                *(
                    (
                        JobTaxonomyReviewItem.taxonomy_revision_id
                        == canonical_revision_id,
                    )
                    if canonical_revision_id is not None
                    else (False,)
                ),
                Job.is_deleted.is_(False),
            )
            .all()
        )
        counts: Counter[str] = Counter()
        for (reasons,) in rows:
            counts.update(str(reason) for reason in (reasons or ()))
        return dict(sorted(counts.items()))


__all__ = [
    "GovernanceAreaSummaryView",
    "JobIntelligenceDomainAvailabilityView",
    "JobIntelligenceCoverageView",
    "JobIntelligenceGovernanceSummaryView",
    "JobIntelligenceJobDetailView",
    "JobIntelligenceProductReadModel",
]
